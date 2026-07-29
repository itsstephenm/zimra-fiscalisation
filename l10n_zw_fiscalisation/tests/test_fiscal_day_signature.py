import unittest
import hashlib
import base64
import json
from unittest.mock import patch, mock_open

# Mock the serialization and keys since we only care about the SHA-256 hash part of the device signature
# The actual RSA signature requires the exact private key from ZIMRA, which we don't have.
# The PDF provides the exact SHA-256 hash in base64 format.

class TestZimraFiscalDaySignature(unittest.TestCase):
    
    def test_fiscal_day_hash_generation(self):
        """
        Tests the fiscal day hash generation against the exact example provided in 
        ZIMRA FDMS API Specification v7.2, Section 13.3.1 (Page 76).
        """
        device_id = "321"
        fiscal_day_no = 84
        fiscal_day_date = "2019-09-23"
        
        # Note: The PDF example for BalanceByMoneyType USD CASH 37,00
        # contains a typo in its "Result used for hash generation" where it uses "USDL" instead of "USD".
        # We use "USDL" here to ensure byte-for-byte matching with the official ZIMRA documentation hash.
        fiscal_day_counters = [
            {"fiscalCounterType": "SaleByTax", "fiscalCounterCurrency": "ZWL", "fiscalCounterTaxID": 1, "fiscalCounterValue": 23000.00},
            {"fiscalCounterType": "SaleByTax", "fiscalCounterCurrency": "ZWL", "fiscalCounterTaxID": 2, "fiscalCounterTaxPercent": 0, "fiscalCounterValue": 12000.00},
            {"fiscalCounterType": "SaleByTax", "fiscalCounterCurrency": "USD", "fiscalCounterTaxID": 3, "fiscalCounterTaxPercent": 14.5, "fiscalCounterValue": 25.00},
            {"fiscalCounterType": "SaleByTax", "fiscalCounterCurrency": "ZWL", "fiscalCounterTaxID": 4, "fiscalCounterTaxPercent": 15, "fiscalCounterValue": 12.00},
            {"fiscalCounterType": "SaleTaxByTax", "fiscalCounterCurrency": "USD", "fiscalCounterTaxID": 3, "fiscalCounterTaxPercent": 15, "fiscalCounterValue": 2.50},
            {"fiscalCounterType": "SaleTaxByTax", "fiscalCounterCurrency": "ZWL", "fiscalCounterTaxID": 4, "fiscalCounterTaxPercent": 15, "fiscalCounterValue": 2300.00},
            {"fiscalCounterType": "BalanceByMoneyType", "fiscalCounterCurrency": "ZWL", "fiscalCounterMoneyType": "CARD", "fiscalCounterValue": 15000.00},
            {"fiscalCounterType": "BalanceByMoneyType", "fiscalCounterCurrency": "USDL", "fiscalCounterMoneyType": "CASH", "fiscalCounterValue": 37.00},
            {"fiscalCounterType": "BalanceByMoneyType", "fiscalCounterCurrency": "ZWL", "fiscalCounterMoneyType": "CASH", "fiscalCounterValue": 20000.00},
        ]
        
        # We'll use the logic directly from zimra_client.py's _generate_fiscal_day_signature
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
                "OTHER": 6
            }
            return (
                counter_type_enum.get(type_val, 99),
                int(c.get("fiscalCounterTaxID", 0)),
                c.get("fiscalCounterCurrency", "").upper(),
                money_enum.get(c.get("fiscalCounterMoneyType", "").upper(), 99)
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
            
        concatenated = f"{device_id}{fiscal_day_no}{fiscal_day_date}{counters_str}"
        
        # The exact string expected by ZIMRA PDF
        expected_concatenated = "321842019-09-23SALEBYTAXZWL2300000SALEBYTAXZWL0.001200000SALEBYTAXUSD14.502500SALEBYTAXZWL15.001200SALETAXBYTAXUSD15.00250SALETAXBYTAXZWL15.00230000BALANCEBYMONEYTYPEUSDLCASH3700BALANCEBYMONEYTYPEZWLCASH2000000BALANCEBYMONEYTYPEZWLCARD1500000"
        
        self.assertEqual(concatenated, expected_concatenated, "Concatenated string does not match exactly")
        
        hash_obj = hashlib.sha256(concatenated.encode('utf-8'))
        hash_digest = hash_obj.digest()
        hash_base64 = base64.b64encode(hash_digest).decode('utf-8')
        
        expected_hash_base64 = "OdT8lLI0JXhXl1XQgr64Zb1ltFDksFXThVxqM6O8xZE="
        
        self.assertEqual(hash_base64, expected_hash_base64, "Generated SHA-256 base64 hash does not match exactly")

if __name__ == '__main__':
    unittest.main()
