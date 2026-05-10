from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import List, Tuple

from .inventory import choose_fulfillment_warehouse
from .models import Customer, InventoryBalance, InventoryMovement, Order, OrderItem, Payment, Product, Shipment
from .reference_data import CHANNELS, CARRIERS, PAYMENT_METHODS


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


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f'Unsupported datetime value: {value!r}')


def simulate_orders(
    n_orders: int,
    customers: List[Customer],
    products: List[Product],
    rng: random.Random,
) -> Tuple[List[Order], List[OrderItem], List[Payment], List[Shipment]]:
    orders: List[Order] = []
    order_items: List[OrderItem] = []
    payments: List[Payment] = []
    shipments: List[Shipment] = []

    payment_id = 1
    shipment_id = 1
    order_item_id = 1
    start = datetime(2024, 1, 1)

    for order_id in range(1, n_orders + 1):
        customer = rng.choice(customers)
        order_created_at = max(customer.created_at + timedelta(days=1), start + timedelta(minutes=rng.randint(0, 60 * 24 * 180)))
        order_created_at += timedelta(minutes=rng.randint(0, 24 * 60))
        order_status = choose_order_status(rng)
        channel = rng.choice(CHANNELS)

        line_count = rng.randint(1, 5)
        chosen_products = rng.sample(products, k=min(line_count, len(products)))
        total = 0.0
        for product in chosen_products:
            quantity = rng.randint(1, 3)
            line_total = round(quantity * product.unit_price, 2)
            total += line_total
            order_items.append(OrderItem(order_item_id, order_id, product.product_id, 1, quantity, product.unit_price, line_total))
            order_item_id += 1

        total = round(total, 2)
        orders.append(Order(order_id, customer.customer_id, order_created_at, order_status, channel, total))

        attempts = 1 if order_status in {'cancelled', 'created'} else rng.randint(1, 2)
        captured = False
        last_payment_time = order_created_at
        for attempt in range(attempts):
            payment_created_at = last_payment_time + timedelta(minutes=rng.randint(1, 30))
            if attempt == attempts - 1 and order_status in {'paid', 'shipped', 'delivered'}:
                payment_status = 'captured'
                captured = True
            else:
                payment_status = rng.choices(['failed', 'pending', 'captured'], weights=[0.7, 0.2, 0.1])[0]
                captured = captured or payment_status == 'captured'
            amount = total if payment_status == 'captured' else round(total * rng.uniform(0.5, 1.0), 2)
            payments.append(Payment(payment_id, order_id, payment_created_at, rng.choice(PAYMENT_METHODS), payment_status, amount))
            payment_id += 1
            last_payment_time = payment_created_at

        if captured and order_status in {'paid', 'shipped', 'delivered'}:
            shipment_status = rng.choices(['pending', 'shipped', 'delivered', 'failed'], weights=[0.1, 0.35, 0.5, 0.05])[0]
            shipped_at = order_created_at + timedelta(hours=rng.randint(4, 72))
            delivered_at = None
            if shipment_status == 'delivered':
                delivered_at = shipped_at + timedelta(days=rng.randint(1, 7))
                order_status = 'delivered'
            elif shipment_status == 'shipped':
                order_status = 'shipped'
            elif shipment_status == 'failed':
                order_status = 'paid'
            else:
                order_status = 'paid'
            shipments.append(Shipment(shipment_id, order_id, shipment_status, shipped_at if shipment_status in {'shipped', 'delivered', 'failed'} else None, delivered_at, rng.choice(CARRIERS)))
            shipment_id += 1

    return orders, order_items, payments, shipments


def simulate_orders_for_day(
    day: date,
    n_orders: int,
    customers: List[Customer],
    products: List[Product],
    rng: random.Random,
    order_id_start: int,
    order_item_id_start: int,
    payment_id_start: int,
    shipment_id_start: int,
    inventory_balances: dict[tuple[int, int], InventoryBalance],
) -> Tuple[List[Order], List[OrderItem], List[Payment], List[Shipment], List[InventoryMovement]]:
    orders: List[Order] = []
    order_items: List[OrderItem] = []
    payments: List[Payment] = []
    shipments: List[Shipment] = []
    movements: List[InventoryMovement] = []

    order_item_id = order_item_id_start
    payment_id = payment_id_start
    shipment_id = shipment_id_start
    movement_id = 1
    day_start = datetime.combine(day, datetime.min.time())

    for order_id in range(order_id_start, order_id_start + n_orders):
        customer = rng.choice(customers)
        order_created_at = day_start + timedelta(minutes=rng.randint(0, 24 * 60 - 1))
        customer_created_at = _parse_datetime(customer.created_at)
        order_created_at = max(order_created_at, customer_created_at + timedelta(days=1))
        order_status = choose_order_status(rng)
        channel = rng.choice(CHANNELS)

        line_count = rng.randint(1, 5)
        chosen_products = rng.sample(products, k=min(line_count, len(products)))
        total = 0.0
        chosen_line_items = []
        for product in chosen_products:
            quantity = rng.randint(1, 3)
            balance = choose_fulfillment_warehouse(inventory_balances, product.product_id, rng, quantity)
            line_total = round(quantity * product.unit_price, 2)
            total += line_total
            order_items.append(OrderItem(order_item_id, order_id, product.product_id, balance.warehouse_id, quantity, product.unit_price, line_total))
            chosen_line_items.append((product.product_id, balance.warehouse_id, quantity, order_item_id))
            balance.reserved_quantity += quantity
            balance.available_quantity -= quantity
            movements.append(InventoryMovement(movement_id, product.product_id, balance.warehouse_id, order_id, order_item_id, 'sale_reservation', -quantity, order_created_at, 'reserved for order'))
            movement_id += 1
            order_item_id += 1

        total = round(total, 2)
        orders.append(Order(order_id, customer.customer_id, order_created_at, order_status, channel, total))

        attempts = 1 if order_status in {'cancelled', 'created'} else rng.randint(1, 2)
        captured = False
        last_payment_time = order_created_at
        for attempt in range(attempts):
            payment_created_at = last_payment_time + timedelta(minutes=rng.randint(1, 30))
            if attempt == attempts - 1 and order_status in {'paid', 'shipped', 'delivered'}:
                payment_status = 'captured'
                captured = True
            else:
                payment_status = rng.choices(['failed', 'pending', 'captured'], weights=[0.7, 0.2, 0.1])[0]
                captured = captured or payment_status == 'captured'
            amount = total if payment_status == 'captured' else round(total * rng.uniform(0.5, 1.0), 2)
            payments.append(Payment(payment_id, order_id, payment_created_at, rng.choice(PAYMENT_METHODS), payment_status, amount))
            payment_id += 1
            last_payment_time = payment_created_at

        if captured and order_status in {'paid', 'shipped', 'delivered'}:
            shipment_status = rng.choices(['pending', 'shipped', 'delivered', 'failed'], weights=[0.1, 0.35, 0.5, 0.05])[0]
            shipped_at = order_created_at + timedelta(hours=rng.randint(4, 72))
            delivered_at = None
            if shipment_status == 'delivered':
                delivered_at = shipped_at + timedelta(days=rng.randint(1, 7))
                order_status = 'delivered'
            elif shipment_status == 'shipped':
                order_status = 'shipped'
            elif shipment_status == 'failed':
                order_status = 'paid'
            else:
                order_status = 'paid'
            shipments.append(Shipment(shipment_id, order_id, shipment_status, shipped_at if shipment_status in {'shipped', 'delivered', 'failed'} else None, delivered_at, rng.choice(CARRIERS)))
            shipment_id += 1

        for product_id, warehouse_id, quantity, item_id in chosen_line_items:
            balance = inventory_balances[(product_id, warehouse_id)]
            if order_status in {'cancelled', 'created'}:
                balance.available_quantity += quantity
                balance.reserved_quantity -= quantity
                movements.append(InventoryMovement(movement_id, product_id, warehouse_id, order_id, item_id, 'release', quantity, order_created_at, 'order not fulfilled'))
            elif order_status in {'paid', 'shipped', 'delivered'}:
                balance.reserved_quantity -= quantity
                balance.stock_on_hand -= quantity
                movements.append(InventoryMovement(movement_id, product_id, warehouse_id, order_id, item_id, 'shipment_deduction', -quantity, order_created_at, 'fulfilled order'))
            movement_id += 1

    return orders, order_items, payments, shipments, movements
