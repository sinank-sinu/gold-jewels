# -*- coding: utf-8 -*-
import logging
import requests
import time
import re
from datetime import timezone

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

    # Extended Pine Labs response fields
    customer_vpa = fields.Char(string='Customer VPA (UPI ID)', copy=False)
    acquirer_name = fields.Char(string='Acquirer Name', copy=False)
    acquirer_id = fields.Char(string='Acquirer ID', copy=False)
    transaction_log_id = fields.Char(string='Transaction Log ID', copy=False)
    host_txn_id = fields.Char(string='Host Transaction ID', copy=False)
    transaction_date_raw = fields.Char(string='Transaction Date (Terminal)', copy=False)
    transaction_time_raw = fields.Char(string='Transaction Time (Terminal)', copy=False)
    amount_in_paisa = fields.Char(string='Amount in Paisa', copy=False)

    # Card / Points Redemption specific fields
    card_holder_name = fields.Char(string='Card Holder Name', copy=False)
    expiry_date = fields.Char(string='Card Expiry Date', copy=False)
    reward_txn_id = fields.Char(string='Reward / Points Txn ID', copy=False)
    original_amount_paisa = fields.Char(string='Original Amount (Paisa)', copy=False)
    final_amount_paisa = fields.Char(string='Final Amount (Paisa)', copy=False)
    invoice_number_terminal = fields.Char(string='Terminal Invoice Number', copy=False)

    # Linked records
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', copy=False)
    invoice_id = fields.Many2one('account.move', string='Invoice', copy=False)
    payment_id = fields.Many2one('account.payment', string='Payment', copy=False)
    pos_order_id = fields.Many2one('pos.order', string='POS Order', copy=False)

    # Configuration snapshot
    merchant_id = fields.Char(string='Merchant ID Used')
    terminal_id = fields.Char(string='Terminal ID Used')
    merchant_store_pos_code = fields.Char(string='Merchant Store POS Code Used')
    imei = fields.Char(string='IMEI Used')
    sequence_number = fields.Integer(string='Sequence Number', default=1, copy=False)
    pinelabs_terminal_id = fields.Many2one('pinelabs.terminal', string='Terminal Record')

    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', string='Created By',
                              default=lambda self: self.env.user)

    @api.model
    def create(self, vals):
        if not vals.get('name') or vals.get('name') in ('New', _('New')):
            vals['name'] = self.env['ir.sequence'].next_by_code('pinelabs.transaction') or f"PLT/{int(time.time())}"

        if not vals.get('sequence_number'):
            domain = [('state', '=', 'success')]
            if vals.get('invoice_id'):
                domain.append(('invoice_id', '=', vals['invoice_id']))
            elif vals.get('sale_order_id'):
                domain.append(('sale_order_id', '=', vals['sale_order_id']))
            elif vals.get('payment_id'):
                domain.append(('payment_id', '=', vals['payment_id']))
            elif vals.get('name'):
                domain.append(('name', '=', vals['name']))

            successful_count = self.search_count(domain) if len(domain) > 1 else 0
            vals['sequence_number'] = successful_count + 1

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

    def _build_gst_breakdown(self, invoice):
        """
        Build the GstBrkUp string from invoice tax lines.
        Format: 'CGST:08.45|SGST:08.45' or 'IGST:18.00'
        Reads from account.move.line tax_ids grouped by CGST/SGST/IGST/CESS.
        """
        if not invoice:
            return ''

        gst_parts = {}
        # Iterate tax group lines on the invoice
        for line in invoice.line_ids.filtered(lambda l: l.tax_line_id):
            tax = line.tax_line_id
            tax_name_upper = (tax.name or '').upper()
            amount_type = tax.amount_type  # 'percent', 'fixed', etc.
            tax_rate = tax.amount if amount_type == 'percent' else 0.0

            # Detect GST component type by name
            if 'CGST' in tax_name_upper:
                gst_parts['CGST'] = gst_parts.get('CGST', 0.0) + tax_rate
            elif 'SGST' in tax_name_upper or 'UTGST' in tax_name_upper:
                key = 'SGST'
                gst_parts[key] = gst_parts.get(key, 0.0) + tax_rate
            elif 'IGST' in tax_name_upper:
                gst_parts['IGST'] = gst_parts.get('IGST', 0.0) + tax_rate
            elif 'CESS' in tax_name_upper:
                gst_parts['CESS'] = gst_parts.get('CESS', 0.0) + tax_rate

        if not gst_parts:
            return ''

        return '|'.join(
            '%s:%.2f' % (k, v) for k, v in gst_parts.items()
        )

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

        # User / Cashier Name
        user_id = config.get('user_id') or self.env.user.name or self.env.user.login or ''

        # Ensure AllowedPaymentMode is numeric/integer if digits (e.g. 10 for UPI, 1 for Card)
        mode_val = int(allowed_mode) if str(allowed_mode).isdigit() else allowed_mode

        clean_txn_number = re.sub(r'[^A-Za-z0-9]', '', str(self.name or ''))
        if not clean_txn_number:
            clean_txn_number = f"PAY{int(time.time())}"

        # Sequence number for this payment attempt on this document
        seq_num = self.sequence_number or 1

        payload = {
            "MerchantID": str(config['merchant_id']),
            "SecurityToken": str(config['security_token']),
            "TransactionNumber": clean_txn_number,
            "SequenceNumber": seq_num,
            "AllowedPaymentMode": mode_val,
            "MerchantStorePosCode": str(config.get('merchant_store_pos_code') or config.get('store_id') or ''),
            "Amount": int(round(amount * 100)),  # Pine Labs expects paise (rupees × 100)
            "UserID": str(user_id),
            "IMEI": str(config.get('imei') or config.get('terminal_id') or ''),
        }

        response = self._pinelabs_make_request(url, payload)
        _logger.info('Pine Labs UploadBilledTransaction response: %s', response)
        self.response_log = str(response)

        if response.get('error'):
            self.state = 'failed'
            return response

        response_code = response.get('ResponseCode')
        response_message = str(response.get('ResponseMessage', ''))

        # If terminal returns TXN ALREADY COMPLETED, automatically increment SequenceNumber and retry
        # If terminal returns TXN ALREADY COMPLETED, automatically retry with a fresh unique TransactionNumber and SequenceNumber 1
        if (response_code is not None and str(response_code) != '0' and
                'ALREADY COMPLETED' in response_message.upper()):
            new_txn_number = f"{clean_txn_number[:12]}{str(int(time.time()))[-6:]}"
            self.name = new_txn_number
            self.sequence_number = 1
            payload['TransactionNumber'] = new_txn_number
            payload['SequenceNumber'] = 1
            _logger.warning(
                'Pine Labs transaction %s was already completed. Retrying with fresh TransactionNumber %s and SequenceNumber 1...',
                clean_txn_number, new_txn_number
            )
            time.sleep(1)
            response = self._pinelabs_make_request(url, payload)
            _logger.info('Pine Labs retry response: %s', response)
            self.response_log = str(response)
            response_code = response.get('ResponseCode')
            response_message = str(response.get('ResponseMessage', ''))

        if response_code is not None and str(response_code) != '0':
            if 'OPEN TXN' in response_message.upper() or 'APPROVE' in response_message.upper():
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
                    _logger.warning('Pine Labs terminal has open transaction %s (amt=%s). Attempting auto-cancel and retry...', existing_ref, existing_amt)
                    try:
                        plutus_cancel_id = int(existing_ref)
                    except (TypeError, ValueError):
                        plutus_cancel_id = existing_ref

                    try:
                        cancel_amt = int(existing_amt) if existing_amt else int(round(amount * 100))
                    except (TypeError, ValueError):
                        cancel_amt = int(round(amount * 100))

                    cancel_url = f"{config['base_url']}/CancelTransaction"
                    cancel_payload = {
                        "MerchantID": config['merchant_id'],
                        "SecurityToken": config['security_token'],
                        "PlutusTransactionReferenceID": plutus_cancel_id,
                        "Amount": cancel_amt,
                    }
                    if config.get('merchant_store_pos_code'):
                        cancel_payload["MerchantStorePosCode"] = config['merchant_store_pos_code']
                    elif config.get('store_id'):
                        cancel_payload["StoreID"] = config['store_id']

                    if config.get('imei'):
                        cancel_payload["IMEI"] = config['imei']

                    if config.get('client_id') and not config.get('merchant_store_pos_code'):
                        cancel_payload["ClientID"] = config['client_id']
                    cancel_resp = self._pinelabs_make_request(cancel_url, cancel_payload)
                    _logger.info('Auto-cancel open txn %s response: %s', existing_ref, cancel_resp)
                    if cancel_resp.get('ResponseCode') == 0 or 'APPROVED' in str(cancel_resp.get('ResponseMessage', '')).upper():
                        # Retry uploading new payment now that previous stuck transaction is cancelled
                        time.sleep(1)
                        response = self._pinelabs_make_request(url, payload)
                        _logger.info('Pine Labs retry UploadBilledTransaction response: %s', response)
                        self.response_log = str(response)
                    else:
                        # Cancel could not be done by server (e.g. CANNOT CANCEL AS TRANSACTION IS IN PROGRESS)
                        # Save the cancel error message into response so wizard can explain it clearly
                        cancel_err = cancel_resp.get('ResponseMessage') or cancel_resp.get('error') or ''
                        if cancel_err:
                            response['TerminalCancelError'] = cancel_err
                            response['ExistingReferenceId'] = str(existing_ref)

        # Pine Labs returns PlutusTransactionReferenceID (positive integer) on success
        ref_id = (response.get('PlutusTransactionReferenceID') or
                  response.get('plutusTransactionReferenceID'))
        try:
            ref_int = int(ref_id) if ref_id is not None else 0
        except (ValueError, TypeError):
            ref_int = 0

        if response.get('ResponseCode') == 0 and ref_int > 0:
            self.pinelabs_transaction_id = str(ref_int)
            self.merchant_id = config['merchant_id']
            self.terminal_id = config['terminal_id']
            self.merchant_store_pos_code = config.get('merchant_store_pos_code', '')
            self.imei = config.get('imei', '')
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

        # Pine Labs expects PlutusTransactionReferenceID as an integer
        try:
            plutus_ref_id = int(self.pinelabs_transaction_id)
        except (TypeError, ValueError):
            plutus_ref_id = self.pinelabs_transaction_id

        payload = {
            "MerchantID": config['merchant_id'],
            "SecurityToken": config['security_token'],
            "PlutusTransactionReferenceID": plutus_ref_id,
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
        self.response_log = str(response)
        return self._process_status_response(response)

    def _process_status_response(self, response):
        """
        Parse a Pine Labs GetCloudBasedTxnStatus response and update the transaction record.

        Pine Labs returns TransactionData as a Tag/Value array:
          [{"Tag": "ApprovalCode", "Value": "849035"}, {"Tag": "PaymentMode", "Value": "CARD"}, ...]

        Success is indicated by ResponseCode == 0 at the root level.
        A pending (still processing) state has ResponseCode != 0 and no TransactionData.
        """
        if response.get('error'):
            return response

        response_code = response.get('ResponseCode')
        response_message = str(response.get('ResponseMessage', ''))
        transaction_data = response.get('TransactionData')

        # ── Convert Tag/Value array to a flat dict ──────────────────────
        txn_dict = {}
        if isinstance(transaction_data, list):
            for item in transaction_data:
                if isinstance(item, dict) and 'Tag' in item and 'Value' in item:
                    txn_dict[item['Tag']] = item.get('Value', '')
        elif isinstance(transaction_data, dict):
            # Some responses wrap it in a dict; handle both formats
            txn_dict = transaction_data

        _logger.info('Pine Labs status parsed txn_dict: %s', txn_dict)

        # ── Determine outcome based on ResponseCode ──────────────────────
        # ResponseCode 0 = TXN APPROVED (Success)
        # ResponseCode 1001 = TXN UPLOADED (Pending on terminal)
        # ResponseCode 1008 = TXN VOIDED / CANCELLED
        msg_upper = response_message.upper()

        if response_code in (1008, '1008'):  # Voided / Cancelled
            self.state = 'cancelled'
            return {'status': 'failed', 'message': _('Transaction voided/cancelled on Pine Labs terminal.')}

        # Terminal has completed, dropped, or cancelled the transaction:
        if response_code not in (0, '0') and any(
            x in msg_upper for x in [
                'NOT FOUND', 'INVALID TRANSACTION', 'CANCELLED', 'CANCELED',
                'TIMED OUT', 'TIMEOUT', 'DECLINED', 'DOES NOT EXIST', 'NOT APPLICABLE'
            ]
        ):
            self.state = 'cancelled' if any(c in msg_upper for c in ['CANCEL', 'NOT FOUND', 'INVALID']) else 'failed'
            return {
                'status': 'failed',
                'message': _('Pine Labs terminal: %s') % response_message,
            }

        if response_code in (1001, '1001', 1052, '1052') or 'INITIATED' in msg_upper or 'UPLOADED' in msg_upper or response_code is None or (not txn_dict and response_code not in (0, '0')):
            return {'status': 'pending'}

        if response_code == 0 or str(response_code) == '0':  # Success / Approved
            # Map known Tag keys to Odoo fields
            # Pine Labs uses slightly different key names per payment mode
            # ("Card Type", "Card Type", "CardType", etc.) — check both variants
            def _tag(*names):
                """Return first non-empty value from txn_dict for any of the given keys."""
                for k in names:
                    v = txn_dict.get(k, '')
                    if v:
                        return str(v)
                return ''

            # ── Build write_vals covering all Pine Labs payment modes ──────────
            # Tag names vary by mode:
            #   UPI:    CamelCase  → "AcquirerName", "CustomerVPA", "TransactionDate"…
            #   Card:   Spaced     → "Card Type", "Card Number", "Acquirer Name"…
            #   Points: Spaced     → "Card Type"=REWARD, "Card Holder Name", "Reward Txn ID"…
            write_vals = {
                'state': 'success',
                'payment_date': fields.Datetime.now(),
                # ── Common fields ──────────────────────────────────────────
                'approval_code':              _tag('ApprovalCode'),
                'payment_mode':               _tag('PaymentMode', 'Payment Mode'),
                'retrieval_reference_number': _tag('RRN'),
                'batch_number':               _tag('BatchNumber', 'Batch Number'),
                'amount_in_paisa':            _tag('AmountInPaisa', 'Amount In Paisa'),
                'transaction_date_raw':       _tag('TransactionDate', 'Transaction Date'),
                'transaction_time_raw':       _tag('Transaction Time', 'TransactionTime'),
                # ── Card / Points fields ───────────────────────────────────
                # "Card Type" → CREDIT / DEBIT / REWARD (Points) / PREPAID
                'card_type':          _tag('CardType', 'Card Type'),
                # "Card Number" present for Card/Points; absent for UPI
                'card_number_masked': _tag('CardNumber', 'Card Number', 'Masked Card Number'),
                # Card holder name (Points / Debit / Credit responses)
                'card_holder_name':   _tag('Card Holder Name', 'CardHolderName', 'CardHolder Name'),
                # Expiry date tag
                'expiry_date':        _tag('Expiry Date', 'ExpiryDate'),
                # Reward / Points specific txn ID
                'reward_txn_id':      _tag('Reward Txn ID', 'RewardTxnId', 'Reward Txn Id'),
                # Original and Final amounts (in paisa); useful for reward discount tracking
                'original_amount_paisa': _tag('OriginalAmount', 'Original Amount'),
                'final_amount_paisa':    _tag('FinalAmount', 'Final Amount'),
                # Terminal invoice number (different from Odoo invoice number)
                'invoice_number_terminal': _tag('Invoice Number', 'InvoiceNumber'),
                # ── Acquirer / Issuer ──────────────────────────────────────
                # UPI response: "AcquirerName" | Card/Points: "Acquirer Name"
                'issuer_bank':   _tag('AcquirerName', 'Acquirer Name', 'IssuerBankName', 'Issuer Bank Name'),
                'acquirer_name': _tag('AcquirerName', 'Acquirer Name'),
                'acquirer_id':   _tag('AcquirerId', 'Acquirer Id', 'AcquirerID'),
                # ── UPI-specific ───────────────────────────────────────────
                'customer_vpa': _tag('CustomerVPA', 'Customer VPA', 'MaskedMobileNumber', 'Masked Moblie Number'),
                # ── Log / host IDs ─────────────────────────────────────────
                'transaction_log_id': _tag('TransactionLogId', 'Transaction Log ID', 'TransactionLog Id'),
                'host_txn_id':        _tag('HostTxnId', 'HostTID', 'HOST_TID'),
            }

            # Capture TID / MID from response (useful for reconciliation)
            tid_val = _tag('TID')
            mid_val = _tag('MID')
            if tid_val and not self.terminal_id:
                write_vals['terminal_id'] = tid_val
            if mid_val and not self.merchant_id:
                write_vals['merchant_id'] = mid_val

            self.write(write_vals)
            _logger.info(
                'Pine Labs txn %s → SUCCESS | mode=%s | cardType=%s | approval=%s | '
                'RRN=%s | VPA=%s | cardHolder=%s | origAmt=%s | finalAmt=%s',
                self.name,
                write_vals.get('payment_mode'),
                write_vals.get('card_type'),
                write_vals.get('approval_code'),
                write_vals.get('retrieval_reference_number'),
                write_vals.get('customer_vpa'),
                write_vals.get('card_holder_name'),
                write_vals.get('original_amount_paisa'),
                write_vals.get('final_amount_paisa'),
            )
            return {
                'status': 'success',
                'data': txn_dict,
                'response_message': response_message,
            }

        elif response_code == 1008:  # Voided
            self.state = 'cancelled'
            return {'status': 'cancelled', 'message': response_message}

        else:
            # Non-zero, non-1008 with data present = failed
            self.state = 'failed'
            return {'status': 'failed', 'message': response_message}


    def pinelabs_cancel_payment(self):
        """Cancel a pending Pine Labs transaction using CancelTransaction."""
        self.ensure_one()
        config = self._get_pinelabs_config()

        if (config.get('demo_mode') and
                self.pinelabs_transaction_id and
                str(self.pinelabs_transaction_id).startswith('DEMO')):
            self.state = 'cancelled'
            self.response_log = "DEMO MODE CANCEL SUCCESS"
            return {'status': 'cancelled', 'success': True, 'ResponseCode': 0, 'ResponseMessage': 'DEMO CANCEL SUCCESS'}

        url = f"{config['base_url']}/CancelTransaction"

        # Pine Labs expects PlutusTransactionReferenceID as integer if possible
        try:
            plutus_ref_id = int(self.pinelabs_transaction_id)
        except (TypeError, ValueError):
            plutus_ref_id = self.pinelabs_transaction_id

        payload = {
            "MerchantID": config['merchant_id'],
            "SecurityToken": config['security_token'],
            "PlutusTransactionReferenceID": plutus_ref_id,
            "Amount": int(round(self.amount * 100)),  # Pine Labs expects paise (rupees × 100)
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
        self.response_log = str(response)

        resp_code = response.get('ResponseCode')
        resp_msg = str(response.get('ResponseMessage', ''))
        resp_upper = resp_msg.upper()

        # Pine Labs success: ResponseCode == 0 or APPROVED in response message,
        # OR terminal reports that the transaction is already gone / not found / cancelled
        if (resp_code == 0 or str(resp_code) == '0' or
            'APPROVED' in resp_upper or
            any(k in resp_upper for k in ['NOT FOUND', 'INVALID TRANSACTION', 'ALREADY CANCELLED', 'DOES NOT EXIST'])):
            self.state = 'cancelled'
            response['success'] = True
            if any(k in resp_upper for k in ['NOT FOUND', 'INVALID TRANSACTION', 'DOES NOT EXIST']):
                response['ResponseMessage'] = _('Transaction is no longer active on terminal (closed or already cancelled).')
        else:
            response['success'] = False

        return response
