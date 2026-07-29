from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

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
                # ZimRate objects typically have: {'currency': 'USD', 'source': 'RBZ', 'rate': 27.34, ...}
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

                # Odoo stores currency rates as: 1 [company_currency] = rate [foreign_currency]
                # If company currency is ZWG and foreign is USD:
                #   ZimRate gives e.g. 27.34 ZWG per 1 USD → Odoo rate = 27.34
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
