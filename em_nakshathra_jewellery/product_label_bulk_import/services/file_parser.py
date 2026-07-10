import base64
import csv
import io

from openpyxl import load_workbook


class FileParser:

    @staticmethod
    def get_sheet_names(file_b64, file_name):
        """Return list of sheet names for XLSX files; ['Sheet1'] for CSV."""
        if file_name.lower().endswith('.csv'):
            return ['Sheet1']
        data = base64.b64decode(file_b64)
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        names = wb.sheetnames
        wb.close()
        return names

    @staticmethod
    def get_headers(file_b64, file_name, sheet_name=None):
        """Return list of column header strings (first row only)."""
        if file_name.lower().endswith('.csv'):
            return FileParser._csv_headers(file_b64)
        return FileParser._xlsx_headers(file_b64, sheet_name)

    @staticmethod
    def count_rows(file_b64, file_name, sheet_name=None):
        """Return total data row count (excluding header)."""
        if file_name.lower().endswith('.csv'):
            return FileParser._csv_count(file_b64)
        return FileParser._xlsx_count(file_b64, sheet_name)

    @staticmethod
    def get_preview(file_b64, file_name, num_rows=20, sheet_name=None):
        """Return (headers, list_of_dicts) for first num_rows data rows."""
        if file_name.lower().endswith('.csv'):
            return FileParser._csv_preview(file_b64, num_rows)
        return FileParser._xlsx_preview(file_b64, num_rows, sheet_name)

    @staticmethod
    def iter_batch(file_b64, file_name, headers, offset, limit, sheet_name=None):
        """Yield dicts for rows [offset, offset+limit) (0-based, after header)."""
        if file_name.lower().endswith('.csv'):
            yield from FileParser._csv_batch(file_b64, offset, limit)
        else:
            yield from FileParser._xlsx_batch(file_b64, headers, offset, limit, sheet_name)

    # ── CSV helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _decode_csv(file_b64):
        raw = base64.b64decode(file_b64)
        for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode('latin-1', errors='replace')

    @staticmethod
    def _csv_headers(file_b64):
        content = FileParser._decode_csv(file_b64)
        reader = csv.reader(io.StringIO(content))
        return [h.strip() for h in (next(reader, []))]

    @staticmethod
    def _csv_count(file_b64):
        content = FileParser._decode_csv(file_b64)
        reader = csv.reader(io.StringIO(content))
        next(reader, None)  # skip header
        return sum(1 for _ in reader)

    @staticmethod
    def _csv_preview(file_b64, num_rows):
        content = FileParser._decode_csv(file_b64)
        reader = csv.DictReader(io.StringIO(content))
        rows = []
        for i, row in enumerate(reader):
            if i >= num_rows:
                break
            rows.append(dict(row))
        return list(reader.fieldnames or []), rows

    @staticmethod
    def _csv_batch(file_b64, offset, limit):
        content = FileParser._decode_csv(file_b64)
        reader = csv.DictReader(io.StringIO(content))
        for i, row in enumerate(reader):
            if i < offset:
                continue
            if i >= offset + limit:
                break
            yield dict(row)

    # ── XLSX helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _get_ws(wb, sheet_name):
        """Return worksheet: by name if given, else the active (first) sheet."""
        if sheet_name and sheet_name in wb.sheetnames:
            return wb[sheet_name]
        return wb.active

    @staticmethod
    def _xlsx_headers(file_b64, sheet_name=None):
        data = base64.b64decode(file_b64)
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = FileParser._get_ws(wb, sheet_name)
        headers = []
        for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
            headers = [str(c).strip() if c is not None else '' for c in row]
        wb.close()
        return headers

    @staticmethod
    def _xlsx_count(file_b64, sheet_name=None):
        data = base64.b64decode(file_b64)
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = FileParser._get_ws(wb, sheet_name)
        count = (ws.max_row or 1) - 1
        wb.close()
        return max(count, 0)

    @staticmethod
    def _xlsx_preview(file_b64, num_rows, sheet_name=None):
        data = base64.b64decode(file_b64)
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = FileParser._get_ws(wb, sheet_name)
        headers = []
        rows = []
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=num_rows + 1, values_only=True)):
            if i == 0:
                headers = [str(c).strip() if c is not None else '' for c in row]
            else:
                rows.append(dict(zip(headers, [c for c in row])))
        wb.close()
        return headers, rows

    @staticmethod
    def _xlsx_batch(file_b64, headers, offset, limit, sheet_name=None):
        data = base64.b64decode(file_b64)
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = FileParser._get_ws(wb, sheet_name)
        # row 1 = header, data starts at row 2; offset is 0-based
        min_row = offset + 2
        max_row = offset + limit + 1
        for row in ws.iter_rows(min_row=min_row, max_row=max_row, values_only=True):
            yield dict(zip(headers, [c for c in row]))
        wb.close()