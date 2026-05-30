from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import db  # noqa: E402
from src.config import SEED  # noqa: E402
import main  # noqa: E402


SMALL_CUSTOMERS = 50
SMALL_PRODUCTS = 30
SMALL_WAREHOUSES = 3
SMALL_ORDERS = 100


@pytest.fixture
def small_defaults(monkeypatch):
    monkeypatch.setattr(main, 'DEFAULT_CUSTOMERS', SMALL_CUSTOMERS)
    monkeypatch.setattr(main, 'DEFAULT_PRODUCTS', SMALL_PRODUCTS)
    monkeypatch.setattr(main, 'DEFAULT_WAREHOUSES', SMALL_WAREHOUSES)
    monkeypatch.setattr(main, 'DEFAULT_ORDERS', SMALL_ORDERS)


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / 'datagen.db'
    eng = db.make_engine(f'sqlite:///{db_path}')
    yield eng
    eng.dispose()


@pytest.fixture
def reset_engine(engine, small_defaults):
    main.full_run(engine)
    return engine


def count(engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def fetch_all(engine, table) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(table)).mappings().all()]


def orders_for_day(engine, day: date) -> list[dict]:
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                select(db.orders).where(
                    db.orders.c.order_created_at >= day_start,
                    db.orders.c.order_created_at < day_end,
                )
            ).mappings().all()
        ]
