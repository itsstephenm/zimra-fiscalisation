from odoo import models, fields, api
import json
import logging

_logger = logging.getLogger(__name__)

class L10nZwReceiptQueue(models.Model):
    """
    Offline Queuing Model for ZIMRA Fiscalisation.
    Ensures that all receipts are submitted strictly in the 
    order of their receiptCounter, handling hash chaining correctly.
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

    @api.model
    def _process_queue(self):
        """
        Cron job method to process pending receipts.
        Must process strictly in receipt_global_no order per company.
        """
        queue_items = self.search([
            ('status', 'in', ['pending', 'error'])
        ], order='receipt_global_no asc')
        
        for item in queue_items:
            company = item.company_id
            if not company:
                continue

            from .zimra_client import ZimraClient
            
            cert = company.l10n_zw_cert_path
            if not cert or not cert.startswith('/'):
                cert = '/mnt/extra-addons/l10n_zw_fiscalisation/certs/device_cert.pem'
                
            key = company.l10n_zw_key_path
            if not key or not key.startswith('/'):
                key = '/mnt/extra-addons/l10n_zw_fiscalisation/certs/private_key.pem'

            device_id = company.l10n_zw_device_id if company.l10n_zw_device_id else 37988

            client = ZimraClient(
                base_url=company.l10n_zw_base_url or 'https://fdmsapitest.zimra.co.zw',
                device_id=device_id,
                cert_path=cert,
                key_path=key,
                device_model_name=company.l10n_zw_device_model_name or 'Server',
                device_model_version=company.l10n_zw_device_model_version or 'v1',
            )

            try:
                payload = json.loads(item.payload_json)
                result = client._post_receipt(payload) or {}
                
                item.write({
                    'status': 'submitted',
                    'error_message': False
                })
                
                # Extract ID fields flexibly supporting multiple casing formats
                receipt_id = str(result.get('receiptID') or result.get('receiptId') or result.get('id') or '')
                operation_id = str(result.get('operationID') or result.get('operationId') or '')

                vals = {
                    'l10n_zw_receipt_id': receipt_id,
                    'l10n_zw_operation_id': operation_id,
                    'l10n_zw_status': 'submitted',
                    'l10n_zw_error_message': False,
                }
                if item.move_id:
                    item.move_id.write(vals)
                if item.pos_order_id:
                    item.pos_order_id.write(vals)

                _logger.info("ZIMRA Queue: Successfully submitted receipt %s", item.receipt_global_no)
                
            except Exception as e:
                error_msg = str(e)
                item.write({
                    'status': 'error',
                    'error_message': error_msg,
                    'retry_count': item.retry_count + 1
                })
                _logger.error("ZIMRA Queue: Failed to submit receipt %s: %s", item.receipt_global_no, error_msg)
                break