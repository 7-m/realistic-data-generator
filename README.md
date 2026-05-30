# Datagen

Generate realistic synthetic business data for analytics, data engineering, testing etc. 
The project currently focuses on an ecommerce-style dataset with a database-first generation flow.

## Quick start (Docker)

Build the image:

```bash
docker build -t datagen .
```

Run against a local SQLite file at `./data/datagen.db`:

```bash
docker run --rm -v "$PWD/data:/app/data" datagen --db-url sqlite:////app/data/datagen.db --reset
```

Run against an existing Postgres or MySQL instance by passing its URL:

```bash
docker run --rm datagen --db-url postgresql+psycopg://user:pw@host:5432/datagen --reset
docker run --rm datagen --db-url mysql+pymysql://user:pw@host:3306/datagen --reset
```

To reach a database running on the Docker host, use `host.docker.internal` (macOS/Windows) or `--network host` (Linux):

```bash
docker run --rm datagen --db-url postgresql+psycopg://user:pw@host.docker.internal:5432/datagen --reset
docker run --rm --network host datagen --db-url postgresql+psycopg://user:pw@localhost:5432/datagen --reset
```

Append a day or wipe a day:

```bash
docker run --rm -v "$PWD/data:/app/data" datagen --db-url sqlite:////app/data/datagen.db --date 2024-01-15 --orders 100
docker run --rm -v "$PWD/data:/app/data" datagen --db-url sqlite:////app/data/datagen.db --date 2024-01-15 --clear-day
```

## Use with Airflow (BashOperator)

The simplest integration: install datagen on the Airflow worker and call `python main.py` from a `BashOperator`. No Docker daemon, no extra Airflow providers — datagen's only runtime deps are `SQLAlchemy` plus a DB driver.

**1. Install on every Airflow worker.** Drop the repo at a known path (e.g. `/opt/datagen`), then in the Airflow Python env:

```bash
pip install -r /opt/datagen/requirements.txt
pip install "psycopg[binary]"   # or pymysql, depending on your backend
```

**2. Bootstrap once, by hand.** `--reset` drops and recreates everything, so it must not run on a schedule:

```bash
python /opt/datagen/main.py --db-url "$DATAGEN_DB_URL" --reset
```

**3. Daily DAG.** A two-task DAG that maps Airflow's logical date (`{{ ds }}`) to `--date`. The upstream `--clear-day` makes the DAG safely re-runnable for the same date (backfills, retries):

```python
# dags/datagen_daily.py
from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator

DATAGEN_DIR = "/opt/datagen"

with DAG(
    dag_id="datagen_daily",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    default_args={"retries": 1},
) as dag:
    clear = BashOperator(
        task_id="clear_day",
        bash_command=(
            f"cd {DATAGEN_DIR} && "
            'python main.py --db-url "$DATAGEN_DB_URL" '
            "--date {{ ds }} --clear-day"
        ),
        env={"DATAGEN_DB_URL": "{{ var.value.datagen_db_url }}"},
    )

    generate = BashOperator(
        task_id="generate_day",
        bash_command=(
            f"cd {DATAGEN_DIR} && "
            'python main.py --db-url "$DATAGEN_DB_URL" '
            "--date {{ ds }} --orders 100"
        ),
        env={"DATAGEN_DB_URL": "{{ var.value.datagen_db_url }}"},
    )

    clear >> generate
```

Set the `datagen_db_url` Airflow Variable (or swap `env` for an Airflow Connection) before enabling the DAG. A runnable copy of the DAG lives at `examples/airflow/datagen_daily.py`.

## Setup (local Python)

```bash
pip install -r requirements.txt
# Then install the driver for your backend (uncomment the line in requirements.txt or):
#   pip install pymysql            # for MySQL/MariaDB
#   pip install "psycopg[binary]"  # for PostgreSQL
# SQLite needs no driver — it ships with Python.
```

## Output

Nine tables (see `schema.md`):

- `customers`, `products`, `warehouses` — reference data
- `orders`, `order_items`, `payments`, `shipments` — order lifecycle
- `inventory_balances`, `inventory_movements` — stock state and history

## Usage

Full regeneration (default). Drops and recreates all tables:

```bash
python main.py --reset
```

Append data for a specific day, persisting inventory across days:

```bash
python main.py --date 2024-01-15 --orders 100
```

`--date` always appends — running it twice for the same day produces two batches of orders for that day. To wipe a day's data, use `--clear-day`:

```bash
python main.py --date 2024-01-15 --clear-day                 # wipe Jan 15
python main.py --date 2024-01-15 --orders 100                # then regenerate, if you want
```

Pick the backend with `--db-url`:

```bash
python main.py --reset --db-url "sqlite:///./datagen.db"
python main.py --reset --db-url "mysql+pymysql://user:pw@localhost/datagen"
python main.py --reset --db-url "postgresql+psycopg://user:pw@localhost/datagen"
```

Flags:

- `--db-url URL` — SQLAlchemy URL (default `sqlite:///datagen.db`)
- `--date YYYY-MM-DD` — the day to operate on (required for `--clear-day`)
- `--orders N` — number of orders to generate for `--date` (default `DEFAULT_ORDERS`)
- `--clear-day` — delete every row for `--date` from `orders`, `order_items`, `payments`, `shipments`, and `inventory_movements`, and reverse the day's effect on `inventory_balances`. Generates nothing on its own.
- `--reset` — drop all tables and regenerate from scratch

## How it works

`--reset` builds customers, products, warehouses, and initial inventory balances, then simulates `DEFAULT_ORDERS` orders over a 180-day window starting 2024-01-01. Each order produces line items (with a chosen fulfillment warehouse), payments, an optional shipment, and matching inventory reservation/release/deduction movements. Everything is inserted in a single transaction.

`--date` ensures the schema exists, loads existing reference data and inventory balances, then simulates `--orders` orders for that day. PK sequences continue from the current `MAX(...)` per table. Inventory balances are `UPDATE`d at the end so the next day starts from the new state. The whole daily run is one transaction.

## Process flow

When each record is produced.

**Reference data — once per `--reset`** (read from DB on `--date`):

| Table                | When                                                                                                  |
| -------------------- | ----------------------------------------------------------------------------------------------------- |
| `customers`          | one row per customer at startup                                                                       |
| `products`           | one row per product at startup                                                                        |
| `warehouses`         | one row per warehouse at startup                                                                      |
| `inventory_balances` | one row per `(product, warehouse)` at startup; updated at end of every run with current state        |

**Per-order flow** (`simulate_orders` for `--reset`, `simulate_orders_for_day` for `--date`):

```
for each order:
  pick a random customer + 1–5 products + a status from a weighted distribution

  for each line item (1 per chosen product):
    pick a fulfillment warehouse with enough available stock
    -> order_items row
    -> inventory_movements row  (type=sale_reservation, qty=-)
    update inventory_balances    (reserved += q, available -= q)

  -> orders row  (status will be reconciled below)

  payment attempts (1 if cancelled/created, else 1–2):
    -> payments row per attempt  (final attempt forced to 'captured' for paid/shipped/delivered)

  if any payment captured AND status in {paid, shipped, delivered}:
    roll shipment_status (pending/shipped/delivered/failed)
    reconcile order_status to match the shipment outcome
    -> shipments row              (shipped_at/delivered_at filled per status)

  finalize order_status on the orders row

  for each line item:
    if order_status in {cancelled, created}:
      -> inventory_movements row  (type=release, qty=+)
      update inventory_balances    (reserved -= q, available += q)
    elif order_status in {paid, shipped, delivered}:
      -> inventory_movements row  (type=shipment_deduction, qty=-)
      update inventory_balances    (reserved -= q, stock_on_hand -= q)
```

**Cardinality summary**:

- 1 order → 1 `orders` row, 1–5 `order_items` rows, 1–2 `payments` rows, 0–1 `shipments` rows
- 1 line item → 2 `inventory_movements` rows (one reservation, one release or deduction)
- A `pending` shipment writes a `shipments` row with `NULL` `shipped_at`/`delivered_at`; a `failed` shipment also leaves `shipped_at` `NULL`

## Configuration

Defaults in `src/config.py`: `DEFAULT_DB_URL`, `DEFAULT_CUSTOMERS`, `DEFAULT_PRODUCTS`, `DEFAULT_ORDERS`, `DEFAULT_WAREHOUSES`, `DEFAULT_INITIAL_STOCK_MIN/MAX`, `DEFAULT_REORDER_POINT`, `DEFAULT_REORDER_QUANTITY`, `SEED`.

## Layout

- `main.py` — CLI entry, full-run and daily-run orchestration
- `src/db.py` — SQLAlchemy table definitions and engine helpers
- `src/generators.py` — customer and product generation
- `src/inventory.py` — warehouses, balances, fulfillment selection, restock
- `src/simulator.py` — order, payment, shipment, and inventory-movement simulation
- `src/models.py`, `src/reference_data.py`, `src/config.py` — data classes, fixed values, defaults
