from odoo import models, fields, api

class ResCompany(models.Model):
    _inherit = 'res.company'

    # ── Connection Settings ────────────────────────────────────────────────────
    zimra_base_url = fields.Char(
        string='ZIMRA Base URL',
        default='https://fdmsapitest.zimra.co.zw',
        help="Use https://fdmsapitest.zimra.co.zw for testing and https://fdmsapi.zimra.co.zw for production."
    )
    zimra_device_id = fields.Char(string='ZIMRA Device ID')
    zimra_serial_no = fields.Char(string='ZIMRA Serial Number')
    zimra_activation_key = fields.Char(string='ZIMRA Activation Key')
    zimra_device_model_name = fields.Char(string='Device Model Name', default='Server')
    zimra_device_model_version = fields.Char(string='Device Model Version', default='v1')

    # ── Certificate Storage ────────────────────────────────────────────────────
    zimra_cert_path = fields.Char(
        string='Certificate Path',
        default='certs/device_cert.pem',
        help="Absolute or relative path to the ZIMRA X.509 device certificate on the server."
    )
    zimra_key_path = fields.Char(
        string='Private Key Path',
        default='certs/private_key.pem',
        help="Absolute or relative path to the RSA private key on the server."
    )

    # ── Fiscal Day State ───────────────────────────────────────────────────────
    zimra_fiscal_day_status = fields.Selection([
        ('closed', 'Closed'),
        ('open', 'Open'),
    ], string='Fiscal Day Status', default='closed')

    zimra_fiscal_day_no = fields.Integer(string='Current Fiscal Day No.', default=0)
    zimra_fiscal_day_opened = fields.Datetime(string='Fiscal Day Opened At')

    # ── Receipt Counters ───────────────────────────────────────────────────────
    zimra_receipt_counter = fields.Integer(
        string='Receipt Counter',
        default=0,
        help="The global receipt counter for this device. Incremented on every submitted receipt."
    )
    zimra_last_receipt_hash = fields.Char(
        string='Last Receipt Hash',
        help="The SHA-256 hash of the last submitted receipt. Used to chain receipts together.",
        default=''
    )

    def zimra_increment_receipt_counter(self):
        """Thread-safe increment of the receipt counter. Returns the new value."""
        self.ensure_one()
        self.sudo().write({
            'zimra_receipt_counter': self.zimra_receipt_counter + 1
        })
        return self.zimra_receipt_counter
