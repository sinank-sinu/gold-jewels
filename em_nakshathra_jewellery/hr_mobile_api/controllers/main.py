from odoo import http
from odoo.http import request
import json

class HRMobileAPI(http.Controller):
    #LOGIN
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
    
    #User Profile API
    @http.route('/api/hr/user/profile', type='json', auth='user', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_user_profile(self, **kwargs):
        user = request.env.user
        employee = user.employee_id
        
        if not employee:
            return {"status": "error", "message": "Employee record not found"}

        return {
            "status": "success",
            "data": {
                "name": employee.name,
                "job_title": employee.job_id if employee else None,
                "work_email": employee.work_email or "",
                "work_phone": employee.work_phone or "",
                "department": employee.department_id.name or "",
            }
        }

    #Today Overview API
    @http.route('/api/hr/dashboard/overview', type='json', auth='user', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_today_overview(self, **kwargs):
        employee = request.env.user.employee_id
        return {
            "status": "success",
            "data": {
                "attendance_state": employee.attendance_state, # 'checked_in' or 'checked_out'
                "last_check_in": employee.last_attendance_id.check_in or "",
                "total_today_hours": employee.hours_today or 0.0
            }
        }

    #Weekly Attendance API
    @http.route('/api/hr/dashboard/weekly-attendance', type='json', auth='user', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_weekly_attendance(self, **kwargs):
        employee = request.env.user.employee_id
        # Search for attendances in the last 7 days
        attendances = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id)
        ], limit=7, order='check_in desc')

        history = []
        for att in attendances:
            history.append({
                "date": att.check_in.date().isoformat(),
                "check_in": att.check_in,
                "check_out": att.check_out or "Working...",
                "worked_hours": att.worked_hours or 0.0
            })
            
        return {"status": "success", "data": history}

    #Team Status API
    @http.route('/api/hr/team/status', type='json', auth='user', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_team_status(self, **kwargs):
        employee = request.env.user.employee_id
        # Find employees who report to this person
        subordinates = request.env['hr.employee'].sudo().search([
            ('parent_id', '=', employee.id)
        ])

        team = []
        for sub in subordinates:
            team.append({
                "name": sub.name,
                "state": sub.attendance_state,
                "job": sub.job_id.name or ""
            })
            
        return {"status": "success", "data": team}
    
    #TEST TEAM STATUS API
    # @http.route('/api/hr/team/status', type='json', auth='user', methods=['POST'], csrf=False)
    # def get_team_status(self, **kwargs):
    #     try:
    #         # Fetch all active employees
    #         employees = request.env['hr.employee'].sudo().search([])

    #         team_data = []
    #         for emp in employees:
    #             team_data.append({
    #                 "id": emp.id,
    #                 "name": emp.name,
    #                 "role": emp.job_id.name or "Staff",
    #                 "employee_code": "",
    #                 "department": emp.department_id.name or "General",
    #                 "work_email": emp.work_email or "",
    #                 "work_phone": emp.work_phone or "",
    #                 "department": emp.department_id.name or "",                    
                  
    #             })

    #         return {
    #             "status": "success",
    #             "count": len(team_data),
    #             "data": team_data
    #         }
    #     except Exception as e:
    #         return {
    #             "status": "error",
    #             "message": str(e)
    #         }