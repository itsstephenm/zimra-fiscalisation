"""
Diagnostic: what exact concatenation string does the server expect for Day 1?
We know:
  - deviceID = 36915
  - fiscalDayNo = 1
  - fiscalDayDate = 2026-07-29 (date the day was opened, from the first test run)
  - 1 receipt was submitted: USD $10.00, tax ID 513, 0%, code unknown

Try all plausible combinations of fiscalDayUpdated / fiscalDayDate / reconciliationMode
and print the resulting hash so we can compare.
"""
import hashlib, base64, datetime, importlib.util, pathlib

_spec = importlib.util.spec_from_file_location('zimra_client', pathlib.Path('l10n_zw_fiscalisation/models/zimra_client.py'))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ZimraClient = _mod.ZimraClient

client = ZimraClient('https://fdmsapitest.zimra.co.zw', 36915, 'certs/device_cert.pem', 'certs/private_key.pem')

# The stale day's known facts:
#   opened: 2026-07-29 (first run)
#   1 receipt: USD $10.00, tax ID 513, tax% 0.0, code unknown
#   Payment: Cash $10.00

TAX_ID = 513
TAX_PCT = 0.0
SALE = 10.00
TAX_AMT = 0.00

counters = [
    {"fiscalCounterType": "SaleByTax",        "fiscalCounterCurrency": "USD", "fiscalCounterTaxID": TAX_ID, "fiscalCounterTaxPercent": TAX_PCT, "fiscalCounterValue": SALE},
    {"fiscalCounterType": "SaleTaxByTax",     "fiscalCounterCurrency": "USD", "fiscalCounterTaxID": TAX_ID, "fiscalCounterTaxPercent": TAX_PCT, "fiscalCounterValue": TAX_AMT},
    {"fiscalCounterType": "BalanceByMoneyType","fiscalCounterCurrency": "USD", "fiscalCounterMoneyType": "Cash", "fiscalCounterValue": SALE},
]

# Possible open dates
open_dates = ["2026-07-29", "2026-07-28", "2026-07-30"]
# Possible close timestamps (we tried 2026-07-29T10:28:32 region originally)
close_timestamps = [
    # actual time CloseDay was first sent (approx from test run 1)
    "2026-07-29T10:28:49",
    "2026-07-29T10:28:48",
    "2026-07-29T10:28:50",
    "2026-07-29T10:29:04",
    # today's attempts
    datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    # try without fiscalDayUpdated (old format - just date + counters)
    None,
]
recon_modes = ["AUTO", "MANUAL", ""]

print("Testing different hash combinations for stale Day 1:")
print("="*70)

for open_date in open_dates:
    for close_ts in close_timestamps:
        for mode in recon_modes:
            sig = client._generate_fiscal_day_signature(
                fiscal_day_no=1,
                fiscal_day_date=open_date,
                fiscal_day_counters=counters,
                fiscal_day_updated=close_ts,
                reconciliation_mode=mode,
            )
            label = f"open={open_date} close={str(close_ts)[:19]} mode={mode!r}"
            print(f"  {label}")
            print(f"    hash={sig['hash']}")
