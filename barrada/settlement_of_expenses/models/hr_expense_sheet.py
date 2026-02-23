# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup
import pytz


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

    refund = fields.Monetary(
        string='Refund',
        #compute='_compute_diferenc',
        store=True,
        readonly=True,
        help='Negative: employee owes money to the company\nPositive: company owes money to employee'
    )

    verified = fields.Boolean(
        string='Verified', default=False,
        help='Check to view total verified expenses')

    supporting_documents = fields.Binary(
        string='Supporting Documents',
        help='Please Only Allowed Formats (PDF, JPG, JPEG or PNG)',
        tracking=False)

    real_expenses = fields.Monetary(
        string='Real Expenses',
        help='Enter the actual amount spent',
        tracking=True)

    total_verified_expenses = fields.Monetary(
        string='Verified Expenses',
        #compute='_compute_total_expenses_verified',
        store=False,
        help='Amount visible only when verified'
    )

    type_ticket = fields.Selection([
        ('air', _("Air")),
        ('land_bus', _("Land bus")),
        ('land_car', _("Land car (m2o)"))
    ])

    # ========== Si Aereo ==========
    flight_date = fields.Datetime(string='Flight Date', tracking=True)
    airline = fields.Char(string='Airline', tracking=True)
    route = fields.Char(string='Route', tracking=True)
    flight = fields.Char(string='Flight', tracking=True)

    # ========== CAMPOS DE LIQUIDACIÓN ==========
    liquidation_status = fields.Selection([
        ('pending', _('Pending')),
        ('liquidated', _('Liquidated')),
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

    settled_report = fields.Boolean("Settled report", default=False)

    def _compute_totals_liquidation(self):
        for rec in self:
            rec.total_experiences_verified = 0


    # ========== METHODS ==========
    @api.depends('date_since', 'date_up')
    def _compute_number_of_days(self):
        for sheet in self:
            if sheet.date_since and sheet.date_up:
                delta = sheet.date_up - sheet.date_since
                sheet.number_days = delta.days + 1
            else:
                sheet.number_days = 0

    # @api.depends('expense_line_ids.total_actual_expense_verified') #TODO




    @api.onchange('date_since', 'date_up')
    def check_date(self):
        if self.date_since and self.date_up and self.date_up < self.date_since:
            raise UserError(_("Incorrect date range."))

    # @api.onchange('date_since', 'flight_date')
    # def check_flight_date(self):
    #     if self.date_since and self.flight_date and self.flight_date != self.date_since:
    #         raise UserError(_("Incorrect flight date."))


    @api.depends('state')
    def _compute_liquidation_status(self):
        for record in self:
            if record.state != 'done':
                record.liquidation_status = 'pending'
            else:
                record.liquidation_status = 'liquidated'


    def action_settle_advance(self):
        """Crear hoja de liquidación para el anticipo"""

        self.ensure_one()

        # Validar estado
        if self.state != 'done':
            raise UserError(_('Advances can only be settled on forms with a status of "Approved"'))

        # Validar que no exista ya una liquidación
        if self.settled_report:
            raise UserError(_('This sheet already has an associated settlement.:\n%s') %
                            self.settlement_sheet_id.name)

        # Preparar líneas de gasto duplicadas (sin ID para crear nuevas)
        expense_lines = []
        for line in self.expense_line_ids:
            # Usar copy_data() para preservar todos los campos incluyendo personalizados
            line_data = line.copy_data()[0]
            # Eliminar campos que no deben copiarse o que se asignarán automáticamente
            line_data.pop('sheet_id', None)
            line_data.pop('id', None)
            expense_lines.append((0, 0, line_data))

        # Crear nueva hoja de liquidación con líneas y campos personalizados
        vals = {
            'name': _('SETTLEMENT %s') % self.name,
            'employee_id': self.employee_id.id,
            'is_liquidation': True,
            'original_sheet_id': self.id,
            'destination': self.destination,
            'justification': self.justification,
            'real_expenses': self.real_expenses,
            'total_verified_expenses': self.total_verified_expenses,
            'verified': self.verified,
            'supporting_documents': self.supporting_documents,
            'overnight': self.overnight,
            'date_since': self.date_since,
            'date_up': self.date_up,
            'number_days': self.number_days,
            'type_ticket':self.type_ticket,
            'flight_date': self.flight_date,
            'airline': self.airline,
            'route': self.route,
            'flight': self.flight,
            'expense_line_ids': expense_lines,  # Incluir todas las líneas duplicadas
        }

        new_sheet = self.env['hr.expense.sheet'].create([vals])
        self.settled_report = True

        # Obtener fecha actual en la zona horaria del usuario
        user_tz = self.env.user.tz or 'UTC'
        now_utc = fields.Datetime.now()
        # Convertir de UTC a la zona horaria del usuario
        user_timezone = pytz.timezone(user_tz)
        now_user_tz = pytz.utc.localize(now_utc).astimezone(user_timezone)
        settlement_date = now_user_tz.strftime('%d/%m/%Y %H:%M:%S')

        # Mensaje en el reporte original con hipervínculo a la liquidación
        self.message_post(
            body=Markup(_('Report created on %s: <a href="/web#id=%s&amp;model=hr.expense.sheet&amp;view_type=form">%s</a>')) %
                 (settlement_date, new_sheet.id, new_sheet.name),
            subtype_xmlid='mail.mt_note'
        )

        # Mensaje en la nueva liquidación con hipervínculo al reporte original
        new_sheet.message_post(
            body=Markup(_('Settlement created on %s for advance: <a href="/web#id=%s&amp;model=hr.expense.sheet&amp;view_type=form">%s</a>')) %
                 (settlement_date, self.id, self.name),
            subtype_xmlid='mail.mt_note'
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.expense.sheet',
            'res_id': new_sheet.id,
            'view_mode': 'form',
            'target': 'current',
            'name': _('Settlement Sheet'),
        }

    def _prepare_bills_vals(self):
        self.ensure_one()
        move_vals = self._prepare_move_vals()
        if self.employee_id.sudo().bank_account_id:
            move_vals['partner_bank_id'] = self.employee_id.sudo().bank_account_id.id

        move_type = 'in_invoice'
        partner_id = self.employee_id.sudo().work_contact_id.id
        journal_invoice = self.journal_id.id

        if self.is_liquidation and self.total_amount > 0:
            move_type = 'out_invoice'
            partner_id = self.employee_id.sudo().user_id.id
            journal_id_str = self.env['ir.config_parameter'].sudo().get_param('hr_expense.reimbursement_journal_id')
            journal_id = int(journal_id_str) if journal_id_str else False
            if journal_id:
                journal_invoice = journal_id

        return {
            **move_vals,
            'journal_id': journal_invoice,
            'ref': self.name,
            'move_type': move_type,
            'partner_id': partner_id,
            'commercial_partner_id': self.employee_id.user_partner_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [Command.create(expense._prepare_move_lines_vals()) for expense in self.expense_line_ids],
            'attachment_ids': [
                Command.create(attachment.copy_data({'res_model': 'account.move', 'res_id': False, 'raw': attachment.raw})[0])
                for attachment in self.expense_line_ids.attachment_ids
            ],
        }



  