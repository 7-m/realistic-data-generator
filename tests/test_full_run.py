from __future__ import annotations

from sqlalchemy import select

from src import db
from tests.conftest import (
    SMALL_CUSTOMERS,
    SMALL_ORDERS,
    SMALL_PRODUCTS,
    SMALL_WAREHOUSES,
    count,
    fetch_all,
)


def test_reset_creates_all_tables_with_expected_row_counts(reset_engine):
    assert count(reset_engine, db.customers) == SMALL_CUSTOMERS
    assert count(reset_engine, db.products) == SMALL_PRODUCTS
    assert count(reset_engine, db.warehouses) == SMALL_WAREHOUSES
    assert count(reset_engine, db.inventory_balances) == SMALL_PRODUCTS * SMALL_WAREHOUSES
    assert count(reset_engine, db.orders) == SMALL_ORDERS
    # Each order has 1-5 line items, each line item has 2 movements (reservation + release/deduction)
    items = count(reset_engine, db.order_items)
    assert SMALL_ORDERS <= items <= SMALL_ORDERS * 5
    # Each item produces 2 movements (reservation + release/deduction); each return adds one more.
    returns = count(reset_engine, db.returns)
    assert count(reset_engine, db.inventory_movements) == 2 * items + returns


def test_reset_pks_are_unique(reset_engine):
    for table, col in (
        (db.customers, 'customer_id'),
        (db.products, 'product_id'),
        (db.warehouses, 'warehouse_id'),
        (db.orders, 'order_id'),
        (db.order_items, 'order_item_id'),
        (db.payments, 'payment_id'),
        (db.shipments, 'shipment_id'),
        (db.inventory_movements, 'movement_id'),
    ):
        rows = fetch_all(reset_engine, table)
        ids = [r[col] for r in rows]
        assert len(ids) == len(set(ids)), f'duplicate {col} in {table.name}'


def test_reset_inventory_balances_composite_pk_unique(reset_engine):
    rows = fetch_all(reset_engine, db.inventory_balances)
    keys = [(r['product_id'], r['warehouse_id']) for r in rows]
    assert len(keys) == len(set(keys))


def test_reset_all_fks_resolve(reset_engine):
    customers = {r['customer_id'] for r in fetch_all(reset_engine, db.customers)}
    products = {r['product_id'] for r in fetch_all(reset_engine, db.products)}
    warehouses = {r['warehouse_id'] for r in fetch_all(reset_engine, db.warehouses)}
    orders = {r['order_id'] for r in fetch_all(reset_engine, db.orders)}
    items = {r['order_item_id'] for r in fetch_all(reset_engine, db.order_items)}

    for o in fetch_all(reset_engine, db.orders):
        assert o['customer_id'] in customers
    for it in fetch_all(reset_engine, db.order_items):
        assert it['order_id'] in orders
        assert it['product_id'] in products
        assert it['warehouse_id'] in warehouses
    for p in fetch_all(reset_engine, db.payments):
        assert p['order_id'] in orders
    for s in fetch_all(reset_engine, db.shipments):
        assert s['order_id'] in orders
    for m in fetch_all(reset_engine, db.inventory_movements):
        assert m['product_id'] in products
        assert m['warehouse_id'] in warehouses
        if m['order_id'] is not None:
            assert m['order_id'] in orders
        if m['order_item_id'] is not None:
            assert m['order_item_id'] in items
    for b in fetch_all(reset_engine, db.inventory_balances):
        assert b['product_id'] in products
        assert b['warehouse_id'] in warehouses


def test_delivered_shipments_imply_delivered_order(reset_engine):
    with reset_engine.connect() as conn:
        bad = conn.execute(
            select(db.orders.c.order_id)
            .select_from(db.orders.join(db.shipments, db.orders.c.order_id == db.shipments.c.order_id))
            .where(db.shipments.c.shipment_status == 'delivered')
            .where(db.orders.c.order_status != 'delivered')
        ).all()
    assert bad == []


def test_failed_shipments_have_null_shipped_at(reset_engine):
    with reset_engine.connect() as conn:
        bad = conn.execute(
            select(db.shipments.c.shipment_id)
            .where(db.shipments.c.shipment_status == 'failed')
            .where(db.shipments.c.shipped_at.is_not(None))
        ).all()
    assert bad == []


def test_payments_amount_matches_order_for_captured(reset_engine):
    """Captured payment amount equals order_total per simulator contract."""
    with reset_engine.connect() as conn:
        rows = conn.execute(
            select(db.payments.c.amount, db.orders.c.order_total)
            .select_from(db.payments.join(db.orders, db.payments.c.order_id == db.orders.c.order_id))
            .where(db.payments.c.payment_status == 'captured')
        ).all()
    assert rows
    for amount, total in rows:
        assert amount == total, f'captured amount {amount} != order_total {total}'


def test_inventory_movement_quantity_signs(reset_engine):
    """Reservations and shipment_deductions are negative; releases and restocks are positive."""
    for row in fetch_all(reset_engine, db.inventory_movements):
        if row['movement_type'] in {'sale_reservation', 'shipment_deduction'}:
            assert row['quantity_change'] < 0, row
        elif row['movement_type'] in {'release', 'restock', 'return_restock'}:
            assert row['quantity_change'] > 0, row
        else:
            raise AssertionError(f'unknown movement_type: {row["movement_type"]!r}')
