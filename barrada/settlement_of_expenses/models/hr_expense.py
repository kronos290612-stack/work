# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    verified = fields.Boolean(
        string='Verified', default=False,
        help='Check to view total verified expenses')

    real_expenses = fields.Monetary(
        string='Real Expenses',
        help='Enter the actual amount spent',
        tracking=True)

    total_expenses_verified = fields.Monetary(
        string='Verified Expenses',
        compute='_compute_total_expenses_verified',
        store=False,
        help='Amount visible only when verified'
               )

    supporting_documents = fields.Binary(
        string='Supporting Documents',
        help='Please Only Allowed Formats (PDF, JPG, JPEG or PNG)',
        tracking=False)

    refund = fields.Monetary(
        string='Refund',
        compute='_compute_diferenc',
        store=True,
        readonly=True,
        help='Negative: employee owes money to the company\nPositive: company owes money to employee'
    )

     # CALCULO DE DIFERENCIA ENTRE DOS CAMPOS
    @api.depends('real_expenses', 'total_amount')
    def _compute_diferenc(self):
        for record in self:
            real_expenses = record.real_expenses or 0.0
            total_amount = record.total_amount or 0.0
            record.refund = float(total_amount - real_expenses)

    # MOSTAR CAMPO SI CHECKBOX ACTIVO
    @api.depends('verified', 'real_expenses')
    def _compute_total_expenses_verified(self):
     for expense in self:
        expense.total_expenses_verified = expense.real_expenses if expense.verified else 0.0


     # Asegurar diario al validar reporte
     def action_sheet_move_create(self):
         """Garantizar que las facturas usen el diario de gastos configurado"""
         company = self.company_id or self.env.company

         if company.expense_claim_use_same_journal and company.expense_journal_id:
             # Forzar contexto para que account.move.create use el diario correcto
             self = self.with_context(
                 default_journal_id=company.expense_journal_id.id,
                 force_expense_journal=True
             )

         return super().action_sheet_move_create()



