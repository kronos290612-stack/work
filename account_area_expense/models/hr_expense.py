from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    # Sección 1: Información del Viaje
    travel_destination = fields.Char(
        string='Destino',
        help='Destino del viaje o lugar donde se realizaron los gastos'
    )

    trip_justification = fields.Text(
        string='Justificación',
        help='Justificación del viaje o gasto realizado'
    )

    # Sección 2: Detalles de Gastos
    expense_amount = fields.Monetary(
        string='Expensas',
        help='Monto total de expensas (alojamiento, alimentación, etc.)',
        currency_field='currency_id'
    )

    ticket_amount = fields.Monetary(
        string='Pasajes',
        help='Monto total de pasajes (transporte)',
        currency_field='currency_id'
    )

    transport_type = fields.Selection([
        ('avion', 'Avión'),
        ('tren', 'Tren'),
        ('auto', 'Auto/Carro'),
        ('bus', 'Ómnibus/Bus'),
        ('otros', 'Otros')
    ], string='Tipo de Transporte', help='Tipo de transporte utilizado')

    travel_date = fields.Date(
        string='Fecha del Viaje',
        help='Fecha en que se realizó el viaje'
    )

    duration_days = fields.Integer(
        string='Duración (días)',
        help='Duración del viaje en días'
    )

    @api.constrains('monto_expensas', 'monto_pasajes')
    def _check_montos_positivos(self):
        for expense in self:
            if expense.monto_expensas < 0 or expense.monto_pasajes < 0:
                raise ValidationError(_('Los montos de expensas y pasajes deben ser positivos.'))

    @api.onchange('monto_expensas', 'monto_pasajes')
    def _onchange_montos_viaje(self):
        """Opcional: Actualizar automáticamente el monto total del gasto"""
        for expense in self:
            if expense.monto_expensas or expense.monto_pasajes:
                expense.total_amount = (expense.monto_expensas or 0) + (expense.monto_pasajes or 0)