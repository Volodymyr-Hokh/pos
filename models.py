from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from bson import ObjectId


class PyObjectId(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, info=None):
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, str) and ObjectId.is_valid(v):
            return v
        raise ValueError("Invalid ObjectId")


# Category models
class CategoryCreate(BaseModel):
    name: str
    icon: str = "tag"
    sort_order: int = 0


class Category(CategoryCreate):
    id: Optional[str] = Field(None, alias="_id")

    class Config:
        populate_by_name = True


# Modifier models
class ModifierOption(BaseModel):
    name: str
    price_add: float = 0  # Additional price for this option


class ModifierGroupCreate(BaseModel):
    name: str  # e.g., "Розмір", "Молоко", "Добавки"
    type: str = "single"  # single (radio) or multiple (checkbox)
    required: bool = False
    options: List[ModifierOption] = []
    # New fields for enhanced modifiers
    display_order: int = 0  # Order of display (1, 2, 3...)
    display_mode: str = "row"  # "row" or "column"
    show_for_otp: bool = True  # Show for OTP (Order Taking Point)
    show_for_vtp: bool = True  # Show for VTP (Verification Terminal Point)
    is_enabled: bool = True  # Enable/disable without deleting


class ModifierGroup(ModifierGroupCreate):
    id: Optional[str] = Field(None, alias="_id")

    class Config:
        populate_by_name = True


# Product Tag models
class ProductTagCreate(BaseModel):
    name: str
    color: str = "#6366f1"


class ProductTag(ProductTagCreate):
    id: Optional[str] = Field(None, alias="_id")

    class Config:
        populate_by_name = True


# Audit Log model
class AuditLog(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    action: str  # "create", "update", "delete", "copy"
    entity_type: str  # "product", "modifier", "category", "order"
    entity_id: str
    entity_name: str
    changes: dict = {}  # {"field": {"old": x, "new": y}}
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


# Project model for organizing assortments
class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    is_active: bool = True


class Project(ProjectCreate):
    id: Optional[str] = Field(None, alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


# Product models
class ProductCreate(BaseModel):
    name: str
    category_id: str
    price: float
    description: str = ""
    image: str = "/static/img/placeholder.svg"
    weight: str = ""
    cook_time: str = ""
    available: bool = True
    modifier_groups: List[str] = []  # List of modifier group IDs
    daily_production_norm: Optional[int] = None  # Daily production target
    tags: List[str] = []  # List of tag IDs
    is_alcohol: bool = False  # Alcohol indicator
    project_id: Optional[str] = None  # Project for organization


class Product(ProductCreate):
    id: Optional[str] = Field(None, alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


# Selected modifier for order
class SelectedModifier(BaseModel):
    group_name: str
    option_name: str
    price_add: float = 0


# Order item
class OrderItem(BaseModel):
    product_id: str
    name: str
    qty: int = 1
    price: float
    modifiers: List[SelectedModifier] = []
    is_combo: bool = False
    combo_items: Optional[List[dict]] = None  # Expanded items for kitchen display


# Order models
class OrderCreate(BaseModel):
    items: List[OrderItem]
    order_type: str = "dine_in"  # dine_in, takeaway, delivery, self_service
    table_number: Optional[int] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    delivery_zone: Optional[str] = None  # "in_city" | "out_of_city" for delivery orders
    notes: Optional[str] = None
    promo_code: Optional[str] = None


class Order(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    order_number: str
    items: List[OrderItem]
    total: float
    status: str = "new"  # new, preparing, ready, completed, cancelled
    payment_status: str = "pending"  # pending, paid
    order_type: str = "dine_in"  # dine_in, takeaway, delivery, self_service
    table_number: Optional[int] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    delivery_zone: Optional[str] = None  # "in_city" | "out_of_city" for delivery orders
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


# Stats models
class DailyStat(BaseModel):
    date: str
    orders_count: int
    revenue: float


class Stats(BaseModel):
    today_orders: int = 0
    today_revenue: float = 0
    pending_orders: int = 0
    completed_orders: int = 0
    top_products: List[dict] = []
    daily_stats: List[DailyStat] = []


# Feedback models
class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)  # 1-5 stars, required
    phone: str = ""
    comment: str = ""


class Feedback(FeedbackCreate):
    id: Optional[str] = Field(None, alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


# Combo item
class ComboItem(BaseModel):
    product_id: str
    product_name: str
    qty: int = 1


# Combo models
class ComboCreate(BaseModel):
    name: str
    description: str = ""
    image: str = "/static/img/placeholder.svg"
    items: List[ComboItem] = []
    regular_price: float  # Sum of individual items
    combo_price: float  # Discounted price
    available: bool = True


class Combo(ComboCreate):
    id: Optional[str] = Field(None, alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


# Promo code models
class PromoCodeCreate(BaseModel):
    code: str
    discount_type: str = "percentage"  # percentage or fixed
    discount_value: float
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    usage_limit: Optional[int] = None  # None = unlimited
    min_order_amount: float = 0
    is_active: bool = True


class PromoCode(PromoCodeCreate):
    id: Optional[str] = Field(None, alias="_id")
    usage_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


# Menu item models (links products/combos from assortment to active menu)
class MenuItemCreate(BaseModel):
    item_type: str = "product"  # "product" or "combo"
    product_id: Optional[str] = None  # For products
    combo_id: Optional[str] = None    # For combos
    category_id: Optional[str] = None  # Override category (useful for combos)
    is_active: bool = True
    sort_order: int = 0


class MenuItem(MenuItemCreate):
    id: Optional[str] = Field(None, alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
