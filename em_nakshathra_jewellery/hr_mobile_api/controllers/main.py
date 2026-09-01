from odoo import http
from odoo.http import request
import json

class HRMobileAPI(http.Controller):

    def _get_current_user(self, kwargs):
        user = request.env.user
        public_user = request.env.ref('base.public_user', raise_if_not_found=False)
        public_id = public_user.id if public_user else None

        if not user or (public_id and user.id == public_id):
            uid = request.session.uid or kwargs.get('user_id')
            if uid:
                user = request.env['res.users'].sudo().browse(int(uid))

        if user and user.exists() and (not public_id or user.id != public_id):
            return user
        return None

    def _get_employee(self, user):
        if not user:
            return request.env['hr.employee']
        employee = user.sudo().employee_id
        if not employee:
            employee = request.env['hr.employee'].sudo().search([
                ('user_id', '=', user.id)
            ], limit=1)
        return employee

    # LOGIN
    @http.route('/api/hr/login', type='json', auth='none', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
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
            employee = self._get_employee(user)

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

    # LOGOUT
    @http.route('/api/hr/logout', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
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
    
    # User Profile API
    @http.route('/api/hr/user/profile', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_user_profile(self, **kwargs):
        user = self._get_current_user(kwargs)
        if not user:
            return {"status": "error", "message": "Session expired"}
            
        employee = self._get_employee(user)
        if not employee:
            return {"status": "error", "message": "Employee record not found"}

        return {
            "status": "success",
            "data": {
                "name": employee.name or "",
                "job_title": employee.job_id.name if employee and employee.job_id else "",
                "work_email": employee.work_email or "",
                "work_phone": employee.work_phone or "",
                "department": employee.department_id.name if employee and employee.department_id else "",
            }
        }

    # Today Overview API
    @http.route('/api/hr/dashboard/overview', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_today_overview(self, **kwargs):
        user = self._get_current_user(kwargs)
        if not user:
            return {"status": "error", "message": "Session expired"}

        employee = self._get_employee(user)
        if not employee:
            return {
                "status": "success",
                "data": {
                    "attendance_state": "checked_out",
                    "last_check_in": "",
                    "total_today_hours": 0.0
                }
            }

        last_check_in = ""
        if employee.last_attendance_id and employee.last_attendance_id.check_in:
            last_check_in = employee.last_attendance_id.check_in.isoformat()

        return {
            "status": "success",
            "data": {
                "attendance_state": employee.attendance_state or 'checked_out',
                "last_check_in": last_check_in,
                "total_today_hours": employee.hours_today or 0.0
            }
        }

    # Weekly Attendance API
    @http.route('/api/hr/dashboard/weekly-attendance', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_weekly_attendance(self, **kwargs):
        user = self._get_current_user(kwargs)
        if not user:
            return {"status": "error", "message": "Session expired"}

        employee = self._get_employee(user)
        if not employee:
            return {"status": "success", "data": []}

        attendances = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id)
        ], limit=7, order='check_in desc')

        history = []
        for att in attendances:
            history.append({
                "date": att.check_in.date().isoformat() if att.check_in else "",
                "check_in": att.check_in.isoformat() if att.check_in else "",
                "check_out": att.check_out.isoformat() if att.check_out else "Working...",
                "worked_hours": att.worked_hours or 0.0
            })
            
        return {"status": "success", "data": history}

    # Team Status API
    @http.route('/api/hr/team/status', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_team_status(self, **kwargs):
        user = self._get_current_user(kwargs)
        if not user:
            return {"status": "error", "message": "Session expired"}

        employee = self._get_employee(user)
        if not employee:
            return {"status": "success", "data": []}

        subordinates = request.env['hr.employee'].sudo().search([
            ('parent_id', '=', employee.id)
        ])

        team = []
        for sub in subordinates:
            team.append({
                "name": sub.name,
                "state": sub.attendance_state or 'checked_out',
                "job": sub.job_id.name if sub.job_id else ""
            })
            
        return {"status": "success", "data": team}