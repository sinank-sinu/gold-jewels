from odoo import models, fields, _, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare
from dateutil.relativedelta import relativedelta  # Added for safe month arithmetic

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
    move_id = fields.Many2one('account.move')
    transaction_id = fields.Char(string="Transaction ID", copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('paid', 'Paid')
    ], default='draft')


    @api.model_create_multi
    def create(self, vals_list):
        """
        Intercepts creation to split bulk lump-sum payments into individual lines.
        Respects the user's selected date for the active payment, and calculates 
        clean historical dates for the caught-up pending months.
        """
        new_vals_list = []

        for vals in vals_list:
            enrollment = self.env['jewellery.scheme.enrollment'].browse(vals.get('enrollment_id'))
            
            if enrollment and vals.get('amount'):
                inst_amt = enrollment.installment_amount
                entered_amt = vals.get('amount')
                # Fallback to today if no date is present in vals
                user_selected_date = fields.Date.to_date(vals.get('date')) or fields.Date.today()

                # Check if entered amount is greater than standard installment amount
                if float_compare(entered_amt, inst_amt, precision_digits=2) > 0 and inst_amt > 0:
                    remaining_amount = entered_amt
                    
                    # 1. Calculate how many total pieces this lump sum splits into
                    # e.g., 3000 / 1000 = 3 installments total
                    total_split_lines = int(entered_amt // inst_amt)
                    if entered_amt % inst_amt > 0:
                        total_split_lines += 1

                    line_index = 0
                    while float_compare(remaining_amount, 0, precision_digits=2) > 0:
                        current_line_amt = inst_amt if float_compare(remaining_amount, inst_amt, precision_digits=2) >= 0 else remaining_amount
                        
                        # 2. Work backwards from the user-selected date for the older months.
                        # The very last line gets the exact date the user picked.
                        # Previous lines get subtracted by 1 month, 2 months, etc.
                        months_to_subtract = (total_split_lines - 1) - line_index
                        calculated_line_date = user_selected_date - relativedelta(months=months_to_subtract)

                        line_vals = vals.copy()
                        line_vals['amount'] = current_line_amt
                        line_vals['date'] = calculated_line_date
                        
                        new_vals_list.append(line_vals)
                        
                        remaining_amount -= current_line_amt
                        line_index += 1
                else:
                    # If it's a standard single payment, do NOT alter the date. 
                    # Keep exactly what the user selected in the interface.
                    new_vals_list.append(vals)
            else:
                new_vals_list.append(vals)

        return super(JewellerySchemeInstallment, self).create(new_vals_list)
  
    def action_confirm_payment(self):
        """ 
        Overriding to open the Pine Labs payment gateway instead of 
        instantly generating a manual local journal entry.
        """
        for rec in self:
            if rec.state == 'paid' or rec.move_id:
                raise UserError(_("This installment has already been paid."))

            if rec.amount <= 0:
                raise UserError(_("Installment amount must be greater than zero."))

            # Open the Pine Labs payment wizard, passing the current installment details in context
            return {
                'name': _('Pay via Pine Labs (Scheme)'),
                'type': 'ir.actions.act_window',
                'res_model': 'pinelabs.payment.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_amount': rec.amount,
                    'default_scheme_installment_id': rec.id, # Map back to this line when transaction finishes
                },
            }




# from odoo import models, fields, _, api
# from odoo.exceptions import UserError, ValidationError

# class JewellerySchemeInstallment(models.Model):
#     _name = 'jewellery.scheme.installment'
#     _description = 'Scheme Installment'

#     enrollment_id = fields.Many2one(
#         'jewellery.scheme.enrollment',
#         required=True,
#         ondelete='cascade'
#     )

#     date = fields.Date(default=fields.Date.today)
#     amount = fields.Float(required=True)

#     journal_id = fields.Many2one('account.journal')
#     move_id = fields.Many2one('account.move')
#     transaction_id = fields.Char(string="Transaction ID", copy=False)
#     state = fields.Selection([
#         ('draft', 'Draft'),
#         ('paid', 'Paid')
#     ], default='draft')

#     def action_confirm_payment(self):
#         """ 
#         Overriding to open the Pine Labs payment gateway instead of 
#         instantly generating a manual local journal entry.
#         """
#         for rec in self:
#             if rec.state == 'paid' or rec.move_id:
#                 raise UserError(_("This installment has already been paid."))

#             if rec.amount <= 0:
#                 raise UserError(_("Installment amount must be greater than zero."))

#             # Open the Pine Labs payment wizard, passing the current installment details in context
#             return {
#                 'name': _('Pay via Pine Labs (Scheme)'),
#                 'type': 'ir.actions.act_window',
#                 'res_model': 'pinelabs.payment.wizard',
#                 'view_mode': 'form',
#                 'target': 'new',
#                 'context': {
#                     'default_amount': rec.amount,
#                     'default_scheme_installment_id': rec.id, # Map back to this line when transaction finishes
#                 },
#             }

    