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

    # Pasajes
    ticket_type = fields.Selection([
        ('air', 'Air'),
        ('terrestrial_bus', 'Terrestrial Bus'),
        ('terrestrial_auto', 'Terrestrial Auto'),
    ], string='Ticket Type', tracking=True)

    # Campos aéreos (condicionales)
    flight_date = fields.Datetime(string='Flight Date', tracking=True)
    airline = fields.Char(string='Airline', tracking=True)
    route = fields.Char(string='Route', tracking=True)
    flight = fields.Char(string='Flight', tracking=True)

    # ========== CAMPOS DE LIQUIDACIÓN ==========
    liquidation_status = fields.Selection([
        ('pending', 'Pending settlement'),
        ('liquidated', 'Liquidated'),
    ], string='Liquidation Status',
        compute='_compute_liquidation_status',
        store=True,
        readonly=True,
        default='pending')

    settlement_sheet_id = fields.Many2one(
        'hr.expense.sheet',
        string='Settlement Sheet',
        readonly=True,
        copy=False,
        help='Settlement sheet associated with this advance'
    )

    original_sheet_id = fields.Many2one(
        'hr.expense.sheet',
        string='Original Sheet',
        readonly=True,
        copy=False,
        help='Original advance payment slip that originated this settlement'
    )

    is_liquidation = fields.Boolean(
        string='Is_liquidation',
        default=False,
        copy=False
    )

    total_experiences_verified = fields.Monetary(
        string='Total Verified Expenses',
        compute='_compute_totals_liquidation',
        store=True,
        readonly=True
    )

    refund = fields.Monetary(
        string='Refund',
        compute='_compute_totals_liquidation',
        store=True,
        readonly=True,
        help='Negative: employee owes money to the company\nPositive: company owes money to employee'
    )

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

    # ========== VALIDACIONES ==========
    @api.constrains('settlement_sheet_id')
    def _check_single_liquidation(self):
        for sheet in self:
            if sheet.settlement_sheet_id:
                # Verificar que no exista otra liquidación para esta hoja
                existing = self.search([
                    ('original_sheet_id', '=', sheet.id),
                    ('id', '!=', sheet.settlement_sheet_id.id),
                    ('is_liquidation', '=', True)
                ], limit=1)
                if existing:
                    raise ValidationError(
                        _('A settlement already exists for this expense sheet. Multiple settlements are not allowed.'))

    # ========== ACCIONES ==========
    def action_settle_advance(self):
        """Crear hoja de liquidación para el anticipo"""
        self.ensure_one()

        # Validar estado
        if self.state != 'done':
            raise UserError(_('Advances can only be settled on forms with a status of "Approved"'))

        # Validar que no exista ya una liquidación
        if self.settlement_sheet_id:
            raise UserError(_('This sheet already has an associated settlement.:\n%s') %
                            self.settlement_sheet_id.name)

        # Crear nueva hoja de liquidación
        vals = {
            'name': _('SETTLEMENT %s') % self.name,
            'employee_id': self.employee_id.id,
            'department_id': self.department_id.id,
            'company_id': self.company_id.id,
            'payment_mode': self.payment_mode,
            'is_liquidation': True,
            'original_sheet_id': self.id,
            'destination': self.destination,
            'justification': self.justification,
            'overnight': self.overnight,
            'date_since': self.date_since,
            'date_up': self.date_up,
            'ticket_type': self.ticket_type,
            'flight_date': self.flight_date,
            'airline': self.airline,
            'route': self.route,
            'flight': self.flight,
        }

        new_sheet = self.env['hr.expense.sheet'].create(vals)

        # Vincular hojas
        self.write({'settlement_sheet_id': new_sheet.id})

        # Mensajes en el chatter
        self.message_post(
            body=_('Settlement sheet created: <a href="/web#id=%s&amp;model=hr.expense.sheet&amp;view_type=form">%s</a>') %
                 (new_sheet.id, new_sheet.name)
        )

        new_sheet.message_post(
            body=_('This sheet was created to settle the advance payment:<a href="/web#id=%s&amp;model=hr.expense.sheet&amp;view_type=form">%s</a>') %
                 (self.id, self.name)
        )

        return {
            'name': _('Advance Payment Settlement'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.expense.sheet',
            'res_id': new_sheet.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ========== SOBREESCRITURA DE FLUJO DE PAGO ==========
    def action_sheet_move_create(self):
        """Crear asientos contables con lógica especial para liquidaciones"""
        res = super(HrExpenseSheet, self).action_sheet_move_create()

        for sheet in self.filtered(lambda s: s.is_liquidation and s.refund != 0):
            # Obtener diario de reintegro desde configuración
            reimbursement_journal = self.env.company.expense_reimbursement_journal_id
            if not reimbursement_journal and sheet.refund > 0:
                raise UserError(_('You must set up a "Reimbursement Journal" in Employee Expense Settings'))

            # Crear factura según signo del reintegro
            if sheet.refund < 0:
                # Caso negativo: empleado debe dinero (factura de proveedor)
                self._create_supplier_invoice(sheet)
            else:
                # Caso positivo: empresa debe dinero (factura de cliente)
                self._create_customer_invoice(sheet, reimbursement_journal)

        return res

    def _create_supplier_invoice(self, sheet):
        """Crear factura de proveedor para reintegro negativo"""
        # Lógica nativa de Odoo ya maneja esto, solo registramos en chatter
        sheet.message_post(
            body=_('Negative refund (%s). A supplier invoice was created for the employee.') %
                 sheet.currency_id.format(sheet.refund)
        )

    def _create_customer_invoice(self, sheet, journal):
        """Crear factura de cliente para reintegro positivo"""
        # Crear factura de cliente
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': sheet.employee_id.sudo().address_home_id.id or sheet.employee_id.work_contact_id.id,
            'journal_id': journal.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {
                'name': _('Reimbursement for expenses - %s') % sheet.name,
                'quantity': 1,
                'price_unit': sheet.refund,
                'account_id': journal.default_account_id.id,
            })],
            'ref': _('Refund %s') % sheet.name,
        }

        invoice = self.env['account.move'].create(invoice_vals)

        sheet.message_post(
            body=_(
                'Positive refund (%). Customer invoice created for employee: <a href="/web#id=%s&amp;model=account.move&amp;view_type=form">%s</a>') %
                 (sheet.currency_id.format(sheet.refund), invoice.id, invoice.name)
        )

        return invoice


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    # Campos para liquidación
    real_expense = fields.Monetary(
        string='Real Expense',
        help='Actual amount of the expense verified with supporting documentation'
    )

    proof = fields.Binary(
        string='Proof',
        attachment=True,
        help='Attach receipt, invoice or other proof of purchase'
    )

    proof_filename = fields.Char(string='Filename')

    checked = fields.Boolean(
        string='Checked',
        default=False,
        tracking=True,
        help='Marked by the approver to validate that the receipt corresponds to the expense'
    )

    total_actual_expense_verified = fields.Monetary(
        string='Checked Total',
        compute='_compute_total_actual_expense_verified',
        store=True
    )

    @api.depends('real_expense', 'checked')
    def _compute_total_actual_expense_verified(self):
        for expense in self:
            expense.total_actual_expense_verified = expense.real_expense if expense.checked else 0.0

    @api.constrains('real_expense')
    def _check_real_expense(self):
        for expense in self:
            if expense.sheet_id.is_liquidation and expense.real_expense < 0:
                raise ValidationError(_('"Actual Spending" cannot be negative'))
