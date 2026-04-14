from odoo import models, fields

class LabPurity(models.Model):
    _name = 'lab.purity'
    _description = 'Lab Purity'

    name = fields.Char(required=True)
    percentage = fields.Float(string="Purity %")
    active = fields.Boolean(default=True)
    picking_id = fields.Many2one('stock.picking', string="Picking", readonly=True)
    refinery_issue_id = fields.Many2one('old.gold.refinery.issue', string="Refinery Issue", readonly=True)
