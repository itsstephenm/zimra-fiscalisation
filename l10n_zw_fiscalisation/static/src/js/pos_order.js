/** @odoo-module **/

import { Order } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

patch(Order.prototype, {
    export_for_printing() {
        const receipt = super.export_for_printing(...arguments);
        
        // Inject ZIMRA fields if they are present on the order
        // Note: These fields will only be present if the order has been synced 
        // to the backend and the backend has assigned the global receipt number.
        if (this.l10n_zw_receipt_global_no) {
            receipt.l10n_zw_receipt_global_no = this.l10n_zw_receipt_global_no;
            receipt.l10n_zw_qr_url = this.l10n_zw_qr_url;
            receipt.l10n_zw_device_id = this.pos.company.l10n_zw_device_id;
        }
        
        return receipt;
    }
});
