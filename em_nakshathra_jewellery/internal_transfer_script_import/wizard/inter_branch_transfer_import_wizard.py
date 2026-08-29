import base64
import logging
import os
import tempfile
from io import BytesIO
import openpyxl
import pytz

from datetime import datetime, date

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InterBranchTransferImportWizard(models.TransientModel):
    _name = "inter.branch.transfer.import.wizard"
    _description = "Inter-Branch Stock Transfer Import Wizard"

    file = fields.Binary(
        string="Excel File",
        required=True,
        help="Upload the Excel file containing Inter-Branch Transfers."
    )
    filename = fields.Char(
        string="Filename"
    )

    def _parse_datetime(self, val):
        if not val:
            return False
        dt = False
        if isinstance(val, datetime):
            dt = val
        elif isinstance(val, date):
            dt = datetime.combine(val, datetime.min.time())
        else:
            val_str = str(val).strip()
            formats = [
                '%Y-%m-%d %H:%M:%S',
                '%m/%d/%Y %H:%M:%S',
                '%d/%m/%Y %H:%M:%S',
                '%Y-%m-%d %H:%M',
                '%m/%d/%Y %H:%M',
                '%d/%m/%Y %H:%M',
                '%Y-%m-%d',
                '%m/%d/%Y',
                '%d/%m/%Y',
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(val_str, fmt)
                    break
                except ValueError:
                    pass

        if dt:
            user_tz_name = self.env.user.tz or 'Asia/Kolkata'
            try:
                user_tz = pytz.timezone(user_tz_name)
                local_dt = user_tz.localize(dt)
                return local_dt.astimezone(pytz.utc).replace(tzinfo=None)
            except Exception:
                return dt
        return False

    def _get_float(self, val):
        try:
            if val is None or str(val).strip() == '':
                return 0.0
            return float(str(val).replace(',', ''))
        except Exception:
            return 0.0

    def action_import(self):
        self.ensure_one()

        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))

        file_data = base64.b64decode(self.file)
        
        import tempfile
        import os
        import openpyxl
        import logging
        import csv
        import io
        
        _logger = logging.getLogger(__name__)
        
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx', prefix='inter_branch_wiz_') as tmp:
                tmp_path = tmp.name
                tmp.write(file_data)
            
            workbook = openpyxl.load_workbook(tmp_path, read_only=True, data_only=True)
            sheet = workbook.active
            
            headers = [str(cell.value).strip() if cell.value else "" for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
            header_map = {header: index for index, header in enumerate(headers)}
            
            transferred_count = 0
            updated_count = 0
            skipped_count = 0
            skipped_details = []
            process_logs = []
            
            process_logs.append("Reading Excel file...")
            _logger.info("Reading Excel file...")
            
            # Lists for bulk ORM creation
            valid_transfers = []
            virtual_locations = {}
            
            for row_no, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                if not any(row):
                    continue
                    
                row_dict = dict(zip(headers, row))
                
                label_name = str(row_dict.get("Label Name") or "").strip()
                raw_barcode = row_dict.get("Barcode")
                
                normalized_barcode = False
                if raw_barcode is not None and str(raw_barcode).strip():
                    if isinstance(raw_barcode, float) and raw_barcode.is_integer():
                        normalized_barcode = str(int(raw_barcode))
                    elif isinstance(raw_barcode, str) and raw_barcode.endswith('.0'):
                        normalized_barcode = raw_barcode[:-2]
                    else:
                        normalized_barcode = str(raw_barcode).strip()
                        
                if not label_name and not normalized_barcode:
                    skipped_count += 1
                    skipped_details.append({'row': row_no, 'label': '', 'reason': 'Missing Label Name and Barcode'})
                    continue
                    
                try:
                    # 1. Determine Company from Excel
                    comp_name = str(row_dict.get("Company") or "").strip()
                    company = self.env['res.company']
                    if comp_name:
                        company = self.env['res.company'].search([('name', '=ilike', comp_name)], limit=1)

                    # 1b. Fetch labels first to use as fallback for company if Excel company is missing
                    labels = self.env['product.label']
                    if label_name:
                        labels = self.env['product.label'].search([('name', '=', label_name)])
                    if not labels and normalized_barcode:
                        labels = self.env['product.label'].search([('barcode', '=', normalized_barcode)])
                        
                    if not company and labels:
                        company = labels[0].company_id
                    if not company:
                        company = self.env.company

                    if not labels:
                        skipped_count += 1
                        skipped_details.append({'row': row_no, 'label': label_name or normalized_barcode, 'reason': 'Label not found in system'})
                        continue
                        
                    # 2. Source Location (Company Aware)
                    src_name = str(row_dict.get("Source Location") or "").strip()
                    src_loc = self.env['stock.location'].search([
                        ('complete_name', '=', src_name),
                        '|', ('company_id', '=', company.id), ('company_id', '=', False)
                    ], limit=1)
                    if not src_loc:
                        src_loc = self.env['stock.location'].search([
                            ('name', '=', src_name),
                            '|', ('company_id', '=', company.id), ('company_id', '=', False)
                        ], limit=1)
                    if not src_loc:
                        skipped_count += 1
                        skipped_details.append({'row': row_no, 'label': label_name or normalized_barcode, 'reason': f"Source location '{src_name}' not found for company {company.name}"})
                        continue

                    # 3. Destination Location (Company Aware)
                    dest_name = str(row_dict.get("Destination Location") or "").strip()
                    dest_loc = self.env['stock.location'].search([
                        ('complete_name', '=', dest_name),
                        '|', ('company_id', '=', company.id), ('company_id', '=', False)
                    ], limit=1)
                    if not dest_loc:
                        dest_loc = self.env['stock.location'].search([
                            ('name', '=', dest_name),
                            '|', ('company_id', '=', company.id), ('company_id', '=', False)
                        ], limit=1)
                    if not dest_loc:
                        skipped_count += 1
                        skipped_details.append({'row': row_no, 'label': label_name or normalized_barcode, 'reason': f"Destination location '{dest_name}' not found for company {company.name}"})
                        continue

                    # 4. Resolve duplicated labels (now that we have locations and company)
                    if len(labels) > 1:
                        # Match by company and exact source location (branch_location_id)
                        matched_labels = labels.filtered(lambda l: l.company_id.id == company.id and l.branch_location_id.id == src_loc.id)
                        
                        if not matched_labels:
                            # Match by company and exact destination location (branch_location_id)
                            matched_labels = labels.filtered(lambda l: l.company_id.id == company.id and l.branch_location_id.id == dest_loc.id)
                            
                        if not matched_labels:
                            # Match by company and source_location_id
                            matched_labels = labels.filtered(lambda l: l.company_id.id == company.id and l.source_location_id.id == src_loc.id)
                            
                        if not matched_labels:
                            # Fallback to company only
                            matched_labels = labels.filtered(lambda l: l.company_id.id == company.id)
                            
                        if matched_labels:
                            label = matched_labels[0]
                        else:
                            label = labels[0]
                    else:
                        label = labels[0]
                    
                    # 5. Check Virtual Location to prevent duplicate/invalid transfers
                    current_loc_id = virtual_locations.get(label.id, label.branch_location_id.id if label.branch_location_id else False)
                    
                    # NOTE: Removed the 'current_loc_id != src_loc.id' skip logic 
                    # as requested, to allow all historical transfers to import successfully.

                        
                    # Sync data if needed
                    changes = self._sync_label_data(label, row_dict, dest_loc, src_loc)
                        
                    # Add to grouping dictionary
                    branch = dest_loc.branch_id if dest_loc and dest_loc.branch_id else (src_loc.branch_id if src_loc else label.branch_id)
                    gross_wt = self._get_float(row_dict.get("Sale Gross Weight (g)")) or self._get_float(row_dict.get("Tag Weight (g)")) or label.sale_gross_weight or 1.0
                    transfer_date = self._parse_datetime(row_dict.get("Date") or row_dict.get("Transfer Date") or row_dict.get("Scheduled Date") or row_dict.get("Created Date"))
                    
                    group_key = (company.id, src_loc.id, dest_loc.id, branch.id if branch else False, transfer_date)
                    # Update virtual location to simulate the sequence of transfers
                    virtual_locations[label.id] = dest_loc.id
                    
                    valid_transfers.append({
                        'label': label,
                        'src_loc': src_loc,
                        'dest_loc': dest_loc,
                        'company': company,
                        'branch': branch,
                        'transfer_date': transfer_date,
                        'gross_wt': gross_wt,
                        'row_no': row_no
                    })
                        
                except Exception as e:
                    skipped_count += 1
                    skipped_details.append({'row': row_no, 'label': label_name or str(normalized_barcode), 'reason': f"Error parsing row: {str(e)}"})
                    _logger.error(f"Row {row_no} failed: {e}")

            process_logs.append(f"Successfully validated {len(valid_transfers)} rows for individual transfers.")
            _logger.info(f"Successfully validated {len(valid_transfers)} rows for individual transfers.")

            # ---------------------------------------------------------
            # Execute Migration in Background Thread
            # ---------------------------------------------------------
            if valid_transfers:
                process_logs.append(f"Migration started in background for {len(valid_transfers)} transfers. Please check later.")
                _logger.info(f"SUCCESS: Migration started in background for {len(valid_transfers)} transfers. Please check later.")
                
                env = self.env
                db_name = env.cr.dbname
                uid = env.uid
                context = env.context.copy()
                
                import threading
                thread = threading.Thread(
                    target=self._run_migration_background,
                    args=(db_name, uid, context, valid_transfers)
                )
                thread.start()

            # Generate CSV Report
            csv_content = ""
            if skipped_details:
                csv_output = io.StringIO()
                writer = csv.DictWriter(csv_output, fieldnames=['row', 'label', 'reason'])
                writer.writeheader()
                for detail in skipped_details:
                    writer.writerow(detail)
                csv_content = csv_output.getvalue()
                
                # Save to Downloads folder
                try:
                    downloads_path = os.path.expanduser('~/Downloads/Skipped_Transfers_Report.csv')
                    with open(downloads_path, 'w', encoding='utf-8') as f:
                        f.write(csv_content)
                except Exception:
                    pass
                    
                # Save as attachment in Odoo
                attachment = self.env['ir.attachment'].create({
                    'name': 'Skipped_Transfers_Report.csv',
                    'type': 'binary',
                    'datas': base64.b64encode(csv_content.encode('utf-8')),
                    'res_model': 'inter.branch.transfer.import.wizard',
                    'res_id': self.id,
                })
                
        except Exception as e:
            raise ValidationError(str(e))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        message = _("Inter-Branch Transfer Import Completed.\n\n"
                    "Successfully Transferred : %s Labels\n"
                    "Skipped or Failed : %s Labels\n\n") % (transferred_count, skipped_count)

        if skipped_details:
            message += _("A CSV Report was generated in your Downloads folder containing exactly why labels failed.\n\n")
            
        message += "--- Detailed Execution Logs ---\n"
        message += "\n".join(process_logs)

        log_wizard = self.env['inter.branch.transfer.log.wizard'].create({
            'log_text': message
        })

        return {
            'name': _('Import Execution Logs'),
            'type': 'ir.actions.act_window',
            'res_model': 'inter.branch.transfer.log.wizard',
            'res_id': log_wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def _run_migration_background(self, db_name, uid, context, transfer_data_list):
        import odoo
        context = dict(context or {}, skip_label_location_overwrite=True)
        _logger.info("Starting background migration of %s transfers", len(transfer_data_list))
        
        picking_types = {}
        transferred_count = 0
        success_logs = []
        
        for t in transfer_data_list:
            label_id = t['label'].id
            
            try:
                # Spawn a fresh cursor for EVERY row. This ensures total isolation.
                with odoo.registry(db_name).cursor() as cr:
                    env = odoo.api.Environment(cr, uid, context)
                    
                    # Re-fetch the label with the new env
                    label = env['product.label'].browse(label_id)
                    comp_id = t['company'].id
                    
                    # Re-fetch locations with the new env
                    src_loc = env['stock.location'].browse(t['src_loc'].id)
                    dest_loc = env['stock.location'].browse(t['dest_loc'].id)
                    branch_id = t['branch'].id if t['branch'] else False
                    
                    if comp_id not in picking_types:
                        pt = env['stock.picking.type'].search([('code', '=', 'internal'), '|', ('company_id', '=', comp_id), ('company_id', '=', False)], limit=1)
                        if pt and pt.company_id and pt.company_id.id != comp_id:
                            raise ValueError(f"Picking type belongs to another company ({pt.company_id.name})")
                        picking_types[comp_id] = pt.id
                        
                    picking_type_id = picking_types[comp_id]
                    
                    env_company = env['stock.picking'].with_company(comp_id)
                    
                    picking = env_company.create({
                        'location_id': src_loc.id,
                        'location_dest_id': dest_loc.id,
                        'picking_type_id': picking_type_id,
                        'company_id': comp_id,
                        'branch_id': branch_id,
                        'origin': label.name,
                    })
                    
                    picking.write({
                        'location_id': src_loc.id,
                        'location_dest_id': dest_loc.id,
                    })
                    
                    if picking.location_id.id != src_loc.id or picking.location_dest_id.id != dest_loc.id:
                        raise ValueError(f"LOCATION MISMATCH AFTER CREATE. Expected: {src_loc.complete_name} -> {dest_loc.complete_name}. Actual: {picking.location_id.complete_name} -> {picking.location_dest_id.complete_name}")
                    
                    move_val = {
                        'name': label.name,
                        'company_id': comp_id,
                        'product_id': label.product_id.id,
                        'product_uom_qty': t['gross_wt'],
                        'product_uom': label.product_id.uom_id.id,
                        'location_id': src_loc.id,
                        'location_dest_id': dest_loc.id,
                        'picking_id': picking.id,
                        'branch_id': branch_id,
                        'label_id': label.id,
                        'purity_id': label.purity_id.id if label.purity_id else False,
                    }
                    if t['transfer_date']:
                        move_val['date'] = t['transfer_date']
                        
                    move = env['stock.move'].with_company(comp_id).create(move_val)
                    
                    move.write({
                        'location_id': src_loc.id,
                        'location_dest_id': dest_loc.id,
                    })
                    
                    picking.action_confirm()
                    picking.action_assign()
                    
                    if move.move_line_ids:
                        for ml in move.move_line_ids:
                            ml.quantity = move.product_uom_qty
                            ml.location_id = src_loc.id
                            ml.location_dest_id = dest_loc.id
                    else:
                        env['stock.move.line'].with_company(comp_id).create({
                            'move_id': move.id,
                            'picking_id': move.picking_id.id,
                            'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id,
                            'location_id': src_loc.id,
                            'location_dest_id': dest_loc.id,
                            'quantity': move.product_uom_qty,
                        })
                        
                    picking.button_validate()
                    
                    if t['transfer_date']:
                        transfer_date = t['transfer_date']
                        env.flush_all()
                        env.cr.execute(
                            "UPDATE stock_picking SET date_done = %s, scheduled_date = %s, date_deadline = %s WHERE id = %s",
                            (transfer_date, transfer_date, transfer_date, picking.id)
                        )
                        env.cr.execute(
                            "UPDATE stock_move SET date = %s WHERE picking_id = %s",
                            (transfer_date, picking.id)
                        )
                        env.cr.execute(
                            "UPDATE stock_move_line SET date = %s WHERE picking_id = %s",
                            (transfer_date, picking.id)
                        )
                        env.invalidate_all()
                        
                    label.write({
                        'branch_location_id': dest_loc.id,
                        'branch_id': branch_id if branch_id else label.branch_id.id,
                        'picking_id': picking.id,
                        'is_stocked_in': True,
                    })
                    
                    env.cr.commit()
                    transferred_count += 1
                    
                    company_name = env['res.company'].browse(comp_id).name
                    log_msg = f"Created transfer {picking.name} | Excel Source: {src_loc.complete_name} | Actual Source: {picking.location_id.complete_name} | Excel Destination: {dest_loc.complete_name} | Actual Destination: {picking.location_dest_id.complete_name} | Source ID: {picking.location_id.id} | Dest ID: {picking.location_dest_id.id} | Company: {company_name}"
                    _logger.info(log_msg)
                    success_logs.append(log_msg)
                    
            except Exception as e:
                err_msg = f"Row {t['row_no']}: Failed to create transfer for label {label_id}: {str(e)}"
                _logger.error(err_msg)

        _logger.info("Background migration finished: %s successfully created.", transferred_count)
        
        if success_logs:
            import base64
            with odoo.registry(db_name).cursor() as cr:
                env = odoo.api.Environment(cr, uid, context)
                log_content = "\n".join(success_logs)
                env['ir.attachment'].create({
                    'name': 'Background_Migration_Success_Logs.txt',
                    'type': 'binary',
                    'datas': base64.b64encode(log_content.encode('utf-8')),
                    'res_model': 'inter.branch.transfer.import.wizard',
                    'res_id': 0,
                    'description': f"Successfully created {transferred_count} transfers in background."
                })
                env.cr.commit()

    def _update_picking_dates(self, picking, transfer_date):
        if not picking or not transfer_date:
            return
            
        self.env.flush_all()
        
        self.env.cr.execute(
            "UPDATE stock_picking SET date_done = %s, scheduled_date = %s, date_deadline = %s WHERE id = %s",
            (transfer_date, transfer_date, transfer_date, picking.id)
        )
        self.env.cr.execute(
            "UPDATE stock_move SET date = %s WHERE picking_id = %s",
            (transfer_date, picking.id)
        )
        self.env.cr.execute(
            "UPDATE stock_move_line SET date = %s WHERE picking_id = %s",
            (transfer_date, picking.id)
        )
        self.env.invalidate_all()

    def _sync_label_data(self, label, row_dict, dest_loc=False, src_loc=False):
        vals_to_update = {}
        changes = []

        # 1. Gross Weight
        gross_wt = self._get_float(row_dict.get('Sale Gross Weight (g)')) or self._get_float(row_dict.get('Tag Weight (g)'))
        if gross_wt > 0:
            if abs((label.sale_gross_weight or 0.0) - gross_wt) > 0.0001:
                vals_to_update['sale_gross_weight'] = gross_wt
                vals_to_update['purchase_gross_weight'] = gross_wt
                changes.append(f"Gross Wt ({label.sale_gross_weight} -> {gross_wt})")

        # 2. Tag Weight
        tag_wt = self._get_float(row_dict.get('Tag Weight (g)'))
        if tag_wt > 0:
            if abs((label.tag_weight or 0.0) - tag_wt) > 0.0001:
                vals_to_update['tag_weight'] = tag_wt
                changes.append(f"Tag Wt ({label.tag_weight} -> {tag_wt})")

        # 3. Stone Weight
        if 'Sale Stone Weight (g)' in row_dict and row_dict.get('Sale Stone Weight (g)') is not None:
            stone_wt = self._get_float(row_dict.get('Sale Stone Weight (g)'))
            if abs((label.sale_stone_weight or 0.0) - stone_wt) > 0.0001:
                vals_to_update['sale_stone_weight'] = stone_wt
                vals_to_update['purchase_stone_weight'] = stone_wt
                changes.append(f"Stone Wt ({label.sale_stone_weight} -> {stone_wt})")

        # 4. Diamond Weight (g)
        if 'Diamond Weight (g)' in row_dict and row_dict.get('Diamond Weight (g)') is not None:
            diamond_wt_g = self._get_float(row_dict.get('Diamond Weight (g)'))
            if abs((label.sale_diamond_weight_gm or 0.0) - diamond_wt_g) > 0.0001:
                vals_to_update['sale_diamond_weight_gm'] = diamond_wt_g
                vals_to_update['purchase_diamond_weight_gm'] = diamond_wt_g
                changes.append(f"Diamond Wt g ({label.sale_diamond_weight_gm} -> {diamond_wt_g})")

        # 5. Diamond Weight (ct)
        if 'Diamond Weight (ct)' in row_dict and row_dict.get('Diamond Weight (ct)') is not None:
            diamond_wt_ct = self._get_float(row_dict.get('Diamond Weight (ct)'))
            if abs((label.sale_diamond_weight_ct or 0.0) - diamond_wt_ct) > 0.0001:
                vals_to_update['sale_diamond_weight_ct'] = diamond_wt_ct
                vals_to_update['purchase_diamond_weight_ct'] = diamond_wt_ct
                changes.append(f"Diamond Wt ct ({label.sale_diamond_weight_ct} -> {diamond_wt_ct})")

        # 6. Purity
        purity_raw = str(row_dict.get('Purity') or '').strip()
        if purity_raw:
            purity_rec = self.env['gold.purity'].search([('name', '=ilike', purity_raw)], limit=1)
            if purity_rec and label.purity_id.id != purity_rec.id:
                vals_to_update['purity_id'] = purity_rec.id
                vals_to_update['sale_purity_id'] = purity_rec.id
                purity_name = label.purity_id.name if label.purity_id else 'None'
                changes.append(f"Purity ('{purity_name}' -> '{purity_rec.name}')")

        # 7. Company
        comp_name = str(row_dict.get('Company') or '').strip()
        if comp_name:
            comp_rec = self.env['res.company'].search([('name', '=ilike', comp_name)], limit=1)
            if comp_rec and label.company_id.id != comp_rec.id:
                vals_to_update['company_id'] = comp_rec.id
                comp_old = label.company_id.name if label.company_id else 'None'
                changes.append(f"Company ('{comp_old}' -> '{comp_rec.name}')")

        # 8. Branch
        target_branch = dest_loc.branch_id if dest_loc and dest_loc.branch_id else (src_loc.branch_id if src_loc and src_loc.branch_id else False)
        if target_branch and label.branch_id.id != target_branch.id:
            vals_to_update['branch_id'] = target_branch.id
            branch_old = label.branch_id.name if label.branch_id else 'None'
            changes.append(f"Branch ('{branch_old}' -> '{target_branch.name}')")

        # 9. Transfer Date Sync
        transfer_date = self._parse_datetime(row_dict.get("Date") or row_dict.get("Transfer Date") or row_dict.get("Scheduled Date") or row_dict.get("Created Date"))
        if transfer_date and label.picking_id:
            current_dt = label.picking_id.date_done or label.picking_id.scheduled_date
            if not current_dt or current_dt != transfer_date:
                self._update_picking_dates(label.picking_id, transfer_date)
                old_str = current_dt.strftime('%Y-%m-%d %H:%M:%S') if current_dt else 'None'
                new_str = transfer_date.strftime('%Y-%m-%d %H:%M:%S')
                changes.append(f"Transfer Date ({old_str} -> {new_str})")

        if vals_to_update:
            label.write(vals_to_update)

        return changes

class InterBranchTransferLogWizard(models.TransientModel):
    _name = "inter.branch.transfer.log.wizard"
    _description = "Inter-Branch Transfer Log Viewer"

    log_text = fields.Text(string="Execution Logs", readonly=True)

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
