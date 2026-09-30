/** @odoo-module **/

import { WarningDialog } from "@web/core/errors/error_dialogs";
import { patch } from "@web/core/utils/patch";
import { markup } from "@odoo/owl";

patch(WarningDialog.prototype, {
    setup() {
        super.setup();
        if (this.message && (this.message.includes("<span") || this.message.includes("<div") || this.message.includes("<br") || this.message.includes("style="))) {
            this.message = markup(this.message);
        }
    },
});
