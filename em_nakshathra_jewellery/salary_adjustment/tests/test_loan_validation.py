# -*- coding: utf-8 -*-
from odoo.tests import common
from odoo.exceptions import ValidationError
from odoo import fields

class TestLoanValidation(common.TransactionCase):
    def setUp(self):
        super(TestLoanValidation, self).setUp()
        self.company = self.env.company
        self.employee = self.env['hr.employee'].create({
            'name': 'Test Loan Validation Employee',
            'joining_date': fields.Date.to_date('2024-01-01'),
            'company_id': self.company.id,
        })
        self.contract = self.env['hr.contract'].create({
            'name': 'Test Loan Validation Contract',
            'employee_id': self.employee.id,
            'wage': 10000.0,
            'date_start': fields.Date.to_date('2024-01-01'),
            'state': 'open',
            'company_id': self.company.id,
        })
        self.employee.contract_id = self.contract.id

    def test_loan_approval_installment_exceeds_30_percent_failure(self):
        """Test loan approval blocked when installment exceeds 30% of salary"""
        loan = self.env['salary.loan'].create({
            'employee_id': self.employee.id,
            'amount': 4000.0,
            'tenure_months': 1,
            'company_id': self.company.id,
        })
        with self.assertRaises(ValidationError) as cm:
            loan.action_approve()
        self.assertIn("IF THE MONTHLY INSTALLMENT EXCEEDS 30% OF THE SALARY.<br/><span style='color: red;'>So please set the tenure period.</span>", str(cm.exception))

    def test_loan_approval_installment_within_30_percent_success(self):
        """Test loan approval allowed when installment is <= 30% of salary"""
        loan = self.env['salary.loan'].create({
            'employee_id': self.employee.id,
            'amount': 3000.0,
            'tenure_months': 1,
            'company_id': self.company.id,
        })
        loan.action_approve()
        self.assertEqual(loan.state, 'approved')
