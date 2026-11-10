# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    eway_bill_number = fields.Char(string="E-Way Bill Number", tracking=True)
    vehicle_number = fields.Char(string="Vehicle Number", tracking=True)
    transporter_name = fields.Char(string="Transporter / Custodian Staff", tracking=True)
    transfer_batch_no = fields.Char(string="Transfer Batch No.", tracking=True)
    challan_notes = fields.Text(string="Challan Remarks")

    def action_print_delivery_challan(self):
        self.ensure_one()
        return self.env.ref(
            'em_jewellery_internal_transfer_challan.action_report_stock_transfer_delivery_challan'
        ).report_action(self)

    def _get_delivery_challan_data(self):
        """Compile Stock Transfer Delivery Challan data structure (without variants, rates, or taxes)."""
        self.ensure_one()

        # 1. Consignor Branch & Company
        consignor_branch = self.location_id.branch_id or getattr(self, 'branch_id', False)
        consignor_company = consignor_branch.company_id if (consignor_branch and consignor_branch.company_id) else self.company_id

        # 2. Consignee Branch & Company
        consignee_branch = self.location_dest_id.branch_id
        if not consignee_branch and hasattr(self, 'dest_branch_id') and self.dest_branch_id:
            consignee_branch = self.dest_branch_id
        consignee_company = consignee_branch.company_id if (consignee_branch and consignee_branch.company_id) else (
            self.location_dest_id.company_id or self.company_id
        )

        def _format_address(record):
            if not record:
                return ""
            parts = []
            if getattr(record, 'street', False):
                parts.append(record.street.strip())
            if getattr(record, 'street2', False):
                parts.append(record.street2.strip())
            if getattr(record, 'city', False):
                parts.append(record.city.strip())
            state = getattr(record, 'state_id', False)
            if state and getattr(state, 'name', False):
                parts.append(state.name.strip())
            country = getattr(record, 'country_id', False)
            if country and getattr(country, 'name', False) and country.name.lower() != 'india':
                parts.append(country.name.strip())
            zip_code = getattr(record, 'zip', False)
            if zip_code:
                parts.append(str(zip_code).strip())
            return ", ".join([p for p in parts if p])

        consignor_addr = _format_address(consignor_branch) or _format_address(consignor_company.partner_id)
        consignee_addr = _format_address(consignee_branch) or _format_address(consignee_company.partner_id)

        consignor = {
            'company_name': consignor_company.name or 'Nakshathra Gold And Diamond LLP',
            'branch_name': consignor_branch.name if consignor_branch else (self.location_id.name or 'Main Branch'),
            'address': consignor_addr,
            'gstin': consignor_company.vat or (consignor_branch.company_id.vat if consignor_branch else '') or 'N/A',
            'state_name': consignor_company.state_id.name if consignor_company.state_id else '',
            'state_code': consignor_company.state_id.code if consignor_company.state_id else '',
        }

        consignee = {
            'company_name': consignee_company.name or consignor_company.name or 'Nakshathra Gold And Diamond LLP',
            'branch_name': consignee_branch.name if consignee_branch else (self.location_dest_id.name or 'Main Branch'),
            'address': consignee_addr,
            'gstin': consignee_company.vat or (consignee_branch.company_id.vat if consignee_branch else '') or consignor['gstin'],
            'state_name': consignee_company.state_id.name if consignee_company.state_id else '',
            'state_code': consignee_company.state_id.code if consignee_company.state_id else '',
        }

        transfer_date = self.date_done.date() if self.date_done else (
            self.scheduled_date.date() if self.scheduled_date else fields.Date.today()
        )

        meta = {
            'challan_no': self.name or '',
            'date': transfer_date,
            'transfer_type': 'BRANCH TRANSFER',
            'batch_no': self.transfer_batch_no or (self.batch_id.name if hasattr(self, 'batch_id') and self.batch_id else (self.origin or '-')),
            'eway_bill': self.eway_bill_number or '-',
            'vehicle_no': self.vehicle_number or '-',
            'transporter': self.transporter_name or '-',
        }

        # Clean Product Name Extractor (Extract base template name without variant attributes)
        def _get_clean_product_name(product):
            name = product.product_tmpl_id.name if (product and product.product_tmpl_id) else (product.name if product else '')
            name = (name or '').strip()
            # Strip variant attribute combinations like ' ( Layer, None, Stone, None, Multi Colour, None)'
            # Preserves 'BRACELET(18CT)' because '(18CT)' has no preceding space, whereas Odoo attributes start with ' ('
            if ' (' in name and name.endswith(')'):
                name = name[:name.rfind(' (')].strip()
            return name or (product.name if product else 'Unnamed Product')

        grouped = {}
        detailed_lines = []
        moves = self.move_ids_without_package.filtered(lambda m: m.state != 'cancel')
        if not moves:
            moves = self.move_ids.filtered(lambda m: m.state != 'cancel')

        for move in moves:
            lbl = getattr(move, 'label_id', False)
            product = move.product_id

            gross_wt = 0.0
            if lbl:
                gross_wt = getattr(lbl, 'sale_gross_weight', 0.0) or getattr(lbl, 'purchase_gross_weight', 0.0) or getattr(move, 'label_weight', 0.0) or move.quantity or move.product_uom_qty
            else:
                gross_wt = getattr(move, 'label_weight', 0.0) or move.quantity or move.product_uom_qty or 0.0

            net_wt = 0.0
            if lbl:
                net_wt = getattr(lbl, 'sale_net_weight', 0.0) or getattr(lbl, 'purchase_net_weight', 0.0) or gross_wt
            else:
                net_wt = gross_wt

            pieces = getattr(move, 'pieces', 0) if getattr(move, 'pieces', 0) else (1 if lbl else int(move.quantity or move.product_uom_qty or 1))

            clean_name = _get_clean_product_name(product)

            if clean_name not in grouped:
                grouped[clean_name] = {
                    'product_name': clean_name,
                    'pieces': 0,
                    'gross_weight': 0.0,
                    'net_weight': 0.0,
                }
            g = grouped[clean_name]
            g['pieces'] += pieces
            g['gross_weight'] = round(g['gross_weight'] + gross_wt, 3)
            g['net_weight'] = round(g['net_weight'] + net_wt, 3)

            purity = getattr(move, 'purity_id', False) or (getattr(lbl, 'purity_id', False) or getattr(lbl, 'sale_purity_id', False) if lbl else False)
            detailed_lines.append({
                'label_name': lbl.name if lbl else (move.name or product.name),
                'barcode': lbl.barcode if (lbl and lbl.barcode) else (product.barcode or '-'),
                'product_name': clean_name,
                'purity': purity.name if purity else '-',
                'gross_weight': round(gross_wt, 3),
                'net_weight': round(net_wt, 3),
            })

        summary_lines = []
        sl_no = 1
        for prod_name, g in grouped.items():
            summary_lines.append({
                'sl_no': sl_no,
                'product_name': g['product_name'],
                'pieces': g['pieces'],
                'gross_weight': g['gross_weight'],
                'net_weight': g['net_weight'],
            })
            sl_no += 1

        total_pieces = sum(l['pieces'] for l in summary_lines)
        total_gross_weight = round(sum(l['gross_weight'] for l in summary_lines), 3)
        total_net_weight = round(sum(l['net_weight'] for l in summary_lines), 3)

        totals = {
            'total_pieces': total_pieces,
            'total_gross_weight': total_gross_weight,
            'total_net_weight': total_net_weight,
        }

        return {
            'consignor': consignor,
            'consignee': consignee,
            'meta': meta,
            'summary_lines': summary_lines,
            'detailed_lines': detailed_lines,
            'totals': totals,
            'notes': self.challan_notes or getattr(self, 'note', '') or '',
            'prepared_by': self.user_id.name or self.env.user.name or 'Staff',
        }

