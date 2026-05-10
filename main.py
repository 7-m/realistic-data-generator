from __future__ import annotations

import argparse
import random
from datetime import date, datetime as dt

from src.config import DEFAULT_CUSTOMERS, DEFAULT_ORDERS, DEFAULT_PRODUCTS, DEFAULT_WAREHOUSES, OUTPUT_DIR, SEED
from src.generators import make_customers, make_products
from src.inventory import build_inventory_index, make_inventory_balances, make_warehouses
from src.models import Customer, InventoryBalance, Product, Warehouse
from src.simulator import simulate_orders, simulate_orders_for_day
from src.writers import append_csv, infer_dataclass_value, load_dataclass_rows, read_csv, write_csv


def iso(dt):
    return dt.isoformat(sep=' ') if dt else ''


def money(value: float) -> str:
    return f'{value:.2f}'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate ecommerce source data')
    parser.add_argument('--date', help='Generate data for a specific day in YYYY-MM-DD format')
    parser.add_argument('--orders', type=int, default=DEFAULT_ORDERS, help='Number of orders to generate')
    parser.add_argument('--force', action='store_true', help='Overwrite existing rows for the given date')
    parser.add_argument('--reset', action='store_true', help='Regenerate all datasets from scratch')
    return parser.parse_args()


def load_or_create_reference_data(rng: random.Random) -> tuple[list[Customer], list[Product], list[Warehouse]]:
    customers_path = OUTPUT_DIR / 'customers.csv'
    products_path = OUTPUT_DIR / 'products.csv'
    warehouses_path = OUTPUT_DIR / 'warehouses.csv'
    if customers_path.exists() and products_path.exists() and warehouses_path.exists():
        return load_dataclass_rows(customers_path, Customer), load_dataclass_rows(products_path, Product), load_dataclass_rows(warehouses_path, Warehouse)
    customers = make_customers(DEFAULT_CUSTOMERS, rng)
    products = make_products(DEFAULT_PRODUCTS, rng)
    warehouses = make_warehouses(rng, DEFAULT_WAREHOUSES)
    write_csv(
        customers_path,
        ['customer_id', 'customer_name', 'email', 'created_at', 'city', 'country'],
        [{'customer_id': str(c.customer_id), 'customer_name': c.customer_name, 'email': c.email, 'created_at': iso(c.created_at), 'city': c.city, 'country': c.country} for c in customers],
    )
    write_csv(
        products_path,
        ['product_id', 'product_name', 'category', 'brand', 'unit_price', 'unit_cost'],
        [{'product_id': str(p.product_id), 'product_name': p.product_name, 'category': p.category, 'brand': p.brand, 'unit_price': money(p.unit_price), 'unit_cost': money(p.unit_cost)} for p in products],
    )
    write_csv(
        warehouses_path,
        ['warehouse_id', 'warehouse_name', 'city', 'country'],
        [{'warehouse_id': str(w.warehouse_id), 'warehouse_name': w.warehouse_name, 'city': w.city, 'country': w.country} for w in warehouses],
    )
    return customers, products, warehouses


def max_id(path, column: str) -> int:
    if not path.exists():
        return 0
    rows = read_csv(path)
    return max((int(infer_dataclass_value(row[column])) for row in rows), default=0)


def daily_run(target_day: date, n_orders: int, force: bool) -> None:
    rng = random.Random(SEED + int(target_day.strftime('%Y%m%d')))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    customers, products, warehouses = load_or_create_reference_data(rng)

    orders_path = OUTPUT_DIR / 'orders.csv'
    if orders_path.exists() and not force:
        existing = read_csv(orders_path)
        if any(row['order_created_at'].startswith(target_day.isoformat()) for row in existing):
            raise SystemExit(f'orders for {target_day.isoformat()} already exist; use --force to append anyway')

    order_id_start = max_id(orders_path, 'order_id') + 1
    order_item_id_start = max_id(OUTPUT_DIR / 'order_items.csv', 'order_item_id') + 1
    payment_id_start = max_id(OUTPUT_DIR / 'payments.csv', 'payment_id') + 1
    shipment_id_start = max_id(OUTPUT_DIR / 'shipments.csv', 'shipment_id') + 1
    inventory_path = OUTPUT_DIR / 'inventory_balances.csv'
    if inventory_path.exists() and not force:
        balances_list = load_dataclass_rows(inventory_path, InventoryBalance)
        inventory_balances = build_inventory_index(balances_list)
    else:
        balances_list = make_inventory_balances(products, warehouses, rng, dt.combine(target_day, dt.min.time()))
        write_csv(
            inventory_path,
            ['product_id', 'warehouse_id', 'stock_on_hand', 'reserved_quantity', 'available_quantity', 'reorder_point', 'reorder_quantity', 'updated_at'],
            [{'product_id': str(b.product_id), 'warehouse_id': str(b.warehouse_id), 'stock_on_hand': str(b.stock_on_hand), 'reserved_quantity': str(b.reserved_quantity), 'available_quantity': str(b.available_quantity), 'reorder_point': str(b.reorder_point), 'reorder_quantity': str(b.reorder_quantity), 'updated_at': iso(b.updated_at)} for b in balances_list],
        )
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

    append_csv(
        orders_path,
        ['order_id', 'customer_id', 'order_created_at', 'order_status', 'channel', 'order_total'],
        [{'order_id': str(o.order_id), 'customer_id': str(o.customer_id), 'order_created_at': iso(o.order_created_at), 'order_status': o.order_status, 'channel': o.channel, 'order_total': money(o.order_total)} for o in orders],
    )
    append_csv(
        OUTPUT_DIR / 'order_items.csv',
        ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'line_total'],
        [{'order_item_id': str(i.order_item_id), 'order_id': str(i.order_id), 'product_id': str(i.product_id), 'quantity': str(i.quantity), 'unit_price': money(i.unit_price), 'line_total': money(i.line_total)} for i in order_items],
    )
    append_csv(
        OUTPUT_DIR / 'payments.csv',
        ['payment_id', 'order_id', 'payment_created_at', 'payment_method', 'payment_status', 'amount'],
        [{'payment_id': str(p.payment_id), 'order_id': str(p.order_id), 'payment_created_at': iso(p.payment_created_at), 'payment_method': p.payment_method, 'payment_status': p.payment_status, 'amount': money(p.amount)} for p in payments],
    )
    append_csv(
        OUTPUT_DIR / 'shipments.csv',
        ['shipment_id', 'order_id', 'shipment_status', 'shipped_at', 'delivered_at', 'carrier'],
        [{'shipment_id': str(s.shipment_id), 'order_id': str(s.order_id), 'shipment_status': s.shipment_status, 'shipped_at': iso(s.shipped_at), 'delivered_at': iso(s.delivered_at), 'carrier': s.carrier} for s in shipments],
    )
    append_csv(
        OUTPUT_DIR / 'inventory_movements.csv',
        ['movement_id', 'product_id', 'warehouse_id', 'order_id', 'order_item_id', 'movement_type', 'quantity_change', 'movement_created_at', 'reason'],
        [{'movement_id': str(m.movement_id), 'product_id': str(m.product_id), 'warehouse_id': str(m.warehouse_id), 'order_id': '' if m.order_id is None else str(m.order_id), 'order_item_id': '' if m.order_item_id is None else str(m.order_item_id), 'movement_type': m.movement_type, 'quantity_change': str(m.quantity_change), 'movement_created_at': iso(m.movement_created_at), 'reason': m.reason} for m in movements],
    )


def full_run(rng: random.Random) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    customers = make_customers(DEFAULT_CUSTOMERS, rng)
    products = make_products(DEFAULT_PRODUCTS, rng)
    orders, order_items, payments, shipments = simulate_orders(DEFAULT_ORDERS, customers, products, rng)

    write_csv(
        OUTPUT_DIR / 'customers.csv',
        ['customer_id', 'customer_name', 'email', 'created_at', 'city', 'country'],
        [{'customer_id': str(c.customer_id), 'customer_name': c.customer_name, 'email': c.email, 'created_at': iso(c.created_at), 'city': c.city, 'country': c.country} for c in customers],
    )
    write_csv(
        OUTPUT_DIR / 'products.csv',
        ['product_id', 'product_name', 'category', 'brand', 'unit_price', 'unit_cost'],
        [{'product_id': str(p.product_id), 'product_name': p.product_name, 'category': p.category, 'brand': p.brand, 'unit_price': money(p.unit_price), 'unit_cost': money(p.unit_cost)} for p in products],
    )
    write_csv(
        OUTPUT_DIR / 'orders.csv',
        ['order_id', 'customer_id', 'order_created_at', 'order_status', 'channel', 'order_total'],
        [{'order_id': str(o.order_id), 'customer_id': str(o.customer_id), 'order_created_at': iso(o.order_created_at), 'order_status': o.order_status, 'channel': o.channel, 'order_total': money(o.order_total)} for o in orders],
    )
    write_csv(
        OUTPUT_DIR / 'order_items.csv',
        ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'line_total'],
        [{'order_item_id': str(i.order_item_id), 'order_id': str(i.order_id), 'product_id': str(i.product_id), 'quantity': str(i.quantity), 'unit_price': money(i.unit_price), 'line_total': money(i.line_total)} for i in order_items],
    )
    write_csv(
        OUTPUT_DIR / 'payments.csv',
        ['payment_id', 'order_id', 'payment_created_at', 'payment_method', 'payment_status', 'amount'],
        [{'payment_id': str(p.payment_id), 'order_id': str(p.order_id), 'payment_created_at': iso(p.payment_created_at), 'payment_method': p.payment_method, 'payment_status': p.payment_status, 'amount': money(p.amount)} for p in payments],
    )
    write_csv(
        OUTPUT_DIR / 'shipments.csv',
        ['shipment_id', 'order_id', 'shipment_status', 'shipped_at', 'delivered_at', 'carrier'],
        [{'shipment_id': str(s.shipment_id), 'order_id': str(s.order_id), 'shipment_status': s.shipment_status, 'shipped_at': iso(s.shipped_at), 'delivered_at': iso(s.delivered_at), 'carrier': s.carrier} for s in shipments],
    )


def main() -> None:
    args = parse_args()
    rng = random.Random(SEED)

    if args.reset:
        full_run(rng)
    elif args.date:
        daily_run(date.fromisoformat(args.date), args.orders, args.force)
    else:
        full_run(rng)

    print('Generation complete')
    if args.date:
        print(f'date: {args.date}')
    print(f'output_dir: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
