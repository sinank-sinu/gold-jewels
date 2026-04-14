from odoo import models, fields

class JewelleryLabTest(models.Model):
    _name = 'jewellery.lab.test'
    _description = 'Jewellery Lab Purity Test'

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
                                default=lambda self: self.env.user.branch_id.id, )

    job_work_id = fields.Many2one(
        'jewellery.job.work',
        string='Job Work',
        ondelete='cascade',
        required=True
    )

    lab_partner_id = fields.Many2one(
        'res.partner',
        string='Lab'
    )

    sample_ref = fields.Char(string='Sample Reference')

    metal_type = fields.Selection([
        ('gold', 'Gold'),
        ('silver', 'Silver'),
        ('alloy', 'Alloy')
    ], string='Metal Type')

    issued_weight = fields.Float(string='Issued Sample Weight',digits=(16, 3))
    test_date = fields.Date(string='Test Date')

    report_no = fields.Char(string='Lab Report No')

    remarks = fields.Text(string='Remarks')

    state = fields.Selection([
        ('sent', 'Sent to Lab'),
        ('received', 'Result Received')
    ], default='sent', string='Status')
    expected_purity_id = fields.Many2one('gold.purity', string="Expected Purity")
    tested_purity_id = fields.Many2one('gold.purity', string="Tested Purity")
