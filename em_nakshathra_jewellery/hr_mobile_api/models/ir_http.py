# -*- coding: utf-8 -*-
import json
import logging
from odoo import models
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        path = request.httprequest.path
        if path.startswith('/api/scheme'):
            try:
                request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'scheme_api.is_enabled'")
                row = request.env.cr.fetchone()
                if row and row[0] is not None:
                    is_enabled_val = row[0]
                else:
                    request.env.cr.execute("SELECT is_enabled FROM scheme_api_control LIMIT 1")
                    ctrl_row = request.env.cr.fetchone()
                    is_enabled_val = str(ctrl_row[0]) if ctrl_row and ctrl_row[0] is not None else 'True'
            except Exception as e:
                _logger.warning("Error checking Scheme API status parameter: %s", e)
                is_enabled_val = 'True'

            if str(is_enabled_val).strip().lower() in ('false', '0', 'off', 'no'):
                try:
                    request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'scheme_api.disabled_message'")
                    msg_row = request.env.cr.fetchone()
                    disabled_msg = msg_row[0] if msg_row and msg_row[0] else 'Gold Scheme API is currently disabled for maintenance. Please try again later.'
                except Exception:
                    disabled_msg = 'Gold Scheme API is currently disabled for maintenance. Please try again later.'

                _logger.info("Scheme API request to '%s' blocked (Scheme API is disabled).", path)

                dispatcher = getattr(request, 'dispatcher', None)
                routing_type = getattr(dispatcher, 'routing_type', 'json')

                if routing_type == 'json':
                    return {
                        "status": "error",
                        "code": "API_DISABLED",
                        "message": disabled_msg,
                        "api_enabled": False,
                    }
                else:
                    return Response(
                        json.dumps({
                            "status": "error",
                            "code": "API_DISABLED",
                            "message": disabled_msg,
                            "api_enabled": False,
                        }),
                        status=503,
                        headers={
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*',
                        },
                    )

        elif path.startswith('/api/task_manager'):
            try:
                request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'task_manager_api.is_enabled'")
                row = request.env.cr.fetchone()
                is_enabled_val = row[0] if row and row[0] is not None else 'True'
            except Exception as e:
                _logger.warning("Error checking Task Manager API status parameter: %s", e)
                is_enabled_val = 'True'

            if str(is_enabled_val).strip().lower() in ('false', '0', 'off', 'no'):
                try:
                    request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'task_manager_api.disabled_message'")
                    msg_row = request.env.cr.fetchone()
                    disabled_msg = msg_row[0] if msg_row and msg_row[0] else 'Task Manager API is currently disabled for maintenance. Please try again later.'
                except Exception:
                    disabled_msg = 'Task Manager API is currently disabled for maintenance. Please try again later.'

                _logger.info("Task Manager API request to '%s' blocked (Task Manager API is disabled).", path)

                dispatcher = getattr(request, 'dispatcher', None)
                routing_type = getattr(dispatcher, 'routing_type', 'json')

                if routing_type == 'json':
                    return {
                        "status": "error",
                        "code": "API_DISABLED",
                        "message": disabled_msg,
                        "api_enabled": False,
                    }
                else:
                    return Response(
                        json.dumps({
                            "status": "error",
                            "code": "API_DISABLED",
                            "message": disabled_msg,
                            "api_enabled": False,
                        }),
                        status=503,
                        headers={
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*',
                        },
                    )

        elif path.startswith('/api/hr'):
            try:
                request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'hrms_api.is_enabled'")
                row = request.env.cr.fetchone()
                is_enabled_val = row[0] if row and row[0] is not None else 'True'
            except Exception as e:
                _logger.warning("Error checking HRMS API status parameter: %s", e)
                is_enabled_val = 'True'

            if str(is_enabled_val).strip().lower() in ('false', '0', 'off', 'no'):
                try:
                    request.env.cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'hrms_api.disabled_message'")
                    msg_row = request.env.cr.fetchone()
                    disabled_msg = msg_row[0] if msg_row and msg_row[0] else 'HRMS API is currently disabled for maintenance. Please try again later.'
                except Exception:
                    disabled_msg = 'HRMS API is currently disabled for maintenance. Please try again later.'

                _logger.info("HRMS API request to '%s' blocked (HRMS API is disabled).", path)

                dispatcher = getattr(request, 'dispatcher', None)
                routing_type = getattr(dispatcher, 'routing_type', 'json')

                if routing_type == 'json':
                    return {
                        "status": "error",
                        "code": "API_DISABLED",
                        "message": disabled_msg,
                        "api_enabled": False,
                    }
                else:
                    return Response(
                        json.dumps({
                            "status": "error",
                            "code": "API_DISABLED",
                            "message": disabled_msg,
                            "api_enabled": False,
                        }),
                        status=503,
                        headers={
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*',
                        },
                    )

        return super()._dispatch(endpoint)
