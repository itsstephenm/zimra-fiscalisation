{
    'name': 'Zimbabwe - ZIMRA Fiscalisation',
    'version': '1.0',
    'category': 'Accounting/Localizations',
    'summary': 'Integrates Odoo 19 with ZIMRA FDMS for automatic fiscal receipt submission',
    'description': """
        Integrates Odoo 19 Community with the ZIMRA Fiscalisation Data Management System (FDMS).

        Features:
        - Automatic submission of Customer Invoices to ZIMRA on confirmation
        - Automatic submission of POS Orders to ZIMRA on payment (till/receipt flow)
        - Cryptographic receipt signing using RSA private key + SHA-256
        - Receipt chaining via previous hash storage
        - ZIMRA status tracking on every invoice and POS order
        - ZIMRA tax code mapping on Odoo taxes
        - Full ZIMRA Fiscalisation settings in Odoo Company Settings
    """,
    'author': 'Vast-Solutions',
    'website': '',
    'depends': ['base', 'account', 'point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'data/ir_sequence.xml',
        'views/res_config_settings_views.xml',
        'views/account_tax_views.xml',
        'views/account_move_views.xml',
        'views/l10n_zw_fiscal_day_views.xml',
        'views/pos_session_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'l10n_zw_fiscalisation/static/src/xml/OrderReceipt.xml',
            'l10n_zw_fiscalisation/static/src/js/pos_order.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
