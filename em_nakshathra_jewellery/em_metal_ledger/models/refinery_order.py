from odoo import models, fields, api, _

class OldGoldRefineryIssue(models.Model):
    _inherit = 'old.gold.refinery.issue'


    def action_to_melting(self):
        # We create the RED record once moved to melting status (ISSUE)
        res = super(OldGoldRefineryIssue, self).action_to_melting()

        # Create Refinery Margin Report (Red)
        batches = ", ".join(self.batch_ids.mapped('name')) if self.batch_ids else ""
        purity = self.expected_purity_id or (self.line_ids[0].purity_id if self.line_ids else False)
        
        amount = self.total_purchase_amount
        fine_rate = amount / self.total_fine if self.total_fine > 0 else 0.0

        self.env['refinery.margin.report'].create({
            'date': fields.Date.today(),
            'issue_id': self.id,
            'type': 'issue', # Red
            'batches': batches,
            'partner_id': self.refinery_partner_id.id, 
            'gross_weight': self.total_issued_weight,
            'net_weight': self.total_issued_weight,
            'purity_id': purity.id if purity else False,
            'expected_fine': self.total_fine,
            'melting_loss': 0.0,
            'lab_weight': 0.0,
            'refinery_issue_weight': self.total_issued_weight,
            'scrap_bar_fine_weight': 0.0,
            'total_fine_weight': 0.0,
            'balance': 0.0,
            'amount': amount,
            'fine_rate': fine_rate,
        })
        return res

    def action_melting(self):
        # We create the GREEN record once melting is done (RECEIVE/MELTING)
        res = super(OldGoldRefineryIssue, self).action_melting()

        # Create Refinery Margin Report (Green)

        # CREATE REFINERY MARGIN REPORT
        batches = ", ".join(self.batch_ids.mapped('name')) if self.batch_ids else ""

        scrap_bar_fine = self.balance_weight * (self.expected_purity / 100)
        lab_fine = self.lab_sample_weight * (self.lab_purity_percent / 100)
        total_recovered_fine = scrap_bar_fine + lab_fine
        amount = self.output_weight * self.scrap_bar_unit_rate
        fine_rate = amount / total_recovered_fine if total_recovered_fine > 0 else 0.0

        self.env['refinery.margin.report'].create({
            'date': fields.Date.today(),
            'issue_id': self.id,
            'gross_weight': self.total_issued_weight,
            'type': 'receive',  # Red
            'batches':batches,
            'partner_id': self.refinery_partner_id.id, 
            'net_weight': self.output_weight,
            'purity_id': self.expected_purity_id.id,
            'expected_fine': self.total_fine,
            'melting_loss': self.melting_loss,
            'lab_weight': self.lab_sample_weight,
            'refinery_issue_weight': self.balance_weight,
            'scrap_bar_fine_weight': scrap_bar_fine,
            'total_fine_weight': total_recovered_fine,
            'balance': self.total_fine - total_recovered_fine,
            'amount': amount,
            'fine_rate': fine_rate,
        })

        return res

    # def _create_manufacturing_order(self):
    #     """Completely override to use selected output_product_id instead of hardcoded scrap bar."""
    #     MRP = self.env['mrp.production']
    #     product_old_gold = self.env.ref('em_jewellery_management.product_old_gold')
    #     uom_gram = self.env.ref('uom.product_uom_gram')
    #
    #     if not self.line_ids:
    #         return False
    #
    #     mo_location = self.source_location_id
    #     if not mo_location or mo_location.usage != 'internal':
    #         mo_location = self.env.ref('em_jewellery_management.loc_refinery')
    #
    #     move_raw_ids = []
    #     for line in self.line_ids:
    #         move_raw_ids.append((0, 0, {
    #             'product_id': line.product_id.id or product_old_gold.id,
    #             'product_uom': uom_gram.id,
    #             'product_uom_qty': line.issue_weight,
    #             'grams': line.issue_weight,
    #             'purity_id': line.purity_id.id,
    #             'name': f"{line.product_id.name or 'Old Gold'} {line.purity_id.name}",
    #         }))
    #
    #     finished_qty = self.balance_weight or sum(self.line_ids.mapped('issue_weight'))
    #
    #     # Use output_product_id if set, otherwise fallback to em_jewellery_management.product_scrap
    #     target_product = self.output_product_id
    #     if not target_product:
    #         product_scrap = self.env.ref('em_jewellery_management.product_scrap')
    #         target_product = product_scrap if product_scrap._name == 'product.product' else product_scrap.product_variant_id
    #
    #     mo = MRP.create({
    #         'product_id': target_product.id,
    #         'product_uom_id': uom_gram.id,
    #         'product_qty': finished_qty,
    #         'total_grams': finished_qty,
    #         'purity_id': self.expected_purity_id.id or self.line_ids[0].purity_id.id,
    #         'move_raw_ids': move_raw_ids,
    #         'date_start': fields.Datetime.now(),
    #         'location_src_id': mo_location.id,
    #         'location_dest_id': mo_location.id,
    #         'origin': self.name,
    #     })
    #
    #     mo.action_confirm()
    #     self.mo_id = mo.id
    #
    #     batches = self.env['old.gold.batch'].search([('refinery_issue_id', '=', self.id)])
    #     if batches:
    #         batches.write({'mo_id': mo.id})
    #
    #     return mo
