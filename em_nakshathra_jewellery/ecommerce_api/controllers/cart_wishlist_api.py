import json

from odoo import http
from odoo.http import request, Response


class EcommerceCartWishlistAPI(http.Controller):

    # ══════════════════════════════════════════════
    #  AUTHENTICATION HELPER
    # ══════════════════════════════════════════════

    def _get_token_from_request(self, kwargs=None):
        """
        Extract auth token from:
          1. Authorization header  →  'Authorization: Token <token>'
          2. Request body field    →  { "auth_token": "..." }
        Content-Type: application/json is expected when using the header.
        """
        # 1) Try Authorization header first
        auth_header = request.httprequest.headers.get('Authorization', '')
        if auth_header.startswith('Token '):
            return auth_header[6:].strip()

        # 2) Fallback: body / kwargs field
        if kwargs:
            return kwargs.get('auth_token')
        return None

    def _authenticate_token(self, token):
        """Verify authentication token and return customer."""
        if not token:
            return None, {"status": "error", "message": "auth_token is required (body) or Authorization: Token <token> header"}

        Customer = request.env['ecommerce.customer'].sudo()
        customer = Customer.search([('auth_token', '=', token)], limit=1)

        if not customer:
            return None, {"status": "error", "message": "Invalid token"}

        if not customer._verify_token(token):
            return None, {"status": "error", "message": "Token expired or invalid"}

        return customer, None

    def _json_response(self, data, status=200):
        """Return a proper JSON HTTP response (used for GET-type routes)."""
        return Response(
            json.dumps(data),
            status=status,
            mimetype='application/json',
        )

    # ══════════════════════════════════════════════
    #  CART APIs
    # ══════════════════════════════════════════════

    def _get_or_create_cart(self, customer_id):
        """Return the customer's cart, creating one if it doesn't exist."""
        Cart = request.env['ecommerce.cart'].sudo()
        cart = Cart.search([('customer_id', '=', customer_id)], limit=1)
        if not cart:
            cart = Cart.create({'customer_id': customer_id})
        return cart

    def _format_cart(self, cart):
        """Serialize a cart record into a dict."""
        lines = []
        for line in cart.line_ids:
            lines.append({
                "cart_line_id": line.id,
                "product_id": line.product_id.id,
                "product_name": line.product_id.name,
                "image_url": f"/web/image/product.template/{line.product_id.id}/image_1920",
                "quantity": line.quantity,
                "price": line.product_id.list_price,
                "subtotal": line.subtotal,
            })
        return {
            "cart_id": cart.id,
            "customer_id": cart.customer_id.id,
            "total_amount": cart.total_amount,
            "items": lines,
        }

    # ─── Add to Cart (POST + GET) ──────────────────────────────
    @http.route('/api/ecommerce/cart/add', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_add(self, **kwargs):
        """
        Add a product to the cart.
        """
        try:
            customer_id = kwargs.get('customer_id')
            product_id = kwargs.get('product_id')
            quantity   = float(kwargs.get('quantity', 1))

            if not customer_id or not product_id:
                return {"status": "error", "message": "customer_id and product_id are required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}



            if quantity <= 0:
                return {"status": "error", "message": "Quantity must be greater than 0"}

            product = request.env['product.template'].sudo().browse(int(product_id))
            if not product.exists():
                return {"status": "error", "message": "Product not found"}

            # Check stock availability
            quants = request.env['stock.quant'].sudo().search([
                ('product_id.product_tmpl_id', '=', int(product_id)),
                ('quantity', '>', 0)
            ])
            total_stock = sum(quants.mapped('quantity'))

            if total_stock <= 0:
                return {"status": "error", "message": "Product is out of stock"}

            if quantity > total_stock:
                return {"status": "error", "message": f"Only {total_stock} units available"}

            cart = self._get_or_create_cart(customer.id)

            existing_line = cart.line_ids.filtered(lambda l: l.product_id.id == int(product_id))
            if existing_line:
                new_quantity = existing_line.quantity + quantity
                if new_quantity > total_stock:
                    return {"status": "error", "message": f"Only {total_stock} units available (you have {existing_line.quantity} in cart)"}
                existing_line.sudo().write({'quantity': new_quantity})
            else:
                request.env['ecommerce.cart.line'].sudo().create({
                    'cart_id': cart.id,
                    'product_id': int(product_id),
                    'quantity': quantity,
                })

            cart = self._get_or_create_cart(customer.id)  # refresh
            return {
                "status": "success",
                "message": "Item added to cart",
                "cart": self._format_cart(cart),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/cart/add', type='http', auth='public', methods=['GET'], cors='*', csrf=False)
    def cart_add_get(self, **kwargs):
        """
        GET: Add a product to the cart via query params + Authorization header.

        Usage:
          GET /api/ecommerce/cart/add?product_id=1&quantity=2
          Headers:
            Authorization: Token <auth_token>
            Content-Type: application/json
        """
        try:
            token = self._get_token_from_request(kwargs)
            product_id = kwargs.get('product_id')
            quantity   = float(kwargs.get('quantity', 1))

            customer, error = self._authenticate_token(token)
            if error:
                return self._json_response(error, 401)

            if not product_id:
                return self._json_response({"status": "error", "message": "product_id is required"}, 400)

            if quantity <= 0:
                return self._json_response({"status": "error", "message": "Quantity must be greater than 0"}, 400)

            product = request.env['product.template'].sudo().browse(int(product_id))
            if not product.exists():
                return self._json_response({"status": "error", "message": "Product not found"}, 404)

            quants = request.env['stock.quant'].sudo().search([
                ('product_id.product_tmpl_id', '=', int(product_id)),
                ('quantity', '>', 0)
            ])
            total_stock = sum(quants.mapped('quantity'))

            if total_stock <= 0:
                return self._json_response({"status": "error", "message": "Product is out of stock"}, 400)

            if quantity > total_stock:
                return self._json_response({"status": "error", "message": f"Only {total_stock} units available"}, 400)

            cart = self._get_or_create_cart(customer.id)

            existing_line = cart.line_ids.filtered(lambda l: l.product_id.id == int(product_id))
            if existing_line:
                new_quantity = existing_line.quantity + quantity
                if new_quantity > total_stock:
                    return self._json_response({"status": "error", "message": f"Only {total_stock} units available (you have {existing_line.quantity} in cart)"}, 400)
                existing_line.sudo().write({'quantity': new_quantity})
            else:
                request.env['ecommerce.cart.line'].sudo().create({
                    'cart_id': cart.id,
                    'product_id': int(product_id),
                    'quantity': quantity,
                })

            cart = self._get_or_create_cart(customer.id)
            return self._json_response({
                "status": "success",
                "message": "Item added to cart",
                "cart": self._format_cart(cart),
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─── View Cart (POST + GET) ────────────────────────────────
    @http.route('/api/ecommerce/cart/view', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_view(self, **kwargs):
        """
        View cart via POST body or Authorization header token.

        Authentication:
          • Header:  Authorization: Token <auth_token>
          • Body:    { "auth_token": "..." }
        """
        try:
            token = self._get_token_from_request(kwargs)
            customer, error = self._authenticate_token(token)
            if error:
                return error

            cart = request.env['ecommerce.cart'].sudo().search(
                [('customer_id', '=', customer.id)], limit=1
            )
            if not cart:
                return {"status": "success", "message": "Cart is empty", "cart": {"items": [], "total_amount": 0.0}}

            return {"status": "success", "cart": self._format_cart(cart)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/cart/view', type='http', auth='public', methods=['GET'], cors='*', csrf=False)
    def cart_view_get(self, **kwargs):
        """
        GET: View the current user's cart.

        Usage:
          GET /api/ecommerce/cart/view
          Headers:
            Authorization: Token <auth_token>
            Content-Type: application/json
        """
        try:
            token = self._get_token_from_request(kwargs)
            customer, error = self._authenticate_token(token)
            if error:
                return self._json_response(error, 401)

            cart = request.env['ecommerce.cart'].sudo().search(
                [('customer_id', '=', customer.id)], limit=1
            )
            if not cart:
                return self._json_response({"status": "success", "message": "Cart is empty", "cart": {"items": [], "total_amount": 0.0}})

            return self._json_response({"status": "success", "cart": self._format_cart(cart)})
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─── Update Cart Item Quantity ─────────────────
    @http.route('/api/ecommerce/cart/update', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_update(self, **kwargs):
        try:
            token        = self._get_token_from_request(kwargs)
            cart_line_id = kwargs.get('cart_line_id')
            quantity     = float(kwargs.get('quantity', 1))

            customer, error = self._authenticate_token(token)
            if error:
                return error

            if not cart_line_id:
                return {"status": "error", "message": "cart_line_id is required"}

            line = request.env['ecommerce.cart.line'].sudo().browse(int(cart_line_id))
            if not line.exists() or line.cart_id.customer_id.id != customer.id:
                return {"status": "error", "message": "Cart item not found"}

            if quantity <= 0:
                line.unlink()
                msg = "Item removed from cart"
            else:
                quants = request.env['stock.quant'].sudo().search([
                    ('product_id.product_tmpl_id', '=', line.product_id.id),
                    ('quantity', '>', 0)
                ])
                total_stock = sum(quants.mapped('quantity'))

                if quantity > total_stock:
                    return {"status": "error", "message": f"Only {total_stock} units available"}

                line.write({'quantity': quantity})
                msg = "Cart updated"

            cart = self._get_or_create_cart(customer.id)
            return {"status": "success", "message": msg, "cart": self._format_cart(cart)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── Remove Item from Cart ────────────────────
    @http.route('/api/ecommerce/cart/remove', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_remove(self, **kwargs):
        try:
            token        = self._get_token_from_request(kwargs)
            cart_line_id = kwargs.get('cart_line_id')

            customer, error = self._authenticate_token(token)
            if error:
                return error

            if not cart_line_id:
                return {"status": "error", "message": "cart_line_id is required"}

            line = request.env['ecommerce.cart.line'].sudo().browse(int(cart_line_id))
            if not line.exists() or line.cart_id.customer_id.id != customer.id:
                return {"status": "error", "message": "Cart item not found"}

            line.unlink()
            cart = self._get_or_create_cart(customer.id)
            return {"status": "success", "message": "Item removed from cart", "cart": self._format_cart(cart)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── Clear Entire Cart ────────────────────────
    @http.route('/api/ecommerce/cart/clear', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_clear(self, **kwargs):
        try:
            token = self._get_token_from_request(kwargs)
            customer, error = self._authenticate_token(token)
            if error:
                return error

            cart = request.env['ecommerce.cart'].sudo().search(
                [('customer_id', '=', customer.id)], limit=1
            )
            if cart:
                cart.line_ids.unlink()
            return {"status": "success", "message": "Cart cleared"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ══════════════════════════════════════════════
    #  WISHLIST APIs
    # ══════════════════════════════════════════════

    def _format_wishlist_item(self, item):
        prod = item.product_id
        return {
            "wishlist_id": item.id,
            "product_id": prod.id,
            "product_name": prod.name,
            "price": prod.list_price,
            "image_url": f"/web/image/product.template/{prod.id}/image_1920",
            "added_on": item.added_on.strftime('%Y-%m-%d %H:%M:%S') if item.added_on else None,
        }

    # ─── Add to Wishlist (POST + GET) ──────────────────────────
    @http.route('/api/ecommerce/wishlist/add', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def wishlist_add(self, **kwargs):
        """
        Add a product to the wishlist.

        Authentication (choose one):
          • Header:  Authorization: Token <auth_token>
                     Content-Type: application/json
          • Body:    { "auth_token": "...", "product_id": 1 }
        """
        try:
            token      = self._get_token_from_request(kwargs)
            product_id = kwargs.get('product_id')

            customer, error = self._authenticate_token(token)
            if error:
                return error

            if not product_id:
                return {"status": "error", "message": "product_id is required"}

            Wishlist = request.env['ecommerce.wishlist'].sudo()
            existing = Wishlist.search([
                ('customer_id', '=', customer.id),
                ('product_id',  '=', int(product_id)),
            ], limit=1)

            if existing:
                return {"status": "error", "message": "Product already in wishlist"}

            item = Wishlist.create({
                'customer_id': customer.id,
                'product_id': int(product_id),
            })

            return {
                "status": "success",
                "message": "Added to wishlist",
                "item": self._format_wishlist_item(item),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/wishlist/add', type='http', auth='public', methods=['GET'], cors='*', csrf=False)
    def wishlist_add_get(self, **kwargs):
        """
        GET: Add a product to the wishlist via query params + Authorization header.

        Usage:
          GET /api/ecommerce/wishlist/add?product_id=1
          Headers:
            Authorization: Token <auth_token>
            Content-Type: application/json
        """
        try:
            token      = self._get_token_from_request(kwargs)
            product_id = kwargs.get('product_id')

            customer, error = self._authenticate_token(token)
            if error:
                return self._json_response(error, 401)

            if not product_id:
                return self._json_response({"status": "error", "message": "product_id is required"}, 400)

            Wishlist = request.env['ecommerce.wishlist'].sudo()
            existing = Wishlist.search([
                ('customer_id', '=', customer.id),
                ('product_id',  '=', int(product_id)),
            ], limit=1)

            if existing:
                return self._json_response({"status": "error", "message": "Product already in wishlist"}, 409)

            item = Wishlist.create({
                'customer_id': customer.id,
                'product_id': int(product_id),
            })

            return self._json_response({
                "status": "success",
                "message": "Added to wishlist",
                "item": self._format_wishlist_item(item),
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─── View Wishlist (POST + GET) ────────────────────────────
    @http.route('/api/ecommerce/wishlist/view', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def wishlist_view(self, **kwargs):
        """
        View wishlist via POST body or Authorization header token.

        Authentication:
          • Header:  Authorization: Token <auth_token>
          • Body:    { "auth_token": "..." }
        """
        try:
            token = self._get_token_from_request(kwargs)
            customer, error = self._authenticate_token(token)
            if error:
                return error

            items = request.env['ecommerce.wishlist'].sudo().search(
                [('customer_id', '=', customer.id)]
            )
            return {
                "status": "success",
                "count": len(items),
                "data": [self._format_wishlist_item(i) for i in items],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/wishlist/view', type='http', auth='public', methods=['GET'], cors='*', csrf=False)
    def wishlist_view_get(self, **kwargs):
        """
        GET: View the current user's wishlist.

        Usage:
          GET /api/ecommerce/wishlist/view
          Headers:
            Authorization: Token <auth_token>
            Content-Type: application/json
        """
        try:
            token = self._get_token_from_request(kwargs)
            customer, error = self._authenticate_token(token)
            if error:
                return self._json_response(error, 401)

            items = request.env['ecommerce.wishlist'].sudo().search(
                [('customer_id', '=', customer.id)]
            )
            return self._json_response({
                "status": "success",
                "count": len(items),
                "data": [self._format_wishlist_item(i) for i in items],
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─── Remove from Wishlist ─────────────────────
    @http.route('/api/ecommerce/wishlist/remove', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def wishlist_remove(self, **kwargs):
        try:
            token      = self._get_token_from_request(kwargs)
            product_id = kwargs.get('product_id')

            customer, error = self._authenticate_token(token)
            if error:
                return error

            if not product_id:
                return {"status": "error", "message": "product_id is required"}

            item = request.env['ecommerce.wishlist'].sudo().search([
                ('customer_id', '=', customer.id),
                ('product_id',  '=', int(product_id)),
            ], limit=1)

            if not item:
                return {"status": "error", "message": "Item not found in wishlist"}

            item.unlink()
            return {"status": "success", "message": "Removed from wishlist"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
