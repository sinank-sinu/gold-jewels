from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    has_label_variant_report_access = fields.Boolean(
        string="Label Closing Stock Report (With Variants & Vendor)",
        compute='_compute_label_variant_report_access',
        inverse='_inverse_label_variant_report_access',
        help="Check this if the user is authorized to access the Label Closing Stock Report (With Variants & Vendor)."
    )

    def _compute_label_variant_report_access(self):
        group = self.env.ref('product_label_variant_report_xlsx.group_product_label_variant_report', raise_if_not_found=False)
        for user in self:
            user.has_label_variant_report_access = bool(group and group in user.groups_id)

    def _inverse_label_variant_report_access(self):
        group = self.env.ref('product_label_variant_report_xlsx.group_product_label_variant_report', raise_if_not_found=False)
        if not group:
            return
        for user in self:
            if user.has_label_variant_report_access:
                user.groups_id = [(4, group.id)]
            else:
                user.groups_id = [(3, group.id)]
