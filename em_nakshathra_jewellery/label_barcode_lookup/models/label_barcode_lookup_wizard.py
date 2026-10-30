# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class LabelBarcodeLookupWizard(models.TransientModel):
    _name = 'label.barcode.lookup.wizard'
    _description = 'Label Barcode Details Lookup Wizard'
    _transient_max_hours = 0.05

    barcode_search = fields.Char(
        string='Scan Barcode',
        help='Scan Barcode',
    )
    search_state = fields.Selection([
        ('initial', 'Ready to Scan'),
        ('found', 'Label Found'),
        ('not_found', 'Not Found'),
    ], default='initial', string='Status', readonly=True)
    status_message = fields.Char(string='Status Message', readonly=True)

    # Matched label
    label_id = fields.Many2one('product.label', string='Found Label', readonly=True)

    # Basic label details (Strictly readonly - temporary inspection only)
    label_name = fields.Char(string='Label Reference', readonly=True)
    barcode = fields.Char(string='Barcode', readonly=True)
    barcode2 = fields.Char(string='Second Barcode', readonly=True)
    image = fields.Binary(string='Ornament Image', readonly=True)

    product_id = fields.Many2one('product.product', string='Ornament Variant', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string='Ornament Product', readonly=True)
    categ_id = fields.Many2one('product.category', string='Category', readonly=True)
    purity_id = fields.Many2one('gold.purity', string='Gold Purity', readonly=True)
    branch_id = fields.Many2one('res.branch', string='Branch', readonly=True)
    current_location_id = fields.Many2one('stock.location', string='Current / Destination Location', readonly=True)
    source_location_id = fields.Many2one('stock.location', string='Source Location', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)

    # Weights breakdown (in grams and carats)
    tag_weight = fields.Float(string='Tag Weight (g)', digits=(16, 3), readonly=True)
    sale_gross_weight = fields.Float(string='Gross Weight (g)', digits=(16, 3), readonly=True)
    sale_net_weight = fields.Float(string='Net Weight (g)', digits=(16, 3), readonly=True)
    sale_fine_weight = fields.Float(string='Fine Weight (g)', digits=(16, 3), readonly=True)
    sale_stone_weight = fields.Float(string='Stone Weight (g)', digits=(16, 3), readonly=True)
    sale_stone_weight_ct = fields.Float(string='Stone Weight (ct)', digits=(12, 4), readonly=True)
    sale_diamond_weight_gm = fields.Float(string='Diamond Weight (g)', digits=(12, 4), readonly=True)
    sale_diamond_weight_ct = fields.Float(string='Diamond Weight (ct)', digits=(12, 4), readonly=True)
    other_weight_g = fields.Float(string='Other Weight (g)', digits=(16, 3), readonly=True)
    other_weight_amount = fields.Float(string='Other Weight Amount', readonly=True)

    # Sale Pricing & Making charges
    sale_price_per_gram = fields.Float(string='Sale Rate / gram', readonly=True)
    sale_metal_rate = fields.Float(string='Sale Metal Amount', readonly=True)
    sale_stone_rate = fields.Float(string='Sale Stone Amount', readonly=True)
    sale_diamond_rate = fields.Float(string='Sale Diamond Amount', readonly=True)
    sale_making_charge_type = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Fixed Amount'),
        ('rate_per_gram', 'Rate per Gram'),
    ], string='Making Charge Type', readonly=True)
    sale_making_charge_value = fields.Float(string='Making Charge Value', readonly=True)
    sale_making_charge_min = fields.Float(string='Making Charge Min', readonly=True)
    sale_making_charge_amount = fields.Float(string='Making Charge Amount', readonly=True)

    # Lifecycle, Status & Documents
    active = fields.Boolean(string='Active', readonly=True)
    is_stocked_in = fields.Boolean(string='Stock Updated', readonly=True)
    stock_status = fields.Char(string='Stock Status', readonly=True)
    age = fields.Integer(string='Age (Days)', readonly=True)

    purchase_id = fields.Many2one('purchase.order', string='Purchase Order', readonly=True)
    job_work_id = fields.Many2one('jewellery.job.work', string='Job Work', readonly=True)
    requisition_id = fields.Many2one('material.purchase.requisition', string='Requisition', readonly=True)

    def _find_label(self, raw_code):
        """Lookup label by barcode, second barcode, reference or label number."""
        if not raw_code:
            return False
        code = raw_code.strip()
        Label = self.env['product.label'].sudo().with_context(active_test=False)
        has_barcode2 = 'barcode2' in Label._fields

        # 1. Barcode match (exact)
        domain = [('barcode', '=', code)]
        if has_barcode2:
            domain = ['|', ('barcode', '=', code), ('barcode2', '=', code)]

        # Check active labels first
        label = Label.search(domain + [('active', '=', True)], limit=1, order='id desc')
        if not label:
            # Check inactive/sold
            label = Label.search(domain, limit=1, order='id desc')

        # Fallback to case-insensitive barcode match
        if not label:
            ilike_barcode = [('barcode', '=ilike', code)]
            if has_barcode2:
                ilike_barcode = ['|', ('barcode', '=ilike', code), ('barcode2', '=ilike', code)]
            label = Label.search(ilike_barcode + [('active', '=', True)], limit=1, order='id desc')
            if not label:
                label = Label.search(ilike_barcode, limit=1, order='id desc')

        # 2. Match by Label Reference (name, case-insensitive)
        if not label:
            name_domain = [('name', '=ilike', code)]
            label = Label.search(name_domain + [('active', '=', True)], limit=1, order='id desc')
            if not label:
                label = Label.search(name_domain, limit=1, order='id desc')

        # 3. Match by Label Number (if field exists)
        if not label and 'label_number' in Label._fields:
            label = Label.search([('label_number', '=', code)], limit=1, order='id desc')

        return label

    def _get_label_values(self, label):
        """Return dict of fields populated from the found product.label record."""
        if not label:
            return {
                'label_id': False,
                'search_state': 'not_found',
                'status_message': _("❌ No label found for barcode '%s'.") % (self.barcode_search or ''),
                'label_name': False,
                'barcode': False,
                'barcode2': False,
                'image': False,
                'product_id': False,
                'product_tmpl_id': False,
                'categ_id': False,
                'purity_id': False,
                'branch_id': False,
                'current_location_id': False,
                'source_location_id': False,
                'company_id': False,
                'tag_weight': 0.0,
                'sale_gross_weight': 0.0,
                'sale_net_weight': 0.0,
                'sale_fine_weight': 0.0,
                'sale_stone_weight': 0.0,
                'sale_stone_weight_ct': 0.0,
                'sale_diamond_weight_gm': 0.0,
                'sale_diamond_weight_ct': 0.0,
                'other_weight_g': 0.0,
                'other_weight_amount': 0.0,
                'sale_price_per_gram': 0.0,
                'sale_metal_rate': 0.0,
                'sale_stone_rate': 0.0,
                'sale_diamond_rate': 0.0,
                'sale_making_charge_type': False,
                'sale_making_charge_value': 0.0,
                'sale_making_charge_min': 0.0,
                'sale_making_charge_amount': 0.0,
                'active': False,
                'is_stocked_in': False,
                'stock_status': _('Not Found'),
                'age': 0,
                'purchase_id': False,
                'job_work_id': False,
                'requisition_id': False,
            }

        # Human-readable status description
        if label.active:
            if getattr(label, 'is_stocked_in', False):
                status_desc = _('In Stock / Transferred')
            else:
                status_desc = _('Active / Available')
        else:
            if label.branch_location_id and label.branch_location_id.usage == 'customer':
                status_desc = _('Sold / Delivered to Customer')
            else:
                status_desc = _('Inactive / Archived')

        # Variant & Template resolution
        prod = label.product_id
        tmpl = label.product_tmpl_id if label.product_tmpl_id else (prod.product_tmpl_id if prod else False)
        categ = tmpl.categ_id if tmpl and tmpl.categ_id else (prod.categ_id if prod and prod.categ_id else False)
        purity = label.purity_id if label.purity_id else getattr(label, 'sale_purity_id', False)

        vals = {
            'label_id': label.id,
            'search_state': 'found',
            'status_message': _("✔ Found Label: %s | Barcode: %s") % (label.name, label.barcode or _("N/A")),
            'label_name': label.name,
            'barcode': label.barcode,
            'barcode2': getattr(label, 'barcode2', False),
            'image': getattr(label, 'image', False),
            'product_id': prod.id if prod else False,
            'product_tmpl_id': tmpl.id if tmpl else False,
            'categ_id': categ.id if categ else False,
            'purity_id': purity.id if purity else False,
            'branch_id': label.branch_id.id if label.branch_id else False,
            'current_location_id': label.branch_location_id.id if label.branch_location_id else False,
            'source_location_id': label.source_location_id.id if label.source_location_id else False,
            'company_id': label.company_id.id if label.company_id else False,
            'tag_weight': getattr(label, 'tag_weight', 0.0) or 0.0,
            'sale_gross_weight': getattr(label, 'sale_gross_weight', 0.0) or 0.0,
            'sale_net_weight': getattr(label, 'sale_net_weight', 0.0) or 0.0,
            'sale_fine_weight': getattr(label, 'sale_fine_weight', 0.0) or 0.0,
            'sale_stone_weight': getattr(label, 'sale_stone_weight', 0.0) or 0.0,
            'sale_stone_weight_ct': getattr(label, 'sale_stone_weight_ct', 0.0) or 0.0,
            'sale_diamond_weight_gm': getattr(label, 'sale_diamond_weight_gm', 0.0) or 0.0,
            'sale_diamond_weight_ct': getattr(label, 'sale_diamond_weight_ct', 0.0) or 0.0,
            'other_weight_g': getattr(label, 'other_weight_g', 0.0) or 0.0,
            'other_weight_amount': getattr(label, 'other_weight_amount', 0.0) or 0.0,
            'sale_price_per_gram': getattr(label, 'sale_price_per_gram', 0.0) or 0.0,
            'sale_metal_rate': getattr(label, 'sale_metal_rate', 0.0) or 0.0,
            'sale_stone_rate': getattr(label, 'sale_stone_rate', 0.0) or 0.0,
            'sale_diamond_rate': getattr(label, 'sale_diamond_rate', 0.0) or 0.0,
            'sale_making_charge_type': getattr(label, 'sale_making_charge_type', False),
            'sale_making_charge_value': getattr(label, 'sale_making_charge_value', 0.0) or 0.0,
            'sale_making_charge_min': getattr(label, 'sale_making_charge_min', 0.0) or 0.0,
            'sale_making_charge_amount': getattr(label, 'sale_making_charge_amount', 0.0) or 0.0,
            'active': bool(label.active),
            'is_stocked_in': bool(getattr(label, 'is_stocked_in', False)),
            'stock_status': status_desc,
            'age': getattr(label, 'age', 0) or 0,
            'purchase_id': label.purchase_id.id if getattr(label, 'purchase_id', False) else False,
            'job_work_id': label.job_work_id.id if getattr(label, 'job_work_id', False) else False,
            'requisition_id': label.requisition_id.id if getattr(label, 'requisition_id', False) else False,
        }
        return vals

    @api.onchange('barcode_search')
    def _onchange_barcode_search(self):
        """Dynamic update when barcode is scanned or modified."""
        if not self.barcode_search:
            vals = self._get_label_values(False)
            vals['search_state'] = 'initial'
            vals['status_message'] = _('Ready to scan. Please scan or enter barcode.')
            self.update(vals)
            return

        label = self._find_label(self.barcode_search)
        vals = self._get_label_values(label)
        self.update(vals)

    def action_search_barcode(self):
        """Action invoked when clicking Search or pressing Enter in barcode input."""
        self.ensure_one()
        raw_code = (self.barcode_search or '').strip()
        if not raw_code:
            vals = self._get_label_values(False)
            vals['barcode_search'] = False
            self.write(vals)
        else:
            label = self._find_label(raw_code)
            vals = self._get_label_values(label)
            # Clear the input so that the searched barcode is removed and placeholder shows
            vals['barcode_search'] = False
            self.write(vals)
            if not label:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Not Found'),
                        'message': _("No label found for barcode '%s'.") % raw_code,
                        'type': 'warning',
                        'sticky': False,
                        'next': {
                            'type': 'ir.actions.act_window',
                            'name': _('Scan Barcode'),
                            'res_model': 'label.barcode.lookup.wizard',
                            'res_id': self.id,
                            'view_mode': 'form',
                            'target': 'new',
                        }
                    }
                }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Scan Barcode'),
            'res_model': 'label.barcode.lookup.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_clear(self):
        """Reset wizard inputs and details to scan another barcode."""
        self.ensure_one()
        vals = self._get_label_values(False)
        vals['barcode_search'] = False
        vals['search_state'] = 'initial'
        vals['status_message'] = _('Ready to scan. Please scan or enter barcode.')
        self.write(vals)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Barcode Label Lookup'),
            'res_model': 'label.barcode.lookup.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_close(self):
        """Close wizard and purge transient record from database."""
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}
