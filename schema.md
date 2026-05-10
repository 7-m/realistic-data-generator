# Ecommerce Order Lifecycle Source Schema

## Scope
Order lifecycle without returns.

## Tables
1. customers
2. products
3. warehouses
4. orders
5. order_items
6. payments
7. shipments
8. inventory_balances
9. inventory_movements

## Relationships
- customers 1 -> many orders
- warehouses 1 -> many order_items
- orders 1 -> many order_items
- products 1 -> many order_items
- orders 1 -> many payments
- orders 1 -> zero/many shipments
- products 1 -> many inventory_balances
- warehouses 1 -> many inventory_balances
- products 1 -> many inventory_movements
- warehouses 1 -> many inventory_movements

## Lifecycle
order_created_at -> payment_created_at -> shipped_at -> delivered_at

## Notes

- `order_items.warehouse_id` identifies the warehouse that fulfilled the item.
- `inventory_balances` stores the current stock state per product and warehouse.
- `inventory_movements` records reservation, release, shipment deduction, and restock activity.
- Shipment timestamps may be empty when an order has not progressed to that stage.

## Tables and Columns

### customers
- customer_id (PK)
- customer_name
- email
- created_at
- city
- country

### products
- product_id (PK)
- product_name
- category
- brand
- unit_price
- unit_cost

### warehouses
- warehouse_id (PK)
- warehouse_name
- city
- country

### orders
- order_id (PK)
- customer_id (FK)
- order_created_at
- order_status
- channel
- order_total

### order_items
- order_item_id (PK)
- order_id (FK)
- product_id (FK)
- warehouse_id (FK)
- quantity
- unit_price
- line_total

### payments
- payment_id (PK)
- order_id (FK)
- payment_created_at
- payment_method
- payment_status
- amount

### shipments
- shipment_id (PK)
- order_id (FK)
- shipment_status
- shipped_at
- delivered_at
- carrier

### inventory_balances
- product_id (FK)
- warehouse_id (FK)
- stock_on_hand
- reserved_quantity
- available_quantity
- reorder_point
- reorder_quantity
- updated_at

### inventory_movements
- movement_id (PK)
- product_id (FK)
- warehouse_id (FK)
- order_id (FK, nullable)
- order_item_id (FK, nullable)
- movement_type
- quantity_change
- movement_created_at
- reason
