from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_zw_zimrate_enabled = fields.Boolean(string="Enable ZimRate Auto-Fetch", default=False)
    l10n_zw_zimrate_currency_id = fields.Many2one('res.currency', string="ZimRate Foreign Currency")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Environment
    l10n_zw_base_url = fields.Char(
        string="ZIMRA Base URL", 
        default="https://fdmsapitest.zimra.co.zw",
        config_parameter='l10n_zw.base_url'
    )

    # Device Credentials
    l10n_zw_device_id = fields.Integer(
        string="Device ID", 
        config_parameter='l10n_zw.device_id'
    )
    l10n_zw_serial_no = fields.Char(
        string="Device Serial Number", 
        config_parameter='l10n_zw.serial_no'
    )
    l10n_zw_device_model_name = fields.Char(
        string="Device Model Name", 
        config_parameter='l10n_zw.device_model_name'
    )
    l10n_zw_device_model_version = fields.Char(
        string="Device Model Version", 
        config_parameter='l10n_zw.device_model_version'
    )

    # Certificate Paths
    l10n_zw_cert_path = fields.Char(
        string="Certificate Path", 
        default="/path/to/device_cert.pem",
        config_parameter='l10n_zw.cert_path'
    )
    l10n_zw_key_path = fields.Char(
        string="Private Key Path", 
        default="/path/to/private_key.pem",
        config_parameter='l10n_zw.key_path'
    )

    # Fiscal Day Status
    l10n_zw_fiscal_day_status = fields.Char(
        string="Fiscal Day Status", 
        default="Closed"
    )
    l10n_zw_fiscal_day_no = fields.Integer(
        string="Fiscal Day Number", 
        default=0
    )
    l10n_zw_receipt_counter = fields.Integer(
        string="Receipt Counter", 
        default=0
    )

    # ZimRate Integration Fields (Related to company)
    l10n_zw_zimrate_enabled = fields.Boolean(
        string="Enable ZimRate Auto-Fetch",
        related='company_id.l10n_zw_zimrate_enabled', readonly=False, store=True
    )
    l10n_zw_zimrate_currency_id = fields.Many2one(
        'res.currency', 
        string="Foreign Currency to Update",
        related='company_id.l10n_zw_zimrate_currency_id', readonly=False, store=True
    )

    @api.model
    def _l10n_zw_fetch_zimrate(self):
        """
        Cron job: Fetches the RBZ official rate from ZimRate API and updates
        Odoo's res.currency.rate for the configured foreign currency.

        This cron only runs for companies that have explicitly enabled
        l10n_zw_zimrate_enabled in their settings. It is DISABLED by default.

        ZimRate API: https://zimrate.statotec.com
        Docs: https://zimrate.statotec.com/api/latest (returns list of rates)
        """
        import requests
        from odoo import fields

        companies = self.env['res.company'].search([
            ('l10n_zw_zimrate_enabled', '=', True),
            ('l10n_zw_zimrate_currency_id', '!=', False),
        ])

        for company in companies:
            foreign_currency = company.l10n_zw_zimrate_currency_id
            try:
                # ZimRate public endpoint - returns JSON array of rate objects
                response = requests.get(
                    'https://zimrate.statotec.com/api/latest',
                    timeout=15,
                    headers={'Accept': 'application/json'},
                )
                response.raise_for_status()
                rates_data = response.json()

                # Find the RBZ rate for the target currency
                rbz_rate = None
                for entry in rates_data:
                    if (
                        entry.get('currency', '').upper() == foreign_currency.name.upper()
                        and 'RBZ' in entry.get('source', '').upper()
                    ):
                        rbz_rate = entry.get('rate') or entry.get('ask') or entry.get('mid')
                        break

                if not rbz_rate:
                    # Fallback: use any available rate for the currency
                    for entry in rates_data:
                        if entry.get('currency', '').upper() == foreign_currency.name.upper():
                            rbz_rate = entry.get('rate') or entry.get('ask') or entry.get('mid')
                            _logger.warning(
                                "ZIMRA ZimRate: No RBZ-specific rate for %s, using fallback source '%s'",
                                foreign_currency.name, entry.get('source')
                            )
                            break

                if not rbz_rate:
                    _logger.error("ZIMRA ZimRate: Could not find any rate for %s in ZimRate response.", foreign_currency.name)
                    continue

                today = fields.Date.today()
                existing_rate = self.env['res.currency.rate'].search([
                    ('currency_id', '=', foreign_currency.id),
                    ('name', '=', today),
                    ('company_id', '=', company.id),
                ], limit=1)

                rate_vals = {
                    'currency_id': foreign_currency.id,
                    'name': today,
                    'rate': float(rbz_rate),
                    'company_id': company.id,
                }
                if existing_rate:
                    existing_rate.write({'rate': float(rbz_rate)})
                    _logger.info("ZIMRA ZimRate: Updated %s rate to %s for %s", foreign_currency.name, rbz_rate, company.name)
                else:
                    self.env['res.currency.rate'].create(rate_vals)
                    _logger.info("ZIMRA ZimRate: Created %s rate %s for %s", foreign_currency.name, rbz_rate, company.name)

            except requests.exceptions.RequestException as e:
                _logger.error(
                    "ZIMRA ZimRate: Network error fetching rates for company %s: %s. "
                    "Please update the exchange rate manually.",
                    company.name, e
                )
            except Exception as e:
                _logger.error("ZIMRA ZimRate: Unexpected error for company %s: %s", company.name, e)