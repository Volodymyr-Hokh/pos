from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo.database import Database
from pymongo.collection import Collection
from config import MONGODB_URL, MONGODB_DB_NAME

client: MongoClient = None
db: Database = None
connected: bool = False

# Collections
products: Collection = None
orders: Collection = None
categories: Collection = None
settings: Collection = None
feedbacks: Collection = None
promo_codes: Collection = None
modifiers: Collection = None
combos: Collection = None
menu_items: Collection = None
product_tags: Collection = None
audit_logs: Collection = None
projects: Collection = None


def connect_db():
    """Connect to MongoDB Atlas"""
    global client, db, products, orders, categories, settings, feedbacks, promo_codes, modifiers, combos, menu_items, product_tags, audit_logs, projects, connected

    try:
        client = MongoClient(MONGODB_URL, server_api=ServerApi('1'))
        db = client[MONGODB_DB_NAME]

        products = db["products"]
        orders = db["orders"]
        categories = db["categories"]
        settings = db["settings"]
        feedbacks = db["feedbacks"]
        promo_codes = db["promo_codes"]
        modifiers = db["modifiers"]
        combos = db["combos"]
        menu_items = db["menu_items"]
        product_tags = db["product_tags"]
        audit_logs = db["audit_logs"]
        projects = db["projects"]

        # Create indexes
        products.create_index("category_id")
        products.create_index("available")
        products.create_index("tags")
        products.create_index("is_alcohol")
        products.create_index("project_id")
        orders.create_index("created_at")
        orders.create_index("status")
        categories.create_index("sort_order")
        feedbacks.create_index("created_at")
        promo_codes.create_index("code", unique=True)
        combos.create_index("available")
        menu_items.create_index("product_id")
        menu_items.create_index("is_active")
        menu_items.create_index("sort_order")
        product_tags.create_index("name", unique=True)
        audit_logs.create_index([("created_at", -1)])
        audit_logs.create_index("entity_type")
        projects.create_index("name")

        # Test connection
        client.admin.command('ping')
        connected = True
        print(f"Connected to MongoDB: {MONGODB_DB_NAME}")
    except Exception as e:
        connected = False
        import traceback
        print(f"MongoDB connection failed: {e}")
        print(f"Error type: {type(e).__name__}")
        traceback.print_exc()
        print("Running in demo mode without database")


def close_db():
    """Close MongoDB connection"""
    global client
    if client:
        client.close()
        print("MongoDB connection closed")


def get_db() -> Database:
    """Get database instance"""
    return db
