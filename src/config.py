from datetime import date

DEFAULT_DB_URL = 'sqlite:///datagen.db'
DEFAULT_CUSTOMERS = 1000
DEFAULT_PRODUCTS = 200
DEFAULT_ORDERS = 10000
DEFAULT_WAREHOUSES = 5
DEFAULT_INITIAL_STOCK_MIN = 200
DEFAULT_INITIAL_STOCK_MAX = 800
DEFAULT_REORDER_POINT = 60
DEFAULT_REORDER_QUANTITY = 250
SEED = 42
COUNTRY = 'India'

# Window covered by --reset. The full-run distributes DEFAULT_ORDERS uniformly across these days.
SIMULATION_START_DATE = date(2024, 1, 1)
SIMULATION_WINDOW_DAYS = 180

# --- Returns -------------------------------------------------------------
# Override these in this file (or monkeypatch in tests) to tune the rate at which delivered
# orders generate returns. Defaults reflect typical industry behavior.
RETURN_PROBABILITY_PER_ORDER = 0.07
RETURN_PROBABILITY_PER_ITEM = 0.5
FULL_QUANTITY_RETURN_PROBABILITY = 0.6
RETURN_LOOKBACK_DAYS = 21
RETURN_DELAY_MIN_DAYS = 1
RETURN_DELAY_MAX_DAYS = 14

# --- Soft-delete simulation ---------------------------------------------
# Per-active-entity per-day probability of being soft-deleted. Defaults are intentionally
# small so deletions accumulate gradually over a full --reset run.
CUSTOMER_DELETION_PROBABILITY = 0.0005
PRODUCT_DELETION_PROBABILITY = 0.0003
WAREHOUSE_DELETION_PROBABILITY = 0.00005
