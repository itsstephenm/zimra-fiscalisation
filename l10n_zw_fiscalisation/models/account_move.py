from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # ── ZIMRA Status Fields ────────────────────────────────────────────────────
    l10n_zw_receipt_id = fields.Char(string='ZIMRA Receipt ID', readonly=True, copy=False)
    l10n_zw_operation_id = fields.Char(string='ZIMRA Operation ID', readonly=True, copy=False)
    l10n_zw_receipt_global_no = fields.Integer(string='ZIMRA Receipt No.', readonly=True, copy=False)
    l10n_zw_status = fields.Selection([
        ('not_submitted', 'Not Submitted'),
        ('submitted', 'Submitted'),
        ('error', 'Submission Error'),
    ], string='ZIMRA Status', default='not_submitted', readonly=True, copy=False)
    l10n_zw_error_message = fields.Text(string='ZIMRA Error', readonly=True, copy=False)

    def action_post(self):
        """Override invoice confirmation to hook into ZIMRA fiscalisation."""
        res = super(AccountMove, self).action_post()
        for move in self:
            # Only process outgoing invoices/credit notes with ZIMRA configured (or default device fallback)
            if move.move_type in ('out_invoice', 'out_refund') and move.company_id:
                move._submit_to_zimra()
        return res

    def _submit_to_zimra(self):
        """Build the ZIMRA payload and submit it."""
        self.ensure_one()
        company = self.company_id

        # Import the decoupled engine
        from .zimra_client import ZimraClient

        # Force absolute paths if the DB setting is empty or missing the root slash
        cert = company.l10n_zw_cert_path
        if not cert or not cert.startswith('/'):
            cert = '/mnt/extra-addons/l10n_zw_fiscalisation/certs/device_cert.pem'
            
        key = company.l10n_zw_key_path
        if not key or not key.startswith('/'):
            key = '/mnt/extra-addons/l10n_zw_fiscalisation/certs/private_key.pem'

        # Fallback device ID to 37988 if not configured on company settings yet
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
            payload = self._prepare_zimra_payload()
            previous_hash = company.l10n_zw_last_receipt_hash or ''
            
            # 1. Generate Signature Locally
            signature_data = client._generate_signature(payload, previous_hash)
            payload["receiptDeviceSignature"] = signature_data
            
            # 2. Increment counter and save new hash locally IMMEDIATELY
            if hasattr(company, 'l10n_zw_increment_receipt_counter'):
                receipt_global_no = company.l10n_zw_increment_receipt_counter()
            else:
                receipt_global_no = (company.l10n_zw_receipt_counter or 0) + 1
                company.sudo().write({'l10n_zw_receipt_counter': receipt_global_no})

            new_hash = signature_data.get('hash', previous_hash)
            company.sudo().write({'l10n_zw_last_receipt_hash': new_hash})
            
            # 3. Find the currently open fiscal day (required for Z-Report aggregation)
            open_day = self.env['l10n_zw.fiscal.day'].search([
                ('company_id', '=', company.id),
                ('state', '=', 'open'),
            ], limit=1)
            
            # 4. Add to Queue with denormalised fields for CloseDay aggregation
            import json as _json
            self.env['l10n_zw.receipt.queue'].create({
                'company_id': company.id,
                'move_id': self.id,
                'fiscal_day_id': open_day.id if open_day else False,
                'receipt_global_no': receipt_global_no,
                'receipt_currency': payload.get('receiptCurrency', ''),
                'receipt_total': payload.get('receiptTotal', 0.0),
                'taxes_json': _json.dumps(payload.get('receiptTaxes', [])),
                'payload_json': _json.dumps(payload),
                'status': 'pending',
            })
            
            # 5. Attempt to process queue immediately (fail silently if offline)
            try:
                self.env['l10n_zw.receipt.queue']._process_queue()
            except Exception:
                pass
                
            self.write({
                'l10n_zw_receipt_global_no': receipt_global_no,
                'l10n_zw_status': 'submitted',  # updated to reflect successful queuing and signing
            })
            _logger.info("ZIMRA: Invoice %s signed and queued successfully.", self.name)

        except Exception as e:
            error_msg = str(e)
            self.write({
                'l10n_zw_status': 'error',
                'l10n_zw_error_message': error_msg,
            })
            _logger.error("ZIMRA: Invoice %s local signing failed: %s", self.name, error_msg)

    def _prepare_zimra_payload(self):
        """
        Maps an Odoo account.move to a ZIMRA SubmitReceipt JSON payload.
        """
        self.ensure_one()
        company = self.company_id

        # ── 1. Receipt Type ──────────────────────────────────────────────────
        receipt_type_map = {
            'out_invoice': 'FISCALINVOICE',
            'out_refund': 'CREDITNOTE',
        }
        receipt_type = receipt_type_map.get(self.move_type, 'FISCALINVOICE')

        # ── 2. Receipt Counter ───────────────────────────────────────────────
        receipt_counter = (company.l10n_zw_receipt_counter or 0) + 1  # next counter

        # ── 3. Receipt Date ──────────────────────────────────────────────────
        invoice_date = self.invoice_date or fields.Date.today()
        receipt_date = f"{invoice_date}T00:00:00"

        # ── 4. Currency ──────────────────────────────────────────────────────
        currency = self.currency_id.name or 'USD'

        # ── 5. Buyer Data ────────────────────────────────────────────────────
        buyer_data = {}
        if self.partner_id:
            partner = self.partner_id
            buyer_data = {
                'buyerName': partner.name or '',
                'buyerAddress': {
                    'province': partner.state_id.name if partner.state_id else '',
                    'city': partner.city or '',
                    'street': partner.street or '',
                    'houseNo': '',
                    'district': '',
                },
                'buyerPhone': partner.phone or '',
                'buyerEmail': partner.email or '',
            }
            if partner.vat:
                buyer_data['buyerVatNumber'] = partner.vat

        # ── 6. Tax Grouping ──────────────────────────────────────────────────
        tax_groups = {}  # key: account.tax record
        for line in self.invoice_line_ids:
            if line.display_type in ('line_section', 'line_note'):
                continue
            for tax in line.tax_ids:
                if tax not in tax_groups:
                    tax_groups[tax] = {
                        'taxAmount': 0.0,
                        'salesAmountWithTax': 0.0,
                    }
                sign = -1 if self.move_type == 'out_refund' else 1
                tax_groups[tax]['salesAmountWithTax'] += sign * line.price_total
                tax_line = self.line_ids.filtered(
                    lambda l: l.tax_line_id == tax
                )
                tax_groups[tax]['taxAmount'] += sign * sum(tax_line.mapped('price_unit'))

        receipt_taxes = []
        for tax, amounts in tax_groups.items():
            receipt_taxes.append({
                'taxID': getattr(tax, 'l10n_zw_tax_id', 1) or 1,
                'taxCode': getattr(tax, 'l10n_zw_tax_code', 'A') or 'A',
                'taxPercent': tax.amount if tax.amount_type == 'percent' else 0.0,
                'taxAmount': round(amounts['taxAmount'], 2),
                'salesAmountWithTax': round(amounts['salesAmountWithTax'], 2),
            })

        # ── 7. Receipt Lines ─────────────────────────────────────────────────
        sign = -1 if self.move_type == 'out_refund' else 1
        receipt_lines = []
        for idx, line in enumerate(self.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
        )):
            tax_code = 'A'
            if line.tax_ids and hasattr(line.tax_ids[0], 'l10n_zw_tax_code'):
                tax_code = line.tax_ids[0].l10n_zw_tax_code or 'A'
            receipt_lines.append({
                'receiptLineNo': idx + 1,
                'receiptLineHSCode': '',
                'receiptLineName': line.name or line.product_id.name or '',
                'receiptLinePrice': round(line.price_unit, 2),
                'receiptLineQuantity': line.quantity,
                'receiptLineTotal': round(sign * line.price_total, 2),
                'taxCode': tax_code,
            })

        # ── 8. Totals ────────────────────────────────────────────────────────
        receipt_total = round(sign * self.amount_total, 2)

        # ── 9. Print Form ────────────────────────────────────────────────────
        is_b2b = bool(self.partner_id and self.partner_id.vat)
        receipt_print_form = 'INVOICE' if is_b2b else 'RECEIPT'

        # ── Assemble Final Payload ───────────────────────────────────────────
        payload = {
            'receiptType': receipt_type,
            'receiptCurrency': currency,
            'receiptCounter': receipt_counter,
            'receiptGlobalNo': receipt_counter,
            'receiptDate': receipt_date,
            'receiptLinesTaxInclusive': True,
            'receiptTotal': receipt_total,
            'receiptTaxes': receipt_taxes,
            'receiptLines': receipt_lines,
            'receiptPrintForm': receipt_print_form,
            'buyerData': buyer_data,
        }

        _logger.debug("ZIMRA: Built payload for invoice %s: %s", self.name, payload)
        return payload