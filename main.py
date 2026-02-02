import asyncio
import json
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from bson import ObjectId
import pymongo.errors

import database
from database import connect_db, close_db
from redis_manager import redis_manager
from models import (
    ProductCreate, Product,
    ProductTagCreate, ProductTag,
    OrderCreate, Order, OrderItem,
    CategoryCreate, Category,
    FeedbackCreate, Feedback,
    PromoCodeCreate, PromoCode,
    ModifierGroupCreate, ModifierGroup,
    ComboCreate, Combo,
    MenuItemCreate, MenuItem,
    Stats
)
from config import (
    CHANNEL_ORDERS_NEW, CHANNEL_STATS_UPDATE, REDIS_CHANNELS,
    RESTAURANT_NAME, RESTAURANT_ADDRESS, RESTAURANT_PHONE, RESTAURANT_HOURS,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
)
from telegram_bot import send_order_notification


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        connect_db()
        await redis_manager.connect()
        init_default_data()
    except Exception as e:
        print(f"Startup error: {e}")
    yield
    # Shutdown
    close_db()
    await redis_manager.close()


app = FastAPI(title="POS", lifespan=lifespan)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def init_default_data():
    """Initialize default categories if empty"""
    if not database.connected or database.categories is None:
        return
    if database.categories.count_documents({}) == 0:
        default_categories = [
            {"name": "Популярне", "icon": "star", "sort_order": 0},
            {"name": "Кава", "icon": "coffee", "sort_order": 1},
            {"name": "Напої", "icon": "cup", "sort_order": 2},
            {"name": "Сніданки", "icon": "sun", "sort_order": 3},
            {"name": "Сендвічі", "icon": "sandwich", "sort_order": 4},
            {"name": "Салати", "icon": "leaf", "sort_order": 5},
            {"name": "Паста", "icon": "bowl", "sort_order": 6},
            {"name": "Бургери", "icon": "burger", "sort_order": 7},
            {"name": "Піца", "icon": "pizza", "sort_order": 8},
            {"name": "Десерти", "icon": "cake", "sort_order": 9},
        ]
        database.categories.insert_many(default_categories)
        print("Default categories created")


def serialize_doc(doc):
    """Convert MongoDB document to dict with string _id"""
    if doc:
        doc["_id"] = str(doc["_id"])
        if "category_id" in doc and doc["category_id"]:
            doc["category_id"] = str(doc["category_id"])
        if "created_at" in doc and isinstance(doc["created_at"], datetime):
            doc["created_at"] = doc["created_at"].isoformat()
    return doc


def serialize_docs(docs):
    """Convert list of MongoDB documents"""
    return [serialize_doc(doc) for doc in docs]


def log_action(action: str, entity_type: str, entity_id: str, entity_name: str, changes: dict = None):
    """Log an action to the audit log"""
    if not database.connected or database.audit_logs is None:
        return  # Skip logging in demo mode

    try:
        database.audit_logs.insert_one({
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "entity_name": entity_name,
            "changes": changes or {},
            "created_at": datetime.utcnow()
        })
    except Exception as e:
        print(f"Error logging action: {e}")


# Demo data when DB is not connected
DEMO_CATEGORIES = [
    {"_id": "1", "name": "Кава", "icon": "coffee", "sort_order": 1},
    {"_id": "2", "name": "Напої", "icon": "cup", "sort_order": 2},
    {"_id": "3", "name": "Десерти", "icon": "cake", "sort_order": 3},
]

DEMO_PRODUCTS = [
    {"_id": "1", "name": "Капучіно", "category_id": "1", "price": 65, "description": "Класичний капучіно", "image": "/static/img/placeholder.svg", "weight": "250 мл", "cook_time": "5 хв", "available": True},
    {"_id": "2", "name": "Лате", "category_id": "1", "price": 70, "description": "Ніжний лате", "image": "/static/img/placeholder.svg", "weight": "300 мл", "cook_time": "5 хв", "available": True},
    {"_id": "3", "name": "Американо", "category_id": "1", "price": 50, "description": "Класичний американо", "image": "/static/img/placeholder.svg", "weight": "200 мл", "cook_time": "3 хв", "available": True},
    {"_id": "4", "name": "Лимонад", "category_id": "2", "price": 55, "description": "Домашній лимонад", "image": "/static/img/placeholder.svg", "weight": "400 мл", "cook_time": "2 хв", "available": True},
    {"_id": "5", "name": "Чізкейк", "category_id": "3", "price": 95, "description": "Ніжний чізкейк", "image": "/static/img/placeholder.svg", "weight": "150 г", "cook_time": "-", "available": True},
]


def get_categories_list():
    """Get categories from DB or demo data"""
    if database.connected and database.categories is not None:
        return serialize_docs(database.categories.find().sort("sort_order", 1))
    return DEMO_CATEGORIES


def get_products_list(available_only=False):
    """Get products from DB or demo data"""
    if database.connected and database.products is not None:
        query = {"available": True} if available_only else {}
        return serialize_docs(database.products.find(query))
    if available_only:
        return [p for p in DEMO_PRODUCTS if p.get("available", True)]
    return DEMO_PRODUCTS


# Demo data for menu items
DEMO_MENU_ITEMS = []


def get_menu_items_list(active_only=True):
    """Get menu items with product/combo data (for POS/customer menu)"""
    if not database.connected or database.menu_items is None:
        # Demo mode - return all available products as menu items
        if DEMO_MENU_ITEMS:
            return DEMO_MENU_ITEMS
        return get_products_list(available_only=active_only)

    # Get menu items
    query = {"is_active": True} if active_only else {}
    menu_items = list(database.menu_items.find(query).sort("sort_order", 1))

    if not menu_items:
        return []

    # Separate product and combo IDs
    product_ids = []
    combo_ids = []
    for item in menu_items:
        item_type = item.get("item_type", "product")
        if item_type == "combo" and item.get("combo_id"):
            combo_ids.append(ObjectId(item["combo_id"]))
        elif item.get("product_id"):
            product_ids.append(ObjectId(item["product_id"]))

    # Fetch products
    products_map = {}
    if product_ids:
        products_map = {
            str(p["_id"]): p
            for p in database.products.find({"_id": {"$in": product_ids}})
        }

    # Fetch combos
    combos_map = {}
    if combo_ids and database.combos is not None:
        combos_map = {
            str(c["_id"]): c
            for c in database.combos.find({"_id": {"$in": combo_ids}})
        }

    # Merge menu item data with product/combo data
    result = []
    for item in menu_items:
        item_type = item.get("item_type", "product")

        if item_type == "combo":
            combo = combos_map.get(item.get("combo_id"))
            if not combo:
                continue  # Skip orphaned menu items

            merged = serialize_doc(combo.copy())
            merged["menu_item_id"] = str(item["_id"])
            merged["is_active"] = item.get("is_active", True)
            merged["sort_order"] = item.get("sort_order", 0)
            merged["item_type"] = "combo"
            merged["price"] = combo.get("combo_price", 0)  # Use combo_price as display price
            merged["savings"] = combo.get("regular_price", 0) - combo.get("combo_price", 0)
            # Use menu item's category_id if set, otherwise None for combos
            if item.get("category_id"):
                merged["category_id"] = item["category_id"]
            result.append(merged)
        else:
            product = products_map.get(item.get("product_id"))
            if not product:
                continue  # Skip orphaned menu items

            merged = serialize_doc(product.copy())
            merged["menu_item_id"] = str(item["_id"])
            merged["is_active"] = item.get("is_active", True)
            merged["sort_order"] = item.get("sort_order", 0)
            merged["item_type"] = "product"
            # Use menu item's category_id if set, otherwise keep product's category_id
            if item.get("category_id"):
                merged["category_id"] = item["category_id"]
            result.append(merged)

    return result


# ============ Exception Handlers ============

@app.exception_handler(pymongo.errors.ServerSelectionTimeoutError)
async def mongodb_timeout_handler(request: Request, exc: Exception):
    error_html = """
    <html>
        <head><title>Database Error</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px;">
            <h1>503 - Database Unavailable</h1>
            <p>Could not connect to MongoDB. Please check your connection.</p>
        </body>
    </html>
    """
    return HTMLResponse(content=error_html, status_code=503)


# ============ Page Routes ============

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "restaurant_name": RESTAURANT_NAME
    })


@app.get("/menu", response_class=HTMLResponse)
async def menu_page(request: Request):
    cats = get_categories_list()
    # Use menu items if available, fallback to products
    prods = get_menu_items_list(active_only=True)
    if not prods:
        prods = get_products_list(available_only=True)
    return templates.TemplateResponse("menu.html", {
        "request": request,
        "categories": cats,
        "products": prods,
        "restaurant_name": RESTAURANT_NAME,
        "restaurant_address": RESTAURANT_ADDRESS,
        "restaurant_phone": RESTAURANT_PHONE,
        "restaurant_hours": RESTAURANT_HOURS
    })


@app.get("/pos", response_class=HTMLResponse)
async def pos_page(request: Request):
    cats = get_categories_list()
    # Use menu items if available, fallback to products
    prods = get_menu_items_list(active_only=True)
    if not prods:
        prods = get_products_list(available_only=True)
    return templates.TemplateResponse("pos.html", {
        "request": request,
        "categories": cats,
        "products": prods
    })


@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders_page(request: Request):
    return templates.TemplateResponse("admin/orders.html", {"request": request})


@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products_page(request: Request):
    """Redirect to assortment page"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/assortment", status_code=302)


@app.get("/admin/assortment", response_class=HTMLResponse)
async def admin_assortment_page(request: Request):
    """Assortment management page (all products catalog)"""
    cats = get_categories_list()
    return templates.TemplateResponse("admin/assortment.html", {
        "request": request,
        "categories": cats
    })


@app.get("/admin/menu", response_class=HTMLResponse)
async def admin_menu_page(request: Request):
    """Menu management page (active menu items)"""
    cats = get_categories_list()
    return templates.TemplateResponse("admin/menu.html", {
        "request": request,
        "categories": cats
    })


@app.get("/admin/categories", response_class=HTMLResponse)
async def admin_categories_page(request: Request):
    return templates.TemplateResponse("admin/categories.html", {"request": request})


@app.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats_page(request: Request):
    return templates.TemplateResponse("admin/stats.html", {"request": request})


@app.get("/admin/production", response_class=HTMLResponse)
async def admin_production_page(request: Request):
    categories = get_categories_list()
    return templates.TemplateResponse("admin/production.html", {"request": request, "categories": categories})


@app.get("/admin/tags", response_class=HTMLResponse)
async def admin_tags_page(request: Request):
    return templates.TemplateResponse("admin/tags.html", {"request": request})


@app.get("/admin/projects", response_class=HTMLResponse)
async def admin_projects_page(request: Request):
    return templates.TemplateResponse("admin/projects.html", {"request": request})


@app.get("/admin/audit-logs", response_class=HTMLResponse)
async def admin_audit_logs_page(request: Request):
    return templates.TemplateResponse("admin/audit_logs.html", {"request": request})


# ============ API: Categories ============

@app.get("/api/categories")
async def get_categories():
    return get_categories_list()


@app.post("/api/categories")
async def create_category(data: CategoryCreate):
    if not database.connected or database.categories is None:
        raise HTTPException(status_code=503, detail="Database not connected")
    result = database.categories.insert_one(data.model_dump())
    return {"_id": str(result.inserted_id), **data.model_dump()}


@app.delete("/api/categories/{category_id}")
async def delete_category(category_id: str):
    if not database.connected or database.categories is None:
        raise HTTPException(status_code=503, detail="Database not connected")
    result = database.categories.delete_one({"_id": ObjectId(category_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"status": "deleted"}


# ============ API: Product Tags ============

@app.get("/api/product-tags")
async def get_product_tags():
    """Get all product tags"""
    if not database.connected or database.product_tags is None:
        return []
    return serialize_docs(database.product_tags.find().sort("name", 1))


@app.post("/api/product-tags")
async def create_product_tag(data: ProductTagCreate):
    """Create a new product tag"""
    if not database.connected or database.product_tags is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Check if tag with same name already exists
    existing = database.product_tags.find_one({"name": data.name})
    if existing:
        raise HTTPException(status_code=400, detail="Тег з такою назвою вже існує")

    tag_doc = data.model_dump()
    result = database.product_tags.insert_one(tag_doc)
    tag_doc["_id"] = str(result.inserted_id)
    return tag_doc


@app.put("/api/product-tags/{tag_id}")
async def update_product_tag(tag_id: str, data: ProductTagCreate):
    """Update a product tag"""
    if not database.connected or database.product_tags is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Check if another tag with same name exists
    existing = database.product_tags.find_one({"name": data.name, "_id": {"$ne": ObjectId(tag_id)}})
    if existing:
        raise HTTPException(status_code=400, detail="Тег з такою назвою вже існує")

    result = database.product_tags.update_one(
        {"_id": ObjectId(tag_id)},
        {"$set": data.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Tag not found")

    updated = database.product_tags.find_one({"_id": ObjectId(tag_id)})
    return serialize_doc(updated)


@app.delete("/api/product-tags/{tag_id}")
async def delete_product_tag(tag_id: str):
    """Delete a product tag"""
    if not database.connected or database.product_tags is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Remove tag from all products that have it
    database.products.update_many(
        {"tags": tag_id},
        {"$pull": {"tags": tag_id}}
    )

    result = database.product_tags.delete_one({"_id": ObjectId(tag_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"status": "deleted"}


# ============ API: Audit Logs ============

@app.get("/api/audit-logs")
async def get_audit_logs(entity_type: str = None, limit: int = 100):
    """Get audit logs with optional filtering"""
    if not database.connected or database.audit_logs is None:
        return []

    query = {}
    if entity_type:
        query["entity_type"] = entity_type

    logs = list(database.audit_logs.find(query).sort("created_at", -1).limit(limit))
    return serialize_docs(logs)


@app.get("/api/audit-logs/entity/{entity_type}/{entity_id}")
async def get_entity_audit_logs(entity_type: str, entity_id: str):
    """Get audit logs for a specific entity"""
    if not database.connected or database.audit_logs is None:
        return []

    logs = list(database.audit_logs.find({
        "entity_type": entity_type,
        "entity_id": entity_id
    }).sort("created_at", -1))
    return serialize_docs(logs)


# ============ API: Projects ============

@app.get("/api/projects")
async def get_projects():
    """Get all projects"""
    if not database.connected or database.projects is None:
        return []

    projects = list(database.projects.find().sort("name", 1))
    return serialize_docs(projects)


@app.post("/api/projects")
async def create_project(data: dict):
    """Create a new project"""
    if not database.connected or database.projects is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    doc = {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "is_active": data.get("is_active", True),
        "created_at": datetime.utcnow()
    }
    result = database.projects.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    log_action("create", "project", str(result.inserted_id), doc["name"])
    return doc


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, data: dict):
    """Update a project"""
    if not database.connected or database.projects is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    update_data = {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "is_active": data.get("is_active", True)
    }

    result = database.projects.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")

    log_action("update", "project", project_id, update_data["name"])
    return {"status": "updated"}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project"""
    if not database.connected or database.projects is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    project = database.projects.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Remove project_id from all products
    database.products.update_many(
        {"project_id": project_id},
        {"$unset": {"project_id": ""}}
    )

    database.projects.delete_one({"_id": ObjectId(project_id)})
    log_action("delete", "project", project_id, project.get("name", ""))
    return {"status": "deleted"}


# ============ API: Products ============

@app.get("/api/products")
async def get_products(category_id: str = None, available: bool = None):
    if not database.connected or database.products is None:
        result = DEMO_PRODUCTS
        if category_id:
            result = [p for p in result if p["category_id"] == category_id]
        if available is not None:
            result = [p for p in result if p.get("available") == available]
        return result
    query = {}
    if category_id:
        query["category_id"] = category_id
    if available is not None:
        query["available"] = available
    return serialize_docs(database.products.find(query))


@app.post("/api/products")
async def create_product(data: ProductCreate):
    if not database.connected or database.products is None:
        raise HTTPException(status_code=503, detail="Database not connected")
    doc = data.model_dump()
    doc["created_at"] = datetime.utcnow()
    result = database.products.insert_one(doc)

    log_action("create", "product", str(result.inserted_id), data.name)
    return {"_id": str(result.inserted_id), **doc}


@app.put("/api/products/{product_id}")
async def update_product(product_id: str, data: ProductCreate):
    if not database.connected or database.products is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    # Get old product for change tracking
    old_product = database.products.find_one({"_id": ObjectId(product_id)})

    result = database.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": data.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")

    # Track changes
    if old_product:
        changes = {}
        new_data = data.model_dump()
        for key, new_val in new_data.items():
            old_val = old_product.get(key)
            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}
        if changes:
            log_action("update", "product", product_id, data.name, changes)

    return {"status": "updated"}


@app.delete("/api/products/{product_id}")
async def delete_product(product_id: str):
    if not database.connected or database.products is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    product = database.products.find_one({"_id": ObjectId(product_id)})
    result = database.products.delete_one({"_id": ObjectId(product_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")

    if product:
        log_action("delete", "product", product_id, product.get("name", ""))

    return {"status": "deleted"}


@app.post("/api/products/{product_id}/copy")
async def copy_product(product_id: str):
    """Copy a product with a new ID"""
    if not database.connected or database.products is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    product = database.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    original_name = product.get("name", "")

    # Create copy
    del product["_id"]
    product["name"] = f"{original_name} (копія)"
    product["created_at"] = datetime.utcnow()

    result = database.products.insert_one(product)
    product["_id"] = str(result.inserted_id)

    log_action("copy", "product", str(result.inserted_id), product["name"],
               {"copied_from": {"id": product_id, "name": original_name}})

    return serialize_doc(product)


# ============ API: Orders ============

DEMO_ORDERS = []
demo_order_counter = 0


def generate_order_number():
    """Generate unique order number"""
    global demo_order_counter
    today = datetime.utcnow().strftime("%Y%m%d")
    if database.connected and database.orders is not None:
        count = database.orders.count_documents({
            "created_at": {"$gte": datetime.utcnow().replace(hour=0, minute=0, second=0)}
        })
    else:
        demo_order_counter += 1
        count = demo_order_counter
    return f"ORD-{today}-{count:03d}"


@app.get("/api/orders")
async def get_orders(status: str = None, limit: int = 50):
    if not database.connected or database.orders is None:
        result = DEMO_ORDERS
        if status:
            result = [o for o in result if o["status"] == status]
        return result[:limit]
    query = {}
    if status:
        query["status"] = status
    return serialize_docs(
        database.orders.find(query).sort("created_at", -1).limit(limit)
    )


@app.post("/api/orders")
async def create_order(data: OrderCreate):
    subtotal = sum(item.price * item.qty for item in data.items)
    discount_amount = 0
    promo_code_used = None

    # Validate minimum order amount for delivery
    if data.order_type == "delivery":
        delivery_settings = runtime_settings.get("delivery", {})
        if delivery_settings.get("enabled", False):
            # Determine which minimum to use based on delivery zone
            if data.delivery_zone == "out_of_city":
                min_amount = delivery_settings.get("min_order_amount_out_of_city", 0)
            else:
                min_amount = delivery_settings.get("min_order_amount", 0)

            if min_amount > 0 and subtotal < min_amount:
                message = delivery_settings.get("min_order_message", "Мінімальна сума для доставки: {amount} грн")
                raise HTTPException(
                    status_code=400,
                    detail=message.replace("{amount}", str(min_amount))
                )

    # Apply promo code if provided
    if data.promo_code:
        promo_result = validate_promo_code(data.promo_code, subtotal)
        if promo_result["valid"]:
            promo = promo_result["promo"]
            discount_amount = calculate_discount(promo, subtotal)
            promo_code_used = promo["code"]

            # Increment usage count
            if database.connected and database.promo_codes is not None:
                database.promo_codes.update_one(
                    {"code": promo["code"]},
                    {"$inc": {"usage_count": 1}}
                )

    total = subtotal - discount_amount

    order_doc = {
        "order_number": generate_order_number(),
        "items": [item.model_dump() for item in data.items],
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "promo_code": promo_code_used,
        "total": total,
        "status": "new",
        "payment_status": "pending",
        "order_type": data.order_type,
        "table_number": data.table_number,
        "customer_name": data.customer_name,
        "customer_phone": data.customer_phone,
        "delivery_zone": data.delivery_zone,
        "notes": data.notes,
        "created_at": datetime.utcnow().isoformat()
    }

    if not database.connected or database.orders is None:
        order_doc["_id"] = str(len(DEMO_ORDERS) + 1)
        DEMO_ORDERS.insert(0, order_doc)
    else:
        order_doc["created_at"] = datetime.utcnow()
        result = database.orders.insert_one(order_doc)
        order_doc["_id"] = str(result.inserted_id)
        order_doc["created_at"] = order_doc["created_at"].isoformat()

    # Publish to Redis (if connected)
    try:
        await redis_manager.publish(CHANNEL_ORDERS_NEW, {
            "type": "new_order",
            "order": order_doc
        })
    except Exception:
        pass

    # Send Telegram notification
    try:
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            await send_order_notification(order_doc)
    except Exception as e:
        print(f"Telegram notification error: {e}")

    return order_doc


@app.put("/api/orders/{order_id}/status")
async def update_order_status(order_id: str, status: str):
    valid_statuses = ["new", "preparing", "ready", "completed", "cancelled"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    if not database.connected or database.orders is None:
        for order in DEMO_ORDERS:
            if order["_id"] == order_id:
                order["status"] = status
                break
    else:
        result = database.orders.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"status": status}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Order not found")

    # Publish update
    try:
        await redis_manager.publish(CHANNEL_ORDERS_NEW, {
            "type": "order_updated",
            "order_id": order_id,
            "status": status
        })
    except Exception:
        pass

    return {"status": "updated"}


@app.put("/api/orders/{order_id}/payment")
async def update_payment_status(order_id: str, payment_status: str):
    if payment_status not in ["pending", "paid"]:
        raise HTTPException(status_code=400, detail="Invalid payment status")

    if not database.connected or database.orders is None:
        for order in DEMO_ORDERS:
            if order["_id"] == order_id:
                order["payment_status"] = payment_status
                break
    else:
        result = database.orders.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"payment_status": payment_status}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Order not found")
    return {"status": "updated"}


# ============ API: Production Status ============

@app.get("/api/production-status")
async def get_production_status(category_id: str = None):
    """Get production status for today - sold vs planned for products with daily norms"""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    if not database.connected or database.products is None or database.orders is None:
        return {"products": []}

    # Get all products with daily_production_norm set
    query = {"daily_production_norm": {"$exists": True, "$ne": None, "$gt": 0}}
    if category_id:
        query["category_id"] = category_id

    products_with_norms = list(database.products.find(query))

    if not products_with_norms:
        return {"products": []}

    # Get today's completed orders (not cancelled)
    orders_query = {
        "created_at": {"$gte": today_start},
        "status": {"$ne": "cancelled"}
    }

    # Aggregate sold quantities by product_id
    pipeline = [
        {"$match": orders_query},
        {"$unwind": "$items"},
        {"$group": {
            "_id": "$items.product_id",
            "sold_qty": {"$sum": "$items.qty"}
        }}
    ]

    sold_aggregation = list(database.orders.aggregate(pipeline))
    sold_map = {item["_id"]: item["sold_qty"] for item in sold_aggregation}

    # Build response
    result = []
    for product in products_with_norms:
        product_id = str(product["_id"])
        norm = product.get("daily_production_norm", 0)
        sold_today = sold_map.get(product_id, 0)
        percentage = round((sold_today / norm * 100), 1) if norm > 0 else 0

        result.append({
            "_id": product_id,
            "name": product["name"],
            "category_id": product.get("category_id"),
            "sold_today": sold_today,
            "norm": norm,
            "percentage": percentage,
            "remaining": max(0, norm - sold_today)
        })

    # Sort by percentage descending (products closer to norm first)
    result.sort(key=lambda x: x["percentage"], reverse=True)

    return {"products": result}


# ============ API: Stats ============

@app.get("/api/stats")
async def get_stats(
    date_from: str = None,
    date_to: str = None,
    tags: str = None,
    alcohol: str = "all"
):
    """Get statistics with optional date range and product filters.

    Args:
        date_from: Start date in YYYY-MM-DD format (defaults to 7 days ago)
        date_to: End date in YYYY-MM-DD format (defaults to today)
        tags: Comma-separated list of tag IDs to filter by
        alcohol: Filter by alcohol status: 'all', 'alcohol', 'non_alcohol'
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Parse date range
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            start_date = today_start - timedelta(days=7)
    else:
        start_date = today_start - timedelta(days=7)

    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            end_date = datetime.utcnow()
    else:
        end_date = datetime.utcnow()

    # Calculate number of days in range
    days_in_range = (end_date - start_date).days + 1

    if not database.connected or database.orders is None:
        # Demo stats
        today_revenue = sum(o.get("total", 0) for o in DEMO_ORDERS if o.get("status") != "cancelled")
        pending = len([o for o in DEMO_ORDERS if o["status"] in ["new", "preparing"]])
        completed = len([o for o in DEMO_ORDERS if o["status"] == "completed"])

        daily_stats = []
        for i in range(min(days_in_range, 30) - 1, -1, -1):
            day = start_date + timedelta(days=i)
            daily_stats.append({
                "date": day.strftime("%d.%m"),
                "orders_count": len(DEMO_ORDERS) if i == 0 else 0,
                "revenue": today_revenue if i == 0 else 0
            })

        return {
            "today_orders": len(DEMO_ORDERS),
            "today_revenue": today_revenue,
            "pending_orders": pending,
            "completed_orders": completed,
            "top_products": [],
            "daily_stats": daily_stats,
            "revenue_by_type": {"dine_in": today_revenue, "takeaway": 0, "delivery": 0},
            "hourly_distribution": []
        }

    # Today's stats (always show today regardless of filter)
    today_orders = list(database.orders.find({"created_at": {"$gte": today_start}}))
    today_revenue = sum(o.get("total", 0) for o in today_orders if o.get("status") != "cancelled")

    # Pending orders (always current)
    pending = database.orders.count_documents({"status": {"$in": ["new", "preparing"]}})
    completed = database.orders.count_documents({"status": "completed", "created_at": {"$gte": today_start}})

    # Get filtered product IDs if tags or alcohol filter is applied
    filtered_product_ids = None
    if tags or alcohol != "all":
        product_filter = {}
        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            if tag_list:
                product_filter["tags"] = {"$in": tag_list}
        if alcohol == "alcohol":
            product_filter["is_alcohol"] = True
        elif alcohol == "non_alcohol":
            product_filter["is_alcohol"] = {"$ne": True}

        if product_filter and database.products is not None:
            filtered_products = list(database.products.find(product_filter, {"_id": 1}))
            filtered_product_ids = [str(p["_id"]) for p in filtered_products]

    # Top products for selected date range
    pipeline_match = {"created_at": {"$gte": start_date, "$lte": end_date}, "status": {"$ne": "cancelled"}}
    pipeline = [
        {"$match": pipeline_match},
        {"$unwind": "$items"},
    ]

    # Add filter for specific products if filtering is active
    if filtered_product_ids is not None:
        pipeline.append({"$match": {"items.product_id": {"$in": filtered_product_ids}}})

    pipeline.extend([
        {"$group": {
            "_id": "$items.name",
            "product_id": {"$first": "$items.product_id"},
            "count": {"$sum": "$items.qty"},
            "revenue": {"$sum": {"$multiply": ["$items.qty", "$items.price"]}}
        }},
        {"$sort": {"revenue": -1}},
        {"$limit": 50}  # Increased limit for filtered results
    ])
    top_products = list(database.orders.aggregate(pipeline))

    # Revenue by order type for selected date range
    type_pipeline = [
        {"$match": {"created_at": {"$gte": start_date, "$lte": end_date}, "status": {"$ne": "cancelled"}}},
        {"$group": {"_id": "$order_type", "revenue": {"$sum": "$total"}, "count": {"$sum": 1}}}
    ]
    type_results = list(database.orders.aggregate(type_pipeline))
    revenue_by_type = {
        "dine_in": {"revenue": 0, "count": 0},
        "takeaway": {"revenue": 0, "count": 0},
        "delivery": {"revenue": 0, "count": 0}
    }
    for r in type_results:
        if r["_id"] in revenue_by_type:
            revenue_by_type[r["_id"]] = {"revenue": r["revenue"], "count": r["count"]}

    # Hourly distribution for selected date range
    hourly_pipeline = [
        {"$match": {"created_at": {"$gte": start_date, "$lte": end_date}, "status": {"$ne": "cancelled"}}},
        {"$project": {"hour": {"$hour": "$created_at"}, "total": 1}},
        {"$group": {"_id": "$hour", "orders": {"$sum": 1}, "revenue": {"$sum": "$total"}}},
        {"$sort": {"_id": 1}}
    ]
    hourly_results = list(database.orders.aggregate(hourly_pipeline))
    hourly_distribution = [{"hour": r["_id"], "orders": r["orders"], "revenue": r["revenue"]} for r in hourly_results]

    # Daily stats for selected date range (max 30 days)
    daily_stats = []
    for i in range(min(days_in_range, 30)):
        day = start_date + timedelta(days=i)
        next_day = day + timedelta(days=1)
        day_orders = list(database.orders.find({
            "created_at": {"$gte": day, "$lt": next_day},
            "status": {"$ne": "cancelled"}
        }))
        daily_stats.append({
            "date": day.strftime("%d.%m"),
            "orders_count": len(day_orders),
            "revenue": sum(o.get("total", 0) for o in day_orders)
        })

    # Period totals
    period_orders = list(database.orders.find({
        "created_at": {"$gte": start_date, "$lte": end_date},
        "status": {"$ne": "cancelled"}
    }))
    period_revenue = sum(o.get("total", 0) for o in period_orders)

    return {
        "today_orders": len(today_orders),
        "today_revenue": today_revenue,
        "pending_orders": pending,
        "completed_orders": completed,
        "period_orders": len(period_orders),
        "period_revenue": period_revenue,
        "top_products": top_products,
        "daily_stats": daily_stats,
        "revenue_by_type": revenue_by_type,
        "hourly_distribution": hourly_distribution
    }


@app.get("/api/stats/by-tag")
async def get_stats_by_tag(date_from: str = None, date_to: str = None):
    """Get statistics aggregated by product tags"""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Parse date range
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            start_date = today_start - timedelta(days=7)
    else:
        start_date = today_start - timedelta(days=7)

    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            end_date = datetime.utcnow()
    else:
        end_date = datetime.utcnow()

    if not database.connected or database.orders is None or database.products is None:
        return {"tags": []}

    # Get all tags
    all_tags = list(database.product_tags.find()) if database.product_tags else []
    tag_map = {str(t["_id"]): t["name"] for t in all_tags}

    # Get all products with their tags
    products = list(database.products.find({"tags": {"$exists": True, "$ne": []}}))
    product_tags_map = {str(p["_id"]): p.get("tags", []) for p in products}

    # Aggregate orders
    pipeline = [
        {"$match": {"created_at": {"$gte": start_date, "$lte": end_date}, "status": {"$ne": "cancelled"}}},
        {"$unwind": "$items"},
        {"$group": {
            "_id": "$items.product_id",
            "count": {"$sum": "$items.qty"},
            "revenue": {"$sum": {"$multiply": ["$items.qty", "$items.price"]}}
        }}
    ]
    product_stats = list(database.orders.aggregate(pipeline))

    # Aggregate by tag
    tag_stats = {}
    for stat in product_stats:
        product_id = stat["_id"]
        tags = product_tags_map.get(product_id, [])
        for tag_id in tags:
            if tag_id not in tag_stats:
                tag_stats[tag_id] = {"count": 0, "revenue": 0}
            tag_stats[tag_id]["count"] += stat["count"]
            tag_stats[tag_id]["revenue"] += stat["revenue"]

    # Build response
    result = []
    for tag_id, stats in tag_stats.items():
        tag_name = tag_map.get(tag_id, "Невідомий тег")
        result.append({
            "tag_id": tag_id,
            "tag_name": tag_name,
            "count": stats["count"],
            "revenue": stats["revenue"]
        })

    result.sort(key=lambda x: x["revenue"], reverse=True)
    return {"tags": result}


@app.get("/api/stats/by-product/{product_id}")
async def get_stats_by_product(product_id: str, date_from: str = None, date_to: str = None):
    """Get detailed statistics for a specific product"""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Parse date range
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            start_date = today_start - timedelta(days=30)
    else:
        start_date = today_start - timedelta(days=30)

    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            end_date = datetime.utcnow()
    else:
        end_date = datetime.utcnow()

    if not database.connected or database.orders is None or database.products is None:
        return {"product": None, "stats": {}}

    # Get product info
    product = database.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get orders containing this product
    pipeline = [
        {"$match": {"created_at": {"$gte": start_date, "$lte": end_date}, "status": {"$ne": "cancelled"}}},
        {"$unwind": "$items"},
        {"$match": {"items.product_id": product_id}},
        {"$group": {
            "_id": None,
            "total_qty": {"$sum": "$items.qty"},
            "total_revenue": {"$sum": {"$multiply": ["$items.qty", "$items.price"]}},
            "order_count": {"$sum": 1}
        }}
    ]
    stats_result = list(database.orders.aggregate(pipeline))
    stats = stats_result[0] if stats_result else {"total_qty": 0, "total_revenue": 0, "order_count": 0}

    # Daily breakdown
    days_in_range = (end_date - start_date).days + 1
    daily_stats = []
    for i in range(min(days_in_range, 30)):
        day = start_date + timedelta(days=i)
        next_day = day + timedelta(days=1)
        day_pipeline = [
            {"$match": {"created_at": {"$gte": day, "$lt": next_day}, "status": {"$ne": "cancelled"}}},
            {"$unwind": "$items"},
            {"$match": {"items.product_id": product_id}},
            {"$group": {"_id": None, "qty": {"$sum": "$items.qty"}, "revenue": {"$sum": {"$multiply": ["$items.qty", "$items.price"]}}}}
        ]
        day_result = list(database.orders.aggregate(day_pipeline))
        day_stats = day_result[0] if day_result else {"qty": 0, "revenue": 0}
        daily_stats.append({
            "date": day.strftime("%d.%m"),
            "qty": day_stats.get("qty", 0),
            "revenue": day_stats.get("revenue", 0)
        })

    return {
        "product": serialize_doc(product),
        "stats": {
            "total_qty": stats.get("total_qty", 0),
            "total_revenue": stats.get("total_revenue", 0),
            "order_count": stats.get("order_count", 0)
        },
        "daily_stats": daily_stats
    }


# ============ API: Settings ============

# Runtime settings (loaded from DB or environment)
runtime_settings = {
    "telegram": {
        "bot_token": TELEGRAM_BOT_TOKEN,
        "chat_id": TELEGRAM_CHAT_ID
    },
    "restaurant": {
        "name": RESTAURANT_NAME,
        "address": RESTAURANT_ADDRESS,
        "phone": RESTAURANT_PHONE,
        "hours": RESTAURANT_HOURS
    },
    "delivery": {
        "min_order_amount": 0,
        "min_order_amount_out_of_city": 0,
        "min_order_message": "Мінімальна сума для доставки: {amount} грн",
        "enabled": False
    },
    "order_types": [
        {"type": "dine_in", "label": "В залі", "enabled": True, "sort_order": 0},
        {"type": "takeaway", "label": "З собою", "enabled": True, "sort_order": 1},
        {"type": "delivery", "label": "Доставка", "enabled": True, "sort_order": 2},
        {"type": "self_service", "label": "Самообслуговування", "enabled": True, "sort_order": 3}
    ]
}


@app.get("/api/settings")
async def get_settings():
    """Get all settings"""
    # Try to load from database
    if database.connected and database.settings is not None:
        db_settings = database.settings.find_one({"_id": "app_settings"})
        if db_settings:
            if db_settings.get("telegram"):
                runtime_settings["telegram"] = db_settings["telegram"]
            if db_settings.get("restaurant"):
                runtime_settings["restaurant"] = db_settings["restaurant"]
            if db_settings.get("delivery"):
                runtime_settings["delivery"] = db_settings["delivery"]
            if db_settings.get("order_types"):
                runtime_settings["order_types"] = db_settings["order_types"]

    return runtime_settings


@app.post("/api/settings/telegram")
async def save_telegram_settings(bot_token: str = "", chat_id: str = ""):
    """Save Telegram bot settings"""
    global runtime_settings

    runtime_settings["telegram"] = {
        "bot_token": bot_token,
        "chat_id": chat_id
    }

    if database.connected and database.settings is not None:
        database.settings.update_one(
            {"_id": "app_settings"},
            {"$set": {"telegram": runtime_settings["telegram"]}},
            upsert=True
        )

    return {"status": "saved"}


@app.post("/api/settings/telegram/test")
async def test_telegram():
    """Send a test Telegram message"""
    from telegram_bot import send_telegram_message

    settings = runtime_settings.get("telegram", {})
    if not settings.get("bot_token") or not settings.get("chat_id"):
        return {"success": False, "error": "Telegram не налаштовано"}

    # Temporarily override config
    import config
    original_token = config.TELEGRAM_BOT_TOKEN
    original_chat = config.TELEGRAM_CHAT_ID
    config.TELEGRAM_BOT_TOKEN = settings["bot_token"]
    config.TELEGRAM_CHAT_ID = settings["chat_id"]

    try:
        success = await send_telegram_message("Тестове повідомлення від POS системи!")
        return {"success": success, "error": None if success else "Не вдалося надіслати"}
    finally:
        config.TELEGRAM_BOT_TOKEN = original_token
        config.TELEGRAM_CHAT_ID = original_chat


@app.post("/api/settings/restaurant")
async def save_restaurant_settings(name: str = "", address: str = "", phone: str = "", hours: str = ""):
    """Save restaurant settings"""
    global runtime_settings

    runtime_settings["restaurant"] = {
        "name": name,
        "address": address,
        "phone": phone,
        "hours": hours
    }

    if database.connected and database.settings is not None:
        database.settings.update_one(
            {"_id": "app_settings"},
            {"$set": {"restaurant": runtime_settings["restaurant"]}},
            upsert=True
        )

    return {"status": "saved"}


@app.get("/api/settings/delivery")
async def get_delivery_settings():
    """Get delivery settings"""
    # Ensure we have the latest from DB
    if database.connected and database.settings is not None:
        db_settings = database.settings.find_one({"_id": "app_settings"})
        if db_settings and db_settings.get("delivery"):
            runtime_settings["delivery"] = db_settings["delivery"]
    return runtime_settings.get("delivery", {})


@app.post("/api/settings/delivery")
async def save_delivery_settings(
    min_order_amount: float = 0,
    min_order_amount_out_of_city: float = 0,
    min_order_message: str = "",
    enabled: bool = False
):
    """Save delivery settings"""
    global runtime_settings

    runtime_settings["delivery"] = {
        "min_order_amount": min_order_amount,
        "min_order_amount_out_of_city": min_order_amount_out_of_city,
        "min_order_message": min_order_message,
        "enabled": enabled
    }

    if database.connected and database.settings is not None:
        database.settings.update_one(
            {"_id": "app_settings"},
            {"$set": {"delivery": runtime_settings["delivery"]}},
            upsert=True
        )

    return {"status": "saved"}


@app.get("/api/settings/order-types")
async def get_order_types(enabled_only: bool = False):
    """Get order types configuration"""
    # Ensure we have the latest from DB
    if database.connected and database.settings is not None:
        db_settings = database.settings.find_one({"_id": "app_settings"})
        if db_settings and db_settings.get("order_types"):
            runtime_settings["order_types"] = db_settings["order_types"]

    order_types = runtime_settings.get("order_types", [])

    # Sort by sort_order
    order_types = sorted(order_types, key=lambda x: x.get("sort_order", 0))

    # Filter enabled only if requested
    if enabled_only:
        order_types = [ot for ot in order_types if ot.get("enabled", True)]

    return order_types


@app.post("/api/settings/order-types")
async def save_order_types(order_types: List[dict]):
    """Save order types configuration"""
    global runtime_settings

    runtime_settings["order_types"] = order_types

    if database.connected and database.settings is not None:
        database.settings.update_one(
            {"_id": "app_settings"},
            {"$set": {"order_types": runtime_settings["order_types"]}},
            upsert=True
        )

    return {"status": "saved"}


@app.put("/api/settings/order-types/reorder")
async def reorder_order_types(items: List[dict]):
    """Reorder order types by sort_order"""
    global runtime_settings

    # Update sort_order for each item
    for item in items:
        for ot in runtime_settings["order_types"]:
            if ot["type"] == item["type"]:
                ot["sort_order"] = item["sort_order"]
                break

    # Sort by new order
    runtime_settings["order_types"] = sorted(
        runtime_settings["order_types"],
        key=lambda x: x.get("sort_order", 0)
    )

    if database.connected and database.settings is not None:
        database.settings.update_one(
            {"_id": "app_settings"},
            {"$set": {"order_types": runtime_settings["order_types"]}},
            upsert=True
        )

    return {"status": "saved", "order_types": runtime_settings["order_types"]}


# ============ API: Combos ============

DEMO_COMBOS = []


@app.get("/api/combos")
async def get_combos(available: bool = None):
    """Get all combos"""
    if not database.connected or database.combos is None:
        result = DEMO_COMBOS
        if available is not None:
            result = [c for c in result if c.get("available") == available]
        return result
    query = {}
    if available is not None:
        query["available"] = available
    return serialize_docs(database.combos.find(query))


@app.post("/api/combos")
async def create_combo(data: ComboCreate):
    """Create a new combo"""
    if not database.connected or database.combos is None:
        combo_doc = data.model_dump()
        combo_doc["_id"] = str(len(DEMO_COMBOS) + 1)
        combo_doc["created_at"] = datetime.utcnow().isoformat()
        DEMO_COMBOS.append(combo_doc)
        return combo_doc

    combo_doc = data.model_dump()
    combo_doc["created_at"] = datetime.utcnow()
    result = database.combos.insert_one(combo_doc)
    combo_doc["_id"] = str(result.inserted_id)
    combo_doc["created_at"] = combo_doc["created_at"].isoformat()
    return combo_doc


@app.put("/api/combos/{combo_id}")
async def update_combo(combo_id: str, data: ComboCreate):
    """Update a combo"""
    if not database.connected or database.combos is None:
        for combo in DEMO_COMBOS:
            if combo["_id"] == combo_id:
                combo.update(data.model_dump())
                return combo
        raise HTTPException(status_code=404, detail="Combo not found")

    result = database.combos.update_one(
        {"_id": ObjectId(combo_id)},
        {"$set": data.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Combo not found")
    return {"status": "updated"}


@app.delete("/api/combos/{combo_id}")
async def delete_combo(combo_id: str):
    """Delete a combo"""
    if not database.connected or database.combos is None:
        DEMO_COMBOS[:] = [c for c in DEMO_COMBOS if c["_id"] != combo_id]
        return {"status": "deleted"}

    result = database.combos.delete_one({"_id": ObjectId(combo_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Combo not found")
    return {"status": "deleted"}


@app.get("/api/combos/available-for-menu")
async def get_combos_available_for_menu():
    """Get combos that are not yet added to the menu"""
    if not database.connected or database.combos is None:
        # Demo mode - filter out combos already in menu
        menu_combo_ids = [
            item.get("combo_id")
            for item in DEMO_MENU_ITEMS
            if item.get("item_type") == "combo"
        ]
        return [c for c in DEMO_COMBOS if c["_id"] not in menu_combo_ids and c.get("available", True)]

    # Get combo IDs already in menu
    menu_combo_ids = [
        item["combo_id"]
        for item in database.menu_items.find({"item_type": "combo"})
        if item.get("combo_id")
    ]

    # Return combos not in menu
    query = {"available": True}
    if menu_combo_ids:
        query["_id"] = {"$nin": [ObjectId(cid) for cid in menu_combo_ids]}

    return serialize_docs(database.combos.find(query))


# ============ API: Modifiers ============

DEMO_MODIFIERS = []


@app.get("/api/modifiers")
async def get_modifiers():
    """Get all modifier groups"""
    if not database.connected or database.modifiers is None:
        return DEMO_MODIFIERS
    return serialize_docs(database.modifiers.find())


@app.post("/api/modifiers")
async def create_modifier(data: ModifierGroupCreate):
    """Create a new modifier group"""
    if not database.connected or database.modifiers is None:
        modifier_doc = data.model_dump()
        modifier_doc["_id"] = str(len(DEMO_MODIFIERS) + 1)
        DEMO_MODIFIERS.append(modifier_doc)
        return modifier_doc

    modifier_doc = data.model_dump()
    result = database.modifiers.insert_one(modifier_doc)
    modifier_doc["_id"] = str(result.inserted_id)
    return modifier_doc


@app.put("/api/modifiers/{modifier_id}")
async def update_modifier(modifier_id: str, data: ModifierGroupCreate):
    """Update a modifier group"""
    if not database.connected or database.modifiers is None:
        for mod in DEMO_MODIFIERS:
            if mod["_id"] == modifier_id:
                mod.update(data.model_dump())
                return mod
        raise HTTPException(status_code=404, detail="Modifier not found")

    result = database.modifiers.update_one(
        {"_id": ObjectId(modifier_id)},
        {"$set": data.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Modifier not found")
    return {"status": "updated"}


@app.delete("/api/modifiers/{modifier_id}")
async def delete_modifier(modifier_id: str):
    """Delete a modifier group"""
    if not database.connected or database.modifiers is None:
        DEMO_MODIFIERS[:] = [m for m in DEMO_MODIFIERS if m["_id"] != modifier_id]
        return {"status": "deleted"}

    result = database.modifiers.delete_one({"_id": ObjectId(modifier_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Modifier not found")
    return {"status": "deleted"}


@app.put("/api/modifiers/{modifier_id}/toggle")
async def toggle_modifier(modifier_id: str, data: dict):
    """Toggle modifier enabled/disabled status"""
    if not database.connected or database.modifiers is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    is_enabled = data.get("is_enabled", True)
    result = database.modifiers.update_one(
        {"_id": ObjectId(modifier_id)},
        {"$set": {"is_enabled": is_enabled}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Modifier not found")
    return {"status": "toggled", "is_enabled": is_enabled}


@app.post("/api/modifiers/{modifier_id}/copy")
async def copy_modifier(modifier_id: str):
    """Copy a modifier group with a new ID"""
    if not database.connected or database.modifiers is None:
        raise HTTPException(status_code=503, detail="Database not connected")

    modifier = database.modifiers.find_one({"_id": ObjectId(modifier_id)})
    if not modifier:
        raise HTTPException(status_code=404, detail="Modifier not found")

    # Create copy
    del modifier["_id"]
    modifier["name"] = f"{modifier['name']} (копія)"

    result = database.modifiers.insert_one(modifier)
    modifier["_id"] = str(result.inserted_id)

    return serialize_doc(modifier)


# ============ API: Menu Items ============

@app.get("/api/menu-items")
async def get_menu_items(active_only: bool = True):
    """Get menu items with product data"""
    return get_menu_items_list(active_only)


@app.post("/api/menu-items")
async def add_to_menu(data: MenuItemCreate):
    """Add a product or combo to the menu"""
    if not database.connected or database.menu_items is None:
        # Demo mode
        menu_item = data.model_dump()
        menu_item["_id"] = str(len(DEMO_MENU_ITEMS) + 1)
        menu_item["created_at"] = datetime.utcnow().isoformat()
        DEMO_MENU_ITEMS.append(menu_item)
        return menu_item

    item_type = data.item_type or "product"

    if item_type == "combo":
        # Check if combo exists
        if not data.combo_id:
            raise HTTPException(status_code=400, detail="combo_id is required for combos")
        combo = database.combos.find_one({"_id": ObjectId(data.combo_id)})
        if not combo:
            raise HTTPException(status_code=404, detail="Комбо не знайдено")

        # Check if already in menu
        existing = database.menu_items.find_one({"combo_id": data.combo_id, "item_type": "combo"})
        if existing:
            raise HTTPException(status_code=400, detail="Комбо вже є в меню")
    else:
        # Check if product exists
        if not data.product_id:
            raise HTTPException(status_code=400, detail="product_id is required for products")
        product = database.products.find_one({"_id": ObjectId(data.product_id)})
        if not product:
            raise HTTPException(status_code=404, detail="Продукт не знайдено")

        # Check if already in menu
        existing = database.menu_items.find_one({"product_id": data.product_id})
        if existing:
            raise HTTPException(status_code=400, detail="Продукт вже є в меню")

    doc = data.model_dump()
    doc["created_at"] = datetime.utcnow()
    result = database.menu_items.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    doc["created_at"] = doc["created_at"].isoformat()
    return doc


@app.put("/api/menu-items/{menu_item_id}")
async def update_menu_item(menu_item_id: str, data: MenuItemCreate):
    """Update a menu item"""
    if not database.connected or database.menu_items is None:
        for item in DEMO_MENU_ITEMS:
            if item["_id"] == menu_item_id:
                item.update(data.model_dump())
                return item
        raise HTTPException(status_code=404, detail="Позицію меню не знайдено")

    result = database.menu_items.update_one(
        {"_id": ObjectId(menu_item_id)},
        {"$set": data.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Позицію меню не знайдено")
    return {"status": "updated"}


@app.delete("/api/menu-items/{menu_item_id}")
async def remove_from_menu(menu_item_id: str):
    """Remove a product from the menu"""
    if not database.connected or database.menu_items is None:
        DEMO_MENU_ITEMS[:] = [m for m in DEMO_MENU_ITEMS if m["_id"] != menu_item_id]
        return {"status": "deleted"}

    result = database.menu_items.delete_one({"_id": ObjectId(menu_item_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Позицію меню не знайдено")
    return {"status": "deleted"}


@app.post("/api/menu-items/batch")
async def batch_add_to_menu(product_ids: List[str]):
    """Add multiple products to menu at once"""
    if not database.connected or database.menu_items is None:
        added = []
        for pid in product_ids:
            if not any(m.get("product_id") == pid for m in DEMO_MENU_ITEMS):
                item = {"_id": str(len(DEMO_MENU_ITEMS) + 1), "item_type": "product", "product_id": pid, "is_active": True, "sort_order": 0}
                DEMO_MENU_ITEMS.append(item)
                added.append(item["_id"])
        return {"added": added}

    added = []
    for product_id in product_ids:
        existing = database.menu_items.find_one({"product_id": product_id})
        if not existing:
            doc = {
                "item_type": "product",
                "product_id": product_id,
                "is_active": True,
                "sort_order": 0,
                "created_at": datetime.utcnow()
            }
            result = database.menu_items.insert_one(doc)
            added.append(str(result.inserted_id))
    return {"added": added}


@app.post("/api/menu-items/reorder")
async def reorder_menu_items(req: Request):
    """Update sort order for multiple menu items"""
    try:
        items = await req.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    if not database.connected or database.menu_items is None:
        for update in items:
            for item in DEMO_MENU_ITEMS:
                if item["_id"] == update["_id"]:
                    item["sort_order"] = update["sort_order"]
        return {"status": "updated"}

    for update in items:
        database.menu_items.update_one(
            {"_id": ObjectId(update["_id"])},
            {"$set": {"sort_order": update["sort_order"]}}
        )
    return {"status": "updated"}


# ============ API: Promo Codes ============

DEMO_PROMO_CODES = []


def validate_promo_code(code: str, order_total: float):
    """Validate promo code and return discount info or error"""
    if not database.connected or database.promo_codes is None:
        # Demo mode
        for promo in DEMO_PROMO_CODES:
            if promo["code"].upper() == code.upper() and promo.get("is_active"):
                return {"valid": True, "promo": promo}
        return {"valid": False, "error": "Промокод не знайдено"}

    promo = database.promo_codes.find_one({"code": code.upper()})
    if not promo:
        return {"valid": False, "error": "Промокод не знайдено"}

    if not promo.get("is_active"):
        return {"valid": False, "error": "Промокод неактивний"}

    now = datetime.utcnow()
    if promo.get("valid_from") and now < promo["valid_from"]:
        return {"valid": False, "error": "Промокод ще не активний"}

    if promo.get("valid_to") and now > promo["valid_to"]:
        return {"valid": False, "error": "Термін дії промокоду закінчився"}

    if promo.get("usage_limit") and promo.get("usage_count", 0) >= promo["usage_limit"]:
        return {"valid": False, "error": "Ліміт використання вичерпано"}

    if order_total < promo.get("min_order_amount", 0):
        return {"valid": False, "error": f"Мінімальна сума замовлення: {promo['min_order_amount']} грн"}

    return {"valid": True, "promo": serialize_doc(promo)}


def calculate_discount(promo: dict, order_total: float) -> float:
    """Calculate discount amount based on promo code"""
    if promo["discount_type"] == "percentage":
        return round(order_total * promo["discount_value"] / 100, 2)
    else:  # fixed
        return min(promo["discount_value"], order_total)


@app.get("/api/promo-codes")
async def get_promo_codes():
    """Get all promo codes (admin)"""
    if not database.connected or database.promo_codes is None:
        return DEMO_PROMO_CODES
    return serialize_docs(database.promo_codes.find().sort("created_at", -1))


@app.post("/api/promo-codes")
async def create_promo_code(data: PromoCodeCreate):
    """Create a new promo code"""
    if not database.connected or database.promo_codes is None:
        promo_doc = data.model_dump()
        promo_doc["_id"] = str(len(DEMO_PROMO_CODES) + 1)
        promo_doc["code"] = promo_doc["code"].upper()
        promo_doc["usage_count"] = 0
        promo_doc["created_at"] = datetime.utcnow().isoformat()
        DEMO_PROMO_CODES.append(promo_doc)
        return promo_doc

    # Check if code already exists
    existing = database.promo_codes.find_one({"code": data.code.upper()})
    if existing:
        raise HTTPException(status_code=400, detail="Промокод вже існує")

    promo_doc = data.model_dump()
    promo_doc["code"] = promo_doc["code"].upper()
    promo_doc["usage_count"] = 0
    promo_doc["created_at"] = datetime.utcnow()

    result = database.promo_codes.insert_one(promo_doc)
    promo_doc["_id"] = str(result.inserted_id)
    promo_doc["created_at"] = promo_doc["created_at"].isoformat()
    return promo_doc


@app.put("/api/promo-codes/{promo_id}")
async def update_promo_code(promo_id: str, data: PromoCodeCreate):
    """Update a promo code"""
    if not database.connected or database.promo_codes is None:
        for promo in DEMO_PROMO_CODES:
            if promo["_id"] == promo_id:
                promo.update(data.model_dump())
                promo["code"] = promo["code"].upper()
                return promo
        raise HTTPException(status_code=404, detail="Промокод не знайдено")

    update_data = data.model_dump()
    update_data["code"] = update_data["code"].upper()

    result = database.promo_codes.update_one(
        {"_id": ObjectId(promo_id)},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Промокод не знайдено")
    return {"status": "updated"}


@app.delete("/api/promo-codes/{promo_id}")
async def delete_promo_code(promo_id: str):
    """Delete a promo code"""
    if not database.connected or database.promo_codes is None:
        DEMO_PROMO_CODES[:] = [p for p in DEMO_PROMO_CODES if p["_id"] != promo_id]
        return {"status": "deleted"}

    result = database.promo_codes.delete_one({"_id": ObjectId(promo_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Промокод не знайдено")
    return {"status": "deleted"}


@app.post("/api/promo-codes/validate")
async def validate_promo(code: str, order_total: float = 0):
    """Validate a promo code for an order"""
    result = validate_promo_code(code, order_total)
    if result["valid"]:
        promo = result["promo"]
        discount = calculate_discount(promo, order_total)
        return {
            "valid": True,
            "code": promo["code"],
            "discount_type": promo["discount_type"],
            "discount_value": promo["discount_value"],
            "discount_amount": discount,
            "new_total": order_total - discount
        }
    return result


# ============ API: Feedbacks ============

DEMO_FEEDBACKS = []


@app.get("/api/feedbacks")
async def get_feedbacks(limit: int = 50):
    """Get all feedbacks (for admin view)"""
    if not database.connected or database.feedbacks is None:
        return DEMO_FEEDBACKS[:limit]
    return serialize_docs(
        database.feedbacks.find().sort("created_at", -1).limit(limit)
    )


@app.post("/api/feedbacks")
async def create_feedback(data: FeedbackCreate):
    """Create a new feedback/review"""
    if data.rating < 1 or data.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    feedback_doc = {
        "rating": data.rating,
        "phone": data.phone,
        "comment": data.comment,
        "created_at": datetime.utcnow()
    }

    if not database.connected or database.feedbacks is None:
        feedback_doc["_id"] = str(len(DEMO_FEEDBACKS) + 1)
        feedback_doc["created_at"] = feedback_doc["created_at"].isoformat()
        DEMO_FEEDBACKS.insert(0, feedback_doc)
    else:
        result = database.feedbacks.insert_one(feedback_doc)
        feedback_doc["_id"] = str(result.inserted_id)
        feedback_doc["created_at"] = feedback_doc["created_at"].isoformat()

    return feedback_doc


@app.get("/api/feedbacks/stats")
async def get_feedback_stats():
    """Get feedback statistics"""
    if not database.connected or database.feedbacks is None:
        if not DEMO_FEEDBACKS:
            return {"total": 0, "average_rating": 0, "rating_distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}}
        total = len(DEMO_FEEDBACKS)
        avg = sum(f["rating"] for f in DEMO_FEEDBACKS) / total
        dist = {i: len([f for f in DEMO_FEEDBACKS if f["rating"] == i]) for i in range(1, 6)}
        return {"total": total, "average_rating": round(avg, 1), "rating_distribution": dist}

    pipeline = [
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "average_rating": {"$avg": "$rating"}
        }}
    ]
    result = list(database.feedbacks.aggregate(pipeline))

    if not result:
        return {"total": 0, "average_rating": 0, "rating_distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}}

    dist_pipeline = [
        {"$group": {"_id": "$rating", "count": {"$sum": 1}}}
    ]
    dist_result = list(database.feedbacks.aggregate(dist_pipeline))
    distribution = {i: 0 for i in range(1, 6)}
    for item in dist_result:
        distribution[item["_id"]] = item["count"]

    return {
        "total": result[0]["total"],
        "average_rating": round(result[0]["average_rating"], 1),
        "rating_distribution": distribution
    }


@app.get("/admin/feedbacks", response_class=HTMLResponse)
async def admin_feedbacks_page(request: Request):
    return templates.TemplateResponse("admin/feedbacks.html", {"request": request})


@app.get("/admin/promo-codes", response_class=HTMLResponse)
async def admin_promo_codes_page(request: Request):
    return templates.TemplateResponse("admin/promo_codes.html", {"request": request})


@app.get("/admin/qr-codes", response_class=HTMLResponse)
async def admin_qr_codes_page(request: Request):
    return templates.TemplateResponse("admin/qr_codes.html", {"request": request})


@app.get("/admin/modifiers", response_class=HTMLResponse)
async def admin_modifiers_page(request: Request):
    return templates.TemplateResponse("admin/modifiers.html", {"request": request})


@app.get("/admin/combos", response_class=HTMLResponse)
async def admin_combos_page(request: Request):
    return templates.TemplateResponse("admin/combos.html", {"request": request})


@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request):
    return templates.TemplateResponse("admin/settings.html", {"request": request})


# ============ API: Export ============

@app.get("/api/export/orders")
async def export_orders(date_from: str = None, date_to: str = None):
    """Export orders to CSV format"""
    import io
    import csv

    # Parse date range
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            start_date = datetime.utcnow() - timedelta(days=7)
    else:
        start_date = datetime.utcnow() - timedelta(days=7)

    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            end_date = datetime.utcnow()
    else:
        end_date = datetime.utcnow()

    # Get orders from database
    if not database.connected or database.orders is None:
        orders = DEMO_ORDERS
    else:
        orders = list(database.orders.find({
            "created_at": {"$gte": start_date, "$lte": end_date}
        }).sort("created_at", -1))

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # Header with BOM for Excel UTF-8 support
    writer.writerow(['№ Замовлення', 'Дата', 'Тип', 'Столик', 'Клієнт', 'Телефон', 'Товари', 'Сума', 'Статус', 'Оплата'])

    order_types = {'dine_in': 'В залі', 'takeaway': 'З собою', 'delivery': 'Доставка'}
    statuses = {'new': 'Нове', 'preparing': 'Готується', 'ready': 'Готове', 'completed': 'Виконано', 'cancelled': 'Скасовано'}
    payment_statuses = {'pending': 'Очікує', 'paid': 'Оплачено'}

    for order in orders:
        created = order.get('created_at')
        if isinstance(created, datetime):
            date_str = created.strftime('%d.%m.%Y %H:%M')
        elif isinstance(created, str):
            try:
                dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                date_str = dt.strftime('%d.%m.%Y %H:%M')
            except:
                date_str = created
        else:
            date_str = ''

        items_str = ', '.join([f"{item.get('name', '')} x{item.get('qty', 1)}" for item in order.get('items', [])])

        writer.writerow([
            order.get('order_number', ''),
            date_str,
            order_types.get(order.get('order_type', ''), order.get('order_type', '')),
            order.get('table_number', '') or '',
            order.get('customer_name', '') or '',
            order.get('customer_phone', '') or '',
            items_str,
            order.get('total', 0),
            statuses.get(order.get('status', ''), order.get('status', '')),
            payment_statuses.get(order.get('payment_status', ''), order.get('payment_status', ''))
        ])

    # Add BOM for Excel to recognize UTF-8
    csv_content = '\ufeff' + output.getvalue()
    output.close()

    filename = f"orders_{date_from or 'all'}_{date_to or 'now'}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/export/stats")
async def export_stats(date_from: str = None, date_to: str = None):
    """Export daily statistics to CSV format"""
    import io
    import csv

    # Parse date range
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            start_date = datetime.utcnow() - timedelta(days=7)
    else:
        start_date = datetime.utcnow() - timedelta(days=7)

    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            end_date = datetime.utcnow()
    else:
        end_date = datetime.utcnow()

    days_in_range = (end_date - start_date).days + 1

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # Daily stats header
    writer.writerow(['Дата', 'Замовлень', 'Виручка (грн)', 'В залі', 'З собою', 'Доставка'])

    if not database.connected or database.orders is None:
        # Demo data
        for i in range(min(days_in_range, 30)):
            day = start_date + timedelta(days=i)
            writer.writerow([day.strftime('%d.%m.%Y'), 0, 0, 0, 0, 0])
    else:
        for i in range(min(days_in_range, 30)):
            day = start_date + timedelta(days=i)
            next_day = day + timedelta(days=1)
            day_orders = list(database.orders.find({
                "created_at": {"$gte": day, "$lt": next_day},
                "status": {"$ne": "cancelled"}
            }))

            total_revenue = sum(o.get('total', 0) for o in day_orders)
            dine_in = len([o for o in day_orders if o.get('order_type') == 'dine_in'])
            takeaway = len([o for o in day_orders if o.get('order_type') == 'takeaway'])
            delivery = len([o for o in day_orders if o.get('order_type') == 'delivery'])

            writer.writerow([
                day.strftime('%d.%m.%Y'),
                len(day_orders),
                total_revenue,
                dine_in,
                takeaway,
                delivery
            ])

    # Add empty row and summary
    writer.writerow([])
    writer.writerow(['=== Топ продуктів ==='])
    writer.writerow(['Назва', 'Кількість', 'Виручка (грн)'])

    if database.connected and database.orders is not None:
        pipeline = [
            {"$match": {"created_at": {"$gte": start_date, "$lte": end_date}, "status": {"$ne": "cancelled"}}},
            {"$unwind": "$items"},
            {"$group": {
                "_id": "$items.name",
                "count": {"$sum": "$items.qty"},
                "revenue": {"$sum": {"$multiply": ["$items.qty", "$items.price"]}}
            }},
            {"$sort": {"revenue": -1}},
            {"$limit": 20}
        ]
        top_products = list(database.orders.aggregate(pipeline))
        for product in top_products:
            writer.writerow([product['_id'], product['count'], product['revenue']])

    # Add BOM for Excel to recognize UTF-8
    csv_content = '\ufeff' + output.getvalue()
    output.close()

    filename = f"stats_{date_from or 'all'}_{date_to or 'now'}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============ WebSocket ============

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    pubsub = None
    listener_task = None

    try:
        # Try to connect to Redis
        try:
            pubsub = await redis_manager.subscribe(REDIS_CHANNELS)

            async def listener(ps):
                async for message in ps.listen():
                    if message["type"] == "message":
                        await websocket.send_text(message["data"])

            listener_task = asyncio.create_task(listener(pubsub))
        except Exception:
            pubsub = None

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                await websocket.send_text("ping")
            except WebSocketDisconnect:
                break

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        if listener_task:
            listener_task.cancel()
        if pubsub:
            await pubsub.aclose()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
