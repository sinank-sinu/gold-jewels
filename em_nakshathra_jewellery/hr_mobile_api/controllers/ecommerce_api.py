from odoo import http
from odoo.http import request

class EcommerceMobileAPI(http.Controller):
    #LOGIN
    @http.route('/api/ecommerce/login', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def login(self, **kwargs):
        db_name = kwargs.get('db') or request.db
        try:
            username = kwargs.get('username')
            password = kwargs.get('password')

            if not username or not password:
                return {
                    "status": "error",
                    "message": "Username and password required"
                }

            uid = request.session.authenticate(db_name, username, password)

            if not uid:
                return {
                    "status": "error",
                    "message": "Invalid credentials"
                }

            user = request.env['res.users'].sudo().browse(uid)

            employee = request.env['hr.employee'].sudo().search([
                ('user_id', '=', user.id)
            ], limit=1)

            return {
                "status": "success",
                "session_id": request.session.sid,
                "data": {
                    "user_id": user.id,
                    "name": user.name,
                    "email": user.login,
                    "employee_id": employee.id if employee else None,
                    "employee_name": employee.name if employee else None,
                    "job_position": employee.job_id.name if employee and employee.job_id else ""
                }
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    #LOGOUT
    @http.route('/api/ecommerce/logout', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def logout(self, **kwargs):
        try:
            request.session.logout()
            
            return {
                "status": "success",
                "message": "Successfully logged out"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    
    #Categories
    @http.route('/api/ecommerce/categories', type='json', auth='none', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_ecommerce_categories(self, **kwargs):
        try:
            categories = request.env['product.public.category'].sudo().search([])

            category_data = []
            for cat in categories:
                category_data.append({
                    "category_id": cat.id,
                    "name": cat.name,
                    "image_url": f"/web/image/product.public.category/{cat.id}/image_1920",
                    
                })

            return {
                "status": "success",
                "data": category_data
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    
    #Product published
    @http.route('/api/ecommerce/products', type='json', auth='none', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_published_products(self, **kwargs):
        try:
            # Optional filters from the mobile app
            category_id = kwargs.get('category_id')
            limit = kwargs.get('limit', 80) # Default limit for performance
            
            # Domain: Only products marked 'Can be Sold' and 'Published' on website
            domain = [
                ('sale_ok', '=', True),
                ('website_published', '=', True)
            ]
            
            # If the user clicks a specific category in the app
            if category_id:
                domain.append(('public_categ_ids', 'child_of', int(category_id)))

            # Search for products
            products = request.env['product.template'].sudo().search(domain, limit=limit)

            product_data = []
            for prod in products:
                product_data.append({
                    "id": prod.id,
                    "name": prod.name,
                    "price": prod.list_price, # Base price
                    "currency": prod.currency_id.name,
                    "categories": prod.public_categ_ids.mapped('name'),
                    "image_url": f"/web/image/product.template/{prod.id}/image_1920",
                })

            return {
                "status": "success",
                "count": len(product_data),
                "data": product_data
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }