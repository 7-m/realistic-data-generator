from __future__ import annotations

import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from .models import Customer, InventoryBalance, InventoryMovement, Order, OrderItem, Payment, Product, Shipment, Warehouse


def _dt(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(sep=' ')


def _rows(objs: Iterable[object], columns: Sequence[str]) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for obj in objs:
        if not is_dataclass(obj):
            raise TypeError(f'Expected dataclass instance, got {type(obj)!r}')
        data = asdict(obj)
        row = []
        for col in columns:
            val = data[col]
            if isinstance(val, datetime):
                val = _dt(val)
            row.append(val)
        rows.append(tuple(row))
    return rows


class SQLiteBackend:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    def reset(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                '''
                DROP TABLE IF EXISTS inventory_movements;
                DROP TABLE IF EXISTS inventory_balances;
                DROP TABLE IF EXISTS shipments;
                DROP TABLE IF EXISTS payments;
                DROP TABLE IF EXISTS order_items;
                DROP TABLE IF EXISTS orders;
                DROP TABLE IF EXISTS warehouses;
                DROP TABLE IF EXISTS products;
                DROP TABLE IF EXISTS customers;
                '''
            )
            self.create_tables(conn)

    def create_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS customers (
                customer_id INTEGER PRIMARY KEY,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                city TEXT NOT NULL,
                country TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                category TEXT NOT NULL,
                brand TEXT NOT NULL,
                unit_price REAL NOT NULL,
                unit_cost REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS warehouses (
                warehouse_id INTEGER PRIMARY KEY,
                warehouse_name TEXT NOT NULL,
                city TEXT NOT NULL,
                country TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_created_at TEXT NOT NULL,
                order_status TEXT NOT NULL,
                channel TEXT NOT NULL,
                order_total REAL NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
            );

            CREATE TABLE IF NOT EXISTS order_items (
                order_item_id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                warehouse_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                line_total REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(order_id),
                FOREIGN KEY (product_id) REFERENCES products(product_id),
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                payment_created_at TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                amount REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(order_id)
            );

            CREATE TABLE IF NOT EXISTS shipments (
                shipment_id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                shipment_status TEXT NOT NULL,
                shipped_at TEXT,
                delivered_at TEXT,
                carrier TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(order_id)
            );

            CREATE TABLE IF NOT EXISTS inventory_balances (
                product_id INTEGER NOT NULL,
                warehouse_id INTEGER NOT NULL,
                stock_on_hand INTEGER NOT NULL,
                reserved_quantity INTEGER NOT NULL,
                available_quantity INTEGER NOT NULL,
                reorder_point INTEGER NOT NULL,
                reorder_quantity INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (product_id, warehouse_id),
                FOREIGN KEY (product_id) REFERENCES products(product_id),
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
            );

            CREATE TABLE IF NOT EXISTS inventory_movements (
                movement_id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                warehouse_id INTEGER NOT NULL,
                order_id INTEGER,
                order_item_id INTEGER,
                movement_type TEXT NOT NULL,
                quantity_change INTEGER NOT NULL,
                movement_created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(product_id),
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id),
                FOREIGN KEY (order_id) REFERENCES orders(order_id),
                FOREIGN KEY (order_item_id) REFERENCES order_items(order_item_id)
            );
            '''
        )

    def ensure_ready(self) -> None:
        with self.connect() as conn:
            self.create_tables(conn)

    def next_id(self, table: str, column: str) -> int:
        with self.connect() as conn:
            row = conn.execute(f'SELECT COALESCE(MAX({column}), 0) + 1 FROM {table}').fetchone()
            return int(row[0]) if row else 1

    def has_orders_for_day(self, target_day: date) -> bool:
        start = target_day.isoformat()
        end = (target_day.toordinal() + 1)
        with self.connect() as conn:
            row = conn.execute(
                'SELECT 1 FROM orders WHERE order_created_at >= ? AND order_created_at < ? LIMIT 1',
                (f'{start} 00:00:00', f'{date.fromordinal(end).isoformat()} 00:00:00'),
            ).fetchone()
            return row is not None

    def fetch_customers(self) -> list[Customer]:
        with self.connect() as conn:
            rows = conn.execute('SELECT customer_id, customer_name, email, created_at, city, country FROM customers').fetchall()
        return [Customer(*row) for row in rows]

    def fetch_products(self) -> list[Product]:
        with self.connect() as conn:
            rows = conn.execute('SELECT product_id, product_name, category, brand, unit_price, unit_cost FROM products').fetchall()
        return [Product(*row) for row in rows]

    def fetch_warehouses(self) -> list[Warehouse]:
        with self.connect() as conn:
            rows = conn.execute('SELECT warehouse_id, warehouse_name, city, country FROM warehouses').fetchall()
        return [Warehouse(*row) for row in rows]

    def fetch_inventory_balances(self) -> list[InventoryBalance]:
        with self.connect() as conn:
            rows = conn.execute('SELECT product_id, warehouse_id, stock_on_hand, reserved_quantity, available_quantity, reorder_point, reorder_quantity, updated_at FROM inventory_balances').fetchall()
        return [InventoryBalance(*row) for row in rows]

    def insert_customers(self, rows: list[Customer]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO customers VALUES (?, ?, ?, ?, ?, ?)', _rows(rows, ['customer_id', 'customer_name', 'email', 'created_at', 'city', 'country']))

    def insert_products(self, rows: list[Product]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO products VALUES (?, ?, ?, ?, ?, ?)', _rows(rows, ['product_id', 'product_name', 'category', 'brand', 'unit_price', 'unit_cost']))

    def insert_warehouses(self, rows: list[Warehouse]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO warehouses VALUES (?, ?, ?, ?)', _rows(rows, ['warehouse_id', 'warehouse_name', 'city', 'country']))

    def insert_orders(self, rows: list[Order]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO orders VALUES (?, ?, ?, ?, ?, ?)', _rows(rows, ['order_id', 'customer_id', 'order_created_at', 'order_status', 'channel', 'order_total']))

    def insert_order_items(self, rows: list[OrderItem]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO order_items VALUES (?, ?, ?, ?, ?, ?, ?)', _rows(rows, ['order_item_id', 'order_id', 'product_id', 'warehouse_id', 'quantity', 'unit_price', 'line_total']))

    def run_delete_flow(self, rng, customer_prob: float, product_prob: float, warehouse_prob: float) -> tuple[int, int, int]:
        deleted_customers = self.delete_customers_without_orders(customer_prob, rng)
        deleted_products = self.delete_products_without_order_items(product_prob, rng)
        deleted_warehouses = self.delete_warehouses_without_order_items(warehouse_prob, rng)
        return deleted_customers, deleted_products, deleted_warehouses

    def delete_customers_without_orders(self, probability: float, rng) -> int:
        with self.connect() as conn:
            customer_ids = [row[0] for row in conn.execute(
                '''
                SELECT customer_id
                FROM customers
                WHERE customer_id NOT IN (SELECT DISTINCT customer_id FROM orders)
                '''
            )]
            deleted = 0
            for customer_id in customer_ids:
                if rng.random() < probability:
                    conn.execute('DELETE FROM customers WHERE customer_id = ?', (customer_id,))
                    deleted += 1
            return deleted

    def delete_products_without_order_items(self, probability: float, rng) -> int:
        with self.connect() as conn:
            product_ids = [row[0] for row in conn.execute(
                '''
                SELECT product_id
                FROM products
                WHERE product_id NOT IN (SELECT DISTINCT product_id FROM order_items)
                '''
            )]
            deleted = 0
            for product_id in product_ids:
                if rng.random() < probability:
                    conn.execute('DELETE FROM inventory_movements WHERE product_id = ?', (product_id,))
                    conn.execute('DELETE FROM inventory_balances WHERE product_id = ?', (product_id,))
                    conn.execute('DELETE FROM products WHERE product_id = ?', (product_id,))
                    deleted += 1
            return deleted

    def delete_warehouses_without_order_items(self, probability: float, rng) -> int:
        with self.connect() as conn:
            warehouse_ids = [row[0] for row in conn.execute(
                '''
                SELECT warehouse_id
                FROM warehouses
                WHERE warehouse_id NOT IN (SELECT DISTINCT warehouse_id FROM order_items)
                '''
            )]
            deleted = 0
            for warehouse_id in warehouse_ids:
                if rng.random() < probability:
                    conn.execute('DELETE FROM inventory_movements WHERE warehouse_id = ?', (warehouse_id,))
                    conn.execute('DELETE FROM inventory_balances WHERE warehouse_id = ?', (warehouse_id,))
                    conn.execute('DELETE FROM warehouses WHERE warehouse_id = ?', (warehouse_id,))
                    deleted += 1
            return deleted

    def insert_payments(self, rows: list[Payment]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO payments VALUES (?, ?, ?, ?, ?, ?)', _rows(rows, ['payment_id', 'order_id', 'payment_created_at', 'payment_method', 'payment_status', 'amount']))

    def insert_shipments(self, rows: list[Shipment]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO shipments VALUES (?, ?, ?, ?, ?, ?)', _rows(rows, ['shipment_id', 'order_id', 'shipment_status', 'shipped_at', 'delivered_at', 'carrier']))

    def insert_inventory_balances(self, rows: list[InventoryBalance]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO inventory_balances VALUES (?, ?, ?, ?, ?, ?, ?, ?)', _rows(rows, ['product_id', 'warehouse_id', 'stock_on_hand', 'reserved_quantity', 'available_quantity', 'reorder_point', 'reorder_quantity', 'updated_at']))

    def insert_inventory_movements(self, rows: list[InventoryMovement]) -> None:
        with self.connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO inventory_movements VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', _rows(rows, ['movement_id', 'product_id', 'warehouse_id', 'order_id', 'order_item_id', 'movement_type', 'quantity_change', 'movement_created_at', 'reason']))