import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class EsslApiController(http.Controller):

    @http.route('/api/essl/attendance', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def api_essl_attendance(self, **kwargs):
        # Parse params from request body if content-type is json
        params = {}
        if request.httprequest.headers.get('Content-Type') == 'application/json':
            try:
                params = json.loads(request.httprequest.data.decode('utf-8'))
            except Exception:
                pass
        
        # Merge kwargs (GET/POST params) with JSON params
        merged_params = {**params, **kwargs}
        
        # Extract variables
        from_date = merged_params.get('FromDateTime') or merged_params.get('from_date')
        to_date = merged_params.get('ToDateTime') or merged_params.get('to_date')
        serial_number = merged_params.get('SerialNumber') or merged_params.get('serial_number')
        username = merged_params.get('UserName') or merged_params.get('username')
        password = merged_params.get('UserPassword') or merged_params.get('password')
        
        # sync parameter
        sync_param = merged_params.get('sync', 'false')
        do_sync = sync_param in [True, 1, '1', 'true', 'True']

        # Get the hr.attendance model with sudo
        Attendance = request.env['hr.attendance'].sudo()

        try:
            # We call the model method to fetch and parse the data
            result = Attendance.fetch_and_parse_essl_logs(
                from_date_str=from_date,
                to_date_str=to_date,
                serial_number=serial_number,
                username=username,
                password=password,
                do_sync=do_sync
            )
            
            response_data = {
                'status': 'success',
                'count': len(result.get('attendances', [])),
                'attendances': result.get('attendances', []),
                'raw_logs': result.get('raw_logs', [])
            }
            if do_sync:
                response_data['synced_count'] = result.get('synced_count', 0)
                
            return request.make_response(
                json.dumps(response_data),
                headers=[
                    ('Content-Type', 'application/json'),
                    ('Access-Control-Allow-Origin', '*')
                ]
            )
        except Exception as e:
            _logger.exception("Error in api_essl_attendance controller")
            return request.make_response(
                json.dumps({
                    'status': 'error',
                    'message': str(e)
                }),
                status=500,
                headers=[
                    ('Content-Type', 'application/json'),
                    ('Access-Control-Allow-Origin', '*')
                ]
            )
