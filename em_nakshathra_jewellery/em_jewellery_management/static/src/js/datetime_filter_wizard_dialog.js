/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { SearchBarMenu } from "@web/search/search_bar_menu/search_bar_menu";
import { patch } from "@web/core/utils/patch";
import { Component, useState } from "@odoo/owl";
import { Domain } from "@web/core/domain";

const { DateTime } = luxon;

export class DateTimeFilterWizardDialog extends Component {
    static template = "em_jewellery_management.DateTimeFilterWizardDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        fields: Array,
        onApply: Function,
    };

    setup() {
        this.state = useState({
            fieldName: this.props.fields[0]?.name || "date",
            from: "",
            to: "",
            error: "",
        });
    }

    setPreset(preset) {
        this.state.error = "";
        const now = new Date();
        const formatDate = (d) => {
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, "0");
            const day = String(d.getDate()).padStart(2, "0");
            return `${y}-${m}-${day}`;
        };

        if (preset === "today") {
            const todayStr = formatDate(now);
            this.state.from = `${todayStr}T00:00`;
            this.state.to = `${todayStr}T23:59`;
        } else if (preset === "yesterday") {
            const yesterday = new Date(now);
            yesterday.setDate(yesterday.getDate() - 1);
            const yestStr = formatDate(yesterday);
            this.state.from = `${yestStr}T00:00`;
            this.state.to = `${yestStr}T23:59`;
        } else if (preset === "this_week") {
            const firstDayOfWeek = new Date(now);
            const dayIndex = (firstDayOfWeek.getDay() + 6) % 7; // Monday = 0
            firstDayOfWeek.setDate(firstDayOfWeek.getDate() - dayIndex);
            this.state.from = `${formatDate(firstDayOfWeek)}T00:00`;
            this.state.to = `${formatDate(now)}T23:59`;
        } else if (preset === "clear") {
            this.state.from = "";
            this.state.to = "";
        }
    }

    onApply() {
        const { fieldName, from, to } = this.state;
        if (!from && !to) {
            this.state.error = "Please choose a From or To date & time.";
            return;
        }

        if (from && to && from > to) {
            this.state.error = "From date & time cannot be after To date & time.";
            return;
        }

        const selectedField = this.props.fields.find((f) => f.name === fieldName) || this.props.fields[0];
        const fieldLabel = selectedField?.string || fieldName;
        const isDatetime = selectedField?.type === "datetime";

        const domain = [];
        let desc = "";

        if (isDatetime) {
            let fromUtc = "";
            let toUtc = "";
            let fromDisplay = "";
            let toDisplay = "";

            if (from) {
                const dtFrom = DateTime.fromISO(from);
                fromUtc = dtFrom.setZone("utc").toFormat("yyyy-MM-dd HH:mm:ss");
                fromDisplay = dtFrom.toFormat("dd/MM/yyyy HH:mm");
                domain.push([fieldName, ">=", fromUtc]);
            }
            if (to) {
                const dtTo = DateTime.fromISO(to);
                toUtc = dtTo.setZone("utc").toFormat("yyyy-MM-dd HH:mm:ss");
                toDisplay = dtTo.toFormat("dd/MM/yyyy HH:mm");
                domain.push([fieldName, "<=", toUtc]);
            }

            if (from && to) {
                desc = `${fieldLabel}: ${fromDisplay} - ${toDisplay}`;
            } else if (from) {
                desc = `${fieldLabel} >= ${fromDisplay}`;
            } else if (to) {
                desc = `${fieldLabel} <= ${toDisplay}`;
            }
        } else {
            const fromDate = from ? from.split("T")[0] : null;
            const toDate = to ? to.split("T")[0] : null;

            if (fromDate) domain.push([fieldName, ">=", fromDate]);
            if (toDate) domain.push([fieldName, "<=", toDate]);

            const fromDisplay = fromDate ? DateTime.fromISO(fromDate).toFormat("dd/MM/yyyy") : "";
            const toDisplay = toDate ? DateTime.fromISO(toDate).toFormat("dd/MM/yyyy") : "";

            if (fromDate && toDate) {
                desc = `${fieldLabel}: ${fromDisplay} - ${toDisplay}`;
            } else if (fromDate) {
                desc = `${fieldLabel} >= ${fromDisplay}`;
            } else if (toDate) {
                desc = `${fieldLabel} <= ${toDisplay}`;
            }
        }

        this.props.onApply(domain, desc);
        this.props.close();
    }
}

const isDateTimeWizardItem = (item) => {
    if (!item) return false;
    if (item.isDateTimeFilter) return true;
    if (item.invisible === "True" || item.invisible === true) return true;
    const desc = item.description || "";
    return (
        /\b\d{2}\/\d{2}\/\d{4}/.test(desc) &&
        (desc.includes("<=") || desc.includes(">=") || desc.includes(" - ") || desc.includes(":"))
    );
};

patch(SearchBarMenu.prototype, {
    get isOldGoldPurchase() {
        return ["old.gold.purchase", "sale.old.gold.line"].includes(
            this.env.searchModel?.resModel
        );
    },

    setup() {
        super.setup(...arguments);
        if (this.isOldGoldPurchase) {
            const searchItems = this.env.searchModel?.searchItems || {};
            for (const [id, item] of Object.entries(searchItems)) {
                if (isDateTimeWizardItem(item)) {
                    item.isDateTimeFilter = true;
                    item.invisible = "True";
                }
            }
        }
    },

    get filterItems() {
        if (!this.isOldGoldPurchase) {
            return super.filterItems;
        }
        return (super.filterItems || []).filter((item) => !isDateTimeWizardItem(item));
    },

    get availableDateTimeFields() {
        if (!this.isOldGoldPurchase) {
            return [];
        }
        const fields = [];
        const searchFields = this.env.searchModel?.searchViewFields || {};
        for (const [name, field] of Object.entries(searchFields)) {
            if (field.type === "datetime" || field.type === "date") {
                fields.push({
                    name,
                    string: field.string || name,
                    type: field.type,
                });
            }
        }

        // Prioritize 'date', then 'create_date', then others alphabetically
        fields.sort((a, b) => {
            if (a.name === "date") return -1;
            if (b.name === "date") return 1;
            if (a.name === "create_date") return -1;
            if (b.name === "create_date") return 1;
            return a.string.localeCompare(b.string);
        });

        return fields;
    },

    get hasDateTimeFields() {
        return this.isOldGoldPurchase && this.availableDateTimeFields.length > 0;
    },

    onOpenDateTimeFilterWizard() {
        if (!this.isOldGoldPurchase) return;
        const fields = this.availableDateTimeFields;
        if (!fields.length) return;

        this.dialogService.add(DateTimeFilterWizardDialog, {
            fields,
            onApply: (domain, desc) => {
                if (domain.length) {
                    // Remove any previous date/time filter added by this wizard
                    for (const [id, item] of Object.entries(this.env.searchModel.searchItems)) {
                        if (isDateTimeWizardItem(item)) {
                            this.env.searchModel.query = this.env.searchModel.query.filter(
                                (q) => q.searchItemId !== Number(id)
                            );
                            delete this.env.searchModel.searchItems[id];
                        }
                    }

                    const preFilter = {
                        description: desc,
                        domain: new Domain(domain).toString(),
                        type: "filter",
                        invisible: "True",
                        isDateTimeFilter: true,
                    };
                    this.env.searchModel.createNewFilters([preFilter]);
                }
            },
        });
    },
});

