from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    create_engine,
)


metadata = MetaData()


customers = Table(
    'customers',
    metadata,
    Column('customer_id', Integer, primary_key=True, autoincrement=False),
    Column('customer_name', String(255), nullable=False),
    Column('email', String(255), nullable=False),
    Column('created_at', DateTime, nullable=False),
    Column('city', String(100), nullable=False),
    Column('country', String(100), nullable=False),
    Column('deleted_at', DateTime, nullable=True),
)

products = Table(
    'products',
    metadata,
    Column('product_id', Integer, primary_key=True, autoincrement=False),
    Column('product_name', String(255), nullable=False),
    Column('category', String(50), nullable=False),
    Column('brand', String(100), nullable=False),
    Column('unit_price', Float, nullable=False),
    Column('unit_cost', Float, nullable=False),
    Column('deleted_at', DateTime, nullable=True),
)

warehouses = Table(
    'warehouses',
    metadata,
    Column('warehouse_id', Integer, primary_key=True, autoincrement=False),
    Column('warehouse_name', String(100), nullable=False),
    Column('city', String(100), nullable=False),
    Column('country', String(100), nullable=False),
    Column('deleted_at', DateTime, nullable=True),
)

orders = Table(
    'orders',
    metadata,
    Column('order_id', Integer, primary_key=True, autoincrement=False),
    Column('customer_id', Integer, ForeignKey('customers.customer_id'), nullable=False),
    Column('order_created_at', DateTime, nullable=False),
    Column('order_status', String(20), nullable=False),
    Column('channel', String(20), nullable=False),
    Column('order_total', Float, nullable=False),
)

order_items = Table(
    'order_items',
    metadata,
    Column('order_item_id', Integer, primary_key=True, autoincrement=False),
    Column('order_id', Integer, ForeignKey('orders.order_id'), nullable=False),
    Column('product_id', Integer, ForeignKey('products.product_id'), nullable=False),
    Column('warehouse_id', Integer, ForeignKey('warehouses.warehouse_id'), nullable=False),
    Column('quantity', Integer, nullable=False),
    Column('unit_price', Float, nullable=False),
    Column('line_total', Float, nullable=False),
)

payments = Table(
    'payments',
    metadata,
    Column('payment_id', Integer, primary_key=True, autoincrement=False),
    Column('order_id', Integer, ForeignKey('orders.order_id'), nullable=False),
    Column('payment_created_at', DateTime, nullable=False),
    Column('payment_method', String(30), nullable=False),
    Column('payment_status', String(20), nullable=False),
    Column('amount', Float, nullable=False),
)

shipments = Table(
    'shipments',
    metadata,
    Column('shipment_id', Integer, primary_key=True, autoincrement=False),
    Column('order_id', Integer, ForeignKey('orders.order_id'), nullable=False),
    Column('shipment_status', String(20), nullable=False),
    Column('shipped_at', DateTime, nullable=True),
    Column('delivered_at', DateTime, nullable=True),
    Column('carrier', String(50), nullable=False),
)

inventory_balances = Table(
    'inventory_balances',
    metadata,
    Column('product_id', Integer, ForeignKey('products.product_id'), nullable=False),
    Column('warehouse_id', Integer, ForeignKey('warehouses.warehouse_id'), nullable=False),
    Column('stock_on_hand', Integer, nullable=False),
    Column('reserved_quantity', Integer, nullable=False),
    Column('available_quantity', Integer, nullable=False),
    Column('reorder_point', Integer, nullable=False),
    Column('reorder_quantity', Integer, nullable=False),
    Column('updated_at', DateTime, nullable=False),
    PrimaryKeyConstraint('product_id', 'warehouse_id'),
)

inventory_movements = Table(
    'inventory_movements',
    metadata,
    Column('movement_id', Integer, primary_key=True, autoincrement=False),
    Column('product_id', Integer, ForeignKey('products.product_id'), nullable=False),
    Column('warehouse_id', Integer, ForeignKey('warehouses.warehouse_id'), nullable=False),
    Column('order_id', Integer, ForeignKey('orders.order_id'), nullable=True),
    Column('order_item_id', Integer, ForeignKey('order_items.order_item_id'), nullable=True),
    Column('movement_type', String(30), nullable=False),
    Column('quantity_change', Integer, nullable=False),
    Column('movement_created_at', DateTime, nullable=False),
    Column('reason', Text, nullable=False),
)

returns = Table(
    'returns',
    metadata,
    Column('return_id', Integer, primary_key=True, autoincrement=False),
    Column('order_item_id', Integer, ForeignKey('order_items.order_item_id'), nullable=False),
    Column('quantity_returned', Integer, nullable=False),
    Column('returned_at', DateTime, nullable=False),
    Column('return_reason', String(40), nullable=False),
    Column('refund_amount', Float, nullable=False),
)


# Indexes. Foreign-key columns are not auto-indexed by SQLite or Postgres
# (MySQL/InnoDB does, but a redundant index there is harmless), and the daily
# Airflow flow scans by created_at / returned_at / delivered_at windows.
Index('ix_orders_customer_id', orders.c.customer_id)
Index('ix_orders_order_created_at', orders.c.order_created_at)

Index('ix_order_items_order_id', order_items.c.order_id)
Index('ix_order_items_product_id', order_items.c.product_id)
Index('ix_order_items_warehouse_id', order_items.c.warehouse_id)

Index('ix_payments_order_id', payments.c.order_id)

Index('ix_shipments_order_id', shipments.c.order_id)
Index('ix_shipments_status_delivered_at', shipments.c.shipment_status, shipments.c.delivered_at)

Index('ix_inventory_movements_product_id', inventory_movements.c.product_id)
Index('ix_inventory_movements_warehouse_id', inventory_movements.c.warehouse_id)
Index('ix_inventory_movements_order_id', inventory_movements.c.order_id)
Index('ix_inventory_movements_order_item_id', inventory_movements.c.order_item_id)
Index('ix_inventory_movements_created_at', inventory_movements.c.movement_created_at)

Index('ix_returns_order_item_id', returns.c.order_item_id)
Index('ix_returns_returned_at', returns.c.returned_at)


def make_engine(db_url: str) -> Engine:
    connect_args: dict[str, Any] = {}
    if db_url.startswith('sqlite'):
        connect_args = {'check_same_thread': False}
    engine = create_engine(db_url, future=True, connect_args=connect_args)
    if db_url.startswith('sqlite'):
        from sqlalchemy import event

        @event.listens_for(engine, 'connect')
        def _enable_fk(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute('PRAGMA foreign_keys=ON')
            cur.close()
    return engine


def init_schema(engine: Engine, drop_first: bool) -> None:
    if drop_first:
        metadata.drop_all(engine)
    metadata.create_all(engine)


def to_row(instance: Any) -> dict[str, Any]:
    return asdict(instance)
