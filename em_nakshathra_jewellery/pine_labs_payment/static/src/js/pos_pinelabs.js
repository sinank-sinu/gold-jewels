/** @odoo-module */

import { Payment } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

/**
 * Patch the POS Payment model to serialise/deserialise Pine Labs fields.
 * These are stored in the order and included on the receipt.
 */
patch(Payment.prototype, {
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        if (this.payment_method?.use_payment_terminal === "pine_labs") {
            this.pinelabs_txn_ref = json.pinelabs_txn_ref || "";
            this.pinelabs_approval_code = json.pinelabs_approval_code || "";
            this.pinelabs_card_type = json.pinelabs_card_type || "";
            this.pinelabs_payment_mode = json.pinelabs_payment_mode || "";
            this.pinelabs_rrn = json.pinelabs_rrn || "";
            this.pinelabs_issuer_bank = json.pinelabs_issuer_bank || "";
        }
    },
    export_as_JSON() {
        const result = super.export_as_JSON(...arguments);
        if (result && this.payment_method?.use_payment_terminal === "pine_labs") {
            return Object.assign(result, {
                pinelabs_txn_ref: this.pinelabs_txn_ref || "",
                pinelabs_approval_code: this.pinelabs_approval_code || "",
                pinelabs_card_type: this.pinelabs_card_type || "",
                pinelabs_payment_mode: this.pinelabs_payment_mode || "",
                pinelabs_rrn: this.pinelabs_rrn || "",
                pinelabs_issuer_bank: this.pinelabs_issuer_bank || "",
            });
        }
        return result;
    },
});
