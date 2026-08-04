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

    essl_location_id = fields.Many2one('res.branch', string='Check-in Location', readonly=True)
    essl_checkout_location_id = fields.Many2one('res.branch', string='Check-out Location', readonly=True)
    essl_shift_id = fields.Many2one('essl.shift', string='Shift', readonly=True)
    half_day_leave = fields.Boolean(string='Half Day Leave', default=False)

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

        # If no specific serial_number is passed, check active branches with eSSL serial numbers
        branches = self.env['res.branch'].sudo().browse()
        if not serial_number:
            branches = self.env['res.branch'].sudo().search([('essl_serial_number', '!=', False)])

        all_log_entries = []

        if branches:
            for branch in branches:
                try:
                    log_entries = self._fetch_raw_essl_logs(
                        from_date_str=from_date_str,
                        to_date_str=to_date_str,
                        serial_number=branch.essl_serial_number,
                        username=api_username,
                        password=api_password,
                        url=url,
                        local_tz=local_tz
                    )
                    for entry in log_entries:
                        entry['location_id'] = branch.id
                    all_log_entries.extend(log_entries)
                except Exception as loc_ex:
                    _logger.error(f"Failed to fetch logs for branch location {branch.name} (SN: {branch.essl_serial_number}): {loc_ex}")
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
                branch = self.env['res.branch'].sudo().search([('essl_serial_number', '=', api_serial)], limit=1)
                for entry in log_entries:
                    entry['location_id'] = branch.id if branch else False
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
        employee_ids = []
        if emp_codes:
            matched_employees = self.env['hr.employee'].sudo().search([('essl_emp_code', 'in', emp_codes)])
            for emp in matched_employees:
                employees_by_code[emp.essl_emp_code] = emp
                employee_ids.append(emp.id)
            
            # Fallback search for names if not found by essl_emp_code
            remaining_codes = [c for c in emp_codes if c not in employees_by_code]
            for name in remaining_codes:
                emp = self.env['hr.employee'].sudo().search([('name', '=ilike', name)], limit=1)
                if not emp:
                    emp = self.env['hr.employee'].sudo().search([('name', 'ilike', name)], limit=1)
                if emp:
                    employees_by_code[name] = emp
                    employee_ids.append(emp.id)

        # Batch prefetch shift assignments
        shift_by_employee_id = {}
        if employee_ids:
            # 1. Direct assignments
            assignments = self.env['essl.shift.assignment'].sudo().search([
                ('employee_id', 'in', employee_ids),
                ('active', '=', True)
            ])
            for assign in assignments:
                shift_by_employee_id[assign.employee_id.id] = assign.shift_id

            # 2. Department-wise assignments fallback
            remaining_employees = [emp for emp in employees_by_code.values() if emp and emp.id not in shift_by_employee_id]
            if remaining_employees:
                dept_ids = [emp.department_id.id for emp in remaining_employees if emp.department_id]
                if dept_ids:
                    shifts = self.env['essl.shift'].sudo().search([
                        ('department_ids', 'in', dept_ids)
                    ])
                    shift_by_dept = {}
                    for shift in shifts:
                        for dept in shift.department_ids:
                            shift_by_dept[dept.id] = shift
                    for emp in remaining_employees:
                        if emp.department_id and emp.department_id.id in shift_by_dept:
                            shift_by_employee_id[emp.id] = shift_by_dept[emp.department_id.id]



        for emp_code, entries in list(grouped_entries.items()):
            employee = employees_by_code.get(emp_code)
            employee_name = employee.name if employee else "Unknown"
            shift = shift_by_employee_id.get(employee.id) if employee else None

            # Validate location if employee has an assigned essl_location_id (which is a res.branch)
            if employee and employee.essl_location_id:
                filtered_entries = []
                for entry in entries:
                    if entry.get('location_id') == employee.essl_location_id.id:
                        filtered_entries.append(entry)
                    else:
                        _logger.warning(
                            f"Ignoring punch for employee {employee_name} (code: {emp_code}) at wrong location. "
                            f"Assigned location: {employee.essl_location_id.name}, Punch location ID: {entry.get('location_id')}"
                        )
                entries = filtered_entries
                grouped_entries[emp_code] = entries

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

            if shift:
                # ── Shift-based pairing ──────────────────────────────────────
                # Rule:
                #   check-in  = first punch inside the shift window
                #   check-out = last punch that is AT OR AFTER shift end_time
                #               (i.e. the employee punched out after their shift ended)
                #   If no post-end punch exists yet → check-out is left empty.
                # Each shift is designed to be 8 hrs (start_time → end_time).

                unique_dates = sorted(list(set(entry['dt_local'].date() for entry in entries)))
                # Also consider the previous day to handle overnight shifts
                extended_dates = sorted(list(set(unique_dates + [d - timedelta(days=1) for d in unique_dates])))

                assigned_punches = set()
                for D in extended_dates:
                    shift_start_hour = shift.start_time
                    shift_end_hour   = shift.end_time

                    # Build shift start/end as datetimes for day D
                    start_dt = datetime.combine(D, datetime.min.time()) + timedelta(hours=shift_start_hour)
                    end_dt   = datetime.combine(D, datetime.min.time()) + timedelta(hours=shift_end_hour)

                    # Overnight shift: end on the next calendar day
                    if shift_start_hour >= shift_end_hour:
                        end_dt += timedelta(days=1)

                    # ── Windows ──────────────────────────────────────────────
                    # Allow check-in up to 2 hrs before shift start (early birds)
                    window_start = start_dt - timedelta(hours=2)
                    # Allow check-out up to 4 hrs after shift end (overtime / late punches)
                    window_end   = end_dt + timedelta(hours=4)

                    # All unassigned punches within the full shift window
                    shift_entries = [
                        entry for entry in entries
                        if window_start <= entry['dt_local'] <= window_end
                        and entry['dt_utc'] not in assigned_punches
                    ]

                    if not shift_entries:
                        continue

                    # Mark all punches in this window as assigned
                    for entry in shift_entries:
                        assigned_punches.add(entry['dt_utc'])

                    # ── Check-in: first punch in the window ──────────────────
                    check_in_entry = shift_entries[0]

                    # ── Check-out: last punch in the window (excluding check-in) ──
                    # The last punch is the checkout and it should be recorded if it is the end time
                    # or after the end time of the employee shift, else ignored.
                    other_punches = [
                        e for e in shift_entries
                        if e['dt_utc'] != check_in_entry['dt_utc']
                    ]
                    if other_punches:
                        last_punch = other_punches[-1]
                        if last_punch['dt_local'] >= end_dt:
                            check_out_entry = last_punch
                        else:
                            check_out_entry = None
                    else:
                        check_out_entry = None

                    # ── Late-check / half-day flag ───────────────────────────
                    late_limit = start_dt + timedelta(minutes=shift.extra_minutes)
                    is_late = check_in_entry['dt_local'] > late_limit

                    attendances_result.append({
                        'employee_code':        emp_code,
                        'employee_name':        employee_name,
                        'check_in':             check_in_entry['dt_local'].strftime('%Y-%m-%d %H:%M:%S'),
                        'check_out':            check_out_entry['dt_local'].strftime('%Y-%m-%d %H:%M:%S') if check_out_entry else None,
                        'check_in_utc':         check_in_entry['dt_utc'].strftime('%Y-%m-%d %H:%M:%S'),
                        'check_out_utc':        check_out_entry['dt_utc'].strftime('%Y-%m-%d %H:%M:%S') if check_out_entry else None,
                        'location_id':          check_in_entry.get('location_id', False),
                        'checkout_location_id': check_out_entry.get('location_id', False) if check_out_entry else False,
                        'essl_shift_id':        shift.id,
                        'half_day_leave':       is_late,
                    })

            else:
                # Chronological pairing fallback - group by calendar day
                unique_dates = sorted(list(set(entry['dt_local'].date() for entry in entries)))
                for D in unique_dates:
                    day_entries = [entry for entry in entries if entry['dt_local'].date() == D]
                    if day_entries:
                        check_in_entry = day_entries[0]
                        check_out_entry = day_entries[-1] if len(day_entries) > 1 else None

                        attendances_result.append({
                            'employee_code': emp_code,
                            'employee_name': employee_name,
                            'check_in': check_in_entry['dt_local'].strftime('%Y-%m-%d %H:%M:%S'),
                            'check_out': check_out_entry['dt_local'].strftime('%Y-%m-%d %H:%M:%S') if check_out_entry else None,
                            'check_in_utc': check_in_entry['dt_utc'].strftime('%Y-%m-%d %H:%M:%S'),
                            'check_out_utc': check_out_entry['dt_utc'].strftime('%Y-%m-%d %H:%M:%S') if check_out_entry else None,
                            'location_id': check_in_entry.get('location_id', False),
                            'checkout_location_id': check_out_entry.get('location_id', False) if check_out_entry else False,
                            'essl_shift_id': False,
                            'half_day_leave': False,
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

            # Fetch currently open attendances for these employees to handle conflicts
            open_attendances = {}
            if employee_ids:
                open_recs = self.sudo().search([
                    ('employee_id', 'in', employee_ids),
                    ('check_out', '=', False)
                ])
                for rec in open_recs:
                    open_attendances[rec.employee_id.id] = rec

            vals_list = []
            for att in attendances_result:
                employee = employees_by_code.get(att['employee_code'])
                if not employee:
                    continue
                
                dt_in_utc = datetime.strptime(att['check_in_utc'], '%Y-%m-%d %H:%M:%S')
                dt_out_utc = datetime.strptime(att['check_out_utc'], '%Y-%m-%d %H:%M:%S') if att['check_out_utc'] else None
                
                existing = existing_attendances.get((employee.id, dt_in_utc))
                open_att = open_attendances.get(employee.id)
                if open_att and open_att.check_in > dt_in_utc:
                    open_att = None
                
                if existing:
                    # If check_out is now available but was previously empty, update it
                    write_vals = {}
                    shift = shift_by_employee_id.get(employee.id)
                    if shift:
                        # Let's get the shift end time for this check-in day
                        check_in_local = pytz.utc.localize(existing.check_in).astimezone(local_tz)
                        shift_end_hour = shift.end_time
                        shift_start_hour = shift.start_time
                        end_dt = datetime.combine(check_in_local.date(), datetime.min.time()) + timedelta(hours=shift_end_hour)
                        if shift_start_hour >= shift_end_hour:
                            end_dt += timedelta(days=1)
                        end_dt = local_tz.localize(end_dt)

                        if dt_out_utc:
                            if not existing.check_out or existing.check_out != dt_out_utc:
                                write_vals['check_out'] = dt_out_utc
                                write_vals['essl_checkout_location_id'] = att['checkout_location_id']
                    else:
                        # Fallback / no shift assigned
                        if dt_out_utc and (not existing.check_out or existing.check_out != dt_out_utc):
                            write_vals['check_out'] = dt_out_utc
                            write_vals['essl_checkout_location_id'] = att['checkout_location_id']

                    if not existing.essl_shift_id and att.get('essl_shift_id'):
                        write_vals['essl_shift_id'] = att['essl_shift_id']
                    if existing.half_day_leave != att.get('half_day_leave', False):
                        write_vals['half_day_leave'] = att.get('half_day_leave', False)

                    if write_vals:
                        try:
                            with self.env.cr.savepoint():
                                existing.sudo().write(write_vals)
                                synced_count += 1
                                _logger.info(f"Updated attendance for {employee.name} (check_in={dt_in_utc}): {write_vals}")
                        except Exception as e:
                            _logger.warning(f"Failed to update attendance for {employee.name} (check_in={dt_in_utc}): {e}")
                elif open_att:
                    # Conflict handling: employee has an open attendance record in Odoo
                    # 1. If we have a valid check-out time in the parsed log, we can close the open attendance
                    if dt_out_utc and not open_att.check_out and dt_out_utc > open_att.check_in:
                        write_vals = {
                            'check_out': dt_out_utc,
                            'essl_checkout_location_id': att['checkout_location_id']
                        }
                        if not open_att.essl_shift_id and att.get('essl_shift_id'):
                            write_vals['essl_shift_id'] = att['essl_shift_id']
                        if open_att.half_day_leave != att.get('half_day_leave', False):
                            write_vals['half_day_leave'] = att.get('half_day_leave', False)
                        try:
                            with self.env.cr.savepoint():
                                open_att.sudo().write(write_vals)
                                synced_count += 1
                                # Update the local cache so we know it is no longer open
                                open_attendances.pop(employee.id, None)
                                _logger.info(f"Closed open attendance for {employee.name} (check_in={open_att.check_in}) with check_out={dt_out_utc}")
                        except Exception as e:
                            _logger.warning(f"Failed to close open attendance for {employee.name}: {e}")
                    else:
                        # 2. Otherwise, ignore this new punch to avoid Odoo validation errors
                        _logger.warning(
                            f"Ignoring check-in punch {dt_in_utc} for {employee.name} because they already have an open attendance since {open_att.check_in}."
                        )
                else:
                    # Collect check-ins for creation
                    vals = {
                        'employee_id': employee.id,
                        'check_in': dt_in_utc,
                        'essl_location_id': att['location_id'],
                        'essl_shift_id': att.get('essl_shift_id', False),
                        'half_day_leave': att.get('half_day_leave', False),
                    }
                    if dt_out_utc:
                        vals['check_out'] = dt_out_utc
                        vals['essl_checkout_location_id'] = att['checkout_location_id']
                    vals_list.append(vals)

            if vals_list:
                for vals in vals_list:
                    try:
                        with self.env.cr.savepoint():
                            self.sudo().create([vals])
                            synced_count += 1
                            emp = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                            _logger.info(f"Created attendance check-in for {emp.name} at {vals['check_in']} (check_out={vals.get('check_out')})")
                    except Exception as e:
                        _logger.warning(f"Ignoring duplicate/overlapping punch for employee ID {vals['employee_id']} at {vals['check_in']}: {e}")

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
        # NOTE: do NOT trigger eSSL sync here — read_group is a read operation
        # and a failed sync would abort the transaction, breaking the view.
        return super(HrAttendance, self).read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)

    def _dynamic_essl_sync(self):
        """Trigger an eSSL sync at most once per cooldown window.
        Uses a DB savepoint so a failed network call cannot abort the
        surrounding transaction (which would break list/kanban views).
        """
        if self.env.context.get('skip_essl_sync'):
            return
        global _LAST_ESSL_SYNC
        now = time.time()
        if now - _LAST_ESSL_SYNC > _SYNC_COOLDOWN:
            _LAST_ESSL_SYNC = now
            try:
                with self.env.cr.savepoint():
                    self.with_context(skip_essl_sync=True).fetch_and_parse_essl_logs(do_sync=True)
            except Exception as e:
                _logger.warning(f"Dynamic eSSL fetch failed (transaction rolled back to savepoint): {e}")

    @api.model_create_multi
    def create(self, vals_list):
        res = super(HrAttendance, self).create(vals_list)
        for record in res:
            if record.half_day_leave:
                record._create_half_day_leave()
        return res

    def write(self, vals):
        res = super(HrAttendance, self).write(vals)
        if 'half_day_leave' in vals:
            for record in self:
                if vals['half_day_leave']:
                    record._create_half_day_leave()
                else:
                    record._remove_half_day_leave()
        return res

    def _create_half_day_leave(self):
        if 'hr.leave' not in self.env:
            return
        
        for attendance in self:
            employee = attendance.employee_id
            timezone_name = self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.timezone') or 'Asia/Kolkata'
            try:
                local_tz = pytz.timezone(timezone_name)
            except Exception:
                local_tz = pytz.timezone('Asia/Kolkata')
            
            check_in_local = pytz.utc.localize(attendance.check_in).astimezone(local_tz)
            date_local = check_in_local.date()

            # Check if leave already exists
            existing_leave = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id),
                ('request_date_from', '=', date_local),
                ('state', '!=', 'refuse')
            ], limit=1)
            if existing_leave:
                _logger.info(f"Half-day leave already exists for {employee.name} on {date_local}")
                continue

            leave_type = self.env['hr.leave.type'].sudo().search([
                ('active', '=', True),
                ('unpaid', '=', True)
            ], limit=1)
            if not leave_type:
                leave_type = self.env['hr.leave.type'].sudo().search([
                    ('active', '=', True),
                    ('name', 'ilike', 'unpaid')
                ], limit=1)
            if not leave_type:
                leave_type = self.env['hr.leave.type'].sudo().search([('active', '=', True)], limit=1)
            if not leave_type:
                _logger.warning("No active leave type found to create half-day leave.")
                continue

            try:
                vals = {
                    'employee_id': employee.id,
                    'holiday_status_id': leave_type.id,
                    'request_date_from': date_local,
                    'request_date_to': date_local,
                    'request_unit_half': True,
                    'request_date_from_period': 'am',
                    'name': 'Auto-created half-day leave due to late eSSL punch',
                }
                leave = self.env['hr.leave'].sudo().create(vals)
                if hasattr(leave, 'action_confirm') and leave.state == 'draft':
                    leave.action_confirm()
                _logger.info(f"Auto-created half-day leave for {employee.name} on {date_local} (Leave ID: {leave.id})")
            except Exception as e:
                _logger.error(f"Failed to auto-create half-day leave for {employee.name} on {date_local}: {e}")

    def _remove_half_day_leave(self):
        if 'hr.leave' not in self.env:
            return
        for attendance in self:
            if attendance.check_in and attendance.employee_id:
                timezone_name = self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.timezone') or 'Asia/Kolkata'
                try:
                    local_tz = pytz.timezone(timezone_name)
                except Exception:
                    local_tz = pytz.timezone('Asia/Kolkata')
                check_in_local = pytz.utc.localize(attendance.check_in).astimezone(local_tz)
                date_local = check_in_local.date()
                existing_leaves = self.env['hr.leave'].sudo().search([
                    ('employee_id', '=', attendance.employee_id.id),
                    ('request_date_from', '=', date_local),
                    ('name', '=', 'Auto-created half-day leave due to late eSSL punch')
                ])
                for leave in existing_leaves:
                    try:
                        if leave.state not in ('draft', 'refuse'):
                            leave.write({'state': 'draft'})
                        leave.unlink()
                        _logger.info(f"Removed auto-created half-day leave for {attendance.employee_id.name} on {date_local}")
                    except Exception as e:
                        _logger.warning(f"Could not remove auto-created leave for {attendance.employee_id.name}: {e}")

    @api.depends('check_in', 'check_out', 'half_day_leave', 'employee_id')
    def _compute_worked_hours(self):
        timezone_name = self.env['ir.config_parameter'].sudo().get_param('em_essl_attendance.timezone') or 'Asia/Kolkata'
        try:
            local_tz = pytz.timezone(timezone_name)
        except Exception:
            local_tz = pytz.timezone('Asia/Kolkata')

        for attendance in self:
            if attendance.check_in and attendance.check_out and attendance.employee_id:
                check_in_local = pytz.utc.localize(attendance.check_in).astimezone(local_tz)
                date_local = check_in_local.date()

                # Find if employee has a shift
                shift = None
                assignment = self.env['essl.shift.assignment'].sudo().search([
                    ('employee_id', '=', attendance.employee_id.id),
                    ('active', '=', True)
                ], limit=1)
                if assignment:
                    shift = assignment.shift_id
                elif attendance.employee_id.department_id:
                    shift = self.env['essl.shift'].sudo().search([
                        ('department_ids', 'in', attendance.employee_id.department_id.id)
                    ], limit=1)

                if shift:
                    check_out_local = pytz.utc.localize(attendance.check_out).astimezone(local_tz)
                    shift_end_hour = shift.end_time
                    shift_start_hour = shift.start_time
                    
                    end_dt = datetime.combine(date_local, datetime.min.time()) + timedelta(hours=shift_end_hour)
                    if shift_start_hour >= shift_end_hour:
                        end_dt += timedelta(days=1)
                    
                    end_dt = local_tz.localize(end_dt)
                    
                    if check_out_local >= end_dt and not attendance.half_day_leave:
                        attendance.worked_hours = 8.0
                        continue

                half_day_leave_approved = False
                if 'hr.leave' in self.env:
                    half_day_leave_approved = bool(self.env['hr.leave'].sudo().search_count([
                        ('employee_id', '=', attendance.employee_id.id),
                        ('request_date_from', '=', date_local),
                        ('state', '=', 'validate'),
                        ('request_unit_half', '=', True)
                    ]))

                if attendance.half_day_leave or half_day_leave_approved:
                    attendance.worked_hours = 4.0
                else:
                    attendance.worked_hours = 8.0
            else:
                attendance.worked_hours = 0.0

    @api.depends('worked_hours')
    def _compute_overtime_hours(self):
        for attendance in self:
            attendance.overtime_hours = 0.0

    def _update_overtime(self, employee_attendance_dates=None):
        return

