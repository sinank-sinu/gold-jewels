from odoo import models, fields, api


class PurchaseRequisition(models.Model):
    _inherit = 'material.purchase.requisition'

    def _get_branch_domain(self):
        """methode to get branch domain"""
        company = self.env.company
        branch_ids = self.env.user.branch_ids
        branch = branch_ids.filtered(
            lambda branch: branch.company_id == company)
        return [('id', 'in', branch.ids)]

    branch_id = fields.Many2one('res.branch', string='Branch', store=True,
                                domain=_get_branch_domain,
                                help='Leave this field empty if this account is'
                                     ' shared between all branches',
                                default=lambda self: self.env.user.branch_id.id,)

    job_work_id = fields.Many2one(
        'jewellery.job.work',
        string='Job Work',
        ondelete='cascade',
    )
    job_work_count = fields.Integer(
        compute='_compute_job_work_count',
        string='Job Work Count'
    )



    def _compute_job_work_count(self):
        for rec in self:
            rec.job_work_count = len(rec.job_work_id)

    def action_open_job_works(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Job Works',
            'res_model': 'jewellery.job.work',
            'view_mode': 'tree,form',
            'domain': [('requisition_id', '=', self.id)],
            'context': {
                'default_requisition_id': self.id,
            },
        }
    def action_open_label(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Labels',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('requisition_id', '=', self.id)],
            'context': {
                'default_requisition_id': self.id,
            },
        }


    def action_create_picking_and_po(self):
        res = super().action_create_picking_and_po()
        for line in self.requisition_lines:
            if line.request_action == "work order":
                for vendor in line.vendor_ids:
                    work_vals = {

                        "job_worker_id": vendor.id,
                        "requisition_id":self.id,
                        "job_work_line_ids": [
                            (
                                0,
                                0,
                                {
                                    "product_id": line.product_id.id,
                                    "product_template_id":line.product_template_id.id,
                                    "quantity": line.quantity,
                                    "no_of_pieces": line.no_of_pieces,
                                    "purity_id": line.purity_id.id,
                                    "unit_of_measure": line.product_id.uom_id.id,
                                },
                            )
                        ],
                    }

                    work = self.env["jewellery.job.work"].create(work_vals)
                    self.write({"job_work_id": work.id})

        for line in self.requisition_lines:
            if line.request_action == "purchase order":
                po_lines = self.env["purchase.order.line"].search([
                    ("order_id.requisition_order", "=", self.name),
                    ("product_id", "=", line.product_id.id),
                ])
                for po_line in po_lines:
                    po_line.purity_id = line.purity_id.id

        return res


class MaterialPurchaseRequisitionLine(models.Model):
    _inherit = "material.purchase.requisition.line"

    purity_id = fields.Many2one('gold.purity', string="Purity")
    purchase_price_per_gram = fields.Float(string="Purchase fine Rate / gram",digits=(16, 3))
    purchase_making_charge_value = fields.Float(string="Purchase Making Charge", digits=(16, 3))
    purchase_making_charge_amount = fields.Float(
        string="Purchase Making Charge Amount",
        compute="_compute_purchase_making_charge",
        digits=(16, 3),
        store=True
    )
    net_weight = fields.Float(
        string="Net Weight (g)", digits=(16, 3)
    )
    mc_fine = fields.Float(string="MC Fine", compute="_compute_purchase_mc_fine", digits=(16, 3))
    fine_weight = fields.Float(string="Fine Weight  (g)", digits=(16, 3))
    gram = fields.Float(string="Gram", digits=(16, 3))
    quantity = fields.Float(string="Quantity", compute="_compute_quantity", store=True, digits=(16, 3))

    @api.depends(
        'purchase_making_charge_value',
        'mc_fine',
    )
    def _compute_purchase_making_charge(self):
        for rec in self:
            rec.purchase_making_charge_amount = rec.mc_fine * rec.purchase_price_per_gram

    @api.depends('net_weight', 'purchase_making_charge_amount')
    def _compute_purchase_mc_fine(self):
        for rec in self:
            rec.mc_fine = rec.net_weight * (rec.purchase_making_charge_value) / 100
