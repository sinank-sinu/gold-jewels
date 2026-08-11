from odoo import http, _
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class SchemePaymentCorrectionController(http.Controller):

    @http.route('/scheme-payment/correction-runner', type='http', auth='user', methods=['GET'])
    def correction_runner_ui(self, **kwargs):
        if not request.env.user.has_group('account.group_account_manager'):
            return request.make_response("<h1>Access Denied. Accounting Manager rights required.</h1>")

        html_content = """
        <html>
        <head>
            <title>Scheme Payment Correction</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f4f6f9; color: #333; }
                .container { max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                h1 { color: #2c3e50; }
                .btn { padding: 10px 20px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; margin-right: 10px; }
                .btn:disabled { background: #ccc; }
                .btn-dry { background: #6c757d; }
                #log { background: #222; color: #0f0; padding: 15px; border-radius: 4px; height: 300px; overflow-y: scroll; font-family: monospace; font-size: 14px; margin-top: 20px; }
                .stats { display: flex; gap: 20px; margin-top: 20px; font-weight: bold; }
                .stat-box { padding: 15px; background: #e9ecef; border-radius: 6px; flex: 1; text-align: center; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Scheme Payment Receipt Correction</h1>
                <p>This tool will process EVERY Scheme Payment in the database in small, safe batches to prevent timeouts.</p>
                
                <div>
                    <button class="btn" id="startBtn" onclick="startCorrection(false)">Run Real Correction</button>
                    <button class="btn btn-dry" id="dryBtn" onclick="startCorrection(true)">Run Dry Run (Test)</button>
                    <button class="btn" id="stopBtn" onclick="stopCorrection()" disabled>Stop</button>
                </div>

                <div class="stats">
                    <div class="stat-box">Processed: <br><span id="s-processed">0</span></div>
                    <div class="stat-box">Corrected: <br><span id="s-corrected">0</span></div>
                    <div class="stat-box">Already Correct: <br><span id="s-already">0</span></div>
                    <div class="stat-box">Failed/Skipped: <br><span id="s-failed">0</span></div>
                </div>

                <div id="log">Ready...</div>
            </div>

            <script>
                let isRunning = false;
                let lastId = 0;
                let totals = { processed: 0, corrected: 0, already: 0, failed: 0 };
                let isDryRun = false;

                function logMsg(msg) {
                    const l = document.getElementById('log');
                    l.innerHTML += `<div>${msg}</div>`;
                    l.scrollTop = l.scrollHeight;
                }

                function updateStats(data) {
                    totals.processed += data.processed || 0;
                    totals.corrected += (data.corrected || 0) + (data.would_correct || 0);
                    totals.already += data.already_correct || 0;
                    totals.failed += (data.failed || 0) + (data.skipped || 0) + (data.missing_payment_journal || 0) + (data.missing_outstanding_account || 0);
                    
                    document.getElementById('s-processed').innerText = totals.processed;
                    document.getElementById('s-corrected').innerText = totals.corrected;
                    document.getElementById('s-already').innerText = totals.already;
                    document.getElementById('s-failed').innerText = totals.failed;
                }

                function stopCorrection() {
                    isRunning = false;
                    logMsg("Stopped by user.");
                    document.getElementById('startBtn').disabled = false;
                    document.getElementById('dryBtn').disabled = false;
                    document.getElementById('stopBtn').disabled = true;
                }

                function startCorrection(dryRun) {
                    isRunning = true;
                    isDryRun = dryRun;
                    lastId = 0;
                    totals = { processed: 0, corrected: 0, already: 0, failed: 0 };
                    updateStats({});
                    document.getElementById('log').innerHTML = "<div>Starting " + (dryRun ? "DRY RUN" : "REAL RUN") + "...</div>";
                    document.getElementById('startBtn').disabled = true;
                    document.getElementById('dryBtn').disabled = true;
                    document.getElementById('stopBtn').disabled = false;
                    
                    fetchBatch();
                }

                function fetchBatch() {
                    if (!isRunning) return;
                    
                    let url = `/scheme-payment/correct-outstanding-receipts?batch_size=100&last_id=${lastId}&dry_run=${isDryRun}`;
                    logMsg(`Fetching batch: ID > ${lastId}`);
                    
                    fetch(url)
                        .then(res => res.json())
                        .then(data => {
                            updateStats(data);
                            logMsg(`Batch complete. Processed: ${data.processed}.`);
                            
                            if (data.has_more && isRunning) {
                                lastId = data.last_id;
                                setTimeout(fetchBatch, 500); // slight pause between batches
                            } else {
                                logMsg("<strong>Finished checking ALL Scheme Payments!</strong>");
                                stopCorrection();
                            }
                        })
                        .catch(err => {
                            logMsg(`<span style="color:red">Error fetching batch: ${err}</span>`);
                            stopCorrection();
                        });
                }
            </script>
        </body>
        </html>
        """
        return request.make_response(html_content, headers=[('Content-Type', 'text/html')])

    @http.route('/scheme-payment/correct-outstanding-receipts', type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def correct_outstanding_receipts(self, **kwargs):
        # We need admin access for correcting accounting entries
        if not request.env.user.has_group('account.group_account_manager'):
            return request.make_response(json.dumps({'error': 'Access Denied. Accounting Manager rights required.'}), headers=[('Content-Type', 'application/json')])

        dry_run = str(kwargs.get('dry_run', '')).lower() in ('true', '1', 't')
        
        try:
            batch_size = int(kwargs.get('batch_size', 50))
        except ValueError:
            batch_size = 50
        
        if batch_size > 100:
            batch_size = 100
            
        try:
            last_id = int(kwargs.get('last_id', 0))
        except ValueError:
            last_id = 0

        Installment = request.env['jewellery.scheme.installment'].sudo()
        Log = request.env['scheme.payment.correction.log'].sudo()

        domain = [('id', '>', last_id)]

        installments = Installment.search(domain, limit=batch_size, order='id asc')
        
        has_more = len(installments) == batch_size
        new_last_id = installments[-1].id if installments else last_id
        
        result = {
            'success': True,
            'dry_run': dry_run,
            'batch_size': batch_size,
            'processed': len(installments),
            'corrected': 0,
            'would_correct': 0,
            'already_correct': 0,
            'missing_payment_journal': 0,
            'missing_outstanding_account': 0,
            'skipped': 0,
            'failed': 0,
            'last_id': new_last_id,
            'has_more': has_more,
            'next_url': f'/scheme-payment/correct-outstanding-receipts?batch_size={batch_size}&last_id={new_last_id}' if has_more else None,
            'details': []
        }
        
        _logger.info(f"Starting scheme payment correction batch. Batch Size: {batch_size}. Last ID: {last_id}. Processing: {len(installments)}. Dry run: {dry_run}")
        
        for installment in installments:
            try:
                if request.env.cr.closed:
                    result['failed'] += 1
                    result['details'].append({"error": "Cursor closed, stopping batch"})
                    break
                    
                with request.env.cr.savepoint():
                    scheme_ref = installment.enrollment_id.name if installment.enrollment_id else ''
                    scheme_name = installment.enrollment_id.scheme_id.name if hasattr(installment.enrollment_id, 'scheme_id') and installment.enrollment_id.scheme_id else ''
                    customer = installment.enrollment_id.partner_id if installment.enrollment_id else None
                    
                    move = installment.move_id
                    if not move:
                        msg = f"[{scheme_ref}] Skipped: Missing related payment journal entry."
                        _logger.warning(msg)
                        self._log(Log, move, scheme_ref, scheme_name, customer, installment.journal_id, status='missing_payment_journal', error='Missing related payment journal entry.', dry_run=dry_run)
                        result['missing_payment_journal'] += 1
                        self._add_detail(result, scheme_ref, scheme_name, customer, move, installment.journal_id, None, None, 'missing_payment_journal')
                        continue
                        
                    # We are looking for the receipt side debit line
                    # Usually there's a credit to Debtors and a debit to Bank/Cash or Opening Balance
                    debit_lines = move.line_ids.filtered(lambda l: l.debit > 0 and l.account_id.account_type not in ('asset_receivable', 'liability_payable'))
                    
                    if not debit_lines:
                        msg = f"[{scheme_ref}] Skipped: No valid debit line found in move {move.name}."
                        _logger.warning(msg)
                        self._log(Log, move, scheme_ref, scheme_name, customer, installment.journal_id, status='skipped', error='No valid debit line found.', dry_run=dry_run)
                        result['skipped'] += 1
                        self._add_detail(result, scheme_ref, scheme_name, customer, move, installment.journal_id, None, None, 'skipped')
                        continue
                        
                    if len(debit_lines) > 1:
                        # Try to narrow down
                        cash_bank_lines = debit_lines.filtered(lambda l: l.account_id.account_type in ('asset_cash', 'asset_liquidity', 'current_assets'))
                        if len(cash_bank_lines) == 1:
                            debit_line = cash_bank_lines[0]
                        else:
                            msg = f"[{scheme_ref}] Skipped: Multiple debit lines found. Cannot automatically determine the receipt side."
                            _logger.warning(msg)
                            self._log(Log, move, scheme_ref, scheme_name, customer, installment.journal_id, status='skipped', error='Multiple debit lines found.', dry_run=dry_run)
                            result['skipped'] += 1
                            self._add_detail(result, scheme_ref, scheme_name, customer, move, installment.journal_id, None, None, 'skipped')
                            continue
                    else:
                        debit_line = debit_lines[0]
                    
                    # Determine Outstanding Receipts Account strictly
                    outstanding_account = False
                    actual_payment = move.payment_id
                    
                    # 1. Primary: Search by Exact Name / Code in the Move's Company
                    outstanding_account = request.env['account.account'].sudo().search([
                        ('company_id', '=', move.company_id.id),
                        ('name', '=', 'Outstanding Receipts'),
                        ('deprecated', '=', False)
                    ], limit=1)
                    
                    if not outstanding_account:
                        outstanding_account = request.env['account.account'].sudo().search([
                            ('company_id', '=', move.company_id.id),
                            ('name', 'ilike', 'Outstanding Receipt'),
                            ('deprecated', '=', False)
                        ], limit=1)
                        
                    if not outstanding_account and move.company_id.id == 5:
                        # Edge case for Company 5
                        outstanding_account = request.env['account.account'].sudo().search([
                            ('company_id', '=', 5),
                            ('code', '=', '00011'),
                            ('deprecated', '=', False)
                        ], limit=1)
                        
                    # 2. Secondary: Trace payment configuration, but ONLY accept if it is an Outstanding Receipts account
                    if not outstanding_account:
                        candidate_accounts = request.env['account.account'].sudo()
                        
                        if actual_payment:
                            if actual_payment.payment_method_line_id and actual_payment.payment_method_line_id.payment_account_id:
                                candidate_accounts |= actual_payment.payment_method_line_id.payment_account_id
                            if actual_payment.journal_id:
                                candidate_accounts |= actual_payment.journal_id.inbound_payment_method_line_ids.mapped('payment_account_id')
                        
                        if installment.journal_id:
                            candidate_accounts |= installment.journal_id.inbound_payment_method_line_ids.mapped('payment_account_id')
                            
                        if move.journal_id:
                            candidate_accounts |= move.journal_id.inbound_payment_method_line_ids.mapped('payment_account_id')
                            
                        if move.company_id.account_journal_payment_debit_account_id:
                            candidate_accounts |= move.company_id.account_journal_payment_debit_account_id
                            
                        for acc in candidate_accounts:
                            if not acc:
                                continue
                            name_lower = acc.name.lower() if acc.name else ''
                            if 'outstanding' in name_lower or 'receipt' in name_lower or acc.code == '00011':
                                outstanding_account = acc
                                break
                                
                    if not outstanding_account:
                        # Log exactly as user requested if no account could be determined from the configuration
                        debug_msg = (
                            f"[SCHEME PAYMENT CORRECTION]\n"
                            f"Scheme: {scheme_name}\n"
                            f"Scheme Payment: {scheme_ref}\n"
                            f"Move: {move.name}\n"
                            f"Move Company: {move.company_id.name}\n"
                            f"Move Company ID: {move.company_id.id}\n"
                            f"Current Debit Account: {debit_line.account_id.display_name if debit_line else 'None'}\n"
                            f"Target Outstanding Receipts Account: None found\n"
                        )
                        _logger.info(debug_msg)
                        
                        msg = f"[{scheme_ref}] Skipped: Unable to determine Outstanding Receipts account from Scheme Payment receipt."
                        _logger.warning(msg)
                        self._log(Log, move, scheme_ref, scheme_name, customer, installment.journal_id, status='missing_outstanding_account', error="Unable to determine Outstanding Receipts account from Scheme Payment receipt.", dry_run=dry_run)
                        result['missing_outstanding_account'] += 1
                        self._add_detail(result, scheme_ref, scheme_name, customer, move, installment.journal_id, debit_line.account_id, None, 'missing_outstanding_account')
                        continue

                    # DEBUG output for target account
                    debug_msg = (
                        f"[SCHEME PAYMENT CORRECTION]\n"
                        f"Scheme: {scheme_name}\n"
                        f"Scheme Payment: {scheme_ref}\n"
                        f"Move: {move.name}\n"
                        f"Move Company: {move.company_id.name}\n"
                        f"Move Company ID: {move.company_id.id}\n"
                        f"Receipt: {actual_payment.name if actual_payment else 'None'}\n"
                        f"Payment: {actual_payment.id if actual_payment else 'None'}\n"
                        f"Payment Journal: {actual_payment.journal_id.name if actual_payment else (installment.journal_id.name if installment.journal_id else 'None')}\n"
                        f"Current Debit Account: {debit_line.account_id.display_name if debit_line else 'None'}\n"
                        f"Target Outstanding Receipts Account: {outstanding_account.display_name}\n"
                        f"Target Account Company: {outstanding_account.company_id.name}\n"
                    )
                    _logger.info(debug_msg)
                        
                    if debit_line.account_id.id == outstanding_account.id:
                        if move.state == 'draft':
                            move.action_post()
                            msg = f"[{scheme_ref}] Already correct (Was Draft, Now Posted): Using {outstanding_account.name}."
                            status_label = 'corrected'
                            previous_state = 'draft'
                        else:
                            msg = f"[{scheme_ref}] Already correct: Using {outstanding_account.name}."
                            status_label = 'already_correct'
                            previous_state = move.state
                            
                        _logger.info(msg)
                        self._log(Log, move, scheme_ref, scheme_name, customer, installment.journal_id, status=status_label, previous_state=previous_state, final_state=move.state, dry_run=dry_run)
                        result['already_correct'] += 1
                        self._add_detail(result, scheme_ref, scheme_name, customer, move, installment.journal_id, debit_line.account_id, outstanding_account, status_label, previous_state)
                        continue
                        
                    if dry_run:
                        result['would_correct'] += 1
                        msg = f"[{scheme_ref}] Would correct: {debit_line.account_id.name} -> {outstanding_account.name}"
                        _logger.info(msg)
                        self._log(Log, move, scheme_ref, scheme_name, customer, installment.journal_id, old_account=debit_line.account_id, new_account=outstanding_account, status='corrected', dry_run=True)
                        self._add_detail(result, scheme_ref, scheme_name, customer, move, installment.journal_id, debit_line.account_id, outstanding_account, 'would_correct')
                        continue
                        
                    previous_state = move.state
                    
                    # Proceed with correction
                    if move.state == 'posted':
                        move.button_draft()
                        
                    # 1. Standard ORM write
                    move.write({
                        'line_ids': [(1, debit_line.id, {'account_id': outstanding_account.id})]
                    })
                    
                    # 2. Post again
                    move.action_post()
                    
                    # 3. CRITICAL BYPASS: Odoo 17 automatically forces the default bank account 
                    # onto the liquidity line during `action_post()` for Bank/Cash journals.
                    # We MUST use SQL to forcefully update the account AFTER posting to make it stick!
                    request.env.cr.execute("""
                        UPDATE account_move_line
                        SET account_id = %s
                        WHERE id = %s
                    """, (outstanding_account.id, debit_line.id))
                    
                    # Invalidate the cache so the ORM sees the forced SQL update
                    request.env.invalidate_all()
                        
                    # Final verification of idempotency
                    debit_line_after = move.line_ids.filtered(lambda l: l.id == debit_line.id)
                    if move.state == 'posted' and debit_line_after and debit_line_after.account_id.id == outstanding_account.id:
                        msg = f"[{scheme_ref}] Corrected: {debit_line.account_id.name} -> {outstanding_account.name} (Was {previous_state}, Now {move.state})"
                        _logger.info(msg)
                        self._log(Log, move, scheme_ref, scheme_name, customer, installment.journal_id, old_account=debit_line.account_id, new_account=outstanding_account, status='corrected', previous_state=previous_state, final_state=move.state, dry_run=False)
                        result['corrected'] += 1
                        self._add_detail(result, scheme_ref, scheme_name, customer, move, installment.journal_id, debit_line.account_id, outstanding_account, 'corrected', previous_state)
                    else:
                        raise ValueError(f"Final verification failed! State: {move.state}. Expected Account: {outstanding_account.id}, Found: {debit_line_after.account_id.id if debit_line_after else 'None'}")
                    
            except Exception as e:
                msg = f"[{installment.id}] Failed: {str(e)}"
                _logger.error(msg)
                scheme_ref_fail = installment.enrollment_id.name if installment.enrollment_id else ''
                scheme_name_fail = installment.enrollment_id.scheme_id.name if hasattr(installment.enrollment_id, 'scheme_id') and installment.enrollment_id.scheme_id else ''
                customer_fail = installment.enrollment_id.partner_id if installment.enrollment_id else None
                self._log(Log, installment.move_id, scheme_ref_fail, scheme_name_fail, customer_fail, installment.journal_id, status='failed', error=str(e), dry_run=dry_run)
                result['failed'] += 1
                
                # Pass the error to the UI JSON so we can see why it failed
                self._add_detail(result, scheme_ref_fail, scheme_name_fail, customer_fail, installment.move_id, installment.journal_id, debit_line.account_id if 'debit_line' in locals() else None, outstanding_account if 'outstanding_account' in locals() else None, 'failed', installment.move_id.state if installment.move_id else '', error=str(e))

        return request.make_response(json.dumps(result), headers=[('Content-Type', 'application/json')])

    def _add_detail(self, result, scheme_ref, scheme_name, customer, move, payment_journal, old_account, new_account, status, previous_state=None, error=None):
        amount = 0.0
        if move:
            amount = sum(move.line_ids.filtered(lambda l: l.debit > 0).mapped('debit'))
        
        result['details'].append({
            "scheme_payment": scheme_ref,
            "scheme_name": scheme_name,
            "customer": customer.name if customer else "",
            "journal_entry": move.name if move else "",
            "journal": move.journal_id.name if move and move.journal_id else "",
            "payment_journal": payment_journal.name if payment_journal else "",
            "company": move.company_id.name if move and move.company_id else "",
            "old_account": f"{old_account.code} {old_account.name}" if old_account else "",
            "new_account": f"{new_account.code} {new_account.name}" if new_account else "",
            "amount": amount,
            "previous_state": previous_state or (move.state if move else ""),
            "final_state": move.state if move else "",
            "status": status,
            "error": error if error else ""
        })

    def _log(self, Log, move, scheme_ref, scheme_name, customer, payment_journal=None, old_account=None, new_account=None, status='', error='', previous_state='', final_state='', dry_run=False):
        if dry_run:
            return
        
        # Calculate amount from debit lines
        amount = 0.0
        if move:
            amount = sum(move.line_ids.filtered(lambda l: l.debit > 0).mapped('debit'))
        
        Log.create({
            'move_id': move.id if move else False,
            'move_name': move.name if move else False,
            'scheme_payment_reference': scheme_ref,
            'scheme_name': scheme_name,
            'journal_id': move.journal_id.id if move and move.journal_id else False,
            'payment_journal_id': payment_journal.id if payment_journal else False,
            'company_id': move.company_id.id if move and move.company_id else False,
            'partner_id': customer.id if customer else False,
            'old_account_id': old_account.id if old_account else False,
            'new_account_id': new_account.id if new_account else False,
            'amount': amount,
            'currency_id': move.company_id.currency_id.id,
            'previous_state': previous_state or move.state,
            'final_state': final_state or move.state,
            'status': status,
            'error_message': error,
        })
