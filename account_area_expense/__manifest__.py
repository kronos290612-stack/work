{
    'name': 'Gastos por Áreas',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Expenses',
    'sequence': 35,
    'summary': 'Manage area expenses',
    'description': """
Gestión de solicitudes de gastos por áreas que deberán ser aprobados por usuarios designados como aprobadores.
Al ser aprobadas estas solicitudes los gastos pueden reintegrarse al área o crear las respectivas facturas de proveedores.
""",
    'website': 'https://pakcore.net/',
    'author': 'PAKCORE',
    'depends': [
        'hr_expense',
        'account',
        'hr',
    ],
    'data': [
        'security/account_area_expense_security.xml',
        'security/ir.model.access.csv',
        'views/account_area_expense_views.xml',
        'views/account_area_expense_sheet_views.xml',
        'views/menuitems.xml',
        # 'views/account_menu.xml',
    ],
    'demo': [
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
}