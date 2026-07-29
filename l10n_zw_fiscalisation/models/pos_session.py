from odoo import models, fields, api
from odoo.exceptions import UserError

class PosSession(models.Model):
    _inherit = 'pos.session'

    l10n_zw_fiscal_day_id = fields.Many2one(
        'l10n_zw.fiscal.day', 
        string='ZIMRA Fiscal Day', 
        readonly=True, 
        copy=False
    )
    l10n_zw_fiscal_day_status = fields.Selection(
        related='company_id.l10n_zw_fiscal_day_status', 
        string='ZIMRA Device Status'
    )

    def action_l10n_zw_open_fiscal_day(self):
        """Action for the POS Session form button to open a ZIMRA fiscal day."""
        self.ensure_one()
        if self.company_id.l10n_zw_fiscal_day_status == 'open':
            raise UserError("A ZIMRA Fiscal Day is already open for this company.")
            
        fiscal_day = self.env['l10n_zw.fiscal.day'].create({'company_id': self.company_id.id})
        fiscal_day.action_open_day()
        
        self.l10n_zw_fiscal_day_id = fiscal_day.id
        return True

    def action_l10n_zw_close_fiscal_day(self):
        """Action for the POS Session form button to close a ZIMRA fiscal day (Z-Report)."""
        self.ensure_one()
        
        # Find the currently open fiscal day
        open_day = self.env['l10n_zw.fiscal.day'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'open')
        ], limit=1)
        
        if not open_day:
            raise UserError("There is no open ZIMRA Fiscal Day to close.")
            
        open_day.action_close_day()
        return True
