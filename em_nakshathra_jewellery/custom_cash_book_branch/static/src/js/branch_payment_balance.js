/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

class BranchPaymentBalanceDashboard extends Component {
    static template = "custom_cash_book_branch.BranchPaymentBalanceDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const dd = String(today.getDate()).padStart(2, '0');

        const todayStr = `${yyyy}-${mm}-${dd}`;

        this.state = useState({
            loading: true,
            branches: [],
            selectedBranchId: 'all',
            dateFrom: todayStr,
            dateTo: todayStr,
            activePreset: 'today',
            selectedCategory: null,
            activeTab: 'overview',
            currencySymbol: '₹',
            data: null,

            // Transactions ledger state
            transactions: [],
            transactionsLoading: false,
            searchQuery: '',
            filterCategory: '',
            filterJournalId: null,
            txOffset: 0,
            txLimit: 50,
            txTotalCount: 0,
        });

        this.searchTimeout = null;

        onWillStart(async () => {
            await this.loadInitialMetadata();
            await this.fetchDashboardData();
        });
    }

    async loadInitialMetadata() {
        try {
            const meta = await this.orm.call("branch.payment.balance.report", "get_initial_data", []);
            if (meta) {
                this.state.branches = meta.branches || [];
                if (meta.default_branch_id) {
                    this.state.selectedBranchId = meta.default_branch_id;
                }
                if (meta.date_from) {
                    this.state.dateFrom = meta.date_from;
                }
                if (meta.date_to) {
                    this.state.dateTo = meta.date_to;
                }
                if (meta.currency_symbol) {
                    this.state.currencySymbol = meta.currency_symbol;
                }
            }
        } catch (error) {
            console.error("Failed to load initial branch metadata:", error);
        }
    }

    async fetchDashboardData() {
        this.state.loading = true;
        try {
            const res = await this.orm.call("branch.payment.balance.report", "get_balance_summary", [], {
                branch_id: this.state.selectedBranchId,
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
            });

            this.state.data = res;
            if (res.currency_symbol) {
                this.state.currencySymbol = res.currency_symbol;
            }

            // If currently on transactions tab, refresh transactions as well
            if (this.state.activeTab === 'transactions') {
                await this.fetchTransactions();
            }
        } catch (error) {
            console.error("Error fetching balance data:", error);
            this.notification.add("Could not fetch balance data: " + (error.message || error), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    async fetchTransactions() {
        this.state.transactionsLoading = true;
        try {
            const res = await this.orm.call("branch.payment.balance.report", "get_transaction_lines", [], {
                branch_id: this.state.selectedBranchId,
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
                category: this.state.filterCategory || null,
                journal_id: this.state.filterJournalId || null,
                limit: this.state.txLimit,
                offset: this.state.txOffset,
                search_query: this.state.searchQuery || null,
            });

            this.state.transactions = res.lines || [];
            this.state.txTotalCount = res.total_count || 0;
        } catch (error) {
            console.error("Error fetching transactions:", error);
        } finally {
            this.state.transactionsLoading = false;
        }
    }

    // ── Filter Handlers ──
    async onBranchChange() {
        this.state.txOffset = 0;
        await this.fetchDashboardData();
    }

    async onCustomDateChange() {
        this.state.activePreset = 'custom';
        this.state.txOffset = 0;
        await this.fetchDashboardData();
    }

    async onPresetSelectChange(ev) {
        const preset = ev.target.value;
        if (preset === 'custom') {
            this.state.activePreset = 'custom';
            return;
        }
        await this.setPreset(preset);
    }

    formatYMD(d) {
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    async setPreset(preset) {
        this.state.activePreset = preset;
        const now = new Date();

        if (preset === 'today') {
            const todayStr = this.formatYMD(now);
            this.state.dateFrom = todayStr;
            this.state.dateTo = todayStr;
        } else if (preset === 'yesterday') {
            const yday = new Date(now);
            yday.setDate(now.getDate() - 1);
            const ydayStr = this.formatYMD(yday);
            this.state.dateFrom = ydayStr;
            this.state.dateTo = ydayStr;
        } else if (preset === 'week') {
            const day = now.getDay();
            const diff = now.getDate() - day + (day === 0 ? -6 : 1); // Monday
            const monday = new Date(now.setDate(diff));
            this.state.dateFrom = this.formatYMD(monday);
            this.state.dateTo = this.formatYMD(new Date());
        } else if (preset === 'month') {
            const first = new Date(now.getFullYear(), now.getMonth(), 1);
            this.state.dateFrom = this.formatYMD(first);
            this.state.dateTo = this.formatYMD(now);
        } else if (preset === 'last_month') {
            const firstLastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
            const lastLastMonth = new Date(now.getFullYear(), now.getMonth(), 0);
            this.state.dateFrom = this.formatYMD(firstLastMonth);
            this.state.dateTo = this.formatYMD(lastLastMonth);
        } else if (preset === 'quarter') {
            const currentQuarter = Math.floor(now.getMonth() / 3);
            const firstQuarter = new Date(now.getFullYear(), currentQuarter * 3, 1);
            this.state.dateFrom = this.formatYMD(firstQuarter);
            this.state.dateTo = this.formatYMD(now);
        } else if (preset === 'fy') {
            // Indian Financial Year: April 1 to March 31
            const currentYear = now.getFullYear();
            const currentMonth = now.getMonth(); // 0-based, April is 3
            const startYear = currentMonth >= 3 ? currentYear : currentYear - 1;
            const fyStart = new Date(startYear, 3, 1);
            this.state.dateFrom = this.formatYMD(fyStart);
            this.state.dateTo = this.formatYMD(now);
        } else if (preset === 'last_fy') {
            const currentYear = now.getFullYear();
            const currentMonth = now.getMonth();
            const startYear = (currentMonth >= 3 ? currentYear : currentYear - 1) - 1;
            const fyStart = new Date(startYear, 3, 1);
            const fyEnd = new Date(startYear + 1, 2, 31);
            this.state.dateFrom = this.formatYMD(fyStart);
            this.state.dateTo = this.formatYMD(fyEnd);
        }

        this.state.txOffset = 0;
        await this.fetchDashboardData();
    }

    setTab(tab) {
        this.state.activeTab = tab;
        if (tab === 'transactions') {
            this.fetchTransactions();
        }
    }

    async viewJournalTransactions(journalId, category) {
        this.state.filterJournalId = journalId;
        this.state.filterCategory = category || '';
        this.state.activeTab = 'transactions';
        this.state.txOffset = 0;
        await this.fetchTransactions();
    }

    clearJournalFilter() {
        this.state.filterJournalId = null;
        this.fetchTransactions();
    }

    filterByCategory(cat) {
        this.state.filterCategory = cat;
        this.state.txOffset = 0;
        this.fetchTransactions();
    }

    onSearchInput() {
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        this.searchTimeout = setTimeout(() => {
            this.state.txOffset = 0;
            this.fetchTransactions();
        }, 350);
    }

    prevPage() {
        if (this.state.txOffset >= this.state.txLimit) {
            this.state.txOffset -= this.state.txLimit;
            this.fetchTransactions();
        }
    }

    nextPage() {
        if (this.state.txOffset + this.state.txLimit < this.state.txTotalCount) {
            this.state.txOffset += this.state.txLimit;
            this.fetchTransactions();
        }
    }

    toggleCategoryJournals(catKey) {
        if (this.state.selectedCategory === catKey) {
            this.state.selectedCategory = null;
        } else {
            this.state.selectedCategory = catKey;
        }
    }

    closeCategoryJournals() {
        this.state.selectedCategory = null;
    }

    getSelectedCategoryData() {
        if (!this.state.selectedCategory || !this.state.data || !this.state.data.categories) {
            return null;
        }
        return this.state.data.categories[this.state.selectedCategory] || null;
    }

    openMove(moveId) {
        if (!moveId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: moveId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openJournalLedger(journalId) {
        if (!journalId) return;
        const domain = [
            ["journal_id", "=", journalId],
            ["parent_state", "=", "posted"],
        ];
        if (this.state.dateFrom) {
            domain.push(["date", ">=", this.state.dateFrom]);
        }
        if (this.state.dateTo) {
            domain.push(["date", "<=", this.state.dateTo]);
        }
        this.action.doAction({
            name: "Journal Items (" + this.formatDate(this.state.dateFrom) + " - " + this.formatDate(this.state.dateTo) + ")",
            type: "ir.actions.act_window",
            res_model: "account.move.line",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    exportExcel() {
        const url = `/branch_payment_balance/export_xlsx?branch_id=${this.state.selectedBranchId}&date_from=${this.state.dateFrom}&date_to=${this.state.dateTo}`;
        window.open(url, "_blank");
    }

    getSharePercent(catKey) {
        if (!this.state.data || !this.state.data.total) return "0.0";
        const total = parseFloat(this.state.data.total.closing) || 0;
        if (total <= 0) return "0.0";
        const cat = this.state.data.categories && this.state.data.categories[catKey];
        if (!cat) return "0.0";
        const val = parseFloat(cat.closing) || 0;
        if (val <= 0) return "0.0";
        const pct = (val / total) * 100;
        return Math.min(100, Math.max(0, pct)).toFixed(1);
    }

    hasShare(catKey) {
        return parseFloat(this.getSharePercent(catKey)) > 0;
    }

    getTxEndIndex() {
        return Math.min(this.state.txOffset + this.state.txLimit, this.state.txTotalCount);
    }

    // ── Number & Date Helpers ──
    formatMoney(val) {
        if (val === undefined || val === null) return "0.00";
        const num = parseFloat(val);
        if (isNaN(num)) return "0.00";
        return num.toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    formatDate(str) {
        if (!str) return '';
        const parts = str.split('-');
        if (parts.length === 3) {
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
        return str;
    }
}

registry.category("actions").add("branch_payment_balance_dashboard", BranchPaymentBalanceDashboard);

export default BranchPaymentBalanceDashboard;

