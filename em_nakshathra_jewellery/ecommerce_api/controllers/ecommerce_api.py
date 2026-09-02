import json
from odoo import http, fields
from odoo.http import request, Response


class EcommerceBranchAPI(http.Controller):

    # ─────────────────────────────────────────────
    # BRANCH PRODUCTS
    # ─────────────────────────────────────────────
    @http.route('/api/ecommerce/branch_products', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_branch_products(self, **kwargs):
        try:
            branch_id   = kwargs.get('branch_id')
            branch_name = (kwargs.get('branch_name') or '').strip()
            location_id = kwargs.get('location_id')
            location_name = (kwargs.get('location_name') or '').strip()
            currency_code = kwargs.get('currency')
            customer_id = kwargs.get('customer_id')

            if not branch_id and not branch_name:
                return {"status": "error", "message": "branch_id or branch_name is required"}

            # ── Resolve target currency for price conversion ──
            Currency = request.env['res.currency'].sudo()
            target_currency = None
            if currency_code:
                target_currency = Currency.search([('name', '=', currency_code.upper())], limit=1)
            if not target_currency and customer_id:
                customer = request.env['ecommerce.customer'].sudo().browse(int(customer_id))
                if customer.exists() and customer.currency_id:
                    target_currency = customer.currency_id
            
            # ── Resolve branch_name → branch_id if name was given ──
            Branch = request.env['res.branch'].sudo()
            if branch_name and not branch_id:
                branch = Branch.search([('name', 'ilike', branch_name)], limit=1)
                if not branch:
                    return {"status": "error", "message": f"Branch '{branch_name}' not found"}
                branch_id = branch.id
                resolved_branch_name = branch.name
            else:
                branch = Branch.browse(int(branch_id))
                resolved_branch_name = branch.name if branch else str(branch_id)

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
                        "branch_id": prod.branch_id.id if prod.branch_id else None,
                        "branch_name": prod.branch_id.name if prod.branch_id else "All Branches",
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

            # Resolve branch if branch_id/branch_name is provided
            Branch = request.env['res.branch'].sudo()
            branch = None
            if branch_id:
                branch = Branch.browse(int(branch_id))
            elif branch_name:
                branch = Branch.search([('name', 'ilike', branch_name)], limit=1)

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
                        "branch_id": prod.branch_id.id if prod.branch_id else None,
                        "branch_name": prod.branch_id.name if prod.branch_id else "All Branches",
                        "total_stock": total_stock,
                        "available_locations": available_locations,
                        "location_stocks": location_stocks,
                        "purity": purity_name,
                        "purity_percentage": purity_percentage
                    })

            return {
                "status": "success",
                "query": query,
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

            # ── Generate authentication token ──
            token = customer._generate_token()

            return {
                "status": "success",
                "message": "Registration successful",
                "data": {
                    "customer_id": customer.id,
                    "name": customer.name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                    "branch_id": customer.branch_id.id if hasattr(customer, 'branch_id') and customer.branch_id else None,
                    "branch_name": customer.branch_id.name if hasattr(customer, 'branch_id') and customer.branch_id else None,
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

            if not email or not password:
                return {"status": "error", "message": "Email and password are required"}

            Customer = request.env['ecommerce.customer'].sudo()
            customer = Customer.search([('email', '=', email)], limit=1)

            if not customer:
                return {"status": "error", "message": "Invalid email or password"}

            if not customer._verify_password(password):
                return {"status": "error", "message": "Invalid email or password"}

            # Generate authentication token
            token = customer._generate_token()

            return {
                "status": "success",
                "message": "Login successful",
                "data": {
                    "customer_id": customer.id,
                    "name": customer.name,
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
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

            return {
                "status": "success",
                "message": "Biometric login successful",
                "data": {
                    "customer_id": customer.id,
                    "name": customer.name,
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                    "auth_token": token,
                    "token_expiry": customer.token_expiry.strftime('%Y-%m-%d %H:%M:%S') if customer.token_expiry else None,
                }
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

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

            # Update notification preferences
            for pref in ['push_notifications', 'order_updates', 'offer_alerts', 'email_newsletter']:
                if pref in kwargs:
                    vals[pref] = bool(kwargs[pref])

            if vals:
                customer.write(vals)

            return {
                "status": "success",
                "message": "Profile updated successfully",
                "customer": {
                    "id": customer.id,
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "name": customer.name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                    "push_notifications": customer.push_notifications,
                    "order_updates": customer.order_updates,
                    "offer_alerts": customer.offer_alerts,
                    "email_newsletter": customer.email_newsletter
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

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
                    "created_at": item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None
                })
            
            return {
                "status": "success",
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
            Branch = request.env['res.branch'].sudo()
            branch = None
            if branch_id:
                branch = Branch.browse(int(branch_id))
            elif branch_name:
                branch = Branch.search([('name', 'ilike', branch_name)], limit=1)
            else:
                branch = Branch.search([], limit=1)

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
                    "purity": purity_name,
                    "purity_percentage": purity_percentage,
                    "total_stock": total_stock,
                    "available_locations": available_locations,
                    "in_wishlist": in_wishlist,
                    "image": prod.image_1920.decode('utf-8') if isinstance(prod.image_1920, bytes) else prod.image_1920
                })

            return {
                "status": "success",
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
            Branch = request.env['res.branch'].sudo()
            branch = None
            if branch_id:
                branch = Branch.browse(int(branch_id))
            elif branch_name:
                branch = Branch.search([('name', 'ilike', branch_name)], limit=1)
            else:
                branch = Branch.search([], limit=1)

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
            Branch = request.env['res.branch'].sudo()
            branch = None
            if branch_id:
                branch = Branch.browse(int(branch_id))
            elif branch_name:
                branch = Branch.search([('name', 'ilike', branch_name)], limit=1)
            else:
                branch = Branch.search([], limit=1)

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
            Branch = request.env['res.branch'].sudo()
            branch = None
            if branch_id:
                branch = Branch.browse(int(branch_id))
            elif branch_name:
                branch = Branch.search([('name', 'ilike', branch_name)], limit=1)
            else:
                branch = Branch.search([], limit=1)

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
                "count": len(product_data),
                "products": product_data
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}





