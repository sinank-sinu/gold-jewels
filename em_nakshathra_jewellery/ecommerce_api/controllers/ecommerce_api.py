from odoo import http
from odoo.http import request


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

            if not branch_id and not branch_name:
                return {"status": "error", "message": "branch_id or branch_name is required"}

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
                    quants = request.env['stock.quant'].sudo().search([
                        ('product_id.product_tmpl_id', '=', prod.id),
                        ('location_id', '=', loc.id),
                        ('quantity', '>', 0)
                    ])
                    total_qty = sum(quants.mapped('quantity'))
                    
                    if total_qty > 0:
                        total_stock += total_qty
                        available_locations.append(loc.name)
                        
                        # ── Get label information for this product at this location ──
                        labels = request.env['product.label'].sudo().search([
                            ('product_tmpl_id', '=', prod.id),
                            ('branch_location_id', '=', loc.id),
                            ('active', '=', True)
                        ])
                        
                        label_data = []
                        for label in labels:
                            label_data.append({
                                "label_number": label.label_number,
                                "label_name": label.name,
                                "tag_weight": label.tag_weight,
                                "grams": label.sale_gross_weight,
                                "purity": label.purity_id.name if label.purity_id else purity_name,
                                "purity_percentage": label.purity_id.percentage if label.purity_id else purity_percentage
                            })
                        
                        location_stocks.append({
                            "location_id": loc.id,
                            "location_name": loc.name,
                            "location_complete_name": loc.complete_name,
                            "product_name": prod.name,
                            "price": prod.list_price,
                            "description": description,
                            "image_url": f"/web/image/product.template/{prod.id}/image_1920",
                            "quantity": total_qty,
                            "purity": purity_name,
                            "purity_percentage": purity_percentage,
                            "labels": label_data
                        })
                
                # ── Only include products with stock ──
                if total_stock > 0:
                    product_data.append({
                        "id": prod.id,
                        "name": prod.name,
                        "price": prod.list_price,
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
                "data": product_data
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

            Customer = request.env['ecommerce.customer'].sudo()

            # ── Check duplicate email ──────────────────────
            if Customer.search([('email', '=', email)], limit=1):
                return {"status": "error", "message": "An account with this email already exists"}

            # ── Hash password ──────────────────────────────
            dummy = Customer.new({})
            password_hash, salt = dummy._hash_password(password)

            # ── Create customer record ─────────────────────
            customer = Customer.create({
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'phone': phone,
                'city': city,
                'password_hash': password_hash,
                'password_salt': salt,
            })

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
                }
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}
