/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";

// ─── Chart.js lazy loader (local static file, not in global bundle) ──────────
function loadChartJs() {
    return new Promise((resolve, reject) => {
        if (window.Chart) { resolve(window.Chart); return; }
        const script = document.createElement('script');
        script.src = '/jw_business_dashboard/static/src/js/chart.umd.min.js';
        script.onload = () => resolve(window.Chart);
        script.onerror = () => {
            // Fallback to CDN if local file fails
            const fallback = document.createElement('script');
            fallback.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js';
            fallback.onload = () => resolve(window.Chart);
            fallback.onerror = reject;
            document.head.appendChild(fallback);
        };
        document.head.appendChild(script);
    });
}

// ─── Color palette ────────────────────────────────────────────────────────────
const PALETTE = [
    '#6366f1','#f59e0b','#10b981','#f43f5e','#8b5cf6',
    '#06b6d4','#ef4444','#3b82f6','#ec4899','#14b8a6',
    '#f97316','#84cc16','#a855f7','#22d3ee','#fb923c',
];

const GOLD_PALETTE = [
    '#d97706','#b45309','#f59e0b','#fbbf24','#fde68a',
    '#92400e','#78350f','#a16207','#ca8a04','#eab308',
];

class JwBusinessDashboard extends Component {
    static template = "jw_business_dashboard.MainDashboard";

    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.notification = useService("notification");

        this.charts = {};

        this.state = useState({
            loading: true,
            period: 'this_month',
            dateFrom: '',
            dateTo: '',
            periodLabel: 'This Month',
            lastUpdated: '',
            branchId: 'all',
            branches: [],
            currentTab: 'overview',
            mobileSidebarOpen: false,
            topSaleOrders: [],
            topQuotations: [],
            salesStateDistribution: [],
            kpis: {
                sale_revenue: 0, sale_weight: 0, sale_count: 0,
                quotation_count: 0, quotation_total: 0, quotation_weight: 0,
                purchase_total: 0, purchase_total_weight: 0, purchase_count: 0,
                product_count: 0, stock_value: 0, stock_qty: 0,
                expense_total: 0, jewellery_count: 0, customer_count: 0,
                net_profit: 0, purchase_average_weight: 0,
                employee_count: 0, department_count: 0, present_count: 0,
            },
            salesMonthly: [],
            purchaseMonthly: [],
            expenseMonthly: [],
            inventoryCategory: [],
            productCategory: [],
            jewelleryPurity: [],
            topProducts: [],
            salesBySalesman: [],
            dateBranchCollection: [],
            branchWiseTarget: [],
            stockBalanceProducts: [],
            salesByBranch: [],
            topRfqs: [],
            topPurchaseOrders: [],
            topVendors: [],
            topBuyers: [],
            leastPurchaseOrders: [],
            leastVendors: [],
            bestSellersByRevenue: [],
            bestSellersByQty: [],
            bestSellingCategories: [],
            stockByLocation: [],
            topExpenses: [],
            topExpenseCategories: [],
            topExpenseEmployees: [],
            expenseBulletData: [],
            maximizedChartId: null,

            invoicedKpis: { total_invoiced: 0, total_paid: 0, total_unpaid: 0, avg_invoice: 0, invoice_count: 0 },
            invoicedMonthly: [],
            invoicedTopInvoices: [],
            invoicedTopCategories: [],
            invoicedTopProducts: [],
            invoicedTopSalespeople: [],
            schemesKpis: {
                running: { count: 0, total_paid: 0.0 },
                completed: { count: 0, total_paid: 0.0 },
                redeemed: { count: 0, total_paid: 0.0 },
                total: { count: 0, total_paid: 0.0 }
            },
            schemesMonthlyTrend: [],
            schemesRunning: [],
            schemesCompleted: [],
            schemesRedeemed: [],
            employeeKpis: { total: 0, present: 0, absent: 0, leave: 0, half_day: 0 },
            employeeSummary: [],
        });

        onMounted(async () => {
            await loadChartJs();
            await this.loadData();
        });

        onWillUnmount(() => {
            Object.values(this.charts).forEach(c => c && c.destroy && c.destroy());
        });
    }

    // ─── Period helpers ────────────────────────────────────────────────────
    getPeriodLabel(period) {
        const map = {
            today: 'Today',
            this_week: 'This Week',
            this_month: 'This Month',
            last_month: 'Last Month',
            last_6_months: 'Last 6 Months',
            this_year: 'This Year',
            custom: 'Custom Range',
        };
        return map[period] || period;
    }

    onPeriodChange(ev) {
        this.state.period = ev.target.value;
        this.state.periodLabel = this.getPeriodLabel(this.state.period);
        if (this.state.period !== 'custom') this.loadData();
    }

    onDateChange() {
        if (this.state.dateFrom && this.state.dateTo) this.loadData();
    }

    onBranchChange(ev) {
        this.state.branchId = ev.target.value;
        this.loadData();
    }

    // ─── Data loading ──────────────────────────────────────────────────────
    async loadData() {
        this.state.loading = true;
        try {
            const payload = { period: this.state.period };
            if (this.state.period === 'custom' && this.state.dateFrom && this.state.dateTo) {
                payload.date_from = this.state.dateFrom;
                payload.date_to = this.state.dateTo;
            }
            const data = await this.rpc('/web/dataset/call_kw', {
                model: 'jw.business.dashboard',
                method: 'get_dashboard_data',
                args: [
                    this.state.period,
                    payload.date_from || false,
                    payload.date_to || false,
                    this.state.branchId !== 'all' ? this.state.branchId : false
                ],
                kwargs: {},
            });

            // Update state — set branches explicitly first to guarantee OWL reactivity
            if (data.branches && data.branches.length) {
                this.state.branches = data.branches;
            }
            Object.assign(this.state, {
                kpis: data.kpis || this.state.kpis,
                salesMonthly: data.sales_monthly || [],
                purchaseMonthly: data.purchase_monthly || [],
                expenseMonthly: data.expense_monthly || [],
                inventoryCategory: data.inventory_category || [],
                productCategory: data.product_category || [],
                jewelleryPurity: data.jewellery_purity || [],
                topProducts: data.top_products || [],
                salesBySalesman: data.sales_by_salesman || [],
                dateBranchCollection: data.date_branch_collection || [],
                branchWiseTarget: data.branch_wise_target || [],
                topSaleOrders: data.top_sale_orders || [],
                topQuotations: data.top_quotations || [],
                salesStateDistribution: data.sales_state_distribution || [],
                stockBalanceProducts: data.stock_balance_products || [],
                salesByBranch: data.sales_by_branch || [],
                topRfqs: data.top_rfqs || [],
                topPurchaseOrders: data.top_purchase_orders || [],
                topVendors: data.top_vendors || [],
                topBuyers: data.top_buyers || [],
                leastPurchaseOrders: data.least_purchase_orders || [],
                leastVendors: data.least_vendors || [],
                bestSellersByRevenue: data.best_sellers_by_revenue || [],
                bestSellersByQty: data.best_sellers_by_qty || [],
                bestSellingCategories: data.best_selling_categories || [],
                stockByLocation: data.stock_by_location || [],
                topExpenses: data.top_expenses || [],
                topExpenseCategories: data.top_expense_categories || [],
                topExpenseEmployees: data.top_expense_employees || [],
                expenseBulletData: data.expense_bullet_data || [],

                invoicedKpis: data.invoiced_kpis || this.state.invoicedKpis,
                invoicedMonthly: data.invoiced_monthly || [],
                invoicedTopInvoices: data.invoiced_top_invoices || [],
                invoicedTopCategories: data.invoiced_top_categories || [],
                invoicedTopProducts: data.invoiced_top_products || [],
                invoicedTopSalespeople: data.invoiced_top_salespeople || [],
                schemesKpis: data.schemes_kpis || this.state.schemesKpis,
                schemesMonthlyTrend: data.schemes_monthly_trend || [],
                schemesRunning: data.schemes_running || [],
                schemesCompleted: data.schemes_completed || [],
                schemesRedeemed: data.schemes_redeemed || [],
                employeeKpis: (data.employee_data && data.employee_data.kpis) || this.state.employeeKpis,
                employeeSummary: (data.employee_data && data.employee_data.summary) || [],
                lastUpdated: new Date().toLocaleString(),
                loading: false,
            });

            // Render charts after DOM update
            setTimeout(() => this._renderAllCharts(), 100);
        } catch (err) {
            console.error('JW Dashboard Error:', err);
            this.state.loading = false;
            this.notification.add('Dashboard data load failed. Check console.', { type: 'danger' });
        }
    }

    // ─── Chart rendering ───────────────────────────────────────────────────
    _destroyChart(id) {
        if (this.charts[id]) {
            this.charts[id].destroy();
            delete this.charts[id];
        }
    }

    _getCanvas(id) {
        return document.getElementById(id);
    }

    _renderAllCharts() {
        if (this.state.currentTab === 'overview') {
            this._renderSalesLine();
            this._renderPurchaseBar();
            this._renderExpenseBar();
            this._renderInventoryPie();
            this._renderProductDoughnut();
            this._renderPurityPie();
            this._renderStockBalanceBar();
            this._renderSalesByBranchBar();
            this._renderDateBranchCollectionChart();
        } else if (this.state.currentTab === 'sales') {
            this._renderSalesLine();
            this._renderSalesmanBar();
            this._renderSalesStatePie();
            this._renderBranchTargetBar();
        } else if (this.state.currentTab === 'purchase') {
            this._renderPurchaseLineChart();
            this._renderTopBuyersBar();
        } else if (this.state.currentTab === 'product') {
            this._renderBestSellingCategoriesChart();
            this._renderBestSellersByQtyChart();
        } else if (this.state.currentTab === 'inventory_on_hand') {
            this._renderStockByLocationPie();
        } else if (this.state.currentTab === 'expense') {
            this._renderExpenseBulletChart();
        } else if (this.state.currentTab === 'vendor') {
            this._renderVendorAmountBarChart();
        } else if (this.state.currentTab === 'invoicing') {
            this._renderInvoicedMonthlyBar();
            this._renderInvoicedCategoryChart();
        } else if (this.state.currentTab === 'schemes') {
            this._renderSchemesCharts();
        }

        if (this.state.maximizedChartId) {
            this._renderMaximizedChart(this.state.maximizedChartId);
        }
    }

    _baseLineOptions(title) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true,
                    labels: { color: '#94a3b8', font: { family: "'Inter', sans-serif", size: 12 } }
                },
                tooltip: {
                    backgroundColor: 'rgba(15,23,42,0.9)',
                    titleColor: '#e2e8f0',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(99,102,241,0.3)',
                    borderWidth: 1,
                    padding: 12,
                    callbacks: {
                        label: (ctx) => ` ${ctx.dataset.label}: ${this.formatCurrency(ctx.raw)}`
                    }
                },
            },
            scales: {
                x: {
                    grid: { color: 'rgba(148,163,184,0.08)' },
                    ticks: { color: '#64748b', font: { size: 11 } },
                },
                y: {
                    grid: { color: 'rgba(148,163,184,0.08)' },
                    ticks: { color: '#64748b', font: { size: 11 }, callback: (v) => this.shortNum(v) },
                },
            },
        };
    }

    _baseWeightOptions(title) {
        const opts = this._baseLineOptions(title);
        opts.plugins.tooltip.callbacks.label = (ctx) => ` ${ctx.dataset.label}: ${ctx.raw.toFixed(3)} g`;
        opts.scales.y.ticks.callback = (v) => this.shortNum(v) + ' gms';
        return opts;
    }

    _renderSalesLine() {
        const canvas = this._getCanvas('salesLineChart');
        if (!canvas) return;
        this._destroyChart('salesLineChart');
        const data = this.state.salesMonthly;
        const labels = data.map(d => d.month);
        const revenues = data.map(d => d.revenue);

        this.charts.salesLineChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Gross Weight Sold (gms)',
                        data: revenues,
                        backgroundColor: 'rgba(99, 102, 241, 0.85)',
                        borderColor: '#6366f1',
                        borderWidth: 1,
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                ...this._baseWeightOptions('Sales Weight'),
                onHover: (event, chartElement) => {
                    event.native.target.style.cursor = chartElement.length ? 'pointer' : 'default';
                },
                onClick: (event, activeElements) => {
                    if (activeElements && activeElements.length > 0) {
                        const firstPoint = activeElements[0];
                        const label = labels[firstPoint.index];
                        this.openMonthlySalesOrders(label);
                    }
                },
            },
        });
    }

    openMonthlySalesOrders(label) {
        const monthMap = {
            Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6,
            Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12
        };
        const parts = label.split(' ');
        if (parts.length === 2) {
            const monthStr = parts[0];
            const yearStr = parts[1];
            const month = monthMap[monthStr];
            const year = parseInt(yearStr);
            if (month && year) {
                const startDateStr = `${year}-${String(month).padStart(2, '0')}-01 00:00:00`;
                const lastDay = new Date(year, month, 0).getDate();
                const endDateStr = `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')} 23:59:59`;
                
                const domain = [
                    ['state', 'in', ['sale', 'done']],
                    ['date_order', '>=', startDateStr],
                    ['date_order', '<=', endDateStr]
                ];
                if (this.state.branchId !== 'all') {
                    domain.push(['branch_id', '=', parseInt(this.state.branchId)]);
                }
                
                this.action.doAction({
                    name: `Sales Orders - ${label}`,
                    type: 'ir.actions.act_window',
                    res_model: 'sale.order',
                    view_mode: 'tree,form',
                    views: [[false, 'list'], [false, 'form']],
                    domain: domain,
                    target: 'current',
                });
            }
        }
    }

    _renderPurchaseBar() {
        const canvas = this._getCanvas('purchaseBarChart');
        if (!canvas) return;
        this._destroyChart('purchaseBarChart');
        const data = this.state.purchaseMonthly;
        this.charts.purchaseBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: data.map(d => d.month),
                datasets: [{
                    label: 'Gross Weight Purchased (gms)',
                    data: data.map(d => d.total),
                    backgroundColor: data.map((_, i) => `hsla(38,90%,${50 + (i % 3) * 5}%,0.8)`),
                    borderColor: '#f59e0b',
                    borderWidth: 1,
                    borderRadius: 6,
                }],
            },
            options: {
                ...this._baseWeightOptions('Gross Weight Purchased'),
                plugins: {
                    ...this._baseWeightOptions('Gross Weight Purchased').plugins,
                    legend: { display: false },
                    tooltip: {
                        ...this._baseWeightOptions('Gross Weight Purchased').plugins.tooltip,
                        callbacks: {
                            label: (ctx) => ` Gross Weight: ${ctx.raw.toFixed(3)} g`
                        }
                    }
                },
            },
        });
    }

    _renderExpenseBar() {
        const canvas = this._getCanvas('expenseBarChart');
        if (!canvas) return;
        this._destroyChart('expenseBarChart');
        const data = this.state.expenseMonthly;
        this.charts.expenseBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: data.map(d => d.month),
                datasets: [{
                    label: 'Expenses',
                    data: data.map(d => d.total),
                    backgroundColor: 'rgba(244,63,94,0.75)',
                    borderColor: '#f43f5e',
                    borderWidth: 1,
                    borderRadius: 6,
                }],
            },
            options: {
                ...this._baseLineOptions('Expenses'),
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: { label: (ctx) => ` ${this.formatCurrency(ctx.raw)}` }
                    }
                },
            },
        });
    }

    _renderInventoryPie() {
        const canvas = this._getCanvas('inventoryPieChart');
        if (!canvas) return;
        this._destroyChart('inventoryPieChart');
        const data = this.state.inventoryCategory;
        const labels = data.map(d => d.label);
        const values = data.map(d => d.value);

        this.charts.inventoryPieChart = new window.Chart(canvas, {
            type: 'pie',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: PALETTE.slice(0, labels.length),
                    borderColor: 'transparent',
                    borderWidth: 0,
                    hoverOffset: 10,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw.toFixed(3)} g` }
                    }
                },
            },
        });
        this._buildLegend('inventoryLegend', labels, PALETTE, values, true);
    }

    _renderProductDoughnut() {
        const canvas = this._getCanvas('productDoughnutChart');
        if (!canvas) return;
        this._destroyChart('productDoughnutChart');
        const data = this.state.productCategory;
        const labels = data.map(d => d.label);
        const values = data.map(d => d.value);

        this.charts.productDoughnutChart = new window.Chart(canvas, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: PALETTE.slice(0, labels.length).map(c => c + 'cc'),
                    borderColor: 'transparent',
                    borderWidth: 0,
                    hoverOffset: 10,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw.toFixed(3)} g` }
                    }
                },
            },
        });
        this._buildLegend('productLegend', labels, PALETTE, values, false);
    }

    _renderPurityPie() {
        const canvas = this._getCanvas('purityPieChart');
        if (!canvas) return;
        this._destroyChart('purityPieChart');
        const data = this.state.jewelleryPurity;
        if (!data.length) {
            // Show placeholder if no purity data
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = 'rgba(148,163,184,0.2)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#64748b';
            ctx.font = '14px Inter';
            ctx.textAlign = 'center';
            ctx.fillText('No purity data available', canvas.width / 2, canvas.height / 2);
            return;
        }
        const labels = data.map(d => d.label);
        const values = data.map(d => d.qty);

        this.charts.purityPieChart = new window.Chart(canvas, {
            type: 'pie',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: GOLD_PALETTE.slice(0, labels.length),
                    borderColor: 'transparent',
                    borderWidth: 0,
                    hoverOffset: 10,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw.toFixed(3)} g` }
                    }
                },
            },
        });
        this._buildLegend('purityLegend', labels, GOLD_PALETTE, values, false);
    }

    _renderSalesmanBar() {
        const canvas = this._getCanvas('salesmanBarChart');
        if (!canvas) return;
        this._destroyChart('salesmanBarChart');
        const data = this.state.salesBySalesman;

        this.charts.salesmanBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: data.map(d => d.salesman),
                datasets: [
                    {
                        label: 'Actual Sales (gms)',
                        data: data.map(d => d.revenue),
                        backgroundColor: '#6366f1cc',
                        borderColor: '#6366f1',
                        borderWidth: 1,
                        borderRadius: 6,
                    },
                    {
                        label: 'Target Sales (gms)',
                        data: data.map(d => d.target || 0),
                        backgroundColor: '#10b981cc',
                        borderColor: '#10b981',
                        borderWidth: 1,
                        borderRadius: 6,
                    }
                ],
            },
            options: {
                indexAxis: 'x',
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: { color: '#94a3b8', font: { size: 11 } }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => {
                                const idx = ctx.dataIndex;
                                const item = data[idx];
                                const actual = item.revenue;
                                const target = item.target || 0;
                                const pct = target > 0 ? ((actual / target) * 100).toFixed(1) : 'N/A';
                                if (ctx.datasetIndex === 0) {
                                    return ` Actual: ${this.formatWeight(actual)} (${pct}% of target)`;
                                } else {
                                    return ` Target: ${this.formatWeight(target)}`;
                                }
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#64748b', font: { size: 11 } },
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#94a3b8', font: { size: 11 }, callback: v => this.shortNum(v) + ' gms' },
                    },
                },
            },
        });
    }

    _renderBranchTargetBar() {
        const canvas = this._getCanvas('branchTargetBarChart');
        if (!canvas) return;
        this._destroyChart('branchTargetBarChart');
        const data = this.state.branchWiseTarget;

        this.charts.branchTargetBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: data.map(d => d.branch),
                datasets: [
                    {
                        label: 'Actual Sales (gms)',
                        data: data.map(d => d.actual),
                        backgroundColor: '#3b82f6cc',
                        borderColor: '#3b82f6',
                        borderWidth: 1,
                        borderRadius: 6,
                    },
                    {
                        label: 'Target Sales (gms)',
                        data: data.map(d => d.target || 0),
                        backgroundColor: '#10b981cc',
                        borderColor: '#10b981',
                        borderWidth: 1,
                        borderRadius: 6,
                    }
                ],
            },
            options: {
                indexAxis: 'x',
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: { color: '#94a3b8', font: { size: 11 } }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => {
                                const idx = ctx.dataIndex;
                                const item = data[idx];
                                const actual = item.actual;
                                const target = item.target || 0;
                                const pct = target > 0 ? ((actual / target) * 100).toFixed(1) : 'N/A';
                                if (ctx.datasetIndex === 0) {
                                    return ` Actual: ${this.formatWeight(actual)} (${pct}% of target)`;
                                } else {
                                    return ` Target: ${this.formatWeight(target)}`;
                                }
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#64748b', font: { size: 11 } },
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#94a3b8', font: { size: 11 }, callback: v => this.shortNum(v) + ' gms' },
                    },
                },
            },
        });
    }

    _renderSalesStatePie() {
        const canvas = this._getCanvas('salesStatePieChart');
        if (!canvas) return;
        this._destroyChart('salesStatePieChart');
        const data = this.state.salesStateDistribution;
        const labels = data.map(d => d.label);
        const values = data.map(d => d.value);
        const colors = ['#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#ec4899'];

        this.charts.salesStatePieChart = new window.Chart(canvas, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderWidth: 0,
                    borderColor: 'transparent',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        titleColor: '#e2e8f0',
                        bodyColor: '#94a3b8',
                        borderColor: 'rgba(99,102,241,0.3)',
                        borderWidth: 1,
                        padding: 12,
                        callbacks: {
                            label: (ctx) => ` ${ctx.label}: ${ctx.raw} orders`
                        }
                     }
                },
                cutout: '65%'
            }
        });
        this._buildLegend('salesStateLegend', labels, colors, values, false);
    }

    _renderStockBalanceBar() {
        const canvas = this._getCanvas('stockBalanceBarChart');
        if (!canvas) return;
        this._destroyChart('stockBalanceBarChart');
        const data = this.state.stockBalanceProducts;
        const labels = data.map(d => d.name);
        const values = data.map(d => d.qty);

        this.charts.stockBalanceBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Stock Qty (gms)',
                    data: values,
                    backgroundColor: 'rgba(99,102,241,0.85)',
                    borderColor: '#6366f1',
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Stock Balance: ${ctx.raw.toFixed(3)} g`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 } }
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#94a3b8', font: { size: 11 }, callback: v => this.shortNum(v) + ' gms' }
                    }
                }
            }
        });
    }

    _renderSalesByBranchBar() {
        const canvas = this._getCanvas('salesByBranchBarChart');
        if (!canvas) return;
        this._destroyChart('salesByBranchBarChart');
        const data = this.state.salesByBranch;
        const labels = data.map(d => d.name);
        const values = data.map(d => d.revenue);

        this.charts.salesByBranchBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Total Sales (gms)',
                    data: values,
                    backgroundColor: 'rgba(245,158,11,0.85)',
                    borderColor: '#f59e0b',
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Sales: ${ctx.raw.toFixed(3)} g`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 } }
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#94a3b8', font: { size: 11 }, callback: v => this.shortNum(v) + ' gms' }
                    }
                }
            }
        });
    }

    _createCollectionChart(canvas) {
        const collectionData = this.state.dateBranchCollection || [];

        // 1. Get unique sorted month keys (YYYY-MM format)
        const rawMonths = [...new Set(collectionData.map(item => item.month_key))].sort();

        // Helper to format YYYY-MM -> MonthName (e.g. Jul)
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const formattedLabels = rawMonths.map(key => {
            if (!key) return '';
            const parts = key.split('-');
            if (parts.length < 2) return key;
            const monthIdx = parseInt(parts[1], 10) - 1;
            return months[monthIdx] || key;
        });

        // 2. Get unique branch names
        const branches = [...new Set(collectionData.map(item => item.branch))].sort();

        // 3. Define vibrant color palette
        const colors = [
            '#10B981', // green
            '#6366F1', // indigo
            '#F59E0B', // amber
            '#EC4899', // pink
            '#3B82F6', // blue
            '#EF4444', // red
            '#8B5CF6', // purple
            '#06B6D4', // cyan
        ];

        // 4. Generate datasets
        const datasets = branches.map((branch, index) => {
            const color = colors[index % colors.length];
            return {
                label: branch,
                data: rawMonths.map(key => {
                    const match = collectionData.find(item => item.month_key === key && item.branch === branch);
                    return match ? match.amount : 0;
                }),
                backgroundColor: color + 'CC', // 80% opacity
                borderColor: color,
                borderWidth: 1,
                borderRadius: 4,
            };
        });

        return new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: formattedLabels,
                datasets: datasets,
            },
            options: {
                ...this._baseLineOptions('Collection Amount'),
                scales: {
                    x: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 } },
                        stacked: false,
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: {
                            color: '#94a3b8',
                            font: { size: 11 },
                            callback: (v) => this.shortNum(v),
                        },
                        stacked: false,
                    },
                },
            },
        });
    }

    _renderDateBranchCollectionChart() {
        const canvas = this._getCanvas('dateBranchCollectionChart');
        if (canvas) {
            this._destroyChart('dateBranchCollectionChart');
            this.charts.dateBranchCollectionChart = this._createCollectionChart(canvas);
        }
    }

    _renderPurchaseLineChart() {
        const canvas = this._getCanvas('purchaseLineChart');
        if (!canvas) return;
        this._destroyChart('purchaseLineChart');
        const data = this.state.purchaseMonthly || [];
        this.charts.purchaseLineChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: data.map(d => d.month),
                datasets: [{
                    label: 'Gross Weight Purchased (gms)',
                    data: data.map(d => d.total),
                    backgroundColor: 'rgba(245, 158, 11, 0.85)',
                    borderColor: '#f59e0b',
                    borderWidth: 1,
                    borderRadius: 6
                }]
            },
            options: this._baseWeightOptions('Gross Weight Purchased')
        });
    }

    _renderTopRfqsBar() {
        const canvas = this._getCanvas('topRfqsBarChart');
        if (!canvas) return;
        this._destroyChart('topRfqsBarChart');
        const data = this.state.topRfqs || [];
        const labels = data.map(d => d.name);
        const values = data.map(d => d.amount);

        this.charts.topRfqsBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'RFQ Amount',
                    data: values,
                    backgroundColor: 'rgba(99,102,241,0.85)',
                    borderColor: '#6366f1',
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Amount: ${this.formatCurrency(ctx.raw)}`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 }, callback: (v) => this.shortNum(v) + ' gms' }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { size: 11 } }
                    }
                }
            }
        });
    }

    _renderTopOrdersBar() {
        const canvas = this._getCanvas('topOrdersBarChart');
        if (!canvas) return;
        this._destroyChart('topOrdersBarChart');
        const data = this.state.topPurchaseOrders || [];
        const labels = data.map(d => d.name);
        const values = data.map(d => d.amount);

        this.charts.topOrdersBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Order Amount',
                    data: values,
                    backgroundColor: 'rgba(34,197,94,0.85)',
                    borderColor: '#22c55e',
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Amount: ${this.formatCurrency(ctx.raw)}`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 }, callback: (v) => this.shortNum(v) + ' gms' }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { size: 11 } }
                    }
                }
            }
        });
    }

    _renderTopVendorsBar() {
        const canvas = this._getCanvas('topVendorsBarChart');
        if (!canvas) return;
        this._destroyChart('topVendorsBarChart');
        const data = this.state.topVendors || [];
        const labels = data.map(d => d.name);
        const values = data.map(d => d.total);

        this.charts.topVendorsBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Gross Weight (gms)',
                    data: values,
                    backgroundColor: 'rgba(239,68,68,0.85)',
                    borderColor: '#ef4444',
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Weight: ${ctx.raw.toFixed(3)} g`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 } }
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#94a3b8', font: { size: 11 }, callback: (v) => v.toFixed(1) + ' gms' }
                    }
                }
            }
        });
    }

    _renderTopBuyersBar() {
        const canvas = this._getCanvas('topBuyersBarChart');
        if (!canvas) return;
        this._destroyChart('topBuyersBarChart');
        const data = this.state.topBuyers || [];
        const labels = data.map(d => d.name);
        const values = data.map(d => d.total);

        this.charts.topBuyersBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Gross Weight (gms)',
                    data: values,
                    backgroundColor: 'rgba(245,158,11,0.85)',
                    borderColor: '#f59e0b',
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Weight: ${ctx.raw.toFixed(3)} g`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 } }
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#94a3b8', font: { size: 11 }, callback: (v) => v.toFixed(1) + ' gms' }
                    }
                }
            }
        });
    }

    _renderBestSellingCategoriesChart() {
        const canvas = this._getCanvas('bestSellingCategoriesChart');
        if (!canvas) return;
        this._destroyChart('bestSellingCategoriesChart');
        const data = this.state.bestSellingCategories || [];
        const labels = data.map(d => d.name);
        const quantities = data.map(d => d.qty);

        this.charts.bestSellingCategoriesChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Weight (gms)',
                    data: quantities,
                    backgroundColor: 'rgba(99, 102, 241, 0.85)',
                    borderColor: '#6366f1',
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Weight: ${this.formatWeight(ctx.raw)}`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { size: 9 }, maxRotation: 45, minRotation: 45 }
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 }, callback: (v) => this.shortNum(v) + ' gms' }
                    }
                }
            }
        });
    }

    _renderBestSellersByQtyChart() {
        const canvas = this._getCanvas('bestSellersByQtyChart');
        if (!canvas) return;
        this._destroyChart('bestSellersByQtyChart');
        const data = this.state.bestSellersByQty || [];
        const labels = data.map(d => d.name);
        const quantities = data.map(d => d.qty);

        this.charts.bestSellersByQtyChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Weight (gms)',
                    data: quantities,
                    backgroundColor: 'rgba(16, 185, 129, 0.85)',
                    borderColor: '#10b981',
                    borderWidth: 1,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Weight: ${this.formatWeight(ctx.raw)}`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { size: 9 }, maxRotation: 45, minRotation: 45 }
                    },
                    y: {
                        grid: { color: 'rgba(148,163,184,0.08)' },
                        ticks: { color: '#64748b', font: { size: 10 }, callback: (v) => this.shortNum(v) + ' gms' }
                    }
                }
            }
        });
    }

    _renderStockByLocationPie() {
        const canvas = this._getCanvas('stockByLocationChart');
        if (!canvas) return;
        this._destroyChart('stockByLocationChart');
        const data = this.state.stockByLocation || [];
        const labels = data.map(d => d.location);
        const values = data.map(d => d.qty);

        this.charts.stockByLocationChart = new window.Chart(canvas, {
            type: 'pie',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: PALETTE.slice(0, labels.length).map(c => c + 'cc'),
                    borderColor: 'transparent',
                    borderWidth: 0,
                    hoverOffset: 10,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Weight: ${this.formatNumber(ctx.raw)} gms`
                        }
                    }
                }
            }
        });
        this._buildLegend('stockByLocationLegend', labels, PALETTE, values, false);
    }

    _renderExpenseBulletChart() {
        const canvas = this._getCanvas('expenseBulletChart');
        if (!canvas) return;
        this._destroyChart('expenseBulletChart');

        const bulletData = this.state.expenseBulletData || [];
        const labels = bulletData.map(item => item.category);
        const actuals = bulletData.map(item => item.actual);
        const backgrounds = bulletData.map(item => item.actual > item.target ? '#ef4444' : '#6366f1');

        this.charts.expenseBulletChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Actual Spend',
                    data: actuals,
                    backgroundColor: backgrounds,
                    borderColor: 'transparent',
                    borderWidth: 0,
                    borderRadius: { topLeft: 4, topRight: 4 },
                    barThickness: 30
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        titleColor: '#f8fafc',
                        bodyColor: '#f8fafc',
                        callbacks: {
                            label: (ctx) => {
                                const item = bulletData[ctx.dataIndex];
                                if (!item) return '';
                                return ` Actual: ${this.formatCurrency(item.actual)} (Budget: ${this.formatCurrency(item.target)})`;
                            }
                        }
                    },
                    bulletHelper: {
                        data: bulletData
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8' }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            color: '#94a3b8',
                            callback: (val) => this.formatCurrency(val)
                        }
                    }
                }
            },
            plugins: [{
                id: 'bulletChartPlugin',
                beforeDatasetsDraw(chart) {
                    const { ctx, scales: { x, y } } = chart;
                    const helpers = chart.config.options.plugins.bulletHelper;
                    if (!helpers || !helpers.data) return;
                    
                    helpers.data.forEach((item, index) => {
                        const centerX = x.getPixelForValue(index);
                        const barWidth = 50; // width of background track
                        const leftX = centerX - barWidth / 2;
                        const bottomY = y.getPixelForValue(0);
                        
                        const maxVal = Math.max(item.actual, item.target) * 1.1;
                        const yLow = y.getPixelForValue(item.range_low);
                        const yMed = y.getPixelForValue(item.range_med);
                        const yHigh = y.getPixelForValue(maxVal);
                        
                        // Draw low range (greenish/satisfactory)
                        ctx.fillStyle = 'rgba(16, 185, 129, 0.08)';
                        ctx.fillRect(leftX, yLow, barWidth, bottomY - yLow);
                        
                        // Draw med range (yellowish/warning)
                        ctx.fillStyle = 'rgba(245, 158, 11, 0.08)';
                        ctx.fillRect(leftX, yMed, barWidth, yLow - yMed);
                        
                        // Draw high range (reddish/critical)
                        ctx.fillStyle = 'rgba(244, 63, 94, 0.05)';
                        ctx.fillRect(leftX, yHigh, barWidth, yMed - yHigh);
                    });
                }
            }]
        });
    }

    _renderVendorAmountBarChart() {
        const canvas = this._getCanvas('vendorAmountBarChart');
        if (!canvas) return;
        this._destroyChart('vendorAmountBarChart');

        const vendorsData = this.state.topVendors || [];
        const labels = vendorsData.map(item => item.vendor);
        const totals = vendorsData.map(item => item.total);

        this.charts.vendorAmountBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Gross Weight (gms)',
                    data: totals,
                    backgroundColor: 'rgba(59, 130, 246, 0.85)',
                    borderColor: '#3b82f6',
                    borderWidth: 1,
                    borderRadius: { topLeft: 4, topRight: 4 },
                    barThickness: 24
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` Weight: ${this.formatWeight(ctx.raw)}`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8' }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            color: '#94a3b8',
                            callback: (val) => this.formatWeight(val)
                        }
                    }
                }
            }
        });
    }

    _prepareInvoicedMonthlyDatasets(data) {
        const uniqueMonths = [];
        data.forEach(item => {
            if (!uniqueMonths.includes(item.month)) {
                uniqueMonths.push(item.month);
            }
        });

        const uniquePurities = [];
        data.forEach(item => {
            if (!uniquePurities.includes(item.purity)) {
                uniquePurities.push(item.purity);
            }
        });

        const colors = {
            '22k': 'rgba(245, 158, 11, 0.85)',
            '22K': 'rgba(245, 158, 11, 0.85)',
            '18k': 'rgba(239, 68, 68, 0.85)',
            '18K': 'rgba(239, 68, 68, 0.85)',
            '18CT': 'rgba(239, 68, 68, 0.85)',
            '22KT': 'rgba(245, 158, 11, 0.85)',
            '24k': 'rgba(16, 185, 129, 0.85)',
            '24K': 'rgba(16, 185, 129, 0.85)',
            'Unknown': 'rgba(100, 116, 139, 0.85)'
        };
        const borderColors = {
            '22k': '#f59e0b',
            '22K': '#f59e0b',
            '18k': '#ef4444',
            '18K': '#ef4444',
            '18CT': '#ef4444',
            '22KT': '#f59e0b',
            '24k': '#10b981',
            '24K': '#10b981',
            'Unknown': '#64748b'
        };

        const defaultColors = [
            'rgba(99, 102, 241, 0.85)',
            'rgba(16, 185, 129, 0.85)',
            'rgba(245, 158, 11, 0.85)',
            'rgba(239, 68, 68, 0.85)',
            'rgba(139, 92, 246, 0.85)',
            'rgba(236, 72, 153, 0.85)'
        ];
        const defaultBorders = [
            '#6366f1',
            '#10b981',
            '#f59e0b',
            '#ef4444',
            '#8b5cf6',
            '#ec7299'
        ];

        const datasets = uniquePurities.map((purity, idx) => {
            const dataValues = uniqueMonths.map(month => {
                const match = data.find(item => item.month === month && item.purity === purity);
                return match ? match.weight : 0;
            });

            const key = purity.toLowerCase();
            const color = colors[purity] || colors[key] || defaultColors[idx % defaultColors.length];
            const borderColor = borderColors[purity] || borderColors[key] || defaultBorders[idx % defaultBorders.length];

            return {
                label: purity,
                data: dataValues,
                backgroundColor: color,
                borderColor: borderColor,
                borderWidth: 1,
                borderRadius: { topLeft: 4, topRight: 4 }
            };
        });

        return { labels: uniqueMonths, datasets: datasets };
    }

    _renderInvoicedMonthlyBar() {
        const canvas = this._getCanvas('invoicedMonthlyBarChart');
        if (!canvas) return;
        this._destroyChart('invoicedMonthlyBarChart');

        const data = this.state.invoicedMonthly || [];
        const { labels, datasets } = this._prepareInvoicedMonthlyDatasets(data);

        this.charts.invoicedMonthlyBarChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: { color: '#64748b', font: { size: 10 }, boxWidth: 12 }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw.toFixed(3)} gms`
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { display: false },
                        ticks: { color: '#94a3b8' }
                    },
                    y: {
                        stacked: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            color: '#64748b',
                            font: { size: 10 },
                            callback: (v) => this.shortNum(v) + ' gms'
                        }
                    }
                }
            }
        });
    }

    _renderSchemesCharts() {
        const canvas = this._getCanvas('schemesTrendChart');
        if (!canvas) return;
        this._destroyChart('schemesTrendChart');

        const data = this.state.schemesMonthlyTrend || [];
        const labels = data.map(item => item.label);
        const values = data.map(item => item.value);

        this.charts.schemesTrendChart = new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'New Enrollments Count',
                    data: values,
                    backgroundColor: 'rgba(56, 189, 248, 0.85)',
                    borderColor: '#38bdf8',
                    borderWidth: 1,
                    borderRadius: { topLeft: 4, topRight: 4 },
                    barThickness: 24
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: { label: (ctx) => ` Enrollments: ${ctx.raw}` }
                    }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
                    y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', stepSize: 1, callback: (val) => Math.floor(val) } }
                }
            }
        });
    }

    _renderInvoicedCategoryChart() {
        const canvas = this._getCanvas('invoicedCategoryChart');
        if (!canvas) return;
        this._destroyChart('invoicedCategoryChart');

        const data = this.state.invoicedTopCategories || [];
        const labels = data.map(item => item.name);
        const values = data.map(item => item.value);

        this.charts.invoicedCategoryChart = new window.Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: PALETTE.slice(0, labels.length).map(c => c + 'cc'),
                    borderColor: 'transparent',
                    borderWidth: 0,
                    hoverOffset: 10,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.9)',
                        callbacks: {
                            label: (ctx) => ` ${ctx.label}: ${this.formatWeight(ctx.raw)}`
                        }
                    }
                },
            }
        });
        this._buildLegend('invoicedCategoryLegend', labels, PALETTE, values, true);
    }


    // ─── Legend builder ────────────────────────────────────────────────────
    _buildLegend(containerId, labels, colors, values, showValue) {
        const container = document.getElementById(containerId);
        if (!container) return;
        const total = values.reduce((a, b) => a + b, 0);
        container.innerHTML = labels.slice(0, 6).map((label, i) => {
            const pct = total > 0 ? ((values[i] / total) * 100).toFixed(1) : 0;
            return `
                <div class="jw-legend-item">
                    <span class="jw-legend-dot" style="background:${colors[i % colors.length]}"></span>
                    <span class="jw-legend-label" title="${label}">${label.length > 18 ? label.slice(0, 16) + '…' : label}</span>
                    <span class="jw-legend-pct">${pct}%</span>
                </div>`;
        }).join('');
    }

    // ─── Formatting helpers ────────────────────────────────────────────────
    formatCurrency(val) {
        if (val === undefined || val === null) return '₹0';
        const num = Number(val);
        if (num >= 10000000) return '₹' + (num / 10000000).toFixed(2) + 'Cr';
        if (num >= 100000) return '₹' + (num / 100000).toFixed(2) + 'L';
        if (num >= 1000) return '₹' + (num / 1000).toFixed(1) + 'K';
        return '₹' + num.toFixed(0);
    }

    formatWeight(val) {
        if (val === undefined || val === null) return '0.000 gms';
        return Number(val).toFixed(3) + ' gms';
    }

    formatNumber(val) {
        if (val === undefined || val === null) return '0';
        const num = Number(val);
        if (num >= 1000000) return (num / 1000000).toFixed(2) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toFixed(0);
    }

    getBulletSpecs(item) {
        const actual = Number(item.actual || 0);
        const target = Number(item.target || 3000);
        const maxVal = Math.max(actual, target) * 1.1;
        return {
            lowWidth: ((Number(item.range_low || 0) / maxVal) * 100).toFixed(1),
            medWidth: (((Number(item.range_med || 0) - Number(item.range_low || 0)) / maxVal) * 100).toFixed(1),
            highWidth: (((maxVal - Number(item.range_med || 0)) / maxVal) * 100).toFixed(1),
            actualWidth: ((actual / maxVal) * 100).toFixed(1),
            targetLeft: ((target / maxVal) * 100).toFixed(1),
            isOverTarget: actual > target
        };
    }

    shortNum(val) {
        if (val >= 10000000) return (val / 10000000).toFixed(1) + 'Cr';
        if (val >= 100000) return (val / 100000).toFixed(1) + 'L';
        if (val >= 1000) return (val / 1000).toFixed(0) + 'K';
        return val;
    }

    getBarWidth(value, list) {
        const max = Math.max(...list.map(p => p.revenue), 1);
        return ((value / max) * 100).toFixed(0);
    }

    // ─── Navigation ────────────────────────────────────────────────────────
    navigateTo(actionXmlId) {
        this.action.doAction(actionXmlId);
    }

    toggleMobileSidebar() {
        this.state.mobileSidebarOpen = !this.state.mobileSidebarOpen;
    }

    closeMobileSidebar() {
        this.state.mobileSidebarOpen = false;
    }

    switchTab(tab) {
        this.state.currentTab = tab;
        this.state.mobileSidebarOpen = false;
        setTimeout(() => this._renderAllCharts(), 100);
    }

    toggleChartMaximize(chartId) {
        if (this.state.maximizedChartId === chartId) {
            this.state.maximizedChartId = null;
        } else {
            this.state.maximizedChartId = chartId;
        }
        setTimeout(() => this._renderAllCharts(), 100);
    }

    getMaximizedChartTitle() {
        const titles = {
            'salesLineChart': 'Monthly Sales (Gross Weight)',
            'purchaseBarChart': 'Monthly Purchase (Gross Weight)',
            'stockBalanceBarChart': 'Stock Balance by Purity (gms)',
            'salesByBranchBarChart': 'Sales by Branch (Gross Weight)',
            'inventoryPieChart': 'Inventory by Purity (Gross Weight)',
            'productDoughnutChart': 'Product Distribution (Gross Weight)',
            'purityPieChart': 'Jewellery Purity Breakdown (Gross Weight)',
            'dateBranchCollectionChart': 'Branch Collection',
            'salesmanBarChart': 'Sales by Salesman (Target Achievement)',
            'salesStatePieChart': 'Order State Distribution',
            'branchTargetBarChart': 'Branch-Wise Target vs Actual Sales',
            'purchaseLineChart': 'Gross Weight Purchased Trend',
            'topBuyersBarChart': 'Top Buyers',
            'bestSellingCategoriesChart': 'Best Selling Purity (Weight)',
            'bestSellersByQtyChart': 'Best Sellers by Weight (gms)',
            'stockByLocationChart': 'Stock by Location',
            'expenseBulletChart': 'Expense Budget Analysis',
            'vendorAmountBarChart': 'Top Vendors by Gross Weight',
            'invoicedMonthlyBarChart': 'Invoiced by Month (Purity-Wise Weight)',
            'invoicedCategoryChart': 'Invoiced by Category (Gross Weight)',
            'schemesTrendChart': 'Monthly Schemes Enrollment Trend',
        };
        return titles[this.state.maximizedChartId] || 'Chart';
    }

    _renderMaximizedChart(chartId) {
        const canvas = this._getCanvas('maximizedChartCanvas');
        if (!canvas) return;
        this._destroyChart('maximizedChartCanvas');

        if (chartId === 'salesLineChart') {
            const data = this.state.salesMonthly || [];
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: data.map(d => d.month),
                    datasets: [
                        {
                            label: 'Gross Weight Sold (gms)',
                            data: data.map(d => d.revenue),
                            backgroundColor: 'rgba(99, 102, 241, 0.85)',
                            borderColor: '#6366f1',
                            borderWidth: 1,
                            borderRadius: 6,
                        },
                    ],
                },
                options: {
                    ...this._baseWeightOptions('Sales Weight'),
                },
            });
        } else if (chartId === 'purchaseBarChart') {
            const data = this.state.purchaseMonthly || [];
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: data.map(d => d.month),
                    datasets: [{
                        label: 'Gross Weight Purchased (gms)',
                        data: data.map(d => d.total),
                        backgroundColor: data.map((_, i) => `hsla(38,90%,${50 + (i % 3) * 5}%,0.8)`),
                        borderColor: '#f59e0b',
                        borderWidth: 1,
                        borderRadius: 6,
                    }],
                },
                options: {
                    ...this._baseWeightOptions('Gross Weight Purchased'),
                    plugins: {
                        ...this._baseWeightOptions('Gross Weight Purchased').plugins,
                        legend: { display: false },
                        tooltip: {
                            ...this._baseWeightOptions('Gross Weight Purchased').plugins.tooltip,
                            callbacks: {
                                label: (ctx) => ` Gross Weight: ${ctx.raw.toFixed(3)} g`
                            }
                        }
                    },
                },
            });
        } else if (chartId === 'stockBalanceBarChart') {
            const data = this.state.stockBalanceProducts || [];
            const labels = data.map(d => d.name);
            const values = data.map(d => d.qty);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Stock Qty (gms)',
                        data: values,
                        backgroundColor: 'rgba(99,102,241,0.85)',
                        borderColor: '#6366f1',
                        borderWidth: 1,
                        borderRadius: 6,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: {
                                label: (ctx) => ` Stock Balance: ${ctx.raw.toFixed(3)} g`
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(148,163,184,0.08)' },
                            ticks: { color: '#64748b', font: { size: 10 } }
                        },
                        y: {
                            grid: { color: 'rgba(148,163,184,0.08)' },
                            ticks: { color: '#94a3b8', font: { size: 11 }, callback: v => this.shortNum(v) + ' gms' }
                        }
                    }
                }
            });
        } else if (chartId === 'salesByBranchBarChart') {
            const data = this.state.salesByBranch || [];
            const labels = data.map(d => d.name);
            const values = data.map(d => d.revenue);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Total Sales (gms)',
                        data: values,
                        backgroundColor: 'rgba(245,158,11,0.85)',
                        borderColor: '#f59e0b',
                        borderWidth: 1,
                        borderRadius: 6,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: {
                                label: (ctx) => ` Sales: ${ctx.raw.toFixed(3)} g`
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(148,163,184,0.08)' },
                            ticks: { color: '#64748b', font: { size: 10 } }
                        },
                        y: {
                            grid: { color: 'rgba(148,163,184,0.08)' },
                            ticks: { color: '#94a3b8', font: { size: 11 }, callback: v => this.shortNum(v) + ' gms' }
                        }
                    }
                }
            });
        } else if (chartId === 'inventoryPieChart') {
            const data = this.state.inventoryCategory || [];
            const labels = data.map(d => d.label);
            const values = data.map(d => d.value);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'pie',
                data: {
                    labels,
                    datasets: [{
                        data: values,
                        backgroundColor: PALETTE.slice(0, labels.length),
                        borderColor: 'transparent',
                        borderWidth: 0,
                        hoverOffset: 10,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#64748b', font: { size: 12 } } },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw.toFixed(3)} g` }
                        }
                    },
                },
            });
        } else if (chartId === 'productDoughnutChart') {
            const data = this.state.productCategory || [];
            const labels = data.map(d => d.label);
            const values = data.map(d => d.value);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'doughnut',
                data: {
                    labels,
                    datasets: [{
                        data: values,
                        backgroundColor: PALETTE.slice(0, labels.length).map(c => c + 'cc'),
                        borderColor: 'transparent',
                        borderWidth: 0,
                        hoverOffset: 10,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    cutout: '60%',
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#64748b', font: { size: 12 } } },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw.toFixed(3)} g` }
                        }
                    },
                },
            });
        } else if (chartId === 'purityPieChart') {
            const data = this.state.jewelleryPurity || [];
            const labels = data.map(d => d.label);
            const values = data.map(d => d.qty);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'pie',
                data: {
                    labels,
                    datasets: [{
                        data: values,
                        backgroundColor: GOLD_PALETTE.slice(0, labels.length),
                        borderColor: 'transparent',
                        borderWidth: 0,
                        hoverOffset: 10,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#64748b', font: { size: 12 } } },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw.toFixed(3)} g` }
                        }
                    },
                },
            });
        } else if (chartId === 'dateBranchCollectionChart') {
            this.charts.maximizedChartCanvas = this._createCollectionChart(canvas);
        } else if (chartId === 'salesmanBarChart') {
            const data = this.state.salesBySalesman || [];
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: data.map(d => d.salesman),
                    datasets: [
                        {
                            label: 'Actual Sales (gms)',
                            data: data.map(d => d.revenue),
                            backgroundColor: '#6366f1cc',
                            borderColor: '#6366f1',
                            borderWidth: 1,
                            borderRadius: 6,
                        },
                        {
                            label: 'Target Sales (gms)',
                            data: data.map(d => d.target || 0),
                            backgroundColor: '#10b981cc',
                            borderColor: '#10b981',
                            borderWidth: 1,
                            borderRadius: 6,
                        }
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'top', labels: { color: '#94a3b8', font: { size: 12 } } },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: {
                                label: (ctx) => {
                                    const idx = ctx.dataIndex;
                                    const item = data[idx];
                                    const actual = item.revenue;
                                    const target = item.target || 0;
                                    const pct = target > 0 ? ((actual / target) * 100).toFixed(1) : 'N/A';
                                    if (ctx.datasetIndex === 0) {
                                        return ` Actual: ${this.formatWeight(actual)} (${pct}% of target)`;
                                    } else {
                                        return ` Target: ${this.formatWeight(target)}`;
                                    }
                                }
                            }
                        }
                    },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: '#64748b', font: { size: 12 } } },
                        y: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#94a3b8', font: { size: 12 }, callback: v => this.shortNum(v) + ' gms' } }
                    }
                }
            });
        } else if (chartId === 'salesStatePieChart') {
            const data = this.state.salesStateDistribution || [];
            const labels = data.map(d => d.label);
            const values = data.map(d => d.value);
            const colors = ['#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#ec4899'];
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'doughnut',
                data: {
                    labels,
                    datasets: [{
                        data: values,
                        backgroundColor: colors.slice(0, labels.length),
                        borderWidth: 0,
                        borderColor: 'transparent',
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    cutout: '65%',
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#64748b', font: { size: 12 } } },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            titleColor: '#e2e8f0',
                            bodyColor: '#94a3b8',
                            borderColor: 'rgba(99,102,241,0.3)',
                            borderWidth: 1,
                            padding: 12,
                            callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw} orders` }
                        }
                    }
                }
            });
        } else if (chartId === 'purchaseLineChart') {
            const data = this.state.purchaseMonthly || [];
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: data.map(d => d.month),
                    datasets: [{
                        label: 'Gross Weight Purchased (gms)',
                        data: data.map(d => d.total),
                        backgroundColor: 'rgba(245, 158, 11, 0.85)',
                        borderColor: '#f59e0b',
                        borderWidth: 1,
                        borderRadius: 6
                    }]
                },
                options: this._baseWeightOptions('Gross Weight Purchased')
            });
        } else if (chartId === 'topBuyersBarChart') {
            const data = this.state.topBuyers || [];
            const labels = data.map(d => d.name);
            const values = data.map(d => d.total);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Gross Weight (gms)',
                        data: values,
                        backgroundColor: 'rgba(245,158,11,0.85)',
                        borderColor: '#f59e0b',
                        borderWidth: 1,
                        borderRadius: 6,
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` Weight: ${ctx.raw.toFixed(3)} g` }
                        }
                    },
                    scales: {
                        x: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#64748b', font: { size: 12 } } },
                        y: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#94a3b8', font: { size: 12 }, callback: (v) => v.toFixed(1) + ' gms' } }
                    }
                }
            });
        } else if (chartId === 'bestSellingCategoriesChart') {
            const data = this.state.bestSellingCategories || [];
            const labels = data.map(d => d.name);
            const quantities = data.map(d => d.qty);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Weight (gms)',
                        data: quantities,
                        backgroundColor: 'rgba(99, 102, 241, 0.85)',
                        borderColor: '#6366f1',
                        borderWidth: 1,
                        borderRadius: 6,
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` Weight: ${this.formatWeight(ctx.raw)}` }
                        }
                    },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 12 }, maxRotation: 45, minRotation: 45 } },
                        y: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#64748b', font: { size: 12 }, callback: (v) => this.shortNum(v) } }
                    }
                }
            });
        } else if (chartId === 'bestSellersByQtyChart') {
            const data = this.state.bestSellersByQty || [];
            const labels = data.map(d => d.name);
            const quantities = data.map(d => d.qty);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Weight (gms)',
                        data: quantities,
                        backgroundColor: 'rgba(16, 185, 129, 0.85)',
                        borderColor: '#10b981',
                        borderWidth: 1,
                        borderRadius: 6,
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` Weight: ${this.formatWeight(ctx.raw)}` }
                        }
                    },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 12 }, maxRotation: 45, minRotation: 45 } },
                        y: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#64748b', font: { size: 12 }, callback: (v) => this.shortNum(v) } }
                    }
                }
            });
        } else if (chartId === 'stockByLocationChart') {
            const data = this.state.stockByLocation || [];
            const labels = data.map(d => d.location);
            const values = data.map(d => d.qty);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'pie',
                data: {
                    labels,
                    datasets: [{
                        data: values,
                        backgroundColor: PALETTE.slice(0, labels.length).map(c => c + 'cc'),
                        borderColor: 'transparent',
                        borderWidth: 0,
                        hoverOffset: 10,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#64748b', font: { size: 12 } } },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` Weight: ${this.formatNumber(ctx.raw)} gms` }
                        }
                    }
                }
            });
        } else if (chartId === 'expenseBulletChart') {
            const bulletData = this.state.expenseBulletData || [];
            const labels = bulletData.map(item => item.category);
            const actuals = bulletData.map(item => item.actual);
            const backgrounds = bulletData.map(item => item.actual > item.target ? '#ef4444' : '#6366f1');
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Actual Spend',
                        data: actuals,
                        backgroundColor: backgrounds,
                        borderColor: 'transparent',
                        borderWidth: 0,
                        borderRadius: { topLeft: 4, topRight: 4 },
                        barThickness: 30
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            titleColor: '#f8fafc',
                            bodyColor: '#f8fafc',
                            callbacks: {
                                label: (ctx) => {
                                    const item = bulletData[ctx.dataIndex];
                                    if (!item) return '';
                                    return ` Actual: ${this.formatCurrency(item.actual)} (Budget: ${this.formatCurrency(item.target)})`;
                                }
                            }
                        },
                        bulletHelper: { data: bulletData }
                    },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', callback: (val) => this.formatCurrency(val) } }
                    }
                },
                plugins: [{
                    id: 'bulletChartPlugin',
                    beforeDatasetsDraw(chart) {
                        const { ctx, scales: { x, y } } = chart;
                        const helpers = chart.config.options.plugins.bulletHelper;
                        if (!helpers || !helpers.data) return;
                        helpers.data.forEach((item, index) => {
                            const centerX = x.getPixelForValue(index);
                            const barWidth = 50;
                            const leftX = centerX - barWidth / 2;
                            const bottomY = y.getPixelForValue(0);
                            const maxVal = Math.max(item.actual, item.target) * 1.1;
                            const yLow = y.getPixelForValue(item.range_low);
                            const yMed = y.getPixelForValue(item.range_med);
                            const yHigh = y.getPixelForValue(maxVal);
                            ctx.fillStyle = 'rgba(16, 185, 129, 0.08)';
                            ctx.fillRect(leftX, yLow, barWidth, bottomY - yLow);
                            ctx.fillStyle = 'rgba(245, 158, 11, 0.08)';
                            ctx.fillRect(leftX, yMed, barWidth, yLow - yMed);
                            ctx.fillStyle = 'rgba(244, 63, 94, 0.05)';
                            ctx.fillRect(leftX, yHigh, barWidth, yMed - yHigh);
                        });
                    }
                }]
            });
        } else if (chartId === 'vendorAmountBarChart') {
            const vendorsData = this.state.topVendors || [];
            const labels = vendorsData.map(item => item.vendor);
            const totals = vendorsData.map(item => item.total);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Gross Weight (gms)',
                        data: totals,
                        backgroundColor: 'rgba(59, 130, 246, 0.85)',
                        borderColor: '#3b82f6',
                        borderWidth: 1,
                        borderRadius: { topLeft: 4, topRight: 4 },
                        barThickness: 24
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` Weight: ${this.formatWeight(ctx.raw)}` }
                        }
                    },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', callback: (val) => this.formatWeight(val) } }
                    }
                }
            });
        } else if (chartId === 'invoicedMonthlyBarChart') {
            const data = this.state.invoicedMonthly || [];
            const { labels, datasets } = this._prepareInvoicedMonthlyDatasets(data);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: datasets
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top',
                            labels: { color: '#64748b', font: { size: 10 }, boxWidth: 12 }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw.toFixed(3)} gms` }
                        }
                    },
                    scales: {
                        x: { stacked: true, grid: { display: false }, ticks: { color: '#94a3b8' } },
                        y: { stacked: true, grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', callback: (val) => this.formatWeight(val) } }
                    }
                }
            });
        } else if (chartId === 'invoicedCategoryChart') {
            const data = this.state.invoicedTopCategories || [];
            const labels = data.map(item => item.name);
            const values = data.map(item => item.value);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: values,
                        backgroundColor: PALETTE.slice(0, labels.length).map(c => c + 'cc'),
                        borderColor: 'transparent',
                        borderWidth: 0,
                        hoverOffset: 10,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    cutout: '60%',
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { color: '#64748b', font: { size: 12 } } },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` ${ctx.label}: ${this.formatWeight(ctx.raw)}` }
                        }
                    },
                }
            });
        } else if (chartId === 'branchTargetBarChart') {
            const data = this.state.branchWiseTarget || [];
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: data.map(d => d.branch),
                    datasets: [
                        {
                            label: 'Actual Sales (gms)',
                            data: data.map(d => d.actual),
                            backgroundColor: '#3b82f6cc',
                            borderColor: '#3b82f6',
                            borderWidth: 1,
                            borderRadius: 6,
                        },
                        {
                            label: 'Target Sales (gms)',
                            data: data.map(d => d.target || 0),
                            backgroundColor: '#10b981cc',
                            borderColor: '#10b981',
                            borderWidth: 1,
                            borderRadius: 6,
                        }
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'top', labels: { color: '#94a3b8', font: { size: 12 } } },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: {
                                label: (ctx) => {
                                    const idx = ctx.dataIndex;
                                    const item = data[idx];
                                    const actual = item.actual;
                                    const target = item.target || 0;
                                    const pct = target > 0 ? ((actual / target) * 100).toFixed(1) : 'N/A';
                                    if (ctx.datasetIndex === 0) {
                                        return ` Actual: ${this.formatWeight(actual)} (${pct}% of target)`;
                                    } else {
                                        return ` Target: ${this.formatWeight(target)}`;
                                    }
                                }
                            }
                        }
                    },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: '#64748b', font: { size: 12 } } },
                        y: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#94a3b8', font: { size: 12 }, callback: v => this.shortNum(v) + ' gms' } }
                    }
                }
            });
        } else if (chartId === 'schemesTrendChart') {
            const data = this.state.schemesMonthlyTrend || [];
            const labels = data.map(item => item.label);
            const values = data.map(item => item.value);
            this.charts.maximizedChartCanvas = new window.Chart(canvas, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'New Enrollments Count',
                        data: values,
                        backgroundColor: 'rgba(56, 189, 248, 0.85)',
                        borderColor: '#38bdf8',
                        borderWidth: 1,
                        borderRadius: { topLeft: 4, topRight: 4 },
                        barThickness: 24
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15,23,42,0.9)',
                            callbacks: { label: (ctx) => ` Enrollments: ${ctx.raw}` }
                        }
                    },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
                        y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', callback: (val) => Math.floor(val) } }
                    }
                }
            });
        }
    }

    formatState(state) {
        const map = {
            'draft': 'Quotation',
            'sent': 'Quotation Sent',
            'sale': 'Sales Order',
            'done': 'Locked',
            'cancel': 'Cancelled'
        };
        return map[state] || state;
    }

    openSaleOrder(orderId) {
        if (!orderId) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'sale.order',
            res_id: orderId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openProductTemplate(productTemplateId) {
        if (!productTemplateId) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'product.template',
            res_id: productTemplateId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openPurchaseOrder(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'purchase.order',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openProductCategory(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'product.category',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openStockLocation(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'stock.location',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openExpense(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hr.expense',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openEmployee(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'hr.employee',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openPartner(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'res.partner',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openUser(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'res.users',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openInvoice(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'account.move',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openSchemeEnrollment(id) {
        if (!id) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'jewellery.scheme.enrollment',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

}

registry.category("actions").add("jw_business_dashboard", JwBusinessDashboard);
