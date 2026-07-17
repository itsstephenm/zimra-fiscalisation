import os
from l10n_zw_fiscalisation.models.zimra_client import ZimraClient

DEVICE_ID = 36915
BASE_URL = "https://fdmsapitest.zimra.co.zw"
CERT_PATH = "certs/device_cert.pem"
KEY_PATH = "certs/private_key.pem"

def main():
    if not os.path.exists(CERT_PATH) or not os.path.exists(KEY_PATH):
        print("Error: Certificates not found in certs/ directory.")
        return

    client = ZimraClient(
        base_url=BASE_URL,
        device_id=DEVICE_ID,
        cert_path=CERT_PATH,
        key_path=KEY_PATH
    )

    print("--- Testing GetConfig ---")
    try:
        config = client.get_config()
        print("Successfully retrieved configuration!")
        print("Taxpayer Name:", config.get("taxPayerName"))
        print("TIN:", config.get("taxPayerTIN"))
        print("VAT Number:", config.get("vatNumber"))
        print("Max Fiscal Day (Hrs):", config.get("taxPayerDayMaxHrs"))
        print("Applicable Taxes:")
        for tax in config.get("applicableTaxes", []):
            print(f" - {tax.get('taxName')} ({tax.get('taxPercent')}%) ID: {tax.get('taxID')}")
    except Exception as e:
        print("GetConfig failed.")
        
if __name__ == "__main__":
    main()
