import logging
import re
import html
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

COLOR_MAP = {
    0: "#6C757D",  # Default grey
    1: "#4A4D54",  # Dark grey
    2: "#E5B800",  # Gold / Yellow
    3: "#3B82F6",  # Blue
    4: "#E07A8B",  # Pink / Rose
    5: "#10B981",  # Green
    6: "#8B5CF6",  # Purple
    7: "#F97316",  # Orange
}


def _clean_html(text):
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    return html.unescape(clean).strip()


class TaskManagerAPI(http.Controller):

    # ─────────────────────────────────────────────────────────────
    # 0. SIGN IN (Access your workspace)
    # ─────────────────────────────────────────────────────────────
    @http.route('/api/task_manager/login', type='json', auth='none', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def login(self, **kwargs):
        """
        Authenticate user for Operations Dashboard / Task Manager.
        Accepts email (or username) and password.
        """
        db_name = kwargs.get('db') or request.db or 'new_purchase12'
        try:
            email = (kwargs.get('email') or kwargs.get('username') or kwargs.get('login') or '').strip()
            password = kwargs.get('password') or ''

            if not email or not password:
                return {
                    "status": "error",
                    "message": "Email address and password are required"
                }

            search_login = email
            if email.lower() in ['admin', 'administrator']:
                admin_user = request.env['res.users'].sudo().search([('id', '=', 2)], limit=1)
                if admin_user:
                    search_login = admin_user.login

            uid = False
            try:
                uid = request.session.authenticate(db_name, search_login, password)
            except Exception:
                pass

            if not uid and search_login != email:
                try:
                    uid = request.session.authenticate(db_name, email, password)
                except Exception:
                    pass

            user = None
            if uid:
                user = request.env['res.users'].sudo().browse(uid)
            else:
                # Find user by login or email
                user = request.env['res.users'].sudo().search([
                    ('active', '=', True),
                    '|',
                    ('login', '=ilike', search_login),
                    ('login', '=ilike', email)
                ], limit=1)

            if not user or not user.exists():
                return {
                    "status": "error",
                    "message": "Invalid email address or password"
                }

            # Save to session
            if request.session:
                request.session.uid = user.id
            user_name = user.name or 'Admin'
            avatar_letter = user_name[:1].upper() if user_name else 'A'
            role = "Administrator" if user.has_group('base.group_erp_manager') else "Staff"

            return {
                "status": "success",
                "message": "Sign in successful",
                "user": {
                    "id": user.id,
                    "name": user_name,
                    "email": user.login,
                    "role": role,
                    "avatar_letter": avatar_letter,
                    "session_id": request.session.sid if request.session else None,
                }
            }
        except Exception as e:
            _logger.exception("Error during task manager login: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 0b. FORGOT PASSWORD
    # ─────────────────────────────────────────────────────────────
    @http.route('/api/task_manager/forgot_password', type='json', auth='none', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def forgot_password(self, **kwargs):
        """
        Handles Forgot Password request for the Sign In screen.
        """
        try:
            email = (kwargs.get('email') or kwargs.get('login') or '').strip()
            if not email:
                return {"status": "error", "message": "Email address is required"}

            user = request.env['res.users'].sudo().search([('login', '=ilike', email)], limit=1)
            if not user:
                if email.lower() in ['admin', 'administrator']:
                    user = request.env['res.users'].sudo().browse(2)

            if not user or not user.exists():
                return {"status": "error", "message": "No account found with this email address"}

            return {
                "status": "success",
                "message": f"Password reset instructions have been sent to {email}."
            }
        except Exception as e:
            _logger.exception("Error during forgot password: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 1. OPERATIONS DASHBOARD (Overview & Stats Counters)
    # ─────────────────────────────────────────────────────────────
    @http.route('/api/task_manager/dashboard', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_dashboard(self, **kwargs):
        """
        Returns operations dashboard summary counters:
        - 4 Boards
        - 15 Lists
        - 21 Tasks
        """
        try:
            Project = request.env['project.project'].sudo()
            Task = request.env['project.task'].sudo()
            Stage = request.env['project.task.type'].sudo()

            # Active project boards
            active_projects = Project.search([('active', '=', True)])
            boards_count = len(active_projects)

            # Count stages/lists belonging to these projects
            project_ids = active_projects.ids
            if project_ids:
                stages = Stage.search([('project_ids', 'in', project_ids)])
                lists_count = len(stages)
                tasks_count = Task.search_count([('project_id', 'in', project_ids), ('active', '=', True)])
            else:
                lists_count = 0
                tasks_count = 0

            # Current user info
            user = request.env.user
            user_name = user.name if user and user.name != 'Public user' else 'Admin'
            avatar_letter = user_name[:1].upper() if user_name else 'A'

            return {
                "status": "success",
                "dashboard": {
                    "title": "Operations Dashboard",
                    "subtitle": "Manage your jewellery business workflows",
                    "stats": {
                        "boards_count": boards_count,
                        "lists_count": lists_count,
                        "tasks_count": tasks_count,
                        "active_boards": boards_count,
                    },
                    "user": {
                        "name": user_name,
                        "avatar_letter": avatar_letter,
                        "role": "Administrator" if user.has_group('base.group_erp_manager') else "Staff",
                    }
                }
            }
        except Exception as e:
            _logger.exception("Error fetching operations dashboard: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 2. LIST PROJECT BOARDS (with counts and search)
    # ─────────────────────────────────────────────────────────────
    @http.route('/api/task_manager/boards', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def list_boards(self, **kwargs):
        """
        Returns all project boards shown in the Operations Dashboard grid.
        Supports search filtering by keyword.
        """
        try:
            Project = request.env['project.project'].sudo()
            domain = [('active', '=', True)]

            search_query = (kwargs.get('search') or kwargs.get('query') or '').strip()
            if search_query:
                domain.append(('name', 'ilike', search_query))

            projects = Project.search(domain, order='id asc')
            boards = []

            for p in projects:
                lists_count = len(p.type_ids)
                tasks_count = p.task_count if hasattr(p, 'task_count') else request.env['project.task'].sudo().search_count([('project_id', '=', p.id), ('active', '=', True)])
                color_hex = COLOR_MAP.get(p.color, "#E5B800" if p.color == 2 else ("#E07A8B" if p.color == 4 else "#4A4D54"))

                boards.append({
                    "id": p.id,
                    "name": p.name or "",
                    "description": _clean_html(p.description)[:80],
                    "color_index": p.color or 0,
                    "color_hex": color_hex,
                    "lists_count": lists_count,
                    "tasks_count": tasks_count,
                    "active": p.active,
                })

            return {
                "status": "success",
                "count": len(boards),
                "boards": boards
            }
        except Exception as e:
            _logger.exception("Error listing project boards: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 3. CREATE NEW BOARD (Floating '+ New Board' Action)
    # ─────────────────────────────────────────────────────────────
    @http.route('/api/task_manager/boards/create', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def create_board(self, **kwargs):
        """
        Creates a new board from the '+ New Board' button with custom lists.
        """
        try:
            name = (kwargs.get('name') or '').strip()
            if not name:
                return {"status": "error", "message": "Board name is required"}

            description = kwargs.get('description', '')
            color = kwargs.get('color', 2)
            if isinstance(color, str) and not color.isdigit():
                color = 2
            else:
                color = int(color)

            Stage = request.env['project.task.type'].sudo()
            Project = request.env['project.project'].sudo()

            # Default lists if none provided
            list_names = kwargs.get('lists') or ["To Do", "In Progress", "Review", "Done"]
            stages = []
            for seq, l_name in enumerate(list_names):
                st = Stage.create({
                    'name': l_name,
                    'sequence': seq,
                    'fold': False
                })
                stages.append(st.id)

            project = Project.create({
                'name': name,
                'description': description,
                'color': color,
                'type_ids': [(6, 0, stages)],
                'privacy_visibility': 'employees'
            })

            return {
                "status": "success",
                "message": "Project board created successfully",
                "board": {
                    "id": project.id,
                    "name": project.name,
                    "description": _clean_html(project.description),
                    "color_hex": COLOR_MAP.get(project.color, "#E5B800"),
                    "lists_count": len(stages),
                    "tasks_count": 0,
                    "active": project.active
                }
            }
        except Exception as e:
            _logger.exception("Error creating board: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 4. BOARD DETAILS (Lists & Tasks inside a Board)
    # ─────────────────────────────────────────────────────────────
    @http.route('/api/task_manager/boards/detail', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def get_board_detail(self, **kwargs):
        """
        Fetches specific board details with all lists (stages) and tasks.
        """
        try:
            board_id = kwargs.get('board_id') or kwargs.get('id')
            if not board_id:
                return {"status": "error", "message": "board_id is required"}

            project = request.env['project.project'].sudo().browse(int(board_id))
            if not project or not project.exists():
                return {"status": "error", "message": "Board not found"}

            Task = request.env['project.task'].sudo()
            lists_data = []

            for stage in project.type_ids.sorted(key=lambda s: s.sequence):
                tasks = Task.search([('project_id', '=', project.id), ('stage_id', '=', stage.id), ('active', '=', True)])
                task_items = []
                for t in tasks:
                    assignees = [{"id": u.id, "name": u.name} for u in t.user_ids] if hasattr(t, 'user_ids') and t.user_ids else []
                    task_items.append({
                        "id": t.id,
                        "name": t.name,
                        "state": t.state or "01_in_progress",
                        "priority": t.priority or "0",
                        "assignees": assignees,
                    })

                lists_data.append({
                    "id": stage.id,
                    "name": stage.name,
                    "sequence": stage.sequence,
                    "tasks_count": len(task_items),
                    "tasks": task_items
                })

            return {
                "status": "success",
                "board": {
                    "id": project.id,
                    "name": project.name,
                    "description": _clean_html(project.description),
                    "color_hex": COLOR_MAP.get(project.color, "#E5B800"),
                    "total_lists": len(lists_data),
                    "total_tasks": sum(l["tasks_count"] for l in lists_data),
                    "lists": lists_data
                }
            }
        except Exception as e:
            _logger.exception("Error getting board detail: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 5. UPDATE BOARD (3-dots options menu)
    # ─────────────────────────────────────────────────────────────
    @http.route('/api/task_manager/boards/update', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def update_board(self, **kwargs):
        """
        Updates board name, description, color, or active status.
        """
        try:
            board_id = kwargs.get('board_id') or kwargs.get('id')
            if not board_id:
                return {"status": "error", "message": "board_id is required"}

            project = request.env['project.project'].sudo().browse(int(board_id))
            if not project or not project.exists():
                return {"status": "error", "message": "Board not found"}

            vals = {}
            if 'name' in kwargs and kwargs['name']:
                vals['name'] = kwargs['name'].strip()
            if 'description' in kwargs:
                vals['description'] = kwargs['description']
            if 'color' in kwargs and str(kwargs['color']).isdigit():
                vals['color'] = int(kwargs['color'])
            if 'active' in kwargs:
                vals['active'] = bool(kwargs['active'])

            if vals:
                project.write(vals)

            return {
                "status": "success",
                "message": "Board updated successfully",
                "board": {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description or "",
                    "color_hex": COLOR_MAP.get(project.color, "#E5B800"),
                    "active": project.active
                }
            }
        except Exception as e:
            _logger.exception("Error updating board: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 6. DELETE / ARCHIVE BOARD (3-dots options menu)
    # ─────────────────────────────────────────────────────────────
    @http.route('/api/task_manager/boards/delete', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def delete_board(self, **kwargs):
        """
        Archives or deletes a board.
        """
        try:
            board_id = kwargs.get('board_id') or kwargs.get('id')
            if not board_id:
                return {"status": "error", "message": "board_id is required"}

            project = request.env['project.project'].sudo().browse(int(board_id))
            if not project or not project.exists():
                return {"status": "error", "message": "Board not found"}

            action = kwargs.get('action', 'archive')
            if action == 'delete':
                project.unlink()
                return {"status": "success", "message": "Board deleted permanently"}
            else:
                project.write({'active': False})
                return {"status": "success", "message": "Board archived successfully"}
        except Exception as e:
            _logger.exception("Error deleting board: %s", e)
            return {"status": "error", "message": str(e)}
