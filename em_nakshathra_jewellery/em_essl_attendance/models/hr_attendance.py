import logging
import requests
import pytz
import time
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

_LAST_ESSL_SYNC = 0
_SYNC_COOLDOWN = 15

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    essl_location_id = fields.Many2one('essl.location', string='Check-in Location', readonly=True)
    essl_checkout_location_id = fields.Many2one('essl.location', string='Check-out Location', readonly=True)

    @api.model
    def _fetch_raw_essl_logs(self, from_date_str, to_date_str, serial_number, username, password, url, local_tz):
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://tempuri.org/GetTransactionsLog"
        }

        body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetTransactionsLog xmlns="http://tempuri.org/">
      <FromDateTime>{from_date_str}</FromDateTime>
      <ToDateTime>{to_date_str}</ToDateTime>
      <SerialNumber>{serial_number}</SerialNumber>
      <UserName>{username}</UserName>
      <UserPassword>{password}</UserPassword>
      <strDataList></strDataList>
    </GetTransactionsLog>
  </soap:Body>
</soap:Envelope>"""

        _logger.info(f"Fetching raw eSSL logs for Serial {serial_number} from {from_date_str} to {to_date_str}")
        
        response = requests.post(url, data=body, headers=headers, timeout=30)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        data_text = ""
        for elem in root.iter():
            if elem.tag.endswith('strDataList'):
                data_text = elem.text or ""
                break

        if not data_text:
            return []

        log_entries = []
        for line in data_text.strip().split('\n'):
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            emp_code = parts[0].strip()
            timestamp_str = parts[1].strip()
            raw_punch_type = parts[2].strip().lower() if len(parts) > 2 else ''
            punch_type = raw_punch_type if raw_punch_type in ('in', 'out') else ''
            
            try:
                dt_local = None
                for fmt in ('%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M:%S'):
                    try:
                        dt_local = datetime.strptime(timestamp_str, fmt)
                        break
                    except ValueError:
                        continue
                if dt_local is None:
                    continue
                    
                dt_localized = local_tz.localize(dt_local)
                dt_utc = dt_localized.astimezone(pytz.utc).replace(tzinfo=None)
                log_entries.append({
                    'emp_code': emp_code,
                    'dt_local': dt_local,
                    'dt_utc': dt_utc,
                    'punch_type': punch_type
                })
            except Exception as ex:
                _logger.warning(f"Failed to parse log line: {line}. Error: {ex}")

        return log_entries

    @api.model
    def fetch_and_parse_essl_logs(self, from_date_str=None, to_date_str=None, serial_number=None, username=None, password=None, do_sync=False):
        """ Fetch logs from eSSL SOAP Web Service, map to employees, and optionally sync them. """
        url = self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.api_url')
        if not url:
            raise ValueError("eSSL API URL is not configured.")

        # Ensure the URL points to WebAPIService.asmx and clean any query parameters/double slashes
        if 'WebAPIService.asmx' in url:
            url = url.split('WebAPIService.asmx')[0] + 'WebAPIService.asmx'
        else:
            url = url.rstrip('/') + '/WebAPIService.asmx'

        # Clean double slashes except after http(s):
        if '://' in url:
            proto_parts = url.split('://', 1)
            url = proto_parts[0] + '://' + proto_parts[1].replace('//', '/')

        api_username = username or self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.username') or 'essl'
        api_password = password or self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.password') or 'essl'
        api_serial = serial_number or self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.serial_number') or ''
        timezone_name = self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.timezone') or 'Asia/Kolkata'

        try:
            local_tz = pytz.timezone(timezone_name)
        except Exception as tz_ex:
            _logger.error(f"Invalid timezone {timezone_name}, falling back to Asia/Kolkata. Error: {tz_ex}")
            local_tz = pytz.timezone('Asia/Kolkata')

        # Helper to normalize incoming date-time format for SOAP API (must be DD-MM-YYYY HH:MM:SS)
        def normalize_date_format(date_str, default_time='00:00:00'):
            if not date_str:
                return None
            date_str = date_str.strip()
            parsed_dt = None
            for fmt in ('%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M', '%Y-%m-%d %H:%M', '%d-%m-%Y', '%Y-%m-%d'):
                try:
                    parsed_dt = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
            if parsed_dt:
                if len(date_str) <= 10:
                    return parsed_dt.strftime(f'%d-%m-%Y {default_time}')
                return parsed_dt.strftime('%d-%m-%Y %H:%M:%S')
            return date_str

        # If from/to date strings are not provided, default to last 3 days
        if not from_date_str or not to_date_str:
            now_local = datetime.now(local_tz)
            from_dt_local = now_local - timedelta(days=3)
            from_date_str = from_dt_local.strftime('%d-%m-%Y 00:00:00')
            to_date_str = now_local.strftime('%d-%m-%Y 23:59:59')
        else:
            from_date_str = normalize_date_format(from_date_str, '00:00:00')
            to_date_str = normalize_date_format(to_date_str, '23:59:59')

        # If no specific serial_number is passed, check active locations configuration
        locations = self.env['essl.location'].sudo().browse()
        if not serial_number:
            locations = self.env['essl.location'].sudo().search([('active', '=', True)])

        all_log_entries = []

        if locations:
            for loc in locations:
                try:
                    log_entries = self._fetch_raw_essl_logs(
                        from_date_str=from_date_str,
                        to_date_str=to_date_str,
                        serial_number=loc.serial_number,
                        username=api_username,
                        password=api_password,
                        url=url,
                        local_tz=local_tz
                    )
                    for entry in log_entries:
                        entry['location_id'] = loc.id
                    all_log_entries.extend(log_entries)
                except Exception as loc_ex:
                    _logger.error(f"Failed to fetch logs for location {loc.name} (SN: {loc.serial_number}): {loc_ex}")
        else:
            # Fallback to single serial number from config parameter
            try:
                log_entries = self._fetch_raw_essl_logs(
                    from_date_str=from_date_str,
                    to_date_str=to_date_str,
                    serial_number=api_serial,
                    username=api_username,
                    password=api_password,
                    url=url,
                    local_tz=local_tz
                )
                loc = self.env['essl.location'].sudo().search([('serial_number', '=', api_serial)], limit=1)
                for entry in log_entries:
                    entry['location_id'] = loc.id if loc else False
                all_log_entries.extend(log_entries)
            except Exception as single_ex:
                _logger.error(f"Failed to fetch logs for default SN {api_serial}: {single_ex}")

        # Sort all log entries chronologically across locations
        all_log_entries.sort(key=lambda x: x['dt_utc'])

        # Group entries by employee code
        from collections import defaultdict
        grouped_entries = defaultdict(list)
        for entry in all_log_entries:
            grouped_entries[entry['emp_code']].append(entry)

        raw_logs_result = []
        attendances_result = []
        synced_count = 0

        # Batch prefetch employees to avoid N+1 queries
        emp_codes = list(grouped_entries.keys())
        employees_by_code = {}
        if emp_codes:
            matched_employees = self.env['hr.employee'].sudo().search([('essl_emp_code', 'in', emp_codes)])
            for emp in matched_employees:
                employees_by_code[emp.essl_emp_code] = emp
            
            # Fallback search for names if not found by essl_emp_code
            remaining_codes = [c for c in emp_codes if c not in employees_by_code]
            for name in remaining_codes:
                emp = self.env['hr.employee'].sudo().search([('name', '=ilike', name)], limit=1)
                if not emp:
                    emp = self.env['hr.employee'].sudo().search([('name', 'ilike', name)], limit=1)
                if emp:
                    employees_by_code[name] = emp

        for emp_code, entries in grouped_entries.items():
            employee = employees_by_code.get(emp_code)
            employee_name = employee.name if employee else "Unknown"

            # Populate raw logs for JSON
            for entry in entries:
                raw_logs_result.append({
                    'employee_code': emp_code,
                    'employee_name': employee_name,
                    'timestamp_local': entry['dt_local'].strftime('%Y-%m-%d %H:%M:%S'),
                    'timestamp_utc': entry['dt_utc'].strftime('%Y-%m-%d %H:%M:%S'),
                    'punch_type': entry['punch_type'],
                    'location_id': entry.get('location_id', False)
                })

            # Chronological pairing for attendances list (dry-run output)
            i = 0
            while i < len(entries):
                check_in_entry = entries[i]
                check_out_entry = None
                if i + 1 < len(entries):
                    check_out_entry = entries[i+1]
                    i += 2
                else:
                    i += 1

                attendances_result.append({
                    'employee_code': emp_code,
                    'employee_name': employee_name,
                    'check_in': check_in_entry['dt_local'].strftime('%Y-%m-%d %H:%M:%S'),
                    'check_out': check_out_entry['dt_local'].strftime('%Y-%m-%d %H:%M:%S') if check_out_entry else None,
                    'check_in_utc': check_in_entry['dt_utc'].strftime('%Y-%m-%d %H:%M:%S'),
                    'check_out_utc': check_out_entry['dt_utc'].strftime('%Y-%m-%d %H:%M:%S') if check_out_entry else None,
                    'location_id': check_in_entry.get('location_id', False),
                    'checkout_location_id': check_out_entry.get('location_id', False) if check_out_entry else False,
                })

        # If do_sync is True, perform the actual write to the Odoo database
        if do_sync and attendances_result:
            # Batch prefetch existing attendances in the selected range to avoid N+1 queries
            employee_ids = [emp.id for emp in employees_by_code.values() if emp]
            all_check_ins = [datetime.strptime(att['check_in_utc'], '%Y-%m-%d %H:%M:%S') for att in attendances_result]
            
            existing_attendances = {}
            if employee_ids and all_check_ins:
                min_check_in = min(all_check_ins)
                max_check_in = max(all_check_ins)
                records = self.sudo().search([
                    ('employee_id', 'in', employee_ids),
                    ('check_in', '>=', min_check_in),
                    ('check_in', '<=', max_check_in)
                ])
                for rec in records:
                    existing_attendances[(rec.employee_id.id, rec.check_in)] = rec

            vals_list = []
            for att in attendances_result:
                employee = employees_by_code.get(att['employee_code'])
                if not employee:
                    continue
                
                dt_in_utc = datetime.strptime(att['check_in_utc'], '%Y-%m-%d %H:%M:%S')
                dt_out_utc = datetime.strptime(att['check_out_utc'], '%Y-%m-%d %H:%M:%S') if att['check_out_utc'] else None
                
                existing = existing_attendances.get((employee.id, dt_in_utc))
                
                if existing:
                    # If check_out is now available but was previously empty, update it
                    if dt_out_utc and not existing.check_out:
                        existing.sudo().write({
                            'check_out': dt_out_utc,
                            'essl_checkout_location_id': att['checkout_location_id']
                        })
                        synced_count += 1
                        _logger.info(f"Updated check-out for {employee.name} to {dt_out_utc} (Location: {att['checkout_location_id']})")
                else:
                    # Collect check-ins for batch create
                    vals = {
                        'employee_id': employee.id,
                        'check_in': dt_in_utc,
                        'essl_location_id': att['location_id']
                    }
                    if dt_out_utc:
                        vals['check_out'] = dt_out_utc
                        vals['essl_checkout_location_id'] = att['checkout_location_id']
                    vals_list.append(vals)
                    synced_count += 1

            if vals_list:
                self.sudo().create(vals_list)
                for vals in vals_list:
                    emp = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                    _logger.info(f"Created attendance check-in for {emp.name} at {vals['check_in']} (check_out={vals.get('check_out')})")

        return {
            'attendances': attendances_result,
            'raw_logs': raw_logs_result,
            'synced_count': synced_count
        }

    @api.model
    def _fetch_essl_attendance(self):
        """ Fetch attendance logs from the eSSL SOAP API and create hr.attendance records. """
        try:
            res = self.fetch_and_parse_essl_logs(do_sync=True)
            _logger.info(f"Cron job synced {res.get('synced_count', 0)} attendance records.")
        except Exception as e:
            _logger.error(f"Failed to fetch or parse eSSL attendance in cron: {e}")

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        if self.env.context.get('tz') == 'Asia/Calcutta':
            self = self.with_context(tz='Asia/Kolkata')
        self._dynamic_essl_sync()
        return super(HrAttendance, self).search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order)

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        if self.env.context.get('tz') == 'Asia/Calcutta':
            self = self.with_context(tz='Asia/Kolkata')
        self._dynamic_essl_sync()
        return super(HrAttendance, self).read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)

    def _dynamic_essl_sync(self):
        if self.env.context.get('skip_essl_sync'):
            return
        global _LAST_ESSL_SYNC
        now = time.time()
        if now - _LAST_ESSL_SYNC > _SYNC_COOLDOWN:
            _LAST_ESSL_SYNC = now
            try:
                self.with_context(skip_essl_sync=True).fetch_and_parse_essl_logs(do_sync=True)
            except Exception as e:
                _logger.warning(f"Dynamic eSSL fetch failed: {e}")
