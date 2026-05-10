# Datagen

Datagen is a Python project that generates ecommerce source data as CSV files. It can create a complete dataset from scratch or append data for a specific day while maintaining related inventory state.

## What it generates

The generator writes CSV files into `output/`:

- `customers.csv`
- `products.csv`
- `warehouses.csv`
- `orders.csv`
- `order_items.csv`
- `payments.csv`
- `shipments.csv`
- `inventory_balances.csv`
- `inventory_movements.csv`

## Project structure

- `main.py` — command-line entry point and run orchestration
- `src/config.py` — default sizes, paths, and constants
- `src/generators.py` — customer and product generation
- `src/inventory.py` — warehouse setup and stock reservation/restock helpers
- `src/models.py` — dataclass definitions for generated records
- `src/reference_data.py` — fixed categorical values used by the generator
- `src/simulator.py` — order, payment, shipment, and inventory movement simulation
- `src/writers.py` — CSV reading/writing and dataclass loading helpers
- `schema.md` — documented schema and table relationships

## How to run

### Full regeneration

Generate all datasets from scratch:

```bash
python main.py --reset
```

If no arguments are provided, the default behavior is also a full regeneration.

### Daily incremental generation

Generate data for a specific date and append it to the existing dataset:

```bash
python main.py --date 2024-01-15 --orders 100
```

Useful flags:

- `--date YYYY-MM-DD` — generate a specific day
- `--orders N` — number of orders to create for that day
- `--force` — append even if rows for that date already exist
- `--reset` — regenerate everything from scratch

## Generation flow

1. Customers, products, and warehouses are created as reference data.
2. Orders are generated with linked order items.
3. Payments and shipments are simulated based on order status.
4. For daily runs, inventory balances are loaded or created, stock is reserved/deducted, and inventory movements are written.

## Configuration

Defaults live in `src/config.py`:

- `DEFAULT_CUSTOMERS`
- `DEFAULT_PRODUCTS`
- `DEFAULT_ORDERS`
- `DEFAULT_WAREHOUSES`
- `DEFAULT_INITIAL_STOCK_MIN`
- `DEFAULT_INITIAL_STOCK_MAX`
- `DEFAULT_REORDER_POINT`
- `DEFAULT_REORDER_QUANTITY`
- `SEED`
- `OUTPUT_DIR`

## Schema reference

See `schema.md` for the table list, relationships, and column definitions.
