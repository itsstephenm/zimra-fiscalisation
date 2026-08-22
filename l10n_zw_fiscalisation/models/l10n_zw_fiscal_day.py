from odoo import models, fields, api
from odoo.exceptions import UserError
import json
import logging
from collections import defaultdict

_logger = logging.getLogger(__name__)

class L10nZwFiscalDay(models.Model):
    """
    Manages the opening and closing of a ZIMRA Fiscal Day.
    A fiscal day must be opened before receipts can be generated.
    When closing, a real Z-Report is compiled from this day's receipt_queue
    entries and sent to the ZIMRA CloseDay endpoint.
    """
    _name = 'l10n_zw.fiscal.day'
    _description = 'ZIMRA Fiscal Day'
    _order = 'create_date desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New')
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    
    fiscal_day_no = fields.Integer(string='Fiscal Day Number', readonly=True)
    opened_at = fields.Datetime(string='Opened At', readonly=True)
    closed_at = fields.Datetime(string='Closed At', readonly=True)
    
   state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('closed', 'Closed'),
        ('error', 'Error')
    ], string='Status', default='draft', readonly=False)
    
    receipts_reported = fields.Integer(string='Receipts Reported', readonly=True)
    receipt_counter_closed = fields.Integer(string='Receipt Counter at Close', readonly=True)
    error_message = fields.Text(string='Last Error', readonly=True)

    # Computed summary fields for the list view
    queue_ids = fields.One2many('l10n_zw.receipt.queue', 'fiscal_day_id', string='Receipts')
    total_receipts = fields.Integer(string='Total Receipts', compute='_compute_totals')
    pending_receipts = fields.Integer(string='Pending', compute='_compute_totals')

    @api.depends('queue_ids.status')
    def _compute_totals(self):
        for day in self:
            day.total_receipts = len(day.queue_ids)
            day.pending_receipts = len(day.queue_ids.filtered(lambda q: q.status == 'pending'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('l10n_zw.fiscal.day') or 'New'
        return super().create(vals_list)

    def _get_zimra_client(self):
        """Helper to build a ZimraClient from company settings."""
        self.ensure_one()
        from .zimra_client import ZimraClient
        company = self.company_id
        
        # Force absolute paths if the DB setting is empty or missing the root slash
        cert = company.l10n_zw_cert_path
        if not cert or not cert.startswith('/'):
            cert = '/mnt/extra-addons/l10n_zw_fiscalisation/certs/device_cert.pem'
            
        key = company.l10n_zw_key_path
        if not key or not key.startswith('/'):
            key = '/mnt/extra-addons/l10n_zw_fiscalisation/certs/private_key.pem'

        # Fallback device ID to 37988 if not configured on company settings yet
        device_id = company.l10n_zw_device_id if company.l10n_zw_device_id else 37988

        return ZimraClient(
            base_url=company.l10n_zw_base_url or 'https://fdmsapitest.zimra.co.zw',
            device_id=device_id,
            cert_path=cert,
            key_path=key,
            device_model_name=company.l10n_zw_device_model_name or 'Virtual Server',
            device_model_version=company.l10n_zw_device_model_version or 'v1',
        )

    def action_open_day(self):
        """Opens a new fiscal day via ZIMRA API."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Only draft fiscal days can be opened.")
            
        company = self.company_id
        if company.l10n_zw_fiscal_day_status == 'open':
            raise UserError("A fiscal day is already open for this device.")
            
        opened_at = fields.Datetime.now()
        opened_str = opened_at.strftime('%Y-%m-%dT%H:%M:%S')
        client = self._get_zimra_client()
        
        try:
            result = client.open_day(opened_str)
            fiscal_day_no = result.get('fiscalDayNo', 0)
            
            self.write({
                'state': 'open',
                'opened_at': opened_at,
                'fiscal_day_no': fiscal_day_no,
                'error_message': False,
            })
            company.sudo().write({
                'l10n_zw_fiscal_day_status': 'open',
                'l10n_zw_fiscal_day_no': fiscal_day_no,
                'l10n_zw_fiscal_day_opened': opened_at,
            })
            _logger.info("ZIMRA: Fiscal day %s opened (FDMS fiscal_day_no=%s)", self.name, fiscal_day_no)
            
        except Exception as e:
            self.write({'state': 'error', 'error_message': str(e)})
            raise UserError(f"Failed to open fiscal day: {e}")

    def _compute_fiscal_day_counters(self):
        """
        Aggregates totals from all queue entries linked to this fiscal day to build ZIMRA fiscalCounters.

        ZIMRA's CloseDay requires fiscalDayCounters grouped by currency and tax or payment type.
        """
        self.ensure_one()

        sales_by_tax = defaultdict(float)
        tax_by_tax = defaultdict(float)
        balance_by_money = defaultdict(float)

        queue_entries = self.env['l10n_zw.receipt.queue'].search([
            ('fiscal_day_id', '=', self.id),
        ])
        
        for entry in queue_entries:
            currency = entry.receipt_currency or 'ZWG'
            
            # Extract taxes
            if entry.taxes_json:
                try:
                    taxes = json.loads(entry.taxes_json)
                    for tax in taxes:
                        key = (currency, tax.get('taxID', 0), float(tax.get('taxPercent', 0)))
                        sales_by_tax[key] += float(tax.get('salesAmountWithTax', 0))
                        tax_by_tax[key] += float(tax.get('taxAmount', 0))
                except (json.JSONDecodeError, TypeError):
                    pass
                    
            # Extract payments
            if entry.receipt_total:
                money_key = (currency, 'Cash')
                balance_by_money[money_key] += entry.receipt_total

        counters = []
        
        # 1. SaleByTax
        for (currency, tax_id, tax_percent), amount in sales_by_tax.items():
            if round(amount, 2) != 0:
                counters.append({
                    'fiscalCounterType': 'SaleByTax',
                    'fiscalCounterCurrency': currency,
                    'fiscalCounterTaxID': tax_id,
                    'fiscalCounterTaxPercent': round(tax_percent, 2),
                    'fiscalCounterValue': round(amount, 2)
                })

        # 2. SaleTaxByTax
        for (currency, tax_id, tax_percent), amount in tax_by_tax.items():
            if round(amount, 2) != 0:
                counters.append({
                    'fiscalCounterType': 'SaleTaxByTax',
                    'fiscalCounterCurrency': currency,
                    'fiscalCounterTaxID': tax_id,
                    'fiscalCounterTaxPercent': round(tax_percent, 2),
                    'fiscalCounterValue': round(amount, 2)
                })
                
        # 3. BalanceByMoneyType
        for (currency, money_type), amount in balance_by_money.items():
            if round(amount, 2) != 0:
                counters.append({
                    'fiscalCounterType': 'BalanceByMoneyType',
                    'fiscalCounterCurrency': currency,
                    'fiscalCounterMoneyType': money_type,
                    'fiscalCounterValue': round(amount, 2)
                })

        return counters

    def get_z_report_data(self):
        """Helper to parse and aggregate receipt queue items for the PDF Z-Report."""
        self.ensure_one()
        tax_summary = defaultdict(lambda: {'sales': 0.0, 'tax': 0.0})
        total_sales = 0.0
        
        for item in self.queue_ids:
            total_sales += item.receipt_total or 0.0
            if item.taxes_json:
                try:
                    taxes = json.loads(item.taxes_json)
                    for t in taxes:
                        code = t.get('taxCode', 'A')
                        pct = t.get('taxPercent', 0)
                        key = f"Tax Code {code} ({pct}%)"
                        tax_summary[key]['sales'] += float(t.get('salesAmountWithTax', 0.0))
                        tax_summary[key]['tax'] += float(t.get('taxAmount', 0.0))
                except (json.JSONDecodeError, TypeError):
                    pass
                    
        return {
            'tax_summary': dict(tax_summary),
            'total_sales': total_sales,
        }

    def action_close_day(self):
        """
        Compiles the real Z-Report from this day's receipts and closes the fiscal day.
        """
        self.ensure_one()
        if self.state != 'open':
            raise UserError("Only open fiscal days can be closed.")
            
        company = self.company_id

        # Safety guard: do not allow CloseDay if any receipts are still pending/error
        pending_count = self.env['l10n_zw.receipt.queue'].search_count([
            ('fiscal_day_id', '=', self.id),
            ('status', 'in', ['pending', 'error']),
        ])
        if pending_count:
            raise UserError(
                f"Cannot close the fiscal day: {pending_count} receipt(s) are still pending "
                f"or failed to submit to ZIMRA. Please ensure all receipts are successfully "
                f"submitted before closing the day."
            )

        submitted_count = self.env['l10n_zw.receipt.queue'].search_count([
            ('fiscal_day_id', '=', self.id),
        ])

        closed_at = fields.Datetime.now()
        closed_at_str = closed_at.strftime('%Y-%m-%dT%H:%M:%S')
        reconciliation_mode = "AUTO"  # Always AUTO for online (real-time) devices

        client = self._get_zimra_client()

        # Compute Counters
        fiscal_day_counters = self._compute_fiscal_day_counters()

        # Compute Signature
        fiscal_day_date = self.opened_at.strftime('%Y-%m-%d')
        signature_data = client._generate_fiscal_day_signature(
            fiscal_day_no=self.fiscal_day_no,
            fiscal_day_date=fiscal_day_date,
            fiscal_day_counters=fiscal_day_counters,
        )

        # Build precise payload as per FDMS spec for Online CloseDay
        payload = {
            "deviceID"                : int(company.l10n_zw_device_id or 37988),
            "fiscalDayNo"             : self.fiscal_day_no,
            "fiscalDayDate"           : fiscal_day_date,
            "fiscalDayUpdated"        : closed_at_str,
            "reconciliationMode"      : reconciliation_mode,
            "fiscalDayCounters"       : fiscal_day_counters,
            "fiscalDayDeviceSignature": signature_data,
            "receiptCounter"          : company.l10n_zw_receipt_counter,
        }

        _logger.info(
            "ZIMRA CloseDay payload for %s: %d counters",
            self.name, len(fiscal_day_counters)
        )
        
        try:
            import requests
            url = client._get_url("CloseDay")
            response = requests.post(
                url,
                json=payload,
                headers=client.headers,
                cert=(client.cert_path, client.key_path),
                timeout=30,
            )
            response.raise_for_status()
            
            self.write({
                'state': 'closed',
                'closed_at': closed_at,
                'receipt_counter_closed': company.l10n_zw_receipt_counter,
                'receipts_reported': submitted_count,
                'error_message': False,
            })
            company.sudo().write({
                'l10n_zw_fiscal_day_status': 'closed',
            })
            _logger.info("ZIMRA: Fiscal day %s closed successfully.", self.name)
            
        except Exception as e:
            self.write({'state': 'error', 'error_message': str(e)})
            raise UserError(f"Failed to close fiscal day: {e}")