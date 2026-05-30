from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .models import (
    Customer,
    InventoryBalance,
    InventoryMovement,
    Order,
    OrderItem,
    Payment,
    Product,
    Return,
    Shipment,
    Warehouse,
)
from .reference_data import CARRIERS, CHANNELS, PAYMENT_METHODS, RETURN_REASONS


# ---------------------------------------------------------------------------
# Public state types
# ---------------------------------------------------------------------------


@dataclass
class World:
    """Reference data + mutable inventory state shared across daily simulations."""
    customers: list[Customer]
    products: list[Product]
    warehouses: list[Warehouse]
    balances: dict[tuple[int, int], InventoryBalance]


@dataclass
class IdCounters:
    order_id: int = 1
    order_item_id: int = 1
    payment_id: int = 1
    shipment_id: int = 1
    movement_id: int = 1
    return_id: int = 1


@dataclass
class DayResult:
    orders: list[Order] = field(default_factory=list)
    order_items: list[OrderItem] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    shipments: list[Shipment] = field(default_factory=list)
    movements: list[InventoryMovement] = field(default_factory=list)
    returns: list[Return] = field(default_factory=list)
    deletions: list['DeletionEvent'] = field(default_factory=list)


@dataclass
class ReturnCandidate:
    """One delivered line item eligible to be returned on a future day."""
    order_id: int
    order_item_id: int
    product_id: int
    warehouse_id: int
    quantity: int
    unit_price: float
    delivered_at: datetime


@dataclass
class DeletionEvent:
    """A soft-delete that occurred on a given day. Used by main.py to UPDATE the row."""
    entity: str          # 'customer' | 'product' | 'warehouse'
    entity_id: int
    deleted_at: datetime


# ---------------------------------------------------------------------------
# Per-order working state
# ---------------------------------------------------------------------------


@dataclass
class OrderContext:
    order_id: int
    customer: Customer
    order_created_at: datetime
    order_status: str
    channel: str
    total: float = 0.0
    line_items: list[tuple[int, int, int, int]] = field(default_factory=list)  # (product_id, warehouse_id, qty, item_id)
    captured: bool = False


# ---------------------------------------------------------------------------
# Pure pickers (no side effects beyond the rng)
# ---------------------------------------------------------------------------


def choose_order_status(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.05:
        return 'cancelled'
    if roll < 0.13:
        return 'created'
    if roll < 0.25:
        return 'paid'
    if roll < 0.40:
        return 'shipped'
    return 'delivered'


def choose_fulfillment_warehouse(
    balances: dict[tuple[int, int], InventoryBalance],
    product_id: int,
    quantity: int,
    active_warehouse_ids: set[int] | None = None,
) -> InventoryBalance:
    def _eligible(b: InventoryBalance) -> bool:
        return b.product_id == product_id and (active_warehouse_ids is None or b.warehouse_id in active_warehouse_ids)
    candidates = [b for b in balances.values() if _eligible(b) and b.available_quantity >= quantity]
    if candidates:
        return max(candidates, key=lambda b: (b.available_quantity, -b.warehouse_id))
    return max((b for b in balances.values() if _eligible(b)), key=lambda b: b.available_quantity)


# ---------------------------------------------------------------------------
# Movement helper
# ---------------------------------------------------------------------------


def _record_movement(result: DayResult, ids: IdCounters, **fields) -> None:
    result.movements.append(InventoryMovement(ids.movement_id, **fields))
    ids.movement_id += 1


# ---------------------------------------------------------------------------
# Per-order steps
# ---------------------------------------------------------------------------


def _start_order(day_start: datetime, world: World, ids: IdCounters, rng: random.Random) -> OrderContext:
    order_id = ids.order_id
    ids.order_id += 1
    active_customers = [c for c in world.customers if c.deleted_at is None]
    customer = rng.choice(active_customers)
    order_created_at = max(
        day_start + timedelta(minutes=rng.randint(0, 24 * 60 - 1)),
        customer.created_at + timedelta(days=1),
    )
    order_status = choose_order_status(rng)
    channel = rng.choice(CHANNELS)
    return OrderContext(
        order_id=order_id,
        customer=customer,
        order_created_at=order_created_at,
        order_status=order_status,
        channel=channel,
    )


def _add_line_items(ctx: OrderContext, world: World, ids: IdCounters, rng: random.Random, result: DayResult) -> None:
    active_products = [p for p in world.products if p.deleted_at is None]
    active_warehouse_ids = {w.warehouse_id for w in world.warehouses if w.deleted_at is None}
    line_count = rng.randint(1, 5)
    chosen_products = rng.sample(active_products, k=min(line_count, len(active_products)))
    for product in chosen_products:
        qty = rng.randint(1, 3)
        balance = choose_fulfillment_warehouse(world.balances, product.product_id, qty, active_warehouse_ids)
        line_total = round(qty * product.unit_price, 2)
        ctx.total += line_total

        item_id = ids.order_item_id
        ids.order_item_id += 1
        result.order_items.append(OrderItem(item_id, ctx.order_id, product.product_id, balance.warehouse_id, qty, product.unit_price, line_total))
        ctx.line_items.append((product.product_id, balance.warehouse_id, qty, item_id))

        balance.reserved_quantity += qty
        balance.available_quantity -= qty
        _record_movement(
            result, ids,
            product_id=product.product_id,
            warehouse_id=balance.warehouse_id,
            order_id=ctx.order_id,
            order_item_id=item_id,
            movement_type='sale_reservation',
            quantity_change=-qty,
            movement_created_at=ctx.order_created_at,
            reason='reserved for order',
        )
    ctx.total = round(ctx.total, 2)


def _process_payments(ctx: OrderContext, ids: IdCounters, rng: random.Random, result: DayResult) -> None:
    attempts = 1 if ctx.order_status in {'cancelled', 'created'} else rng.randint(1, 2)
    last_payment_time = ctx.order_created_at
    for attempt in range(attempts):
        payment_created_at = last_payment_time + timedelta(minutes=rng.randint(1, 30))
        if attempt == attempts - 1 and ctx.order_status in {'paid', 'shipped', 'delivered'}:
            payment_status = 'captured'
            ctx.captured = True
        else:
            payment_status = rng.choices(['failed', 'pending', 'captured'], weights=[0.7, 0.2, 0.1])[0]
            ctx.captured = ctx.captured or payment_status == 'captured'
        amount = ctx.total if payment_status == 'captured' else round(ctx.total * rng.uniform(0.5, 1.0), 2)
        result.payments.append(Payment(ids.payment_id, ctx.order_id, payment_created_at, rng.choice(PAYMENT_METHODS), payment_status, amount))
        ids.payment_id += 1
        last_payment_time = payment_created_at


def _process_shipment(ctx: OrderContext, ids: IdCounters, rng: random.Random, result: DayResult) -> None:
    if not (ctx.captured and ctx.order_status in {'paid', 'shipped', 'delivered'}):
        return
    shipment_status = rng.choices(['pending', 'shipped', 'delivered', 'failed'], weights=[0.1, 0.35, 0.5, 0.05])[0]
    shipped_at = ctx.order_created_at + timedelta(hours=rng.randint(4, 72))
    delivered_at = None
    if shipment_status == 'delivered':
        delivered_at = shipped_at + timedelta(days=rng.randint(1, 7))
        ctx.order_status = 'delivered'
    elif shipment_status == 'shipped':
        ctx.order_status = 'shipped'
    else:
        ctx.order_status = 'paid'
    result.shipments.append(Shipment(
        ids.shipment_id,
        ctx.order_id,
        shipment_status,
        shipped_at if shipment_status in {'shipped', 'delivered'} else None,
        delivered_at,
        rng.choice(CARRIERS),
    ))
    ids.shipment_id += 1


def _finalize_order(ctx: OrderContext) -> Order:
    return Order(ctx.order_id, ctx.customer.customer_id, ctx.order_created_at, ctx.order_status, ctx.channel, ctx.total)


def _simulate_returns(
    candidates: list[ReturnCandidate],
    world: World,
    ids: IdCounters,
    rng: random.Random,
    result: DayResult,
) -> None:
    """For each delivered order in `candidates`, probabilistically generate item-level returns."""
    from .config import (
        FULL_QUANTITY_RETURN_PROBABILITY,
        RETURN_DELAY_MAX_DAYS,
        RETURN_DELAY_MIN_DAYS,
        RETURN_PROBABILITY_PER_ITEM,
        RETURN_PROBABILITY_PER_ORDER,
    )

    by_order: dict[int, list[ReturnCandidate]] = {}
    for c in candidates:
        by_order.setdefault(c.order_id, []).append(c)

    for items in by_order.values():
        if rng.random() >= RETURN_PROBABILITY_PER_ORDER:
            continue
        for item in items:
            if rng.random() >= RETURN_PROBABILITY_PER_ITEM:
                continue
            qty = item.quantity if item.quantity == 1 or rng.random() < FULL_QUANTITY_RETURN_PROBABILITY else rng.randint(1, item.quantity - 1)
            returned_at = item.delivered_at + timedelta(days=rng.randint(RETURN_DELAY_MIN_DAYS, RETURN_DELAY_MAX_DAYS))
            refund = round(qty * item.unit_price, 2)
            result.returns.append(Return(ids.return_id, item.order_item_id, qty, returned_at, rng.choice(RETURN_REASONS), refund))
            ids.return_id += 1

            balance = world.balances[(item.product_id, item.warehouse_id)]
            balance.stock_on_hand += qty
            balance.available_quantity += qty
            _record_movement(
                result, ids,
                product_id=item.product_id,
                warehouse_id=item.warehouse_id,
                order_id=item.order_id,
                order_item_id=item.order_item_id,
                movement_type='return_restock',
                quantity_change=qty,
                movement_created_at=returned_at,
                reason='customer return',
            )


def _maybe_delete(entities, get_id, kind: str, probability: float, when: datetime, rng: random.Random, result: DayResult) -> None:
    active = [e for e in entities if e.deleted_at is None]
    if len(active) <= 1:
        return  # never delete the last active entity (would brick simulation)
    for entity in active:
        if rng.random() < probability:
            entity.deleted_at = when
            result.deletions.append(DeletionEvent(kind, get_id(entity), when))


def _simulate_deletions(day_start: datetime, world: World, rng: random.Random, result: DayResult) -> None:
    """Probabilistically soft-delete some customers/products/warehouses."""
    from .config import (
        CUSTOMER_DELETION_PROBABILITY,
        PRODUCT_DELETION_PROBABILITY,
        WAREHOUSE_DELETION_PROBABILITY,
    )
    when = day_start + timedelta(seconds=rng.randint(0, 86399))
    _maybe_delete(world.customers,  lambda c: c.customer_id,  'customer',  CUSTOMER_DELETION_PROBABILITY,  when, rng, result)
    _maybe_delete(world.products,   lambda p: p.product_id,   'product',   PRODUCT_DELETION_PROBABILITY,   when, rng, result)
    _maybe_delete(world.warehouses, lambda w: w.warehouse_id, 'warehouse', WAREHOUSE_DELETION_PROBABILITY, when, rng, result)


def _resolve_reservations(ctx: OrderContext, world: World, ids: IdCounters, result: DayResult) -> None:
    for product_id, warehouse_id, qty, item_id in ctx.line_items:
        balance = world.balances[(product_id, warehouse_id)]
        if ctx.order_status in {'cancelled', 'created'}:
            balance.available_quantity += qty
            balance.reserved_quantity -= qty
            _record_movement(
                result, ids,
                product_id=product_id, warehouse_id=warehouse_id,
                order_id=ctx.order_id, order_item_id=item_id,
                movement_type='release', quantity_change=qty,
                movement_created_at=ctx.order_created_at, reason='order not fulfilled',
            )
        else:
            balance.reserved_quantity -= qty
            balance.stock_on_hand -= qty
            _record_movement(
                result, ids,
                product_id=product_id, warehouse_id=warehouse_id,
                order_id=ctx.order_id, order_item_id=item_id,
                movement_type='shipment_deduction', quantity_change=-qty,
                movement_created_at=ctx.order_created_at, reason='fulfilled order',
            )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def simulate_day(
    day: date,
    n_orders: int,
    world: World,
    ids: IdCounters,
    rng: random.Random,
    return_candidates: list[ReturnCandidate] | None = None,
) -> DayResult:
    """Simulate `n_orders` orders for `day`, mutating `world.balances` and `ids` in place.

    `return_candidates` is a list of delivered line items (from earlier days) that may be
    returned today. Defaults to no candidates when omitted.
    """
    result = DayResult()
    day_start = datetime.combine(day, datetime.min.time())
    for _ in range(n_orders):
        ctx = _start_order(day_start, world, ids, rng)
        _add_line_items(ctx, world, ids, rng, result)
        _process_payments(ctx, ids, rng, result)
        _process_shipment(ctx, ids, rng, result)
        result.orders.append(_finalize_order(ctx))
        _resolve_reservations(ctx, world, ids, result)
    _simulate_returns(return_candidates or [], world, ids, rng, result)
    _simulate_deletions(day_start, world, rng, result)
    return result
