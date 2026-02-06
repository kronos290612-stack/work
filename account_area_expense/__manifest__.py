{
    'name': 'HR Expense Travel Extension',
    'version': '1.0',
    'category': 'Human Resources/Expenses',
    'summary': 'Extensión para gastos de viaje con información adicional',
    'description': """
        Módulo que extiende hr.expense para agregar información de viajes
        - Destino
        - Justificación
        - Expensas
        - Pasajes
    """,
    'author': 'Kronos',
    'website': '',
    'depends': ['hr_expense'],
    'data': [
        'views/hr_expense_views.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}