import hashlib
import base64

def test_zimra_hash():
    device_id = "321"
    receipt_type = "FISCALINVOICE"
    receipt_currency = "ZWL"
    receipt_global_no = "432"
    receipt_date = "2019-09-19T15:43:12"
    
    # 9450,00 to cents
    receipt_total = "945000"
    
    # Taxes from example
    taxes = [
        {"taxID": 1, "taxCode": "A", "taxPercent": None, "taxAmount": 0.00, "salesAmountWithTax": 2500.00},
        {"taxID": 2, "taxCode": "B", "taxPercent": 0, "taxAmount": 0.00, "salesAmountWithTax": 3500.00},
        {"taxID": 3, "taxCode": "C", "taxPercent": 15, "taxAmount": 150.00, "salesAmountWithTax": 1150.00},
        {"taxID": 3, "taxCode": "D", "taxPercent": 15, "taxAmount": 300.00, "salesAmountWithTax": 2300.00},
    ]
    
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
        
    previous_hash = "hNVJXP/ACOiE8McD3pKsDlqBXpuaUqQOfPnMyfZWI9k="
    
    concatenated = f"{device_id}{receipt_type}{receipt_currency}{receipt_global_no}{receipt_date}{receipt_total}{tax_str}{previous_hash}"
    
    expected_string = "321FISCALINVOICEZWL4322019-09-19T15:43:12945000A0250000B0.000350000C15.0015000115000D15.0030000230000hNVJXP/ACOiE8McD3pKsDlqBXpuaUqQOfPnMyfZWI9k="
    
    print("Generated:", concatenated)
    print("Expected: ", expected_string)
    print("Match?    ", concatenated == expected_string)
    
    # Generate SHA256 Hash
    hash_obj = hashlib.sha256(concatenated.encode('utf-8'))
    hash_digest = hash_obj.digest()
    hash_base64 = base64.b64encode(hash_digest).decode('utf-8')
    
    expected_hash = "zDxEalWUpwX2BcsYxRUAEfY/13OaCrTwDt01So3a6uU="
    print("\nHash Gen: ", hash_base64)
    print("Hash Exp: ", expected_hash)
    print("Hash Match?", hash_base64 == expected_hash)

if __name__ == "__main__":
    test_zimra_hash()
