from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # ── ZIMRA Status Fields ────────────────────────────────────────────────────
    zimra_receipt_id = fields.Char(string='ZIMRA Receipt ID', readonly=True, copy=False)
    zimra_operation_id = fields.Char(string='ZIMRA Operation ID', readonly=True, copy=False)
    zimra_receipt_global_no = fields.Integer(string='ZIMRA Receipt No.', readonly=True, copy=False)
    zimra_status = fields.Selection([
        ('not_submitted', 'Not Submitted'),
        ('submitted', 'Submitted'),
        ('error', 'Submission Error'),
    ], string='ZIMRA Status', default='not_submitted', readonly=True, copy=False)
    zimra_error_message = fields.Text(string='ZIMRA Error', readonly=True, copy=False)

    def action_post(self):
        """Override invoice confirmation to hook into ZIMRA fiscalisation."""
        res = super(AccountMove, self).action_post()
        for move in self:
            # Only process outgoing invoices/credit notes with ZIMRA configured
            if move.move_type in ('out_invoice', 'out_refund') and move.company_id.zimra_device_id:
                move._submit_to_zimra()
        return res

    def _submit_to_zimra(self):
        """Build the ZIMRA payload and submit it."""
        self.ensure_one()
        company = self.company_id

        # Import the decoupled engine
        from .zimra_client import ZimraClient

        client = ZimraClient(
            base_url=company.zimra_base_url or 'https://fdmsapitest.zimra.co.zw',
            device_id=company.zimra_device_id,
            cert_path=company.zimra_cert_path,
            key_path=company.zimra_key_path,
            device_model_name=company.zimra_device_model_name or 'Server',
            device_model_version=company.zimra_device_model_version or 'v1',
        )

        try:
            payload = self._prepare_zimra_payload()
            previous_hash = company.zimra_last_receipt_hash or ''
            result = client.submit_receipt(payload, previous_hash)

            # Increment counter and save new hash
            receipt_global_no = company.zimra_increment_receipt_counter()
            new_hash = result.get('receiptDeviceSignature', {}).get('hash', '')
            company.sudo().write({'zimra_last_receipt_hash': new_hash})

            # Write ZIMRA response back to invoice
            self.write({
                'zimra_receipt_id': result.get('receiptID', ''),
                'zimra_operation_id': result.get('operationID', ''),
                'zimra_receipt_global_no': receipt_global_no,
                'zimra_status': 'submitted',
                'zimra_error_message': False,
            })
            _logger.info("ZIMRA: Invoice %s submitted successfully. Receipt ID: %s", self.name, result.get('receiptID'))

        except Exception as e:
            error_msg = str(e)
            self.write({
                'zimra_status': 'error',
                'zimra_error_message': error_msg,
            })
            _logger.error("ZIMRA: Submission failed for invoice %s: %s", self.name, error_msg)
            # We do NOT raise so that the invoice is still confirmed in Odoo
            # The accountant can retry via a button later

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
        receipt_counter = company.zimra_receipt_counter + 1  # next counter

        # ── 3. Receipt Date ──────────────────────────────────────────────────
        invoice_date = self.invoice_date or fields.Date.today()
        receipt_date = f"{invoice_date}T00:00:00"

        # ── 4. Currency ──────────────────────────────────────────────────────
        currency = self.currency_id.name

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
        # Group invoice lines by tax to compute receiptTaxes
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
                # For credit notes, ZIMRA expects negative amounts
                sign = -1 if self.move_type == 'out_refund' else 1
                tax_groups[tax]['salesAmountWithTax'] += sign * line.price_total
                # Compute tax amount from the tax lines
                tax_line = self.line_ids.filtered(
                    lambda l: l.tax_line_id == tax
                )
                tax_groups[tax]['taxAmount'] += sign * sum(tax_line.mapped('price_unit'))

        receipt_taxes = []
        for tax, amounts in tax_groups.items():
            receipt_taxes.append({
                'taxID': tax.zimra_tax_id or 0,
                'taxCode': tax.zimra_tax_code or 'A',
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
            tax_code = line.tax_ids[0].zimra_tax_code if line.tax_ids and line.tax_ids[0].zimra_tax_code else 'A'
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
        sign = -1 if self.move_type == 'out_refund' else 1
        receipt_total = round(sign * self.amount_total, 2)

        # ── 9. Print Form ────────────────────────────────────────────────────
        # B2B (partner has VAT/TIN) → INVOICE, B2C → RECEIPT
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
