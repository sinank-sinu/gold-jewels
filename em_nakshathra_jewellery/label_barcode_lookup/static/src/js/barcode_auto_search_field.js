/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { useEffect, useRef, useExternalListener } from "@odoo/owl";

export class BarcodeAutoSearchField extends CharField {
    setup() {
        super.setup();
        this.input = useRef("input");
        let lastKeyTime = 0;
        let isScanner = false;
        let scanTimer = null;
        let isSearching = false;

        const triggerSearch = async () => {
            if (isSearching || !this.input.el) {
                return;
            }
            const val = (this.input.el.value || "").trim();
            if (!val) {
                return;
            }

            isSearching = true;

            try {
                // Ensure field value is committed to the frontend record model
                this.input.el.dispatchEvent(new Event("change", { bubbles: true }));
                await this.props.record.update({ [this.props.name]: val });
            } catch (err) {
                // If update is already pending or handled, proceed to click
            }

            // Immediately clear the input value so that the searched barcode is removed from view
            if (this.input.el) {
                this.input.el.value = "";
            }

            // Click the hidden Search button to execute server search and reload details
            const root = this.input.el.closest(".o_form_view, .modal-content, form") || document;
            const searchBtn = root.querySelector('button[name="action_search_barcode"]');
            if (searchBtn) {
                searchBtn.click();
            }

            setTimeout(() => {
                if (this.input.el) {
                    this.input.el.value = "";
                    this.input.el.focus();
                }
                isSearching = false;
            }, 500);
        };

        const onKeyDown = (ev) => {
            const now = Date.now();
            const timeDiff = now - lastKeyTime;
            lastKeyTime = now;

            // Scanner gun fires characters rapidly (under 60ms between characters)
            if (timeDiff < 60) {
                isScanner = true;
            }

            // If Enter key is pressed (typical scanner gun suffix or keyboard Enter)
            if (ev.key === "Enter" || ev.keyCode === 13) {
                ev.preventDefault();
                ev.stopPropagation();
                clearTimeout(scanTimer);
                triggerSearch();
                return;
            }

            // If scanner typed characters rapidly without sending Enter, trigger after typing pauses
            clearTimeout(scanTimer);
            scanTimer = setTimeout(() => {
                if (isScanner && this.input.el) {
                    const currentVal = this.input.el.value.trim();
                    if (currentVal.length >= 2) {
                        isScanner = false;
                        triggerSearch();
                        return;
                    }
                }
                isScanner = false;
            }, 250);
        };

        const onPaste = () => {
            clearTimeout(scanTimer);
            scanTimer = setTimeout(() => {
                triggerSearch();
            }, 100);
        };

        const onFocus = () => {
            if (this.input.el) {
                this.input.el.select();
            }
        };

        // If user scans while dialog is open but clicked outside the input
        useExternalListener(window, "keydown", (ev) => {
            if (!this.input.el) return;
            const active = document.activeElement;
            if (active !== this.input.el) {
                const tag = active?.tagName?.toLowerCase();
                if (tag !== "input" && tag !== "textarea") {
                    const modal = this.input.el.closest(".modal");
                    if (modal && modal.classList.contains("show")) {
                        this.input.el.focus();
                    }
                }
            }
        });

        useEffect(
            (inputEl) => {
                if (inputEl) {
                    // Auto-focus and auto-select on mount/update so next scan replaces previous barcode
                    setTimeout(() => {
                        if (inputEl) {
                            inputEl.focus();
                            inputEl.select();
                        }
                    }, 80);

                    inputEl.addEventListener("keydown", onKeyDown, true);
                    inputEl.addEventListener("paste", onPaste, true);
                    inputEl.addEventListener("focus", onFocus, true);

                    return () => {
                        inputEl.removeEventListener("keydown", onKeyDown, true);
                        inputEl.removeEventListener("paste", onPaste, true);
                        inputEl.removeEventListener("focus", onFocus, true);
                        clearTimeout(scanTimer);
                    };
                }
            },
            () => [this.input.el]
        );
    }
}

export const barcodeAutoSearchField = {
    ...charField,
    component: BarcodeAutoSearchField,
    displayName: _t("Barcode Auto Search"),
};

registry.category("fields").add("barcode_auto_search", barcodeAutoSearchField);
