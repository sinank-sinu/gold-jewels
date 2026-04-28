from odoo import models


class ProductMovementReport(models.AbstractModel):
    _name = 'report.product_movement_report_pdf.product_movement_template'

    def _get_report_values(self, docids, data=None):
        return {
            'data': data or {},
        }