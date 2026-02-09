{
    'name': 'HR Expense Travel Extension',
    'version': '1.0',
    'category': 'Human Resources/Expenses',
    'summary': 'Complete management of employee advances, settlements, and expense reimbursements',
    'description': """
    Advanced Management of Advances and Expense Settlements
    ======================================================

    Main Features:
    • "Expense and Travel Request" tab with complete sections for destination, justification, expenses, and tickets
    • "Settle Advance" button to create settlement sheets linked to the original advance
    • "Settlement Status" field (Settled/Pending)
    • Automatic entry in the chat with hyperlinks between related sheets
    • Additional fields in expense lines for settlement:

     - Actual Expense (monetary)

     - Supporting Document (attached)

     - Verified (Boolean for validation)

     • Automatic calculation of:

    - Total verified expenses

    - Reimbursement (difference between advance and verified)
    • Payment flow Smart:

     - Negative Reimbursement → Supplier Invoice to Employee

     - Positive Reimbursement → Customer Invoice to Employee (using configurable reimbursement journal)
     • Settings: Reimbursement Journal for Returns
     • Visual red highlighting of settlement sheets in list views
     • Validation to prevent multiple advance settlements
     """,
    'author': 'PAKCORE',
    'website': 'https://pakcore.net/',
    'depends': ['account_area_expense'],
    'data': [
        'views/hr_expense_views.xml',
            ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
