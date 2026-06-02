# -*- coding: utf-8 -*-
import logging
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = 30


class PineLabsTerminal(models.Model):
    """Branch-wise Pine Labs terminal configuration.
    Each branch can have up to 2 terminals (primary + secondary).
    Access restricted to Administrators only.
    """
    _name = 'pinelabs.terminal'
    _description = 'Pine Labs Terminal'
    _order = 'branch_id, sequence'

    name = fields.Char(string='Terminal Name', required=True,
                       help='E.g. "HO Counter 1", "Branch Counter 2"')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)

    branch_id = fields.Many2one(
        'res.branch',
        string='Branch',
        required=True,
        ondelete='restrict',
    )

    # ── Pine Labs credentials (override company defaults) ──────────────
    merchant_id = fields.Char(string='Merchant ID', required=True)
    security_token = fields.Char(string='Security Token', required=True)
    client_id = fields.Char(string='Client ID', required=True)
    store_id = fields.Char(string='Store ID', required=True)
    terminal_id = fields.Char(string='Terminal ID')

    base_url = fields.Char(
        string='API Base URL',
        default='https://instore-ism.uat.pinelabs.com/api/CloudBasedIntegration/V1',
        help='Leave blank to inherit from company settings.',
    )
    demo_mode = fields.Boolean(
        string='Demo Mode (Mock API)',
        default=False,
        help='If enabled, no real requests are sent to Pine Labs. Instead, successful transactions are mocked.',
    )
    is_production = fields.Boolean(
        string='Production Mode',
        default=False,
        help='If enabled, uses PROD URL. Otherwise UAT URL is used.',
    )
    auto_cancel_minutes = fields.Integer(
        string='Auto Cancel (minutes)',
        default=5,
    )

    # ── Accounting Mappings ────────────────────────────────────────────
    card_journal_id = fields.Many2one(
        'account.journal',
        string='Card Payment Journal',
        domain="[('type', 'in', ('bank', 'cash'))]",
        help='Journal used for automatic posting of Card payments from this terminal.',
    )
    upi_journal_id = fields.Many2one(
        'account.journal',
        string='UPI Payment Journal',
        domain="[('type', 'in', ('bank', 'cash'))]",
        help='Journal used for automatic posting of UPI payments from this terminal.',
    )

    # ── Constraints ────────────────────────────────────────────────────
    _sql_constraints = [
        ('name_branch_unique', 'UNIQUE(name, branch_id)',
         'A terminal with this name already exists for this branch.'),
    ]

    @api.constrains('branch_id')
    def _check_max_two_per_branch(self):
        for rec in self:
            count = self.search_count([
                ('branch_id', '=', rec.branch_id.id),
                ('id', '!=', rec.id),
                ('active', '=', True),
            ])
            if count >= 2:
                raise UserError(
                    _('Each branch can have a maximum of 2 Pine Labs terminals. '
                      'Branch "%s" already has 2 active terminals.') % rec.branch_id.name
                )

    def _get_effective_base_url(self):
        """Return sanitized base URL (strip any accidentally appended endpoint)."""
        self.ensure_one()
        base = (self.base_url or
                'https://instore-ism.uat.pinelabs.com/api/CloudBasedIntegration/V1').rstrip('/')
        if self.is_production:
            base = base.replace('instore-ism.uat.pinelabs.com', 'instore-ism.pinelabs.com')
        for _ep in ['/UploadBilledTransaction', '/GetCloudBasedTxnStatus', '/CancelTransaction']:
            if base.endswith(_ep):
                base = base[:-len(_ep)]
                break
        return base

    def get_config(self):
        """Return a config dict ready for API calls."""
        self.ensure_one()
        return {
            'merchant_id': self.merchant_id,
            'security_token': self.security_token,
            'client_id': self.client_id,
            'store_id': self.store_id,
            'terminal_id': self.terminal_id or '',
            'base_url': self._get_effective_base_url(),
            'auto_cancel_minutes': self.auto_cancel_minutes,
            'demo_mode': self.demo_mode,
        }

    def action_test_connection(self):
        """Quick connectivity test — sends a dummy GetCloudBasedTxnStatus."""
        self.ensure_one()
        config = self.get_config()
        url = f"{config['base_url']}/GetCloudBasedTxnStatus"
        payload = {
            "MerchantID": self.merchant_id,
            "SecurityToken": self.security_token,
            "ClientID": self.client_id,
            "StoreID": self.store_id,
            "PlutusTransactionReferenceID": 0,
        }
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT,
                                 headers={'Content-Type': 'application/json'})
            _logger.info('Pine Labs Terminal test response: %s %s', resp.status_code, resp.text[:200])
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Test'),
                    'message': _('Response: %s — %s') % (resp.status_code, resp.text[:100]),
                    'type': 'success' if resp.status_code == 200 else 'warning',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Failed'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }
