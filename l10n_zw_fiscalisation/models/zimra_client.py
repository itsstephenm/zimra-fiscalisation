import json
import requests
import logging

_logger = logging.getLogger(__name__)

class ZimraClient:
    """
    Decoupled ZIMRA FDMS API Client.
    This class handles all direct communication and cryptography with ZIMRA, 
    independent of Odoo logic.
    """
    def __init__(self, base_url, device_id, cert_path, key_path, device_model_name="Server", device_model_version="v1"):
        self.base_url = base_url.rstrip('/')
        self.device_id = device_id
        self.cert_path = cert_path
        self.key_path = key_path
        self.headers = {
            "Content-Type": "application/json",
            "DeviceModelName": device_model_name,
            "DeviceModelVersion": device_model_version,
        }

    def _get_url(self, endpoint):
        return f"{self.base_url}/Device/v1/{self.device_id}/{endpoint}"

    def get_config(self):
        """
        Retrieves taxpayers and device information and configuration.
        """
        url = self._get_url("GetConfig")
        try:
            response = requests.get(
                url, 
                headers=self.headers, 
                cert=(self.cert_path, self.key_path)
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error("ZIMRA GetConfig Error: %s - Response: %s", e, getattr(e.response, 'text', 'None'))
            raise e

    def open_day(self, fiscal_day_opened):
        """
        Opens a new fiscal day.
        fiscal_day_opened: ISO 8601 format date string (e.g. 2023-05-30T08:38:54)
        """
        url = self._get_url("OpenDay")
        payload = {
            "deviceID": int(self.device_id),
            "fiscalDayOpened": fiscal_day_opened
        }
        try:
            response = requests.post(
                url, 
                json=payload, 
                headers=self.headers, 
                cert=(self.cert_path, self.key_path)
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error("ZIMRA OpenDay Error: %s - Response: %s", e, getattr(e.response, 'text', 'None'))
            raise e

    def submit_receipt(self, receipt_data, previous_hash=""):
        """
        Submits a receipt to ZIMRA.
        Generates the hash and signature automatically before sending.
        """
        # Generate signature data
        signature_data = self._generate_signature(receipt_data, previous_hash)
        
        # Add to receipt
        receipt_data["receiptDeviceSignature"] = signature_data
        
        return self._post_receipt(receipt_data)

    def _post_receipt(self, receipt_data):
        """
        Posts a pre-signed receipt payload to ZIMRA.
        Used by the offline queue.
        """
        url = self._get_url("SubmitReceipt")
        payload = {
            "deviceID": int(self.device_id),
            "receipt": receipt_data
        }
        
        try:
            response = requests.post(
                url, 
                json=payload, 
                headers=self.headers, 
                cert=(self.cert_path, self.key_path)
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error("ZIMRA SubmitReceipt Error: %s - Response: %s", e, getattr(e.response, 'text', 'None'))
            raise e

    def _generate_signature(self, receipt_data, previous_hash=""):
        """
        Generates the ZIMRA-compliant hash and RSA signature.
        """
        import hashlib
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import serialization
        
        # 1. Extract required fields in order
        device_id = str(self.device_id)
        receipt_type = receipt_data.get("receiptType", "").upper()
        receipt_currency = receipt_data.get("receiptCurrency", "").upper()
        receipt_global_no = str(receipt_data.get("receiptGlobalNo", ""))
        receipt_date = receipt_data.get("receiptDate", "")
        
        # Format total to cents
        receipt_total_val = receipt_data.get("receiptTotal", 0.0)
        receipt_total = str(int(round(float(receipt_total_val) * 100)))
        
        # 2. Format taxes
        # Order by taxID ascending, then taxCode alphabetical
        taxes = receipt_data.get("receiptTaxes", [])
        
        def tax_sort_key(t):
            return (int(t.get("taxID", 0)), t.get("taxCode", ""))
            
        sorted_taxes = sorted(taxes, key=tax_sort_key)
        
        tax_str = ""
        for tax in sorted_taxes:
            code = tax.get("taxCode", "")
            
            # Format tax percent
            percent_val = tax.get("taxPercent")
            if percent_val is None:
                percent = "" # Exempt
            elif float(percent_val).is_integer():
                percent = f"{int(float(percent_val))}.00"
            else:
                percent = str(float(percent_val))
                
            # Amounts to cents
            tax_amt = str(int(round(float(tax.get("taxAmount", 0.0)) * 100)))
            sales_amt = str(int(round(float(tax.get("salesAmountWithTax", 0.0)) * 100)))
            
            tax_str += f"{code}{percent}{tax_amt}{sales_amt}"
            
        # 3. Concatenate all parts
        concatenated = f"{device_id}{receipt_type}{receipt_currency}{receipt_global_no}{receipt_date}{receipt_total}{tax_str}{previous_hash}"
        
        # 4. Generate SHA256 Hash
        hash_obj = hashlib.sha256(concatenated.encode('utf-8'))
        hash_digest = hash_obj.digest()
        hash_base64 = base64.b64encode(hash_digest).decode('utf-8')
        
        # 5. Generate RSA Signature
        with open(self.key_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
            )
            
        # PDF states: Signature = RSA(x1||...||xn, d, n)
        # Using PKCS1v15 padding as per ZIMRA standard for SHA256withRSA
        signature = private_key.sign(
            concatenated.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        signature_base64 = base64.b64encode(signature).decode('utf-8')
        
        return {
            "hash": hash_base64,
            "signature": signature_base64
        }

    def _generate_fiscal_day_signature(
        self,
        fiscal_day_no,
        fiscal_day_date,
        fiscal_day_counters,
    ):
        """
        Generates the ZIMRA-compliant hash and RSA signature for a Fiscal Day Close.

        Concatenation order per ZIMRA FDMS API Spec v7.2 §13.3.1:
          1. deviceID
          2. fiscalDayNo
          3. fiscalDayDate       (YYYY-MM-DD)
          4. fiscalDayCounters   (concatenated counter string)
        """
        import hashlib
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import serialization

        device_id = str(self.device_id)
        fiscal_day_no_str = str(fiscal_day_no)

        # ── Build counter string ─────────────────────────────────────────────
        # Sort counters: Type (enum order), TaxID asc, Currency asc, MoneyType (enum order)
        counter_type_enum = {
            "SALEBYTAX": 0,
            "SALETAXBYTAX": 1,
            "CREDITNOTEBYTAX": 2,
            "CREDITNOTETAXBYTAX": 3,
            "DEBITNOTEBYTAX": 4,
            "DEBITNOTETAXBYTAX": 5,
            "BALANCEBYMONEYTYPE": 6,
        }

        def counter_sort_key(c):
            type_val = c.get("fiscalCounterType", "").upper()
            money_enum = {
                "CASH": 0,
                "CARD": 1,
                "MOBILEWALLET": 2,
                "COUPON": 3,
                "CREDIT": 4,
                "BANKTRANSFER": 5,
                "OTHER": 6,
            }
            return (
                counter_type_enum.get(type_val, 99),
                int(c.get("fiscalCounterTaxID", 0)),
                money_enum.get(c.get("fiscalCounterMoneyType", "").upper(), 99),
                c.get("fiscalCounterCurrency", "").upper(),
            )

        sorted_counters = sorted(fiscal_day_counters, key=counter_sort_key)

        counters_str = ""
        for c in sorted_counters:
            c_type = c.get("fiscalCounterType", "").upper()
            c_curr = c.get("fiscalCounterCurrency", "").upper()

            c_tax_percent = ""
            if "fiscalCounterTaxPercent" in c:
                percent_val = c.get("fiscalCounterTaxPercent")
                c_tax_percent = f"{float(percent_val):.2f}"
            elif "fiscalCounterMoneyType" in c:
                c_tax_percent = c.get("fiscalCounterMoneyType", "").upper()

            c_val_str = str(int(round(float(c.get("fiscalCounterValue", 0.0)) * 100)))

            counters_str += f"{c_type}{c_curr}{c_tax_percent}{c_val_str}"

        # ── Concatenate in spec order ────────────────────────────────────────
        concatenated = (
            f"{device_id}"
            f"{fiscal_day_no_str}"
            f"{fiscal_day_date}"
            f"{counters_str}"
        )

        # ── SHA-256 hash ─────────────────────────────────────────────────────
        hash_obj = hashlib.sha256(concatenated.encode("utf-8"))
        hash_digest = hash_obj.digest()
        hash_base64 = base64.b64encode(hash_digest).decode("utf-8")

        # ── RSA-PKCS1v15 signature ───────────────────────────────────────────
        with open(self.key_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
            )

        signature = private_key.sign(
            concatenated.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        signature_base64 = base64.b64encode(signature).decode("utf-8")

        return {
            "hash": hash_base64,
            "signature": signature_base64,
        }

