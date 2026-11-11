import base64
import io
import logging
import threading

import odoo
from odoo import fields, models, _
from odoo.exceptions import UserError
from openpyxl import load_workbook

from ..services.import_service import ProductLabelImportService

_logger = logging.getLogger(__name__)

class ProductLabelImportWizard(models.TransientModel):
    _name = 'product.label.import.wizard'
    _description = 'Product Label Import Wizard'

    file = fields.Binary(string='Excel File', required=True)
    filename = fields.Char(string='Filename')
    mapping_line_ids = fields.One2many(
        'product.label.import.mapping.line',
        'wizard_id',
        string='Excel Field Mapping',
    )
    result_message = fields.Text(string='Import Status', readonly=True)

    def _run_background_import(self, env, file_base64, field_mapping):
        with env.registry.cursor() as new_cr:
            new_env = odoo.api.Environment(new_cr, env.uid, env.context)
            service = ProductLabelImportService(new_env)
            try:
                service.process_import(
                    file_base64,
                    field_mapping=field_mapping,
                )
            except Exception:
                _logger.exception('Background product label import failed for wizard upload.')
                raise

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Please upload an Excel file.'))

        field_mapping = {}
        protected_fields = {
            'name', 'label_name', 'product_id', 'product_tmpl_id', 'company_id',
            'branch_id', 'source_location_id', 'branch_location_id', 'purchase_id',
        }
        for line in self.mapping_line_ids:
            source_column = (line.source_column or '').strip()
            target_field = line.target_field_id.name
            if not source_column:
                raise UserError(_('Enter an Excel column name for every mapping.'))
            if target_field in protected_fields:
                raise UserError(
                    _('The field "%s" is controlled by the product/stock import workflow and cannot be mapped.')
                    % line.target_field_id.field_description
                )
            field = self.env['product.label']._fields.get(target_field)
            if (
                not field
                or field.type not in (
                    'char', 'text', 'integer', 'float', 'boolean', 'selection',
                    'many2one', 'date', 'datetime',
                )
                or field.compute
                or field.related
                or field.readonly
            ):
                raise UserError(
                    _('The selected Product Label field is not directly importable.')
                )
            if target_field in field_mapping.values():
                raise UserError(_('Each Product Label field can only be mapped once.'))
            field_mapping[source_column] = target_field

        self._validate_excel_import(field_mapping)

        self.result_message = _('Import started in the background. Please check the server logs for progress.')

        thread = threading.Thread(
            target=self._run_background_import,
            args=(self.env, self.file, field_mapping),
            daemon=True,
        )
        thread.start()

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _validate_excel_import(self, field_mapping):
        workbook = load_workbook(
            io.BytesIO(base64.b64decode(self.file)),
            data_only=True,
            read_only=True,
        )
        try:
            sheet = workbook.active
            try:
                header_row = next(
                    sheet.iter_rows(min_row=1, max_row=1, values_only=True)
                )
            except StopIteration:
                raise UserError(_('The Excel file is empty and has no header row.'))

            raw_headers = [
                str(value).strip() if value else f'Col_{index}'
                for index, value in enumerate(header_row)
            ]
            headers = []
            header_counts = {}
            for header in raw_headers:
                if header in header_counts:
                    header_counts[header] += 1
                    headers.append(f'{header}_{header_counts[header]}')
                else:
                    header_counts[header] = 0
                    headers.append(header)
            header_by_name = {
                header.casefold(): index for index, header in enumerate(headers)
            }

            missing_mappings = [
                source_column
                for source_column in field_mapping
                if source_column.casefold() not in header_by_name
            ]
            if missing_mappings:
                raise UserError(
                    _('Mapped Excel column(s) not found: %s')
                    % ', '.join(missing_mappings)
                )

            purchase_order_index = next(
                (
                    header_by_name[header]
                    for header in ('choose purchase order', 'purchase order')
                    if header in header_by_name
                ),
                None,
            )
            company_index = header_by_name.get('company')
            if purchase_order_index is None:
                raise UserError(
                    _(
                        'The Excel file must include a "Purchase Order" or '
                        '"Choose Purchase Order" column.'
                    )
                )
            if company_index is None:
                raise UserError(_('The Excel file must include a "Company" column.'))

            companies = {}
            purchase_orders = {}
            for row_number, row in enumerate(
                sheet.iter_rows(min_row=2, values_only=True),
                start=2,
            ):
                if not any(row):
                    continue
                company_name = str(
                    row[company_index] if company_index < len(row) else ''
                ).strip()
                purchase_order_name = str(
                    row[purchase_order_index]
                    if purchase_order_index < len(row)
                    and row[purchase_order_index] is not None
                    else ''
                ).strip()
                if not purchase_order_name:
                    raise UserError(
                        _('Purchase Order is required in Excel row %s.') % row_number
                    )
                if not company_name:
                    raise UserError(
                        _('Company is required in Excel row %s.') % row_number
                    )

                company_key = company_name.casefold()
                if company_key not in companies:
                    companies[company_key] = self.env['res.company'].sudo().search(
                        [('name', '=ilike', company_name)],
                        limit=1,
                    )
                company = companies[company_key]
                if not company:
                    raise UserError(
                        _("Company '%s' was not found in Excel row %s.")
                        % (company_name, row_number)
                    )

                po_key = (company.id, purchase_order_name.casefold())
                if po_key not in purchase_orders:
                    purchase_orders[po_key] = self.env['purchase.order'].sudo().search(
                        [
                            ('name', '=ilike', purchase_order_name),
                            ('company_id', '=', company.id),
                        ],
                        limit=1,
                    )
                if not purchase_orders[po_key]:
                    raise UserError(
                        _("Purchase Order '%s' was not found for company '%s' in Excel row %s.")
                        % (purchase_order_name, company.name, row_number)
                    )
        finally:
            workbook.close()


class ProductLabelImportMappingLine(models.TransientModel):
    _name = 'product.label.import.mapping.line'
    _description = 'Product Label Import Field Mapping'

    wizard_id = fields.Many2one(
        'product.label.import.wizard',
        required=True,
        ondelete='cascade',
    )
    source_column = fields.Char(
        string='Excel Column',
        required=True,
        help='Header text from the first row of the Excel file.',
    )
    target_field_id = fields.Many2one(
        'ir.model.fields',
        string='Product Label Field',
        required=True,
        domain="[('model', '=', 'product.label'), ('readonly', '=', False), "
               "('name', 'not in', ['name', 'label_name', 'product_id', "
               "'product_tmpl_id', 'company_id', 'branch_id', "
               "'source_location_id', 'branch_location_id', 'purchase_id']), "
               "('ttype', 'in', ['char', 'text', 'integer', 'float', "
               "'boolean', 'selection', 'many2one', 'date', 'datetime'])]",
    )
