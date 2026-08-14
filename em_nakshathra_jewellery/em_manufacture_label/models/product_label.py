from odoo import models, fields, api

class ProductLabel(models.Model):
    _inherit = 'product.label'

    production_id = fields.Many2one(
        'mrp.production',
        string="Manufacture Order",
        domain="[('state', '=', 'done'), ('product_id', '=', product_id)]"
    )
    unlabelled_weight_mrp = fields.Float(
        string="Unlabelled Weight",
        compute="_compute_unlabelled_weight",
        store=False,
    )

    @api.depends('purchase_id', 'job_work_id', 'production_id', 'sale_gross_weight')
    def _compute_unlabelled_weight(self):
        super()._compute_unlabelled_weight()
        for rec in self:
            rec.unlabelled_weight_mrp = 0.0
            if rec.production_id:
                mo = rec.production_id
                # Deduct all other labels on this Manufacturing Order, then deduct current label's live weight
                other_labels = self.env['product.label'].search([
                    ('production_id', '=', mo.id)
                ]) - rec
                total_other = sum(other_labels.mapped('sale_gross_weight'))
                mo_weight = mo.total_grams or mo.product_qty
                rec.unlabelled_weight_mrp = mo_weight - total_other - (rec.sale_gross_weight or 0.0)
