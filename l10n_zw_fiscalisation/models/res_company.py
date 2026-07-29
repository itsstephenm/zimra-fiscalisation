from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class ResCompany(models.Model):
    _inherit = 'res.company'

    # ── Connection Settings ────────────────────────────────────────────────────
    l10n_zw_base_url = fields.Char(
        string='ZIMRA Base URL',
        default='https://fdmsapitest.zimra.co.zw',
        help="Use https://fdmsapitest.zimra.co.zw for testing and https://fdmsapi.zimra.co.zw for production."
    )
    l10n_zw_device_id = fields.Char(string='ZIMRA Device ID')
    l10n_zw_serial_no = fields.Char(string='ZIMRA Serial Number')
    l10n_zw_activation_key = fields.Char(string='ZIMRA Activation Key')
    l10n_zw_device_model_name = fields.Char(string='Device Model Name', default='Server')
    l10n_zw_device_model_version = fields.Char(string='Device Model Version', default='v1')

    # ── Certificate Storage ────────────────────────────────────────────────────
    l10n_zw_cert_path = fields.Char(
        string='Certificate Path',
        default='certs/device_cert.pem',
        help="Absolute or relative path to the ZIMRA X.509 device certificate on the server."
    )
    l10n_zw_key_path = fields.Char(
        string='Private Key Path',
        default='certs/private_key.pem',
        help="Absolute or relative path to the RSA private key on the server."
    )

    # ── Fiscal Day State ───────────────────────────────────────────────────────
    l10n_zw_fiscal_day_status = fields.Selection([
        ('closed', 'Closed'),
        ('open', 'Open'),
    ], string='Fiscal Day Status', default='closed')

    l10n_zw_fiscal_day_no = fields.Integer(string='Current Fiscal Day No.', default=0)
    l10n_zw_fiscal_day_opened = fields.Datetime(string='Fiscal Day Opened At')

    # ── Receipt Counters ───────────────────────────────────────────────────────
    l10n_zw_receipt_counter = fields.Integer(
        string='Receipt Counter',
        default=0,
        help="The global receipt counter for this device. Incremented on every submitted receipt."
    )
    l10n_zw_last_receipt_hash = fields.Char(
        string='Last Receipt Hash',
        help="The SHA-256 hash of the last submitted receipt. Used to chain receipts together.",
        default=''
    )

    # ── ZimRate Automatic Exchange Rate Settings ───────────────────────────────
    l10n_zw_zimrate_enabled = fields.Boolean(
        string='Enable ZimRate Auto-Fetch',
        default=False,
        help=(
            "When enabled, a daily cron job will fetch the official RBZ exchange rate "
            "from ZimRate (zimrate.statotec.com) and update Odoo's currency rates automatically.\n\n"
            "NOTE: ZimRate is an unofficial third-party aggregator. If it is unavailable, "
            "you must update the exchange rate manually via Accounting → Configuration → Currencies."
        )
    )
    l10n_zw_zimrate_currency_id = fields.Many2one(
        'res.currency',
        string='Foreign Currency to Update',
        help="The non-base currency to update from ZimRate (typically USD when the company currency is ZWG)."
    )

    def l10n_zw_increment_receipt_counter(self):
        """Thread-safe increment of the receipt counter. Returns the new value."""
        self.ensure_one()
        self.sudo().write({
            'l10n_zw_receipt_counter': self.l10n_zw_receipt_counter + 1
        })
        return self.l10n_zw_receipt_counter
