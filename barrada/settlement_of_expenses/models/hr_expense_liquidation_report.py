from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ExpenseLiquidationReport(models.Model):
    _name = 'hr.expense.liquidation.report'
    _description = 'Liquidation Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    expense_sheet_id = fields.Many2one(
        'hr.expense.sheet',
        string='Expense Report',
        required=True,
        tracking = True
    )

    @api.constrains('expense_sheet_id')
    def _check_unique_expense_sheet(self):
        for record in self:
            if record.expense_sheet_id:
                existing = self.search([
                    ('expense_sheet_id', '=', record.expense_sheet_id.id),
                    ('id', '!=', record.id)
                ], limit=1)
                if existing:
                    raise ValidationError(
                        'A settlement report already exists for this expense report.'
                        'Multiple settlements are not allowed for the same report.'
                    )


