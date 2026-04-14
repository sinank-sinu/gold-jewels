from odoo import models, fields, api
from odoo.exceptions import UserError

class JewelleryDailyStock(models.Model):
    _name = 'jewellery.daily.stock'
    _description = 'Daily Stock Check'

    branch_id = fields.Many2one('res.branch', string='Branch' )
    product_ids = fields.One2many(
        'jewellery.daily.stock.line',
        'stock_id',
        string='Products'
    )

    def _get_user_branch(self):
        """Optional helper to get default branch for the current user."""
        # Assuming a 'branch_id' field exists on res.users
        return self.env.user.branch_id

    def action_update_stock_lines(self):
        """Update stock lines: reload all products with labels for the branch."""
        for rec in self:
            branch = rec.branch_id or rec._get_user_branch()
            if not branch:
                raise UserError("Branch not found for the logged-in user.")

            # Delete existing lines for this stock record
            rec.product_ids.unlink()

            # Fetch products with labels for this branch
            product_ids = self.env['product.label'].search([
                ('branch_id', '=', branch.id)
            ]).mapped('product_id')

            # Create a new line per product
            for product in product_ids:
                self.env['jewellery.daily.stock.line'].create({
                    'stock_id': rec.id,
                    'branch_id': branch.id,
                    'product_id': product.id,
                })
        return True

    @api.onchange('branch_id')
    def _onchange_branch_auto_load_products(self):
        for rec in self:
            if not rec.branch_id:
                continue

            # Get products that have labels in this branch
            product_ids = self.env['product.label'].search([
                ('branch_id', '=', rec.branch_id.id)
            ]).mapped('product_id')

            # Remove existing lines linked to this stock record
            rec.product_ids.unlink()

            # Create a line per product
            for product in product_ids:
                self.env['jewellery.daily.stock.line'].create({
                    'branch_id': rec.branch_id.id,
                    'product_id': product.id,
                })

    def action_load_products_for_branch(self):
        """Load products with labels for the selected branch."""
        for rec in self:
            if not rec.branch_id:
                raise UserError("Please select a branch first.")

            # Delete existing lines
            rec.product_ids.unlink()

            # Get all unique products with labels in this branch
            products = self.env['product.label'].search([
                ('branch_id', '=', rec.branch_id.id)
            ]).mapped('product_id')

            # Create a stock line for each product
            for product in products:
                self.env['jewellery.daily.stock.line'].create({
                    'stock_id': rec.id,
                    'branch_id': rec.branch_id.id,
                    'product_id': product.id,
                })
        return True


class JewelleryDailyStockLine(models.Model):
    _name = 'jewellery.daily.stock.line'
    _description = 'Daily Stock Check Line'

    stock_id = fields.Many2one('jewellery.daily.stock', string="Stock Check")
    branch_id = fields.Many2one('stock.location', string="Branch")
    product_id = fields.Many2one('product.product', string="Product")

    # System values
    # onhand_qty = fields.Integer(string="On-hand Qty", compute='_compute_system_values', store=True)
    total_weight = fields.Float(string="Total Weight", compute='_compute_system_values', store=True)
    label_count = fields.Integer(string="Label Count", compute='_compute_system_values', store=True)

    # Manual verification
    manual_qty = fields.Integer(string="Manual Qty")
    manual_weight = fields.Float(string="Manual Weight")
    verified = fields.Boolean(string="Verified", compute='_compute_verified', store=True)

    # Branch-wise labels
    label_ids = fields.Many2many('product.label', string="Labels", compute='_compute_label_ids')

    @api.depends('branch_id', 'product_id')
    def _compute_system_values(self):
        for rec in self:
            if not rec.branch_id or not rec.product_id:
                rec.label_count = 0
                rec.onhand_qty = 0
                rec.total_weight = 0.0
                continue

            labels = self.env['product.label'].search([
                ('product_id', '=', rec.product_id.id),
                ('branch_id', '=', rec.branch_id.id),
            ])
            rec.label_count = len(labels)
            # rec.onhand_qty = sum(labels.mapped('sale_gross_weight'))
            rec.total_weight = sum(labels.mapped('sale_gross_weight'))

    @api.depends('manual_qty', 'manual_weight','label_count', 'total_weight')
    def _compute_verified(self):
        for rec in self:
            rec.verified = (rec.manual_qty == rec.label_count) and (rec.manual_weight == rec.total_weight)

    @api.depends('branch_id', 'product_id')
    def _compute_label_ids(self):
        for rec in self:
            if not rec.branch_id or not rec.product_id:
                rec.label_ids = [(6, 0, [])]
                continue

            labels = self.env['product.label'].search([
                ('product_id', '=', rec.product_id.id),
                ('branch_id', '=', rec.branch_id.id),
            ])
            rec.label_ids = [(6, 0, labels.ids)]

    # -----------------------------------------------
    # Onchange branch: auto load products
    # -----------------------------------------------
    @api.onchange('branch_id')
    def _onchange_branch_auto_load_products(self):
        for rec in self:
            if not rec.branch_id:
                continue

            # Get all unique products with labels in this branch
            product_ids = self.env['product.label'].search([
                ('branch_id', '=', rec.branch_id.id),
            ]).mapped('product_id')

            # Remove existing lines linked to this stock record
            rec.stock_id.product_ids.unlink()

            # Create a line per product
            lines = []
            for product in product_ids:
                line = self.env['jewellery.daily.stock.line'].create({
                    'stock_id': rec.stock_id.id,
                    'branch_id': rec.branch_id.id,
                    'product_id': product.id,
                })
                lines.append(line)
