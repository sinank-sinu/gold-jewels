# E-commerce API Reference Table

**Base URL:** `/api/ecommerce`

## API Endpoints Overview

| Endpoint | Method | Description | Authentication | Required Parameters |
|----------|--------|-------------|----------------|---------------------|
| `/register` | POST | Register new customer and receive auth_token | public | `first_name`, `last_name`, `phone`, `city`, `email`, `password`, `confirm_password` |
| `/login` | POST | Authenticate customer (token only at registration) | public | `email`, `password` |
| `/branch_products` | POST | Get products for a branch with location-wise stock | public | `branch_name` OR `branch_id`, optional: `location_name` |
| `/cart/add` | POST | Add product to customer's cart | public | `customer_id`, `product_id`, optional: `quantity` |
| `/cart/view` | POST | View customer's shopping cart | public | `customer_id` |
| `/cart/update` | POST | Update quantity of an item in cart | public | `customer_id`, `cart_line_id`, `quantity` |
| `/cart/remove` | POST | Remove an item from cart | public | `customer_id`, `cart_line_id` |
| `/cart/clear` | POST | Clear all items from cart | public | `customer_id` |
| `/wishlist/add` | POST | Add product to wishlist | public | `customer_id`, `product_id` |
| `/wishlist/view` | POST | View customer's wishlist | public | `customer_id` |
| `/wishlist/remove` | POST | Remove product from wishlist | public | `customer_id`, `product_id` |
| `/checkout` | POST | Convert cart to order | public | `customer_id`, `payment_method`, optional: `shipping_address`, `shipping_city`, `shipping_phone`, `notes` |
| `/checkout` | GET | Convert cart to order with token auth | Token (Authorization header) | `payment_method`, optional: `shipping_address`, `shipping_city`, `shipping_phone`, `notes` (in request body) |
| `/orders` | POST | View customer's order history | public | `customer_id` |
| `/orders` | GET | View order history with token auth | Token (Authorization header) | None (token in header) |
| `/order/{order_id}` | POST | View specific order details | public | `customer_id`, `order_id` (in URL) |
| `/order/{order_id}` | GET | View order details with token auth | Token (Authorization header) | `order_id` (in URL) |

---

## Detailed Response Fields

### Register Response
```json
{
  "status": "success",
  "message": "Registration successful",
  "data": {
    "customer_id": 1,
    "name": "John Doe",
    "email": "customer@example.com",
    "phone": "1234567890",
    "city": "Calicut",
    "auth_token": "abc123xyz456...",
    "token_expiry": "2024-02-14"
  }
}
```

### Login Response
```json
{
  "status": "success",
  "message": "Login successful",
  "data": {
    "customer_id": 1,
    "name": "John Doe",
    "email": "customer@example.com",
    "phone": "1234567890",
    "city": "Calicut"
  }
}
```

### Branch Products Response
```json
{
  "status": "success",
  "branch": "Calicut",
  "count": 10,
  "data": [
    {
      "id": 123,
      "name": "Gold Ring",
      "price": 15000.0,
      "description": "22K Gold Ring with diamonds",
      "image_url": "/web/image/product.template/123/image_1920",
      "branch_id": 1,
      "branch_name": "Calicut",
      "total_stock": 15,
      "available_locations": ["wh/stock", "Rifan/stock"],
      "purity": "22K",
      "purity_percentage": 91.67,
      "location_stocks": [
        {
          "location_id": 5,
          "location_name": "wh/stock",
          "location_complete_name": "Calicut/wh/stock",
          "product_name": "Gold Ring",
          "price": 15000.0,
          "description": "22K Gold Ring with diamonds",
          "image_url": "/web/image/product.template/123/image_1920",
          "quantity": 10,
          "purity": "22K",
          "purity_percentage": 91.67,
          "labels": [
            {
              "label_number": "LBL001",
              "label_name": "Gold Ring Label 1",
              "tag_weight": 5.5,
              "grams": 5.2,
              "purity": "22K",
              "purity_percentage": 91.67
            }
          ]
        }
      ]
    }
  ]
}
```

### Cart Add/View/Update/Remove Response
```json
{
  "status": "success",
  "message": "Item added to cart",
  "cart": {
    "cart_id": 1,
    "customer_id": 1,
    "total_amount": 30000.0,
    "items": [
      {
        "cart_line_id": 1,
        "product_id": 123,
        "product_name": "Gold Ring",
        "image_url": "/web/image/product.template/123/image_1920",
        "quantity": 2,
        "price": 15000.0,
        "subtotal": 30000.0
      }
    ]
  }
}
```

### Cart Clear Response
```json
{
  "status": "success",
  "message": "Cart cleared"
}
```

### Wishlist Add Response
```json
{
  "status": "success",
  "message": "Added to wishlist",
  "item": {
    "wishlist_id": 1,
    "product_id": 123,
    "product_name": "Gold Ring",
    "price": 15000.0,
    "image_url": "/web/image/product.template/123/image_1920",
    "added_on": "2024-01-15 10:30:00"
  }
}
```

### Wishlist View Response
```json
{
  "status": "success",
  "count": 2,
  "data": [
    {
      "wishlist_id": 1,
      "product_id": 123,
      "product_name": "Gold Ring",
      "price": 15000.0,
      "image_url": "/web/image/product.template/123/image_1920",
      "added_on": "2024-01-15 10:30:00"
    }
  ]
}
```

### Wishlist Remove Response
```json
{
  "status": "success",
  "message": "Removed from wishlist"
}
```

### Checkout Response
```json
{
  "status": "success",
  "message": "Order created successfully",
  "order": {
    "order_id": 1,
    "order_number": "ORD/20240115123456",
    "customer_id": 1,
    "customer_name": "John Doe",
    "subtotal_amount": 30000.0,
    "tax_amount": 0.0,
    "total_amount": 30000.0,
    "payment_method": "cash",
    "payment_status": "pending",
    "state": "confirmed",
    "shipping_address": "123 Main Street",
    "shipping_city": "Calicut",
    "shipping_phone": "1234567890",
    "notes": "Please deliver after 5 PM",
    "created_at": "2024-01-15 10:30:00",
    "confirmed_at": "2024-01-15 10:30:00",
    "delivered_at": null,
    "items": [
      {
        "order_line_id": 1,
        "product_id": 123,
        "product_name": "Gold Ring",
        "quantity": 2,
        "price": 15000.0,
        "subtotal": 30000.0
      }
    ]
  }
}
```

### Orders History Response
```json
{
  "status": "success",
  "count": 2,
  "data": [
    {
      "order_id": 2,
      "order_number": "ORD/20240116123457",
      "customer_id": 1,
      "customer_name": "John Doe",
      "subtotal_amount": 25000.0,
      "tax_amount": 0.0,
      "total_amount": 25000.0,
      "payment_method": "upi",
      "payment_status": "paid",
      "state": "delivered",
      "shipping_address": "123 Main Street",
      "shipping_city": "Calicut",
      "shipping_phone": "1234567890",
      "notes": null,
      "created_at": "2024-01-16 14:20:00",
      "confirmed_at": "2024-01-16 14:20:00",
      "delivered_at": "2024-01-17 10:00:00",
      "items": [...]
    },
    {
      "order_id": 1,
      "order_number": "ORD/20240115123456",
      "customer_id": 1,
      "customer_name": "John Doe",
      "subtotal_amount": 30000.0,
      "tax_amount": 0.0,
      "total_amount": 30000.0,
      "payment_method": "cash",
      "payment_status": "pending",
      "state": "confirmed",
      "shipping_address": "123 Main Street",
      "shipping_city": "Calicut",
      "shipping_phone": "1234567890",
      "notes": "Please deliver after 5 PM",
      "created_at": "2024-01-15 10:30:00",
      "confirmed_at": "2024-01-15 10:30:00",
      "delivered_at": null,
      "items": [...]
    }
  ]
}
```

### Order Details Response
```json
{
  "status": "success",
  "order": {
    "order_id": 1,
    "order_number": "ORD/20240115123456",
    "customer_id": 1,
    "customer_name": "John Doe",
    "subtotal_amount": 30000.0,
    "tax_amount": 0.0,
    "total_amount": 30000.0,
    "payment_method": "cash",
    "payment_status": "pending",
    "state": "confirmed",
    "shipping_address": "123 Main Street",
    "shipping_city": "Calicut",
    "shipping_phone": "1234567890",
    "notes": "Please deliver after 5 PM",
    "created_at": "2024-01-15 10:30:00",
    "confirmed_at": "2024-01-15 10:30:00",
    "delivered_at": null,
    "items": [
      {
        "order_line_id": 1,
        "product_id": 123,
        "product_name": "Gold Ring",
        "quantity": 2,
        "price": 15000.0,
        "subtotal": 30000.0
      }
    ]
  }
}
```

---

## Error Response Format
All error responses follow this format:
```json
{
  "status": "error",
  "message": "Error description"
}
```

---

## Common Error Messages

| Error | Description |
|-------|-------------|
| "customer_id and product_id are required" | Missing required parameters |
| "Customer not found" | Invalid customer_id |
| "Product not found" | Invalid product_id |
| "Product is out of stock" | No stock available |
| "Only X units available" | Insufficient stock |
| "Quantity must be greater than 0" | Invalid quantity |
| "Product already in wishlist" | Duplicate wishlist item |
| "Item not found in wishlist" | Wishlist item doesn't exist |
| "Cart item not found" | Invalid cart_line_id |
| "Invalid email or password" | Login credentials error |
| "Email already registered" | Duplicate email during registration |

---

## Notes

- **Authentication**: All endpoints use `public` authentication. Cart and wishlist APIs use `customer_id` from request body.
- **Token**: Auth token is only provided at registration. Use the `customer_id` for subsequent API calls.
- **CORS**: All endpoints have CORS enabled (`*`)
- **CSRF**: All endpoints have CSRF disabled
- **Price**: Cart items use `price` field (from product.list_price), not `unit_price`
- **Subtotal**: Calculated as `quantity × price`
