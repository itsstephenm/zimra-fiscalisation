import os
import json
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID
from cryptography import x509

# Configuration - Corrected to match your ZIMRA portal registration
DEVICE_ID = 37988
ACTIVATION_KEY = "00868489"
SERIAL_NO = "VASTSOL-TEST-004"

BASE_URL = "https://fdmsapitest.zimra.co.zw"
REGISTER_URL = f"{BASE_URL}/Public/v1/{DEVICE_ID}/RegisterDevice"

# Corrected Headers to match ZIMRA specs
HEADERS = {
    "Content-Type": "application/json",
    "DeviceModelName": "Virtual Server",
    "DeviceModelVersionNo": "v1"
}

def generate_keys_and_csr():
    print("Generating RSA 2048 private key...")
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Save private key securely - adjusting path to go up one level so certs are in the module root
    cert_dir = "/mnt/extra-addons/l10n_zw_fiscalisation/certs"
    os.makedirs(cert_dir, exist_ok=True)
    
    key_path = os.path.join(cert_dir, "private_key.pem")
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    print(f"Private key saved to {key_path}")

    print("Generating CSR...")
    padded_device_id = str(DEVICE_ID).zfill(10)
    cn = f"ZIMRA-{SERIAL_NO}-{padded_device_id}"
    print(f"Using Common Name (CN): {cn}")

    builder = x509.CertificateSigningRequestBuilder()
    builder = builder.subject_name(x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"ZW"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Zimbabwe Revenue Authority"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Zimbabwe"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ]))

    csr = builder.sign(private_key, hashes.SHA256())
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode('utf-8')

    csr_path = os.path.join(cert_dir, "device_csr.pem")
    with open(csr_path, "w") as f:
        f.write(csr_pem)
    print(f"CSR saved to {csr_path}")
    
    return csr_pem, cert_dir

def register_device(csr_pem, cert_dir):
    print(f"Sending registration request to {REGISTER_URL}...")
    
    payload = {
        "deviceID": DEVICE_ID,
        "activationKey": ACTIVATION_KEY,
        "certificateRequest": csr_pem
    }

    try:
        response = requests.post(REGISTER_URL, json=payload, headers=HEADERS)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("Registration Successful!")
            print(f"Operation ID: {data.get('operationID')}")
            
            certificate_pem = data.get('certificate')
            if certificate_pem:
                cert_path = os.path.join(cert_dir, "device_cert.pem")
                with open(cert_path, "w") as f:
                    f.write(certificate_pem)
                print(f"Saved ZIMRA official certificate to {cert_path}")
            else:
                print("Warning: No certificate returned in response.")
        else:
            print("Registration Failed!")
            try:
                print(json.dumps(response.json(), indent=2))
            except Exception:
                print(response.text)
                
            if response.status_code == 404:
                print("\nSuggestion: The endpoint URL might be different. Let's check Swagger.")
                
    except Exception as e:
        print(f"Error during API request: {e}")

if __name__ == "__main__":
    csr, cert_dir = generate_keys_and_csr()
    register_device(csr, cert_dir)