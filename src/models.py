from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Customer:
    customer_id: int
    customer_name: str
    email: str
    created_at: datetime
    city: str
    country: str
    deleted_at: datetime | None = None


@dataclass
class Product:
    product_id: int
    product_name: str
    category: str
    brand: str
    unit_price: float
    unit_cost: float
    deleted_at: datetime | None = None


@dataclass
class Order:
    order_id: int
    customer_id: int
    order_created_at: datetime
    order_status: str
    channel: str
    order_total: float


@dataclass
class OrderItem:
    order_item_id: int
    order_id: int
    product_id: int
    warehouse_id: int
    quantity: int
    unit_price: float
    line_total: float


@dataclass
class Payment:
    payment_id: int
    order_id: int
    payment_created_at: datetime
    payment_method: str
    payment_status: str
    amount: float


@dataclass
class Shipment:
    shipment_id: int
    order_id: int
    shipment_status: str
    shipped_at: datetime | None
    delivered_at: datetime | None
    carrier: str


@dataclass
class Warehouse:
    warehouse_id: int
    warehouse_name: str
    city: str
    country: str
    deleted_at: datetime | None = None


@dataclass
class InventoryBalance:
    product_id: int
    warehouse_id: int
    stock_on_hand: int
    reserved_quantity: int
    available_quantity: int
    reorder_point: int
    reorder_quantity: int
    updated_at: datetime


@dataclass
class InventoryMovement:
    movement_id: int
    product_id: int
    warehouse_id: int
    order_id: int | None
    order_item_id: int | None
    movement_type: str
    quantity_change: int
    movement_created_at: datetime
    reason: str


@dataclass
class Return:
    return_id: int
    order_item_id: int
    quantity_returned: int
    returned_at: datetime
    return_reason: str
    refund_amount: float
