import json
from odoo import http
from odoo.http import request

RAZORPAY_KEY_ID = "rzp_test_TZTOVDHOQcGeUv"
RAZORPAY_KEY_SECRET = "mAROO5PBwVt2rmPyjLBSZN5l"


class EcommercePaymentAPI(http.Controller):

    @http.route('/api/ecommerce/payment_methods', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def payment_methods(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            cards = request.env['ecommerce.card'].sudo().search([('customer_id', '=', customer.id)])
            upi_profiles = request.env['ecommerce.upi'].sudo().search([('customer_id', '=', customer.id)])

            cards_data = []
            for card in cards:
                cards_data.append({
                    'id': card.id,
                    'card_type': card.card_type.capitalize() if card.card_type else '',
                    'card_holder_name': card.card_holder_name,
                    'card_number': card.card_number_masked,
                    'expiry': card.expiry,
                })

            upi_data = []
            for upi in upi_profiles:
                upi_data.append({
                    'id': upi.id,
                    'upi_id': upi.upi_id,
                    'status': upi.status,
                })

            key_id = request.env['ir.config_parameter'].sudo().get_param('razorpay.key_id', RAZORPAY_KEY_ID)

            return {
                "status": "success",
                "cards": cards_data,
                "upi_profiles": upi_data,
                "razorpay": {
                    "key_id": key_id,
                    "enabled": True,
                    "currency": "INR"
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/card/add', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def card_add(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            card_holder_name = kwargs.get('card_holder_name')
            card_number = kwargs.get('card_number')
            card_type = kwargs.get('card_type')
            expiry = kwargs.get('expiry')

            if not all([customer_id, card_holder_name, card_number, card_type, expiry]):
                return {"status": "error", "message": "customer_id, card_holder_name, card_number, card_type, and expiry are required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            ct_lower = str(card_type).lower()
            if ct_lower not in ('visa', 'mastercard', 'rupay'):
                return {"status": "error", "message": "Invalid card_type. Must be: Visa, Mastercard, or Rupay"}

            card = request.env['ecommerce.card'].sudo().create({
                'customer_id': customer.id,
                'card_holder_name': card_holder_name,
                'card_number': card_number,
                'card_type': ct_lower,
                'expiry': expiry,
            })

            return {
                "status": "success",
                "message": "Card added successfully",
                "card_id": card.id,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/card/delete', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def card_delete(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            card_id = kwargs.get('card_id')

            if not customer_id or not card_id:
                return {"status": "error", "message": "customer_id and card_id are required"}

            card = request.env['ecommerce.card'].sudo().search([
                ('id', '=', int(card_id)),
                ('customer_id', '=', int(customer_id))
            ], limit=1)

            if not card:
                return {"status": "error", "message": "Card not found"}

            card.unlink()

            return {
                "status": "success",
                "message": "Card deleted successfully",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/upi/add', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def upi_add(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            upi_id = kwargs.get('upi_id')
            status = kwargs.get('status', 'active')

            if not customer_id or not upi_id:
                return {"status": "error", "message": "customer_id and upi_id are required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            upi = request.env['ecommerce.upi'].sudo().create({
                'customer_id': customer.id,
                'upi_id': upi_id,
                'status': status.lower() if status else 'active',
            })

            return {
                "status": "success",
                "message": "UPI Profile added successfully",
                "upi_profile_id": upi.id,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/upi/delete', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def upi_delete(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            upi_profile_id = kwargs.get('upi_profile_id')

            if not customer_id or not upi_profile_id:
                return {"status": "error", "message": "customer_id and upi_profile_id are required"}

            upi = request.env['ecommerce.upi'].sudo().search([
                ('id', '=', int(upi_profile_id)),
                ('customer_id', '=', int(customer_id))
            ], limit=1)

            if not upi:
                return {"status": "error", "message": "UPI Profile not found"}

            upi.unlink()

            return {
                "status": "success",
                "message": "UPI Profile deleted successfully",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/razorpay/config', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def razorpay_config(self, **kwargs):
        try:
            key_id = request.env['ir.config_parameter'].sudo().get_param('razorpay.key_id', RAZORPAY_KEY_ID)
            return {
                "status": "success",
                "key_id": key_id,
                "currency": "INR"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
