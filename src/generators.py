from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List

from .config import COUNTRY
from .models import Customer, Product
from .reference_data import BRANDS, CATEGORIES, CITIES, FIRST_NAMES, LAST_NAMES


def make_customers(n: int, rng: random.Random) -> List[Customer]:
    rows: List[Customer] = []
    base = datetime(2023, 1, 1)
    for i in range(1, n + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        city = rng.choice(CITIES)
        created_at = base + timedelta(days=rng.randint(0, 500), minutes=rng.randint(0, 1440))
        rows.append(Customer(i, f'{first} {last}', f'{first.lower()}.{last.lower()}{i}@example.com', created_at, city, COUNTRY))
    return rows


def make_products(n: int, rng: random.Random) -> List[Product]:
    rows: List[Product] = []
    for i in range(1, n + 1):
        category = rng.choice(CATEGORIES)
        brand = rng.choice(BRANDS)
        if category == 'electronics':
            unit_price = rng.uniform(5000, 75000)
        elif category == 'fashion':
            unit_price = rng.uniform(500, 8000)
        elif category == 'home':
            unit_price = rng.uniform(300, 20000)
        elif category == 'beauty':
            unit_price = rng.uniform(150, 5000)
        elif category == 'sports':
            unit_price = rng.uniform(400, 25000)
        elif category == 'grocery':
            unit_price = rng.uniform(50, 1500)
        else:
            unit_price = rng.uniform(100, 2500)
        unit_price = round(unit_price, 2)
        unit_cost = round(unit_price * rng.uniform(0.45, 0.8), 2)
        rows.append(Product(i, f'{brand} {category.title()} {i}', category, brand, unit_price, unit_cost))
    return rows
