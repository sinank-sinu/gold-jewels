from odoo import http
from odoo.http import request

class EcommerceReviewsAndReferralsAPI(http.Controller):

    @http.route('/api/ecommerce/reviews/add', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def review_add(self, **kwargs):
        """Submit a new review for a product."""
        try:
            customer_id = kwargs.get('customer_id')
            product_id = kwargs.get('product_id')
            rating = kwargs.get('rating')
            review_text = kwargs.get('review_text')

            if not all([customer_id, product_id, rating, review_text]):
                return {"status": "error", "message": "customer_id, product_id, rating, and review_text are required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            product = request.env['product.template'].sudo().browse(int(product_id))
            if not product.exists():
                return {"status": "error", "message": "Product not found"}

            # Validate rating is between 1 and 5
            try:
                rating_val = int(rating)
                if not (1 <= rating_val <= 5):
                    raise ValueError()
            except ValueError:
                return {"status": "error", "message": "Rating must be an integer between 1 and 5"}

            review = request.env['ecommerce.product.review'].sudo().create({
                'customer_id': customer.id,
                'product_id': product.id,
                'rating': rating_val,
                'review_text': review_text
            })

            return {
                "status": "success",
                "message": "Review submitted successfully",
                "review_id": review.id
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/reviews/get', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def reviews_get(self, **kwargs):
        """Retrieve all reviews submitted by a specific customer."""
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            reviews = request.env['ecommerce.product.review'].sudo().search([('customer_id', '=', customer.id)])

            reviews_data = []
            for review in reviews:
                # Format date like 'June 26, 2026'
                date_str = review.review_date.strftime('%B %d, %Y') if review.review_date else ""
                reviews_data.append({
                    "id": review.id,
                    "product_id": review.product_id.id,
                    "product_name": review.product_id.name,
                    "rating": review.rating,
                    "review_text": review.review_text,
                    "review_date": date_str
                })

            return {
                "status": "success",
                "reviews": reviews_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/referral/info', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def referral_info(self, **kwargs):
        """Get customer's referral dashboard details."""
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            friends_invited = len(customer.referral_ids)
            gold_earned = customer.referral_earning

            return {
                "status": "success",
                "referral_code": customer.referral_code or "NAKSH-SHINE-77",
                "friends_invited": friends_invited,
                "gold_earned": gold_earned
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/referral/invite', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def referral_invite(self, **kwargs):
        """Submit a friend referral invite."""
        try:
            customer_id = kwargs.get('customer_id')
            friend_email = kwargs.get('friend_email')
            friend_phone = kwargs.get('friend_phone')

            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            if not friend_email and not friend_phone:
                return {"status": "error", "message": "Either friend_email or friend_phone is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            invite = request.env['ecommerce.referral'].sudo().create({
                'referrer_id': customer.id,
                'friend_email': friend_email,
                'friend_phone': friend_phone,
                'status': 'pending',
                'coupon_value': 500.0
            })

            return {
                "status": "success",
                "message": "Referral invitation recorded successfully",
                "invite_id": invite.id
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
