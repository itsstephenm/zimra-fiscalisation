from odoo import models, fields, api
import json
import logging

_logger = logging.getLogger(__name__)

class L10nZwReceiptQueue(models.Model):
    """
    Offline Queuing Model for ZIMRA Fiscalisation.
    Ensures that all receipts (from Invoices or POS) are submitted strictly in the 
    order of their receiptCounter, handling hash chaining correctly even if the 
    network drops.
    Each queue entry is linked to its fiscal day for accurate Z-Report aggregation.
    """
    _name = 'l10n_zw.receipt.queue'
    _description = 'ZIMRA Receipt Queue'
    _order = 'receipt_global_no asc'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    
    # Store references to the original document
    move_id = fields.Many2one('account.move', string='Invoice', ondelete='cascade')
    pos_order_id = fields.Many2one('pos.order', string='POS Order', ondelete='cascade')
    
    # Link to the open fiscal day so CloseDay can aggregate exact taxes from this day's receipts
    fiscal_day_id = fields.Many2one('l10n_zw.fiscal.day', string='Fiscal Day', index=True, ondelete='restrict')
    
    receipt_global_no = fields.Integer(string='Receipt No.', required=True, index=True)
    receipt_currency = fields.Char(string='Currency', help='ISO currency code of the transaction (USD, ZWG, etc.)')
    # Denormalised tax snapshot for CloseDay aggregation — avoids re-parsing payload JSON at close time
    taxes_json = fields.Text(string='Receipt Taxes JSON', help='receiptTaxes array snapshot from the signed payload.')
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
        companies = self.search([('status', 'in', ['pending', 'error'])]).mapped('company_id')
        
        for company in companies:
            # Get pending receipts for this company, ordered sequentially
            queue_items = self.search([
                ('company_id', '=', company.id),
                ('status', 'in', ['pending', 'error'])
            ], order='receipt_global_no asc')
            
            if not queue_items:
                continue

            from .zimra_client import ZimraClient
            client = ZimraClient(
                base_url=company.l10n_zw_base_url or 'https://fdmsapitest.zimra.co.zw',
                device_id=company.l10n_zw_device_id,
                cert_path=company.l10n_zw_cert_path,
                key_path=company.l10n_zw_key_path,
                device_model_name=company.l10n_zw_device_model_name or 'Server',
                device_model_version=company.l10n_zw_device_model_version or 'v1',
            )

            for item in queue_items:
                try:
                    payload = json.loads(item.payload_json)
                    # Submit directly (the payload already contains the signature/hash)
                    result = client._post_receipt(payload)
                    
                    item.write({
                        'status': 'submitted',
                        'error_message': False
                    })
                    
                    # Update the original document
                    vals = {
                        'l10n_zw_receipt_id': result.get('receiptID', ''),
                        'l10n_zw_operation_id': result.get('operationID', ''),
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
                    # STOP processing for this company to maintain strict hash chain sequence!
                    break
