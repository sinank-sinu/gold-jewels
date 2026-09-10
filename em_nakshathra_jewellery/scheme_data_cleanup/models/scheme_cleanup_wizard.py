import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SchemeCleanupWizard(models.TransientModel):
    _name = 'scheme.cleanup.wizard'
    _description = 'Scheme Data Cleanup & Journal Reversal Wizard'

    state = fields.Selection([
        ('draft', 'Preview'),
        ('done', 'Completed'),
    ], default='draft', readonly=True)

    enrollment_count = fields.Integer(string="Scheme Enrollments", readonly=True)
    installment_count = fields.Integer(string="Scheme Installments", readonly=True)
    move_count = fields.Integer(string="Linked Scheme Journal Entries", readonly=True)
    move_line_count = fields.Integer(string="Journal Entry Lines", readonly=True)
    reconcile_count = fields.Integer(string="Reconciliations to Unlink", readonly=True)
    redemption_count = fields.Integer(string="Scheme Redemptions", readonly=True)
    pinelabs_count = fields.Integer(string="Pine Labs Scheme Payments", readonly=True)
    sale_order_scheme_count = fields.Integer(string="Sale Orders with Scheme Ref", readonly=True)

    confirm_deletion = fields.Boolean(
        string="I understand and confirm that this will permanently revert journal entries and delete all scheme data."
    )
    log_summary = fields.Text(string="Execution Summary", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        counts = self._compute_preview_counts()
        res.update(counts)
        return res

    def _table_exists(self, table_name):
        self.env.cr.execute("SELECT to_regclass(%s);", [table_name])
        row = self.env.cr.fetchone()
        return bool(row and row[0])

    def _compute_preview_counts(self):
        cr = self.env.cr
        counts = {
            'enrollment_count': 0,
            'installment_count': 0,
            'move_count': 0,
            'move_line_count': 0,
            'reconcile_count': 0,
            'redemption_count': 0,
            'pinelabs_count': 0,
            'sale_order_scheme_count': 0,
        }

        if self._table_exists('jewellery_scheme_enrollment'):
            cr.execute("SELECT count(*) FROM jewellery_scheme_enrollment;")
            counts['enrollment_count'] = cr.fetchone()[0]

        if self._table_exists('jewellery_scheme_installment'):
            cr.execute("SELECT count(*) FROM jewellery_scheme_installment;")
            counts['installment_count'] = cr.fetchone()[0]

            cr.execute("""
                SELECT count(DISTINCT id) FROM account_move
                WHERE id IN (
                    SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                    UNION
                    SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
                )
                OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%');
            """)
            counts['move_count'] = cr.fetchone()[0]

            cr.execute("""
                SELECT count(*) FROM account_move_line
                WHERE move_id IN (
                    SELECT id FROM account_move
                    WHERE id IN (
                        SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                        UNION
                        SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
                    )
                    OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%')
                );
            """)
            counts['move_line_count'] = cr.fetchone()[0]

            if self._table_exists('account_partial_reconcile'):
                cr.execute("""
                    SELECT count(*) FROM account_partial_reconcile pr
                    JOIN account_move_line l ON pr.debit_move_id = l.id OR pr.credit_move_id = l.id
                    WHERE l.move_id IN (
                        SELECT id FROM account_move
                        WHERE id IN (
                            SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                            UNION
                            SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
                        )
                        OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%')
                    );
                """)
                counts['reconcile_count'] = cr.fetchone()[0]

        if self._table_exists('scheme_redemption'):
            cr.execute("SELECT count(*) FROM scheme_redemption;")
            counts['redemption_count'] = cr.fetchone()[0]

        if self._table_exists('pinelabs_payment_wizard'):
            cr.execute("SELECT count(*) FROM pinelabs_payment_wizard WHERE scheme_installment_id IS NOT NULL;")
            counts['pinelabs_count'] = cr.fetchone()[0]

        if self._table_exists('sale_order'):
            cr.execute("""
                SELECT count(*) FROM information_schema.columns 
                WHERE table_name = 'sale_order' AND column_name = 'active_scheme_id';
            """)
            if cr.fetchone()[0] > 0:
                cr.execute("SELECT count(*) FROM sale_order WHERE active_scheme_id IS NOT NULL;")
                counts['sale_order_scheme_count'] = cr.fetchone()[0]

        return counts

    def action_refresh_counts(self):
        self.ensure_one()
        counts = self._compute_preview_counts()
        self.write(counts)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'scheme.cleanup.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_web_console(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/scheme_cleanup',
            'target': 'new',
        }

    def action_cleanup(self):
        self.ensure_one()
        if not self.confirm_deletion:
            raise UserError(_("Please check the confirmation box to confirm you want to proceed with deletion."))

        cr = self.env.cr
        logs = []
        logs.append("Starting Scheme Data Cleanup & Journal Reversal...")

        # 1. Identify all scheme account_move IDs
        cr.execute("""
            CREATE TEMP TABLE tmp_scheme_moves_to_delete ON COMMIT DROP AS
            SELECT DISTINCT id FROM account_move
            WHERE id IN (
                SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                UNION
                SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
            )
            OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%');
        """)
        cr.execute("CREATE INDEX IF NOT EXISTS idx_tmp_scheme_moves ON tmp_scheme_moves_to_delete(id);")
        cr.execute("SELECT count(*) FROM tmp_scheme_moves_to_delete;")
        total_moves = cr.fetchone()[0]
        logs.append(f"[Step 1] Identified {total_moves:,} scheme journal entries to revert & delete.")

        # 2. Clear foreign keys on sale_order
        if self._table_exists('sale_order'):
            cr.execute("""
                SELECT count(*) FROM information_schema.columns 
                WHERE table_name = 'sale_order' AND column_name = 'active_scheme_id';
            """)
            if cr.fetchone()[0] > 0:
                cr.execute("UPDATE sale_order SET active_scheme_id = NULL WHERE active_scheme_id IS NOT NULL;")
                logs.append(f"[Step 2] Cleared active_scheme_id on {cr.rowcount} sale order(s).")

        # 3. Delete pinelabs payment wizards linked to scheme installments
        if self._table_exists('pinelabs_payment_wizard'):
            cr.execute("DELETE FROM pinelabs_payment_wizard WHERE scheme_installment_id IS NOT NULL;")
            logs.append(f"[Step 3] Deleted {cr.rowcount} pinelabs_payment_wizard record(s).")

        # 4. Delete scheme redemptions
        if self._table_exists('scheme_redemption'):
            cr.execute("DELETE FROM scheme_redemption;")
            logs.append(f"[Step 4] Deleted {cr.rowcount} scheme_redemption record(s).")

        # 5. Check customer_scheme & customer_scheme_payment
        if self._table_exists('customer_scheme_payment'):
            cr.execute("DELETE FROM customer_scheme_payment;")
        if self._table_exists('customer_scheme'):
            cr.execute("DELETE FROM customer_scheme;")
        logs.append("[Step 5] Cleaned customer_scheme tables.")

        if total_moves > 0:
            # 6. Unlink any partial reconciliations involving these move lines
            if self._table_exists('account_partial_reconcile'):
                cr.execute("""
                    DELETE FROM account_partial_reconcile
                    WHERE debit_move_id IN (
                        SELECT id FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete)
                    )
                    OR credit_move_id IN (
                        SELECT id FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete)
                    );
                """)
                logs.append(f"[Step 6] Removed {cr.rowcount} partial reconciliation(s).")

            # 7. Unlink account_payment if any
            if self._table_exists('account_payment'):
                cr.execute("DELETE FROM account_payment WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
                logs.append(f"[Step 7] Removed {cr.rowcount} account_payment record(s).")

            # 8. Unlink mail followers and messages on these moves
            if self._table_exists('mail_followers'):
                cr.execute("DELETE FROM mail_followers WHERE res_model = 'account.move' AND res_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
            if self._table_exists('mail_message'):
                cr.execute("DELETE FROM mail_message WHERE model = 'account.move' AND res_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
            logs.append("[Step 8] Removed mail followers and messages on scheme moves.")

            # 9. Delete account_move_line
            cr.execute("DELETE FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
            logs.append(f"[Step 9] Deleted {cr.rowcount:,} account_move_line record(s).")

        # 10. Delete scheme installments FIRST (empties unindexed FK table for instant move deletion)
        if self._table_exists('jewellery_scheme_installment'):
            cr.execute("UPDATE jewellery_scheme_installment SET move_id = NULL, suspense_move_id = NULL;")
            cr.execute("DELETE FROM jewellery_scheme_installment;")
            logs.append(f"[Step 10] Deleted {cr.rowcount:,} scheme installment(s).")

        # 11. Delete scheme enrollments
        if self._table_exists('jewellery_scheme_enrollment'):
            cr.execute("DELETE FROM jewellery_scheme_enrollment;")
            logs.append(f"[Step 11] Deleted {cr.rowcount:,} scheme enrollment(s).")

        # 12. Delete account_move
        if total_moves > 0:
            cr.execute("DELETE FROM account_move WHERE id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
            logs.append(f"[Step 12] Deleted {cr.rowcount:,} account_move record(s).")

        # 13. Invalidate ORM cache
        self.env.invalidate_all()
        logs.append("[Step 13] Successfully cleared Odoo ORM registry cache.")

        # 14. Final verification count
        post_counts = self._compute_preview_counts()
        logs.append("\n=== POST-CLEANUP VERIFICATION ===")
        for key, val in post_counts.items():
            logs.append(f"{key}: {val}")
        logs.append("Scheme data cleanup completed successfully!")

        summary_text = "\n".join(logs)
        _logger.info(summary_text)

        self.write({
            'state': 'done',
            'log_summary': summary_text,
            'enrollment_count': post_counts['enrollment_count'],
            'installment_count': post_counts['installment_count'],
            'move_count': post_counts['move_count'],
            'move_line_count': post_counts['move_line_count'],
            'reconcile_count': post_counts['reconcile_count'],
            'redemption_count': post_counts['redemption_count'],
            'pinelabs_count': post_counts['pinelabs_count'],
            'sale_order_scheme_count': post_counts['sale_order_scheme_count'],
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'scheme.cleanup.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
