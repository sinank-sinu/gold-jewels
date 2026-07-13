import json

from odoo import http
from odoo.http import request, Response


class EcommerceOrderAPI(http.Controller):

    # ══════════════════════════════════════════════
    #  AUTHENTICATION HELPER
    # ══════════════════════════════════════════════

    def _get_token_from_request(self, kwargs=None):
        """
        Extract auth token from:
          1. Authorization header  →  'Authorization: Token <token>'
          2. Request body field    →  { "auth_token": "..." }
        """
        auth_header = request.httprequest.headers.get('Authorization', '')
        if auth_header.startswith('Token '):
            return auth_header[6:].strip()

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
        """Return a proper JSON HTTP response."""
        return Response(
            json.dumps(data),
            status=status,
            mimetype='application/json'
        )

    def _format_order(self, order):
        """Serialize an order record into a dict."""
        lines = []
        for line in order.line_ids:
            lines.append({
                "order_line_id": line.id,
                "product_id": line.product_id.id,
                "product_name": line.product_name,
                "quantity": line.quantity,
                "price": round(line.price, 2) if line.price else 0.0,
                "subtotal": round(line.subtotal, 2) if line.subtotal else 0.0,
            })
        return {
            "order_id": order.id,
            "order_number": order.order_number,
            "customer_id": order.customer_id.id,
            "customer_name": order.customer_id.name,
            "subtotal_amount": round(order.subtotal_amount, 2) if order.subtotal_amount else 0.0,
            "tax_amount": round(order.tax_amount, 2) if order.tax_amount else 0.0,
            "total_amount": round(order.total_amount, 2) if order.total_amount else 0.0,
            "payment_method": order.payment_method,
            "payment_status": order.payment_status,
            "state": order.state,
            "shipping_address": order.shipping_address,
            "shipping_city": order.shipping_city,
            "shipping_phone": order.shipping_phone,
            "notes": order.notes,
            "created_at": order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else None,
            "confirmed_at": order.confirmed_at.strftime('%Y-%m-%d %H:%M:%S') if order.confirmed_at else None,
            "delivered_at": order.delivered_at.strftime('%Y-%m-%d %H:%M:%S') if order.delivered_at else None,
            "items": lines,
        }

    # ══════════════════════════════════════════════
    #  CHECKOUT API
    # ══════════════════════════════════════════════

    @http.route('/api/ecommerce/checkout', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def checkout(self, **kwargs):
        """
        Convert cart to order (POST with customer_id).
        """
        try:
            customer_id = kwargs.get('customer_id')
            payment_method = kwargs.get('payment_method')
            shipping_address = kwargs.get('shipping_address')
            shipping_city = kwargs.get('shipping_city')
            shipping_phone = kwargs.get('shipping_phone')
            notes = kwargs.get('notes')

            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            if not payment_method:
                return {"status": "error", "message": "payment_method is required"}

            if payment_method not in ['cash', 'bank', 'upi', 'card']:
                return {"status": "error", "message": "Invalid payment_method. Must be: cash, bank, upi, or card"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            # Get customer's cart
            cart = request.env['ecommerce.cart'].sudo().search(
                [('customer_id', '=', customer.id)], limit=1
            )
            if not cart or not cart.line_ids:
                return {"status": "error", "message": "Cart is empty"}

            # Check stock availability
            for line in cart.line_ids:
                quants = request.env['stock.quant'].sudo().search([
                    ('product_id.product_tmpl_id', '=', line.product_id.id),
                    ('quantity', '>', 0)
                ])
                total_stock = sum(quants.mapped('quantity'))
                if line.quantity > total_stock:
                    return {"status": "error", "message": f"Product {line.product_id.name} has only {total_stock} units available"}

            # Create order
            Order = request.env['ecommerce.order'].sudo()
            order = Order.create({
                'customer_id': customer.id,
                'payment_method': payment_method,
                'shipping_address': shipping_address,
                'shipping_city': shipping_city,
                'shipping_phone': shipping_phone,
                'notes': notes,
                'state': 'confirmed',
            })

            # Create order lines from cart lines
            for line in cart.line_ids:
                request.env['ecommerce.order.line'].sudo().create({
                    'order_id': order.id,
                    'product_id': line.product_id.id,
                    'quantity': line.quantity,
                    'price': line.price,
                })

            # Clear cart
            cart.line_ids.unlink()

            return {
                "status": "success",
                "message": "Order created successfully",
                "order": self._format_order(order),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/checkout', type='http', auth='public', methods=['GET'], cors='*', csrf=False)
    def checkout_get(self, **kwargs):
        """
        Convert cart to order (GET with token).
        """
        try:
            token = self._get_token_from_request(kwargs)
            customer, error = self._authenticate_token(token)
            if error:
                return self._json_response(error, 401)

            # Parse request body
            try:
                body_data = json.loads(request.httprequest.data)
                payment_method = body_data.get('payment_method')
                shipping_address = body_data.get('shipping_address')
                shipping_city = body_data.get('shipping_city')
                shipping_phone = body_data.get('shipping_phone')
                notes = body_data.get('notes')
            except:
                return self._json_response({"status": "error", "message": "Invalid request body"}, 400)

            if not payment_method:
                return self._json_response({"status": "error", "message": "payment_method is required"}, 400)

            if payment_method not in ['cash', 'bank', 'upi', 'card']:
                return self._json_response({"status": "error", "message": "Invalid payment_method. Must be: cash, bank, upi, or card"}, 400)

            # Get customer's cart
            cart = request.env['ecommerce.cart'].sudo().search(
                [('customer_id', '=', customer.id)], limit=1
            )
            if not cart or not cart.line_ids:
                return self._json_response({"status": "error", "message": "Cart is empty"}, 400)

            # Check stock availability
            for line in cart.line_ids:
                quants = request.env['stock.quant'].sudo().search([
                    ('product_id.product_tmpl_id', '=', line.product_id.id),
                    ('quantity', '>', 0)
                ])
                total_stock = sum(quants.mapped('quantity'))
                if line.quantity > total_stock:
                    return self._json_response({"status": "error", "message": f"Product {line.product_id.name} has only {total_stock} units available"}, 400)

            # Create order
            Order = request.env['ecommerce.order'].sudo()
            order = Order.create({
                'customer_id': customer.id,
                'payment_method': payment_method,
                'shipping_address': shipping_address,
                'shipping_city': shipping_city,
                'shipping_phone': shipping_phone,
                'notes': notes,
                'state': 'confirmed',
            })

            # Create order lines from cart lines
            for line in cart.line_ids:
                request.env['ecommerce.order.line'].sudo().create({
                    'order_id': order.id,
                    'product_id': line.product_id.id,
                    'quantity': line.quantity,
                    'price': line.price,
                })

            # Clear cart
            cart.line_ids.unlink()

            return self._json_response({
                "status": "success",
                "message": "Order created successfully",
                "order": self._format_order(order),
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ══════════════════════════════════════════════
    #  ORDER HISTORY API
    # ══════════════════════════════════════════════

    @http.route('/api/ecommerce/orders', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def orders(self, **kwargs):
        """
        View customer's order history (POST with customer_id).
        """
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            orders = request.env['ecommerce.order'].sudo().search(
                [('customer_id', '=', customer.id)],
                order='created_at desc'
            )
            return {
                "status": "success",
                "count": len(orders),
                "data": [self._format_order(order) for order in orders],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/orders', type='http', auth='public', methods=['GET'], cors='*', csrf=False)
    def orders_get(self, **kwargs):
        """
        View customer's order history (GET with token).
        """
        try:
            token = self._get_token_from_request(kwargs)
            customer, error = self._authenticate_token(token)
            if error:
                return self._json_response(error, 401)

            orders = request.env['ecommerce.order'].sudo().search(
                [('customer_id', '=', customer.id)],
                order='created_at desc'
            )
            return self._json_response({
                "status": "success",
                "count": len(orders),
                "data": [self._format_order(order) for order in orders],
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ══════════════════════════════════════════════
    #  ORDER DETAILS API
    # ══════════════════════════════════════════════

    @http.route('/api/ecommerce/order/<int:order_id>', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def order_details(self, order_id, **kwargs):
        """
        View specific order details (POST with customer_id).
        """
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            order = request.env['ecommerce.order'].sudo().browse(order_id)
            if not order.exists():
                return {"status": "error", "message": "Order not found"}

            if order.customer_id.id != customer.id:
                return {"status": "error", "message": "Access denied"}

            return {
                "status": "success",
                "order": self._format_order(order),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/order/<int:order_id>', type='http', auth='public', methods=['GET'], cors='*', csrf=False)
    def order_details_get(self, order_id, **kwargs):
        """
        View specific order details (GET with token).
        """
        try:
            token = self._get_token_from_request(kwargs)
            customer, error = self._authenticate_token(token)
            if error:
                return self._json_response(error, 401)

            order = request.env['ecommerce.order'].sudo().browse(order_id)
            if not order.exists():
                return self._json_response({"status": "error", "message": "Order not found"}, 404)

            if order.customer_id.id != customer.id:
                return self._json_response({"status": "error", "message": "Access denied"}, 403)

            return self._json_response({
                "status": "success",
                "order": self._format_order(order),
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)
