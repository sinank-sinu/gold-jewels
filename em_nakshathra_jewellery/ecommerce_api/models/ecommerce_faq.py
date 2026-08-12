from odoo import models, fields

class EcommerceFAQ(models.Model):
    _name = 'ecommerce.faq'
    _description = 'Ecommerce FAQ'
    _order = 'sequence, id'

    question = fields.Char(string='Question', required=True)
    answer = fields.Text(string='Answer', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
