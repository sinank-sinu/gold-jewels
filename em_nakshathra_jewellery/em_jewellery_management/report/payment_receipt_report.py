from odoo import models, api


class ReportPaymentReceipt(models.AbstractModel):
    _name = 'report.account.report_payment_receipt'
    _description = 'Payment Receipt Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        payments = self.env['account.payment'].browse(docids)

        def get_payment_method_label(payment):
            if 'pinelabs_transaction_id' in payment and payment.pinelabs_transaction_id:
                pt = payment.pinelabs_transaction_id
                card_type = (pt.card_type or '').upper()
                payment_mode = (pt.payment_mode or '').upper()
                if 'UPI' in card_type or 'UPI' in payment_mode:
                    return 'UPI'
                return 'Card'

            journal = payment.journal_id
            j_name = (journal.name or '').lower() if journal else ''
            j_type = journal.type if journal else ''
            ref_str = (payment.ref or '').lower()

            if 'upi' in j_name or 'upi' in ref_str or 'gpay' in ref_str or 'phonepe' in ref_str or 'paytm' in ref_str:
                return 'UPI'
            if 'card' in j_name or 'pos' in ref_str or 'pine' in j_name or 'pine' in ref_str:
                return 'Card'
            if j_type == 'cash' or 'cash' in j_name:
                return 'Cash'
            return 'Bank'

        def get_payment_ref_label(payment):
            if 'bank_reference' in payment and payment.bank_reference:
                return str(payment.bank_reference).strip()
            if payment.ref and payment.ref != payment.name:
                return str(payment.ref).strip()
            return str(payment.name or '').strip()

        # Group payments by (sale_id, partner_id) when sale_id is present
        groups_dict = {}
        order_of_groups = []

        for p in payments:
            if p.sale_id:
                key = ('sale', p.sale_id.id, p.partner_id.id)
            else:
                key = ('payment', p.id)

            if key not in groups_dict:
                groups_dict[key] = []
                order_of_groups.append(key)
            groups_dict[key].append(p)

        payment_groups = []
        for key in order_of_groups:
            group_payments = self.env['account.payment'].concat(*groups_dict[key])
            main_payment = group_payments[-1]
            total_amount = sum(group_payments.mapped('amount'))

            # Unique ordered payment methods
            methods = []
            for p in group_payments:
                m = get_payment_method_label(p)
                if m and m not in methods:
                    methods.append(m)
            disp_pay_method = ', '.join(methods) if methods else 'Bank'

            # Unique ordered references / UTRs
            refs = []
            for p in group_payments:
                r = get_payment_ref_label(p)
                if r and r not in refs:
                    refs.append(r)
            disp_payment_ref = ', '.join(refs) if refs else (main_payment.name or '-')

            # Latest payment date
            dates = [p.date for p in group_payments if p.date]
            latest_date = max(dates) if dates else main_payment.date

            payment_groups.append({
                'main_payment': main_payment,
                'payments': group_payments,
                'total_amount': total_amount,
                'sale_id': main_payment.sale_id,
                'partner_id': main_payment.partner_id,
                'disp_pay_method': disp_pay_method,
                'disp_payment_ref': disp_payment_ref,
                'date': latest_date,
                'is_consolidated': len(group_payments) > 1,
            })

        return {
            'doc_ids': docids,
            'doc_model': 'account.payment',
            'docs': payments,
            'payment_groups': payment_groups,
        }

