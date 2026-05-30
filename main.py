from __future__ import annotations

import argparse
import hashlib
import random
from dataclasses import asdict
from datetime import date, datetime as dt, timedelta

from sqlalchemy import Connection, Engine, delete, func, insert, select, update

from src import db
from src.config import (
    DEFAULT_CUSTOMERS,
    DEFAULT_DB_URL,
    DEFAULT_ORDERS,
    DEFAULT_PRODUCTS,
    DEFAULT_WAREHOUSES,
    RETURN_LOOKBACK_DAYS,
    SEED,
    SIMULATION_START_DATE,
    SIMULATION_WINDOW_DAYS,
)
from src.generators import (
    make_customers,
    make_inventory_balances,
    make_products,
    make_warehouses,
)
from src.models import Customer, InventoryBalance, Product, Warehouse
from src.simulator import DayResult, IdCounters, ReturnCandidate, World, simulate_day


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate ecommerce source data into a SQL database')
    parser.add_argument('--db-url', default=DEFAULT_DB_URL, help='SQLAlchemy database URL (e.g. sqlite:///datagen.db, mysql+pymysql://user:pw@host/db)')
    parser.add_argument('--date', help='Generate data for a specific day in YYYY-MM-DD format')
    parser.add_argument('--orders', type=int, default=DEFAULT_ORDERS, help='Number of orders to generate')
    parser.add_argument('--clear-day', dest='clear_day', action='store_true', help='Delete every row for --date across all tables and reverse the day\'s effect on inventory_balances. Generates nothing on its own.')
    parser.add_argument('--reset', action='store_true', help='Drop and recreate all tables, then regenerate from scratch')
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def bulk_insert(conn: Connection, table, instances) -> None:
    if not instances:
        return
    conn.execute(insert(table), [asdict(i) for i in instances])


def max_id(conn: Connection, table, column_name: str) -> int:
    result = conn.execute(select(func.max(table.c[column_name]))).scalar()
    return int(result) if result is not None else 0


def read_id_counters(conn: Connection) -> IdCounters:
    return IdCounters(
        order_id=max_id(conn, db.orders, 'order_id') + 1,
        order_item_id=max_id(conn, db.order_items, 'order_item_id') + 1,
        payment_id=max_id(conn, db.payments, 'payment_id') + 1,
        shipment_id=max_id(conn, db.shipments, 'shipment_id') + 1,
        movement_id=max_id(conn, db.inventory_movements, 'movement_id') + 1,
        return_id=max_id(conn, db.returns, 'return_id') + 1,
    )


_DELETION_TARGETS = {
    'customer':  (lambda: db.customers,  lambda: db.customers.c.customer_id),
    'product':   (lambda: db.products,   lambda: db.products.c.product_id),
    'warehouse': (lambda: db.warehouses, lambda: db.warehouses.c.warehouse_id),
}


def persist_day_result(conn: Connection, result: DayResult) -> None:
    bulk_insert(conn, db.orders, result.orders)
    bulk_insert(conn, db.order_items, result.order_items)
    bulk_insert(conn, db.payments, result.payments)
    bulk_insert(conn, db.shipments, result.shipments)
    bulk_insert(conn, db.inventory_movements, result.movements)
    bulk_insert(conn, db.returns, result.returns)
    for ev in result.deletions:
        table_fn, key_fn = _DELETION_TARGETS[ev.entity]
        conn.execute(update(table_fn()).where(key_fn() == ev.entity_id).values(deleted_at=ev.deleted_at))


def fetch_return_candidates(conn: Connection, day: date, lookback_days: int = RETURN_LOOKBACK_DAYS) -> list[ReturnCandidate]:
    """Items delivered in [day - lookback, day - 1] that have not already been returned."""
    window_start = dt.combine(day - timedelta(days=lookback_days), dt.min.time())
    window_end = dt.combine(day, dt.min.time())
    already_returned = select(db.returns.c.order_item_id)
    stmt = (
        select(
            db.orders.c.order_id,
            db.order_items.c.order_item_id,
            db.order_items.c.product_id,
            db.order_items.c.warehouse_id,
            db.order_items.c.quantity,
            db.order_items.c.unit_price,
            db.shipments.c.delivered_at,
        )
        .select_from(
            db.shipments
            .join(db.orders, db.shipments.c.order_id == db.orders.c.order_id)
            .join(db.order_items, db.orders.c.order_id == db.order_items.c.order_id)
        )
        .where(db.shipments.c.shipment_status == 'delivered')
        .where(db.shipments.c.delivered_at >= window_start)
        .where(db.shipments.c.delivered_at < window_end)
        .where(~db.order_items.c.order_item_id.in_(already_returned))
    )
    return [ReturnCandidate(**dict(r)) for r in conn.execute(stmt).mappings()]


def collect_delivered_candidates(result: DayResult) -> list[ReturnCandidate]:
    """Pull newly-delivered line items out of a DayResult so they can feed future days' returns."""
    delivered_orders = {s.order_id: s.delivered_at for s in result.shipments if s.shipment_status == 'delivered'}
    return [
        ReturnCandidate(
            order_id=item.order_id,
            order_item_id=item.order_item_id,
            product_id=item.product_id,
            warehouse_id=item.warehouse_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            delivered_at=delivered_orders[item.order_id],
        )
        for item in result.order_items
        if item.order_id in delivered_orders
    ]


def insert_balances(conn: Connection, balances: dict[tuple[int, int], InventoryBalance]) -> None:
    bulk_insert(conn, db.inventory_balances, list(balances.values()))


def update_balances(conn: Connection, balances: dict[tuple[int, int], InventoryBalance]) -> None:
    col = db.inventory_balances.c
    for b in balances.values():
        conn.execute(
            update(db.inventory_balances)
            .where(col.product_id == b.product_id)
            .where(col.warehouse_id == b.warehouse_id)
            .values(
                stock_on_hand=b.stock_on_hand,
                reserved_quantity=b.reserved_quantity,
                available_quantity=b.available_quantity,
                reorder_point=b.reorder_point,
                reorder_quantity=b.reorder_quantity,
                updated_at=b.updated_at,
            )
        )


# ---------------------------------------------------------------------------
# World construction / loading
# ---------------------------------------------------------------------------


def build_world(rng: random.Random, balance_updated_at: dt) -> World:
    customers = make_customers(DEFAULT_CUSTOMERS, rng)
    products = make_products(DEFAULT_PRODUCTS, rng)
    warehouses = make_warehouses(DEFAULT_WAREHOUSES, rng)
    balances_list = make_inventory_balances(products, warehouses, rng, balance_updated_at)
    balances = {(b.product_id, b.warehouse_id): b for b in balances_list}
    return World(customers=customers, products=products, warehouses=warehouses, balances=balances)


def persist_world(conn: Connection, world: World) -> None:
    bulk_insert(conn, db.customers, world.customers)
    bulk_insert(conn, db.products, world.products)
    bulk_insert(conn, db.warehouses, world.warehouses)
    insert_balances(conn, world.balances)


def load_or_build_world(conn: Connection, rng: random.Random, balance_updated_at: dt) -> World:
    customers = [Customer(**dict(r)) for r in conn.execute(select(db.customers)).mappings()]
    products = [Product(**dict(r)) for r in conn.execute(select(db.products)).mappings()]
    warehouses = [Warehouse(**dict(r)) for r in conn.execute(select(db.warehouses)).mappings()]
    balance_rows = conn.execute(select(db.inventory_balances)).mappings().all()

    populated = [bool(x) for x in (customers, products, warehouses, balance_rows)]
    if all(populated):
        balances = {(r['product_id'], r['warehouse_id']): InventoryBalance(**dict(r)) for r in balance_rows}
        return World(customers, products, warehouses, balances)
    if any(populated):
        raise SystemExit('reference data is partially populated; run with --reset to regenerate')

    world = build_world(rng, balance_updated_at)
    persist_world(conn, world)
    return world


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------


def make_daily_rng(target_day: date) -> random.Random:
    digest = hashlib.blake2b(target_day.isoformat().encode(), digest_size=8).digest()
    return random.Random(SEED ^ int.from_bytes(digest, 'big'))


def full_run(engine: Engine) -> None:
    """Drop + recreate the schema, then simulate SIMULATION_WINDOW_DAYS days."""
    db.init_schema(engine, drop_first=True)
    rng = random.Random(SEED)
    world = build_world(rng, dt.combine(SIMULATION_START_DATE, dt.min.time()))
    ids = IdCounters()

    base = DEFAULT_ORDERS // SIMULATION_WINDOW_DAYS
    remainder = DEFAULT_ORDERS - base * SIMULATION_WINDOW_DAYS

    pending: list[ReturnCandidate] = []  # delivered items waiting their return window

    with engine.begin() as conn:
        persist_world(conn, world)
        for offset in range(SIMULATION_WINDOW_DAYS):
            day = SIMULATION_START_DATE + timedelta(days=offset)
            day_start = dt.combine(day, dt.min.time())
            window_start = day_start - timedelta(days=RETURN_LOOKBACK_DAYS)

            today_candidates = [c for c in pending if window_start <= c.delivered_at < day_start]

            n = base + (1 if offset < remainder else 0)
            result = simulate_day(day, n, world, ids, make_daily_rng(day), today_candidates)
            persist_day_result(conn, result)

            # Drop expired candidates and any item that returned today; add this day's deliveries.
            returned_item_ids = {r.order_item_id for r in result.returns}
            pending = [c for c in pending if c.delivered_at >= window_start and c.order_item_id not in returned_item_ids]
            pending.extend(collect_delivered_candidates(result))

        update_balances(conn, world.balances)


def daily_run(engine: Engine, target_day: date, n_orders: int) -> None:
    db.init_schema(engine, drop_first=False)
    with engine.begin() as conn:
        rng = make_daily_rng(target_day)
        world = load_or_build_world(conn, rng, dt.combine(target_day, dt.min.time()))
        ids = read_id_counters(conn)
        candidates = fetch_return_candidates(conn, target_day)
        result = simulate_day(target_day, n_orders, world, ids, rng, candidates)
        persist_day_result(conn, result)
        update_balances(conn, world.balances)


def clear_day(conn: Connection, target_day: date) -> int:
    """Delete every row generated for `target_day` and reverse the day's effect on inventory_balances."""
    day_start = dt.combine(target_day, dt.min.time())
    day_end = day_start + timedelta(days=1)

    order_ids = [
        row[0]
        for row in conn.execute(
            select(db.orders.c.order_id).where(
                db.orders.c.order_created_at >= day_start,
                db.orders.c.order_created_at < day_end,
            )
        )
    ]

    order_item_ids = [
        row[0]
        for row in conn.execute(
            select(db.order_items.c.order_item_id).where(db.order_items.c.order_id.in_(order_ids))
        )
    ] if order_ids else []

    mv = db.inventory_movements.c
    movement_filter = mv.movement_created_at >= day_start
    movement_filter = movement_filter & (mv.movement_created_at < day_end)
    if order_item_ids:
        movement_filter = movement_filter | mv.order_item_id.in_(order_item_ids)

    movements = conn.execute(select(db.inventory_movements).where(movement_filter)).mappings().all()

    for m in movements:
        qc = m['quantity_change']
        col = db.inventory_balances.c
        if m['movement_type'] in ('sale_reservation', 'release'):
            updates = {'reserved_quantity': col.reserved_quantity + qc, 'available_quantity': col.available_quantity - qc}
        elif m['movement_type'] == 'shipment_deduction':
            updates = {'reserved_quantity': col.reserved_quantity - qc, 'stock_on_hand': col.stock_on_hand - qc}
        elif m['movement_type'] in ('restock', 'return_restock'):
            updates = {'stock_on_hand': col.stock_on_hand - qc, 'available_quantity': col.available_quantity - qc}
        else:
            continue
        conn.execute(
            update(db.inventory_balances)
            .where(db.inventory_balances.c.product_id == m['product_id'])
            .where(db.inventory_balances.c.warehouse_id == m['warehouse_id'])
            .values(**updates)
        )

    rt = db.returns.c
    returns_filter = (rt.returned_at >= day_start) & (rt.returned_at < day_end)
    if order_item_ids:
        returns_filter = returns_filter | rt.order_item_id.in_(order_item_ids)
    conn.execute(delete(db.returns).where(returns_filter))

    conn.execute(delete(db.inventory_movements).where(movement_filter))

    if order_ids:
        for table in (db.shipments, db.payments, db.order_items, db.orders):
            conn.execute(delete(table).where(table.c.order_id.in_(order_ids)))

    for table in (db.customers, db.products, db.warehouses):
        conn.execute(
            update(table)
            .where(table.c.deleted_at >= day_start)
            .where(table.c.deleted_at < day_end)
            .values(deleted_at=None)
        )

    return len(order_ids)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()
    engine = db.make_engine(args.db_url)

    if args.clear_day and not args.date:
        raise SystemExit('--clear-day requires --date')

    if args.reset:
        full_run(engine)
        print('Generation complete')
    elif args.clear_day:
        target_day = date.fromisoformat(args.date)
        db.init_schema(engine, drop_first=False)
        with engine.begin() as conn:
            removed = clear_day(conn, target_day)
        print(f'Cleared {removed} orders for {args.date}')
    elif args.date:
        daily_run(engine, date.fromisoformat(args.date), args.orders)
        print(f'Generation complete')
        print(f'date: {args.date}')
    else:
        full_run(engine)
        print('Generation complete')

    print(f'db_url: {args.db_url}')


if __name__ == '__main__':
    main()
