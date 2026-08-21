"""
End-to-end sandbox integration test against fdmsapitest.zimra.co.zw.

Sequence:
  0. GetConfig  → discover device's actual tax ID, percent, and tax code
  0b. GetStatus → if a day is already open / close-failed, close it first
  1. OpenDay    → get fiscalDayNo
  2. SubmitReceipt (one receipt using the device's real tax, with full buyerData)
  3. CloseDay   → should produce zero validation errors

Goal: A *clean* run — HTTP 200 with an empty validationErrors list, and
GetStatus afterwards showing FiscalDayClosed.

This also definitively confirms whether USD or USDL is the correct currency string,
and whether the fiscal-day signature is correctly formed.
"""
import sys
import json
import time
import datetime
import requests
import importlib.util
import pathlib

# ---------------------------------------------------------------------------
# Load ZimraClient directly to avoid the Odoo-dependent __init__.py chain
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "zimra_client",
    pathlib.Path(__file__).parent / "l10n_zw_fiscalisation" / "models" / "zimra_client.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ZimraClient = _mod.ZimraClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEVICE_ID = 36915
BASE_URL  = "https://fdmsapitest.zimra.co.zw"
CERT_PATH = "certs/device_cert.pem"
KEY_PATH  = "certs/private_key.pem"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts_now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def date_today():
    return datetime.date.today().strftime("%Y-%m-%d")

def pp(label, data):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print('='*60)
    print(json.dumps(data, indent=2, default=str))

def check_validation_errors(response_body, step_name):
    """
    Inspect validationErrors. Returns True if there are zero Red errors.
    Yellow warnings are printed but do not fail the check.
    """
    errors = response_body.get("validationErrors", [])
    if not errors:
        print(f"    [CLEAN] {step_name}: zero validationErrors.")
        return True

    reds    = [e for e in errors if e.get("validationErrorColor", "").lower() == "red"]
    yellows = [e for e in errors if e.get("validationErrorColor", "").lower() == "yellow"]

    for e in yellows:
        print(f"    [YELLOW] {e.get('validationErrorCode')}: {e.get('validationErrorDescription')}")
    for e in reds:
        print(f"    [RED]    {e.get('validationErrorCode')}: {e.get('validationErrorDescription')}")

    if reds:
        print(f"    [FAIL] {step_name} has {len(reds)} RED error(s).")
        return False
    print(f"    [OK] {step_name}: only Yellow warnings (acceptable).")
    return True


def get_status(client):
    url = client._get_url("GetStatus")
    resp = requests.get(url, headers=client.headers, cert=(CERT_PATH, KEY_PATH), timeout=15)
    resp.raise_for_status()
    return resp.json()


def close_day(client, fiscal_day_no, fiscal_day_date, counters, receipt_counter,
              fiscal_day_updated=None, reconciliation_mode="AUTO"):
    """
    Build and POST a CloseDay request.
    Returns (http_ok: bool, body: dict|str, signature_hash: str)

    Per ZIMRA FDMS API Spec §13.3.1 the hash covers:
      deviceID + fiscalDayNo + fiscalDayDate + counters
    """
    if fiscal_day_updated is None:
        fiscal_day_updated = ts_now()

    sig = client._generate_fiscal_day_signature(
        fiscal_day_no=fiscal_day_no,
        fiscal_day_date=fiscal_day_date,
        fiscal_day_counters=counters,
    )
    payload = {
        "deviceID"                : int(DEVICE_ID),
        "fiscalDayNo"             : fiscal_day_no,
        "fiscalDayDate"           : fiscal_day_date,
        "fiscalDayUpdated"        : fiscal_day_updated,
        "reconciliationMode"      : reconciliation_mode,
        "fiscalDayCounters"       : counters,
        "fiscalDayDeviceSignature": sig,
        "receiptCounter"          : receipt_counter,
    }
    print(f"    fiscalDayUpdated = {fiscal_day_updated}")
    print(f"    reconciliationMode = {reconciliation_mode}")
    print(f"    hash  = {sig['hash']}")
    url = client._get_url("CloseDay")
    resp = requests.post(
        url,
        json=payload,
        headers=client.headers,
        cert=(CERT_PATH, KEY_PATH),
        timeout=30,
    )
    body = resp.text
    try:
        body = resp.json()
    except Exception:
        pass
    print(f"    HTTP {resp.status_code}")
    return resp.status_code in (200, 201, 204), body, sig["hash"]



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client = ZimraClient(
        base_url=BASE_URL,
        device_id=DEVICE_ID,
        cert_path=CERT_PATH,
        key_path=KEY_PATH,
        device_model_name="Server",
        device_model_version="v1",
    )

    # ── STEP 0: GetConfig ────────────────────────────────────────────────────
    print("\n[0] GetConfig ...")
    try:
        cfg = client.get_config()
        pp("GetConfig response", cfg)
        applicable_taxes = cfg.get("applicableTaxes", [])
    except Exception as e:
        print(f"    GetConfig FAILED: {e}")
        sys.exit(1)

    if not applicable_taxes:
        print("    ERROR: No applicable taxes — cannot build a valid receipt.")
        sys.exit(1)

    tax         = applicable_taxes[0]
    tax_id      = tax.get("taxID")
    tax_percent = float(tax.get("taxPercent") or 0)
    tax_name    = tax.get("taxName", "")
    # GetConfig for this sandbox device does NOT return taxCode, so we derive:
    #   0%  → code "B" (zero-rated non-VAT per ZIMRA convention)
    tax_code    = tax.get("taxCode") or ("B" if tax_percent == 0 else "A")
    print(f"\n    Tax: {tax_name} ({tax_percent}%) ID={tax_id} code={tax_code}")

    # ── STEP 0b: GetStatus — resolve any stale open/failed day ───────────────
    print("\n[0b] GetStatus ...")
    try:
        status = get_status(client)
        pp("GetStatus response", status)
        fiscal_day_status  = status.get("fiscalDayStatus", "")
        last_receipt_no    = status.get("lastReceiptGlobalNo", 0)
        last_fiscal_day_no = status.get("lastFiscalDayNo", 0)
        closing_error      = status.get("fiscalDayClosingErrorCode", "")
        print(f"    status         : {fiscal_day_status}")
        print(f"    lastFiscalDayNo: {last_fiscal_day_no}")
        print(f"    lastReceiptNo  : {last_receipt_no}")
        if closing_error:
            print(f"    closingError   : {closing_error}")
    except Exception as e:
        print(f"    GetStatus FAILED: {e}")
        sys.exit(1)

    # If there's an open or failed day we must close it before opening a new one.
    stale_statuses = {"FiscalDayOpen", "FiscalDayCloseFailed"}
    if fiscal_day_status in stale_statuses:
        print(f"\n    Stale day detected ({fiscal_day_status}) — closing day {last_fiscal_day_no} first ...")

        # Build minimal empty counters for the stale day.
        # The stale day from the previous run had 1 receipt in USD at $10.00 with 0% tax.
        # We reconstruct the same counters — the server already accepted that receipt.
        stale_sale   = 10.00
        stale_tax    = 0.00
        stale_counters = [
            {
                "fiscalCounterType"     : "SaleByTax",
                "fiscalCounterCurrency" : "USD",
                "fiscalCounterTaxID"    : 513,
                "fiscalCounterTaxPercent": 0.0,
                "fiscalCounterValue"    : stale_sale,
            },
            {
                "fiscalCounterType"     : "BalanceByMoneyType",
                "fiscalCounterCurrency" : "USD",
                "fiscalCounterMoneyType": "Cash",
                "fiscalCounterValue"    : stale_sale,
            },
        ]
        stale_day_date = "2026-07-29" # The date Day 1 was actually opened
        ok, body, _ = close_day(client, last_fiscal_day_no, stale_day_date, stale_counters, last_receipt_no)
        pp("CloseDay (stale day) response", body)
        if not ok:
            print("    [ERROR] Could not close the stale day. Cannot continue.")
            sys.exit(1)

        # Poll until the server finishes processing the close (async on ZIMRA side).
        # FiscalDayCloseInitiated → FiscalDayClosed (success) or FiscalDayCloseFailed (error)
        print("    Polling for close confirmation (up to 30s) ...")
        transitional = {"FiscalDayCloseInitiated", "FiscalDayOpen"}
        new_status = ""
        closing_error2 = ""
        for attempt in range(10):
            time.sleep(3)
            status2 = get_status(client)
            new_status    = status2.get("fiscalDayStatus", "")
            closing_error2 = status2.get("fiscalDayClosingErrorCode", "")
            print(f"      [{attempt+1}/10] status={new_status}  error={closing_error2 or 'none'}")
            if new_status not in transitional:
                break

        pp("GetStatus (post-stale-close)", status2)

        if new_status == "FiscalDayClosed":
            print("    Stale day successfully closed.")
        elif new_status in stale_statuses:
            print("    [ERROR] Day still not closed after 30s. Check signature logic.")
            sys.exit(1)
        else:
            # FiscalDayCloseInitiated after 30s — ZIMRA server is slow but may still close.
            # Attempt OpenDay anyway; the server should allow it once processing finishes.
            print(f"    [WARN] Status still '{new_status}' after 30s — proceeding to OpenDay anyway.")


    # ── STEP 1: OpenDay ──────────────────────────────────────────────────────
    print("\n[1] OpenDay ...")
    opened_str = ts_now()
    try:
        od_result = client.open_day(opened_str)
        pp("OpenDay response", od_result)
        fiscal_day_no = od_result.get("fiscalDayNo")
        if not fiscal_day_no:
            print("    ERROR: No fiscalDayNo returned.")
            sys.exit(1)
        print(f"    fiscalDayNo = {fiscal_day_no}")
    except Exception as e:
        print(f"    OpenDay FAILED: {e}")
        sys.exit(1)

    # Wait 1 second so receipt timestamp is strictly after OpenDay timestamp (avoids RCPT014).
    time.sleep(1)

    # ── STEP 2: SubmitReceipt ────────────────────────────────────────────────
    print("\n[2] SubmitReceipt ...")

    sale_amount    = 10.00
    tax_amount     = 0.00          # 0% tax → no tax collected
    sales_with_tax = sale_amount   # tax-inclusive, all of it is the sale amount

    receipt_date = ts_now()

    # buyerData: mandatory per ZIMRA spec (RCPT043)
    buyer_data = {
        "buyerName": "Test Buyer",
        "buyerAddress": {
            "province": "Harare",
            "city":     "Harare",
            "street":   "1 Test Street",
            "houseNo":  "1",
            "district": "Harare CBD",
        },
        "buyerPhone": "+263771234567",
        "buyerEmail": "test@example.com",
    }

    receipt_payload = {
        "receiptType"             : "FISCALINVOICE",
        "receiptCurrency"         : "USD",
        "receiptCounter"          : 1,
        "receiptGlobalNo"         : 1,
        "invoiceNo"               : "TEST-E2E-002",
        "buyerData"               : buyer_data,
        "receiptNotes"            : "E2E clean-run sandbox test",
        "receiptDate"             : receipt_date,
        "receiptLinesTaxInclusive": True,
        "receiptLines"            : [
            {
                "receiptLineType"    : "Sale",
                "receiptLineNo"      : 1,
                "receiptLineHSCode"  : "",
                "receiptLineName"    : "Test Item",
                "receiptLinePrice"   : sale_amount,
                "receiptLineQuantity": 1,
                "taxID"              : tax_id,
                "receiptLineTotal"   : sale_amount,
            }
        ],
        "receiptTaxes"            : [
            {
                "taxID"             : tax_id,
                "taxPercent"        : tax_percent,
                "taxCode"           : tax_code,
                "salesAmountWithTax": sales_with_tax,
                "taxAmount"         : tax_amount,
            }
        ],
        "receiptPayments"         : [
            {
                "moneyTypeCode": "Cash",
                "paymentAmount": sale_amount,
            }
        ],
        "receiptTotal"            : sale_amount,
        "fiscalDayNo"             : fiscal_day_no,
    }

    print(f"    receipt_date  : {receipt_date}")
    print(f"    tax_id={tax_id}  percent={tax_percent}%  code={tax_code}")
    print(f"    sale={sale_amount}  tax={tax_amount}")

    try:
        sr_result = client.submit_receipt(receipt_payload, previous_hash="")
        pp("SubmitReceipt response", sr_result)
        receipt_counter = sr_result.get("receiptCounter", 1)
        receipt_clean   = check_validation_errors(sr_result, "SubmitReceipt")
        print(f"    receiptID={sr_result.get('receiptID')}  counter={receipt_counter}")
    except Exception as e:
        print(f"    SubmitReceipt FAILED: {e}")
        sys.exit(1)

    if not receipt_clean:
        print("\n    RED errors on SubmitReceipt — aborting before CloseDay.")
        sys.exit(1)

    # ── STEP 3: Build fiscalDayCounters ─────────────────────────────────────
    print("\n[3] Building fiscalDayCounters ...")
    fiscal_day_counters = [
        {
            "fiscalCounterType"      : "SaleByTax",
            "fiscalCounterCurrency"  : "USD",
            "fiscalCounterTaxID"     : tax_id,
            "fiscalCounterTaxPercent": tax_percent,
            "fiscalCounterValue"     : sales_with_tax,
        },
        {
            "fiscalCounterType"      : "SaleTaxByTax",
            "fiscalCounterCurrency"  : "USD",
            "fiscalCounterTaxID"     : tax_id,
            "fiscalCounterTaxPercent": tax_percent,
            "fiscalCounterValue"     : tax_amount,
        },
        {
            "fiscalCounterType"      : "BalanceByMoneyType",
            "fiscalCounterCurrency"  : "USD",
            "fiscalCounterMoneyType" : "Cash",
            "fiscalCounterValue"     : sale_amount,
        },
    ]
    fiscal_day_counters = [c for c in fiscal_day_counters if c.get("fiscalCounterValue", 0.0) != 0.0]

    for c in fiscal_day_counters:
        print(f"      {c}")

    # ── STEP 4: CloseDay with USD ────────────────────────────────────────────
    print("\n[4] CloseDay with 'USD' ...")
    ok_usd, resp_usd, hash_usd = close_day(
        client, fiscal_day_no, date_today(), fiscal_day_counters, receipt_counter
    )
    pp("CloseDay (USD) response", resp_usd)


    # ── STEP 5: GetStatus — confirm server accepted the close ─────────────────
    print("\n[5] GetStatus (post-CloseDay) — polling up to 30s ...")
    final_day_status = "Unknown"
    final_close_err  = ""
    transitional5    = {"FiscalDayCloseInitiated"}
    final_status     = {}
    for attempt in range(10):
        time.sleep(3)
        try:
            final_status     = get_status(client)
            final_day_status = final_status.get("fiscalDayStatus", "")
            final_close_err  = final_status.get("fiscalDayClosingErrorCode", "")
            print(f"      [{attempt+1}/10] status={final_day_status}  error={final_close_err or 'none'}")
            if final_day_status not in transitional5:
                break
        except Exception as e:
            print(f"    GetStatus FAILED: {e}")
            break

    pp("GetStatus (final)", final_status)
    print(f"    fiscalDayStatus: {final_day_status}")
    if final_close_err:
        print(f"    closingError   : {final_close_err}")


    # ── FINAL VERDICT ────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  FINAL VERDICT")
    print("="*60)

    server_confirmed_closed = (final_day_status == "FiscalDayClosed" and not final_close_err)
    http_ok                 = ok_usd

    if http_ok and server_confirmed_closed and receipt_clean:
        print("\n[PROVEN WORKING] Full clean run confirmed:")
        print("  - SubmitReceipt : zero RED validation errors")
        print("  - CloseDay      : HTTP 200")
        print(f"  - GetStatus     : {final_day_status} (no signature errors)")
        print("\n  CONCLUSION:")
        print("  'USD' is the correct fiscalCounterCurrency value.")
        print("  The 'USDL' in the PDF hash example is a documentation typo.")
        print("  The signature algorithm is correct (BadCertificateSignature resolved).")
    elif http_ok and not server_confirmed_closed:
        print("\n[SIGNATURE ISSUE] CloseDay returned HTTP 200 but server flagged:")
        print(f"  fiscalDayStatus={final_day_status}  error={final_close_err or 'none'}")
        print("  The signature or hash concatenation is still wrong.")
        print("  Check _generate_fiscal_day_signature() logic.")
    elif not http_ok:
        print("\n[FAIL] CloseDay was rejected (non-2xx HTTP).")
        print("  Check the response body above for the error detail.")
        print("  Consider retrying with USDL if the error mentions currency.")
    else:
        print(f"\n[PARTIAL] HTTP={http_ok}  server_closed={server_confirmed_closed}  receipt_clean={receipt_clean}")


if __name__ == "__main__":
    main()
