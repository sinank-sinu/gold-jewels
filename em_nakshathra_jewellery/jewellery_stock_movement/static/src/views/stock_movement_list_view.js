/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { onWillStart, useState } from "@odoo/owl";

function getTodayStr() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function getStartOfMonthStr() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    return `${y}-${m}-01`;
}

export class StockMovementListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.userService = useService("user");

        this.state = useState({
            warehouses: [],
            selectedWarehouseId: "",
            dateFrom: "",
            dateTo: "",
            summary: {
                total_products: 0,
                total_variants: 0,
                total_weight: 0.0,
            },
            isLoading: false,
        });

        onWillStart(async () => {
            try {
                this.state.warehouses = await this.orm.searchRead(
                    "stock.warehouse",
                    [],
                    ["id", "name", "code"],
                    { order: "name asc" }
                );

                // Initial data generation
                const res = await this.orm.call(
                    "stock.movement.report",
                    "compute_report_data",
                    [],
                    {
                        warehouse_id: this.state.selectedWarehouseId ? parseInt(this.state.selectedWarehouseId) : false,
                        date_from: this.state.dateFrom || false,
                        date_to: this.state.dateTo || false,
                    }
                );
                if (res) {
                    this.state.summary = res;
                }
            } catch (err) {
                console.error("Failed to initialize stock movement:", err);
            }
        });
    }

    async onWarehouseChange(ev) {
        this.state.selectedWarehouseId = ev.target.value;
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
        this.state.selectedWarehouseId = "";
        this.state.dateFrom = "";
        this.state.dateTo = "";
        await this.reloadReport();
    }

    async setFilterToday() {
        this.state.dateFrom = getTodayStr();
        this.state.dateTo = getTodayStr();
        await this.reloadReport();
    }

    async setFilterThisMonth() {
        this.state.dateFrom = getStartOfMonthStr();
        this.state.dateTo = getTodayStr();
        await this.reloadReport();
    }

    async setFilterAllDates() {
        this.state.dateFrom = "";
        this.state.dateTo = "";
        await this.reloadReport();
    }

    async reloadReport() {
        this.state.isLoading = true;
        try {
            const res = await this.orm.call(
                "stock.movement.report",
                "compute_report_data",
                [],
                {
                    warehouse_id: this.state.selectedWarehouseId ? parseInt(this.state.selectedWarehouseId) : false,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                }
            );
            if (res) {
                this.state.summary = res;
            }
            await this.model.root.load({ offset: 0 });
        } catch (err) {
            console.error("Error updating stock movement report:", err);
        } finally {
            this.state.isLoading = false;
        }
    }

    formatWeight(val) {
        if (!val && val !== 0) return "0.000";
        return Number(val).toLocaleString(undefined, {
            minimumFractionDigits: 3,
            maximumFractionDigits: 3,
        });
    }

    formatNumber(val) {
        if (!val && val !== 0) return "0";
        return Number(val).toLocaleString();
    }
}

StockMovementListController.template = "jewellery_stock_movement.StockMovementListView";

export const StockMovementListView = {
    ...listView,
    Controller: StockMovementListController,
};

registry.category("views").add("stock_movement_list", StockMovementListView);
