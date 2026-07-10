from odoo import http
from odoo.http import request


class EcommerceCartWishlistAPI(http.Controller):

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
                "unit_price": line.price,
                "subtotal": line.subtotal,
            })
        return {
            "cart_id": cart.id,
            "customer_id": cart.customer_id.id,
            "total_amount": cart.total_amount,
            "items": lines,
        }

    # ─── Add to Cart ──────────────────────────────
    @http.route('/api/ecommerce/cart/add', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_add(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            product_id  = kwargs.get('product_id')
            quantity    = float(kwargs.get('quantity', 1))

            if not customer_id or not product_id:
                return {"status": "error", "message": "customer_id and product_id are required"}

            if quantity <= 0:
                return {"status": "error", "message": "Quantity must be greater than 0"}

            # Validate customer
            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            # Validate product
            product = request.env['product.template'].sudo().browse(int(product_id))
            if not product.exists():
                return {"status": "error", "message": "Product not found"}

            cart = self._get_or_create_cart(int(customer_id))

            # If product already in cart, increase quantity
            existing_line = cart.line_ids.filtered(lambda l: l.product_id.id == int(product_id))
            if existing_line:
                existing_line.sudo().write({'quantity': existing_line.quantity + quantity})
            else:
                request.env['ecommerce.cart.line'].sudo().create({
                    'cart_id': cart.id,
                    'product_id': int(product_id),
                    'quantity': quantity,
                })

            cart = self._get_or_create_cart(int(customer_id))  # refresh
            return {
                "status": "success",
                "message": "Item added to cart",
                "cart": self._format_cart(cart),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── View Cart ────────────────────────────────
    @http.route('/api/ecommerce/cart/view', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_view(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            cart = request.env['ecommerce.cart'].sudo().search(
                [('customer_id', '=', int(customer_id))], limit=1
            )
            if not cart:
                return {"status": "success", "message": "Cart is empty", "cart": {"items": [], "total_amount": 0.0}}

            return {"status": "success", "cart": self._format_cart(cart)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── Update Cart Item Quantity ─────────────────
    @http.route('/api/ecommerce/cart/update', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_update(self, **kwargs):
        try:
            customer_id  = kwargs.get('customer_id')
            cart_line_id = kwargs.get('cart_line_id')
            quantity     = float(kwargs.get('quantity', 1))

            if not customer_id or not cart_line_id:
                return {"status": "error", "message": "customer_id and cart_line_id are required"}

            line = request.env['ecommerce.cart.line'].sudo().browse(int(cart_line_id))
            if not line.exists() or line.cart_id.customer_id.id != int(customer_id):
                return {"status": "error", "message": "Cart item not found"}

            if quantity <= 0:
                line.unlink()
                msg = "Item removed from cart"
            else:
                line.write({'quantity': quantity})
                msg = "Cart updated"

            cart = self._get_or_create_cart(int(customer_id))
            return {"status": "success", "message": msg, "cart": self._format_cart(cart)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── Remove Item from Cart ────────────────────
    @http.route('/api/ecommerce/cart/remove', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_remove(self, **kwargs):
        try:
            customer_id  = kwargs.get('customer_id')
            cart_line_id = kwargs.get('cart_line_id')

            if not customer_id or not cart_line_id:
                return {"status": "error", "message": "customer_id and cart_line_id are required"}

            line = request.env['ecommerce.cart.line'].sudo().browse(int(cart_line_id))
            if not line.exists() or line.cart_id.customer_id.id != int(customer_id):
                return {"status": "error", "message": "Cart item not found"}

            line.unlink()
            cart = self._get_or_create_cart(int(customer_id))
            return {"status": "success", "message": "Item removed from cart", "cart": self._format_cart(cart)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── Clear Entire Cart ────────────────────────
    @http.route('/api/ecommerce/cart/clear', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def cart_clear(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            cart = request.env['ecommerce.cart'].sudo().search(
                [('customer_id', '=', int(customer_id))], limit=1
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

    # ─── Add to Wishlist ──────────────────────────
    @http.route('/api/ecommerce/wishlist/add', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def wishlist_add(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            product_id  = kwargs.get('product_id')

            if not customer_id or not product_id:
                return {"status": "error", "message": "customer_id and product_id are required"}

            Wishlist = request.env['ecommerce.wishlist'].sudo()
            existing = Wishlist.search([
                ('customer_id', '=', int(customer_id)),
                ('product_id',  '=', int(product_id)),
            ], limit=1)

            if existing:
                return {"status": "error", "message": "Product already in wishlist"}

            item = Wishlist.create({
                'customer_id': int(customer_id),
                'product_id': int(product_id),
            })

            return {
                "status": "success",
                "message": "Added to wishlist",
                "item": self._format_wishlist_item(item),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── View Wishlist ────────────────────────────
    @http.route('/api/ecommerce/wishlist/view', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def wishlist_view(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            items = request.env['ecommerce.wishlist'].sudo().search(
                [('customer_id', '=', int(customer_id))]
            )
            return {
                "status": "success",
                "count": len(items),
                "data": [self._format_wishlist_item(i) for i in items],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── Remove from Wishlist ─────────────────────
    @http.route('/api/ecommerce/wishlist/remove', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def wishlist_remove(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            product_id  = kwargs.get('product_id')

            if not customer_id or not product_id:
                return {"status": "error", "message": "customer_id and product_id are required"}

            item = request.env['ecommerce.wishlist'].sudo().search([
                ('customer_id', '=', int(customer_id)),
                ('product_id',  '=', int(product_id)),
            ], limit=1)

            if not item:
                return {"status": "error", "message": "Item not found in wishlist"}

            item.unlink()
            return {"status": "success", "message": "Removed from wishlist"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
