import hashlib
import os
import secrets
import datetime

from odoo import models, fields, api


class EcommerceCustomer(models.Model):
    """Stores e-commerce website customers (separate from internal Odoo users)."""
    _name = 'ecommerce.customer'
    _description = 'Ecommerce Website Customer'
    _rec_name = 'email'

    first_name = fields.Char(string='First Name', required=True)
    last_name = fields.Char(string='Last Name', required=True)
    name = fields.Char(string='Full Name', compute='_compute_name', store=True)
    email = fields.Char(string='Email', required=True, index=True)
    phone = fields.Char(string='Phone')
    city = fields.Char(string='City')
    password_hash = fields.Char(string='Password Hash')
    password_salt = fields.Char(string='Password Salt')
    auth_token = fields.Char(string='Authentication Token')
    token_expiry = fields.Datetime(string='Token Expiry')
    login_otp = fields.Char(string='Login OTP', copy=False)
    login_otp_expiry = fields.Datetime(string='Login OTP Expiry', copy=False)
    active = fields.Boolean(default=True)
    created_at = fields.Datetime(string='Registered On', default=fields.Datetime.now)
    address_ids = fields.One2many('ecommerce.address', 'customer_id', string='Saved Addresses')
    currency_id = fields.Many2one('res.currency', string='Preferred Currency')
    branch_id = fields.Many2one('res.branch', string='Preferred Branch')
    card_ids = fields.One2many('ecommerce.card', 'customer_id', string='Saved Cards')
    upi_ids = fields.One2many('ecommerce.upi', 'customer_id', string='Saved UPI Profiles')


    push_notifications = fields.Boolean(string='Push Notifications Preference', default=True)
    order_updates = fields.Boolean(string='Order Updates Preference', default=True)
    offer_alerts = fields.Boolean(string='Offer Alerts Preference', default=True)
    email_newsletter = fields.Boolean(string='Email Newsletter Preference', default=True)
    referral_code = fields.Char(string='Referral Code', compute='_compute_referral_code')
    referral_earning = fields.Float(string='Referral Earnings (₹)', compute='_compute_referral_earning')
    referred_by_id = fields.Many2one('ecommerce.customer', string='Referred By')
    review_ids = fields.One2many('ecommerce.product.review', 'customer_id', string='Reviews')
    referral_ids = fields.One2many('ecommerce.referral', 'referrer_id', string='Referrals')

    def _compute_referral_code(self):
        for rec in self:
            if rec.id:
                rec.referral_code = f"NAKSH-SHINE-{rec.id + 73}"
            else:
                rec.referral_code = "NAKSH-SHINE-77"

    def _compute_referral_earning(self):
        for rec in self:
            rec.referral_earning = sum(ref.coupon_value for ref in rec.referral_ids if ref.status in ('joined', 'shipped'))

    _sql_constraints = [
        ('email_unique', 'UNIQUE(email)', 'A customer with this email already exists.')
    ]

    @api.depends('first_name', 'last_name')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.first_name or ''} {rec.last_name or ''}".strip()

    def _hash_password(self, password, salt=None):
        """Hash a password with a random salt using SHA-256."""
        if not salt:
            salt = os.urandom(16).hex()
        hashed = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        return hashed, salt

    def _verify_password(self, password):
        """Verify a plain-text password against the stored hash."""
        if not self.password_hash or not self.password_salt:
            return False
        hashed, _ = self._hash_password(password, self.password_salt)
        return hashed == self.password_hash

    def _generate_token(self):
        """Generate a secure authentication token."""
        token = secrets.token_urlsafe(32)
        # Set token expiry to 30 days from now
        expiry = datetime.datetime.now() + datetime.timedelta(days=30)
        self.write({
            'auth_token': token,
            'token_expiry': expiry
        })
        return token

    def _verify_token(self, token):
        """Verify an authentication token."""
        if not self.auth_token:
            return False
        if self.auth_token != token:
            return False
        if self.token_expiry and self.token_expiry < datetime.datetime.now():
            return False
        return True

    def _revoke_token(self):
        """Revoke the current authentication token."""
        self.write({
            'auth_token': None,
            'token_expiry': None
        })
