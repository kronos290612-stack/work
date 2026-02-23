from odoo import api, fields, Command, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_split, float_repr, float_round, is_html_empty


class AccountAreaExpense(models.Model):
    _name = "account.area.expense"
    _inherit = 'hr.expense'
    _description = "Account Area Expense"
    _order = "date desc, id desc"
    _check_company_auto = True

    # Account fields
    payment_account_mode = fields.Selection(
        selection=[
            ('manager_area', _("Manager Area")),
            ('company', _("Company"))
        ],
        string="Payment mode",
        default='manager_area',
        required=True,
        tracking=True
    )

    area_manager_id = fields.Many2one('res.users', 'Area Manager')

    tax_ids = fields.Many2many(
        comodel_name='account.tax',
        relation='account_area_expense_tax_rel',
        column1='expense_id',
        column2='tax_id',
        string='Taxes'
    )

    account_sheet_id = fields.Many2one('account.area.expense.sheet', 'Sheet Report')

    sale_order_id = fields.Many2one('sale.order', compute='_compute_sale_order_id', store=True, index='btree_not_null',
                                    string='Customer to Reinvoice', readonly=False, tracking=True,
                                    help="If the category has an expense policy, it will be reinvoiced on this sales order")

    can_be_reinvoiced = fields.Boolean("Can be reinvoiced", compute='_compute_can_be_reinvoiced')

    @api.model
    def _default_employee_id_account_area(self):
        employee = self.env.user.employee_id
        return employee

    employee_id = fields.Many2one(required=False, default=_default_employee_id_account_area,)

    state = fields.Selection(
        selection=[
            ('draft', 'Por reportar'),
            ('reported', 'To Submit'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('done', 'Done'),
            ('refused', 'Refused')
        ],
        string="Status",
        compute='_compute_state', store=True, readonly=True,
        index=True,
        copy=False,
        default='draft',
    )

    def action_submit_expenses(self):
        self.payment_mode = 'own_account'
        sheets = self._create_sheets_from_expense()
        return {
            'name': _('New Expense Reports'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.area.expense.sheet',
            'context': self.env.context,
            'views': [[False, "list"], [False, "form"]] if len(sheets) > 1 else [[False, "form"]],
            'domain': [('id', 'in', sheets.ids)],
            'res_id': sheets.id if len(sheets) == 1 else False,
        }

    def _create_sheets_from_expense(self):
        if self.payment_account_mode == 'manager_area':
            if self.filtered(lambda expense: not expense.is_editable):
                raise UserError(_('You are not authorized to edit this expense.'))
            sheets = self.env['account.area.expense.sheet'].create(self._get_default_expense_sheet_values())
            return sheets

        sheets = self.env['account.area.expense.sheet'].create(self._get_default_expense_sheet_values())
        return sheets

    def _get_default_expense_sheet_values(self):
        # If there is an expense with total_amount == 0, it means that expense has not been processed by OCR yet
        expenses_with_amount = self.filtered(lambda expense: not (
            expense.currency_id.is_zero(expense.total_amount_currency)
            or expense.company_currency_id.is_zero(expense.total_amount)
            or (expense.product_id and not float_round(expense.quantity, precision_rounding=expense.product_uom_id.rounding))
        ))

        if any(expense.state != 'draft' or expense.sheet_id for expense in expenses_with_amount):
            raise UserError(_("You cannot report twice the same line!"))
        if not expenses_with_amount:
            raise UserError(_("You cannot report the expenses without amount!"))
        if any(not expense.product_id for expense in expenses_with_amount):
            raise UserError(_("You can not create report without category."))
        if len(self.company_id) != 1:
            raise UserError(_("You cannot report expenses for different companies in the same report."))

        # Check if two reports should be created
        own_expenses = expenses_with_amount.filtered(lambda x: x.payment_mode == 'own_account')
        company_expenses = expenses_with_amount - own_expenses
        create_two_reports = own_expenses and company_expenses

        sheets = (own_expenses, company_expenses) if create_two_reports else (expenses_with_amount,)
        values = []

        # We use a fallback name only when several expense sheets are created,
        # else we use the form view required name to force the user to set a name
        for todo in sheets:
            paid_by = 'company' if todo[0].payment_mode == 'company_account' else 'employee'
            sheet_name = self.env['account.area.expense.sheet']._get_default_sheet_name(todo)
            if not sheet_name and len(sheets) > 1:
                sheet_name = _("New Expense Report, paid by %(paid_by)s", paid_by=paid_by)
            values.append({
                'company_id': self.company_id.id,
                'employee_id': self[0].employee_id.id,
                'name': sheet_name,
                'account_expense_line_ids': [Command.set(todo.ids)],
                'state': 'draft',
            })
        return values

    def _compute_nb_attachment(self):
        attachment_data = self.env['ir.attachment']._read_group(
            [('res_model', '=', 'account.area.expense'), ('res_id', 'in', self.ids)],
            ['res_id'],
            ['__count'],
        )
        attachment = dict(attachment_data)
        for expense in self:
            expense.nb_attachment = attachment.get(expense._origin.id, 0)

    def action_view_sheet(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'views': [[False, "form"]],
            'res_model': 'account.area.expense.sheet',
            'target': 'current',
            'res_id': self.account_sheet_id.id
        }

    def attach_document(self, **kwargs):
        """When an attachment is uploaded as a receipt, set it as the main attachment."""
        if not self.has_access('write') or (self.account_sheet_id and not self.account_sheet_id.has_access('write')):
            raise UserError(_("You don't have the rights to attach a document to a submitted expense. Please reset the expense report to draft first."))
        self._message_set_main_attachment_id(self.env["ir.attachment"].browse(kwargs['attachment_ids'][-1:]), force=True)

    @api.depends('account_sheet_id', 'account_sheet_id.account_move_ids', 'account_sheet_id.state')
    def _compute_state(self):
        for expense in self:
            if not expense.account_sheet_id:
                expense.state = 'draft'
            elif expense.account_sheet_id.state == 'draft':
                expense.state = 'reported'
            elif expense.account_sheet_id.state == 'cancel':
                expense.state = 'refused'
            elif expense.account_sheet_id.state in {'approve', 'post'}:
                expense.state = 'approved'
            elif not expense.account_sheet_id.account_move_ids:
                expense.state = 'submitted'
            else:
                expense.state = 'done'

    def _prepare_payments_vals(self):
        self.ensure_one()

        journal = self.account_sheet_id.journal_id
        payment_method_line = self.account_sheet_id.payment_method_line_id
        if not payment_method_line:
            raise UserError(_("You need to add a manual payment method on the journal (%s)", journal.name))

        AccountTax = self.env['account.tax']
        rate = abs(self.total_amount_currency / self.total_amount) if self.total_amount else 0.0
        base_line = self._prepare_base_line_for_taxes_computation(
            price_unit=self.total_amount_currency,
            quantity=1.0,
            account_id=self._get_base_account(),
            rate=rate,
        )
        base_lines = [base_line]
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        AccountTax._add_accounting_data_in_base_lines_tax_details(base_lines, self.company_id, include_caba_tags=self.payment_mode == 'company_account')
        tax_results = AccountTax._prepare_tax_lines(base_lines, self.company_id)

        # Base line.
        move_lines = []
        for base_line, to_update in tax_results['base_lines_to_update']:
            base_move_line = {
                'name': self._get_move_line_name(),
                'account_id': base_line['account_id'].id,
                'product_id': base_line['product_id'].id,
                'analytic_distribution': base_line['analytic_distribution'],
                'expense_id': self.id,
                'tax_ids': [Command.set(base_line['tax_ids'].ids)],
                'tax_tag_ids': to_update['tax_tag_ids'],
                'amount_currency': to_update['amount_currency'],
                'balance': to_update['balance'],
                'currency_id': base_line['currency_id'].id,
                'partner_id': self.vendor_id.id,
            }
            move_lines.append(base_move_line)

        # Tax lines.
        total_tax_line_balance = 0.0
        for tax_line in tax_results['tax_lines_to_add']:
            total_tax_line_balance += tax_line['balance']
            move_lines.append(tax_line)
        base_move_line['balance'] = self.total_amount - total_tax_line_balance

        # Outstanding payment line.
        move_lines.append({
            'name': self._get_move_line_name(),
            'account_id': self.account_sheet_id._get_expense_account_destination(),
            'balance': -self.total_amount,
            'amount_currency': self.currency_id.round(-self.total_amount_currency),
            'currency_id': self.currency_id.id,
            'partner_id': self.vendor_id.id,
        })
        payment_vals = {
            'date': self.date,
            'memo': self.name,
            'journal_id': journal.id,
            'amount': self.total_amount_currency,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.vendor_id.id,
            'currency_id': self.currency_id.id,
            'payment_method_line_id': payment_method_line.id,
            'company_id': self.company_id.id,
        }
        move_vals = {
            **self.account_sheet_id._prepare_move_vals(),
            'ref': self.name,
            'date': self.date,
            'journal_id': journal.id,
            'partner_id': self.vendor_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [Command.create(line) for line in move_lines],
            'attachment_ids': [
                Command.create(attachment.copy_data({'res_model': 'account.move', 'res_id': False, 'raw': attachment.raw})[0])
                for attachment in self.message_main_attachment_id]
        }
        return move_vals, payment_vals

    def _prepare_move_lines_vals(self):
        self.ensure_one()
        account = self._get_base_account()

        return {
            'name': self._get_move_line_name(),
            'account_id': account.id,
            'quantity': self.quantity or 1,
            'price_unit': self.price_unit,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_uom_id.id,
            'analytic_distribution': self.analytic_distribution,
            'area_expense_id': self.id,
            'partner_id': False if self.payment_mode == 'company_account' else self.employee_id.sudo().work_contact_id.id,
            'tax_ids': [Command.set(self.tax_ids.ids)],
        }