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
        ('10', 'UPI'),
        ('3', 'Points Redemption'),
        ('4', 'Net Banking'),
        ('7', 'Wallet'),
        ('6', 'Brand EMI'),
        ('1,10', 'Card + UPI'),
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

        import re
        clean_txn_number = re.sub(r'[^A-Za-z0-9]', '', str(billing_ref_no or ''))
        if not clean_txn_number:
            clean_txn_number = f"POS{int(time.time())}"

        # Payment Mode: '1' for Card, '10' for UPI Sale
        payment_mode = self.pinelabs_payment_mode
        if not payment_mode:
            payment_mode = '10' if 'UPI' in (self.name or '').upper() else '1'
        mode_val = int(payment_mode) if str(payment_mode).isdigit() else payment_mode
        if mode_val == 10 and float(amount) < 1.0:
            return {'error': _('Minimum amount for Pine Labs UPI payment is ₹1.00 (100 paise). Please enter an amount of at least ₹1.00.')}
        user_id = config.get('user_id') or self.env.user.name or self.env.user.login or ''

        payload = {
            "MerchantID": str(config['merchant_id']),
            "SecurityToken": str(config['security_token']),
            "TransactionNumber": clean_txn_number,
            "SequenceNumber": 1,
            "AllowedPaymentMode": mode_val,
            "MerchantStorePosCode": str(config.get('merchant_store_pos_code') or config.get('store_id') or ''),
            "Amount": int(round(float(amount) * 100)),
            "UserID": str(user_id),
            "IMEI": str(config.get('imei') or config.get('terminal_id') or ''),
        }

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs UploadBilledTransaction response: %s', response)

        # If terminal returns TXN ALREADY COMPLETED, retry with fresh unique TransactionNumber and SequenceNumber 1
        if (resp_code is not None and str(resp_code) != '0' and
                'ALREADY COMPLETED' in resp_msg.upper()):
            payload['TransactionNumber'] = f"{clean_txn_number[:12]}{str(int(time.time()))[-6:]}"
            payload['SequenceNumber'] = 1
            time.sleep(1)
            response = self._pinelabs_make_request(url, payload)
            _logger.info('Pine Labs POS retry response: %s', response)
            resp_code = response.get('ResponseCode')
            resp_msg = str(response.get('ResponseMessage', ''))

        # Handle stuck open transaction auto-cancel
        if resp_code is not None and str(resp_code) != '0' and ('OPEN TXN' in resp_msg.upper() or 'APPROVE' in resp_msg.upper()):
            existing_ref = None
            existing_amt = None
            add_info = response.get('AdditionalInfo') or []
            if isinstance(add_info, list):
                for item in add_info:
                    if isinstance(item, dict):
                        if item.get('Tag') == 'ExistingReferenceId':
                            existing_ref = item.get('Value')
                        elif item.get('Tag') == 'Amount':
                            existing_amt = item.get('Value')
            if existing_ref:
                try:
                    plutus_cancel_id = int(existing_ref)
                except (TypeError, ValueError):
                    plutus_cancel_id = existing_ref

                try:
                    cancel_amt = int(existing_amt) if existing_amt else int(round(float(amount) * 100))
                except (TypeError, ValueError):
                    cancel_amt = int(round(float(amount) * 100))

                cancel_url = f"{config['base_url']}/CancelTransaction"
                cancel_payload = {
                    "MerchantID": str(config['merchant_id']),
                    "SecurityToken": str(config['security_token']),
                    "PlutusTransactionReferenceID": plutus_cancel_id,
                    "Amount": cancel_amt,
                }
                if config.get('merchant_store_pos_code'):
                    cancel_payload["MerchantStorePosCode"] = str(config['merchant_store_pos_code'])
                elif config.get('store_id'):
                    cancel_payload["StoreID"] = str(config['store_id'])

                if config.get('imei'):
                    cancel_payload["IMEI"] = str(config['imei'])

                cancel_resp = self._pinelabs_make_request(cancel_url, cancel_payload)
                _logger.info('POS Auto-cancel open txn %s response: %s', existing_ref, cancel_resp)
                if cancel_resp.get('ResponseCode') == 0 or 'APPROVED' in str(cancel_resp.get('ResponseMessage', '')).upper():
                    time.sleep(1)
                    response = self._pinelabs_make_request(url, payload)
                    _logger.info('POS retry UploadBilledTransaction response: %s', response)
                    resp_code = response.get('ResponseCode')
                    resp_msg = str(response.get('ResponseMessage', ''))

        if resp_code is not None and str(resp_code) != '0':
            if 'OPEN TXN' in resp_msg.upper():
                return {'error': _("Pine Labs terminal has an active transaction in progress. Please press the RED cancel (✕) key on the physical terminal, or wait for it to cancel, then try again.")}
            return {'error': f"Pine Labs: {resp_msg} (Code: {resp_code})"}

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
            "PlutusTransactionReferenceID": plutus_transaction_ref_id,
        }
        if config.get('merchant_store_pos_code'):
            payload["MerchantStorePosCode"] = config['merchant_store_pos_code']
        elif config.get('store_id'):
            payload["StoreID"] = config['store_id']

        if config.get('imei'):
            payload["IMEI"] = config['imei']

        if config.get('client_id') and not config.get('merchant_store_pos_code'):
            payload["ClientID"] = config['client_id']

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
            "PlutusTransactionReferenceID": plutus_transaction_ref_id,
            "Amount": int(round(float(amount) * 100)),  # Pine Labs expects paise (rupees × 100)
        }
        if config.get('merchant_store_pos_code'):
            payload["MerchantStorePosCode"] = config['merchant_store_pos_code']
        elif config.get('store_id'):
            payload["StoreID"] = config['store_id']

        if config.get('imei'):
            payload["IMEI"] = config['imei']

        if config.get('client_id') and not config.get('merchant_store_pos_code'):
            payload["ClientID"] = config['client_id']

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs CancelTransaction response: %s', response)
        return response

    def _parse_status_response(self, response):
        """Parse a status response and return a normalized dict for the JS layer."""
        if response.get('error'):
            return response

        response_code = response.get('ResponseCode')
        response_message = str(response.get('ResponseMessage', ''))
        transaction_data = response.get('TransactionData')

        # Convert Tag/Value array to flat dict
        txn_dict = {}
        if isinstance(transaction_data, list):
            for item in transaction_data:
                if isinstance(item, dict) and 'Tag' in item and 'Value' in item:
                    txn_dict[item['Tag']] = item.get('Value', '')
        elif isinstance(transaction_data, dict):
            txn_dict = transaction_data

        msg_upper = response_message.upper()

        if response_code == 0 or str(response_code) == '0':
            return {
                'status': 'success',
                'approval_code': txn_dict.get('ApprovalCode', ''),
                'card_type': txn_dict.get('CardType') or txn_dict.get('Card Type', ''),
                'payment_mode': txn_dict.get('PaymentMode') or txn_dict.get('Payment Mode', ''),
                'card_number_masked': txn_dict.get('CardNumber') or txn_dict.get('Card Number', ''),
                'issuer_bank': txn_dict.get('AcquirerName') or txn_dict.get('Acquirer Name', ''),
                'rrn': txn_dict.get('RRN', ''),
                'batch_number': txn_dict.get('BatchNumber', ''),
                'txn_status_msg': response_message,
            }

        if response_code in (1001, '1001', 1052, '1052') or 'INITIATED' in msg_upper or 'UPLOADED' in msg_upper or not txn_dict:
            return {'status': 'pending', 'raw': response}

        if response_code in (1008, '1008') or any(c in msg_upper for c in ['CANCEL', 'NOT FOUND', 'INVALID', 'DECLINED', 'TIMEOUT']):
            return {'status': 'cancelled' if 'CANCEL' in msg_upper else 'failed', 'message': response_message}

        return {'status': 'pending', 'raw': response}
