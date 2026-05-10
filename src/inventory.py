from __future__ import annotations

import random
from datetime import datetime

from .config import (
    COUNTRY,
    DEFAULT_INITIAL_STOCK_MAX,
    DEFAULT_INITIAL_STOCK_MIN,
    DEFAULT_REORDER_POINT,
    DEFAULT_REORDER_QUANTITY,
    DEFAULT_WAREHOUSES,
)
from .models import InventoryBalance, InventoryMovement, Product, Warehouse


WAREHOUSE_CITIES = ['Mumbai', 'Delhi', 'Bengaluru', 'Pune', 'Hyderabad', 'Chennai', 'Kolkata']


def make_warehouses(rng: random.Random, n_warehouses: int = DEFAULT_WAREHOUSES) -> list[Warehouse]:
    warehouses: list[Warehouse] = []
    for warehouse_id in range(1, n_warehouses + 1):
        city = rng.choice(WAREHOUSE_CITIES)
        warehouses.append(Warehouse(warehouse_id, f'Warehouse {warehouse_id}', city, COUNTRY))
    return warehouses


def make_inventory_balances(
    products: list[Product],
    warehouses: list[Warehouse],
    rng: random.Random,
    updated_at: datetime,
) -> list[InventoryBalance]:
    balances: list[InventoryBalance] = []
    for product in products:
        for warehouse in warehouses:
            stock_on_hand = rng.randint(DEFAULT_INITIAL_STOCK_MIN, DEFAULT_INITIAL_STOCK_MAX)
            balances.append(
                InventoryBalance(
                    product.product_id,
                    warehouse.warehouse_id,
                    stock_on_hand,
                    0,
                    stock_on_hand,
                    DEFAULT_REORDER_POINT,
                    DEFAULT_REORDER_QUANTITY,
                    updated_at,
                )
            )
    return balances


def build_inventory_index(balances: list[InventoryBalance]) -> dict[tuple[int, int], InventoryBalance]:
    return {(b.product_id, b.warehouse_id): b for b in balances}


def choose_fulfillment_warehouse(
    balances: dict[tuple[int, int], InventoryBalance],
    product_id: int,
    rng: random.Random,
    quantity: int,
) -> InventoryBalance:
    candidates = [balance for balance in balances.values() if balance.product_id == product_id and balance.available_quantity >= quantity]
    if candidates:
        return max(candidates, key=lambda b: (b.available_quantity, -b.warehouse_id))
    return max((balance for balance in balances.values() if balance.product_id == product_id), key=lambda b: b.available_quantity)


def reserve_stock(balance: InventoryBalance, quantity: int) -> None:
    balance.reserved_quantity += quantity
    balance.available_quantity -= quantity
    balance.updated_at = datetime.utcnow()


def deduct_stock(balance: InventoryBalance, quantity: int) -> None:
    balance.stock_on_hand -= quantity
    balance.updated_at = datetime.utcnow()


def release_stock(balance: InventoryBalance, quantity: int) -> None:
    balance.reserved_quantity -= quantity
    balance.available_quantity += quantity
    balance.updated_at = datetime.utcnow()


def maybe_restock(balance: InventoryBalance, movement_id: int, product_id: int, warehouse_id: int, when: datetime) -> InventoryMovement | None:
    if balance.available_quantity >= balance.reorder_point:
        return None
    balance.stock_on_hand += balance.reorder_quantity
    balance.available_quantity += balance.reorder_quantity
    balance.updated_at = when
    return InventoryMovement(
        movement_id,
        product_id,
        warehouse_id,
        None,
        None,
        'restock',
        balance.reorder_quantity,
        when,
        'auto restock triggered by reorder point',
    )