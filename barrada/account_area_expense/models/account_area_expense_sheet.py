from odoo import api, fields, models, _, Command
from odoo.exceptions import ValidationError, AccessError, UserError
from odoo.tools.misc import clean_context
from odoo.addons.hr_expense.models.hr_expense_sheet import HrExpenseSheet


class AccountAreaExpenseSheet(models.Model):
    _name = "account.area.expense.sheet"
    _inherit = 'hr.expense.sheet'
    _description = "Account Area Expense Report"
    _order = "accounting_date desc, id desc"
    _check_company_auto = True

    area_manager_id = fields.Many2one('res.users', 'Area Manager')

    provider_id = fields.Many2one('res.partner', "Provider")

    approved_id = fields.Many2one('res.users', "Approved by")

    account_expense_line_ids = fields.One2many(
        comodel_name='account.area.expense', inverse_name='account_sheet_id',
        string="Expense Lines",
        copy=False,
    )

    area_payment_mode = fields.Selection(
        related='account_expense_line_ids.payment_mode',
        string="Paid By",
        tracking=True,
        readonly=True,
    )

    area_account_move_ids = fields.One2many(
        string="Journal Entries",
        comodel_name='account.move', inverse_name='account_area_expense_sheet_id', readonly=True,
    )

    employee_id = fields.Many2one(required=False)

    state = fields.Selection(
        selection=[
            ('draft', 'Por enviar'),
            ('submit', 'Enviado'),
            ('approve', 'Aprobado'),
            ('post', 'Registrado'),
            ('done', 'Listo'),
            ('cancel', 'Cancelado')
        ],
        string="Status",
        compute='_compute_state', store=True, readonly=True,
        index=True,
        required=True,
        default='draft',
        tracking=True,
        copy=False,
    )

    def activity_update(self):
        reports_requiring_feedback = self.env['account.area.expense.sheet']
        reports_activity_unlink = self.env['account.area.expense.sheet']
        for expense_report in self:
            if expense_report.state == 'submit':
                expense_report.activity_schedule(
                    'hr_expense.mail_act_expense_approval',
                    user_id=expense_report.sudo()._get_responsible_for_approval().id or self.env.user.id)
            elif expense_report.state == 'approve':
                reports_requiring_feedback |= expense_report
            elif expense_report.state in {'draft', 'cancel'}:
                reports_activity_unlink |= expense_report
        if reports_requiring_feedback:
            reports_requiring_feedback.activity_feedback(['account.area.expense.mail_act_expense_approval'])
        if reports_activity_unlink:
            reports_activity_unlink.activity_unlink(['account.area.expense.mail_act_expense_approval'])

    def write(self, values):
        res = super(HrExpenseSheet, self).write(values)

        self.check_expense_lines()

        user_is_accountant = self.env.user.has_group('account.group_account_user')
        edit_lines = 'expense_line_ids' in values
        edit_states = 'state' in values or 'approval_state' in values
        # Forbids (un)linking expenses from an approved sheet if you're not an accountant
        if edit_lines and not user_is_accountant and set(self.mapped('state')) - {'draft', 'submit'}:
            raise AccessError(
                _("You do not have the rights to add or remove any expenses on an approved or paid expense report."))

        # Ensures there is no empty expense report in a state different from draft or cancel
        if edit_states or edit_lines:
            for sheet in self.filtered(lambda sheet: not sheet.account_expense_line_ids):
                if sheet.state in {'submit', 'approve', 'post',
                                   'done'}:  # Empty expense report in a state different from draft or cancel
                    if edit_lines and not sheet.account_expense_line_ids:  # If you try to remove all expenses from the sheet
                        raise UserError(
                            _("You cannot remove all expenses from a submitted, approved or paid expense report."))
                    else:  # If you try to submit, approve, post or pay an empty sheet
                        raise UserError(
                            _("This expense report is empty. You cannot submit or approve an empty expense report."))
        return res

    @api.model_create_multi
    def create(self, vals):
        res = super(AccountAreaExpenseSheet, self).create(vals)

        for sheet in res:
            sheet.check_expense_lines()
            if sheet.account_expense_line_ids:
                sheet.provider_id = sheet.account_expense_line_ids[0].vendor_id.id
                sheet.area_manager_id = sheet.account_expense_line_ids[0].area_manager_id.id

        return res

    def check_expense_lines(self):
        self.ensure_one()
        manager_area_select = False
        company_select = False
        if self.account_expense_line_ids:
            for line in self.account_expense_line_ids:
                if line.payment_account_mode == 'manager_area':
                    manager_area_select = True
                else:
                    company_select = True

            if manager_area_select == company_select:
                raise UserError(_("You cannot select expense lines with combined `Payment Method`."))

    def _do_submit(self):
        self.write({
            'approval_state': 'submit',
            'payment_mode': 'own_account',
            # 'account_sheet_id.payment_method_line_id'
        })
        self.sudo().activity_update()

    @api.depends('employee_journal_id', 'payment_method_line_id')
    def _compute_journal_id(self):
        for sheet in self:
            if sheet.area_payment_mode == 'company_account':
                sheet.journal_id = sheet.payment_method_line_id.journal_id
            else:
                sheet.journal_id = sheet.employee_journal_id

    def action_approve_expense_sheets(self):
        self._check_can_approve()
        self._validate_analytic_distribution()
        self._check_can_approve_permission()
        duplicates = self.account_expense_line_ids.duplicate_expense_ids.filtered(lambda exp: exp.state in {'approved', 'done'})
        if duplicates:
            action = self.env["ir.actions.act_window"]._for_xml_id('hr_expense.hr_expense_approve_duplicate_action')
            action['context'] = {'default_sheet_ids': self.ids, 'default_expense_ids': duplicates.ids}
            return action
        self._do_approve()

    def _check_can_approve_permission(self):
        if not self.env.user.has_group('account_area_expense.group_accountant'):
            raise UserError(_("Only users with rol Accountant, can Approve this expense"))

    def _check_can_create_move(self):
        if any(not sheet.account_expense_line_ids for sheet in self):
            raise UserError(_("You cannot create accounting entries for an expense report without expenses."))

    def _do_create_moves(self):
        """
        Creation of the account moves for the expenses report. Sudo-ed as they are created in draft and the manager may not have
        the accounting rights (and there is no reason to give them those rights).
        There are two main flows at play:
            - Expense paid by the company -> Create an account payment (we only "log" the already paid expense so it can be reconciled)
            - Expense paid by he employee's own account -> As it should be reimbursed to them, it creates a vendor bill.
        """
        self = self.with_context(clean_context(self.env.context))  # remove default_*
        own_account_sheets = self.filtered(lambda sheet: sheet.area_payment_mode == 'own_account')
        company_account_sheets = self - own_account_sheets

        is_payment_mode_company = False
        for sheet in own_account_sheets:
            sheet.accounting_date = sheet.accounting_date or sheet._calculate_default_accounting_date()
            for expense in sheet.account_expense_line_ids:
                if expense.payment_account_mode == 'company':
                    is_payment_mode_company = True
                    break

        values = [sheet._prepare_bills_vals() for sheet in own_account_sheets]

        for val in values:
            if is_payment_mode_company:
                val.update({
                    'partner_id': self.provider_id.id
                })
            else:
                val.update({
                    'partner_id': self.create_uid.partner_id.id
                })

        moves_sudo = self.env['account.move'].sudo().create(values)

        for move_sudo in moves_sudo:
            move_sudo._message_set_main_attachment_id(move_sudo.attachment_ids, force=True, filter_xml=False)
        if company_account_sheets:
            move_vals_list, payment_vals_list = zip(*[
                expense._prepare_payments_vals()
                for expense in company_account_sheets.account_expense_line_ids
            ])

            if move_vals_list:
                for move in move_vals_list:
                    if 'expense_sheet_id' in move:
                        expense_sheet_id = move.pop('expense_sheet_id')
                    move.update({
                        'account_area_expense_sheet_id': self.id
                    })

                    for line in move.get('line_ids', []):
                        if line[2].get('expense_id', False):
                            expense_id = line[2].pop('expense_id')
                            line[2].update({'area_expense_id': expense_id})

            payment_moves_sudo = self.env['account.move'].sudo().create(move_vals_list)
            for payment_vals, move in zip(payment_vals_list, payment_moves_sudo):
                payment_vals['move_id'] = move.id

            payments_sudo = self.env['account.payment'].sudo().create(payment_vals_list)
            for payment_sudo, move_sudo in zip(payments_sudo, payment_moves_sudo):
                move_sudo.update({
                    'origin_payment_id': payment_sudo.id,
                    # We need to put the journal_id because editing origin_payment_id triggers a re-computation chain
                    # that voids the company_currency_id of the lines
                    'journal_id': move_sudo.journal_id.id,
                })

            moves_sudo |= payment_moves_sudo

        # returning the move with the super user flag set back as it was at the origin of the call
        return moves_sudo.sudo(self.env.su)

    def _calculate_default_accounting_date(self):
        """
        Calculate the default accounting date for the expenses paid by employees
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        start_month = fields.Date.start_of(today, "month")
        end_month = fields.Date.end_of(today, "month")
        most_recent_expense = max(self.account_expense_line_ids.filtered(lambda exp: exp.date).mapped('date'), default=today)

        if most_recent_expense > end_month:
            return most_recent_expense

        if most_recent_expense >= start_month:
            return today

        lock_date = self.company_id._get_user_fiscal_lock_date(self.journal_id)

        return min(
            max(
                fields.Date.end_of(most_recent_expense, "month"),
                fields.Date.end_of(fields.Date.add(lock_date, months=1), "month")
            ),
            today
        )

    def _prepare_bills_vals(self):
        self.ensure_one()
        move_vals = self._prepare_move_vals()
        if self.employee_id.sudo().bank_account_id:
            move_vals['partner_bank_id'] = self.employee_id.sudo().bank_account_id.id
        return {
            **move_vals,
            'journal_id': self.journal_id.id,
            'ref': self.name,
            'move_type': 'in_invoice',
            'partner_id': self.employee_id.sudo().work_contact_id.id,
            'commercial_partner_id': self.employee_id.user_partner_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [Command.create(expense._prepare_move_lines_vals()) for expense in self.account_expense_line_ids],
            'attachment_ids': [
                Command.create(attachment.copy_data({'res_model': 'account.move', 'res_id': False, 'raw': attachment.raw})[0])
                for attachment in self.account_expense_line_ids.message_main_attachment_id
            ],
        }

    def _prepare_move_vals(self):
        self.ensure_one()
        to_return = {
            # force the name to the default value, to avoid an eventual 'default_name' in the context
            # to set it to '' which cause no number to be given to the account.move when posted.
            'name': '/',
            'account_area_expense_sheet_id': self.id,
        }

        today = fields.Date.context_today(self)
        most_recent_expense = max(self.account_expense_line_ids.filtered(lambda exp: exp.date).mapped('date'), default=today)

        if self.payment_mode == 'company_account':
            to_return['date'] = most_recent_expense
        else:
            to_return['invoice_date'] = self.accounting_date

        return to_return

    @api.depends('area_account_move_ids.payment_state', 'area_account_move_ids.amount_residual', 'account_move_ids.payment_state', 'account_move_ids.amount_residual')
    def _compute_from_account_move_ids(self):
        for sheet in self:
            if sheet.payment_mode == 'company_account':
                if sheet.area_account_move_ids.filtered(lambda move: move.state != 'draft'):
                    # when the sheet is paid by the company, the state/amount of the related account_move_ids are not relevant
                    # unless all moves have been reversed
                    sheet.amount_residual = 0.
                    if (sheet.account_move_ids - sheet.account_move_ids.filtered('reversal_move_ids')) or (sheet.area_account_move_ids - sheet.area_account_move_ids.filtered('reversal_move_ids')):
                        sheet.payment_state = 'paid'
                    else:
                        sheet.payment_state = 'reversed'
                else:
                    sheet.amount_residual = sum(sheet.area_account_move_ids.mapped('amount_residual')) if sheet.area_account_move_ids else sum(sheet.account_move_ids.mapped('amount_residual'))
                    payment_states = set(sheet.area_account_move_ids.mapped('payment_state')) if sheet.area_account_move_ids else set(sheet.account_move_ids.mapped('payment_state'))
                    if len(payment_states) <= 1:  # If only 1 move or only one state
                        sheet.payment_state = payment_states.pop() if payment_states else 'not_paid'
                    elif 'partial' in payment_states or 'paid' in payment_states:  # else if any are (partially) paid
                        sheet.payment_state = 'partial'
                    else:
                        sheet.payment_state = 'not_paid'
            else:
                # Only one move is created when the expenses are paid by the employee
                if (sheet.account_move_ids.filtered(lambda move: move.state == 'posted')) or (sheet.area_account_move_ids.filtered(lambda move: move.state == 'posted')):
                    sheet.amount_residual = sum(sheet.area_account_move_ids.mapped('amount_residual')) if sheet.area_account_move_ids else sum(sheet.account_move_ids.mapped('amount_residual'))
                    sheet.payment_state = sheet.area_account_move_ids[:1].payment_state if sheet.area_account_move_ids else sheet.account_move_ids[:1].payment_state
                else:
                    sheet.amount_residual = 0.0
                    sheet.payment_state = 'not_paid'

    @api.depends('area_account_move_ids', 'account_move_ids', 'payment_state', 'approval_state')
    def _compute_state(self):
        for sheet in self:
            move_ids = sheet.account_move_ids or sheet.area_account_move_ids
            if not sheet.approval_state:
                sheet.state = 'draft'
            elif sheet.approval_state == 'cancel':
                sheet.state = 'cancel'
            elif move_ids:
                if sheet.payment_state != 'not_paid':
                    sheet.state = 'done'
                elif all(move_ids.mapped(lambda move: move.state == 'draft')):
                    sheet.state = 'approve'
                else:
                    sheet.state = 'post'
            else:
                sheet.state = sheet.approval_state  # Submit & approved without a move case

    @api.depends('account_move_ids', 'area_account_move_ids')
    def _compute_nb_account_move(self):
        for sheet in self:
            sheet.nb_account_move = len(sheet.account_move_ids) if sheet.account_move_ids else len(sheet.area_account_move_ids)

    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' not in init_values:
            return super()._track_subtype(init_values)

        match self.state:
            case 'draft':
                return self.env.ref('hr_expense.mt_expense_reset')
            case 'cancel':
                return self.env.ref('hr_expense.mt_expense_refused')
            case 'done':
                return self.env.ref('hr_expense.mt_expense_paid')
            case 'approve':
                if init_values['state'] in {'post', 'done'}:  # Reverting state
                    subtype = 'hr_expense.mt_expense_entry_draft' if self.account_move_ids or self.area_account_move_ids else 'hr_expense.mt_expense_entry_delete'
                    return self.env.ref(subtype)
                return self.env.ref('hr_expense.mt_expense_approved')
            case _:
                return super()._track_subtype(init_values)

    def action_sheet_move_post(self):
        is_area_sheet_context = self.env.context.get('account_area_expense_sheet', False)
        if not is_area_sheet_context:
            # When a move has been deleted
            self.filtered(lambda sheet: not sheet.account_move_ids)._do_create_moves()
        elif is_area_sheet_context:
            self.filtered(lambda sheet: not sheet.area_account_move_ids)._do_create_moves()

        company_sheets = self.filtered(lambda sheet: sheet.payment_mode == 'company_account')
        employee_sheets = self - company_sheets
        if not is_area_sheet_context:
            # Post the employee-paid expenses moves
            employee_sheets.account_move_ids.action_post()

            # Post the company-paid expense through the payment instead, to post both at the same time
            company_sheets.account_move_ids.origin_payment_id.action_post()
        elif is_area_sheet_context:
            # Post the employee-paid expenses moves
            employee_sheets.area_account_move_ids.action_post()

            # Post the company-paid expense through the payment instead, to post both at the same time
            company_sheets.area_account_move_ids.origin_payment_id.action_post()

    def action_reset_expense_sheets(self):
        self.filtered(lambda sheet: sheet.state not in {'draft', 'submit'})._check_can_reset_approval()
        self.sudo()._do_reverse_moves()
        self._do_reset_approval()
        if self.sudo().account_move_ids:
            self.sudo().account_move_ids = [Command.clear()]
        elif self.sudo().area_account_move_ids:
            self.sudo().area_account_move_ids = [Command.clear()]

    def action_register_payment(self):
        ''' Open the account.payment.register wizard to pay the selected journal entries.
        There can be more than one bank_account_id in the expense sheet when registering payment for multiple expenses.
        The default_partner_bank_id is set only if there is one available, if more than one the field is left empty.
        :return: An action opening the account.payment.register wizard.
        '''
        is_area_sheet_context = self.env.context.get('account_area_expense_sheet', False)
        if not is_area_sheet_context:
            return self.account_move_ids.with_context(default_partner_bank_id=(
                self.account_move_ids.partner_bank_id.id if len(self.account_move_ids.partner_bank_id.ids) <= 1 else None
            )).action_register_payment()
        elif is_area_sheet_context:
            return self.area_account_move_ids.with_context(default_partner_bank_id=(
                self.area_account_move_ids.partner_bank_id.id if len(
                    self.area_account_move_ids.partner_bank_id.ids) <= 1 else None
            )).action_register_payment()

    def _check_can_pay_permission(self):
        if not self.env.user.has_group('account_area_expense.group_treasury'):
            raise UserError(_("Only users with rol Accountant, can Approve this expense"))

    def action_open_account_moves(self):
        self.ensure_one()
        is_area_sheet_context = self.env.context.get('account_area_expense_sheet', False)
        if self.payment_mode == 'own_account':
            res_model = 'account.move'
            if not is_area_sheet_context:
                record_ids = self.account_move_ids
            elif is_area_sheet_context:
                record_ids = self.area_account_move_ids
        else:
            res_model = 'account.payment'
            if not is_area_sheet_context:
                record_ids = self.account_move_ids.origin_payment_id
            elif is_area_sheet_context:
                record_ids = self.area_account_move_ids.origin_payment_id

        action = {'type': 'ir.actions.act_window', 'res_model': res_model}
        if len(self.account_move_ids) == 1 or len(self.area_account_move_ids) == 1:
            action.update({
                'name': record_ids.name,
                'view_mode': 'form',
                'res_id': record_ids.id,
                'views': [(False, 'form')],
            })
        else:
            action.update({
                'name': _("Journal entries"),
                'view_mode': 'list',
                'domain': [('id', 'in', record_ids.ids)],
                'views': [(False, 'list'), (False, 'form')],
            })
        return action

    def _do_refuse(self, reason):
        # Sudoed as approvers may not be accountants
        if self.sudo().account_move_ids:
            draft_moves_sudo = self.sudo().account_move_ids.filtered(lambda move: move.state == 'draft')
        else:
            draft_moves_sudo = self.sudo().area_account_move_ids.filtered(lambda move: move.state == 'draft')

        if (self.sudo().account_move_ids - draft_moves_sudo) or (self.sudo().area_account_move_ids - draft_moves_sudo):
            raise UserError(_("You cannot cancel an expense sheet linked to a posted journal entry"))

        if draft_moves_sudo:
            draft_moves_sudo.unlink()  # Else we have lingering moves

        self.approval_state = 'cancel'
        subtype_id = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_comment')
        for sheet in self:
            sheet.message_post_with_source(
                'hr_expense.hr_expense_template_refuse_reason',
                subtype_id=subtype_id,
                render_values={'reason': reason, 'name': sheet.name},
            )
        self.activity_update()

    def _do_reverse_moves(self):
        self = self.with_context(clean_context(self.env.context))
        if self.account_move_ids:
            moves = self.account_move_ids
        else:
            moves = self.area_account_move_ids
        draft_moves = moves.filtered(lambda m: m.state == 'draft')
        non_draft_moves = moves - draft_moves
        non_draft_moves._reverse_moves(
            default_values_list=[{'invoice_date': fields.Date.context_today(move), 'ref': False} for move in non_draft_moves],
            cancel=True
        )
        draft_moves.unlink()
