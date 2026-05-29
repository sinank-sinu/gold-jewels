# -*- coding: utf-8 -*-
import logging
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = 30


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    # Link to Branch Terminal configuration
    pinelabs_terminal_id = fields.Many2one('pinelabs.terminal', string='Pine Labs Terminal',
                                           domain="[('active', '=', True)]",
                                           help='Select the terminal configuration for this POS.')
    pinelabs_payment_mode = fields.Selection([
        ('1', 'Card (Credit/Debit)'),
        ('3', 'UPI'),
        ('4', 'Net Banking'),
        ('7', 'Wallet'),
        ('10', 'EMI'),
        ('1,3', 'Card + UPI'),
    ], string='Pine Labs Payment Mode', default='1',
        help='AllowedPaymentMode sent to Pine Labs terminal')

    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [('pine_labs', 'Pine Labs Terminal')]

    # ─────────────────────────────────────────────────────────────────
    # Methods called by the POS JS layer via RPC
    # ─────────────────────────────────────────────────────────────────

    def _pinelabs_get_config(self):
        """Return effective Pine Labs config for this payment method."""
        if not self.pinelabs_terminal_id:
            raise UserError(_('Pine Labs Terminal is not configured for this payment method.'))
        return self.pinelabs_terminal_id.get_config()

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
            return response.json()
        except requests.exceptions.Timeout:
            _logger.warning('Pine Labs request timed out: %s', url)
            return {'error': _('Pine Labs terminal request timed out.')}
        except requests.exceptions.RequestException as e:
            _logger.warning('Pine Labs request failed: %s', e)
            return {'error': str(e)}
        except ValueError:
            return {'error': _('Invalid response from Pine Labs server.')}

    def pinelabs_initiate_payment(self, amount, billing_ref_no):
        """
        Called from POS JS to send a payment request to the Pine Labs terminal
        via UploadBilledTransaction. Returns a dict with PlutusTransactionReferenceID or error.
        """
        self.ensure_one()
        config = self._pinelabs_get_config()

        if config.get('demo_mode'):
            _logger.info('Pine Labs DEMO initiate_payment: %s', amount)
            return {'PlutusTransactionReferenceID': f"DEMO-{billing_ref_no}"}

        if not config['merchant_id'] or not config['security_token']:
            return {'error': _('Pine Labs is not configured. Please check Settings.')}

        url = f"{config['base_url']}/UploadBilledTransaction"

        # Amount must be in paise (rupees × 100) — e.g. ₹100 = 10000
        payment_mode = self.pinelabs_payment_mode or '1'
        payload = {
            "TransactionNumber": billing_ref_no,
            "SequenceNumber": 1,
            "AllowedPaymentMode": payment_mode,
            "Amount": int(round(float(amount) * 100)),
            "ClientID": config['client_id'],
            "StoreID": config['store_id'],
            "UserID": "",
            "MerchantID": config['merchant_id'],
            "SecurityToken": config['security_token'],
            "AutoCancelDurationInMinutes": 5,
        }

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs UploadBilledTransaction response: %s', response)
        return response

    def pinelabs_fetch_payment_status(self, plutus_transaction_ref_id):
        """
        Called repeatedly by POS JS to poll the terminal status
        via GetCloudBasedTxnStatus. Returns status dict or error.
        """
        self.ensure_one()
        config = self._pinelabs_get_config()

        if config.get('demo_mode') and str(plutus_transaction_ref_id).startswith('DEMO-'):
            _logger.info('Pine Labs DEMO fetch_payment_status for: %s', plutus_transaction_ref_id)
            return {
                'status': 'success',
                'approval_code': 'DEMO123',
                'card_type': 'CREDIT',
                'payment_mode': 'DEMO CARD',
                'card_number_masked': '1234xxxx5678',
                'issuer_bank': 'DEMO BANK',
                'rrn': '987654321',
                'batch_number': '0001',
                'txn_status_msg': 'Demo Success',
            }

        url = f"{config['base_url']}/GetCloudBasedTxnStatus"

        payload = {
            "MerchantID": config['merchant_id'],
            "SecurityToken": config['security_token'],
            "ClientID": config['client_id'],
            "StoreID": config['store_id'],
            "PlutusTransactionReferenceID": plutus_transaction_ref_id,
        }

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs GetCloudBasedTxnStatus response: %s', response)
        return self._parse_status_response(response)

    def pinelabs_cancel_payment(self, plutus_transaction_ref_id, amount):
        """
        Called from POS JS to cancel a pending transaction
        via CancelTransaction. Returns response dict.
        """
        self.ensure_one()
        config = self._pinelabs_get_config()

        if config.get('demo_mode') and str(plutus_transaction_ref_id).startswith('DEMO-'):
            _logger.info('Pine Labs DEMO cancel_payment for: %s', plutus_transaction_ref_id)
            return {'status': 'cancelled'}

        url = f"{config['base_url']}/CancelTransaction"

        payload = {
            "MerchantID": config['merchant_id'],
            "SecurityToken": config['security_token'],
            "ClientID": config['client_id'],
            "StoreID": config['store_id'],
            "PlutusTransactionReferenceID": plutus_transaction_ref_id,
            "Amount": int(round(float(amount) * 100)),  # Pine Labs expects paise (rupees × 100)
        }

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs CancelTransaction response: %s', response)
        return response

    def _parse_status_response(self, response):
        """Parse a status response and return a normalized dict for the JS layer."""
        if response.get('error'):
            return response
        txn_data = response.get('TransactionData')
        if not txn_data:
            return {'status': 'pending', 'raw': response}
        detail = txn_data[0] if isinstance(txn_data, list) else txn_data
        txn_status = str(detail.get('TxnStatus', ''))
        if txn_status in ('0', '0000'):
            return {
                'status': 'success',
                'approval_code': detail.get('ApprovalCode', ''),
                'card_type': detail.get('CardType', ''),
                'payment_mode': detail.get('TxnModeName', ''),
                'card_number_masked': detail.get('CardNumberMasked', ''),
                'issuer_bank': detail.get('IssuingBankName', ''),
                'rrn': detail.get('RRN', ''),
                'batch_number': detail.get('BatchNumber', ''),
                'txn_status_msg': detail.get('TxnStatusMsg', ''),
            }
        elif txn_status in ('', 'None'):
            return {'status': 'pending'}
        else:
            return {'status': 'failed', 'message': detail.get('TxnStatusMsg', 'Transaction declined')}
