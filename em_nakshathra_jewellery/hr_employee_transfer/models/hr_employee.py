# -*- coding: utf-8 -*-
#############################################################################
#    A part of Open HRMS Project <https://www.openhrms.com>
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        compute='_compute_branch_id',
        store=True,
        readonly=False,
        domain="[('company_id', '=', company_id)]",
        help="Branch where the employee works."
    )

    @api.depends('user_id', 'user_id.branch_id')
    def _compute_branch_id(self):
        for emp in self:
            if not emp.branch_id and emp.user_id and emp.user_id.branch_id:
                emp.branch_id = emp.user_id.branch_id
            elif not emp.branch_id:
                emp.branch_id = False


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        readonly=True,
        help="Branch where the employee works."
    )
