from odoo import models, fields, api
import json
import logging

_logger = logging.getLogger(__name__)

class L10nZwReceiptQueue(models.Model):
    """
    Offline Queuing Model for ZIMRA Fiscalisation.
    Ensures that all receipts are tracked for Z-Report compilation.
    """
    _name = 'l10n_zw.receipt.queue'
    _description = 'ZIMRA Receipt Queue'
    _order = 'receipt_global_no asc'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    
    move_id = fields.Many2one('account.move', string='Invoice', ondelete='cascade')
    pos_order_id = fields.Many2one('pos.order', string='POS Order', ondelete='cascade')
    fiscal_day_id = fields.Many2one('l10n_zw.fiscal.day', string='Fiscal Day', index=True, ondelete='restrict')
    
    receipt_global_no = fields.Integer(string='Receipt No.', required=True, index=True)
    receipt_currency = fields.Char(string='Currency')
    taxes_json = fields.Text(string='Receipt Taxes JSON')
    receipt_total = fields.Float(string='Receipt Total', digits=(18, 2))
    payload_json = fields.Text(string='Payload JSON', required=True)
    
    status = fields.Selection([
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('error', 'Error')
    ], string='Status', default='pending', index=True)
    
    error_message = fields.Text(string='Last Error')
    retry_count = fields.Integer(default=0)