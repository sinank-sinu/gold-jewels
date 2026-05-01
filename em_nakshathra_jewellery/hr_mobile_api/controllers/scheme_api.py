from odoo import http
from odoo.http import request
import json

class SchemeMobileAPI(http.Controller):
    #LOGIN
    @http.route('/api/scheme/login', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
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
                    "job_position": employee.job_id if employee else None
                }
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    #LOGOUT
    @http.route('/api/scheme/logout', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
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

    #To get existing Schemes
    @http.route('/api/scheme/my-schemes', type='json', auth='user', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_my_schemes(self, **kwargs):
        partner = request.env.user.partner_id
        
        enrollments = request.env['jewellery.scheme.enrollment'].sudo().search([
            ('partner_id', '=', partner.id)
        ])
        
        data = []
        for rec in enrollments:
            data.append({
                "plan_name": rec.name if rec.scheme_id else "No Plan Name",
                "duration": f"{rec.duration} months",
                "monthly_installment": rec.installment_amount,
            })
            
        return {
            "status": "success", 
            "data": data
        }