# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta
from dateutil.relativedelta import relativedelta


class SalesmanTargetTransferWizard(models.TransientModel):
    _name = 'salesman.target.transfer.wizard'
    _description = 'Transfer Salesman and Split/Reassign Target'

    target_id = fields.Many2one(
        'salesman.target',
        string='Source Target',
        required=True,
        readonly=True,
    )
    salesman_id = fields.Many2one(
        'res.users',
        related='target_id.salesman_id',
        string='Transferred Salesman',
        readonly=True,
    )
    branch_id = fields.Many2one(
        'res.branch',
        related='target_id.branch_id',
        string='Current Branch',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='target_id.currency_id',
        readonly=True,
    )
    date_from = fields.Date(
        related='target_id.date_from',
        string='Period From',
        readonly=True,
    )
    date_to = fields.Date(
        related='target_id.date_to',
        string='Period To',
        readonly=True,
    )

    transfer_date = fields.Date(
        string='Transfer Date',
        required=True,
        default=fields.Date.today,
        help="Effective transfer date (last working day of employee at current branch)."
    )

    total_days = fields.Integer(
        string='Total Period Days',
        compute='_compute_split_details',
    )
    days_worked = fields.Integer(
        string='Days Worked (Former)',
        compute='_compute_split_details',
    )
    days_remaining = fields.Integer(
        string='Days Remaining (Balance)',
        compute='_compute_split_details',
    )
    former_ratio = fields.Float(
        string='Former Share (%)',
        compute='_compute_split_details',
    )
    balance_ratio = fields.Float(
        string='Balance Share (%)',
        compute='_compute_split_details',
    )

    # Current Branch Successor
    assign_successor = fields.Boolean(
        string='Assign Balance Target to Replacement',
        default=True,
        help="Assign the remaining days and balance target in current branch to a replacement salesperson."
    )
    successor_salesman_id = fields.Many2one(
        'res.users',
        string='Replacement Salesperson',
        domain="[('share', '=', False), ('branch_ids', 'in', branch_id), ('id', '!=', salesman_id)]",
    )

    # Destination Branch
    destination_mode = fields.Selection([
        ('create_new', 'Create New Target in Destination Branch'),
        ('none', 'Do Not Create in New Branch (Assign Manually Later)'),
    ], default='create_new', string='Destination Branch Allocation')

    destination_branch_id = fields.Many2one(
        'res.branch',
        string='Destination Branch',
    )

    @api.depends('target_id', 'transfer_date')
    def _compute_split_details(self):
        for wizard in self:
            target = wizard.target_id
            if not target or not target.date_from or not target.date_to or not wizard.transfer_date:
                wizard.total_days = 0
                wizard.days_worked = 0
                wizard.days_remaining = 0
                wizard.former_ratio = 0.0
                wizard.balance_ratio = 0.0
                continue

            t_days = (target.date_to - target.date_from).days + 1
            worked = max(0, min(t_days, (wizard.transfer_date - target.date_from).days + 1))
            remaining = max(0, t_days - worked)

            wizard.total_days = t_days
            wizard.days_worked = worked
            wizard.days_remaining = remaining
            wizard.former_ratio = (worked / t_days) if t_days else 0.0
            wizard.balance_ratio = (remaining / t_days) if t_days else 0.0

    def action_apply_transfer(self):
        self.ensure_one()
        target = self.target_id
        if not (target.date_from <= self.transfer_date <= target.date_to):
            raise ValidationError(
                _("Transfer date must be within Period From (%s) and Period To (%s).")
                % (target.date_from, target.date_to)
            )

        if self.assign_successor and not self.successor_salesman_id:
            raise ValidationError(
                _("Please select a replacement salesperson or uncheck 'Assign Balance Target to Replacement'.")
            )

        if self.destination_mode == 'create_new' and not self.destination_branch_id:
            raise ValidationError(_("Please select the Destination Branch."))

        worked = self.days_worked
        total = self.total_days
        remaining = self.days_remaining

        if total <= 0:
            raise ValidationError(_("Total period days must be greater than zero."))

        ratio_former = self.former_ratio
        ratio_balance = self.balance_ratio

        # 1. Store original full targets on target if not already stored
        if not target.orig_target_amount and not target.orig_target_gms_22k and not target.orig_target_gms_18ct:
            target.write({
                'orig_target_amount': target.target_amount,
                'orig_target_gms_22k': target.target_gms_22k,
                'orig_target_gms_18ct': target.target_gms_18ct,
                'orig_target_gms_22kt': target.target_gms_22kt,
                'orig_target_diamond_ct': target.target_diamond_ct,
                'orig_incentive_amount': target.incentive_amount,
            })

        orig_amount = target.orig_target_amount or target.target_amount
        orig_22k = target.orig_target_gms_22k or target.target_gms_22k
        orig_18ct = target.orig_target_gms_18ct or target.target_gms_18ct
        orig_22kt = target.orig_target_gms_22kt or target.target_gms_22kt
        orig_dmd = target.orig_target_diamond_ct or target.target_diamond_ct
        orig_inc = target.orig_incentive_amount or target.incentive_amount

        # Pro-rated targets for former employee
        former_amount = round(orig_amount * ratio_former, 2)
        former_22k = round(orig_22k * ratio_former, 3)
        former_18ct = round(orig_18ct * ratio_former, 3)
        former_22kt = round(orig_22kt * ratio_former, 3)
        former_dmd = round(orig_dmd * ratio_former, 3)
        former_inc = round(orig_inc * ratio_former, 2)

        # Balance targets for successor
        balance_amount = max(0.0, round(orig_amount - former_amount, 2))
        balance_22k = max(0.0, round(orig_22k - former_22k, 3))
        balance_18ct = max(0.0, round(orig_18ct - former_18ct, 3))
        balance_22kt = max(0.0, round(orig_22kt - former_22kt, 3))
        balance_dmd = max(0.0, round(orig_dmd - former_dmd, 3))
        balance_inc = max(0.0, round(orig_inc - former_inc, 2))

        original_date_to = target.date_to

        # 2. Update former employee target record
        target.write({
            'date_to': self.transfer_date,
            'is_transferred': True,
            'transfer_date': self.transfer_date,
            'target_amount': former_amount,
            'target_gms_22k': former_22k,
            'target_gms_18ct': former_18ct,
            'target_gms_22kt': former_22kt,
            'target_diamond_ct': former_dmd,
            'incentive_amount': former_inc,
            'state': 'transferred',
        })
        target._compute_achievements()
        target._incentive_add()

        target.message_post(
            body=_("<b>Salesman Transferred</b> on %s.<br/>"
                   "Worked %s of %s days (%.1f%%).<br/>"
                   "Target pro-rated to worked period. Achieved incentive: %s (Eligible for payslip redemption).") % (
                self.transfer_date, worked, total, ratio_former * 100, target.earned_incentive
            )
        )

        successor_start_date = self.transfer_date + timedelta(days=1)
        created_count = 0

        # 3. Create Successor Target in Current Branch (Balance Target)
        if self.assign_successor and self.successor_salesman_id and remaining > 0 and successor_start_date <= original_date_to:
            successor_vals = {
                'salesman_id': self.successor_salesman_id.id,
                'branch_id': target.branch_id.id,
                'date_from': successor_start_date,
                'date_to': original_date_to,
                'target_amount': balance_amount,
                'target_gms_22k': balance_22k,
                'target_gms_18ct': balance_18ct,
                'target_gms_22kt': balance_22kt,
                'target_diamond_ct': balance_dmd,
                'incentive_amount': balance_inc,
                'branch_target_amount': target.branch_target_amount,
                'branch_target_gms_22k': target.branch_target_gms_22k,
                'branch_target_gms_18ct': target.branch_target_gms_18ct,
                'branch_target_gms_22kt': target.branch_target_gms_22kt,
                'branch_target_diamond_ct': target.branch_target_diamond_ct,
                'inc_18ct': target.inc_18ct,
                'dmd_inc': target.dmd_inc,
                'gold_inc': target.gold_inc,
                'parent_target_id': target.id,
                'state': 'confirmed',
            }
            succ_target = self.env['salesman.target'].create(successor_vals)
            succ_target._compute_achievements()
            succ_target._incentive_add()
            created_count += 1
            succ_target.message_post(
                body=_("<b>Successor Target Created</b> following transfer of %s.<br/>"
                       "Assigned balance target for remaining %s days (%.1f%%).") % (
                    target.salesman_id.name, remaining, ratio_balance * 100
                )
            )

        # 4. Create Destination Branch Target for Transferred Employee
        if self.destination_mode == 'create_new' and self.destination_branch_id and remaining > 0 and successor_start_date <= original_date_to:
            dest_existing = self.env['salesman.target'].search([
                ('branch_id', '=', self.destination_branch_id.id),
                ('date_from', '<=', successor_start_date),
                ('date_to', '>=', original_date_to),
            ], limit=1, order='create_date desc, id desc')

            dest_target_amount = round((dest_existing.target_amount if dest_existing else orig_amount) * ratio_balance, 2)
            dest_target_22k = round((dest_existing.target_gms_22k if dest_existing else orig_22k) * ratio_balance, 3)
            dest_target_18ct = round((dest_existing.target_gms_18ct if dest_existing else orig_18ct) * ratio_balance, 3)
            dest_target_22kt = round((dest_existing.target_gms_22kt if dest_existing else orig_22kt) * ratio_balance, 3)
            dest_target_dmd = round((dest_existing.target_diamond_ct if dest_existing else orig_dmd) * ratio_balance, 3)
            dest_inc = round((dest_existing.incentive_amount if dest_existing else orig_inc) * ratio_balance, 2)

            dest_vals = {
                'salesman_id': target.salesman_id.id,
                'branch_id': self.destination_branch_id.id,
                'date_from': successor_start_date,
                'date_to': original_date_to,
                'target_amount': dest_target_amount,
                'target_gms_22k': dest_target_22k,
                'target_gms_18ct': dest_target_18ct,
                'target_gms_22kt': dest_target_22kt,
                'target_diamond_ct': dest_target_dmd,
                'incentive_amount': dest_inc,
                'branch_target_amount': dest_existing.branch_target_amount if dest_existing else 0.0,
                'branch_target_gms_22k': dest_existing.branch_target_gms_22k if dest_existing else 0.0,
                'branch_target_gms_18ct': dest_existing.branch_target_gms_18ct if dest_existing else 0.0,
                'branch_target_gms_22kt': dest_existing.branch_target_gms_22kt if dest_existing else 0.0,
                'branch_target_diamond_ct': dest_existing.branch_target_diamond_ct if dest_existing else 0.0,
                'inc_18ct': dest_existing.inc_18ct if dest_existing else target.inc_18ct,
                'dmd_inc': dest_existing.dmd_inc if dest_existing else target.dmd_inc,
                'gold_inc': dest_existing.gold_inc if dest_existing else target.gold_inc,
                'parent_target_id': target.id,
                'state': 'confirmed',
            }
            dest_target = self.env['salesman.target'].create(dest_vals)
            dest_target._compute_achievements()
            dest_target._incentive_add()
            created_count += 1
            dest_target.message_post(
                body=_("<b>Destination Target Created</b> for %s at %s.<br/>"
                       "Period: %s to %s (%s days).") % (
                    target.salesman_id.name, self.destination_branch_id.name, successor_start_date, original_date_to, remaining
                )
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Transfer Completed"),
                'message': _("Former target pro-rated and redeemed. Created %d target(s).") % created_count,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
