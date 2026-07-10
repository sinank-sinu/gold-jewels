import hashlib
import os

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
    active = fields.Boolean(default=True)
    created_at = fields.Datetime(string='Registered On', default=fields.Datetime.now)

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
