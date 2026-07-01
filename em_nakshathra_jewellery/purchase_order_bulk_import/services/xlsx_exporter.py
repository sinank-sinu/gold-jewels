import io
import xlsxwriter


class XlsxExporter:
    """Generate downloadable XLSX files for import result sets."""

    RESULT_TYPES = {
        'error':     ('Error Rows',     ['Row #', 'PO Number', 'Error Message', 'Row Data']),
        'updated':   ('Updated Rows',   ['Row #', 'PO Number', 'Status', 'Row Data']),
        'duplicate': ('Duplicate Rows', ['Row #', 'PO Number', 'Reason', 'Row Data']),
        'skipped':   ('Skipped Rows',   ['Row #', 'PO Number', 'Reason', 'Row Data']),
    }

    @staticmethod
    def build(batches, result_type):
        """
        Build an XLSX file bytes for the given result_type across all batches.
        result_type: 'error' | 'updated' | 'duplicate' | 'skipped'
        """
        sheet_name, columns = XlsxExporter.RESULT_TYPES.get(result_type, ('Results', ['Row #', 'Data']))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet(sheet_name[:31])

        # Styles
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#4472C4', 'font_color': '#FFFFFF',
            'border': 1, 'text_wrap': True,
        })
        cell_fmt = workbook.add_format({'border': 1, 'text_wrap': False})
        error_fmt = workbook.add_format({'border': 1, 'font_color': '#CC0000'})

        # Header row
        for col_idx, col_name in enumerate(columns):
            worksheet.write(0, col_idx, col_name, header_fmt)

        row_idx = 1
        getter_map = {
            'error':     'get_error_rows',
            'updated':   'get_updated_rows',
            'duplicate': 'get_duplicate_rows',
            'skipped':   'get_skipped_rows',
        }
        getter = getter_map.get(result_type, 'get_error_rows')

        for batch in batches:
            rows = getattr(batch, getter)()
            for entry in rows:
                row_data = entry.get('data', {})
                data_str = ', '.join(f'{k}={v}' for k, v in row_data.items()) if row_data else ''
                fmt = error_fmt if result_type == 'error' else cell_fmt

                if result_type == 'error':
                    worksheet.write(row_idx, 0, entry.get('row', ''), fmt)
                    worksheet.write(row_idx, 1, entry.get('po_number', ''), fmt)
                    worksheet.write(row_idx, 2, entry.get('error', ''), fmt)
                    worksheet.write(row_idx, 3, data_str, fmt)
                else:
                    worksheet.write(row_idx, 0, entry.get('row', ''), fmt)
                    worksheet.write(row_idx, 1, entry.get('po_number', ''), fmt)
                    worksheet.write(row_idx, 2, entry.get('reason', entry.get('status', '')), fmt)
                    worksheet.write(row_idx, 3, data_str, fmt)

                row_idx += 1

        # Column widths
        col_widths = [10, 20, 40, 60]
        for i, w in enumerate(col_widths[:len(columns)]):
            worksheet.set_column(i, i, w)

        worksheet.freeze_panes(1, 0)
        workbook.close()
        return output.getvalue()