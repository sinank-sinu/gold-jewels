from odoo import models, fields, api


class JewelleryJobWork(models.Model):
    _inherit = 'jewellery.job.work'

    # -------------------------------------------------------------------------
    # Revert / Cancel
    # -------------------------------------------------------------------------

    @api.depends('job_worker_id', 'state')
    def _compute_job_worker_balance(self):
        super()._compute_job_worker_balance()
        for rec in self:
            if rec.state == 'draft':
                rec.job_worker_balance = 0.0

    def action_revert(self):
        """
        Revert the job work completely:
        - DELETE stock pickings/moves forcefully (no return)
        - Cancel Vouchers, delete their lines, clear values, and UNLINK them
        - Clear Requisition, Branch, and MO links
        - Delete Job Work lines and mark as Cancelled
        """
        self.ensure_one()

        # ── RECEIVE VOUCHERS ─────────────────────────────────────────────────
        for rv in self.receive_voucher_ids:
            self._delete_picking_forcefully(rv.picking_id)
            rv.line_ids.unlink()
            rv.write({
                'state': 'draft',
                'job_worker_id': False,
                'job_work_id': False,
                'branch_id': False,
            })

        # ── ISSUE VOUCHERS ────────────────────────────────────────────────────
        for iv in self.issue_voucher_ids:
            self._delete_picking_forcefully(iv.picking_id)
            iv.line_ids.unlink()
            iv.write({
                'state': 'draft',
                'job_worker_id': False,
                'job_work_id': False,
                'branch_id': False,
            })

        # ── LABELS ──────────────────────────────────────────────────────────
        # Search for labels created from this Job Work and delete them
        labels = self.env['product.label'].search([('job_work_id', '=', self.id)])
        for label in labels:
            # If the label had a stock-in picking, delete it
            self._delete_picking_forcefully(label.picking_id)
        labels.unlink()

        # ── REQUISITION & BRANCH & MO LINKS ─────────────────────────────────
        if self.requisition_id:
            # Delete Requisition lines
            self.requisition_id.requisition_lines.unlink()
            # Re-enable the requisition by removing the link and resetting state
            self.requisition_id.sudo().write({
                'job_work_id': False,
                'state': 'new',
            })
            
        self.write({
            'requisition_id': False,
            'branch_id': False,
            'mo_id': False,
        })

        # ── JOB WORK: Clear lines and Mark as Cancelled ─────────────────────
        self.job_work_line_ids.unlink()
        self.write({'state': 'draft'})

    def _delete_picking_forcefully(self, picking):
        """
        Forcefully delete a stock picking and all its moves/layers/lines.
        Since Odoo prevents unlinking 'done' pickings, we use direct SQL.
        """
        if not picking:
            return
        
        picking_id = picking.id
        
        # 1. Delete associated Valuation Layers (must be first for FKs)
        self.env.cr.execute(
            "DELETE FROM stock_valuation_layer WHERE stock_move_id IN (SELECT id FROM stock_move WHERE picking_id = %s)", 
            [picking_id]
        )
        # 2. Delete Stock Move Lines
        self.env.cr.execute("DELETE FROM stock_move_line WHERE picking_id = %s", [picking_id])
        # 3. Delete Stock Moves
        self.env.cr.execute("DELETE FROM stock_move WHERE picking_id = %s", [picking_id])
        # 4. Finally delete the Picking itself
        self.env.cr.execute("DELETE FROM stock_picking WHERE id = %s", [picking_id])
        # 5. Invalidate Odoo's internal cache for these records
        picking.invalidate_recordset()
