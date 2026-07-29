from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class PosOrder(models.Model):
    """
    Extends Odoo POS Order to hook into ZIMRA fiscalisation.
    This is the primary flow for till/POS receipt printing in SME shops.
    ZIMRA receipts are submitted automatically when a POS order is paid/closed.
    """
    _inherit = 'pos.order'

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
    l10n_zw_qr_url = fields.Char(string='ZIMRA QR URL', readonly=True, copy=False)

    def action_pos_order_paid(self):
        """Override the POS order paid action to hook into ZIMRA fiscalisation."""
        res = super(PosOrder, self).action_pos_order_paid()
        for order in self:
            if order.company_id.l10n_zw_device_id:
                order._submit_pos_to_zimra()
        return res

    def _submit_pos_to_zimra(self):
        """Build the ZIMRA payload for a POS order and submit it."""
        self.ensure_one()
        company = self.company_id

        from .zimra_client import ZimraClient

        client = ZimraClient(
            base_url=company.l10n_zw_base_url or 'https://fdmsapitest.zimra.co.zw',
            device_id=company.l10n_zw_device_id,
            cert_path=company.l10n_zw_cert_path,
            key_path=company.l10n_zw_key_path,
            device_model_name=company.l10n_zw_device_model_name or 'Server',
            device_model_version=company.l10n_zw_device_model_version or 'v1',
        )

        try:
            payload = self._prepare_zimra_pos_payload()
            previous_hash = company.l10n_zw_last_receipt_hash or ''
            
            # 1. Generate Signature Locally
            signature_data = client._generate_signature(payload, previous_hash)
            payload["receiptDeviceSignature"] = signature_data
            
            # 2. Increment counter and save new hash locally IMMEDIATELY
            receipt_global_no = company.l10n_zw_increment_receipt_counter()
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
                'pos_order_id': self.id,
                'fiscal_day_id': open_day.id if open_day else False,
                'receipt_global_no': receipt_global_no,
                'receipt_currency': payload.get('receiptCurrency', ''),
                'receipt_total': payload.get('receiptTotal', 0.0),
                'taxes_json': _json.dumps(payload.get('receiptTaxes', [])),
                'payload_json': _json.dumps(payload),
                'status': 'pending',
            })
            
            # 5. Attempt to process queue immediately
            try:
                self.env['l10n_zw.receipt.queue']._process_queue()
            except Exception:
                pass

            # Build ZIMRA QR Code URL
            # Format: https://fdms.zimra.co.zw/receipts/verify?deviceID=XXX&receiptNo=YYY
            base = (company.l10n_zw_base_url or '').replace('fdmsapitest', 'fdms').replace('/api', '')
            qr_url = f"{base}/receipts/verify?deviceID={company.l10n_zw_device_id}&receiptNo={receipt_global_no}"

            self.write({
                'l10n_zw_receipt_global_no': receipt_global_no,
                'l10n_zw_status': 'not_submitted',
                'l10n_zw_qr_url': qr_url,
            })

        except Exception as e:
            error_msg = str(e)
            self.write({
                'l10n_zw_status': 'error',
                'l10n_zw_error_message': error_msg,
            })
            _logger.error("ZIMRA: POS Order %s local signing failed: %s", self.name, error_msg)

    def _prepare_zimra_pos_payload(self):
        """
        Maps an Odoo pos.order to a ZIMRA SubmitReceipt JSON payload.
        This is optimised for B2C till receipts at POS.
        """
        self.ensure_one()
        company = self.company_id
        receipt_counter = company.l10n_zw_receipt_counter + 1

        # ── Receipt Date ─────────────────────────────────────────────────────
        order_date = self.date_order or fields.Datetime.now()
        receipt_date = order_date.strftime('%Y-%m-%dT%H:%M:%S')

        # ── Currency ─────────────────────────────────────────────────────────
        currency = self.currency_id.name

        # ── Buyer Data (B2C — minimal info at till) ──────────────────────────
        buyer_data = {}
        if self.partner_id and self.partner_id != company.partner_id:
            buyer_data = {
                'buyerName': self.partner_id.name or '',
                'buyerPhone': self.partner_id.phone or '',
                'buyerEmail': self.partner_id.email or '',
                'buyerAddress': {
                    'province': self.partner_id.state_id.name if self.partner_id.state_id else '',
                    'city': self.partner_id.city or '',
                    'street': self.partner_id.street or '',
                    'houseNo': '',
                    'district': '',
                },
            }
            if self.partner_id.vat:
                buyer_data['buyerVatNumber'] = self.partner_id.vat

        # ── Tax Grouping ─────────────────────────────────────────────────────
        tax_groups = {}
        for line in self.lines:
            for tax in line.tax_ids:
                if tax not in tax_groups:
                    tax_groups[tax] = {
                        'taxAmount': 0.0,
                        'salesAmountWithTax': 0.0,
                    }
                tax_groups[tax]['salesAmountWithTax'] += line.price_subtotal_incl
                # Compute the tax portion of the line
                tax_amount = line.price_subtotal_incl - line.price_subtotal
                tax_groups[tax]['taxAmount'] += tax_amount

        receipt_taxes = []
        for tax, amounts in tax_groups.items():
            receipt_taxes.append({
                'taxID': tax.l10n_zw_tax_id or 0,
                'taxCode': tax.l10n_zw_tax_code or 'A',
                'taxPercent': tax.amount if tax.amount_type == 'percent' else 0.0,
                'taxAmount': round(amounts['taxAmount'], 2),
                'salesAmountWithTax': round(amounts['salesAmountWithTax'], 2),
            })

        # ── Receipt Lines ────────────────────────────────────────────────────
        receipt_lines = []
        for idx, line in enumerate(self.lines):
            tax_code = line.tax_ids[0].l10n_zw_tax_code if line.tax_ids and line.tax_ids[0].l10n_zw_tax_code else 'A'
            receipt_lines.append({
                'receiptLineNo': idx + 1,
                'receiptLineHSCode': '',
                'receiptLineName': line.product_id.name or '',
                'receiptLinePrice': round(line.price_unit, 2),
                'receiptLineQuantity': line.qty,
                'receiptLineTotal': round(line.price_subtotal_incl, 2),
                'taxCode': tax_code,
            })

        # ── Assemble Payload ─────────────────────────────────────────────────
        payload = {
            'receiptType': 'FISCALINVOICE',
            'receiptCurrency': currency,
            'receiptCounter': receipt_counter,
            'receiptGlobalNo': receipt_counter,
            'receiptDate': receipt_date,
            'receiptLinesTaxInclusive': True,
            'receiptTotal': round(self.amount_total, 2),
            'receiptTaxes': receipt_taxes,
            'receiptLines': receipt_lines,
            'receiptPrintForm': 'RECEIPT',  # POS is always B2C receipt
            'buyerData': buyer_data,
        }

        _logger.debug("ZIMRA: Built POS payload for order %s: %s", self.name, payload)
        return payload
