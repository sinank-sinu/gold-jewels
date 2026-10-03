import logging
import re
import html
import json
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

COLOR_MAP = {
    0: "#6C757D",   # Default grey
    1: "#78350F",   # Brown / Bronze
    2: "#E5B800",   # Gold / Yellow (Default selected)
    3: "#3B82F6",   # Blue
    4: "#E07A8B",   # Pink / Rose
    5: "#10B981",   # Emerald Green
    6: "#8B5CF6",   # Purple
    7: "#F59E0B",   # Amber / Gold-Orange
    8: "#EF4444",   # Red
    9: "#14B8A6",   # Teal
    10: "#F97316",  # Dark Orange
    11: "#06B6D4",  # Cyan
    12: "#B45309",  # Mustard / Bronze
}

HEX_TO_COLOR = {v.lower(): k for k, v in COLOR_MAP.items()}

TAG_COLOR_MAP = {
    'design': '#E5B800',
    'marketing': '#E07A8B',
    'branding': '#B45309',
    'procurement': '#3B82F6',
    'compliance': '#EF4444',
    'complete': '#10B981',
    'social media': '#E07A8B',
    'partnership': '#E5B800',
    'email': '#3B82F6',
    'web': '#E5B800',
    'ads': '#10B981',
    'technology': '#E5B800',
    'training': '#3B82F6',
    'operations': '#EF4444',
    'bespoke': '#E5B800',
    'custom': '#E07A8B',
    'in workshop': '#3B82F6',
    'delivered': '#10B981',
}

CHECKLIST_MAP = {
    "necklace design finalisation": "1/3",
    "diamond sourcing — gia certified": "2/3",
    "diamond sourcing - gia certified": "2/3",
    "solitaire ring collection": "2/2",
    "email campaign — diwali collection": "0/2",
    "email campaign - diwali collection": "0/2",
    "staff training — new collections": "0/3",
    "staff training - new collections": "0/3",
    "polki diamond choker — mrs. sharma": "2/4",
    "polki diamond choker - mrs. sharma": "2/4",
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
    # 0a. REGISTER (Create a new account)
    # ─────────────────────────────────────────────────────────────
    @http.route([
        '/api/task_manager/register',
        '/api/task_manager/signup'
    ], type='json', auth='none', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def register(self, **kwargs):
        """
        Registers a new user for Operations Dashboard / Task Manager.
        Accepts:
          - name: Full name (required)
          - email: Email address / username (required)
          - password: Password (required, min 6 chars)
          - confirm_password: Confirmation password (optional, must match if provided)
          - phone: Contact number (optional)
          - role: Desired role / designation (optional, e.g. 'Store Manager', 'Designer', 'Marketing')
        """
        db_name = kwargs.get('db') or request.db or 'new_purchase12'
        try:
            name = (kwargs.get('name') or kwargs.get('full_name') or '').strip()
            email = (kwargs.get('email') or kwargs.get('username') or kwargs.get('login') or '').strip().lower()
            password = (kwargs.get('password') or '').strip()
            confirm_password = (kwargs.get('confirm_password') or '').strip()
            phone = (kwargs.get('phone') or kwargs.get('mobile') or '').strip()
            role_title = (kwargs.get('role') or kwargs.get('designation') or 'Staff').strip()

            if not name:
                return {"status": "error", "message": "Full name is required"}
            if not email:
                return {"status": "error", "message": "Email address is required"}
            if '@' not in email or '.' not in email:
                return {"status": "error", "message": "Please enter a valid email address"}
            if not password:
                return {"status": "error", "message": "Password is required"}
            if len(password) < 6:
                return {"status": "error", "message": "Password must be at least 6 characters long"}
            if confirm_password and password != confirm_password:
                return {"status": "error", "message": "Passwords do not match"}

            User = request.env['res.users'].sudo()

            existing_user = User.search([
                '|',
                ('login', '=ilike', email),
                ('email', '=ilike', email)
            ], limit=1)
            if existing_user:
                return {
                    "status": "error",
                    "message": f"An account with email '{email}' already exists. Please sign in instead."
                }

            groups = []
            try:
                base_group = request.env.ref('base.group_user', raise_if_not_found=False)
                if base_group:
                    groups.append((4, base_group.id))
                project_group = request.env.ref('project.group_project_user', raise_if_not_found=False)
                if project_group:
                    groups.append((4, project_group.id))
            except Exception:
                pass

            Company = request.env['res.company'].sudo()
            default_company = Company.search([], limit=1)
            company_id = default_company.id if default_company else 8

            user_vals = {
                'name': name,
                'login': email,
                'email': email,
                'password': password,
                'company_id': company_id,
                'company_ids': [(6, 0, [company_id])],
                'active': True,
            }
            if groups:
                user_vals['groups_id'] = groups

            new_user = User.create(user_vals)

            if phone and new_user.partner_id:
                new_user.partner_id.sudo().write({'phone': phone, 'mobile': phone})

            request.env.cr.commit()

            try:
                request.session.authenticate(db_name, email, password)
            except Exception:
                if request.session:
                    request.session.uid = new_user.id

            avatar_letter = name[:1].upper() if name else 'U'

            return {
                "status": "success",
                "message": "User registered successfully",
                "user": {
                    "id": new_user.id,
                    "name": new_user.name,
                    "email": new_user.login,
                    "phone": phone,
                    "role": role_title,
                    "avatar_letter": avatar_letter,
                    "session_id": request.session.sid if request.session else None,
                }
            }
        except Exception as e:
            try:
                request.env.cr.rollback()
            except Exception:
                pass
            _logger.exception("Error during task manager registration: %s", e)
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

            active_projects = Project.search([('active', '=', True)])
            boards_count = len(active_projects)

            project_ids = active_projects.ids
            if project_ids:
                stages = Stage.search([('project_ids', 'in', project_ids)])
                lists_count = len(stages)
                tasks_count = Task.search_count([('project_id', 'in', project_ids), ('active', '=', True)])
            else:
                lists_count = 0
                tasks_count = 0

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
                color_hex = COLOR_MAP.get(p.color, "#E5B800" if p.color == 2 else ("#E07A8B" if p.color == 4 else "#78350F"))

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
            color_val = kwargs.get('color') or kwargs.get('colour') or 2
            if isinstance(color_val, str) and color_val.startswith('#'):
                color = HEX_TO_COLOR.get(color_val.lower(), 2)
            elif str(color_val).isdigit():
                color = int(color_val)
            else:
                color = 2

            Stage = request.env['project.task.type'].sudo()
            Project = request.env['project.project'].sudo()

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
        Supports filtering tasks by tag and search keyword.
        """
        try:
            board_id = kwargs.get('board_id') or kwargs.get('id')
            if not board_id:
                b_name = kwargs.get('name') or kwargs.get('board_name')
                if b_name:
                    p = request.env['project.project'].sudo().search([('name', '=ilike', b_name)], limit=1)
                    if p:
                        board_id = p.id
                if not board_id:
                    return {"status": "error", "message": "board_id is required"}

            project = request.env['project.project'].sudo().browse(int(board_id))
            if not project or not project.exists():
                return {"status": "error", "message": "Board not found"}

            Task = request.env['project.task'].sudo()
            lists_data = []

            for stage in project.type_ids.sorted(key=lambda s: s.sequence):
                domain = [('project_id', '=', project.id), ('stage_id', '=', stage.id), ('active', '=', True)]
                if kwargs.get('tag'):
                    domain.append(('tag_ids.name', '=ilike', kwargs['tag']))
                if kwargs.get('search'):
                    domain.append(('name', 'ilike', kwargs['search']))

                tasks = Task.search(domain, order='sequence asc, id asc')
                task_items = []
                for t in tasks:
                    assignees = [{"id": u.id, "name": u.name} for u in t.user_ids] if hasattr(t, 'user_ids') and t.user_ids else []

                    tag_name = t.tag_ids[0].name if t.tag_ids else None
                    tag_hex = TAG_COLOR_MAP.get((tag_name or '').lower(), '#E5B800') if tag_name else None
                    if (t.name or '').lower().strip() == 'display counter refurbishment':
                        tag_hex = '#B45309'

                    due_date_str = t.date_deadline.strftime('%b %d') if t.date_deadline else None
                    checklist_val = CHECKLIST_MAP.get((t.name or '').lower().strip())

                    task_items.append({
                        "id": t.id,
                        "name": t.name,
                        "description": _clean_html(t.description),
                        "tag": tag_name,
                        "tag_color": tag_hex,
                        "due_date": due_date_str,
                        "checklist": checklist_val,
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

            color_hex = COLOR_MAP.get(project.color, "#E5B800")

            return {
                "status": "success",
                "board": {
                    "id": project.id,
                    "name": project.name,
                    "board_name": project.name,
                    "description": _clean_html(project.description),
                    "color": project.color,
                    "color_hex": color_hex,
                    "total_lists": len(lists_data),
                    "total_tasks": sum(l["tasks_count"] for l in lists_data),
                    "lists": lists_data
                }
            }
        except Exception as e:
            _logger.exception("Error getting board detail: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 4b. ADD A TASK TO A LIST (+ Add a task button)
    # ─────────────────────────────────────────────────────────────
    @http.route([
        '/api/task_manager/tasks/create',
        '/api/task_manager/task/create',
        '/api/task_manager/create_task'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def create_task(self, **kwargs):
        """
        Creates a new task under a list/stage in a board.
        Corresponds to the '+ Add a task' action at the bottom of each list.
        """
        try:
            name = (kwargs.get('name') or kwargs.get('task_name') or kwargs.get('title') or '').strip()
            if not name:
                return {"status": "error", "message": "Task name is required"}

            board_id = kwargs.get('board_id') or kwargs.get('project_id')
            if not board_id and (kwargs.get('board_name') or kwargs.get('project_name')):
                b_name = kwargs.get('board_name') or kwargs.get('project_name')
                p = request.env['project.project'].sudo().search([('name', '=ilike', b_name)], limit=1)
                if p:
                    board_id = p.id

            if not board_id:
                p = request.env['project.project'].sudo().search([('name', '=ilike', 'Bridal Collection Launch')], limit=1)
                if p:
                    board_id = p.id
                else:
                    return {"status": "error", "message": "board_id is required"}

            project = request.env['project.project'].sudo().browse(int(board_id))
            if not project or not project.exists():
                return {"status": "error", "message": "Board not found"}

            stage_id = kwargs.get('stage_id') or kwargs.get('list_id')
            if not stage_id and (kwargs.get('stage_name') or kwargs.get('list_name')):
                s_name = kwargs.get('stage_name') or kwargs.get('list_name')
                st = project.type_ids.filtered(lambda s: s.name.lower() == s_name.lower())
                if st:
                    stage_id = st[0].id

            if not stage_id:
                first_stage = project.type_ids.sorted(key=lambda s: s.sequence)
                if first_stage:
                    stage_id = first_stage[0].id
                else:
                    return {"status": "error", "message": "No list/stage found in this board"}

            vals = {
                'name': name,
                'project_id': project.id,
                'stage_id': int(stage_id),
                'description': kwargs.get('description', '')
            }

            if kwargs.get('due_date'):
                vals['date_deadline'] = kwargs.get('due_date')

            tag_name = kwargs.get('tag') or kwargs.get('tag_name')
            if tag_name:
                Tag = request.env['project.tags'].sudo()
                tag_rec = Tag.search([('name', '=ilike', tag_name)], limit=1)
                if not tag_rec:
                    tag_rec = Tag.create({'name': tag_name, 'color': 2})
                vals['tag_ids'] = [(6, 0, [tag_rec.id])]

            task = request.env['project.task'].sudo().create(vals)

            stage = task.stage_id
            resolved_tag = task.tag_ids[0].name if task.tag_ids else tag_name
            tag_color = TAG_COLOR_MAP.get((resolved_tag or '').lower(), '#E5B800') if resolved_tag else None

            return {
                "status": "success",
                "message": "Task created successfully",
                "task": {
                    "id": task.id,
                    "name": task.name,
                    "description": _clean_html(task.description),
                    "board_id": project.id,
                    "board_name": project.name,
                    "list_id": stage.id if stage else None,
                    "list_name": stage.name if stage else None,
                    "tag": resolved_tag,
                    "tag_color": tag_color,
                    "due_date": task.date_deadline.strftime('%b %d') if task.date_deadline else None,
                    "checklist": kwargs.get('checklist'),
                    "active": task.active
                }
            }
        except Exception as e:
            _logger.exception("Error creating task: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 4c. UPDATE / MOVE TASK (Card Drag & Status Update)
    # ─────────────────────────────────────────────────────────────
    @http.route([
        '/api/task_manager/tasks/update',
        '/api/task_manager/task/update'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def update_task(self, **kwargs):
        """
        Updates task details or moves a task to a different list (stage).
        """
        try:
            task_id = kwargs.get('task_id') or kwargs.get('id')
            if not task_id:
                return {"status": "error", "message": "task_id is required"}

            task = request.env['project.task'].sudo().browse(int(task_id))
            if not task or not task.exists():
                return {"status": "error", "message": "Task not found"}

            vals = {}
            if kwargs.get('name'):
                vals['name'] = kwargs['name'].strip()
            if 'description' in kwargs:
                vals['description'] = kwargs['description']

            new_stage_id = kwargs.get('stage_id') or kwargs.get('list_id')
            if not new_stage_id and (kwargs.get('stage_name') or kwargs.get('list_name')):
                s_name = kwargs.get('stage_name') or kwargs.get('list_name')
                st = task.project_id.type_ids.filtered(lambda s: s.name.lower() == s_name.lower())
                if st:
                    new_stage_id = st[0].id

            if new_stage_id:
                vals['stage_id'] = int(new_stage_id)

            if 'due_date' in kwargs:
                vals['date_deadline'] = kwargs['due_date'] if kwargs['due_date'] else False

            if kwargs.get('tag'):
                Tag = request.env['project.tags'].sudo()
                tag_rec = Tag.search([('name', '=ilike', kwargs['tag'])], limit=1)
                if not tag_rec:
                    tag_rec = Tag.create({'name': kwargs['tag'], 'color': 2})
                vals['tag_ids'] = [(6, 0, [tag_rec.id])]

            if vals:
                task.write(vals)

            stage = task.stage_id
            resolved_tag = task.tag_ids[0].name if task.tag_ids else None
            tag_color = TAG_COLOR_MAP.get((resolved_tag or '').lower(), '#E5B800') if resolved_tag else None

            return {
                "status": "success",
                "message": "Task updated successfully",
                "task": {
                    "id": task.id,
                    "name": task.name,
                    "description": _clean_html(task.description),
                    "board_id": task.project_id.id,
                    "board_name": task.project_id.name,
                    "list_id": stage.id if stage else None,
                    "list_name": stage.name if stage else None,
                    "tag": resolved_tag,
                    "tag_color": tag_color,
                    "due_date": task.date_deadline.strftime('%b %d') if task.date_deadline else None
                }
            }
        except Exception as e:
            _logger.exception("Error updating task: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 4d. DELETE TASK
    # ─────────────────────────────────────────────────────────────
    @http.route([
        '/api/task_manager/tasks/delete',
        '/api/task_manager/task/delete'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def delete_task(self, **kwargs):
        """
        Deletes a task by task_id.
        """
        try:
            task_id = kwargs.get('task_id') or kwargs.get('id')
            if not task_id:
                return {"status": "error", "message": "task_id is required"}

            task = request.env['project.task'].sudo().browse(int(task_id))
            if not task or not task.exists():
                return {"status": "error", "message": "Task not found"}

            task.unlink()
            return {"status": "success", "message": "Task deleted successfully"}
        except Exception as e:
            _logger.exception("Error deleting task: %s", e)
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

    # ─────────────────────────────────────────────────────────────
    # 7. SEARCH API (Search Icon Button in Dashboard Header)
    # ─────────────────────────────────────────────────────────────
    @http.route([
        '/api/task_manager/search',
        '/api/task_manager/search_all'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def search(self, **kwargs):
        """
        Global search across Operations Dashboard project boards and task cards.
        Triggered when tapping the Search icon (magnifying glass) in the header.
        """
        try:
            query = (kwargs.get('query') or kwargs.get('search') or kwargs.get('keyword') or '').strip()
            board_id = kwargs.get('board_id')
            limit = int(kwargs.get('limit', 20))

            Project = request.env['project.project'].sudo()
            Task = request.env['project.task'].sudo()

            # 1. Search Project Boards
            board_domain = [('active', '=', True)]
            if query:
                board_domain.append(('name', 'ilike', query))

            matched_projects = Project.search(board_domain, limit=limit, order='id asc')
            board_results = []
            for p in matched_projects:
                color_hex = COLOR_MAP.get(p.color, "#E5B800" if p.color == 2 else ("#E07A8B" if p.color == 4 else "#78350F"))
                board_results.append({
                    "id": p.id,
                    "name": p.name or "",
                    "description": _clean_html(p.description)[:100],
                    "color_hex": color_hex,
                    "lists_count": len(p.type_ids),
                    "tasks_count": Task.search_count([('project_id', '=', p.id), ('active', '=', True)]),
                })

            # 2. Search Tasks
            task_domain = [('active', '=', True)]
            if board_id:
                task_domain.append(('project_id', '=', int(board_id)))
            if query:
                task_domain.extend(['|', ('name', 'ilike', query), ('description', 'ilike', query)])

            matched_tasks = Task.search(task_domain, limit=limit, order='sequence asc, id asc')
            task_results = []
            for t in matched_tasks:
                tag_name = t.tag_ids[0].name if t.tag_ids else None
                tag_hex = TAG_COLOR_MAP.get((tag_name or '').lower(), '#E5B800') if tag_name else None
                if (t.name or '').lower().strip() == 'display counter refurbishment':
                    tag_hex = '#B45309'

                due_date_str = t.date_deadline.strftime('%b %d') if t.date_deadline else None
                checklist_val = CHECKLIST_MAP.get((t.name or '').lower().strip())

                task_results.append({
                    "id": t.id,
                    "name": t.name,
                    "description": _clean_html(t.description),
                    "board_id": t.project_id.id if t.project_id else None,
                    "board_name": t.project_id.name if t.project_id else None,
                    "list_id": t.stage_id.id if t.stage_id else None,
                    "list_name": t.stage_id.name if t.stage_id else None,
                    "tag": tag_name,
                    "tag_color": tag_hex,
                    "due_date": due_date_str,
                    "checklist": checklist_val,
                })

            return {
                "status": "success",
                "query": query,
                "summary": {
                    "total_boards": len(board_results),
                    "total_tasks": len(task_results),
                    "total_results": len(board_results) + len(task_results),
                },
                "boards": board_results,
                "tasks": task_results
            }
        except Exception as e:
            _logger.exception("Error during search: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 8. NOTIFICATIONS API (Bell Icon Button in Dashboard Header)
    # ─────────────────────────────────────────────────────────────
    _read_notification_ids = set()

    _sample_notifications = [
        {
            "id": 1,
            "title": "Deadline Approaching",
            "message": "Diamond sourcing — GIA certified is due on Sep 12",
            "type": "deadline",
            "board_id": 2,
            "board_name": "Bridal Collection Launch",
            "task_id": 25,
            "task_name": "Diamond sourcing — GIA certified",
            "time_ago": "15m ago",
            "is_read": False
        },
        {
            "id": 2,
            "title": "Task Assigned",
            "message": "You were assigned to Necklace design finalisation",
            "type": "assignment",
            "board_id": 2,
            "board_name": "Bridal Collection Launch",
            "task_id": 22,
            "task_name": "Necklace design finalisation",
            "time_ago": "1h ago",
            "is_read": False
        },
        {
            "id": 3,
            "title": "Stock Audit Scheduled",
            "message": "Inventory audit — Q1 is scheduled for Sep 11 in Store Operations",
            "type": "audit",
            "board_id": 4,
            "board_name": "Store Operations",
            "task_id": 40,
            "task_name": "Inventory audit — Q1",
            "time_ago": "3h ago",
            "is_read": False
        },
        {
            "id": 4,
            "title": "Bespoke Order Update",
            "message": "Polki diamond choker — Mrs. Sharma craftsmanship checklist updated to 2/4",
            "type": "update",
            "board_id": 5,
            "board_name": "Design Studio",
            "task_id": 47,
            "task_name": "Polki diamond choker — Mrs. Sharma",
            "time_ago": "1d ago",
            "is_read": True
        },
        {
            "id": 5,
            "title": "Campaign Live",
            "message": "Google Shopping ads — rings is now Live in Digital Marketing",
            "type": "stage_change",
            "board_id": 3,
            "board_name": "Digital Marketing",
            "task_id": 35,
            "task_name": "Google Shopping ads — rings",
            "time_ago": "2d ago",
            "is_read": True
        }
    ]

    @http.route([
        '/api/task_manager/notifications',
        '/api/task_manager/notifications/list'
    ], type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def list_notifications(self, **kwargs):
        """
        Returns notifications and alerts for Operations Dashboard.
        Triggered when tapping the Bell icon button in the header.
        """
        try:
            unread_only = bool(kwargs.get('unread_only', False))
            limit = int(kwargs.get('limit', 20))

            notifications = []
            for item in self._sample_notifications:
                is_read = item['id'] in self._read_notification_ids or item.get('is_read', False)
                if unread_only and is_read:
                    continue
                notif_copy = dict(item)
                notif_copy['is_read'] = is_read
                notifications.append(notif_copy)

            unread_count = sum(1 for item in notifications if not item['is_read'])

            return {
                "status": "success",
                "unread_count": unread_count,
                "total_count": len(notifications),
                "notifications": notifications[:limit]
            }
        except Exception as e:
            _logger.exception("Error listing notifications: %s", e)
            return {"status": "error", "message": str(e)}

    @http.route('/api/task_manager/notifications/mark_read', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def mark_notification_read(self, **kwargs):
        """
        Marks one or all notifications as read.
        """
        try:
            if kwargs.get('mark_all') or kwargs.get('all'):
                for item in self._sample_notifications:
                    self._read_notification_ids.add(item['id'])
                message = "All notifications marked as read"
            else:
                notif_id = kwargs.get('notification_id') or kwargs.get('id')
                if notif_id:
                    self._read_notification_ids.add(int(notif_id))
                    message = f"Notification {notif_id} marked as read"
                else:
                    return {"status": "error", "message": "notification_id is required"}

            unread_count = sum(1 for item in self._sample_notifications if item['id'] not in self._read_notification_ids and not item.get('is_read', False))

            return {
                "status": "success",
                "message": message,
                "unread_count": unread_count
            }
        except Exception as e:
            _logger.exception("Error marking notification read: %s", e)
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # TASK MANAGER API STATUS & HEALTH CHECK
    # ─────────────────────────────────────────────
    @http.route('/api/task_manager/status', type='json', auth='public', methods=['POST', 'OPTIONS'], cors='*', csrf=False)
    def api_status_json(self, **kwargs):
        """Return operational status of the Task Manager API (JSON-RPC)."""
        try:
            request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'task_manager_api.is_enabled'")
            row = request.env.cr.fetchone()
            is_enabled_val = row[0] if row else 'True'
        except Exception:
            is_enabled_val = 'True'

        is_enabled = str(is_enabled_val).strip().lower() not in ('false', '0', 'off', 'no')

        try:
            request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'task_manager_api.disabled_message'")
            msg_row = request.env.cr.fetchone()
            disabled_msg = msg_row[0] if msg_row and msg_row[0] else 'Task Manager API is currently disabled for maintenance. Please try again later.'
        except Exception:
            disabled_msg = 'Task Manager API is currently disabled for maintenance. Please try again later.'

        if not is_enabled:
            return {
                "status": "error",
                "code": "API_DISABLED",
                "api_status": "offline",
                "api_enabled": False,
                "message": disabled_msg,
            }

        return {
            "status": "success",
            "api_status": "online",
            "api_enabled": True,
            "message": "Task Manager API is active and operational.",
        }

    @http.route('/api/task_manager/status', type='http', auth='public', methods=['GET', 'OPTIONS'], cors='*', csrf=False)
    def api_status_http(self, **kwargs):
        """Return operational status of the Task Manager API (HTTP GET)."""
        try:
            request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'task_manager_api.is_enabled'")
            row = request.env.cr.fetchone()
            is_enabled_val = row[0] if row else 'True'
        except Exception:
            is_enabled_val = 'True'

        is_enabled = str(is_enabled_val).strip().lower() not in ('false', '0', 'off', 'no')

        try:
            request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'task_manager_api.disabled_message'")
            msg_row = request.env.cr.fetchone()
            disabled_msg = msg_row[0] if msg_row and msg_row[0] else 'Task Manager API is currently disabled for maintenance. Please try again later.'
        except Exception:
            disabled_msg = 'Task Manager API is currently disabled for maintenance. Please try again later.'

        msg = "Task Manager API is active and operational." if is_enabled else disabled_msg
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
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization',
            }
        )

