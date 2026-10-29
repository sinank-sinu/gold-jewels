from odoo import api, models, _
from odoo.exceptions import UserError


class ProductLabelReport(models.AbstractModel):
    _name = 'report.em_jewellery_management.report_product_label'
    _description = 'Product Label Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        labels = self.env['product.label'].browse(docids)
        if len(labels) > 1000:
            raise UserError(_("You can print a maximum of 1,000 labels at a time."))

        if labels.filtered(lambda label: label.company_id != self.env.company):
            raise UserError(_(
                "You can only print labels belonging to the active company: %s."
            ) % self.env.company.display_name)

        return {
            'doc_ids': docids,
            'doc_model': 'product.label',
            'docs': labels,
        }
