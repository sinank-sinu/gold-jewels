from odoo import models, fields, _, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare
from dateutil.relativedelta import relativedelta  # Added for safe month arithmetic
from markupsafe import Markup, escape


class JewellerySchemeInstallment(models.Model):
    _name = 'jewellery.scheme.installment'
    _description = 'Scheme Installment'

    enrollment_id = fields.Many2one(
        'jewellery.scheme.enrollment',
        required=True,
        ondelete='cascade'
    )

    date = fields.Date(default=fields.Date.today)
    amount = fields.Float(required=True)

    journal_id = fields.Many2one('account.journal')
    move_id = fields.Many2one('account.move', string="Customer Move")
    suspense_move_id = fields.Many2one('account.move', string="Suspense Move", copy=False)
    transaction_id = fields.Char(string="Transaction ID", copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('paid', 'Paid')
    ], default='draft')
    remark = fields.Char(string="Remark")
    is_transferred = fields.Boolean(string="Transferred", default=False, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_scheme_tracking'):
            enrollment_map = {}
            for rec in records:
                if rec.enrollment_id:
                    enrollment_map.setdefault(rec.enrollment_id, []).append(rec)
            for enrollment, inst_list in enrollment_map.items():
                if len(inst_list) == 1:
                    rec = inst_list[0]
                    state_label = dict(rec._fields['state'].selection).get(rec.state, rec.state)
                    body = Markup(
                        '<p><strong>Installment Added:</strong> Amount: %s, Date: %s, State: %s</p>'
                    ) % (
                        f"{rec.amount:,.2f}",
                        rec.date or '',
                        state_label,
                    )
                    enrollment.message_post(body=body, subtype_xmlid='mail.mt_note')
                else:
                    lines_html = Markup("").join(
                        Markup('<li>Amount: %s, Date: %s, State: %s</li>') % (
                            f"{r.amount:,.2f}",
                            r.date or '',
                            dict(r._fields['state'].selection).get(r.state, r.state),
                        )
                        for r in inst_list
                    )
                    body = Markup('<p><strong>%s Installments Added:</strong></p><ul>%s</ul>') % (
                        len(inst_list),
                        lines_html,
                    )
                    enrollment.message_post(body=body, subtype_xmlid='mail.mt_note')
        return records

    def write(self, vals):
        tracked_fields = {
            'amount': 'Amount',
            'date': 'Date',
            'journal_id': 'Journal',
            'state': 'State',
            'transaction_id': 'Transaction ID',
            'remark': 'Remark',
            'is_transferred': 'Transferred',
        }
        old_values = {}
        do_track = not self.env.context.get('skip_scheme_tracking') and not self.env.context.get('skip_installment_write_note')
        if do_track:
            for rec in self:
                if rec.enrollment_id:
                    old_values[rec.id] = {f: rec[f] for f in tracked_fields if f in vals}

        res = super().write(vals)

        if do_track:
            for rec in self:
                if rec.enrollment_id and rec.id in old_values:
                    changes = []
                    for f, label in tracked_fields.items():
                        if f in vals:
                            old_val = old_values[rec.id].get(f)
                            new_val = rec[f]
                            if f == 'amount':
                                old_str = f"{old_val:,.2f}" if isinstance(old_val, (int, float)) else str(old_val or '')
                                new_str = f"{new_val:,.2f}" if isinstance(new_val, (int, float)) else str(new_val or '')
                            elif f == 'journal_id':
                                old_str = old_val.display_name if old_val else 'None'
                                new_str = new_val.display_name if new_val else 'None'
                            elif f == 'state':
                                sel_map = dict(rec._fields['state'].selection)
                                old_str = sel_map.get(old_val, str(old_val))
                                new_str = sel_map.get(new_val, str(new_val))
                            else:
                                old_str = str(old_val if old_val is not False else '')
                                new_str = str(new_val if new_val is not False else '')

                            if old_str != new_str:
                                changes.append(
                                    Markup('<li><strong>%s:</strong> %s &rarr; %s</li>') % (
                                        label, escape(old_str), escape(new_str)
                                    )
                                )

                    if changes:
                        body = Markup(
                            '<p><strong>Installment (Date: %s, Amount: %s) Updated:</strong></p><ul>%s</ul>'
                        ) % (
                            rec.date or '',
                            f"{rec.amount:,.2f}",
                            Markup("").join(changes),
                        )
                        rec.enrollment_id.message_post(body=body, subtype_xmlid='mail.mt_note')
                        
        # POST-WRITE SPLIT LOGIC
        if not self.env.context.get('skip_installment_split'):
            if vals.get('state') == 'paid' or 'amount' in vals:
                for rec in self:
                    if rec.state == 'paid':
                        enrollment = rec.enrollment_id
                        if enrollment and enrollment.installment_amount > 0:
                            inst_amt = enrollment.installment_amount
                            if rec.amount > inst_amt:
                                remaining = rec.amount - inst_amt
                                
                                # Cap this record's amount
                                rec.with_context(skip_installment_split=True, skip_scheme_tracking=True, skip_installment_write_note=True).write({'amount': inst_amt})
                                
                                base_date = rec.date or fields.Date.today()
                                i = 1
                                extra_vals = []
                                while remaining > 0:
                                    split_amt = inst_amt if remaining >= inst_amt else remaining
                                    remaining -= split_amt
                                    
                                    extra_vals.append({
                                        'enrollment_id': enrollment.id,
                                        'amount': split_amt,
                                        'date': base_date + relativedelta(months=i),
                                        'state': 'paid',
                                        'journal_id': rec.journal_id.id,
                                        'transaction_id': rec.transaction_id,
                                        'move_id': rec.move_id.id,
                                        'suspense_move_id': rec.suspense_move_id.id,
                                        'remark': rec.remark,
                                    })
                                    i += 1
                                
                                if extra_vals:
                                    # Create the extra installment lines silently
                                    self.env['jewellery.scheme.installment'].with_context(
                                        skip_installment_split=True, 
                                        skip_scheme_tracking=True
                                    ).create(extra_vals)
                                    
                                    # Manually log the split to chatter if tracking is enabled
                                    if not self.env.context.get('skip_scheme_tracking'):
                                        lines_html = Markup("").join(
                                            Markup('<li>Amount: %s, Date: %s, State: Paid</li>') % (
                                                f"{v['amount']:,.2f}",
                                                v['date']
                                            ) for v in extra_vals
                                        )
                                        body = Markup('<p><strong>Payment Split into Additional Installments:</strong></p><ul>%s</ul>') % lines_html
                                        enrollment.message_post(body=body, subtype_xmlid='mail.mt_note')

        return res

    def unlink(self):
        if not self.env.is_superuser() and not self.env.user.has_group('base.group_system'):
            raise UserError(_(
                "Only an administrator can delete scheme installment lines."
            ))

        moves = self.mapped('move_id') | self.mapped('suspense_move_id')
        # moves_to_cancel = moves.filtered(lambda move: move.state != 'cancel')
        # if moves_to_cancel:
        #     moves_to_cancel.button_cancel()
        if moves.filtered(lambda move: move.state != 'cancel'):
            raise UserError(_(
                "The linked journal entries must be cancelled before deleting "
                "the scheme installment."
            ))

        if not self.env.context.get('skip_scheme_tracking'):
            for rec in self:
                if rec.enrollment_id:
                    state_label = dict(rec._fields['state'].selection).get(rec.state, rec.state)
                    body = Markup(
                        '<p><strong>Installment Removed:</strong> Date: %s, Amount: %s, State: %s</p>'
                    ) % (
                        rec.date or '',
                        f"{rec.amount:,.2f}",
                        state_label,
                    )
                    rec.enrollment_id.message_post(body=body, subtype_xmlid='mail.mt_note')
        return super().unlink()

    def action_transfer(self):
        self.ensure_one()

        if self.is_transferred:
            raise UserError(_("This installment has already been transferred!"))

        if not self.amount or self.amount <= 0:
            raise UserError(_("Installment amount must be greater than zero to transfer."))

        partner = self.enrollment_id.partner_id
        if not partner:
            raise UserError(_("No partner found on the scheme enrollment."))

        enrollment = self.enrollment_id
        expected_total = enrollment.total_scheme_amount if hasattr(enrollment, 'total_scheme_amount') and enrollment.total_scheme_amount > 0 else (enrollment.duration * enrollment.installment_amount)
        if expected_total > 0 and (enrollment.total_paid + self.amount) > expected_total:
            raise UserError(
                _("Transfer limit exceeded. Total allowed amount for this scheme is %s. You cannot transfer more than the allowed duration.") % expected_total)

        target_company_id = self.enrollment_id.branch_id.company_id.id if self.enrollment_id.branch_id and hasattr(
            self.enrollment_id.branch_id,
            'company_id') and self.enrollment_id.branch_id.company_id else self.env.company.id
        target_company = self.env['res.company'].browse(target_company_id)

        # 1. Find Miscellaneous Journal for target company
        journal = self.env['account.journal'].search([
            ('company_id', '=', target_company_id),
            ('code', '=', 'SUS')
        ], limit=1) or self.env['account.journal'].search([
            ('company_id', '=', target_company_id),
            ('name', 'ilike', 'suspense')
        ], limit=1) or self.env['account.journal'].search([
            ('company_id', '=', target_company_id),
            ('type', '=', 'general')
        ], limit=1)

        if not journal:
            raise UserError(
                _("Miscellaneous Journal missing!\nPlease create or configure a Miscellaneous Journal for company '%s'.") % target_company.name)

        # 2. Get Suspense Partner
        suspense_partner = self.env['res.partner'].search([
            ('name', 'ilike', 'Suspense')
        ], limit=1)

        if not suspense_partner or not suspense_partner.id:
            suspense_partner = self.env['res.partner'].create({
                'name': 'Scheme Suspense',
                'company_id': False,
            })

        # 3. Get Customer Debtors Account
        debtors_account = partner.with_company(target_company).property_account_receivable_id
        if debtors_account and debtors_account.company_id and debtors_account.company_id.id != target_company_id:
            debtors_account = False

        if not debtors_account:
            debtors_account = self.env['account.account'].search([
                ('company_id', '=', target_company_id),
                ('account_type', '=', 'asset_receivable')
            ], limit=1)

        if not debtors_account or not debtors_account.id:
            raise UserError(
                _("No Receivable account found on the partner '%s', and no generic receivable account found for company '%s'.") % (
                    partner.name, target_company.name))

        # 4. Get Outstanding Receipts Account

        outstanding_receipt_account = self.env['account.account'].search([
            ('company_id', '=', target_company_id),
            ('name', 'ilike', 'Outstanding Receipt')
        ], limit=1) or self.env['account.account'].search([
            ('company_id', '=', target_company_id),
            ('name', 'ilike', 'Outstanding Reciept')
        ], limit=1) or self.env['account.account'].search([
            ('company_id', '=', target_company_id),
            ('name', 'ilike', 'Outstanding')
        ], limit=1)

        if not outstanding_receipt_account or not outstanding_receipt_account.id:
            raise UserError(_("Outstanding Receipts Account missing for company '%s'.") % target_company.name)

        # ------------------------------------------------------------------
        branch_id = self.enrollment_id.branch_id.id if self.enrollment_id.branch_id else False
        entry_date = self.date or fields.Date.today()

        # ------------------------------------------------------------------
        # ENTRY 2 (Miscellaneous Journal - Suspense Partner Clearing):
        # Line 1 (Debit): Debtor / Suspense Account (Debit) - Suspense Partner
        # Line 2 (Credit): Outstanding Receipts Account (Credit) - Suspense Partner
        # ------------------------------------------------------------------
        entry2_vals = {
            'journal_id': journal.id,
            'company_id': target_company_id,
            'date': entry_date,
            'ref': f"Scheme Transfer (Suspense) - {self.enrollment_id.name or partner.name}",
            'partner_id': suspense_partner.id,
            'branch_id': branch_id,
            'line_ids': [
                (0, 0, {
                    'account_id': debtors_account.id,
                    'partner_id': suspense_partner.id,
                    'name': f"Transfer Scheme Suspense Debtor - {suspense_partner.name}",
                    'debit': self.amount,
                    'credit': 0.0,
                    'company_id': target_company_id,
                    'branch_id': branch_id,
                }),
                (0, 0, {
                    'account_id': outstanding_receipt_account.id,
                    'partner_id': suspense_partner.id,
                    'name': f"Transfer Scheme Suspense Outstanding Receipt - {suspense_partner.name}",
                    'debit': 0.0,
                    'credit': self.amount,
                    'company_id': target_company_id,
                    'branch_id': branch_id,
                })
            ]
        }
        move2 = self.env['account.move'].create(entry2_vals)
        move2.write({'partner_id': suspense_partner.id})
        move2.action_post()

        # ------------------------------------------------------------------
        # ENTRY 3 (Miscellaneous Journal - Customer Partner Allocation):
        # Line 1 (Debit): Outstanding Receipts Account (Debit) - Customer Partner
        # Line 2 (Credit): Debtor Account (Credit) - Customer Partner
        # ------------------------------------------------------------------
        entry3_vals = {
            'journal_id': journal.id,
            'company_id': target_company_id,
            'date': entry_date,
            'ref': f"Scheme Transfer - {self.enrollment_id.name or partner.name}",
            'partner_id': partner.id,
            'branch_id': branch_id,
            'line_ids': [
                (0, 0, {
                    'account_id': outstanding_receipt_account.id,
                    'partner_id': partner.id,
                    'name': f"Scheme Outstanding Receipt - {partner.name}",
                    'debit': self.amount,
                    'credit': 0.0,
                    'company_id': target_company_id,
                    'branch_id': branch_id,
                }),
                (0, 0, {
                    'account_id': debtors_account.id,
                    'partner_id': partner.id,
                    'name': f"Scheme Debtor Transfer - {partner.name}",
                    'debit': 0.0,
                    'credit': self.amount,
                    'company_id': target_company_id,
                    'branch_id': branch_id,
                })
            ]
        }
        move3 = self.env['account.move'].create(entry3_vals)
        move3.write({'partner_id': partner.id})
        move3.action_post()

        # ------------------------------------------------------------------
        # 1. Cancel Move 2 and Move 3 against each other on Outstanding Receipts
        # (Both entries have the same account, same amount; debit & credit cancel each other)
        # ------------------------------------------------------------------
        try:
            m2_out_line = move2.line_ids.filtered(
                lambda l: l.account_id.id == outstanding_receipt_account.id and not l.reconciled
            )
            m3_out_line = move3.line_ids.filtered(
                lambda l: l.account_id.id == outstanding_receipt_account.id and not l.reconciled
            )
            if m2_out_line and m3_out_line:
                (m2_out_line + m3_out_line).reconcile()
        except Exception:
            pass

        # ------------------------------------------------------------------
        # 2. Clear Suspense Partner in Debtors Account
        # Reconcile Move 2's Suspense Debtor line with Customer Payment's Debtor line.
        # NOTE: The Customer Payment's Outstanding Receipts line is NOT touched,
        # so it remains available for Bank Statement Reconciliation.
        # ------------------------------------------------------------------
        try:
            m2_debtor_line = move2.line_ids.filtered(
                lambda l: l.account_id.id == debtors_account.id and not l.reconciled
            )
            if m2_debtor_line:
                counterpart_domain = [
                    ('partner_id', '=', suspense_partner.id),
                    ('account_id', '=', debtors_account.id),
                    ('reconciled', '=', False),
                    ('company_id', '=', target_company_id),
                    ('id', '!=', m2_debtor_line.id),
                    ('credit', '=', self.amount),
                ]

                counterpart = False
                # If transaction_id is present, try matching specific payment first
                if self.transaction_id:
                    counterpart = self.env['account.move.line'].search(counterpart_domain + [
                        '|', '|',
                        ('move_id.ref', '=', self.transaction_id),
                        ('move_id.payment_id.bank_reference', '=', self.transaction_id),
                        ('move_id.payment_id.ref', '=', self.transaction_id),
                    ], limit=1)

                if not counterpart:
                    counterpart = self.env['account.move.line'].search(counterpart_domain, limit=1)

                if counterpart:
                    (m2_debtor_line + counterpart).reconcile()

            # Pairwise reconcile any remaining matching amounts for suspense partner on Debtors ONLY
            unreconciled_lines = self.env['account.move.line'].search([
                ('partner_id', '=', suspense_partner.id),
                ('account_id', '=', debtors_account.id),
                ('reconciled', '=', False),
                ('company_id', '=', target_company_id),
            ])
            debit_lines = list(unreconciled_lines.filtered(lambda l: l.debit > 0))
            credit_lines = list(unreconciled_lines.filtered(lambda l: l.credit > 0))
            for d in debit_lines[:]:
                for c in credit_lines[:]:
                    if float_compare(d.debit, c.credit, precision_rounding=0.01) == 0:
                        (d + c).reconcile()
                        debit_lines.remove(d)
                        credit_lines.remove(c)
                        break
        except Exception:
            pass

        # Link moves to the installment record
        self.with_context(skip_installment_write_note=True).write({
            'suspense_move_id': move2.id,
            'move_id': move3.id,
            'journal_id': journal.id,
            'is_transferred': True,
            'state': 'paid',
            'transaction_id': self.transaction_id or 'BANK-TRANSFER',
        })

        # Track transfer in enrollment chatter
        if self.enrollment_id:
            move3_str = Markup('<a href="#" data-oe-model="account.move" data-oe-id="%s">%s</a>') % (
                move3.id, escape(move3.name or move3.ref or str(move3.id))
            )
            move2_str = Markup('<a href="#" data-oe-model="account.move" data-oe-id="%s">%s</a>') % (
                move2.id, escape(move2.name or move2.ref or str(move2.id))
            )
            body = Markup(
                '<p><strong>Installment Transferred</strong></p>'
                '<ul>'
                '<li><strong>Amount:</strong> %s</li>'
                '<li><strong>Date:</strong> %s</li>'
                '<li><strong>Customer Entry:</strong> %s</li>'
                '<li><strong>Suspense Entry:</strong> %s</li>'
                '<li><strong>Transaction ID:</strong> %s</li>'
                '</ul>'
            ) % (
                f"{self.amount:,.2f}",
                self.date or '',
                move3_str,
                move2_str,
                escape(self.transaction_id or 'BANK-TRANSFER'),
            )
            self.enrollment_id.message_post(
                body=body,
                subtype_xmlid='mail.mt_note'
            )

        # Return action to view created transfer entries
        return {
            'name': _('Transfer Journal Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'domain': [('id', 'in', [move2.id, move3.id])],
            'view_mode': 'tree,form',
            'target': 'current',
        }


    def action_confirm_payment(self):
            self.ensure_one()

            if self.state == 'paid' or self.move_id:
                raise UserError(_("Already paid."))

            enrollment = self.enrollment_id
            inst_amt = enrollment.installment_amount
            payment_amount = self.amount

            if inst_amt <= 0:
                raise UserError(_("Invalid installment amount."))


            expected_total = enrollment.total_scheme_amount if hasattr(enrollment, 'total_scheme_amount') and enrollment.total_scheme_amount > 0 else (enrollment.duration * inst_amt)
            if expected_total > 0 and (enrollment.total_paid + payment_amount) > expected_total:
                raise UserError(_("Payment limit exceeded. Total allowed amount for this scheme is %s. You cannot pay more than the allowed duration.") % expected_total)

            # --------------------------------------------------
            # OPEN PAYMENT WIZARD
            # --------------------------------------------------
            return {
                'name': _('Pay via Pine Labs (Scheme)'),
                'type': 'ir.actions.act_window',
                'res_model': 'pinelabs.payment.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_amount': payment_amount,
                    'default_scheme_installment_id': self.id,
                },
        }


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    # --------------------------------------------------
    # PAYMENT HOOK (RIGHT PLACE)
    # --------------------------------------------------
    def _create_payments(self):
        payments = super()._create_payments()

        for wizard in self:
            wizard._generate_scheme_installments()

        return payments

    # --------------------------------------------------
    # YOUR SPLIT LOGIC (FIXED)
    # --------------------------------------------------
    def _generate_scheme_installments(self):
        self.ensure_one()

        # If it is paying an invoice (NOT a standalone/outstanding payment), skip scheme allocation
        if self.line_ids.move_id:
            return

        enrollment = self.env['jewellery.scheme.enrollment'].search([
            ('partner_id', '=', self.partner_id.id)
        ], limit=1)

        if not enrollment:
            return

        inst_amt = enrollment.installment_amount
        entered_amt = self.amount

        if not inst_amt or entered_amt <= 0:
            return

        # ------------------------------------------
        # calculate splits
        # ------------------------------------------
        total_lines = int(entered_amt // inst_amt)
        if entered_amt % inst_amt:
            total_lines += 1

        remaining = entered_amt

        # ------------------------------------------
        # IMPORTANT FIX:
        # start from NEXT MONTH (NO BACK DATES)
        # ------------------------------------------
        base_date = self.payment_date or fields.Date.today()

        for i in range(total_lines):

            amount = inst_amt if remaining >= inst_amt else remaining
            remaining -= amount

            installment_date = base_date + relativedelta(months=i + 1)

            self.env['jewellery.scheme.installment'].create({
                'enrollment_id': enrollment.id,
                'amount': amount,
                'date': installment_date,
            })