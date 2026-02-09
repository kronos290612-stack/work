# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.tools import SQL


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    area_expense_id = fields.Many2one('account.area.expense', string='Expense Area', copy=True)

    @api.constrains('account_id', 'display_type')
    def _check_payable_receivable(self):
        super(AccountMoveLine, self.filtered(lambda line: line.move_id.account_area_expense_sheet_id.payment_mode != 'company_account'))._check_payable_receivable()

    def _get_attachment_domains(self):
        attachment_domains = super(AccountMoveLine, self)._get_attachment_domains()
        if self.area_expense_id:
            attachment_domains.append([('res_model', '=', 'account.area.expense'), ('res_id', '=', self.area_expense_id.id)])
        return attachment_domains

    def _compute_totals(self):
        expenses = self.filtered('area_expense_id')
        super(AccountMoveLine, expenses.with_context(force_price_include=True))._compute_totals()
        super(AccountMoveLine, self - expenses)._compute_totals()

    def _get_extra_query_base_tax_line_mapping(self) -> SQL:
        return SQL(' AND (base_line.area_expense_id IS NULL OR account_move_line.area_expense_id = base_line.area_expense_id)')
