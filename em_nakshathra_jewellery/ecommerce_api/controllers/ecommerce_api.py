import json
import random
import datetime
import logging
from odoo import http, fields
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class EcommerceBranchAPI(http.Controller):

    def _resolve_branch(self, kwargs, customer=None):
        """
        Resolve Branch object prioritizing:
        1. Registered customer's saved branch (from customer parameter, customer_id, or auth_token)
        2. Active HTTP Session saved branch (from registration or previous login)
        3. Explicit kwargs['branch_id'] / kwargs['branch_name'] if no authenticated customer branch exists
        4. Default fallback branch (Calicut ID 11 / First available branch)
        """
        Branch = request.env['res.branch'].sudo()
        branch_id = kwargs.get('branch_id')
        branch_name = (kwargs.get('branch_name') or '').strip()
        customer_id = kwargs.get('customer_id')

        branch = None

        # 1. From customer object or customer_id
        if not customer and customer_id:
            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))

        if not customer or not customer.exists():
            token = None
            auth_header = request.httprequest.headers.get('Authorization', '')
            if auth_header.startswith('Token '):
                token = auth_header[6:].strip()
            if not token:
                token = kwargs.get('auth_token')
            if token:
                cust = request.env['ecommerce.customer'].sudo().search([('auth_token', '=', token)], limit=1)
                if cust and cust.exists():
                    customer = cust

        if customer and customer.exists() and customer.branch_id:
            branch = customer.branch_id

        # 2. From request session (saved from registration / login)
        if (not branch or not branch.exists()) and request.session and request.session.get('branch_id'):
            sess_branch = Branch.browse(int(request.session['branch_id']))
            if sess_branch.exists():
                branch = sess_branch

        # 3. Explicit branch_id or branch_name parameter (only if no customer/session branch exists)
        if (not branch or not branch.exists()):
            if branch_id:
                branch = Branch.browse(int(branch_id))
            elif branch_name:
                found_branch = Branch.search([('name', 'ilike', branch_name)], limit=1)
                if found_branch:
                    branch = found_branch

        # 4. Default fallback to Calicut (ID 11) or first available branch
        if not branch or not branch.exists():
            branch = Branch.search([('id', '=', 11)], limit=1)
        if not branch or not branch.exists():
            branch = Branch.search([], limit=1)

        # Store into session for continuity across subsequent API calls
        if branch and branch.exists() and request.session:
            request.session['branch_id'] = branch.id

        return branch

    # ─────────────────────────────────────────────
    # BRANCH PRODUCTS
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/branch_products', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_branch_products(self, **kwargs):
        try:
            branch = self._resolve_branch(kwargs)
            if not branch or not branch.exists():
                return {"status": "error", "message": "Branch not found"}

            branch_id = branch.id
            resolved_branch_name = branch.name
            location_id = kwargs.get('location_id')
            location_name = (kwargs.get('location_name') or '').strip()
            currency_code = kwargs.get('currency')
            customer_id = kwargs.get('customer_id')

            # ── Resolve target currency for price conversion ──
            Currency = request.env['res.currency'].sudo()
            target_currency = None
            if currency_code:
                target_currency = Currency.search([('name', '=', currency_code.upper())], limit=1)
            if not target_currency and customer_id:
                customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
                if customer.exists() and customer.currency_id:
                    target_currency = customer.currency_id

            company = branch.company_id if branch and branch.company_id else request.env.company
            company_currency = company.currency_id
            if not target_currency:
                target_currency = company_currency

            domain = [
                ('sale_ok', '=', True),
                '|',
                ('branch_id', '=', int(branch_id)),
                ('branch_id', '=', False)
            ]

            products = request.env['product.template'].sudo().search(domain)

            # ── Get locations for this branch ──
            location_domain = [('branch_id', '=', int(branch_id))]
            
            # ── Filter by specific location if provided ──
            if location_id:
                location_domain.append(('id', '=', int(location_id)))
            elif location_name:
                location_domain.append(('name', 'ilike', location_name))
            
            locations = request.env['stock.location'].sudo().search(location_domain)

            # ── Pre-fetch quants and labels in batch ──
            all_quants = request.env['stock.quant'].sudo().search([
                ('product_id.product_tmpl_id', 'in', products.ids),
                ('location_id', 'in', locations.ids),
                ('quantity', '>', 0)
            ])
            quant_map = {}
            for q in all_quants:
                key = (q.product_id.product_tmpl_id.id, q.location_id.id)
                quant_map.setdefault(key, []).append(q)

            all_labels = request.env['product.label'].sudo().search([
                ('product_tmpl_id', 'in', products.ids),
                ('branch_location_id', 'in', locations.ids),
                ('active', '=', True)
            ])
            label_map = {}
            for l in all_labels:
                key = (l.product_tmpl_id.id, l.branch_location_id.id)
                label_map.setdefault(key, []).append(l)

            product_data = []
            for prod in products:
                description = prod.description_sale or prod.description or ""
                
                # ── Get product purity ──
                purity_name = prod.purity_id.name if prod.purity_id else None
                purity_percentage = prod.purity_id.percentage if prod.purity_id else None
                
                # ── Get stock quantities for each location ──
                location_stocks = []
                total_stock = 0
                available_locations = []
                
                for loc in locations:
                    prod_loc_quants = quant_map.get((prod.id, loc.id), [])
                    total_qty = sum(q.quantity for q in prod_loc_quants)
                    
                    if total_qty > 0:
                        total_stock += total_qty
                        available_locations.append(loc.name)
                        
                        # ── Get label information for this product at this location ──
                        prod_loc_labels = label_map.get((prod.id, loc.id), [])
                        
                        label_data = []
                        for label in prod_loc_labels:
                            label_data.append({
                                "label_number": label.label_number,
                                "label_name": label.name,
                                "tag_weight": label.tag_weight,
                                "grams": label.sale_gross_weight,
                                "purity": label.purity_id.name if label.purity_id else purity_name,
                                "purity_percentage": label.purity_id.percentage if label.purity_id else purity_percentage
                            })
                        
                        loc_price = prod.list_price or 0.0
                        if target_currency != company_currency:
                            loc_price = company_currency._convert(loc_price, target_currency, company, fields.Date.today())

                        location_stocks.append({
                            "location_id": loc.id,
                            "location_name": loc.name,
                            "location_complete_name": loc.complete_name,
                            "product_name": prod.name,
                            "price": round(loc_price, 2),
                            "description": description,
                            "image_url": f"/web/image/product.template/{prod.id}/image_1920",
                            "quantity": total_qty,
                            "purity": purity_name,
                            "purity_percentage": purity_percentage,
                            "labels": label_data
                        })
                
                # ── Only include products with stock ──
                if total_stock > 0:
                    prod_price = prod.list_price or 0.0
                    if target_currency != company_currency:
                        prod_price = company_currency._convert(prod_price, target_currency, company, fields.Date.today())

                    product_data.append({
                        "id": prod.id,
                        "name": prod.name,
                        "price": round(prod_price, 2),
                        "description": description,
                        "image_url": f"/web/image/product.template/{prod.id}/image_1920",
                        "branch_id": prod.branch_id.id if prod.branch_id else branch_id,
                        "branch_name": prod.branch_id.name if prod.branch_id else resolved_branch_name,
                        "total_stock": total_stock,
                        "available_locations": available_locations,
                        "location_stocks": location_stocks,
                        "purity": purity_name,
                        "purity_percentage": purity_percentage
                    })

            # ── Include location filter info in response ──
            response_data = {
                "status": "success",
                "branch": resolved_branch_name,
                "branch_id": branch_id,
                "count": len(product_data),
                "data": product_data,
                "currency": target_currency.name,
                "currency_symbol": target_currency.symbol or target_currency.name
            }
            
            if location_id:
                location = request.env['stock.location'].sudo().browse(int(location_id))
                if location:
                    response_data["location_filter"] = {
                        "location_id": location.id,
                        "location_name": location.name,
                        "location_complete_name": location.complete_name
                    }
            elif location_name:
                response_data["location_filter"] = {
                    "location_name": location_name
                }
            
            return response_data

        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # SEARCH PRODUCTS API (JSON)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/products/search', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def search_products(self, **kwargs):
        try:
            query = (kwargs.get('query') or kwargs.get('search_query') or '').strip()
            if not query:
                return {"status": "error", "message": "query or search_query parameter is required"}

            branch_id   = kwargs.get('branch_id')
            branch_name = (kwargs.get('branch_name') or '').strip()
            currency_code = kwargs.get('currency')
            customer_id = kwargs.get('customer_id')

            # ── Resolve Branch ──
            branch = self._resolve_branch(kwargs)

            # Resolve currency
            Currency = request.env['res.currency'].sudo()
            target_currency = None
            if currency_code:
                target_currency = Currency.search([('name', '=', currency_code.upper())], limit=1)
            if not target_currency and customer_id:
                customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
                if customer.exists() and customer.currency_id:
                    target_currency = customer.currency_id

            company = branch.company_id if branch and branch.company_id else request.env.company
            company_currency = company.currency_id
            if not target_currency:
                target_currency = company_currency

            # Build domain: must be saleable, match search query (name/code)
            domain = [
                ('sale_ok', '=', True),
                '|', ('name', 'ilike', query), ('default_code', 'ilike', query)
            ]
            if branch:
                domain.append('|')
                domain.append(('branch_id', '=', branch.id))
                domain.append(('branch_id', '=', False))

            products = request.env['product.template'].sudo().search(domain)

            # Resolve stock locations
            location_domain = []
            if branch:
                location_domain.append(('branch_id', '=', branch.id))
            locations = request.env['stock.location'].sudo().search(location_domain)

            # ── Pre-fetch quants and labels in batch ──
            all_quants = request.env['stock.quant'].sudo().search([
                ('product_id.product_tmpl_id', 'in', products.ids),
                ('location_id', 'in', locations.ids),
                ('quantity', '>', 0)
            ])
            quant_map = {}
            for q in all_quants:
                key = (q.product_id.product_tmpl_id.id, q.location_id.id)
                quant_map.setdefault(key, []).append(q)

            all_labels = request.env['product.label'].sudo().search([
                ('product_tmpl_id', 'in', products.ids),
                ('branch_location_id', 'in', locations.ids),
                ('active', '=', True)
            ])
            label_map = {}
            for l in all_labels:
                key = (l.product_tmpl_id.id, l.branch_location_id.id)
                label_map.setdefault(key, []).append(l)

            product_data = []
            for prod in products:
                description = prod.description_sale or prod.description or ""
                purity_name = prod.purity_id.name if prod.purity_id else None
                purity_percentage = prod.purity_id.percentage if prod.purity_id else None
                
                location_stocks = []
                total_stock = 0
                available_locations = []
                
                for loc in locations:
                    prod_loc_quants = quant_map.get((prod.id, loc.id), [])
                    total_qty = sum(q.quantity for q in prod_loc_quants)
                    
                    if total_qty > 0:
                        total_stock += total_qty
                        available_locations.append(loc.name)
                        
                        prod_loc_labels = label_map.get((prod.id, loc.id), [])
                        
                        label_data = []
                        for label in prod_loc_labels:
                            label_data.append({
                                "label_number": label.label_number,
                                "label_name": label.name,
                                "tag_weight": label.tag_weight,
                                "grams": label.sale_gross_weight,
                                "purity": label.purity_id.name if label.purity_id else purity_name,
                                "purity_percentage": label.purity_id.percentage if label.purity_id else purity_percentage
                            })
                        
                        loc_price = prod.list_price or 0.0
                        if target_currency != company_currency:
                            loc_price = company_currency._convert(loc_price, target_currency, company, fields.Date.today())

                        location_stocks.append({
                            "location_id": loc.id,
                            "location_name": loc.name,
                            "location_complete_name": loc.complete_name,
                            "product_name": prod.name,
                            "price": round(loc_price, 2),
                            "description": description,
                            "image_url": f"/web/image/product.template/{prod.id}/image_1920",
                            "quantity": total_qty,
                            "purity": purity_name,
                            "purity_percentage": purity_percentage,
                            "labels": label_data
                        })
                
                if (branch and total_stock > 0) or not branch:
                    prod_price = prod.list_price or 0.0
                    if target_currency != company_currency:
                        prod_price = company_currency._convert(prod_price, target_currency, company, fields.Date.today())

                    product_data.append({
                        "id": prod.id,
                        "name": prod.name,
                        "price": round(prod_price, 2),
                        "description": description,
                        "image_url": f"/web/image/product.template/{prod.id}/image_1920",
                        "branch_id": prod.branch_id.id if prod.branch_id else (branch.id if branch else None),
                        "branch_name": prod.branch_id.name if prod.branch_id else (branch.name if branch else "All Branches"),
                        "total_stock": total_stock,
                        "available_locations": available_locations,
                        "location_stocks": location_stocks,
                        "purity": purity_name,
                        "purity_percentage": purity_percentage
                    })

            return {
                "status": "success",
                "query": query,
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None,
                "count": len(product_data),
                "data": product_data,
                "currency": target_currency.name,
                "currency_symbol": target_currency.symbol or target_currency.name
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # ECOMMERCE BRANCHES LIST
    # ─────────────────────────────────────────────
    def _get_branches_data(self):
        Branch = request.env['res.branch'].sudo()
        branches = Branch.search([])
        branch_data = []
        for b in branches:
            branch_data.append({
                "id": b.id,
                "name": b.name,
                "code": b.code if hasattr(b, 'code') and b.code else "",
                "city": b.city if hasattr(b, 'city') and b.city else "",
            })
        
        if not branch_data:
            branch_data = [
                {"id": 1, "name": "Calicut Main Branch", "code": "CLT", "city": "Calicut"},
                {"id": 2, "name": "Cochin Branch", "code": "COK", "city": "Cochin"},
                {"id": 3, "name": "Trivandrum Branch", "code": "TRV", "city": "Trivandrum"},
            ]

        return {
            "status": "success",
            "data": branch_data
        }

    @http.route('/api/ecommerce/branches', type='json', auth='public', methods=['POST', 'GET', 'OPTIONS'], cors='*', csrf=False)
    def get_branches(self, **kwargs):
        try:
            return self._get_branches_data()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route('/api/ecommerce/branches', type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], cors='*', csrf=False)
    def get_branches_http(self, **kwargs):
        try:
            data = self._get_branches_data()
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)


    # ─────────────────────────────────────────────
    # CUSTOMER REGISTER
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/register', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)

    def register(self, **kwargs):
        try:
            first_name      = (kwargs.get('first_name') or '').strip()
            last_name       = (kwargs.get('last_name') or '').strip()
            phone           = (kwargs.get('phone') or '').strip()
            city            = (kwargs.get('city') or '').strip()
            email           = (kwargs.get('email') or '').strip().lower()
            password        = kwargs.get('password') or ''
            confirm_password = kwargs.get('confirm_password') or ''
            branch_id       = kwargs.get('branch_id')
            branch_name     = kwargs.get('branch_name')


            # ── Validation ─────────────────────────────────
            required = {
                'first_name': first_name,
                'last_name': last_name,
                'phone': phone,
                'city': city,
                'email': email,
                'password': password,
                'confirm_password': confirm_password,
            }
            missing = [k for k, v in required.items() if not v]
            if missing:
                return {"status": "error", "message": f"Missing fields: {', '.join(missing)}"}

            if password != confirm_password:
                return {"status": "error", "message": "Passwords do not match"}

            if len(password) < 6:
                return {"status": "error", "message": "Password must be at least 6 characters"}

            # Resolve branch if provided
            resolved_branch = None
            if branch_id:
                resolved_branch = request.env['res.branch'].sudo().browse(int(branch_id))
            elif branch_name:
                resolved_branch = request.env['res.branch'].sudo().search([('name', 'ilike', branch_name)], limit=1)

            Customer = request.env['ecommerce.customer'].sudo()

            # ── Check duplicate email ──────────────────────
            if Customer.search([('email', '=', email)], limit=1):
                return {"status": "error", "message": "An account with this email already exists"}

            # ── Hash password ──────────────────────────────
            dummy = Customer.new({})
            password_hash, salt = dummy._hash_password(password)

            # ── Create customer record ─────────────────────
            customer_vals = {
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'phone': phone,
                'city': city,
                'password_hash': password_hash,
                'password_salt': salt,
            }
            if resolved_branch and resolved_branch.exists():
                customer_vals['branch_id'] = resolved_branch.id

            customer = Customer.create(customer_vals)

            token = customer._generate_token()

            # Store in request session for continuous API calls
            if request.session:
                request.session['customer_id'] = customer.id
                if customer.branch_id:
                    request.session['branch_id'] = customer.branch_id.id

            return {
                "status": "success",
                "message": "Registration successful",
                "branch": customer.branch_id.name if customer.branch_id else "All Branches",
                "branch_id": customer.branch_id.id if customer.branch_id else None,
                "data": {
                    "customer_id": customer.id,
                    "name": customer.name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                    "branch_id": customer.branch_id.id if customer.branch_id else None,
                    "branch_name": customer.branch_id.name if customer.branch_id else None,
                    "auth_token": token,
                    "token_expiry": customer.token_expiry.strftime('%Y-%m-%d %H:%M:%S') if customer.token_expiry else None,
                }
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # CUSTOMER LOGIN
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/login', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def login(self, **kwargs):
        try:
            email    = (kwargs.get('email') or '').strip().lower()
            password = kwargs.get('password') or ''
            branch_id = kwargs.get('branch_id')
            branch_name = kwargs.get('branch_name')

            if not email or not password:
                return {"status": "error", "message": "Email and password are required"}

            Customer = request.env['ecommerce.customer'].sudo()
            customer = Customer.search([('email', '=', email)], limit=1)

            if not customer:
                return {"status": "error", "message": "Invalid email or password"}

            if not customer._verify_password(password):
                return {"status": "error", "message": "Invalid email or password"}

            # Only set preferred branch if customer doesn't already have a saved branch
            if not customer.branch_id:
                if branch_id:
                    branch = request.env['res.branch'].sudo().browse(int(branch_id))
                    if branch.exists():
                        customer.write({'branch_id': branch.id})
                elif branch_name:
                    branch = request.env['res.branch'].sudo().search([('name', 'ilike', branch_name)], limit=1)
                    if branch.exists():
                        customer.write({'branch_id': branch.id})

            # Generate authentication token
            token = customer._generate_token()

            resolved_branch = customer.branch_id
            if not resolved_branch or not resolved_branch.exists():
                resolved_branch = self._resolve_branch(kwargs, customer=customer)

            # Store in request session for continuous API calls
            if request.session:
                request.session['customer_id'] = customer.id
                if resolved_branch:
                    request.session['branch_id'] = resolved_branch.id

            return {
                "status": "success",
                "message": "Login successful",
                "branch": resolved_branch.name if resolved_branch else "All Branches",
                "branch_id": resolved_branch.id if resolved_branch else None,
                "data": {
                    "customer_id": customer.id,
                    "name": customer.name,
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                    "branch_id": resolved_branch.id if resolved_branch else None,
                    "branch_name": resolved_branch.name if resolved_branch else None,
                    "auth_token": token,
                    "token_expiry": customer.token_expiry.strftime('%Y-%m-%d %H:%M:%S') if customer.token_expiry else None,
                }
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # BIOMETRIC LOGIN
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/biometric_login', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def biometric_login(self, **kwargs):
        try:
            token = None
            auth_header = request.httprequest.headers.get('Authorization', '')
            if auth_header.startswith('Token '):
                token = auth_header[6:].strip()
            
            if not token:
                token = kwargs.get('auth_token')

            if not token:
                return {"status": "error", "message": "auth_token is required in body or Authorization: Token <token> header"}

            Customer = request.env['ecommerce.customer'].sudo()
            customer = Customer.search([('auth_token', '=', token)], limit=1)

            if not customer:
                return {"status": "error", "message": "Invalid authentication token"}

            if not customer._verify_token(token):
                return {"status": "error", "message": "Authentication token expired or invalid"}

            resolved_branch = customer.branch_id
            if not resolved_branch or not resolved_branch.exists():
                resolved_branch = self._resolve_branch(kwargs, customer=customer)

            return {
                "status": "success",
                "message": "Biometric login successful",
                "branch": resolved_branch.name if resolved_branch else "All Branches",
                "branch_id": resolved_branch.id if resolved_branch else None,
                "data": {
                    "customer_id": customer.id,
                    "name": customer.name,
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                    "branch_id": resolved_branch.id if resolved_branch else None,
                    "branch_name": resolved_branch.name if resolved_branch else None,
                    "auth_token": token,
                    "token_expiry": customer.token_expiry.strftime('%Y-%m-%d %H:%M:%S') if customer.token_expiry else None,
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _send_otp_sms(self, phone, otp):
        _logger.info("\n=== ECOMMERCE OTP LOG ===")
        _logger.info("PHONE: %s | OTP: %s", phone, otp)
        _logger.info("==========================\n")
        if not phone:
            return False
        try:
            api_url = request.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_api_url', 'https://api.xpresssms.in/api/v2/SendBulkSMS')
            api_key = request.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_api_key', 'nUvKhbmpknZTeVr8WzjBKx180Qd6p/pQ6smsMv0e6Y8=')
            client_id = request.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_client_id', 'fd4e0c95-91f6-40d1-80d0-eab5d913a4e3')
            sender_id = request.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_sender_id', 'NAKGND')
            msg_template = request.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_message_template', '{otp} is your OTP to login to the NAKSHATHRA GOLD AND DIAMOND LLP application. OTP is valid for 5 minutes. Please do not share the OTP.')
            peid = (request.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_peid') or '1601764169804801352').strip()
            otp_template_id = (request.env['ir.config_parameter'].sudo().get_param('em_otp_login.xpresssms_otp_template_id') or '1607100000000289598').strip()

            digits = ''.join(c for c in phone if c.isdigit())
            if len(digits) == 11 and digits.startswith('0'):
                digits = digits[1:]
            if len(digits) == 10:
                digits = '91' + digits

            if api_key and client_id and digits:
                body = msg_template.format(otp=otp) if msg_template else f"Your verification code is {otp}."
                payload = {
                    'SenderId': sender_id or 'NAKGND',
                    'templateId': otp_template_id or '1607100000000289598',
                    'principleEntityId': peid or '1601764169804801352',
                    'MessageParameters': [
                        {
                            'Number': digits,
                            'Text': body
                        }
                    ],
                    'ApiKey': api_key,
                    'ClientId': client_id
                }
                import requests
                requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
        except Exception as e:
            _logger.warning("Could not send OTP SMS: %s", e)

    # ─────────────────────────────────────────────
    # OTP SEND / REQUEST API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/otp/send', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def otp_send(self, **kwargs):
        """
        Send / Request OTP for phone or email.
        """
        try:
            phone = (kwargs.get('phone') or '').strip()
            email = (kwargs.get('email') or '').strip()

            if not phone and not email:
                return {"status": "error", "message": "phone or email is required"}

            Customer = request.env['ecommerce.customer'].sudo()
            domain = []
            if phone:
                domain.append(('phone', '=', phone))
            elif email:
                domain.append(('email', '=', email))

            customer = Customer.search(domain, limit=1)
            branch = self._resolve_branch(kwargs, customer=customer)

            otp_code = f"{random.randint(100000, 999999)}"
            expiry = fields.Datetime.now() + datetime.timedelta(minutes=5)

            if customer:
                customer.write({
                    'login_otp': otp_code,
                    'login_otp_expiry': expiry
                })
                if branch and not customer.branch_id:
                    customer.write({'branch_id': branch.id})
            else:
                customer_vals = {
                    'first_name': kwargs.get('first_name', 'Customer'),
                    'last_name': kwargs.get('last_name', phone or 'User'),
                    'email': email or f"user_{phone}@example.com",
                    'phone': phone,
                    'login_otp': otp_code,
                    'login_otp_expiry': expiry,
                    'branch_id': branch.id if branch else None,
                }
                customer = Customer.create(customer_vals)

            # Send SMS
            self._send_otp_sms(customer.phone or phone, otp_code)

            return {
                "status": "success",
                "message": "OTP sent successfully",
                "otp": otp_code,
                "phone": customer.phone or phone,
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # OTP VERIFY API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/otp/verify', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def otp_verify(self, **kwargs):
        """
        Verify OTP and authenticate user.
        """
        try:
            phone = (kwargs.get('phone') or '').strip()
            email = (kwargs.get('email') or '').strip()
            otp_entered = (str(kwargs.get('otp') or kwargs.get('otp_code') or '')).strip()

            if not phone and not email:
                return {"status": "error", "message": "phone or email is required"}
            if not otp_entered:
                return {"status": "error", "message": "otp is required"}

            Customer = request.env['ecommerce.customer'].sudo()
            domain = []
            if phone:
                domain.append(('phone', '=', phone))
            elif email:
                domain.append(('email', '=', email))

            customer = Customer.search(domain, limit=1)
            if not customer:
                return {"status": "error", "message": "Customer not found"}

            if not customer.login_otp or str(customer.login_otp).strip() != otp_entered:
                return {"status": "error", "message": "Invalid OTP code"}

            if customer.login_otp_expiry and customer.login_otp_expiry < fields.Datetime.now():
                return {"status": "error", "message": "OTP has expired. Please request a new OTP."}

            branch = self._resolve_branch(kwargs, customer=customer)

            # OTP is valid -> generate token & clear OTP
            token = customer._generate_token()
            customer.write({
                'login_otp': False,
                'login_otp_expiry': False
            })

            return {
                "status": "success",
                "message": "OTP verified successfully. Login successful.",
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None,
                "data": {
                    "customer_id": customer.id,
                    "name": customer.name,
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                    "branch_id": branch.id if branch else None,
                    "branch_name": branch.name if branch else None,
                    "auth_token": token,
                    "token_expiry": customer.token_expiry.strftime('%Y-%m-%d %H:%M:%S') if customer.token_expiry else None,
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # OTP RESEND API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/otp/resend', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def otp_resend(self, **kwargs):
        """
        Resend OTP.
        """
        return self.otp_send(**kwargs)

    # ─────────────────────────────────────────────
    # GET LANGUAGES
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/languages', type='json', auth='public', methods=['POST', 'OPTIONS', 'GET'], cors='*', csrf=False)
    def get_languages(self, **kwargs):
        try:
            languages = request.env['res.lang'].sudo().search([('active', '=', True)])
            lang_data = []
            for lang in languages:
                lang_data.append({
                    "id": lang.id,
                    "name": lang.name,
                    "code": lang.code,
                    "iso_code": lang.iso_code,
                    "direction": lang.direction,
                })
            
            return {
                "status": "success",
                "count": len(lang_data),
                "data": lang_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # SET/FETCH LANGUAGE SPECIFIC API
    # ─────────────────────────────────────────────
    @http.route([
        '/api/ecommerce/language/english',
        '/api/ecommerce/language/hindi',
        '/api/ecommerce/language/tamil',
        '/api/ecommerce/language/malayalam',
        '/api/ecommerce/language/telugu',
        '/api/ecommerce/language/kannada'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def handle_specific_language(self, **kwargs):
        try:
            path = request.httprequest.path
            lang_name = path.split('/')[-1]

            # Map common names to Odoo language codes
            lang_map = {
                'english': 'en_US',
                'hindi': 'hi_IN',
                'tamil': 'ta_IN',
                'malayalam': 'ml_IN',
                'telugu': 'te_IN',
                'kannada': 'kn_IN'
            }
            
            clean_name = lang_name.lower().strip()
            if clean_name not in lang_map:
                return {"status": "error", "message": f"Language '{lang_name}' is not currently supported."}

            odoo_lang_code = lang_map[clean_name]
            customer_id = kwargs.get('customer_id')

            # If a customer_id is provided, update their language preference in Odoo
            if customer_id:
                customer = request.env['ecommerce.customer'].sudo().browse(customer_id)
                if customer.exists():
                    # Assuming there's a field or partner linked. 
                    # If using standard res.partner, it would be customer.partner_id.lang = odoo_lang_code
                    pass

            return {
                "status": "success",
                "message": f"{lang_name.capitalize()} language API activated successfully.",
                "language_code": odoo_lang_code,
                "data": {
                    "info": f"This is the dedicated endpoint for {lang_name.capitalize()}."
                }
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # GET CURRENCIES (JSON)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/currencies', type='json', auth='public', methods=['POST', 'OPTIONS', 'GET'], cors='*', csrf=False)
    def get_currencies_json(self, **kwargs):
        try:
            return self._get_currencies_data()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # GET CURRENCIES (HTTP GET)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/currencies', type='http', auth='public', methods=['GET', 'OPTIONS'], cors='*', csrf=False)
    def get_currencies_http(self, **kwargs):
        try:
            data = self._get_currencies_data()
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # GET CURRENCIES (HTTP POST)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/currencies', type='http', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_currencies_http_post(self, **kwargs):
        try:
            data = self._get_currencies_data()
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    def _get_currencies_data(self):
        currency_codes = ['INR', 'USD', 'AED', 'SGD']
        Currency = request.env['res.currency'].sudo()
        currencies = Currency.with_context(active_test=False).search([('name', 'in', currency_codes)])
        
        # Ensure AED and SGD are active in Odoo if found
        for curr in currencies:
            if not curr.active:
                curr.write({'active': True})
                
        currency_defaults = {
            'INR': {'symbol': '₹', 'full_name': 'Indian Rupee'},
            'USD': {'symbol': '$', 'full_name': 'US Dollar'},
            'AED': {'symbol': 'د.إ', 'full_name': 'UAE Dirham'},
            'SGD': {'symbol': 'S$', 'full_name': 'Singapore Dollar'}
        }
        
        currency_data = []
        for code in currency_codes:
            curr_rec = currencies.filtered(lambda c: c.name == code)
            if curr_rec:
                currency_data.append({
                    "id": curr_rec.id,
                    "name": curr_rec.currency_unit_label or currency_defaults[code]['full_name'],
                    "code": curr_rec.name,
                    "symbol": curr_rec.symbol or currency_defaults[code]['symbol'],
                    "rate": curr_rec.rate or 1.0,
                })
            else:
                currency_data.append({
                    "id": 0,
                    "name": currency_defaults[code]['full_name'],
                    "code": code,
                    "symbol": currency_defaults[code]['symbol'],
                    "rate": 1.0,
                })
        return {
            "status": "success",
            "count": len(currency_data),
            "data": currency_data
        }

    # ─────────────────────────────────────────────
    # SET CURRENCY (JSON)
    # ─────────────────────────────────────────────
    @http.route([
        '/api/ecommerce/currency/inr',
        '/api/ecommerce/currency/usd',
        '/api/ecommerce/currency/aed',
        '/api/ecommerce/currency/sgd'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def handle_specific_currency_json(self, **kwargs):
        try:
            # We support reading parameters from jsonrpc post
            return self._set_specific_currency(kwargs)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # SET CURRENCY (HTTP GET)
    # ─────────────────────────────────────────────
    @http.route([
        '/api/ecommerce/currency/inr',
        '/api/ecommerce/currency/usd',
        '/api/ecommerce/currency/aed',
        '/api/ecommerce/currency/sgd'
    ], type='http', auth='public', methods=['GET', 'OPTIONS'], cors='*', csrf=False)
    def handle_specific_currency_http(self, **kwargs):
        try:
            # In HTTP GET, params are in request.params
            data = self._set_specific_currency(request.params)
            if data.get("status") == "error":
                return self._json_response(data, 400)
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    def _set_specific_currency(self, kwargs):
        path = request.httprequest.path
        currency_code = path.split('/')[-1].upper() # 'INR', 'USD', 'AED', 'SGD'
        
        customer_id = kwargs.get('customer_id')
        
        Currency = request.env['res.currency'].sudo()
        currency = Currency.with_context(active_test=False).search([('name', '=', currency_code)], limit=1)
        if currency:
            if not currency.active:
                currency.write({'active': True})
        else:
            return {"status": "error", "message": f"Currency '{currency_code}' not found."}
            
        if customer_id:
            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if customer.exists():
                customer.write({'currency_id': currency.id})
                
        return {
            "status": "success",
            "message": f"{currency_code} currency preference set successfully.",
            "currency_code": currency_code,
            "symbol": currency.symbol or '$',
            "rate": currency.rate or 1.0,
            "data": {
                "info": f"This is the dedicated endpoint for {currency_code}."
            }
        }

    # ─────────────────────────────────────────────
    # HELP CENTER API (FAQs)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/help_center', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_help_center(self, **kwargs):
        try:
            faqs = request.env['ecommerce.faq'].sudo().search([])
            faq_data = []
            for faq in faqs:
                faq_data.append({
                    "id": faq.id,
                    "question": faq.question,
                    "answer": faq.answer,
                })
            
            # Predefined high-quality defaults if database is empty
            if not faq_data:
                faq_data = [
                    {
                        "id": 1,
                        "question": "What is Nakshathra Gold & Diamonds?",
                        "answer": "Nakshathra is a premier jewellery store offering pure gold, diamond, platinum, and silver ornaments with certified quality."
                    },
                    {
                        "id": 2,
                        "question": "How do I trace my order?",
                        "answer": "You can view your order status in the Order History section of the mobile application."
                    },
                    {
                        "id": 3,
                        "question": "What is the return policy?",
                        "answer": "We offer a 7-day return/exchange policy for standard ornaments in their original, unused condition."
                    }
                ]
            
            return {
                "status": "success",
                "faqs": faq_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # CHAT WITH US API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/chat_info', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_chat_info(self, **kwargs):
        try:
            ICPSudo = request.env['ir.config_parameter'].sudo()
            whatsapp_number = ICPSudo.get_param('ecommerce.chat.whatsapp_number', '+916282116343')
            start_time = ICPSudo.get_param('ecommerce.chat.start_time', '9AM')
            end_time = ICPSudo.get_param('ecommerce.chat.end_time', '9PM')
            
            return {
                "status": "success",
                "whatsapp_number": whatsapp_number,
                "availability": f"Available {start_time} - {end_time}",
                "chat_link": f"https://wa.me/{whatsapp_number.replace('+', '').replace(' ', '')}"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # RATE THE APP API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/app_rating_info', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_app_rating_info(self, **kwargs):
        try:
            ICPSudo = request.env['ir.config_parameter'].sudo()
            play_store_url = ICPSudo.get_param('ecommerce.rating.play_store_url', 'https://play.google.com/store/apps/details?id=com.nakshathra.app')
            app_store_url = ICPSudo.get_param('ecommerce.rating.app_store_url', 'https://apps.apple.com/app/id123456789')
            
            return {
                "status": "success",
                "play_store_url": play_store_url,
                "app_store_url": app_store_url,
                "message": "Enjoying Nakshathra? Leave a review!"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # ABOUT API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/about', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_about_info(self, **kwargs):
        try:
            company = request.env.company
            ICPSudo = request.env['ir.config_parameter'].sudo()
            app_version = ICPSudo.get_param('ecommerce.about.app_version', '2.1.0')
            tc_url = ICPSudo.get_param('ecommerce.about.terms_and_conditions', 'https://nakshathra.com/terms')
            privacy_url = ICPSudo.get_param('ecommerce.about.privacy_policy', 'https://nakshathra.com/privacy')
            
            return {
                "status": "success",
                "company_name": company.name or "Nakshathra Gold & Diamonds",
                "email": company.email or "support@nakshathra.com",
                "phone": company.phone or "+916282116343",
                "website": company.website or "https://nakshathra.com",
                "app_version": app_version,
                "terms_and_conditions_url": tc_url,
                "privacy_policy_url": privacy_url
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # PRIVACY POLICY API (HTTP GET & POST)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/privacy_policy', type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], cors='*', csrf=False)
    def get_privacy_policy_http(self, **kwargs):
        try:
            ICPSudo = request.env['ir.config_parameter'].sudo()
            privacy_url = ICPSudo.get_param('ecommerce.about.privacy_policy', 'https://nakshathra.com/privacy')
            
            data = {
                "status": "success",
                "privacy_policy_url": privacy_url,
                "content": "This is the Privacy Policy of Nakshathra Gold & Diamonds. We are committed to protecting your personal data. Please visit our website for the full policy details."
            }
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # PRIVACY POLICY API (JSON-RPC)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/privacy_policy/json', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_privacy_policy_json(self, **kwargs):
        try:
            ICPSudo = request.env['ir.config_parameter'].sudo()
            privacy_url = ICPSudo.get_param('ecommerce.about.privacy_policy', 'https://nakshathra.com/privacy')
            
            return {
                "status": "success",
                "privacy_policy_url": privacy_url,
                "content": "This is the Privacy Policy of Nakshathra Gold & Diamonds. We are committed to protecting your personal data. Please visit our website for the full policy details."
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # GET CUSTOMER ADDRESSES API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/addresses', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_addresses(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(customer_id)
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            addresses = request.env['ecommerce.address'].sudo().search([('customer_id', '=', customer.id)])
            address_data = []
            for addr in addresses:
                address_data.append({
                    "id": addr.id,
                    "type": addr.name,
                    "recipient_name": addr.recipient_name,
                    "phone": addr.phone,
                    "address_details": addr.address_details
                })

            return {
                "status": "success",
                "count": len(address_data),
                "addresses": address_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # ADD ADDRESS API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/address/add', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def add_address(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            addr_type = kwargs.get('type', 'home')
            recipient_name = kwargs.get('recipient_name')
            phone = kwargs.get('phone')
            address_details = kwargs.get('address_details')

            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}
            if not recipient_name:
                return {"status": "error", "message": "recipient_name is required"}
            if not phone:
                return {"status": "error", "message": "phone is required"}
            if not address_details:
                return {"status": "error", "message": "address_details is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(customer_id)
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            if addr_type not in ['home', 'work', 'other']:
                return {"status": "error", "message": "Invalid address type. Must be 'home', 'work', or 'other'."}

            addr = request.env['ecommerce.address'].sudo().create({
                'name': addr_type,
                'recipient_name': recipient_name,
                'phone': phone,
                'address_details': address_details,
                'customer_id': customer.id
            })

            return {
                "status": "success",
                "message": "Address added successfully",
                "address_id": addr.id
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # UPDATE ADDRESS API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/address/update', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def update_address(self, **kwargs):
        try:
            address_id = kwargs.get('address_id')
            customer_id = kwargs.get('customer_id')

            if not address_id:
                return {"status": "error", "message": "address_id is required"}
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            addr = request.env['ecommerce.address'].sudo().browse(address_id)
            if not addr.exists() or addr.customer_id.id != int(customer_id):
                return {"status": "error", "message": "Address not found or unauthorized"}

            vals = {}
            if 'type' in kwargs:
                if kwargs['type'] not in ['home', 'work', 'other']:
                    return {"status": "error", "message": "Invalid address type. Must be 'home', 'work', or 'other'."}
                vals['name'] = kwargs['type']
            if 'recipient_name' in kwargs:
                vals['recipient_name'] = kwargs['recipient_name']
            if 'phone' in kwargs:
                vals['phone'] = kwargs['phone']
            if 'address_details' in kwargs:
                vals['address_details'] = kwargs['address_details']

            if vals:
                addr.write(vals)

            return {
                "status": "success",
                "message": "Address updated successfully"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # DELETE ADDRESS API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/address/delete', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def delete_address(self, **kwargs):
        try:
            address_id = kwargs.get('address_id')
            customer_id = kwargs.get('customer_id')

            if not address_id:
                return {"status": "error", "message": "address_id is required"}
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            addr = request.env['ecommerce.address'].sudo().browse(address_id)
            if not addr.exists() or addr.customer_id.id != int(customer_id):
                return {"status": "error", "message": "Address not found or unauthorized"}

            addr.unlink()

            return {
                "status": "success",
                "message": "Address deleted successfully"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # GET HTTP HELPER
    # ─────────────────────────────────────────────
    def _json_response(self, data, status=200):
        """Return a proper JSON HTTP response (used for GET-type routes)."""
        return Response(
            json.dumps(data),
            status=status,
            mimetype='application/json',
        )

    # ─────────────────────────────────────────────
    # GET CUSTOMER ADDRESSES API (GET)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/addresses', type='http', auth='public', methods=['GET', 'OPTIONS'], cors='*', csrf=False)
    def get_addresses_get(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return self._json_response({"status": "error", "message": "customer_id is required"}, 400)

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return self._json_response({"status": "error", "message": "Customer not found"}, 404)

            addresses = request.env['ecommerce.address'].sudo().search([('customer_id', '=', customer.id)])
            address_data = []
            for addr in addresses:
                address_data.append({
                    "id": addr.id,
                    "type": addr.name,
                    "recipient_name": addr.recipient_name,
                    "phone": addr.phone,
                    "address_details": addr.address_details
                })

            return self._json_response({
                "status": "success",
                "count": len(address_data),
                "addresses": address_data
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # ADD ADDRESS API (GET)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/address/add', type='http', auth='public', methods=['GET', 'OPTIONS'], cors='*', csrf=False)
    def add_address_get(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            addr_type = kwargs.get('type', 'home')
            recipient_name = kwargs.get('recipient_name')
            phone = kwargs.get('phone')
            address_details = kwargs.get('address_details')

            if not customer_id:
                return self._json_response({"status": "error", "message": "customer_id is required"}, 400)
            if not recipient_name:
                return self._json_response({"status": "error", "message": "recipient_name is required"}, 400)
            if not phone:
                return self._json_response({"status": "error", "message": "phone is required"}, 400)
            if not address_details:
                return self._json_response({"status": "error", "message": "address_details is required"}, 400)

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return self._json_response({"status": "error", "message": "Customer not found"}, 404)

            if addr_type not in ['home', 'work', 'other']:
                return self._json_response({"status": "error", "message": "Invalid address type. Must be 'home', 'work', or 'other'."}, 400)

            addr = request.env['ecommerce.address'].sudo().create({
                'name': addr_type,
                'recipient_name': recipient_name,
                'phone': phone,
                'address_details': address_details,
                'customer_id': customer.id
            })

            return self._json_response({
                "status": "success",
                "message": "Address added successfully",
                "address_id": addr.id
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # UPDATE ADDRESS API (GET / PUT / PATCH)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/address/update', type='http', auth='public', methods=['GET', 'PUT', 'PATCH', 'OPTIONS'], cors='*', csrf=False)
    def update_address_get(self, **kwargs):
        try:
            if request.httprequest.method in ['PUT', 'PATCH']:
                try:
                    body_data = json.loads(request.httprequest.data)
                    kwargs.update(body_data)
                except Exception:
                    pass
            address_id = kwargs.get('address_id')
            customer_id = kwargs.get('customer_id')

            if not address_id:
                return self._json_response({"status": "error", "message": "address_id is required"}, 400)
            if not customer_id:
                return self._json_response({"status": "error", "message": "customer_id is required"}, 400)

            addr = request.env['ecommerce.address'].sudo().browse(int(address_id))
            if not addr.exists() or addr.customer_id.id != int(customer_id):
                return self._json_response({"status": "error", "message": "Address not found or unauthorized"}, 404)

            vals = {}
            if 'type' in kwargs:
                if kwargs['type'] not in ['home', 'work', 'other']:
                    return self._json_response({"status": "error", "message": "Invalid address type. Must be 'home', 'work', or 'other'."}, 400)
                vals['name'] = kwargs['type']
            if 'recipient_name' in kwargs:
                vals['recipient_name'] = kwargs['recipient_name']
            if 'phone' in kwargs:
                vals['phone'] = kwargs['phone']
            if 'address_details' in kwargs:
                vals['address_details'] = kwargs['address_details']

            if vals:
                addr.write(vals)

            return self._json_response({
                "status": "success",
                "message": "Address updated successfully"
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # DELETE ADDRESS API (GET / DELETE)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/address/delete', type='http', auth='public', methods=['GET', 'DELETE', 'OPTIONS'], cors='*', csrf=False)
    def delete_address_get(self, **kwargs):
        try:
            if request.httprequest.method == 'DELETE':
                try:
                    body_data = json.loads(request.httprequest.data)
                    kwargs.update(body_data)
                except Exception:
                    pass
            address_id = kwargs.get('address_id')
            customer_id = kwargs.get('customer_id')

            if not address_id:
                return self._json_response({"status": "error", "message": "address_id is required"}, 400)
            if not customer_id:
                return self._json_response({"status": "error", "message": "customer_id is required"}, 400)

            addr = request.env['ecommerce.address'].sudo().browse(int(address_id))
            if not addr.exists() or addr.customer_id.id != int(customer_id):
                return self._json_response({"status": "error", "message": "Address not found or unauthorized"}, 404)

            addr.unlink()

            return self._json_response({
                "status": "success",
                "message": "Address deleted successfully"
            })
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # GET CUSTOMER PROFILE API (JSON & HTTP)
    # ─────────────────────────────────────────────
    def _get_customer_profile_data(self, **kwargs):
        customer_id = kwargs.get('customer_id')
        if not customer_id:
            # Fallback to session or Authorization token if provided
            if request.session and request.session.get('customer_id'):
                customer_id = request.session.get('customer_id')
            elif request.httprequest and request.httprequest.headers.get('Authorization'):
                token = request.httprequest.headers.get('Authorization', '').replace('Bearer ', '').strip()
                cust = request.env['ecommerce.customer'].sudo().search([('auth_token', '=', token)], limit=1)
                if cust:
                    customer_id = cust.id

        if not customer_id:
            return {"status": "error", "message": "customer_id is required"}

        try:
            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
        except (ValueError, TypeError):
            return {"status": "error", "message": "Invalid customer_id format"}

        if not customer.exists():
            return {"status": "error", "message": "Customer not found"}

        orders_count = request.env['ecommerce.order'].sudo().search_count([('customer_id', '=', customer.id)])
        wishlist_count = request.env['ecommerce.wishlist'].sudo().search_count([('customer_id', '=', customer.id)])
        reviews_count = request.env['ecommerce.product.review'].sudo().search_count([('customer_id', '=', customer.id)])

        saved_addresses_count = len(customer.address_ids)
        saved_cards_count = len(customer.card_ids)
        saved_upi_count = len(customer.upi_ids)
        payment_methods_count = saved_cards_count + saved_upi_count

        membership = "Gold Member"
        if orders_count >= 10:
            membership = "Gold Member"
        elif orders_count >= 5:
            membership = "Silver Member"
        else:
            membership = "Gold Member" if customer.id == 1 else "Bronze Member"

        resolved_branch = customer.branch_id

        my_account = [
            {
                "key": "orders",
                "title": "My Orders",
                "subtitle": "Track, return or buy again",
                "count": orders_count,
                "icon": "orders"
            },
            {
                "key": "addresses",
                "title": "Saved Addresses",
                "subtitle": "Manage delivery addresses",
                "count": saved_addresses_count,
                "icon": "addresses"
            },
            {
                "key": "payment_methods",
                "title": "Payment Methods",
                "subtitle": "Cards, UPI, net banking",
                "count": payment_methods_count,
                "icon": "payment_methods"
            }
        ]

        return {
            "status": "success",
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "first_name": customer.first_name,
                "last_name": customer.last_name,
                "email": customer.email,
                "phone": customer.phone or "",
                "city": customer.city or "",
                "branch_id": resolved_branch.id if resolved_branch else None,
                "branch_name": resolved_branch.name if resolved_branch else None,
                "membership": membership,
                "member_tier": membership,
                "badge": membership,
                "orders_count": orders_count,
                "wishlist_count": wishlist_count,
                "reviews_count": reviews_count,
                "push_notifications": customer.push_notifications,
                "order_updates": customer.order_updates,
                "offer_alerts": customer.offer_alerts,
                "email_newsletter": customer.email_newsletter
            },
            "stats": {
                "orders": orders_count,
                "wishlist": wishlist_count,
                "reviews": reviews_count
            },
            "orders_count": orders_count,
            "wishlist_count": wishlist_count,
            "reviews_count": reviews_count,
            "orders": orders_count,
            "wishlist": wishlist_count,
            "reviews": reviews_count,
            "membership": membership,
            "member_tier": membership,
            "badge": membership,
            "my_account": my_account
        }

    @http.route([
        '/api/ecommerce/customer/profile',
        '/api/ecommerce/profile'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_customer_profile(self, **kwargs):
        try:
            return self._get_customer_profile_data(**kwargs)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route([
        '/api/ecommerce/customer/profile',
        '/api/ecommerce/profile'
    ], type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], cors='*', csrf=False)
    def get_customer_profile_http(self, **kwargs):
        try:
            params = dict(kwargs)
            if request.httprequest.is_json:
                try:
                    data = request.get_json_data() or {}
                    if isinstance(data, dict):
                        # Extract params if wrapped in JSON-RPC style or direct
                        if 'params' in data and isinstance(data['params'], dict):
                            params.update(data['params'])
                        else:
                            params.update(data)
                except Exception:
                    pass
            if 'customer_id' not in params and request.httprequest.args.get('customer_id'):
                params['customer_id'] = request.httprequest.args.get('customer_id')
            data = self._get_customer_profile_data(**params)
            status_code = 200 if data.get('status') == 'success' else 400
            return self._json_response(data, status=status_code)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # UPDATE CUSTOMER PROFILE API (JSON)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/customer/update', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def update_customer_profile(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            vals = {}
            if 'first_name' in kwargs:
                vals['first_name'] = kwargs['first_name']
            if 'last_name' in kwargs:
                vals['last_name'] = kwargs['last_name']
            
            # If name is provided and we aren't explicitly updating first_name/last_name, parse it
            if 'name' in kwargs and 'first_name' not in kwargs and 'last_name' not in kwargs:
                name_parts = (kwargs['name'] or '').strip().split(None, 1)
                if len(name_parts) == 1:
                    vals['first_name'] = name_parts[0]
                    vals['last_name'] = ''
                elif len(name_parts) > 1:
                    vals['first_name'] = name_parts[0]
                    vals['last_name'] = name_parts[1]

            if 'phone' in kwargs:
                vals['phone'] = kwargs['phone']
            if 'email' in kwargs:
                email = (kwargs['email'] or '').strip().lower()
                if email and email != customer.email:
                    if request.env['ecommerce.customer'].sudo().search([('email', '=', email)], limit=1):
                        return {"status": "error", "message": "An account with this email already exists"}
                    vals['email'] = email
            if 'city' in kwargs:
                vals['city'] = kwargs['city']

            # Update branch preference if provided
            if 'branch_id' in kwargs and kwargs['branch_id']:
                b = request.env['res.branch'].sudo().browse(int(kwargs['branch_id']))
                if b.exists():
                    vals['branch_id'] = b.id
            elif 'branch_name' in kwargs and kwargs['branch_name']:
                b = request.env['res.branch'].sudo().search([('name', 'ilike', kwargs['branch_name'])], limit=1)
                if b.exists():
                    vals['branch_id'] = b.id

            # Update notification preferences
            for pref in ['push_notifications', 'order_updates', 'offer_alerts', 'email_newsletter']:
                if pref in kwargs:
                    vals[pref] = bool(kwargs[pref])

            if vals:
                customer.write(vals)

            resolved_branch = customer.branch_id
            if request.session and resolved_branch:
                request.session['branch_id'] = resolved_branch.id

            return {
                "status": "success",
                "message": "Profile updated successfully",
                "branch": resolved_branch.name if resolved_branch else "All Branches",
                "branch_id": resolved_branch.id if resolved_branch else None,
                "customer": {
                    "id": customer.id,
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "name": customer.name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                    "branch_id": resolved_branch.id if resolved_branch else None,
                    "branch_name": resolved_branch.name if resolved_branch else None,
                    "push_notifications": customer.push_notifications,
                    "order_updates": customer.order_updates,
                    "offer_alerts": customer.offer_alerts,
                    "email_newsletter": customer.email_newsletter
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # NOTIFICATION PREFERENCES CONSTANTS & HELPERS
    # ─────────────────────────────────────────────
    NOTIFICATION_METADATA = {
        'push_notifications': {
            'title': 'Push Notifications',
            'subtitle': 'Alerts on new arrivals & deals',
        },
        'order_updates': {
            'title': 'Order Updates',
            'subtitle': 'Shipping & delivery status',
        },
        'offer_alerts': {
            'title': 'Offer Alerts',
            'subtitle': 'Festive discounts & flash sales',
        },
        'email_newsletter': {
            'title': 'Email Newsletter',
            'subtitle': 'Monthly trends & new collections',
        },
    }

    def _parse_notification_bool(self, val):
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            clean = val.strip().lower()
            if clean in ('true', '1', 'yes', 'on', 'enable', 'enabled'):
                return True
            if clean in ('false', '0', 'no', 'off', 'disable', 'disabled'):
                return False
        return bool(val)

    def _extract_request_params(self, kwargs):
        params = dict(kwargs)
        if hasattr(request, 'httprequest'):
            for k, v in request.httprequest.args.items():
                if k not in params:
                    params[k] = v
            if getattr(request.httprequest, 'is_json', False):
                try:
                    data = request.get_json_data() or {}
                    if isinstance(data, dict):
                        if 'params' in data and isinstance(data['params'], dict):
                            params.update(data['params'])
                        else:
                            params.update(data)
                except Exception:
                    pass
            elif getattr(request.httprequest, 'data', None):
                try:
                    data = json.loads(request.httprequest.data.decode('utf-8'))
                    if isinstance(data, dict):
                        if 'params' in data and isinstance(data['params'], dict):
                            params.update(data['params'])
                        else:
                            params.update(data)
                except Exception:
                    pass
        return params

    def _resolve_customer_for_notifications(self, **kwargs):
        customer_id = kwargs.get('customer_id')
        if not customer_id:
            if request.session and request.session.get('customer_id'):
                customer_id = request.session.get('customer_id')
            elif hasattr(request, 'httprequest') and request.httprequest.headers.get('Authorization'):
                token = request.httprequest.headers.get('Authorization', '').replace('Bearer ', '').replace('Token ', '').strip()
                cust = request.env['ecommerce.customer'].sudo().search([('auth_token', '=', token)], limit=1)
                if cust:
                    customer_id = cust.id
            elif kwargs.get('auth_token'):
                cust = request.env['ecommerce.customer'].sudo().search([('auth_token', '=', kwargs.get('auth_token'))], limit=1)
                if cust:
                    customer_id = cust.id

        if not customer_id:
            return None, {"status": "error", "message": "customer_id is required"}

        try:
            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
        except (ValueError, TypeError):
            return None, {"status": "error", "message": "Invalid customer_id format"}

        if not customer.exists():
            return None, {"status": "error", "message": "Customer not found"}

        return customer, None

    def _update_single_notification_pref(self, pref_key, **kwargs):
        try:
            customer, err = self._resolve_customer_for_notifications(**kwargs)
            if err:
                return err

            meta = self.NOTIFICATION_METADATA.get(pref_key, {
                'title': pref_key.replace('_', ' ').title(),
                'subtitle': ''
            })

            # Determine whether a new value is provided
            val_to_set = None
            has_val = False
            for k in [pref_key, 'enabled', 'value', 'status', 'state']:
                if k in kwargs and kwargs[k] is not None:
                    val_to_set = self._parse_notification_bool(kwargs[k])
                    has_val = True
                    break

            if not has_val and kwargs.get('action') == 'toggle':
                current = bool(getattr(customer, pref_key))
                val_to_set = not current
                has_val = True

            if has_val:
                customer.write({pref_key: val_to_set})
                action_word = "enabled" if val_to_set else "disabled"
                message = f"{meta['title']} {action_word} successfully"
            else:
                message = f"{meta['title']} preference retrieved successfully"

            current_val = bool(getattr(customer, pref_key))
            all_prefs = {
                "push_notifications": customer.push_notifications,
                "order_updates": customer.order_updates,
                "offer_alerts": customer.offer_alerts,
                "email_newsletter": customer.email_newsletter
            }

            return {
                "status": "success",
                "message": message,
                "customer_id": customer.id,
                "key": pref_key,
                "title": meta['title'],
                "subtitle": meta['subtitle'],
                "enabled": current_val,
                pref_key: current_val,
                "data": {
                    "customer_id": customer.id,
                    "key": pref_key,
                    "title": meta['title'],
                    "subtitle": meta['subtitle'],
                    "enabled": current_val,
                    pref_key: current_val,
                    "preferences": all_prefs
                },
                "preferences": all_prefs
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # 1. PUSH NOTIFICATIONS API
    # ─────────────────────────────────────────────
    @http.route([
        '/api/ecommerce/customer/push_notifications',
        '/api/ecommerce/customer/push-notifications',
        '/api/ecommerce/customer/notification/push_notifications',
        '/api/ecommerce/notifications/push_notifications',
        '/api/ecommerce/push_notifications'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def update_push_notifications_json(self, **kwargs):
        try:
            return self._update_single_notification_pref('push_notifications', **kwargs)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route([
        '/api/ecommerce/customer/push_notifications',
        '/api/ecommerce/customer/push-notifications',
        '/api/ecommerce/customer/notification/push_notifications',
        '/api/ecommerce/notifications/push_notifications',
        '/api/ecommerce/push_notifications'
    ], type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], cors='*', csrf=False)
    def update_push_notifications_http(self, **kwargs):
        try:
            params = self._extract_request_params(kwargs)
            res = self._update_single_notification_pref('push_notifications', **params)
            status_code = 200 if res.get('status') == 'success' else 400
            return self._json_response(res, status=status_code)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # 2. ORDER UPDATES API
    # ─────────────────────────────────────────────
    @http.route([
        '/api/ecommerce/customer/order_updates',
        '/api/ecommerce/customer/order-updates',
        '/api/ecommerce/customer/notification/order_updates',
        '/api/ecommerce/notifications/order_updates',
        '/api/ecommerce/order_updates'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def update_order_updates_json(self, **kwargs):
        try:
            return self._update_single_notification_pref('order_updates', **kwargs)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route([
        '/api/ecommerce/customer/order_updates',
        '/api/ecommerce/customer/order-updates',
        '/api/ecommerce/customer/notification/order_updates',
        '/api/ecommerce/notifications/order_updates',
        '/api/ecommerce/order_updates'
    ], type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], cors='*', csrf=False)
    def update_order_updates_http(self, **kwargs):
        try:
            params = self._extract_request_params(kwargs)
            res = self._update_single_notification_pref('order_updates', **params)
            status_code = 200 if res.get('status') == 'success' else 400
            return self._json_response(res, status=status_code)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # 3. OFFER ALERTS API
    # ─────────────────────────────────────────────
    @http.route([
        '/api/ecommerce/customer/offer_alerts',
        '/api/ecommerce/customer/offer-alerts',
        '/api/ecommerce/customer/notification/offer_alerts',
        '/api/ecommerce/notifications/offer_alerts',
        '/api/ecommerce/offer_alerts'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def update_offer_alerts_json(self, **kwargs):
        try:
            return self._update_single_notification_pref('offer_alerts', **kwargs)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route([
        '/api/ecommerce/customer/offer_alerts',
        '/api/ecommerce/customer/offer-alerts',
        '/api/ecommerce/customer/notification/offer_alerts',
        '/api/ecommerce/notifications/offer_alerts',
        '/api/ecommerce/offer_alerts'
    ], type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], cors='*', csrf=False)
    def update_offer_alerts_http(self, **kwargs):
        try:
            params = self._extract_request_params(kwargs)
            res = self._update_single_notification_pref('offer_alerts', **params)
            status_code = 200 if res.get('status') == 'success' else 400
            return self._json_response(res, status=status_code)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # 4. EMAIL NEWSLETTER API
    # ─────────────────────────────────────────────
    @http.route([
        '/api/ecommerce/customer/email_newsletter',
        '/api/ecommerce/customer/email-newsletter',
        '/api/ecommerce/customer/notification/email_newsletter',
        '/api/ecommerce/notifications/email_newsletter',
        '/api/ecommerce/email_newsletter'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def update_email_newsletter_json(self, **kwargs):
        try:
            return self._update_single_notification_pref('email_newsletter', **kwargs)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route([
        '/api/ecommerce/customer/email_newsletter',
        '/api/ecommerce/customer/email-newsletter',
        '/api/ecommerce/customer/notification/email_newsletter',
        '/api/ecommerce/notifications/email_newsletter',
        '/api/ecommerce/email_newsletter'
    ], type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], cors='*', csrf=False)
    def update_email_newsletter_http(self, **kwargs):
        try:
            params = self._extract_request_params(kwargs)
            res = self._update_single_notification_pref('email_newsletter', **params)
            status_code = 200 if res.get('status') == 'success' else 400
            return self._json_response(res, status=status_code)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # ALL NOTIFICATION PREFERENCES (LIST & BULK UPDATE)
    # ─────────────────────────────────────────────
    def _handle_all_notification_preferences(self, **kwargs):
        try:
            customer, err = self._resolve_customer_for_notifications(**kwargs)
            if err:
                return err

            vals = {}
            for pref in ['push_notifications', 'order_updates', 'offer_alerts', 'email_newsletter']:
                if pref in kwargs and kwargs[pref] is not None:
                    vals[pref] = self._parse_notification_bool(kwargs[pref])

            if vals:
                customer.write(vals)
                message = "Notification preferences updated successfully"
            else:
                message = "Notification preferences retrieved successfully"

            preferences_list = [
                {
                    "key": "push_notifications",
                    "title": "Push Notifications",
                    "subtitle": "Alerts on new arrivals & deals",
                    "enabled": customer.push_notifications
                },
                {
                    "key": "order_updates",
                    "title": "Order Updates",
                    "subtitle": "Shipping & delivery status",
                    "enabled": customer.order_updates
                },
                {
                    "key": "offer_alerts",
                    "title": "Offer Alerts",
                    "subtitle": "Festive discounts & flash sales",
                    "enabled": customer.offer_alerts
                },
                {
                    "key": "email_newsletter",
                    "title": "Email Newsletter",
                    "subtitle": "Monthly trends & new collections",
                    "enabled": customer.email_newsletter
                }
            ]

            all_prefs = {
                "push_notifications": customer.push_notifications,
                "order_updates": customer.order_updates,
                "offer_alerts": customer.offer_alerts,
                "email_newsletter": customer.email_newsletter
            }

            return {
                "status": "success",
                "message": message,
                "customer_id": customer.id,
                "preferences": preferences_list,
                "data": {
                    "customer_id": customer.id,
                    "title": "Notifications",
                    "preferences": preferences_list,
                    "values": all_prefs
                },
                "values": all_prefs
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route([
        '/api/ecommerce/customer/notifications',
        '/api/ecommerce/customer/notification_preferences',
        '/api/ecommerce/customer/notification-preferences',
        '/api/ecommerce/notifications/preferences'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def notification_preferences_json(self, **kwargs):
        try:
            return self._handle_all_notification_preferences(**kwargs)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route([
        '/api/ecommerce/customer/notifications',
        '/api/ecommerce/customer/notification_preferences',
        '/api/ecommerce/customer/notification-preferences',
        '/api/ecommerce/notifications/preferences'
    ], type='http', auth='public', methods=['GET', 'POST', 'OPTIONS'], cors='*', csrf=False)
    def notification_preferences_http(self, **kwargs):
        try:
            params = self._extract_request_params(kwargs)
            res = self._handle_all_notification_preferences(**params)
            status_code = 200 if res.get('status') == 'success' else 400
            return self._json_response(res, status=status_code)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, 500)

    # ─────────────────────────────────────────────
    # CUSTOMER LOGOUT API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/logout', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def logout(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            return {
                "status": "success",
                "message": "Logged out successfully"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # DELETE CUSTOMER ACCOUNT API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/customer/delete', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def delete_customer_account(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            if not customer_id:
                return {"status": "error", "message": "customer_id is required"}

            customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
            if not customer.exists():
                return {"status": "error", "message": "Customer not found"}

            # Deactivate account by setting active = False
            customer.write({'active': False})

            return {
                "status": "success",
                "message": "Account deleted/deactivated successfully"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # GET ACTIVE OFFERS / PROMOTIONS API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/active_offers', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_active_offers(self, **kwargs):
        try:
            customer_id = kwargs.get('customer_id')
            category = kwargs.get('category')
            branch_id = kwargs.get('branch_id')
            branch_name = kwargs.get('branch_name')
            
            # Resolve Branch
            branch = self._resolve_branch(kwargs)

            domain = [('active', '=', True)]
            
            if category:
                domain.append(('notification_category', '=', category))
            else:
                domain.append(('notification_category', 'in', ['offer_alert', 'new_arrival']))
                
            if customer_id:
                domain.append('|')
                domain.append(('customer_id', '=', int(customer_id)))
                domain.append(('customer_id', '=', False))
            else:
                domain.append(('customer_id', '=', False))

            notifications = request.env['ecommerce.notification'].sudo().search(domain, order='created_at desc')
            
            offers = []
            for item in notifications:
                offers.append({
                    "id": item.id,
                    "title": item.title,
                    "message": item.message,
                    "image": item.image.decode('utf-8') if isinstance(item.image, bytes) else item.image,
                    "category": item.notification_category,
                    "branch_id": branch.id if branch else None,
                    "branch_name": branch.name if branch else "All Branches",
                    "created_at": item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None
                })
            
            return {
                "status": "success",
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None,
                "offers": offers
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # GET CATEGORIES API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/categories', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_categories(self, **kwargs):
        try:
            parent_name = kwargs.get('parent_name', 'Saleable')
            branch_id = kwargs.get('branch_id')
            branch_name = kwargs.get('branch_name')

            # Resolve Branch
            branch = self._resolve_branch(kwargs)

            domain = []
            if parent_name:
                parent = request.env['product.category'].sudo().search([('name', '=', parent_name)], limit=1)
                if parent:
                    domain.append(('parent_id', '=', parent.id))
            
            if not domain:
                domain = [('name', 'in', ['Necklaces', 'Earrings', 'Rings', 'Bracelets', 'Wedding Sets'])]

            categories = request.env['product.category'].sudo().search(domain)
            category_list = []
            for cat in categories:
                category_list.append({
                    "id": cat.id,
                    "name": cat.name,
                    "parent_id": cat.parent_id.id if cat.parent_id else None,
                    "parent_name": cat.parent_id.name if cat.parent_id else None
                })
            return {
                "status": "success",
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None,
                "categories": category_list
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # GET CATEGORY PRODUCTS API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/category_products', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_category_products(self, **kwargs):
        try:
            category_id = kwargs.get('category_id')
            category_name = kwargs.get('category_name')
            branch_id = kwargs.get('branch_id')
            branch_name = kwargs.get('branch_name')
            currency_code = kwargs.get('currency')
            customer_id = kwargs.get('customer_id')

            if not category_id and not category_name:
                return {"status": "error", "message": "category_id or category_name is required"}

            # Resolve Category
            Category = request.env['product.category'].sudo()
            category = None
            if category_id:
                category = Category.browse(int(category_id))
            elif category_name:
                category = Category.search([('name', 'ilike', category_name)], limit=1)

            if not category or not category.exists():
                return {"status": "error", "message": "Category not found"}

            # Resolve Currency
            Currency = request.env['res.currency'].sudo()
            target_currency = None
            if currency_code:
                target_currency = Currency.search([('name', '=', currency_code.upper())], limit=1)
            if not target_currency and customer_id:
                customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
                if customer.exists() and customer.currency_id:
                    target_currency = customer.currency_id

            # Resolve Branch
            branch = self._resolve_branch(kwargs)

            company = branch.company_id if branch and branch.company_id else request.env.company
            company_currency = company.currency_id
            if not target_currency:
                target_currency = company_currency

            # Build Domain
            domain = [
                ('sale_ok', '=', True),
                ('categ_id', '=', category.id)
            ]
            if branch:
                domain.append('|')
                domain.append(('branch_id', '=', branch.id))
                domain.append(('branch_id', '=', False))

            products = request.env['product.template'].sudo().search(domain)

            # Resolve locations for this branch
            locations = request.env['stock.location'].sudo()
            if branch:
                locations = request.env['stock.location'].sudo().search([('branch_id', '=', branch.id)])

            product_data = []
            for prod in products:
                description = prod.description_sale or prod.description or ""
                purity_name = prod.purity_id.name if prod.purity_id else None
                purity_percentage = prod.purity_id.percentage if prod.purity_id else None
                
                total_stock = 0
                available_locations = []
                for loc in locations:
                    quants = request.env['stock.quant'].sudo().search([
                        ('product_id.product_tmpl_id', '=', prod.id),
                        ('location_id', '=', loc.id),
                        ('quantity', '>', 0)
                    ])
                    total_qty = sum(quants.mapped('quantity'))
                    if total_qty > 0:
                        total_stock += total_qty
                        available_locations.append(loc.name)

                # Convert price if needed
                list_price = prod.list_price or 0.0
                if target_currency and company_currency and target_currency != company_currency:
                    converted_price = company_currency._convert(
                        list_price, target_currency, company, fields.Date.today()
                    )
                else:
                    converted_price = list_price

                # Check if in customer's wishlist
                in_wishlist = False
                if customer_id:
                    wish_item = request.env['ecommerce.wishlist'].sudo().search([
                        ('customer_id', '=', int(customer_id)),
                        ('product_id', '=', prod.id)
                    ], limit=1)
                    in_wishlist = bool(wish_item)

                product_data.append({
                    "id": prod.id,
                    "name": prod.name,
                    "description": description,
                    "price": round(converted_price, 2),
                    "currency": target_currency.name if target_currency else "INR",
                    "branch_id": prod.branch_id.id if prod.branch_id else (branch.id if branch else None),
                    "branch_name": prod.branch_id.name if prod.branch_id else (branch.name if branch else "All Branches"),
                    "purity": purity_name,
                    "purity_percentage": purity_percentage,
                    "total_stock": total_stock,
                    "available_locations": available_locations,
                    "in_wishlist": in_wishlist,
                    "image": prod.image_1920.decode('utf-8') if isinstance(prod.image_1920, bytes) else prod.image_1920
                })

            return {
                "status": "success",
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None,
                "category": {
                    "id": category.id,
                    "name": category.name
                },
                "products": product_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # PRODUCT DETAIL API (JSON)
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/product_detail', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_product_detail(self, **kwargs):
        try:
            product_id = kwargs.get('product_id')
            customer_id = kwargs.get('customer_id')
            branch_id = kwargs.get('branch_id')
            branch_name = kwargs.get('branch_name')
            currency_code = kwargs.get('currency')

            if not product_id:
                return {"status": "error", "message": "product_id is required"}

            # Resolve Product Template
            ProductTemplate = request.env['product.template'].sudo()
            prod = ProductTemplate.browse(int(product_id))
            if not prod or not prod.exists():
                return {"status": "error", "message": "Product not found"}

            # Resolve Currency
            Currency = request.env['res.currency'].sudo()
            target_currency = None
            if currency_code:
                target_currency = Currency.search([('name', '=', currency_code.upper())], limit=1)
            if not target_currency and customer_id:
                customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
                if customer.exists() and customer.currency_id:
                    target_currency = customer.currency_id

            # Resolve Branch
            branch = self._resolve_branch(kwargs)

            company = branch.company_id if branch and branch.company_id else request.env.company
            company_currency = company.currency_id
            if not target_currency:
                target_currency = company_currency

            # Resolve locations for this branch
            locations = request.env['stock.location'].sudo()
            if branch:
                locations = request.env['stock.location'].sudo().search([('branch_id', '=', branch.id)])

            # Stock Calculation
            total_stock = 0
            available_locations = []
            for loc in locations:
                quants = request.env['stock.quant'].sudo().search([
                    ('product_id.product_tmpl_id', '=', prod.id),
                    ('location_id', '=', loc.id),
                    ('quantity', '>', 0)
                ])
                total_qty = sum(quants.mapped('quantity'))
                if total_qty > 0:
                    total_stock += total_qty
                    available_locations.append(loc.name)

            # Price Conversion
            list_price = prod.list_price or 0.0
            if target_currency and company_currency and target_currency != company_currency:
                converted_price = company_currency._convert(
                    list_price, target_currency, company, fields.Date.today()
                )
            else:
                converted_price = list_price

            # Check if in customer's wishlist
            in_wishlist = False
            if customer_id:
                wish_item = request.env['ecommerce.wishlist'].sudo().search([
                    ('customer_id', '=', int(customer_id)),
                    ('product_id', '=', prod.id)
                ], limit=1)
                in_wishlist = bool(wish_item)

            # Calculate average rating and reviews count
            reviews = request.env['ecommerce.product.review'].sudo().search([
                ('product_id', '=', prod.id)
            ])
            reviews_count = len(reviews)
            if reviews_count > 0:
                avg_rating = round(sum(r.rating for r in reviews) / reviews_count, 1)
            else:
                avg_rating = 4.8  # Default rating

            # Original price (mimicking a 20% discount if not defined)
            original_price = round(converted_price / 0.8, 2)
            discount_percentage = 20

            purity_name = prod.purity_id.name if prod.purity_id else None
            purity_percentage = prod.purity_id.percentage if prod.purity_id else None

            description = prod.description_sale or prod.description or ""

            product_details = {
                "id": prod.id,
                "name": prod.name,
                "description": description,
                "price": round(converted_price, 2),
                "original_price": original_price,
                "discount_percentage": discount_percentage,
                "currency": target_currency.name if target_currency else "INR",
                "currency_symbol": target_currency.symbol or (target_currency.name if target_currency else "₹"),
                "branch_id": prod.branch_id.id if prod.branch_id else (branch.id if branch else None),
                "branch_name": prod.branch_id.name if prod.branch_id else (branch.name if branch else "All Branches"),
                "purity": purity_name,
                "purity_percentage": purity_percentage,
                "total_stock": total_stock,
                "available_locations": available_locations,
                "rating": avg_rating,
                "reviews_count": reviews_count,
                "in_wishlist": in_wishlist,
                "image": prod.image_1920.decode('utf-8') if isinstance(prod.image_1920, bytes) else prod.image_1920
            }

            return {
                "status": "success",
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None,
                "product": product_details
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # LATEST MODELS API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/latest_models', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_latest_models(self, **kwargs):
        try:
            limit = kwargs.get('limit', 10)
            customer_id = kwargs.get('customer_id')
            branch_id = kwargs.get('branch_id')
            branch_name = kwargs.get('branch_name')
            currency_code = kwargs.get('currency')

            # Resolve Currency
            Currency = request.env['res.currency'].sudo()
            target_currency = None
            if currency_code:
                target_currency = Currency.search([('name', '=', currency_code.upper())], limit=1)
            if not target_currency and customer_id:
                customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
                if customer.exists() and customer.currency_id:
                    target_currency = customer.currency_id

            # Resolve Branch
            branch = self._resolve_branch(kwargs)

            company = branch.company_id if branch and branch.company_id else request.env.company
            company_currency = company.currency_id
            if not target_currency:
                target_currency = company_currency

            # Resolve locations for this branch
            locations = request.env['stock.location'].sudo()
            if branch:
                locations = request.env['stock.location'].sudo().search([('branch_id', '=', branch.id)])

            # Build Domain for Latest Models
            domain = [
                ('sale_ok', '=', True)
            ]
            if branch:
                domain.append('|')
                domain.append(('branch_id', '=', branch.id))
                domain.append(('branch_id', '=', False))

            products = request.env['product.template'].sudo().search(domain, order='create_date desc, id desc', limit=int(limit))

            product_data = []
            for prod in products:
                description = prod.description_sale or prod.description or ""
                purity_name = prod.purity_id.name if prod.purity_id else None
                purity_percentage = prod.purity_id.percentage if prod.purity_id else None
                
                total_stock = 0
                available_locations = []
                for loc in locations:
                    quants = request.env['stock.quant'].sudo().search([
                        ('product_id.product_tmpl_id', '=', prod.id),
                        ('location_id', '=', loc.id),
                        ('quantity', '>', 0)
                    ])
                    total_qty = sum(quants.mapped('quantity'))
                    if total_qty > 0:
                        total_stock += total_qty
                        available_locations.append(loc.name)

                # Convert price if needed
                list_price = prod.list_price or 0.0
                if target_currency and company_currency and target_currency != company_currency:
                    converted_price = company_currency._convert(
                        list_price, target_currency, company, fields.Date.today()
                    )
                else:
                    converted_price = list_price

                # Check if in customer's wishlist
                in_wishlist = False
                if customer_id:
                    wish_item = request.env['ecommerce.wishlist'].sudo().search([
                        ('customer_id', '=', int(customer_id)),
                        ('product_id', '=', prod.id)
                    ], limit=1)
                    in_wishlist = bool(wish_item)

                # Rating
                reviews = request.env['ecommerce.product.review'].sudo().search([
                    ('product_id', '=', prod.id)
                ])
                reviews_count = len(reviews)
                if reviews_count > 0:
                    avg_rating = round(sum(r.rating for r in reviews) / reviews_count, 1)
                else:
                    avg_rating = 4.8

                original_price = round(converted_price / 0.8, 2)
                discount_percentage = 20

                product_data.append({
                    "id": prod.id,
                    "name": prod.name,
                    "description": description,
                    "price": round(converted_price, 2),
                    "original_price": original_price,
                    "discount_percentage": discount_percentage,
                    "currency": target_currency.name if target_currency else "INR",
                    "currency_symbol": target_currency.symbol or (target_currency.name if target_currency else "₹"),
                    "branch_id": prod.branch_id.id if prod.branch_id else (branch.id if branch else None),
                    "branch_name": prod.branch_id.name if prod.branch_id else (branch.name if branch else "All Branches"),
                    "purity": purity_name,
                    "purity_percentage": purity_percentage,
                    "total_stock": total_stock,
                    "available_locations": available_locations,
                    "rating": avg_rating,
                    "reviews_count": reviews_count,
                    "in_wishlist": in_wishlist,
                    "badge": "NEW",
                    "image": prod.image_1920.decode('utf-8') if isinstance(prod.image_1920, bytes) else prod.image_1920
                })

            return {
                "status": "success",
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None,
                "count": len(product_data),
                "products": product_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # RECOMMENDATIONS API
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/recommendations', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_recommendations(self, **kwargs):
        try:
            limit = kwargs.get('limit', 10)
            customer_id = kwargs.get('customer_id')
            branch_id = kwargs.get('branch_id')
            branch_name = kwargs.get('branch_name')
            currency_code = kwargs.get('currency')

            # Resolve Currency
            Currency = request.env['res.currency'].sudo()
            target_currency = None
            if currency_code:
                target_currency = Currency.search([('name', '=', currency_code.upper())], limit=1)
            if not target_currency and customer_id:
                customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
                if customer.exists() and customer.currency_id:
                    target_currency = customer.currency_id

            # Resolve Branch
            branch = self._resolve_branch(kwargs)

            company = branch.company_id if branch and branch.company_id else request.env.company
            company_currency = company.currency_id
            if not target_currency:
                target_currency = company_currency

            # Resolve locations for this branch
            locations = request.env['stock.location'].sudo()
            if branch:
                locations = request.env['stock.location'].sudo().search([('branch_id', '=', branch.id)])

            # Build Domain for Recommendations
            domain = [
                ('sale_ok', '=', True)
            ]
            if branch:
                domain.append('|')
                domain.append(('branch_id', '=', branch.id))
                domain.append(('branch_id', '=', False))

            # Fetch a larger pool of products to sort by rating in memory
            products = request.env['product.template'].sudo().search(domain, limit=100)

            product_pool = []
            for prod in products:
                # Rating
                reviews = request.env['ecommerce.product.review'].sudo().search([
                    ('product_id', '=', prod.id)
                ])
                reviews_count = len(reviews)
                if reviews_count > 0:
                    avg_rating = round(sum(r.rating for r in reviews) / reviews_count, 1)
                else:
                    avg_rating = 4.8

                product_pool.append((prod, avg_rating, reviews_count))

            # Sort by rating desc, then reviews count desc, then id desc
            product_pool.sort(key=lambda x: (x[1], x[2], x[0].id), reverse=True)

            # Apply limit
            product_pool = product_pool[:int(limit)]

            product_data = []
            for prod, avg_rating, reviews_count in product_pool:
                description = prod.description_sale or prod.description or ""
                purity_name = prod.purity_id.name if prod.purity_id else None
                purity_percentage = prod.purity_id.percentage if prod.purity_id else None
                
                total_stock = 0
                available_locations = []
                for loc in locations:
                    quants = request.env['stock.quant'].sudo().search([
                        ('product_id.product_tmpl_id', '=', prod.id),
                        ('location_id', '=', loc.id),
                        ('quantity', '>', 0)
                    ])
                    total_qty = sum(quants.mapped('quantity'))
                    if total_qty > 0:
                        total_stock += total_qty
                        available_locations.append(loc.name)

                # Convert price if needed
                list_price = prod.list_price or 0.0
                if target_currency and company_currency and target_currency != company_currency:
                    converted_price = company_currency._convert(
                        list_price, target_currency, company, fields.Date.today()
                    )
                else:
                    converted_price = list_price

                # Check if in customer's wishlist
                in_wishlist = False
                if customer_id:
                    wish_item = request.env['ecommerce.wishlist'].sudo().search([
                        ('customer_id', '=', int(customer_id)),
                        ('product_id', '=', prod.id)
                    ], limit=1)
                    in_wishlist = bool(wish_item)

                original_price = round(converted_price / 0.8, 2)
                discount_percentage = 20

                product_data.append({
                    "id": prod.id,
                    "name": prod.name,
                    "description": description,
                    "price": round(converted_price, 2),
                    "original_price": original_price,
                    "discount_percentage": discount_percentage,
                    "currency": target_currency.name if target_currency else "INR",
                    "currency_symbol": target_currency.symbol or (target_currency.name if target_currency else "₹"),
                    "branch_id": prod.branch_id.id if prod.branch_id else (branch.id if branch else None),
                    "branch_name": prod.branch_id.name if prod.branch_id else (branch.name if branch else "All Branches"),
                    "purity": purity_name,
                    "purity_percentage": purity_percentage,
                    "total_stock": total_stock,
                    "available_locations": available_locations,
                    "rating": avg_rating,
                    "reviews_count": reviews_count,
                    "in_wishlist": in_wishlist,
                    "image": prod.image_1920.decode('utf-8') if isinstance(prod.image_1920, bytes) else prod.image_1920
                })

            return {
                "status": "success",
                "branch": branch.name if branch else "All Branches",
                "branch_id": branch.id if branch else None,
                "count": len(product_data),
                "products": product_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # API STATUS & HEALTH CHECK
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/status', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def api_status_json(self, **kwargs):
        """Return operational status of the eCommerce API (JSON-RPC)."""
        try:
            request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'ecommerce_api.is_enabled'")
            row = request.env.cr.fetchone()
            is_enabled_val = row[0] if row else 'True'
        except Exception:
            is_enabled_val = 'True'

        is_enabled = str(is_enabled_val).strip().lower() not in ('false', '0', 'off', 'no')

        try:
            request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'ecommerce_api.disabled_message'")
            msg_row = request.env.cr.fetchone()
            disabled_msg = msg_row[0] if msg_row and msg_row[0] else 'eCommerce API is currently disabled for maintenance. Please try again later.'
        except Exception:
            disabled_msg = 'eCommerce API is currently disabled for maintenance. Please try again later.'

        msg = "eCommerce API is active and operational." if is_enabled else disabled_msg
        return {
            "status": "success",
            "api_status": "online" if is_enabled else "offline",
            "api_enabled": is_enabled,
            "message": msg,
        }

    @http.route('/api/ecommerce/status', type='http', auth='public', methods=['GET', 'OPTIONS'], cors='*', csrf=False)
    def api_status_http(self, **kwargs):
        """Return operational status of the eCommerce API (HTTP GET)."""
        try:
            request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'ecommerce_api.is_enabled'")
            row = request.env.cr.fetchone()
            is_enabled_val = row[0] if row else 'True'
        except Exception:
            is_enabled_val = 'True'

        is_enabled = str(is_enabled_val).strip().lower() not in ('false', '0', 'off', 'no')

        try:
            request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'ecommerce_api.disabled_message'")
            msg_row = request.env.cr.fetchone()
            disabled_msg = msg_row[0] if msg_row and msg_row[0] else 'eCommerce API is currently disabled for maintenance. Please try again later.'
        except Exception:
            disabled_msg = 'eCommerce API is currently disabled for maintenance. Please try again later.'

        msg = "eCommerce API is active and operational." if is_enabled else disabled_msg
        data = {
            "status": "success",
            "api_status": "online" if is_enabled else "offline",
            "api_enabled": is_enabled,
            "message": msg,
        }
        return Response(
            json.dumps(data),
            status=200 if is_enabled else 503,
            headers={
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            }
        )
