/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { onWillStart, useState } from "@odoo/owl";

function toDateStr(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}

const EMPTY_SUMMARY = {
    total_products: 0,
    total_variants: 0,
    opening_qty: 0, opening_weight: 0,
    qty_in: 0, weight_in: 0,
    qty_out: 0, weight_out: 0,
    closing_qty: 0, closing_weight: 0,
};

export class StockMovementListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");

        const today = new Date();
        this.state = useState({
            branches: [],
            warehouses: [],
            locations: [],
            branchLocked: false,
            selectedBranchId: "",
            selectedWarehouseId: "",
            selectedLocationId: "",
            dateFrom: toDateStr(new Date(today.getFullYear(), today.getMonth(), 1)),
            dateTo: toDateStr(today),
            summary: { ...EMPTY_SUMMARY },
            isLoading: false,
        });

        onWillStart(async () => {
            const opts = await this.orm.call("stock.movement.report", "get_filter_options", []);
            this.state.branches = opts.branches;
            this.state.warehouses = opts.warehouses;
            this.state.locations = opts.locations;
            this.state.branchLocked = opts.branch_locked;
            this.state.selectedBranchId = opts.default_branch_id ? String(opts.default_branch_id) : "";
            await this.computeReport();
        });
    }

    // ---------------------------------------------------------------- getters
    get filteredWarehouses() {
        const b = this.state.selectedBranchId;
        return b ? this.state.warehouses.filter((w) => String(w.branch_id) === b) : this.state.warehouses;
    }

    get filteredLocations() {
        const whId = this.state.selectedWarehouseId;
        if (whId) {
            return this.state.locations.filter((l) => String(l.warehouse_id) === whId);
        }
        const whIds = new Set(this.filteredWarehouses.map((w) => w.id));
        return this.state.locations.filter((l) => whIds.has(l.warehouse_id));
    }

    // --------------------------------------------------------------- handlers
    async onBranchChange(ev) {
        this.state.selectedBranchId = ev.target.value;
        this.state.selectedWarehouseId = "";
        this.state.selectedLocationId = "";
        await this.reloadReport();
    }

    async onWarehouseChange(ev) {
        this.state.selectedWarehouseId = ev.target.value;
        this.state.selectedLocationId = "";
        await this.reloadReport();
    }

    async onLocationChange(ev) {
        this.state.selectedLocationId = ev.target.value;
        await this.reloadReport();
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
    }

    async onApplyFilter() {
        await this.reloadReport();
    }

    async onResetFilter() {
        if (!this.state.branchLocked) {
            this.state.selectedBranchId = "";
        }
        this.state.selectedWarehouseId = "";
        this.state.selectedLocationId = "";
        await this.setPreset("month");
    }

    async setPreset(preset) {
        const today = new Date();
        let from = today;
        let to = today;
        if (preset === "yesterday") {
            from = to = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
        } else if (preset === "month") {
            from = new Date(today.getFullYear(), today.getMonth(), 1);
        } else if (preset === "last_month") {
            from = new Date(today.getFullYear(), today.getMonth() - 1, 1);
            to = new Date(today.getFullYear(), today.getMonth(), 0);
        } else if (preset === "fy") {
            // Indian financial year: 1 April - 31 March
            const fyStartYear = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
            from = new Date(fyStartYear, 3, 1);
        }
        this.state.dateFrom = toDateStr(from);
        this.state.dateTo = toDateStr(to);
        await this.reloadReport();
    }

    // ------------------------------------------------------------------- data
    async computeReport() {
        this.state.summary = await this.orm.call("stock.movement.report", "compute_report_data", [], {
            branch_id: this.state.selectedBranchId || false,
            warehouse_id: this.state.selectedWarehouseId || false,
            location_id: this.state.selectedLocationId || false,
            date_from: this.state.dateFrom || false,
            date_to: this.state.dateTo || false,
        });
    }

    async reloadReport() {
        if (this.state.dateFrom && this.state.dateTo && this.state.dateFrom > this.state.dateTo) {
            this.notification.add("'From Date' cannot be later than 'To Date'.", { type: "danger" });
            return;
        }
        this.state.isLoading = true;
        try {
            await this.computeReport();
            await this.model.load();
        } finally {
            this.state.isLoading = false;
        }
    }

    // ------------------------------------------------------------- formatting
    formatWeight(val) {
        return Number(val || 0).toLocaleString(undefined, {
            minimumFractionDigits: 3,
            maximumFractionDigits: 3,
        });
    }

    formatNumber(val) {
        return Number(val || 0).toLocaleString();
    }
}

StockMovementListController.template = "jewellery_stock_movement.StockMovementListView";

export const StockMovementListView = {
    ...listView,
    Controller: StockMovementListController,
};

registry.category("views").add("stock_movement_list", StockMovementListView);
