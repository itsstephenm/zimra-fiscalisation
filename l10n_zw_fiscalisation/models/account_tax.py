from odoo import models, fields

class AccountTax(models.Model):
    """
    Extends Odoo's built-in account.tax model to add ZIMRA-specific fields.
    After installing this module, go to Accounting > Configuration > Taxes
    and fill in the ZIMRA Tax ID and Tax Code for each applicable tax.
    """
    _inherit = 'account.tax'

    zimra_tax_id = fields.Integer(
        string='ZIMRA Tax ID',
        default=0,
        help="The numeric Tax ID returned by ZIMRA's GetConfig endpoint (e.g. 513 for Non-VAT 0%)."
    )
    zimra_tax_code = fields.Char(
        string='ZIMRA Tax Code',
        size=1,
        help="The single-letter tax code used in the ZIMRA receipt hash (e.g. 'A', 'B', 'C', 'D')."
    )
