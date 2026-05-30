from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

import main
from src import db
from tests.conftest import count, fetch_all


def test_reset_produces_returns(reset_engine):
    assert count(reset_engine, db.returns) > 0


def test_returns_fk_to_order_items_resolves(reset_engine):
    item_ids = {r['order_item_id'] for r in fetch_all(reset_engine, db.order_items)}
    for ret in fetch_all(reset_engine, db.returns):
        assert ret['order_item_id'] in item_ids


def test_only_delivered_items_are_returned(reset_engine):
    """Every returned order_item must belong to an order that was delivered."""
    delivered_orders = {
        s['order_id']
        for s in fetch_all(reset_engine, db.shipments)
        if s['shipment_status'] == 'delivered'
    }
    items = {i['order_item_id']: i['order_id'] for i in fetch_all(reset_engine, db.order_items)}
    for ret in fetch_all(reset_engine, db.returns):
        order_id = items[ret['order_item_id']]
        assert order_id in delivered_orders


def test_quantity_returned_does_not_exceed_original(reset_engine):
    items = {i['order_item_id']: i['quantity'] for i in fetch_all(reset_engine, db.order_items)}
    totals: dict[int, int] = {}
    for ret in fetch_all(reset_engine, db.returns):
        totals[ret['order_item_id']] = totals.get(ret['order_item_id'], 0) + ret['quantity_returned']
    for item_id, qty_returned in totals.items():
        assert qty_returned <= items[item_id], f'over-return on order_item {item_id}: {qty_returned} > {items[item_id]}'


def test_refund_amount_matches_quantity_times_unit_price(reset_engine):
    item_prices = {i['order_item_id']: i['unit_price'] for i in fetch_all(reset_engine, db.order_items)}
    for ret in fetch_all(reset_engine, db.returns):
        expected = round(ret['quantity_returned'] * item_prices[ret['order_item_id']], 2)
        assert ret['refund_amount'] == expected, ret


def test_returns_happen_after_delivery_within_window(reset_engine):
    """returned_at must fall in (delivered_at, delivered_at + 14 days]."""
    items = {i['order_item_id']: i['order_id'] for i in fetch_all(reset_engine, db.order_items)}
    delivered_at_by_order = {
        s['order_id']: s['delivered_at']
        for s in fetch_all(reset_engine, db.shipments)
        if s['delivered_at'] is not None
    }
    for ret in fetch_all(reset_engine, db.returns):
        order_id = items[ret['order_item_id']]
        delivered_at = delivered_at_by_order[order_id]
        delta = ret['returned_at'] - delivered_at
        assert timedelta(days=1) <= delta <= timedelta(days=14), (ret, delivered_at)


def test_each_return_has_paired_restock_movement(reset_engine):
    """Every Return row has a matching `return_restock` movement with the same qty and timestamp."""
    movements = [m for m in fetch_all(reset_engine, db.inventory_movements) if m['movement_type'] == 'return_restock']
    movement_keys = {(m['order_item_id'], m['quantity_change'], m['movement_created_at']) for m in movements}
    for ret in fetch_all(reset_engine, db.returns):
        key = (ret['order_item_id'], ret['quantity_returned'], ret['returned_at'])
        assert key in movement_keys, f'return {ret["return_id"]} has no paired return_restock movement'
    # And every restock movement positive
    for m in movements:
        assert m['quantity_change'] > 0


def test_clear_day_removes_returns_and_reverses_restock(engine, small_defaults):
    """A daily run that produces returns must be cleanly reversible by clear_day."""
    main.full_run(engine)

    target = date(2024, 6, 30)  # well past the start so candidates exist

    pre_balances = {
        (b['product_id'], b['warehouse_id']): (b['stock_on_hand'], b['available_quantity'])
        for b in fetch_all(engine, db.inventory_balances)
    }
    pre_returns = count(engine, db.returns)

    main.daily_run(engine, target, 5)
    after_returns = count(engine, db.returns)
    assert after_returns >= pre_returns

    with engine.begin() as conn:
        main.clear_day(conn, target)

    assert count(engine, db.returns) == pre_returns
    post_balances = {
        (b['product_id'], b['warehouse_id']): (b['stock_on_hand'], b['available_quantity'])
        for b in fetch_all(engine, db.inventory_balances)
    }
    assert post_balances == pre_balances
