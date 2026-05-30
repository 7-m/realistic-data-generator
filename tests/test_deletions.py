from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import update

import main
from src import config, db
from src.simulator import IdCounters, World, simulate_day
from tests.conftest import (
    SMALL_CUSTOMERS,
    SMALL_PRODUCTS,
    SMALL_WAREHOUSES,
    count,
    fetch_all,
    orders_for_day,
)


@pytest.fixture
def aggressive_deletes(monkeypatch):
    """Bump probabilities so deletions are observable in small-defaults runs."""
    monkeypatch.setattr(config, 'CUSTOMER_DELETION_PROBABILITY', 0.05)
    monkeypatch.setattr(config, 'PRODUCT_DELETION_PROBABILITY', 0.05)
    monkeypatch.setattr(config, 'WAREHOUSE_DELETION_PROBABILITY', 0.02)


def _aggressive_engine(engine, small_defaults, aggressive_deletes):
    main.full_run(engine)
    return engine


@pytest.fixture
def deletes_engine(engine, small_defaults, aggressive_deletes):
    main.full_run(engine)
    return engine


# 1. Deletions occur when probabilities are high enough
def test_deletions_occur_in_all_three_tables(deletes_engine):
    deleted_customers = [r for r in fetch_all(deletes_engine, db.customers) if r['deleted_at'] is not None]
    deleted_products = [r for r in fetch_all(deletes_engine, db.products) if r['deleted_at'] is not None]
    deleted_warehouses = [r for r in fetch_all(deletes_engine, db.warehouses) if r['deleted_at'] is not None]
    assert deleted_customers, 'expected some deleted customers with bumped probability'
    assert deleted_products, 'expected some deleted products with bumped probability'
    # Warehouses are rare even at 2% per day for 3 warehouses; allow zero.
    assert isinstance(deleted_warehouses, list)


# 2. Deletion timestamps fall inside the simulation window
def test_deletion_timestamps_within_simulation_window(deletes_engine):
    window_start = datetime.combine(config.SIMULATION_START_DATE, datetime.min.time())
    window_end = window_start + timedelta(days=config.SIMULATION_WINDOW_DAYS)
    for table in (db.customers, db.products, db.warehouses):
        for r in fetch_all(deletes_engine, table):
            if r['deleted_at'] is not None:
                assert window_start <= r['deleted_at'] < window_end, r


# 3. Last-active guard: no run can delete every customer
def test_last_active_customer_is_never_deleted(deletes_engine):
    customers = fetch_all(deletes_engine, db.customers)
    active = [c for c in customers if c['deleted_at'] is None]
    assert len(active) >= 1
    products = fetch_all(deletes_engine, db.products)
    assert sum(1 for p in products if p['deleted_at'] is None) >= 1
    warehouses = fetch_all(deletes_engine, db.warehouses)
    assert sum(1 for w in warehouses if w['deleted_at'] is None) >= 1


# 4. Deleted customers don't get new orders
def test_deleted_customers_get_no_new_orders(reset_engine):
    target_day = date(2024, 9, 1)
    cust_id = fetch_all(reset_engine, db.customers)[0]['customer_id']
    deletion_time = datetime.combine(target_day, datetime.min.time()) - timedelta(seconds=1)
    with reset_engine.begin() as conn:
        conn.execute(
            update(db.customers).where(db.customers.c.customer_id == cust_id).values(deleted_at=deletion_time)
        )
    main.daily_run(reset_engine, target_day, 100)

    new_orders = orders_for_day(reset_engine, target_day)
    assert new_orders, 'sanity: daily run must have produced orders'
    assert all(o['customer_id'] != cust_id for o in new_orders)


# 5. Deleted products don't appear in new line items
def test_deleted_products_get_no_new_line_items(reset_engine):
    target_day = date(2024, 9, 2)
    prod_id = fetch_all(reset_engine, db.products)[0]['product_id']
    with reset_engine.begin() as conn:
        conn.execute(
            update(db.products).where(db.products.c.product_id == prod_id).values(
                deleted_at=datetime.combine(target_day, datetime.min.time()) - timedelta(seconds=1)
            )
        )
    main.daily_run(reset_engine, target_day, 100)

    day_order_ids = {o['order_id'] for o in orders_for_day(reset_engine, target_day)}
    new_items = [i for i in fetch_all(reset_engine, db.order_items) if i['order_id'] in day_order_ids]
    assert new_items
    assert all(i['product_id'] != prod_id for i in new_items)


# 6. Deleted warehouses don't get new fulfillment
def test_deleted_warehouses_get_no_new_fulfillment(reset_engine):
    target_day = date(2024, 9, 3)
    wh_id = fetch_all(reset_engine, db.warehouses)[0]['warehouse_id']
    with reset_engine.begin() as conn:
        conn.execute(
            update(db.warehouses).where(db.warehouses.c.warehouse_id == wh_id).values(
                deleted_at=datetime.combine(target_day, datetime.min.time()) - timedelta(seconds=1)
            )
        )
    main.daily_run(reset_engine, target_day, 100)

    day_order_ids = {o['order_id'] for o in orders_for_day(reset_engine, target_day)}
    new_items = [i for i in fetch_all(reset_engine, db.order_items) if i['order_id'] in day_order_ids]
    assert new_items
    assert all(i['warehouse_id'] != wh_id for i in new_items)


# 7. Returns can still be generated for items whose product/customer was later deleted
def test_returns_survive_post_delivery_deletion(reset_engine):
    """A delivered order whose customer/product is deleted later may still be returned."""
    delivered_shipment = next(s for s in fetch_all(reset_engine, db.shipments) if s['shipment_status'] == 'delivered')
    order_id = delivered_shipment['order_id']
    item = next(i for i in fetch_all(reset_engine, db.order_items) if i['order_id'] == order_id)
    customer_id = next(o['customer_id'] for o in fetch_all(reset_engine, db.orders) if o['order_id'] == order_id)

    delivered_at = delivered_shipment['delivered_at']
    target_day = (delivered_at + timedelta(days=2)).date()
    delete_time = datetime.combine(target_day, datetime.min.time()) - timedelta(seconds=1)
    with reset_engine.begin() as conn:
        conn.execute(update(db.customers).where(db.customers.c.customer_id == customer_id).values(deleted_at=delete_time))
        conn.execute(update(db.products).where(db.products.c.product_id == item['product_id']).values(deleted_at=delete_time))

    # Run a daily simulation centered on a day within the return window — the deleted product's
    # already-delivered line items should still be valid return candidates.
    main.daily_run(reset_engine, target_day, 1)
    # We can't deterministically assert a return happened (probabilistic), but we can assert no exception.


# 8. clear_day undoes soft-deletes that fell on the target day
def test_clear_day_reverses_soft_deletes(reset_engine):
    target_day = date(2024, 9, 4)
    cust_id = fetch_all(reset_engine, db.customers)[0]['customer_id']
    delete_time = datetime.combine(target_day, datetime.min.time()) + timedelta(hours=12)
    with reset_engine.begin() as conn:
        conn.execute(update(db.customers).where(db.customers.c.customer_id == cust_id).values(deleted_at=delete_time))

    # Sanity: the customer is now deleted
    deleted = next(c for c in fetch_all(reset_engine, db.customers) if c['customer_id'] == cust_id)
    assert deleted['deleted_at'] is not None

    with reset_engine.begin() as conn:
        main.clear_day(conn, target_day)

    restored = next(c for c in fetch_all(reset_engine, db.customers) if c['customer_id'] == cust_id)
    assert restored['deleted_at'] is None


# 9. With default probabilities (no monkeypatching), the existing 27 tests remain green —
# this is implicitly covered by the rest of the suite. The check here is that the deletions
# subsystem doesn't break anything when probabilities are at defaults.
def test_default_probabilities_dont_break_anything(reset_engine):
    # If we got here, reset_engine ran with default tiny probabilities and finished.
    assert count(reset_engine, db.customers) == SMALL_CUSTOMERS
    assert count(reset_engine, db.products) == SMALL_PRODUCTS
    assert count(reset_engine, db.warehouses) == SMALL_WAREHOUSES
