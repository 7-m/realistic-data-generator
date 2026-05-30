"""Daily Airflow DAG that appends one day of synthetic data to your database.

Prerequisites on every Airflow worker:
  - This repo cloned to DATAGEN_DIR (default /opt/datagen)
  - `pip install -r $DATAGEN_DIR/requirements.txt` plus the DB driver
    (`psycopg[binary]` for Postgres, `pymysql` for MySQL)
  - Airflow Variable `datagen_db_url` set to the SQLAlchemy URL, OR swap the
    `env` dicts below for an Airflow Connection lookup.

Bootstrap once by hand before enabling this DAG:
    python /opt/datagen/main.py --db-url "$DATAGEN_DB_URL" --reset

`clear_day` runs first so reruns and backfills are idempotent: re-running the
same logical date wipes the previous attempt and regenerates cleanly.
"""

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

DATAGEN_DIR = "/opt/datagen"
ORDERS_PER_DAY = 100

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
            f"--date {{{{ ds }}}} --orders {ORDERS_PER_DAY}"
        ),
        env={"DATAGEN_DB_URL": "{{ var.value.datagen_db_url }}"},
    )

    clear >> generate
