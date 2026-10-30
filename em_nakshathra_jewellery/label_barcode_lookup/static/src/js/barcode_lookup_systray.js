/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class BarcodeLookupSystray extends Component {
    static template = "label_barcode_lookup.BarcodeLookupSystray";
    static props = {};

    setup() {
        this.actionService = useService("action");
    }

    async onClick() {
        await this.actionService.doAction("label_barcode_lookup.action_label_barcode_lookup_wizard");
    }
}

export const barcodeLookupSystrayItem = {
    Component: BarcodeLookupSystray,
    isDisplayed(env) {
        try {
            const menuService = env.services.menu;
            const currentApp = menuService ? menuService.getCurrentApp() : null;
            if (currentApp) {
                return currentApp.xmlid === "sale.sale_menu_root" || currentApp.name === "Sales";
            }
            const hash = window.location.hash || "";
            return hash.includes("action=sale.") || hash.includes("model=sale.");
        } catch (e) {
            return false;
        }
    },
};

// Sequence 26 places it immediately before messaging_menu (which is sequence 25 in ascending, reversed)
registry.category("systray").add("label_barcode_lookup.systray", barcodeLookupSystrayItem, { sequence: 26 });
