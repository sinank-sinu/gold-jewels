from odoo import models, fields, api, _
import math

from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # =========================
    # SALES JEWELLERY DETAILS
    # =========================
    sale_purity_id = fields.Many2one('gold.purity', string="Sale Purity")
    sale_price_per_gram = fields.Float(string="Sale Rate / gram")
    is_bullion_product = fields.Boolean(string="Bullion Product")
    is_old_gold = fields.Boolean(string="Is Old Gold")
    is_diamond_og = fields.Boolean(string="Is Diamond OG")
    is_purchase_expense = fields.Boolean(
        string="Is Purchase Expense",
        compute="_compute_is_purchase_expense",
        search="_search_is_purchase_expense",
    )
    is_scheme_product = fields.Boolean(string="Scheme Product")
    purity_id = fields.Many2one(
        'gold.purity',
        string="Purity"
    )
    label_count = fields.Integer(
        string="Labels",
        compute="_compute_label_count"
    )

    @api.depends('detailed_type')
    def _compute_is_purchase_expense(self):
        for tmpl in self:
            tmpl.is_purchase_expense = tmpl.detailed_type in ('consu', 'service')

    def _search_is_purchase_expense(self, operator, value):
        if operator not in ('=', '!='):
            return []
        is_true = bool(value) if operator == '=' else not bool(value)
        if is_true:
            return [('detailed_type', 'in', ['consu', 'service'])]
        return [('detailed_type', 'not in', ['consu', 'service'])]


    def _compute_label_count(self):
        Label = self.env['product.label']
        for template in self:
            template.label_count = Label.search_count([
                ('product_tmpl_id', '=', template.id)
            ])

    def action_view_labels(self):
        self.ensure_one()
        return {
            'name': 'Product Labels',
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('product_tmpl_id', '=', self.id)],
            'context': {
                'default_product_tmpl_id': self.id,
            },
        }

    # @api.constrains('is_scheme_product')
    # def _check_single_scheme_product(self):
    #     for product in self:
    #         if product.is_scheme_product:
    #             count = self.search_count([
    #                 ('is_scheme_product', '=', True),
    #                 ('id', '!=', product.id),
    #             ])
    #             if count:
    #                 raise ValidationError(
    #                     _("Only ONE product can be marked as Scheme Product.")
    #                 )


class Product(models.Model):
    _inherit = 'product.product'

    is_bullion_product = fields.Boolean(
        related='product_tmpl_id.is_bullion_product',
        string="Bullion Product",
        store=True,
        readonly=False,
    )
    is_old_gold = fields.Boolean(
        related='product_tmpl_id.is_old_gold',
        string="Is Old Gold",
        store=True,
        readonly=False,
    )
    is_diamond_og = fields.Boolean(
        related='product_tmpl_id.is_diamond_og',
        string="Is Diamond OG",
        store=True,
        readonly=False,
    )

    sale_purity_id = fields.Many2one(
        'gold.purity',
        string="Sale Purity"
    )
    purity_id = fields.Many2one(
        related='product_tmpl_id.purity_id',
        string='Purity',
        store=True,
        readonly=False,
    )
    
    sale_price_per_gram = fields.Float(
        string="Sale Rate / gram"
    )

    label_count = fields.Integer(
        string="Labels",
        compute="_compute_label_count"
    )

    def _compute_label_count(self):
        Label = self.env['product.label']
        for product in self:
            product.label_count = Label.search_count([
                ('product_id', '=', product.id)
            ])

    def action_view_labels(self):
        self.ensure_one()
        return {
            'name': 'Product Labels',
            'type': 'ir.actions.act_window',
            'res_model': 'product.label',
            'view_mode': 'tree,form',
            'domain': [('product_id', '=', self.id)],
            'context': {
                'default_product_id': self.id,
            },
        }

    # @api.constrains('is_scheme_product')
    # def _check_single_scheme_product(self):
    #     for product in self:
    #         if product.is_scheme_product:
    #             count = self.search_count([
    #                 ('is_scheme_product', '=', True),
    #                 ('id', '!=', product.id),
    #             ])
    #             if count:
    #                 raise ValidationError(
    #                     _("Only ONE product can be marked as Scheme Product.")
    #                 )






