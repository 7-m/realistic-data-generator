from __future__ import annotations

import random
from datetime import datetime, timedelta

from .config import (
    COUNTRY,
    DEFAULT_INITIAL_STOCK_MAX,
    DEFAULT_INITIAL_STOCK_MIN,
    DEFAULT_REORDER_POINT,
    DEFAULT_REORDER_QUANTITY,
)
from .models import Customer, InventoryBalance, Product, Warehouse
from .reference_data import BRANDS, CATEGORIES, CITIES, FIRST_NAMES, LAST_NAMES


WAREHOUSE_CITIES = ['Mumbai', 'Delhi', 'Bengaluru', 'Pune', 'Hyderabad', 'Chennai', 'Kolkata']


def make_customers(n: int, rng: random.Random) -> list[Customer]:
    base = datetime(2023, 1, 1)
    rows: list[Customer] = []
    for i in range(1, n + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        created_at = base + timedelta(days=rng.randint(0, 500), minutes=rng.randint(0, 1440))
        rows.append(Customer(i, f'{first} {last}', f'{first.lower()}.{last.lower()}{i}@example.com', created_at, rng.choice(CITIES), COUNTRY))
    return rows


_PRICE_RANGES = {
    'electronics': (5000, 75000),
    'fashion': (500, 8000),
    'home': (300, 20000),
    'beauty': (150, 5000),
    'sports': (400, 25000),
    'grocery': (50, 1500),
}


def make_products(n: int, rng: random.Random) -> list[Product]:
    rows: list[Product] = []
    for i in range(1, n + 1):
        category = rng.choice(CATEGORIES)
        brand = rng.choice(BRANDS)
        lo, hi = _PRICE_RANGES.get(category, (100, 2500))
        unit_price = round(rng.uniform(lo, hi), 2)
        unit_cost = round(unit_price * rng.uniform(0.45, 0.8), 2)
        rows.append(Product(i, f'{brand} {category.title()} {i}', category, brand, unit_price, unit_cost))
    return rows


def make_warehouses(n: int, rng: random.Random) -> list[Warehouse]:
    return [
        Warehouse(i, f'Warehouse {i}', rng.choice(WAREHOUSE_CITIES), COUNTRY)
        for i in range(1, n + 1)
    ]


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
            balances.append(InventoryBalance(
                product.product_id,
                warehouse.warehouse_id,
                stock_on_hand,
                0,
                stock_on_hand,
                DEFAULT_REORDER_POINT,
                DEFAULT_REORDER_QUANTITY,
                updated_at,
            ))
    return balances
