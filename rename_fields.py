import os

directory = 'c:/Users/Stephen J Muregwi/Documents/GitHub/zimra-fiscalisation/l10n_zw_fiscalisation'

# Fields to rename
renames = [
    ('zimra_base_url', 'l10n_zw_base_url'),
    ('zimra_device_id', 'l10n_zw_device_id'),
    ('zimra_serial_no', 'l10n_zw_serial_no'),
    ('zimra_activation_key', 'l10n_zw_activation_key'),
    ('zimra_device_model_name', 'l10n_zw_device_model_name'),
    ('zimra_device_model_version', 'l10n_zw_device_model_version'),
    ('zimra_cert_path', 'l10n_zw_cert_path'),
    ('zimra_key_path', 'l10n_zw_key_path'),
    ('zimra_fiscal_day_status', 'l10n_zw_fiscal_day_status'),
    ('zimra_fiscal_day_no', 'l10n_zw_fiscal_day_no'),
    ('zimra_fiscal_day_opened', 'l10n_zw_fiscal_day_opened'),
    ('zimra_receipt_counter', 'l10n_zw_receipt_counter'),
    ('zimra_last_receipt_hash', 'l10n_zw_last_receipt_hash'),
    ('zimra_increment_receipt_counter', 'l10n_zw_increment_receipt_counter'),
    ('zimra_tax_id', 'l10n_zw_tax_id'),
    ('zimra_tax_code', 'l10n_zw_tax_code'),
    ('zimra_receipt_id', 'l10n_zw_receipt_id'),
    ('zimra_operation_id', 'l10n_zw_operation_id'),
    ('zimra_receipt_global_no', 'l10n_zw_receipt_global_no'),
    ('zimra_status', 'l10n_zw_status'),
    ('zimra_error_message', 'l10n_zw_error_message'),
    ('zimra_qr_url', 'l10n_zw_qr_url'),
]

for root, dirs, files in os.walk(directory):
    for file in files:
        if file.endswith('.py') or file.endswith('.xml'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r') as f:
                content = f.read()
            
            new_content = content
            for old, new in renames:
                new_content = new_content.replace(old, new)
                
            if content != new_content:
                with open(filepath, 'w') as f:
                    f.write(new_content)
                print(f"Updated {filepath}")
