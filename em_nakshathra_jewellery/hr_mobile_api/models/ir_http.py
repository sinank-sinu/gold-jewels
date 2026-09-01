from odoo import models
from odoo.exceptions import AccessDenied, AccessError
from odoo.http import request

class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _authenticate(cls, endpoint):
        auth = endpoint.routing.get('auth') if endpoint and hasattr(endpoint, 'routing') and isinstance(endpoint.routing, dict) else 'none'
        if auth in ('none', 'public') and getattr(request, 'session', None) and request.session.uid:
            try:
                super()._authenticate(endpoint)
            except (AccessDenied, AccessError, Exception):
                request.session.logout(keep_db=True)
                super()._authenticate(endpoint)
        else:
            super()._authenticate(endpoint)
