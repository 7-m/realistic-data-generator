from __future__ import annotations

from datetime import date

import main
from src import db
from tests.conftest import count, fetch_all, orders_for_day


# Pick three dates clearly outside the --reset 180-day window starting 2024-01-01.
DAY1 = date(2024, 9, 1)
DAY2 = date(2024, 9, 2)
DAY3 = date(2024, 9, 3)
DAILY_ORDERS = 20


def _balances_snapshot(engine):
    return {
        (b['product_id'], b['warehouse_id']): (b['stock_on_hand'], b['reserved_quantity'], b['available_quantity'])
        for b in fetch_all(engine, db.inventory_balances)
    }


def _clear(engine, day):
    with engine.begin() as conn:
        return main.clear_day(conn, day)


def test_single_day_appends_rows(reset_engine):
    base_orders = count(reset_engine, db.orders)
    base_items = count(reset_engine, db.order_items)
    base_movements = count(reset_engine, db.inventory_movements)

    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)

    assert count(reset_engine, db.orders) == base_orders + DAILY_ORDERS
    assert len(orders_for_day(reset_engine, DAY1)) == DAILY_ORDERS
    items_added = count(reset_engine, db.order_items) - base_items
    movements_added = count(reset_engine, db.inventory_movements) - base_movements
    assert DAILY_ORDERS <= items_added <= DAILY_ORDERS * 5
    assert movements_added == 2 * items_added


def test_multi_day_adds_keep_ids_monotonic_and_unique(reset_engine):
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    main.daily_run(reset_engine, DAY2, DAILY_ORDERS)
    main.daily_run(reset_engine, DAY3, DAILY_ORDERS)

    for table, col in (
        (db.orders, 'order_id'),
        (db.order_items, 'order_item_id'),
        (db.payments, 'payment_id'),
        (db.shipments, 'shipment_id'),
        (db.inventory_movements, 'movement_id'),
    ):
        rows = fetch_all(reset_engine, table)
        ids = [r[col] for r in rows]
        assert len(ids) == len(set(ids)), f'duplicate {col} after multi-day adds'

    assert len(orders_for_day(reset_engine, DAY1)) == DAILY_ORDERS
    assert len(orders_for_day(reset_engine, DAY2)) == DAILY_ORDERS
    assert len(orders_for_day(reset_engine, DAY3)) == DAILY_ORDERS


def test_multi_day_preserves_inventory_state_across_runs(reset_engine):
    initial = _balances_snapshot(reset_engine)
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    after_day1 = _balances_snapshot(reset_engine)
    main.daily_run(reset_engine, DAY2, DAILY_ORDERS)
    after_day2 = _balances_snapshot(reset_engine)
    assert initial != after_day1
    assert after_day1 != after_day2


def test_running_same_day_twice_just_appends(reset_engine):
    """Without --clear-day, running --date for the same day twice doubles the data."""
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    assert len(orders_for_day(reset_engine, DAY1)) == 2 * DAILY_ORDERS


def test_clear_day_removes_only_target_day(reset_engine):
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    main.daily_run(reset_engine, DAY2, DAILY_ORDERS)
    main.daily_run(reset_engine, DAY3, DAILY_ORDERS)

    day1_before = {o['order_id'] for o in orders_for_day(reset_engine, DAY1)}
    day3_before = {o['order_id'] for o in orders_for_day(reset_engine, DAY3)}

    removed = _clear(reset_engine, DAY2)
    assert removed == DAILY_ORDERS

    assert {o['order_id'] for o in orders_for_day(reset_engine, DAY1)} == day1_before
    assert {o['order_id'] for o in orders_for_day(reset_engine, DAY3)} == day3_before
    assert orders_for_day(reset_engine, DAY2) == []


def test_clear_day_does_not_orphan_child_rows(reset_engine):
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    main.daily_run(reset_engine, DAY2, DAILY_ORDERS)
    _clear(reset_engine, DAY2)

    orders = {r['order_id'] for r in fetch_all(reset_engine, db.orders)}
    items = {r['order_item_id'] for r in fetch_all(reset_engine, db.order_items)}

    for table in (db.order_items, db.payments, db.shipments):
        for r in fetch_all(reset_engine, table):
            assert r['order_id'] in orders, f'{table.name} has orphan order_id={r["order_id"]}'

    for m in fetch_all(reset_engine, db.inventory_movements):
        if m['order_id'] is not None:
            assert m['order_id'] in orders
        if m['order_item_id'] is not None:
            assert m['order_item_id'] in items


def test_clear_day_reverses_inventory_state(reset_engine):
    """clear_day on the only post-reset day must restore inventory_balances exactly."""
    before = _balances_snapshot(reset_engine)
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    assert _balances_snapshot(reset_engine) != before, 'sanity: daily run should mutate balances'
    _clear(reset_engine, DAY1)
    assert _balances_snapshot(reset_engine) == before


def test_clear_day_cancels_a_double_run(reset_engine):
    """Running a day twice and then clearing it must remove all of that day's rows and effects."""
    before = _balances_snapshot(reset_engine)
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    assert len(orders_for_day(reset_engine, DAY1)) == 2 * DAILY_ORDERS
    _clear(reset_engine, DAY1)
    assert orders_for_day(reset_engine, DAY1) == []
    assert _balances_snapshot(reset_engine) == before


def test_clear_day_on_unknown_day_is_noop(reset_engine):
    before_orders = count(reset_engine, db.orders)
    before_balances = _balances_snapshot(reset_engine)
    removed = _clear(reset_engine, DAY1)
    assert removed == 0
    assert count(reset_engine, db.orders) == before_orders
    assert _balances_snapshot(reset_engine) == before_balances


def test_movement_id_continues_from_max_after_daily(reset_engine):
    pre_max = max(m['movement_id'] for m in fetch_all(reset_engine, db.inventory_movements))
    main.daily_run(reset_engine, DAY1, DAILY_ORDERS)
    new_movements = [m for m in fetch_all(reset_engine, db.inventory_movements) if m['movement_id'] > pre_max]
    assert new_movements
    new_ids = sorted(m['movement_id'] for m in new_movements)
    assert new_ids[0] == pre_max + 1
    assert new_ids == list(range(new_ids[0], new_ids[-1] + 1))


def test_daily_run_on_fresh_db_creates_schema_and_reference_data(engine, small_defaults):
    main.daily_run(engine, DAY1, DAILY_ORDERS)
    assert count(engine, db.customers) > 0
    assert count(engine, db.products) > 0
    assert count(engine, db.warehouses) > 0
    assert count(engine, db.inventory_balances) > 0
    assert len(orders_for_day(engine, DAY1)) == DAILY_ORDERS
