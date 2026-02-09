# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class HrExpenseSheet(models.Model):
    _inherit = 'hr.expense.sheet'

    # CAMPOS DE SOLICITUD DE VIAJE
    destination = fields.Char(string='Destination', tracking=True)
    justification = fields.Text(string='Justification', tracking=True)

    # Expensas
    overnight = fields.Boolean(string='Overnight', default=False, tracking=True)
    date_since = fields.Date(string='From', tracking=True)
    date_up = fields.Date(string='Until', tracking=True)
    number_days = fields.Integer(
        string='Number of days',
        compute='_compute_number_of_days',
        store=True,
        readonly=True
    )

   # ========== CAMPOS DE LIQUIDACIÓN ==========
    liquidation_status = fields.Selection([
        ('pending', 'Pending settlement'),
        ('liquidated', 'Liquidated'),
    ], string='Liquidation Status',
        compute='_compute_liquidation_status',
        store=True,
        readonly=True,
        default='pending')

   

    # ========== METHODS ==========
    @api.depends('date_since', 'date_up')
    def _compute_number_of_days(self):
        for sheet in self:
            if sheet.date_since and sheet.date_up:
                delta = sheet.date_up - sheet.date_since
                sheet.number_days = delta.days + 1
            else:
                sheet.number_days = 0

    @api.depends('expense_line_ids.total_actual_expense_verified')
    def _compute_totals_liquidation(self):
        for sheet in self:
            if sheet.is_liquidation:
                total_verified = sum(sheet.expense_line_ids.mapped('total_actual_expense_verified'))
                sheet.total_experiences_verified = total_verified
                sheet.refund = sheet.total_amount - total_verified
            else:
                sheet.total_experiences_verified = 0.0
                sheet.refund = 0.0

    @api.depends('settlement_sheet_id')
    def _compute_totals_liquidation(self):
        for sheet in self:
            sheet.liquidation_state = 'liquidated' if sheet.settlement_sheet_id else 'pending'

  