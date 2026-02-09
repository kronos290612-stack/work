# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    expense_reimbursement_journal_id = fields.Many2one(
        'account.journal',
        string='Reimbursement log',
        related='company_id.expense_reimbursement_journal_id',
        readonly=False,
        domain="[('type', 'in', ['sale', 'general']), ('company_id', '=', company_id)]",
        help='Default accounting journal for expense reimbursement (when the reimbursement is positive)'
    )