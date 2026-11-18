/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class StockInflowOutflowDashboard extends Component {
    static template = "stock_inflow_outflow.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const today = new Date();
        const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
        const defaultTab = (this.props.action && this.props.action.context && this.props.action.context.default_tab) || "inflow_outflow";

        this.state = useState({
            // Shared filter state across both tabs
            branches: [],
            isBranchEditable: true,
            selectedBranchId: "all",
            dateFrom: this.formatYMD(firstDay),
            dateTo: this.formatYMD(today),
            activePreset: "month",
            currencySymbol: "₹",
            companyName: "",

            // Active top-level tab
            activeTab: defaultTab === "vendor_labels" ? "vendor_labels" : "inflow_outflow",
            dirtyTabs: {
                inflow_outflow: true,
                vendor_labels: true,
            },

            // Tab 1: Stock Inflow & Outflow
            flowLoading: true,
            flowData: null,
            flowSubTab: "products", // 'products' | 'ledger' | 'branches'
            onlyWithMovement: false,
            productSearch: "",
            productLimit: 50,
            productOffset: 0,

            // Tab 1: Movement Ledger
            ledgerLoading: false,
            ledgerLines: [],
            ledgerTotalCount: 0,
            ledgerFilteredWt: 0,
            ledgerFilteredQty: 0,
            ledgerDirection: "", // '' | 'in' | 'out'
            ledgerCategory: "",
            ledgerProductId: null,
            ledgerProductName: "",
            ledgerSearch: "",
            ledgerLimit: 50,
            ledgerOffset: 0,

            // Tab 2: Vendor-Wise Labels (uses exact same Branch & Date filter)
            vendorLoading: false,
            vendorData: null,
            vendorMode: "movement", // 'movement' | 'created' | 'closing'
            vendorSubTab: "summary", // 'summary' | 'all_labels'
            includeNoVendor: true,
            onlyPeriodActivity: false,
            vendorActiveFilter: "all", // 'all' | 'active' | 'inactive'
            vendorSearch: "",

            // Tab 2: Label Drill-down / All Labels
            selectedVendorId: null,
            selectedVendorName: "",
            labelLinesLoading: false,
            labelLines: [],
            labelTotalCount: 0,
            labelSumGross: 0,
            labelSumNet: 0,
            labelFlowFilter: "all", // 'all' | 'inflow' | 'outflow' | 'closing' | 'opening'
            labelLimit: 50,
            labelOffset: 0,
        });

        this.productSearchTimer = null;
        this.ledgerSearchTimer = null;
        this.vendorSearchTimer = null;

        onWillStart(async () => {
            await this.loadInitialMetadata();
            await this.refreshActiveTab();
        });
    }

    // ------------------------------------------------------------------
    // Formatting & Date Helpers
    // ------------------------------------------------------------------
    formatYMD(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${day}`;
    }

    formatDisplayDate(str) {
        if (!str) return "";
        const parts = str.split("-");
        if (parts.length === 3) {
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
        return str;
    }

    formatWeight(val) {
        const num = Number(val || 0);
        return num.toLocaleString("en-IN", {
            minimumFractionDigits: 3,
            maximumFractionDigits: 3,
        });
    }

    formatCount(val) {
        return Number(val || 0).toLocaleString("en-IN");
    }

    pageEnd(offset, limit, total) {
        return Math.min((offset || 0) + (limit || 0), total || 0);
    }

    get selectedBranchName() {
        if (!this.state.selectedBranchId || this.state.selectedBranchId === "all") {
            return this.state.branches.length === 1
                ? this.state.branches[0].name
                : "All Branches";
        }
        const match = this.state.branches.find(
            (b) => String(b.id) === String(this.state.selectedBranchId)
        );
        return match ? match.name : "Selected Branch";
    }

    // ------------------------------------------------------------------
    // Initialization & Unified Filter Actions
    // ------------------------------------------------------------------
    async loadInitialMetadata() {
        try {
            const meta = await this.orm.call(
                "stock.inflow.outflow.report",
                "get_initial_metadata",
                []
            );
            if (meta) {
                this.state.branches = meta.branches || [];
                this.state.isBranchEditable = !!meta.is_branch_editable;
                if (meta.default_branch_id !== undefined && meta.default_branch_id !== false) {
                    this.state.selectedBranchId = String(meta.default_branch_id);
                }
                if (meta.date_from) this.state.dateFrom = meta.date_from;
                if (meta.date_to) this.state.dateTo = meta.date_to;
                if (meta.currency_symbol) this.state.currencySymbol = meta.currency_symbol;
                if (meta.company_name) this.state.companyName = meta.company_name;
            }
        } catch (err) {
            this.notification.add("Failed to load branch metadata: " + (err.message || err), {
                type: "danger",
            });
        }
    }

    markAllDirty() {
        this.state.dirtyTabs.inflow_outflow = true;
        this.state.dirtyTabs.vendor_labels = true;
    }

    async onTabSwitch(tabName) {
        if (this.state.activeTab === tabName) return;
        this.state.activeTab = tabName;
        if (this.state.dirtyTabs[tabName]) {
            await this.refreshActiveTab();
        }
    }

    async onBranchChange() {
        if (!this.state.isBranchEditable) return;
        this.state.productOffset = 0;
        this.state.ledgerOffset = 0;
        this.state.labelOffset = 0;
        this.markAllDirty();
        await this.refreshActiveTab();
    }

    async selectBranchFromTable(branchId) {
        if (!this.state.isBranchEditable) return;
        this.state.selectedBranchId = String(branchId);
        this.state.productOffset = 0;
        this.state.ledgerOffset = 0;
        this.state.labelOffset = 0;
        this.markAllDirty();
        await this.refreshActiveTab();
    }

    async onCustomDateChange() {
        this.state.activePreset = "custom";
        if (this.state.dateFrom && this.state.dateTo && this.state.dateFrom > this.state.dateTo) {
            this.notification.add("'From Date' cannot be later than 'To Date'.", {
                type: "danger",
            });
            return;
        }
        this.state.productOffset = 0;
        this.state.ledgerOffset = 0;
        this.state.labelOffset = 0;
        this.markAllDirty();
        await this.refreshActiveTab();
    }

    async onPresetChange(ev) {
        const preset = ev.target.value;
        this.state.activePreset = preset;
        if (preset === "custom") return;

        const now = new Date();
        let from = new Date(now);
        let to = new Date(now);

        if (preset === "today") {
            // already today
        } else if (preset === "yesterday") {
            from = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
            to = new Date(from);
        } else if (preset === "week") {
            const day = now.getDay();
            const diff = now.getDate() - day + (day === 0 ? -6 : 1);
            from = new Date(now.getFullYear(), now.getMonth(), diff);
        } else if (preset === "month") {
            from = new Date(now.getFullYear(), now.getMonth(), 1);
        } else if (preset === "last_month") {
            from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
            to = new Date(now.getFullYear(), now.getMonth(), 0);
        } else if (preset === "quarter") {
            const q = Math.floor(now.getMonth() / 3);
            from = new Date(now.getFullYear(), q * 3, 1);
        } else if (preset === "fy") {
            const fyStartYear = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
            from = new Date(fyStartYear, 3, 1);
        } else if (preset === "last_fy") {
            const fyStartYear = (now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1) - 1;
            from = new Date(fyStartYear, 3, 1);
            to = new Date(fyStartYear + 1, 2, 31);
        }

        this.state.dateFrom = this.formatYMD(from);
        this.state.dateTo = this.formatYMD(to);
        this.state.productOffset = 0;
        this.state.ledgerOffset = 0;
        this.state.labelOffset = 0;
        this.markAllDirty();
        await this.refreshActiveTab();
    }

    async onRefreshClick() {
        this.markAllDirty();
        await this.refreshActiveTab();
    }

    async refreshActiveTab() {
        if (this.state.dateFrom && this.state.dateTo && this.state.dateFrom > this.state.dateTo) {
            this.notification.add("'From Date' cannot be later than 'To Date'.", {
                type: "danger",
            });
            return;
        }
        if (this.state.activeTab === "inflow_outflow") {
            await this.fetchFlowSummary();
            if (this.state.flowSubTab === "ledger") {
                await this.fetchLedger();
            }
            this.state.dirtyTabs.inflow_outflow = false;
        } else {
            await this.fetchVendorSummary();
            if (this.state.vendorSubTab === "all_labels" || this.state.selectedVendorId !== null) {
                await this.fetchLabelLines();
            }
            this.state.dirtyTabs.vendor_labels = false;
        }
    }

    // ------------------------------------------------------------------
    // Tab 1: Stock Inflow & Outflow Fetching & Handlers
    // ------------------------------------------------------------------
    async fetchFlowSummary() {
        this.state.flowLoading = true;
        try {
            const res = await this.orm.call(
                "stock.inflow.outflow.report",
                "get_inflow_outflow_summary",
                [],
                {
                    branch_id: this.state.selectedBranchId,
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                    only_with_movement: this.state.onlyWithMovement,
                    search_query: this.state.productSearch || null,
                    product_limit: this.state.productLimit,
                    product_offset: this.state.productOffset,
                }
            );
            this.state.flowData = res;
        } catch (err) {
            this.notification.add("Error loading stock inflow/outflow: " + (err.message || err), {
                type: "danger",
            });
        } finally {
            this.state.flowLoading = false;
        }
    }

    async fetchLedger() {
        this.state.ledgerLoading = true;
        try {
            const res = await this.orm.call(
                "stock.inflow.outflow.report",
                "get_inflow_outflow_ledger",
                [],
                {
                    branch_id: this.state.selectedBranchId,
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                    direction: this.state.ledgerDirection || null,
                    category: this.state.ledgerCategory || null,
                    product_id: this.state.ledgerProductId || null,
                    search_query: this.state.ledgerSearch || null,
                    limit: this.state.ledgerLimit,
                    offset: this.state.ledgerOffset,
                }
            );
            this.state.ledgerLines = res.lines || [];
            this.state.ledgerTotalCount = res.total_count || 0;
            this.state.ledgerFilteredWt = res.filtered_wt || 0;
            this.state.ledgerFilteredQty = res.filtered_qty || 0;
        } catch (err) {
            this.notification.add("Error loading movement ledger: " + (err.message || err), {
                type: "danger",
            });
        } finally {
            this.state.ledgerLoading = false;
        }
    }

    async setFlowSubTab(sub) {
        this.state.flowSubTab = sub;
        if (sub === "ledger") {
            await this.fetchLedger();
        }
    }

    async toggleOnlyWithMovement() {
        this.state.onlyWithMovement = !this.state.onlyWithMovement;
        this.state.productOffset = 0;
        await this.fetchFlowSummary();
    }

    onProductSearchInput() {
        clearTimeout(this.productSearchTimer);
        this.productSearchTimer = setTimeout(() => {
            this.state.productOffset = 0;
            this.fetchFlowSummary();
        }, 350);
    }

    async prevProductPage() {
        if (this.state.productOffset >= this.state.productLimit) {
            this.state.productOffset -= this.state.productLimit;
            await this.fetchFlowSummary();
        }
    }

    async nextProductPage() {
        const total = (this.state.flowData && this.state.flowData.product_total_count) || 0;
        if (this.state.productOffset + this.state.productLimit < total) {
            this.state.productOffset += this.state.productLimit;
            await this.fetchFlowSummary();
        }
    }

    async filterLedgerByCategory(catKey) {
        if (this.state.ledgerCategory === catKey && this.state.flowSubTab === "ledger") {
            this.state.ledgerCategory = "";
            this.state.ledgerDirection = "";
        } else {
            this.state.ledgerCategory = catKey;
            this.state.ledgerDirection = "";
        }
        this.state.ledgerOffset = 0;
        this.state.flowSubTab = "ledger";
        await this.fetchLedger();
    }

    async filterLedgerByProduct(productId, productName) {
        this.state.ledgerProductId = productId;
        this.state.ledgerProductName = productName;
        this.state.ledgerOffset = 0;
        this.state.flowSubTab = "ledger";
        await this.fetchLedger();
    }

    async clearLedgerProductFilter() {
        this.state.ledgerProductId = null;
        this.state.ledgerProductName = "";
        this.state.ledgerOffset = 0;
        await this.fetchLedger();
    }

    async onLedgerFilterChange() {
        this.state.ledgerOffset = 0;
        await this.fetchLedger();
    }

    onLedgerSearchInput() {
        clearTimeout(this.ledgerSearchTimer);
        this.ledgerSearchTimer = setTimeout(() => {
            this.state.ledgerOffset = 0;
            this.fetchLedger();
        }, 350);
    }

    async prevLedgerPage() {
        if (this.state.ledgerOffset >= this.state.ledgerLimit) {
            this.state.ledgerOffset -= this.state.ledgerLimit;
            await this.fetchLedger();
        }
    }

    async nextLedgerPage() {
        if (this.state.ledgerOffset + this.state.ledgerLimit < this.state.ledgerTotalCount) {
            this.state.ledgerOffset += this.state.ledgerLimit;
            await this.fetchLedger();
        }
    }

    // ------------------------------------------------------------------
    // Tab 2: Vendor-Wise Labels Fetching & Handlers
    // ------------------------------------------------------------------
    async fetchVendorSummary() {
        this.state.vendorLoading = true;
        try {
            const res = await this.orm.call(
                "stock.inflow.outflow.report",
                "get_vendor_labels_summary",
                [],
                {
                    branch_id: this.state.selectedBranchId,
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                    mode: this.state.vendorMode,
                    include_no_vendor: this.state.includeNoVendor,
                    only_period_activity: this.state.onlyPeriodActivity,
                    active_filter: this.state.vendorActiveFilter,
                    search_query: this.state.vendorSearch || null,
                }
            );
            this.state.vendorData = res;
        } catch (err) {
            this.notification.add("Error loading vendor-wise labels: " + (err.message || err), {
                type: "danger",
            });
        } finally {
            this.state.vendorLoading = false;
        }
    }

    async fetchLabelLines() {
        this.state.labelLinesLoading = true;
        try {
            const vendorArg =
                this.state.vendorSubTab === "all_labels"
                    ? this.state.selectedVendorId
                    : this.state.selectedVendorId;
            const res = await this.orm.call(
                "stock.inflow.outflow.report",
                "get_vendor_label_lines",
                [],
                {
                    branch_id: this.state.selectedBranchId,
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                    vendor_id: vendorArg !== null ? vendorArg : null,
                    mode: this.state.vendorMode,
                    flow_filter: this.state.labelFlowFilter,
                    include_no_vendor: this.state.includeNoVendor,
                    active_filter: this.state.vendorActiveFilter,
                    search_query: this.state.vendorSearch || null,
                    limit: this.state.labelLimit,
                    offset: this.state.labelOffset,
                }
            );
            this.state.labelLines = res.lines || [];
            this.state.labelTotalCount = res.total_count || 0;
            this.state.labelSumGross = res.sum_gross || 0;
            this.state.labelSumNet = res.sum_net || 0;
        } catch (err) {
            this.notification.add("Error loading label details: " + (err.message || err), {
                type: "danger",
            });
        } finally {
            this.state.labelLinesLoading = false;
        }
    }

    async setVendorMode(mode) {
        if (this.state.vendorMode === mode) return;
        this.state.vendorMode = mode;
        this.state.labelFlowFilter = "all";
        this.state.labelOffset = 0;
        await this.fetchVendorSummary();
        if (this.state.vendorSubTab === "all_labels" || this.state.selectedVendorId !== null) {
            await this.fetchLabelLines();
        }
    }

    async setVendorSubTab(sub) {
        this.state.vendorSubTab = sub;
        this.state.labelOffset = 0;
        if (sub === "all_labels") {
            this.state.selectedVendorId = null;
            this.state.selectedVendorName = "";
            await this.fetchLabelLines();
        }
    }

    async toggleIncludeNoVendor() {
        this.state.includeNoVendor = !this.state.includeNoVendor;
        this.state.labelOffset = 0;
        await this.fetchVendorSummary();
        if (this.state.vendorSubTab === "all_labels" || this.state.selectedVendorId !== null) {
            await this.fetchLabelLines();
        }
    }

    async toggleOnlyPeriodActivity() {
        this.state.onlyPeriodActivity = !this.state.onlyPeriodActivity;
        this.state.labelOffset = 0;
        await this.fetchVendorSummary();
    }

    async onVendorActiveFilterChange() {
        this.state.labelOffset = 0;
        await this.fetchVendorSummary();
        if (this.state.vendorSubTab === "all_labels" || this.state.selectedVendorId !== null) {
            await this.fetchLabelLines();
        }
    }

    onVendorSearchInput() {
        clearTimeout(this.vendorSearchTimer);
        this.vendorSearchTimer = setTimeout(async () => {
            this.state.labelOffset = 0;
            await this.fetchVendorSummary();
            if (this.state.vendorSubTab === "all_labels" || this.state.selectedVendorId !== null) {
                await this.fetchLabelLines();
            }
        }, 350);
    }

    async selectVendor(vendor) {
        if (this.state.selectedVendorId === vendor.vendor_id) {
            this.state.selectedVendorId = null;
            this.state.selectedVendorName = "";
            this.state.labelLines = [];
            return;
        }
        this.state.selectedVendorId = vendor.vendor_id;
        this.state.selectedVendorName = vendor.vendor_name;
        this.state.labelFlowFilter = "all";
        this.state.labelOffset = 0;
        await this.fetchLabelLines();
    }

    closeVendorDrilldown() {
        this.state.selectedVendorId = null;
        this.state.selectedVendorName = "";
        this.state.labelLines = [];
    }

    async setLabelFlowFilter(fl) {
        this.state.labelFlowFilter = fl;
        this.state.labelOffset = 0;
        await this.fetchLabelLines();
    }

    async prevLabelPage() {
        if (this.state.labelOffset >= this.state.labelLimit) {
            this.state.labelOffset -= this.state.labelLimit;
            await this.fetchLabelLines();
        }
    }

    async nextLabelPage() {
        if (this.state.labelOffset + this.state.labelLimit < this.state.labelTotalCount) {
            this.state.labelOffset += this.state.labelLimit;
            await this.fetchLabelLines();
        }
    }

    // ------------------------------------------------------------------
    // Export & Native Odoo Record Navigation
    // ------------------------------------------------------------------
    exportExcel() {
        const params = new URLSearchParams({
            branch_id: this.state.selectedBranchId || "all",
            date_from: this.state.dateFrom || "",
            date_to: this.state.dateTo || "",
            mode: this.state.vendorMode || "movement",
            include_no_vendor: this.state.includeNoVendor ? "1" : "0",
            only_period_activity: this.state.onlyPeriodActivity ? "1" : "0",
            active_filter: this.state.vendorActiveFilter || "all",
        });
        window.open(`/stock_inflow_outflow/export_xlsx?${params.toString()}`, "_blank");
    }

    openRecord(resModel, resId) {
        if (!resId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("stock_inflow_outflow_dashboard", StockInflowOutflowDashboard);

export default StockInflowOutflowDashboard;

