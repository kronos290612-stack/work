# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    expense_claim_use_same_journal = fields.Boolean(
        string='Use the same journal for invoices per claim',
        help='By enabling this option, invoices generated from expense claims will '
             'use the same accounting journal configured in "Expense Journal".',
        default=False
    )