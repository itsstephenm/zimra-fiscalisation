import importlib.util, pathlib, json, requests, time

_spec = importlib.util.spec_from_file_location('zimra_client', pathlib.Path('l10n_zw_fiscalisation/models/zimra_client.py'))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ZimraClient = _mod.ZimraClient

client = ZimraClient('https://fdmsapitest.zimra.co.zw', 36915, 'certs/device_cert.pem', 'certs/private_key.pem')
url_status = client._get_url('GetStatus')

for i in range(8):
    time.sleep(4)
    s = requests.get(url_status, headers=client.headers, cert=('certs/device_cert.pem', 'certs/private_key.pem'), timeout=15).json()
    status = s.get('fiscalDayStatus')
    err = s.get('fiscalDayClosingErrorCode', 'none')
    print(f'[{i+1}/8] {status}  err={err}')
    if status not in ('FiscalDayCloseInitiated', 'FiscalDayOpen'):
        print(json.dumps(s, indent=2))
        break
