import logging
import random
from datetime import timedelta
from odoo import http, fields, _
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.utils import ensure_db

_logger = logging.getLogger(__name__)

class HomeOTP(Home):

    @http.route('/web/login', type='http', auth="public", website=True, sitemap=False)
    def web_login(self, redirect=None, **kw):
        if request.httprequest.method != 'POST':
            return super().web_login(redirect=redirect, **kw)

        ensure_db()
        request.params['login_success'] = False

        login = request.params.get('login')
        password = request.params.get('password')

        if not login or not password:
            return super().web_login(redirect=redirect, **kw)

        try:
            uid = request.session.authenticate(request.db, login, password)
            user = request.env['res.users'].sudo().browse(uid)
            
            mobile = False
            if user.is_otp_required:
                mobile = user.partner_id.mobile or user.partner_id.phone
                if not mobile and user.employee_id:
                    mobile = user.employee_id.mobile_phone or user.employee_id.work_phone

            if mobile:
                otp = f"{random.randint(100000, 999999)}"
                expiry = fields.Datetime.now() + timedelta(minutes=1)
                
                user.write({
                    'login_otp': otp,
                    'login_otp_expiry': expiry
                })
                
                user._send_login_otp_sms(otp)
                
                request.session.pre_uid = uid
                request.session.pre_login = login
                request.session.uid = None
                
                otp_url = '/web/login/otp'
                if redirect:
                    otp_url += f'?redirect={redirect}'
                return request.redirect(otp_url)
            else:
                request.params['login_success'] = True
                return request.redirect(self._login_redirect(uid, redirect=redirect))

        except AccessDenied:
            return super().web_login(redirect=redirect, **kw)

    @http.route('/web/login/otp', type='http', auth='public', methods=['GET', 'POST'], website=True, sitemap=False)
    def web_login_otp(self, redirect=None, **kwargs):
        if not request.session.pre_uid:
            return request.redirect('/web/login')

        if request.session.uid:
            return request.redirect(self._login_redirect(request.session.uid, redirect=redirect))

        error = None
        user = request.env['res.users'].sudo().browse(request.session.pre_uid)

        if request.httprequest.method == 'POST' and kwargs.get('otp_token'):
            entered_otp = kwargs.get('otp_token').strip()
            
            if user.login_otp and user.login_otp == entered_otp:
                if user.login_otp_expiry and user.login_otp_expiry >= fields.Datetime.now():
                    user.write({
                        'login_otp': False,
                        'login_otp_expiry': False
                    })
                    
                    request.session.finalize(request.env)
                    request.update_env(user=request.session.uid)
                    request.update_context(**request.session.context)
                    
                    return request.redirect(self._login_redirect(request.session.uid, redirect=redirect))
                else:
                    error = _("OTP is expired. Please try logging in again.")
            else:
                error = _("Wrong OTP. Please try again.")

        request.session.touch()

        return request.render('em_otp_login.auth_otp_form', {
            'user': user,
            'error': error,
            'redirect': redirect,
        })
