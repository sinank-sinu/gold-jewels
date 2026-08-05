import base64
import io
from collections import defaultdict
from datetime import datetime, date

from openpyxl import load_workbook

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


def _norm(s):
    return str(s or "").strip().lower().replace("_", " ").replace("-", " ").replace("/", " ")


class JobWorkImportWizard(models.TransientModel):
    _name = "job.work.import.wizard"
    _description = "Import Jewellery Job Work"

    file = fields.Binary(
        string="Excel File",
        required=True,
    )

    filename = fields.Char()

    # Main Import

    def action_import(self):

        self.ensure_one()
        master = self._load_master_data()

        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))

        try:
            workbook = load_workbook(
                filename=io.BytesIO(
                    base64.b64decode(self.file)
                ),
                data_only=True,
            )

        except Exception as e:
            raise ValidationError(str(e))

        sheet = workbook.active

        aliases = {
            "job work number": ["job work no", "job work #", "jobwork number", "jobwork no", "job_work_number", "jw number", "jw no", "job work num", "job work"],
            "job worker": ["worker", "job_worker", "job worker name", "jobworker", "vendor", "vendor name"],
            "order date": ["date", "order_date", "job work date", "jw date"],
            "branch": ["branch name", "branch_id", "company branch"],
        }

        required = [
            "Job Work Number",
            "Job Worker",
            "Order Date",
            "Branch",
        ]

        # Search top 20 rows for header row
        header_row_idx = 1
        found_header = False

        for r_idx, row_cells in enumerate(sheet.iter_rows(max_row=20, values_only=True), start=1):
            row_vals_norm = [_norm(c) for c in row_cells if c is not None]
            matches = 0
            for req in required:
                req_norm = _norm(req)
                req_aliases = aliases.get(req_norm, [])
                if any(a in row_vals_norm for a in [req_norm] + req_aliases):
                    matches += 1
            if matches >= 2:
                header_row_idx = r_idx
                found_header = True
                break

        header_cells = list(sheet.iter_rows(min_row=header_row_idx, max_row=header_row_idx, values_only=True))[0]
        headers = [str(c).strip() if c is not None else "" for c in header_cells]

        header_map = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            header_map[h] = i
            h_norm = _norm(h)
            if h_norm not in header_map:
                header_map[h_norm] = i

            # Map aliases to this index
            for req, req_aliases in aliases.items():
                if h_norm == req or h_norm in req_aliases:
                    for name in [req] + req_aliases:
                        if name not in header_map:
                            header_map[name] = i

        missing = []
        for x in required:
            x_norm = _norm(x)
            if x not in header_map and x_norm not in header_map:
                missing.append(x)

        if missing:
            raise ValidationError(
                _("Missing columns\n\n%s")
                % ("\n".join(missing))
            )

        self._load_master_data()

        grouped_rows = defaultdict(list)

        jw_num_key = "Job Work Number" if "Job Work Number" in header_map else _norm("Job Work Number")

        for row in sheet.iter_rows(
                min_row=header_row_idx + 1,
                values_only=True,
        ):

            if not any(row):
                continue

            number = row[
                header_map[jw_num_key]
            ]

            if not number:
                continue

            grouped_rows[
                str(number).strip()
            ].append(row)

        created = 0
        skipped = 0
        errors = []

        for job_number, rows in grouped_rows.items():

            try:

                existing = self.env[
                    "jewellery.job.work"
                ].search([
                    ("name", "=", job_number)
                ], limit=1)

                if existing:
                    skipped += 1
                    continue

                self._create_complete_job_work(
                    job_number,
                    rows,
                    header_map,
                    master,
                )

                created += 1

            except Exception as e:

                errors.append(
                    "%s : %s"
                    % (
                        job_number,
                        str(e),
                    )
                )

        if errors:

            raise ValidationError(
                _(
                    "Created : %s\n"
                    "Skipped : %s\n\n"
                    "%s"
                ) % (
                    created,
                    skipped,
                    "\n".join(errors),
                )
            )

        return {
            "type": "ir.actions.act_window_close",
        }

    # ==========================================================
    # MASTER DATA
    # ==========================================================

    def _load_master_data(self):

        master = {
            "partners": {
                p.name.strip().lower(): p
                for p in self.env["res.partner"].search([("is_job_worker", "=", True)])
                if p.name
            },

            "branches": {
                b.name.strip().lower(): b
                for b in self.env["res.branch"].search([])
                if b.name
            },

            "products": {
                (p.display_name or p.name).strip().lower(): p
                for p in self.env["product.product"].search([])
                if (p.display_name or p.name)
            },

            "purities": {
                p.name.strip().lower(): p
                for p in self.env["gold.purity"].search([])
                if p.name
            },

            "locations": {
                l.complete_name.strip().lower(): l
                for l in self.env["stock.location"].search([])
                if l.complete_name
            },

            "uoms": {
                u.name.strip().lower(): u
                for u in self.env["uom.uom"].search([])
                if u.name
            },

            "gram_ranges": {
                g.name.strip().lower(): g
                for g in self.env["gold.gram.range"].search([])
                if g.name
            },
        }

        return master

    # ==========================================================
    # LOOKUPS
    # ==========================================================

    def _find_partner(self, value, master):

        if not value:
            return False

        val_clean = str(value).strip()
        val_key = val_clean.lower()

        partner = master["partners"].get(val_key)
        if partner:
            return partner

        # Search res.partner broadly (with or without is_job_worker flag)
        partner = self.env["res.partner"].search([
            '|',
            ('name', '=ilike', val_clean),
            ('ref', '=ilike', val_clean)
        ], limit=1)

        if partner:
            if not partner.is_job_worker:
                partner.write({'is_job_worker': True})
            master["partners"][val_key] = partner
            return partner

        # Create missing job worker partner automatically (same behavior as purchase_label_import)
        partner = self.env["res.partner"].create({
            'name': val_clean,
            'is_job_worker': True,
            'company_id': False,  # Shared across companies
        })
        master["partners"][val_key] = partner
        return partner

    def _find_branch(self, value, master):

        if not value:
            return False

        val_clean = str(value).strip()
        key = val_clean.lower()

        branch = master["branches"].get(key)
        if branch:
            return branch

        branch = self.env["res.branch"].search([('name', '=ilike', val_clean)], limit=1)
        if not branch:
            # Fallback to HEAD OFFICE or first available branch
            branch = self.env["res.branch"].search([('name', 'ilike', 'HEAD OFFICE')], limit=1)
        if not branch:
            branch = self.env["res.branch"].search([], limit=1)

        if branch:
            master["branches"][key] = branch
            return branch

        return False

    def _find_product(self, value, master):

        if not value or str(value).strip() in ("", "False", "None", "0"):
            # Match or create default CHAIN product
            product = self.env["product.product"].search([
                '|',
                ('name', '=ilike', 'CHAIN'),
                ('name', 'ilike', 'CHAIN')
            ], limit=1)
            if not product:
                uom_g = self.env['uom.uom'].search([('name', '=ilike', 'g')], limit=1) or self.env.ref('uom.product_uom_gram', raise_if_not_found=False)
                uom_id = uom_g.id if uom_g else (self.env['uom.uom'].search([], limit=1).id or False)
                tmpl_vals = {'name': 'CHAIN', 'type': 'product'}
                if uom_id:
                    tmpl_vals['uom_id'] = uom_id
                    tmpl_vals['uom_po_id'] = uom_id
                tmpl = self.env["product.template"].create(tmpl_vals)
                product = tmpl.product_variant_ids[0] if tmpl.product_variant_ids else self.env["product.product"].search([('product_tmpl_id', '=', tmpl.id)], limit=1)
            return product

        val_clean = str(value).strip()
        val_key = val_clean.lower()

        product = master["products"].get(val_key)
        if product:
            return product

        # 1. Use name_search (Odoo's built-in variant/template search engine)
        ns_res = self.env["product.product"].name_search(val_clean, limit=1)
        if ns_res:
            product = self.env["product.product"].browse(ns_res[0][0])

        # 2. Search stored fields on product.product
        if not product:
            product = self.env["product.product"].search([
                '|', '|', '|',
                ('name', '=ilike', val_clean),
                ('default_code', '=ilike', val_clean),
                ('product_tmpl_id.name', '=ilike', val_clean),
                ('name', 'ilike', val_clean)
            ], limit=1)

        # 3. Try with base product name (e.g., "CHAIN(22CT)" -> "CHAIN")
        base_name = val_clean.split("(")[0].split("[")[0].strip()
        if not product and base_name:
            ns_res_base = self.env["product.product"].name_search(base_name, limit=1)
            if ns_res_base:
                product = self.env["product.product"].browse(ns_res_base[0][0])

        if not product and base_name:
            product = self.env["product.product"].search([
                '|', '|',
                ('name', '=ilike', base_name),
                ('product_tmpl_id.name', '=ilike', base_name),
                ('name', 'ilike', base_name)
            ], limit=1)

        # 4. Search product.template
        if not product:
            tmpl = self.env["product.template"].search([
                '|', '|',
                ('name', '=ilike', val_clean),
                ('name', '=ilike', base_name),
                ('name', 'ilike', base_name)
            ], limit=1)
            if tmpl:
                if tmpl.product_variant_ids:
                    product = tmpl.product_variant_ids[0]
                else:
                    product = self.env["product.product"].search([('product_tmpl_id', '=', tmpl.id)], limit=1)

        # 5. Create missing product template & variant with the exact name from Excel
        if not product:
            uom_g = self.env['uom.uom'].search([('name', '=ilike', 'g')], limit=1) or self.env.ref('uom.product_uom_gram', raise_if_not_found=False)
            uom_id = uom_g.id if uom_g else (self.env['uom.uom'].search([], limit=1).id or False)
            
            tmpl_vals = {
                'name': val_clean,
                'type': 'product',
            }
            if uom_id:
                tmpl_vals['uom_id'] = uom_id
                tmpl_vals['uom_po_id'] = uom_id

            tmpl = self.env["product.template"].create(tmpl_vals)
            if tmpl.product_variant_ids:
                product = tmpl.product_variant_ids[0]
            else:
                product = self.env["product.product"].search([('product_tmpl_id', '=', tmpl.id)], limit=1)

        if product:
            master["products"][val_key] = product
            return product

        return False

    def _find_purity(self, value, master):

        if value in (None, "", False):
            return False

        name_clean = str(value).strip()
        key = name_clean.lower()

        purity = master["purities"].get(key)
        if purity:
            return purity

        try:
            key_float = str(float(value))
            purity = master["purities"].get(key_float)
            if purity:
                return purity
        except Exception:
            pass

        # Search ORM by ilike
        purity = self.env["gold.purity"].search([('name', '=ilike', name_clean)], limit=1)
        if not purity:
            pct = 100.0
            name_upper = name_clean.upper()
            if '22' in name_upper:
                pct = 91.6
            elif '18' in name_upper:
                pct = 75.0
            elif '24' in name_upper:
                pct = 99.9
            elif '92' in name_upper:
                pct = 92.0
            elif '99' in name_upper or 'SLV' in name_upper or 'SILVER' in name_upper:
                pct = 99.0
            purity = self.env["gold.purity"].create({
                'name': name_clean,
                'percentage': pct,
            })

        master["purities"][key] = purity
        return purity

    def _find_location(self, value, master):

        if not value:
            return False

        val_clean = str(value).strip()
        key = val_clean.lower()

        loc = master["locations"].get(key)
        if loc:
            return loc

        loc = self.env["stock.location"].search([
            '|',
            ('complete_name', '=ilike', val_clean),
            ('name', '=ilike', val_clean)
        ], limit=1)

        if not loc:
            # Fallback to standard internal stock location
            loc = self.env["stock.location"].search([('usage', '=', 'internal')], limit=1)

        if loc:
            master["locations"][key] = loc
            return loc

        return False

    def _find_uom(self, value, master):

        if not value:
            return False

        return master["uoms"].get(
            str(value).strip().lower()
        )

    def _find_gram_range(self, value, master):

        if not value:
            return False

        return master["gram_ranges"].get(
            str(value).strip().lower()
        )

    # ==========================================================
    # HELPERS
    # ==========================================================

    def _get_val(self, row, header_map, keys, default=""):
        if isinstance(keys, str):
            keys = [keys]
        for key in keys:
            if key in header_map:
                idx = header_map[key]
                if idx < len(row):
                    val = row[idx]
                    if val is not None and str(val).strip() != "":
                        return val
            norm_key = _norm(key)
            if norm_key in header_map:
                idx = header_map[norm_key]
                if idx < len(row):
                    val = row[idx]
                    if val is not None and str(val).strip() != "":
                        return val

        # Secondary fuzzy lookup: search for header_map keys containing or contained in norm_key
        for key in keys:
            norm_key = _norm(key)
            if len(norm_key) < 3:
                continue
            for h_k, idx in header_map.items():
                h_k_norm = _norm(h_k)
                if norm_key in h_k_norm or h_k_norm in norm_key:
                    if idx < len(row):
                        val = row[idx]
                        if val is not None and str(val).strip() != "":
                            return val

        return default

    def _float(self, value):

        if value in (None, "", False):
            return 0.0

        if isinstance(value, (int, float)):
            return float(value)

        value = str(value)

        value = value.replace(",", "")

        value = value.strip()

        try:
            return float(value)
        except Exception:
            return 0.0

    def _int(self, value):

        return int(round(self._float(value)))

    def _date(self, value):

        if not value or value in (None, "", False):
            return fields.Date.today()

        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        value = str(value).strip()

        formats = (
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%m/%d/%Y",
            "%Y/%m/%d",
        )

        for fmt in formats:

            try:
                return datetime.strptime(
                    value,
                    fmt,
                ).date()

            except Exception:
                pass

        return fields.Date.today()

    def _state_mapping(self, value):

        if not value:
            return "draft"

        value = str(value).strip().lower()

        mapping = {

            "draft": "draft",

            "issued": "issued",

            "received": "received",

            "done": "done",

        }

        return mapping.get(value, "draft")

    def _create_complete_job_work(
            self,
            job_number,
            rows,
            header_map,
            master,
    ):

        row = rows[0]

        # =====================================================
        # Job Worker
        # =====================================================

        worker_val = self._get_val(row, header_map, ["Job Worker", "JobWorker", "Worker", "Vendor", "Job Worker Name", "Vendor Name"])
        partner = self._find_partner(
            worker_val,
            master,
        )

        if not partner:
            raise ValidationError(
                _("Job Worker '%s' not found.")
                % worker_val
            )

        # =====================================================
        # Branch
        # =====================================================

        branch_val = self._get_val(row, header_map, ["Branch", "Branch Name", "Company Branch", "Branch_id"], default="HEAD OFFICE")
        branch = self._find_branch(
            branch_val,
            master,
        )

        if not branch:
            raise ValidationError(
                _("Branch '%s' not found.")
                % branch_val
            )

        # =====================================================
        # Create Job Work
        # =====================================================

        date_val = self._get_val(row, header_map, ["Order Date", "OrderDate", "Date", "Job Work Date", "JW Date"])
        state_val = self._get_val(row, header_map, ["State", "Status"], default="draft")
        total_fine_wt_val = self._get_val(row, header_map, ["Total Fine Weight", "TotalFineWeight", "Total Fine"], default=0.0)

        job_work_vals = {

            "name": job_number,

            "job_worker_id": partner.id,

            "branch_id": branch.id,

            "order_date": self._date(date_val),

            "state": self._state_mapping(state_val),

            "total_fine_weight": self._float(total_fine_wt_val),

        }

        job_work = self.env[
            "jewellery.job.work"
        ].create(job_work_vals)

        # =====================================================
        # Create Job Work Lines
        # =====================================================

        for line in rows:
            self._create_job_work_line(
                job_work,
                line,
                header_map,
                master,
            )

        # =====================================================
        # Issue Voucher
        # =====================================================

        issue = self._create_issue_voucher(
            job_work,
            row,
            header_map,
            master,
        )

        # =====================================================
        # Issue Voucher Lines
        # =====================================================

        for line in rows:
            self._create_issue_line(
                issue,
                line,
                header_map,
                master,
            )

        # =====================================================
        # Receive Voucher
        # =====================================================

        receive = self._create_receive_voucher(
            job_work,
            issue,
            row,
            header_map,
            master,
        )

        # =====================================================
        # Receive Voucher Lines
        # =====================================================

        for line in rows:
            self._create_receive_line(
                receive,
                issue,
                line,
                header_map,
                master,
            )

        return job_work

    def _get_ptav_ids_for_row(self, product, row, header_map):
        if not product or not product.product_tmpl_id:
            return []

        template = product.product_tmpl_id
        attr_defs = [
            ("Type", ["Job Work Line/Type", "Type", "Product Type"]),
            ("Variety", ["Job Work Line/Variety", "Variety"]),
            ("Design", ["Job Work Line/Design", "Design"]),
            ("Size", ["Job Work Line/Size", "Size"]),
            ("Stone Colour", ["Job Work Line/Stone Colour", "Stone Colour", "Stone Color", "StoneColour"]),
            ("Metal Colour", ["Job Work Line/Metal Colour", "Metal Colour", "Metal Color", "MetalColour"]),
        ]

        ptav_ids = []

        for attr_name, keys in attr_defs:
            raw_val = self._get_val(row, header_map, keys)
            if not raw_val or str(raw_val).strip().lower() in ("", "false", "nan", "0"):
                val_str = "None"
            else:
                val_str = str(raw_val).strip().title()
                if val_str.lower() in ("none", "null", "false"):
                    val_str = "None"

            # Find or create product.attribute
            attribute = self.env['product.attribute'].search([('name', '=ilike', attr_name)], limit=1)
            if not attribute:
                attribute = self.env['product.attribute'].create({'name': attr_name})

            # Find or create product.attribute.value
            value = self.env['product.attribute.value'].search([
                ('attribute_id', '=', attribute.id),
                ('name', '=ilike', val_str)
            ], limit=1)
            if not value:
                value = self.env['product.attribute.value'].create({
                    'attribute_id': attribute.id,
                    'name': val_str
                })

            # Ensure PTAL on template
            ptal = template.attribute_line_ids.filtered(lambda l: l.attribute_id.id == attribute.id)
            if not ptal:
                self.env['product.template.attribute.line'].create({
                    'product_tmpl_id': template.id,
                    'attribute_id': attribute.id,
                    'value_ids': [(6, 0, [value.id])]
                })
            elif value.id not in ptal.value_ids.ids:
                ptal.write({'value_ids': [(4, value.id)]})

            # Get PTAV for this template & value
            ptav = self.env['product.template.attribute.value'].search([
                ('product_tmpl_id', '=', template.id),
                ('attribute_id', '=', attribute.id),
                ('product_attribute_value_id', '=', value.id)
            ], limit=1)

            if ptav:
                ptav_ids.append(ptav.id)

        return ptav_ids

    def _find_or_create_variant(self, product_tmpl, ptav_ids):
        if not product_tmpl:
            return False
        if not ptav_ids:
            return product_tmpl.product_variant_id

        for variant in product_tmpl.product_variant_ids:
            if set(variant.product_template_attribute_value_ids.ids) == set(ptav_ids):
                return variant

        try:
            product_tmpl._create_variant_ids()
        except Exception:
            pass

        for variant in product_tmpl.product_variant_ids:
            if set(variant.product_template_attribute_value_ids.ids) == set(ptav_ids):
                return variant

        # Explicitly create product.product variant for this specific attribute combination
        try:
            var_vals = {
                'product_tmpl_id': product_tmpl.id,
                'product_template_attribute_value_ids': [(6, 0, ptav_ids)]
            }
            new_var = self.env['product.product'].create(var_vals)
            if new_var:
                return new_var
        except Exception:
            pass

        return product_tmpl.product_variant_id or (product_tmpl.product_variant_ids[:1] if product_tmpl.product_variant_ids else product_tmpl.product_variant_id)

    def _create_job_work_line(
            self,
            job_work,
            row,
            header_map,
            master,
    ):

        # Product

        prod_val = self._get_val(row, header_map, [
            "Job Work Line/Product Template", "Job Work Line/Product", "JobWorkLine/ProductTemplate", "Job Work Line/ProductTemplate",
            "Job Work Line/Product/Display Name", "Job Work Line/Product/Name", "Job Work Line/ProductTemplate/Name",
            "JobWorkLine/ProductTemplate/Name", "Job Work Line/Product/id", "Job Work Line/ProductTemplate/id",
            "Product/Display Name", "Product/Name", "Product", "Product Name", "Item", "Item Name",
            "Product Template", "Product Template/Name", "Design Name", "Design", "Ornament",
            "Ornament Name", "Particulars", "Product/Template", "Product/Product Template",
            "Issue Voucher/Order Lines/Product", "Receive Voucher/Order Lines/Product"
        ])
        product = self._find_product(
            prod_val,
            master,
        )

        if not product:
            raise ValidationError(
                _("Product '%s' not found.")
                % prod_val
            )

        ptav_ids = self._get_ptav_ids_for_row(product, row, header_map)
        variant_product = self._find_or_create_variant(product.product_tmpl_id, ptav_ids)

        # Purity

        purity_val = self._get_val(row, header_map, ["Job Work Line/Purity", "JobWorkLine/Purity", "Purity", "Gold Purity", "Karat", "Karatage", "Issue Voucher/Order Lines/Purity", "Receive Voucher/Order Lines/Purity"])
        purity = self._find_purity(
            purity_val,
            master,
        )

        if not purity:
            raise ValidationError(
                _("Purity '%s' not found.")
                % purity_val
            )

        # Gram Range

        range_val = self._get_val(row, header_map, ["Job Work Line/Gram Range", "JobWorkLine/Gram Range", "Gram Range", "GramRange", "Issue Voucher/Order Lines/Gram Range"])
        gram_range = self._find_gram_range(range_val, master) if range_val else False

        qty_val = self._get_val(row, header_map, ["Job Work Line/ Quantity", "Job Work Line/Quantity", "JobWorkLine/Quantity", "Quantity", "Qty", "Oder Qty of Ornaments", "Net Weight", "Net Weight (g)", "Net Weight(g)", "Weight"], default=0.0)
        stone_wt_val = self._get_val(row, header_map, ["Job Work Line/Stone/Diamond Weight (g)", "JobWorkLine/Stone/DiamondWeight(g)", "Stone Weight", "Stone Weight (g)", "Stone Weight(g)", "Diamond Weight", "Diamond Weight (g)"], default=0.0)
        net_wt_val = self._get_val(row, header_map, ["Job Work Line/Net Weight (g)", "Job Work Line/Net Weight", "JobWorkLine/Net Weight (g)", "Net Weight", "Net Weight (g)", "Net Weight(g)", "Job Work Line/ Quantity", "Quantity", "Qty"], default=qty_val)
        gross_wt_val = self._get_val(row, header_map, ["Job Work Line/Gross Weight (g)", "Job Work Line/Gross Weight", "Gross Weight (g)", "Gross Weight", "Gross Wt"], default=net_wt_val)
        mc_pct_val = self._get_val(row, header_map, ["Receive Voucher/MC%", "ReceiveVoucher/MC%", "MC%", "Job Work Line/Purchase Making Charge", "Purchase Making Charge", "MC Percent"], default=0.0)
        pcs_val = self._get_val(row, header_map, ["Job Work Line/No. of Pieces", "JobWorkLine/No.ofPieces", "No. of Pieces", "No.ofPieces", "No of Pieces", "Pieces", "Pcs"], default=1)

        final_net = self._float(net_wt_val) if self._float(net_wt_val) > 0 else self._float(qty_val)
        final_gross = self._float(gross_wt_val) if self._float(gross_wt_val) > 0 else final_net

        # Create Line

        vals = {

            "job_work_id": job_work.id,

            "product_id": variant_product.id,

            "product_template_id": product.product_tmpl_id.id,

            "product_template_attribute_value_ids": [(6, 0, ptav_ids)],

            "purity_id": purity.id,

            "quantity": final_net,

            "stone_weight": self._float(stone_wt_val),

            "net_weight": final_net,

            "gross_weight": final_gross,

            "purchase_making_charge_value": self._float(mc_pct_val),

            "purchase_price_per_gram": 0.0,

            "no_of_pieces": self._int(pcs_val),

            "gram_range_id": gram_range.id if gram_range else False,

        }

        self.env[
            "jewellery.job.work.line"
        ].create(vals)

    def _create_issue_voucher(
            self,
            job_work,
            row,
            header_map,
            master,
    ):

        src_loc_val = self._get_val(row, header_map, ["Issue Voucher/Source Location", "Issue Source Location", "Source Location", "From Location"], default="Main Stock")
        source_location = self._find_location(src_loc_val, master)

        if not source_location:
            raise ValidationError(
                _("Source Location '%s' not found.")
                % src_loc_val
            )

        vnd_loc_val = self._get_val(row, header_map, ["Issue Voucher/Vendor Location", "Issue Vendor Location", "Vendor Location", "Received Location", "To Location"], default="Vendor Location")
        vendor_location = self._find_location(vnd_loc_val, master)

        if not vendor_location:
            raise ValidationError(
                _("Vendor Location '%s' not found.")
                % vnd_loc_val
            )

        issue_num = self._get_val(row, header_map, ["Issue Voucher/Issue Voucher Number", "Issue Voucher Number", "Issue Voucher No", "Issue No", "Issue Number"], default=f"ISS-{job_work.name}")
        fine_wt_val = self._get_val(row, header_map, ["Issue Voucher/Total Fine Weight", "Total Fine Weight", "Fine Weight"], default=0.0)

        vals = {

            "name": issue_num,

            "job_work_id": job_work.id,

            "job_worker_id": job_work.job_worker_id.id,

            "branch_id": job_work.branch_id.id,

            "order_date": job_work.order_date,

            "source_location_id": source_location.id,

            "received_location_id": vendor_location.id,

            "total_fine_weight": self._float(fine_wt_val),

            "state": "draft",

        }

        issue = self.env[
            "jewellery.issue.voucher"
        ].create(vals)

        return issue

    def _create_issue_line(
            self,
            issue,
            row,
            header_map,
            master,
    ):

        prod_val = self._get_val(row, header_map, [
            "Job Work Line/Product Template", "Issue Voucher/Order Lines/Product", "Job Work Line/Product", "JobWorkLine/ProductTemplate",
            "Product", "Product Name", "Item", "Item Name", "Product Template", "Design Name",
            "Design", "Ornament", "Ornament Name", "Particulars", "Product/Template"
        ])
        product = self._find_product(prod_val, master)

        if not product:
            raise ValidationError(
                _("Product '%s' not found.")
                % prod_val
            )

        purity_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/Purity", "Job Work Line/Purity", "JobWorkLine/Purity", "Purity", "Gold Purity", "Karat"])
        purity = self._find_purity(purity_val, master)

        if not purity:
            raise ValidationError(
                _("Purity '%s' not found.")
                % purity_val
            )

        uom_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/UoM", "UoM", "Unit of Measure", "UOM"], default="g")
        uom = self._find_uom(uom_val, master)

        if not uom:
            uom = product.uom_id

        range_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/Gram Range", "Job Work Line/Gram Range", "Gram Range"])
        gram_range = self._find_gram_range(range_val, master) if range_val else False

        issued_wt_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/Issued Weight (g)", "Issued Weight", "Issued Weight (g)", "Net Weight", "Quantity", "Qty"], default=0.0)
        stone_wt_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/Stone Weight (g)", "Stone Weight", "Stone Weight (g)"], default=0.0)
        dia_wt_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/Diamond Weight (g)", "Diamond Weight", "Diamond Weight (g)"], default=0.0)
        rate_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/Purchase fine Rate / gram", "Purchase fine Rate / gram", "Fine Rate"], default=0.0)
        pcs_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/No. of Pieces", "No. of Pieces", "No.ofPieces", "Pieces", "Pcs"], default=1)
        fine_gms_price_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/Fine GMS Price", "Fine GMS Price"], default=0.0)
        fine_amt_val = self._get_val(row, header_map, ["Issue Voucher/Order Lines/Fine Amount", "Fine Amount"], default=0.0)

        ptav_ids = self._get_ptav_ids_for_row(product, row, header_map)
        variant_product = self._find_or_create_variant(product.product_tmpl_id, ptav_ids)

        vals = {

            "voucher_id": issue.id,

            "product_id": variant_product.id,

            "product_template_id": product.product_tmpl_id.id,

            "product_template_attribute_value_ids": [(6, 0, ptav_ids)],

            "uom_id": uom.id if uom else False,

            "purity_id": purity.id,

            "issued_weight": self._float(issued_wt_val),

            "stone_weight": self._float(stone_wt_val),

            "diamond_weight": self._float(dia_wt_val),

            "purchase_price_per_gram": self._float(rate_val),

            "purchase_making_charge_value": 0.0,

            "no_of_pieces": self._int(pcs_val),

            "gram_range_id": gram_range.id if gram_range else False,

            "fine_gms_price": self._float(fine_gms_price_val),

            "fine_issue_amount": self._float(fine_amt_val),

        }

        self.env[
            "jewellery.issue.voucher.line"
        ].create(vals)

    def _create_receive_voucher(
            self,
            job_work,
            issue,
            row,
            header_map,
            master,
    ):

        src_loc_val = self._get_val(row, header_map, ["Receive Voucher/Source Location", "Receive Source Location", "Source Location"], default="Vendor Location")
        source_location = self._find_location(src_loc_val, master)

        if not source_location:
            raise ValidationError(
                _("Receive Source Location '%s' not found.")
                % src_loc_val
            )

        dest_loc_val = self._get_val(row, header_map, ["Receive Voucher/Received Location", "Receive Destination", "Received Location", "To Location"], default="Main Stock")
        destination = self._find_location(dest_loc_val, master)

        if not destination:
            raise ValidationError(
                _("Receive Destination '%s' not found.")
                % dest_loc_val
            )

        rec_num = self._get_val(row, header_map, ["Receive Voucher/Receive Voucher Number", "Receive Voucher Number", "Receive Voucher No", "Receive No"], default=f"REC-{job_work.name}")
        date_val = self._get_val(row, header_map, ["Receive Voucher/Order Date", "Order Date", "Date"], default=job_work.order_date)
        fine_rate_val = self._get_val(row, header_map, ["Receive Voucher/Fine Rate (g)", "Fine Rate", "Fine Rate (g)"], default=0.0)
        job_type_val = self._get_val(row, header_map, ["Receive Voucher/Job Type Selection", "Job Type Selection", "Job Type"], default="gold_only")
        mc_type_val = self._get_val(row, header_map, ["Receive Voucher/MC Type", "MC Type", "Making Charge Type"], default="percent")
        mc_pct_val = self._get_val(row, header_map, ["Receive Voucher/MC%", "ReceiveVoucher/MC%", "MC%", "MC Percent"], default=0.0)
        rate_val = self._get_val(row, header_map, ["Receive Voucher/Rate(g)", "Rate", "Rate(g)"], default=0.0)
        wastage_val = self._get_val(row, header_map, ["Receive Voucher/Wastage Weight", "Wastage Weight", "Wastage"], default=0.0)

        vals = {

            "name": rec_num,

            "job_work_id": job_work.id,

            "job_worker_id": job_work.job_worker_id.id,

            "issue_voucher_id": issue.id,

            "branch_id": job_work.branch_id.id,

            "order_date": self._date(date_val),

            "source_location_id": source_location.id,

            "received_location_id": destination.id,

            "fine_rate": self._float(fine_rate_val),

            "job_type_selection": (
                "gold_alloy"
                if str(job_type_val).strip().lower() == "gold + alloy"
                else "gold_only"
            ),

            "making_charge_type": {
                "percentage": "percent",
                "amount": "amount",
                "rate per gram": "rate_per_gram",
            }.get(
                str(mc_type_val).strip().lower(),
                "percent",
            ),

            "mc_percent": self._float(mc_pct_val),

            "rate_value": self._float(rate_val),

            "wastage_weight": self._float(wastage_val),

            "state": "done",

        }

        receive = self.env[
            "jewellery.receive.voucher"
        ].create(vals)

        return receive

    def _create_receive_line(
            self,
            receive,
            issue,
            row,
            header_map,
            master,
    ):

        # Product

        prod_val = self._get_val(row, header_map, [
            "Job Work Line/Product Template", "Receive Voucher/Order Lines/Product", "Job Work Line/Product", "Product",
            "Product Name", "Item", "Item Name", "Product Template", "Design Name",
            "Design", "Ornament", "Ornament Name", "Particulars", "Product/Template"
        ])
        product = self._find_product(prod_val, master)

        if not product:
            raise ValidationError(
                _("Receive Product '%s' not found.")
                % prod_val
            )

        # Purity

        purity_val = self._get_val(row, header_map, ["Receive Voucher/Order Lines/Purity", "Job Work Line/Purity", "Purity"])
        purity = self._find_purity(purity_val, master)

        if not purity:
            raise ValidationError(
                _("Purity '%s' not found.")
                % purity_val
            )

        # UOM

        uom_val = self._get_val(row, header_map, ["Receive Voucher/Order Lines/UoM", "UoM", "UOM"], default="g")
        uom = self._find_uom(uom_val, master)

        if not uom:
            uom = product.uom_id

        # Find Issue Line

        issue_line = issue.line_ids.filtered(
            lambda l: l.product_id.id == product.id
        )[:1]

        gross_wt_val = self._get_val(row, header_map, ["Receive Voucher/Order Lines/Gross Weight (g)", "Gross Weight", "Gross Weight (g)"], default=0.0)
        stone_wt_val = self._get_val(row, header_map, ["Receive Voucher/Order Lines/Stone Weight (g)", "Stone Weight", "Stone Weight (g)"], default=0.0)
        dia_wt_val = self._get_val(row, header_map, ["Receive Voucher/Order Lines/Diamond Weight (g)", "Diamond Weight", "Diamond Weight (g)"], default=0.0)
        mc_val = self._get_val(row, header_map, ["Receive Voucher/Order Lines/Purchase Making Charge", "Purchase Making Charge", "MC Value"], default=0.0)
        fine_price_val = self._get_val(row, header_map, ["Receive Voucher/Order Lines/Fine GMS Price", "Fine GMS Price"], default=0.0)
        fine_amt_val = self._get_val(row, header_map, ["Receive Voucher/Order Lines/Fine Issue Amount", "Fine Issue Amount", "Fine Amount"], default=0.0)

        ptav_ids = self._get_ptav_ids_for_row(product, row, header_map)
        variant_product = self._find_or_create_variant(product.product_tmpl_id, ptav_ids)

        vals = {

            "voucher_id": receive.id,

            "issue_voucher_line_id": issue_line.id if issue_line else False,

            "product_id": variant_product.id,

            "product_template_id": product.product_tmpl_id.id,

            "product_template_attribute_value_ids": [(6, 0, ptav_ids)],

            "uom_id": uom.id if uom else False,

            "purity_id": purity.id,

            "gross_weight": self._float(gross_wt_val),

            "stone_weight": self._float(stone_wt_val),

            "diamond_weight": self._float(dia_wt_val),

            "purchase_making_charge_value": self._float(mc_val),

            "fine_gms_price": self._float(fine_price_val),

            "fine_issue_amount": self._float(fine_amt_val),

        }

        self.env[
            "jewellery.receive.voucher.line"
        ].create(vals)