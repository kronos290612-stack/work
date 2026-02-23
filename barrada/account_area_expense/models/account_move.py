# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.api import ondelete
from odoo.exceptions import UserError
from odoo.tools.misc import frozendict
from odoo.addons.hr_expense.models.account_move import AccountMove as Account_Move_expense


class AccountMove(models.Model):
    _inherit = "account.move"

    account_area_expense_sheet_id = fields.Many2one(comodel_name='account.area.expense.sheet', ondelete='set null',
                                                    copy=False, index='btree_not_null')

    def _prepare_product_base_line_for_taxes_computation(self, product_line):
        # EXTENDS 'account'
        results = super(Account_Move_expense, self)._prepare_product_base_line_for_taxes_computation(product_line)
        if product_line.expense_id:
            results['special_mode'] = 'total_included'
        elif product_line.area_expense_id:
            results['special_mode'] = 'total_included'
        return results

    @api.depends('partner_id', 'expense_sheet_id', 'company_id')
    def _compute_commercial_partner_id(self):
        is_area_sheet_context = self.get_context_account_area_expense()
        if not is_area_sheet_context:
            own_expense_moves = self.filtered(lambda move: move.sudo().expense_sheet_id.payment_mode == 'own_account')
        else:
            own_expense_moves = self.filtered(lambda move: move.sudo().account_area_expense_sheet_id.payment_mode == 'own_account')
        for move in own_expense_moves:
            if (not is_area_sheet_context and move.expense_sheet_id.payment_mode == 'own_account') or \
                    (is_area_sheet_context and move.expense_sheet_id.payment_mode == 'own_account'):
                move.commercial_partner_id = (
                    move.partner_id.commercial_partner_id
                    if move.partner_id.commercial_partner_id != move.company_id.partner_id
                    else move.partner_id
                )
        super(Account_Move_expense, self - own_expense_moves)._compute_commercial_partner_id()

    def get_context_account_area_expense(self):
        is_area_sheet_context = self.env.context.get('account_area_expense_sheet', False)
        return is_area_sheet_context

    def action_open_expense_report(self):
        self.ensure_one()
        return {
            'name': self.expense_sheet_id.name if self.expense_sheet_id else self.account_area_expense_sheet_id.name,
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'res_model': 'hr.expense.sheet' if self.expense_sheet_id else 'account.area.expense',
            'res_id': self.expense_sheet_id.id if self.expense_sheet_id else self.account_area_expense_sheet_id.id
        }

    @api.depends('commercial_partner_id')
    def _compute_show_commercial_partner_warning(self):
        for move in self:
            move.show_commercial_partner_warning = (
                    move.commercial_partner_id == self.env.company.partner_id
                    and move.move_type == 'in_invoice'
                    and move.partner_id.employee_ids
            )

    def _creation_message(self):
        is_area_sheet_context = self.get_context_account_area_expense()
        if not is_area_sheet_context and self.expense_sheet_id:
            return _("Expense entry created from: %s", self.expense_sheet_id._get_html_link())
        elif is_area_sheet_context and self.account_area_expense_sheet_id:
            return _("Expense entry created from: %s", self.account_area_expense_sheet_id._get_html_link())
        return super(Account_Move_expense, self)._creation_message()

    @api.depends('expense_sheet_id')
    def _compute_needed_terms(self):
        # EXTENDS account
        # We want to set the account destination based on the 'payment_mode'.
        super(Account_Move_expense, self)._compute_needed_terms()
        for move in self:
            if move.expense_sheet_id and move.expense_sheet_id.payment_mode == 'company_account':
                term_lines = move.line_ids.filtered(lambda l: l.display_type != 'payment_term')
                move.needed_terms = {
                    frozendict(
                        {
                            "move_id": move.id,
                            "date_maturity": move.expense_sheet_id.accounting_date or fields.Date.context_today(
                                move.expense_sheet_id),
                        }
                    ): {
                        "balance": -sum(term_lines.mapped("balance")),
                        "amount_currency": -sum(term_lines.mapped("amount_currency")),
                        "name": "",
                        "account_id": move.expense_sheet_id._get_expense_account_destination(),
                    }
                }
            elif move.account_area_expense_sheet_id and move.account_area_expense_sheet_id.payment_mode == 'company_account':
                term_lines = move.line_ids.filtered(lambda l: l.display_type != 'payment_term')
                move.needed_terms = {
                    frozendict(
                        {
                            "move_id": move.id,
                            "date_maturity": move.account_area_expense_sheet_id.accounting_date or fields.Date.context_today(
                                move.account_area_expense_sheet_id),
                        }
                    ): {
                        "balance": -sum(term_lines.mapped("balance")),
                        "amount_currency": -sum(term_lines.mapped("amount_currency")),
                        "name": "",
                        "account_id": move.account_area_expense_sheet_id._get_expense_account_destination(),
                    }
                }

    def _reverse_moves(self, default_values_list=None, cancel=False):
        # EXTENDS account
        is_area_sheet_context = self.get_context_account_area_expense()
        if not is_area_sheet_context:
            own_expense_moves = self.filtered(lambda move: move.expense_sheet_id.payment_mode == 'own_account')
            own_expense_moves.write({'expense_sheet_id': False, 'ref': False})
        elif is_area_sheet_context:
            own_expense_moves = self.filtered(lambda move: move.account_area_expense_sheet_id == 'own_account')
            own_expense_moves.write({'ref': False, 'account_area_expense_sheet_id': False})
        # else, when restarting the expense flow we get duplicate issue on vendor.bill
        return super(Account_Move_expense, self)._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    @ondelete(at_uninstall=True)
    def _must_delete_all_expense_entries(self):
        if self.expense_sheet_id and self.expense_sheet_id.account_move_ids - self:  # If not all the payments are to be deleted
            raise UserError(
                _("You cannot delete only some entries linked to an expense report. All entries must be deleted at the same time."))
        elif self.account_area_expense_sheet_id and self.account_area_expense_sheet_id.account_move_ids - self:
            raise UserError(
                _("You cannot delete only some entries linked to an expense report. All entries must be deleted at the same time."))

    def button_cancel(self):
        # EXTENDS account
        # We need to override this method to remove the link with the move, else we cannot reimburse them anymore.
        # And cancelling the move != cancelling the expense
        res = super(Account_Move_expense, self).button_cancel()
        is_area_sheet_context = self.get_context_account_area_expense()
        if not is_area_sheet_context:
            self.write({'expense_sheet_id': False, 'ref': False})
        elif is_area_sheet_context:
            self.write({'ref': False, 'account_area_expense_sheet_id': False})
        return res
