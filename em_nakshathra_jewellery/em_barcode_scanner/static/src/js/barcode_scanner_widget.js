/** @odoo-module **/

/**
 * BarcodeFieldWidget
 *
 * A Field Widget (not a standalone Component) registered under
 * "barcode_scanner_field".  This is how we embed the BarcodeScannerWidget
 * OWL component inside an Odoo 17 form view via:
 *
 *   <widget name="barcode_scanner" model="jewellery.receive.voucher"/>
 *
 * Odoo 17 form views support <widget name="..."> for non-field components.
 * We register this in the "view_widgets" category.
 */

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

class BarcodeScannerFormWidget extends Component {
    static template = "em_barcode_scanner.BarcodeScannerWidget";

    // Props injected by Odoo's widget infrastructure
    static props = {
        // Standard Odoo widget props
        record: { type: Object },
        slots: { type: Object, optional: true },
        // custom prop declared on the widget node: model="..."
        model: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.inputRef = useRef("barcodeInput");

        this.state = useState({
            barcode: "",
            isScanning: false,
            lastResult: "",
        });

        onMounted(() => {
            if (this.inputRef.el) {
                this.inputRef.el.focus();
            }
        });
    }

    get recordId() {
        return this.props.record.resId || null;
    }

    get modelName() {
        // Prefer explicit prop, then fall back to record's model
        return this.props.model || this.props.record.resModel;
    }

    async onKeyDown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            ev.stopPropagation();
            await this._processBarcode();
        }
    }

    onInput(ev) {
        this.state.barcode = ev.target.value;
    }

    async _processBarcode() {
        const barcode = (this.state.barcode || "").trim();
        if (!barcode) return;

        if (!this.recordId) {
            this.notification.add(
                _t("Please save the voucher first before scanning."),
                { type: "warning", sticky: false }
            );
            return;
        }

        this.state.isScanning = true;
        this.state.lastResult = "";

        try {
            const result = await this.orm.call(
                this.modelName,
                "action_scan_barcode",
                [this.recordId, barcode]
            );

            if (result.error) {
                this.state.lastResult = `❌ ${result.error}`;
                this.notification.add(result.error, {
                    type: "danger",
                    sticky: false,
                });
            } else {
                const msg = _t("✅ Added: %s", result.product);
                this.state.lastResult = msg;
                this.notification.add(
                    _t("Scanned successfully: %s", result.product),
                    { type: "success", sticky: false }
                );
                // Reload the record so the new line appears in the list
                await this.props.record.load();
            }
        } catch (error) {
            const msg = _t("Scan error: %s", error.message || String(error));
            this.state.lastResult = `❌ ${msg}`;
            this.notification.add(msg, { type: "danger", sticky: false });
        } finally {
            this.state.isScanning = false;
            this.state.barcode = "";
            if (this.inputRef.el) {
                this.inputRef.el.value = "";
                this.inputRef.el.focus();
            }
        }
    }
}

// Register as a view widget (used via <widget name="barcode_scanner"/> in form view)
registry.category("view_widgets").add("barcode_scanner", {
    component: BarcodeScannerFormWidget,
    // extractProps maps XML attrs into component props
    extractProps({ attrs }) {
        return {
            model: attrs.model || "",
        };
    },
});
