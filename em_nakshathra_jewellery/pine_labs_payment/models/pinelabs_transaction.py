# -*- coding: utf-8 -*-
import logging
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30


class PineLabsTransaction(models.Model):
    _name = 'pinelabs.transaction'
    _description = 'Pine Labs Transaction'
    _order = 'create_date desc'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Transaction Reference', required=True, copy=False, default=lambda self: _('New'))
    amount = fields.Float(string='Amount', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: self.env.company.currency_id)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting', 'Waiting Terminal'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ], string='Status', default='draft', copy=False, tracking=True)

    # Transaction details from Pine Labs
    pinelabs_transaction_id = fields.Char(string='Pine Labs Transaction ID', copy=False)
    approval_code = fields.Char(string='Approval Code', copy=False)
    card_type = fields.Char(string='Card Type', copy=False)  # CREDIT, DEBIT, UPI
    payment_mode = fields.Char(string='Payment Mode', copy=False)  # CARD, UPI, NB
    response_log = fields.Text(string='Response Log', copy=False)
    retrieval_reference_number = fields.Char(string='Retrieval Reference No.', copy=False)
    batch_number = fields.Char(string='Batch Number', copy=False)
    card_number_masked = fields.Char(string='Card No. (Masked)', copy=False)
    issuer_bank = fields.Char(string='Issuer Bank', copy=False)
    payment_date = fields.Datetime(string='Payment Date', copy=False)

    # Linked records
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', copy=False)
    invoice_id = fields.Many2one('account.move', string='Invoice', copy=False)
    payment_id = fields.Many2one('account.payment', string='Payment', copy=False)
    pos_order_id = fields.Many2one('pos.order', string='POS Order', copy=False)

    # Configuration snapshot
    merchant_id = fields.Char(string='Merchant ID Used')
    terminal_id = fields.Char(string='Terminal ID Used')
    pinelabs_terminal_id = fields.Many2one('pinelabs.terminal', string='Terminal Record')

    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', string='Created By',
                              default=lambda self: self.env.user)

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('pinelabs.transaction') or _('New')
        return super().create(vals)

    def action_retry(self):
        """Mark as draft to allow retry."""
        self.ensure_one()
        if self.state in ('failed', 'cancelled'):
            self.state = 'draft'
        else:
            raise UserError(_('Only failed or cancelled transactions can be retried.'))

    def action_cancel(self):
        """Cancel the transaction."""
        self.ensure_one()
        if self.state in ('draft', 'waiting'):
            self.state = 'cancelled'
        else:
            raise UserError(_('Only draft or waiting transactions can be cancelled.'))

    # ─────────────────────────────────────────────────────────────────
    # Pine Labs Cloud API helpers
    # ─────────────────────────────────────────────────────────────────

    def _get_pinelabs_config(self):
        """Return Pine Labs credentials from the linked terminal."""
        if self.pinelabs_terminal_id:
            return self.pinelabs_terminal_id.get_config()

        raise UserError(
            _('Pine Labs Terminal is not linked to this transaction. '
              'Cannot connect to Pine Labs API.')
        )

    def _pinelabs_make_request(self, url, payload):
        """Make a POST request to the given Pine Labs Cloud API URL."""
        _logger.info('Pine Labs → POST %s | payload: %s', url, payload)
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=REQUEST_TIMEOUT,
                headers={'Content-Type': 'application/json'},
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            _logger.warning('Pine Labs request timed out: %s', url)
            return {'error': _('Connection to Pine Labs terminal timed out.')}
        except requests.exceptions.RequestException as e:
            _logger.warning('Pine Labs request error: %s | URL: %s', e, url)
            return {'error': str(e)}
        try:
            return response.json()
        except ValueError:
            return {'error': _('Invalid response from Pine Labs server.')}

    def pinelabs_create_payment(self, amount, allowed_mode='1'):
        """
        Initiate a payment on the Pine Labs terminal using UploadBilledTransaction.
        allowed_mode: '1'=Card, '3'=UPI, '4'=Net Banking, '7'=Wallet, '10'=EMI
        Returns the response dict.
        """
        self.ensure_one()
        config = self._get_pinelabs_config()

        if config.get('demo_mode'):
            _logger.info('Pine Labs DEMO create_payment: %s (mode=%s)', amount, allowed_mode)
            self.pinelabs_transaction_id = f"DEMO-TXN-{self.id}"
            self.merchant_id = 'DEMO_MERCHANT'
            self.terminal_id = 'DEMO_TERMINAL'
            self.response_log = "DEMO MODE INITIATE SUCCESS"
            self.state = 'waiting'
            return {'PlutusTransactionReferenceID': self.pinelabs_transaction_id}

        url = f"{config['base_url']}/UploadBilledTransaction"

        payload = {
            "TransactionNumber": self.name,
            "SequenceNumber": 1,
            "AllowedPaymentMode": allowed_mode,
            "Amount": int(round(amount * 100)),  # Pine Labs expects paise (rupees × 100)
            "ClientID": config['client_id'],
            "StoreID": config['store_id'],
            "UserID": "",
            "MerchantID": config['merchant_id'],
            "SecurityToken": config['security_token'],
            "AutoCancelDurationInMinutes": 5,
        }

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs UploadBilledTransaction response: %s', response)
        self.response_log = str(response)

        if response.get('error'):
            self.state = 'failed'
            return response

        # Pine Labs returns PlutusTransactionReferenceID (integer) on success
        ref_id = (response.get('PlutusTransactionReferenceID') or
                  response.get('plutusTransactionReferenceID'))
        if ref_id:
            self.pinelabs_transaction_id = str(ref_id)
            self.merchant_id = config['merchant_id']
            self.terminal_id = config['terminal_id']
            self.state = 'waiting'
        else:
            self.state = 'failed'
        return response

    def pinelabs_check_status(self):
        """Poll the Pine Labs terminal for transaction status using GetCloudBasedTxnStatus."""
        self.ensure_one()
        config = self._get_pinelabs_config()

        if (config.get('demo_mode') and
                self.pinelabs_transaction_id and
                str(self.pinelabs_transaction_id).startswith('DEMO')):
            self.write({
                'state': 'success',
                'approval_code': 'DEMO123',
                'card_type': 'CREDIT',
                'payment_mode': 'DEMO CARD',
                'card_number_masked': '1234xxxx5678',
                'issuer_bank': 'DEMO BANK',
                'retrieval_reference_number': '987654321',
                'batch_number': '0001',
                'payment_date': fields.Datetime.now(),
                'response_log': "DEMO MODE STATUS SUCCESS",
            })
            return {'status': 'success', 'data': {'TxnStatus': '0', 'TxnStatusMsg': 'Success'}}

        url = f"{config['base_url']}/GetCloudBasedTxnStatus"

        payload = {
            "MerchantID": config['merchant_id'],
            "SecurityToken": config['security_token'],
            "ClientID": config['client_id'],
            "StoreID": config['store_id'],
            "PlutusTransactionReferenceID": self.pinelabs_transaction_id,
        }

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs GetCloudBasedTxnStatus response: %s', response)
        self.response_log = str(response)
        return self._process_status_response(response)

    def _process_status_response(self, response):
        """Parse a Pine Labs status response and update the transaction record."""
        if response.get('error'):
            return response
        transaction_data = response.get('TransactionData')
        if not transaction_data:
            return {'status': 'pending'}
        detail = transaction_data[0] if isinstance(transaction_data, list) else transaction_data
        txn_status = str(detail.get('TxnStatus', ''))
        if txn_status in ('0000', '0'):  # Success
            self.write({
                'state': 'success',
                'approval_code': detail.get('ApprovalCode', ''),
                'card_type': detail.get('CardType', ''),
                'payment_mode': detail.get('TxnModeName', ''),
                'card_number_masked': detail.get('CardNumberMasked', ''),
                'issuer_bank': detail.get('IssuingBankName', ''),
                'retrieval_reference_number': detail.get('RRN', ''),
                'batch_number': detail.get('BatchNumber', ''),
                'payment_date': fields.Datetime.now(),
            })
            return {'status': 'success', 'data': detail}
        elif txn_status in ('', 'None'):
            return {'status': 'pending'}
        else:
            self.state = 'failed'
            return {'status': 'failed', 'message': detail.get('TxnStatusMsg', 'Transaction failed')}

    def pinelabs_cancel_payment(self):
        """Cancel a pending Pine Labs transaction using CancelTransaction."""
        self.ensure_one()
        config = self._get_pinelabs_config()

        if (config.get('demo_mode') and
                self.pinelabs_transaction_id and
                str(self.pinelabs_transaction_id).startswith('DEMO')):
            self.state = 'cancelled'
            self.response_log = "DEMO MODE CANCEL SUCCESS"
            return {'status': 'cancelled'}

        url = f"{config['base_url']}/CancelTransaction"

        payload = {
            "MerchantID": config['merchant_id'],
            "SecurityToken": config['security_token'],
            "ClientID": config['client_id'],
            "StoreID": config['store_id'],
            "PlutusTransactionReferenceID": self.pinelabs_transaction_id,
            "Amount": int(round(self.amount * 100)),  # Pine Labs expects paise (rupees × 100)
        }

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs CancelTransaction response: %s', response)
        self.response_log = str(response)
        if not response.get('error'):
            self.state = 'cancelled'
        return response
