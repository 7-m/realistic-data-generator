from __future__ import annotations

import argparse
import random
from datetime import date, datetime as dt
from pathlib import Path

from src.config import DEFAULT_CUSTOMERS, DEFAULT_ORDERS, DEFAULT_PRODUCTS, DEFAULT_WAREHOUSES, SEED
from src.database import SQLiteBackend
from src.generators import make_customers, make_products
from src.inventory import build_inventory_index, make_inventory_balances, make_warehouses
from src.models import Customer, InventoryBalance, Product, Warehouse
from src.simulator import simulate_orders, simulate_orders_for_day


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate ecommerce source data')
    parser.add_argument('--date', help='Generate data for a specific day in YYYY-MM-DD format')
    parser.add_argument('--orders', type=int, default=DEFAULT_ORDERS, help='Number of orders to generate')
    parser.add_argument('--force', action='store_true', help='Overwrite existing rows for the given date')
    parser.add_argument('--reset', action='store_true', help='Regenerate all datasets from scratch')
    parser.add_argument('--db-path', default=str(Path('output') / 'datagen.sqlite'), help='SQLite database path')
    parser.add_argument('--customer-delete-probability', type=float, default=0.01, help='Probability of deleting eligible customers during daily DB runs')
    parser.add_argument('--product-delete-probability', type=float, default=0.005, help='Probability of deleting eligible products during daily DB runs')
    parser.add_argument('--warehouse-delete-probability', type=float, default=0.001, help='Probability of deleting eligible warehouses during daily DB runs')
    return parser.parse_args()


def iso(value):
    return value.isoformat(sep=' ') if value else ''


def money(value: float) -> str:
    return f'{value:.2f}'


def backend_from_args(args: argparse.Namespace) -> SQLiteBackend:
    return SQLiteBackend(Path(args.db_path))


def load_or_create_reference_data(db: SQLiteBackend, rng: random.Random) -> tuple[list[Customer], list[Product], list[Warehouse]]:
    customers = db.fetch_customers()
    products = db.fetch_products()
    warehouses = db.fetch_warehouses()
    if customers and products and warehouses:
        return customers, products, warehouses

    customers = make_customers(DEFAULT_CUSTOMERS, rng)
    products = make_products(DEFAULT_PRODUCTS, rng)
    warehouses = make_warehouses(rng, DEFAULT_WAREHOUSES)
    db.insert_customers(customers)
    db.insert_products(products)
    db.insert_warehouses(warehouses)
    return customers, products, warehouses


def persist_reference_data(db: SQLiteBackend, customers: list[Customer], products: list[Product], warehouses: list[Warehouse]) -> None:
    db.insert_customers(customers)
    db.insert_products(products)
    db.insert_warehouses(warehouses)


def daily_run(target_day: date, n_orders: int, force: bool, db: SQLiteBackend, customer_delete_probability: float, product_delete_probability: float, warehouse_delete_probability: float) -> tuple[int, int, int]:
    rng = random.Random(SEED + int(target_day.strftime('%Y%m%d')))
    db.ensure_ready()
    customers, products, warehouses = load_or_create_reference_data(db, rng)

    if db.has_orders_for_day(target_day) and not force:
        raise SystemExit(f'orders for {target_day.isoformat()} already exist; use --force to append anyway')

    order_id_start = db.next_id('orders', 'order_id')
    order_item_id_start = db.next_id('order_items', 'order_item_id')
    payment_id_start = db.next_id('payments', 'payment_id')
    shipment_id_start = db.next_id('shipments', 'shipment_id')

    balances_list = db.fetch_inventory_balances()
    if not balances_list:
        balances_list = make_inventory_balances(products, warehouses, rng, dt.combine(target_day, dt.min.time()))
        db.insert_inventory_balances(balances_list)
    inventory_balances = build_inventory_index(balances_list)

    orders, order_items, payments, shipments, movements = simulate_orders_for_day(
        target_day,
        n_orders,
        customers,
        products,
        rng,
        order_id_start,
        order_item_id_start,
        payment_id_start,
        shipment_id_start,
        inventory_balances,
    )

    db.insert_orders(orders)
    db.insert_order_items(order_items)
    db.insert_payments(payments)
    db.insert_shipments(shipments)
    db.insert_inventory_movements(movements)

    return db.run_delete_flow(rng, customer_delete_probability, product_delete_probability, warehouse_delete_probability)


def full_run(rng: random.Random, db: SQLiteBackend, customer_delete_probability: float, product_delete_probability: float, warehouse_delete_probability: float) -> tuple[int, int, int]:
    db.ensure_ready()
    db.reset()
    customers = make_customers(DEFAULT_CUSTOMERS, rng)
    products = make_products(DEFAULT_PRODUCTS, rng)
    warehouses = make_warehouses(rng, DEFAULT_WAREHOUSES)
    orders, order_items, payments, shipments = simulate_orders(DEFAULT_ORDERS, customers, products, rng)
    persist_reference_data(db, customers, products, warehouses)
    db.insert_orders(orders)
    db.insert_order_items(order_items)
    db.insert_payments(payments)
    db.insert_shipments(shipments)
    return db.run_delete_flow(rng, customer_delete_probability, product_delete_probability, warehouse_delete_probability)


def main() -> None:
    args = parse_args()
    rng = random.Random(SEED)
    db = backend_from_args(args)

    if args.reset or not args.date:
        deleted_counts = full_run(rng, db, args.customer_delete_probability, args.product_delete_probability, args.warehouse_delete_probability)
    else:
        deleted_counts = daily_run(date.fromisoformat(args.date), args.orders, args.force, db, args.customer_delete_probability, args.product_delete_probability, args.warehouse_delete_probability)

    print('Generation complete')
    if args.date:
        print(f'date: {args.date}')
    print(f'deleted_customers: {deleted_counts[0]}')
    print(f'deleted_products: {deleted_counts[1]}')
    print(f'deleted_warehouses: {deleted_counts[2]}')
    print(f'db_path: {db.path}')


if __name__ == '__main__':
    main()