# realistic-data-generator

Generate realistic synthetic business data for analytics, data engineering, testing, and learning. The project currently focuses on an ecommerce-style dataset with a database-first generation flow.

## What it generates

The generator produces a linked business dataset covering:

- customers
- products
- warehouses
- orders
- order items
- payments
- shipments
- inventory balances
- inventory movements

All output is written to a database. The bundled backend uses SQLite, but the generation flow is designed so other database backends can be added by implementing the same backend contract.

## Database-first architecture

The codebase no longer supports CSV output. Runtime generation always persists data through a database backend.

Current backend responsibilities include:

- creating and resetting tables
- inserting generated rows
- loading existing reference and inventory data
- generating next IDs from database state
- checking whether a date already has orders
- running safe delete simulations for unused reference data

### Plugging in another database

`main.py` depends on the backend interface rather than on SQLite-specific logic. To add another database, create a backend class that exposes the same methods as `SQLiteBackend` in `src/database.py`, then wire it into the backend factory in `main.py`.

This keeps the generator database-independent while still shipping with a working default implementation.

## How to run

### Full regeneration

```bash
python3 main.py --reset
```

If no arguments are provided, the default behavior is also a full regeneration.

### Daily incremental generation

```bash
python3 main.py --date 2024-01-15 --orders 100
```

Useful flags:

- `--date YYYY-MM-DD` — generate a specific day
- `--orders N` — number of orders to create for that day
- `--force` — append even if rows for that date already exist
- `--reset` — regenerate everything from scratch
- `--db-path PATH` — SQLite database file path
- `--customer-delete-probability` — chance of deleting eligible customers during a daily DB run
- `--product-delete-probability` — chance of deleting eligible products during a daily DB run
- `--warehouse-delete-probability` — chance of deleting eligible warehouses during a daily DB run

## Default database

The bundled backend stores data in SQLite at `output/datagen.sqlite` by default.

## Project structure

- `main.py` — command-line entry point and run orchestration
- `src/config.py` — default sizes, paths, and constants
- `src/generators.py` — customer and product generation
- `src/inventory.py` — warehouse setup and stock reservation/restock helpers
- `src/database.py` — database backend and operations
- `src/models.py` — dataclass definitions for generated records
- `src/reference_data.py` — fixed categorical values used by the generator
- `src/simulator.py` — order, payment, shipment, and inventory movement simulation
- `schema.md` — documented schema and table relationships

## Generation flow

1. Reference data such as customers, products, and warehouses is created or loaded from the database.
2. Full runs generate orders, order items, payments, and shipments.
3. Daily runs reuse existing data when available, generate inventory balances if needed, and simulate stock reservation, release, shipment deduction, and restock movements.
4. The backend persists rows and can optionally perform safe delete simulations for unused records.

## Schema reference

See `schema.md` for the table list, relationships, and column definitions.