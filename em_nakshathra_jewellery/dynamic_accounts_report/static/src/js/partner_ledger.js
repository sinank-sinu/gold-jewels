/** @odoo-module */
const { Component } = owl;
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRef, useState } from "@odoo/owl";
import { BlockUI } from "@web/core/ui/block_ui";
import { download } from "@web/core/network/download";
const actionRegistry = registry.category("actions");

class PartnerLedger extends owl.Component {
    setup() {
        super.setup(...arguments);
        this.initial_render = true;
        this.orm = useService('orm');
        this.action = useService('action');
        this.tbody = useRef('tbody');
        this.unfoldButton = useRef('unfoldButton');
        this.dialog = useService("dialog");
        this._searchTimeout = null;
        this.state = useState({
            partners: null,
            visible_partners: null,
            data: null,
            total: null,
            title: null,
            currency: null,
            filter_applied: null,
            selected_partner: [],
            selected_partner_rec: [],
            total_debit: null,
            total_credit: null,
            partner_list: null,
            total_list: null,
            date_range: null,
            account: null,
            options: null,
            search_partner_term: "",
            message_list : [],
            // Server-side pagination state (80 records per page)
            current_page: 1,
            page_size: 80,
            total_pages: 1,
            total_partners: 0,
            is_loading: false,
            partner_line_page: {},
        });
        this.load_data();
    }

    get isFirstPageDisabled() {
        return this.state.current_page <= 1 || this.state.is_loading;
    }

    get isLastPageDisabled() {
        return this.state.current_page >= this.state.total_pages || this.state.is_loading;
    }

    getPartnerLines(partner) {
        const lines = (this.state.data && this.state.data[partner]) || [];
        const page = (this.state.partner_line_page && this.state.partner_line_page[partner]) || 1;
        const pageSize = 80;
        const start = (page - 1) * pageSize;
        return lines.slice(start, start + pageSize);
    }

    getPartnerLinePage(partner) {
        return (this.state.partner_line_page && this.state.partner_line_page[partner]) || 1;
    }

    getPartnerTotalLinePages(partner) {
        const total = (this.state.data && this.state.data[partner] && this.state.data[partner].length) || 0;
        return Math.max(1, Math.ceil(total / 80));
    }

    getPartnerLineRangeText(partner) {
        const total = (this.state.data && this.state.data[partner] && this.state.data[partner].length) || 0;
        if (total === 0) return "0 transactions";
        const page = this.getPartnerLinePage(partner);
        const start = (page - 1) * 80 + 1;
        const end = Math.min(page * 80, total);
        return `${start}–${end} of ${total}`;
    }

    getTotalLinesCount(partner) {
        const lines = (this.state.data && this.state.data[partner]) || [];
        return lines.length;
    }

    isPartnerFirstLinePage(partner) {
        return this.getPartnerLinePage(partner) <= 1;
    }

    isPartnerLastLinePage(partner) {
        return this.getPartnerLinePage(partner) >= this.getPartnerTotalLinePages(partner);
    }

    onPrevPartnerLines(ev) {
        const partner = ev.currentTarget.getAttribute("data-partner");
        if (partner) {
            if (!this.state.partner_line_page) {
                this.state.partner_line_page = {};
            }
            const currentPage = this.state.partner_line_page[partner] || 1;
            if (currentPage > 1) {
                this.state.partner_line_page[partner] = currentPage - 1;
            }
        }
    }

    onNextPartnerLines(ev) {
        const partner = ev.currentTarget.getAttribute("data-partner");
        if (partner) {
            if (!this.state.partner_line_page) {
                this.state.partner_line_page = {};
            }
            const currentPage = this.state.partner_line_page[partner] || 1;
            const maxPages = this.getPartnerTotalLinePages(partner);
            if (currentPage < maxPages) {
                this.state.partner_line_page[partner] = currentPage + 1;
            }
        }
    }

    async load_data() {
        /**
         * Loads the initial data for the partner ledger report (page 1).
         */
        await this.fetchLedgerData(1);
    }

    async fetchLedgerData(page = 1) {
        /**
         * Fetches paginated partner ledger data from backend (80 partners per page).
         */
        this.state.is_loading = true;
        let partner_list = [];
        let partner_totals = {};
        let totalDebitSum = 0;
        let totalCreditSum = 0;
        let currency = this.state.currency;
        let pagination = null;
        const action_title = this.props.action.display_name;

        try {
            const result = await this.orm.call(
                "account.partner.ledger",
                "get_filter_values",
                [
                    this.state.selected_partner,
                    this.state.date_range,
                    this.state.account,
                    this.state.options,
                    page,
                    this.state.page_size || 80,
                    this.state.search_partner_term || null,
                ]
            );

            $.each(result, function (index, value) {
                if (index === 'partner_totals') {
                    partner_totals = value;
                    Object.values(partner_totals).forEach(pTot => {
                        if (pTot && pTot.currency_id) {
                            currency = pTot.currency_id;
                        }
                        totalDebitSum += pTot.total_debit || 0;
                        totalCreditSum += pTot.total_credit || 0;
                    });
                } else if (index === 'pagination') {
                    pagination = value;
                } else {
                    partner_list.push(index);
                }
            });

            this.state.data = result;
            this.state.partners = partner_list;
            this.state.visible_partners = partner_list;
            this.state.partner_list = partner_list;
            this.state.total_list = partner_totals;
            this.state.total = partner_totals;
            this.state.currency = currency;
            this.state.total_debit = Math.round(totalDebitSum * 100) / 100;
            this.state.total_credit = Math.round(totalCreditSum * 100) / 100;
            this.state.title = action_title;
            this.state.partner_line_page = {};

            if (pagination) {
                this.state.current_page = pagination.current_page;
                this.state.page_size = pagination.page_size;
                this.state.total_partners = pagination.total_partners;
                this.state.total_pages = pagination.total_pages;
            } else {
                this.state.current_page = page;
                this.state.page_size = 80;
                this.state.total_pages = 1;
                this.state.total_partners = partner_list.length;
            }

            if (this.unfoldButton && this.unfoldButton.el && this.unfoldButton.el.classList.contains("selected-filter")) {
                this.unfoldButton.el.classList.remove("selected-filter");
            }
        } catch (e) {
            console.error("Error fetching partner ledger data:", e);
        } finally {
            this.state.is_loading = false;
        }
    }

        async printPdf(ev) {
        /**
         * Generates and displays a PDF report for the partner ledger.
         *
         * @param {Event} ev - The event object triggered by the action.
         * @returns {Promise} - A promise that resolves to the result of the action.
         */
        ev.preventDefault();
        let partner_list = []
        let partner_value = []
        let partner_totals = ''
        let totals = {
            'total_debit':this.state.total_debit,
            'total_credit':this.state.total_credit,
            'currency':this.state.currency,
        }
        var action_title = this.props.action.display_name;
        return this.action.doAction({
            'type': 'ir.actions.report',
            'report_type': 'qweb-pdf',
            'report_name': 'dynamic_accounts_report.partner_ledger',
            'report_file': 'dynamic_accounts_report.partner_ledger',
            'data': {
                'partners': this.state.partners,
                'filters': this.filter(),
                'grand_total': totals,
                'data': this.state.data,
                'total': this.state.total,
                'title': action_title,
                'report_name': this.props.action.display_name
            },
            'display_name': this.props.action.display_name,
        });
    }
    filter() {
    var self=this;
    let startDate, endDate;
    let startYear, startMonth, startDay, endYear, endMonth, endDay;
        if (self.state.date_range){
            const today = new Date();
            if (self.state.date_range === 'year') {
                startDate = new Date(today.getFullYear(), 0, 1);
                endDate = new Date(today.getFullYear(), 11, 31);
            } else if (self.state.date_range === 'quarter') {
                const currentQuarter = Math.floor(today.getMonth() / 3);
                startDate = new Date(today.getFullYear(), currentQuarter * 3, 1);
                endDate = new Date(today.getFullYear(), (currentQuarter + 1) * 3, 0);
            } else if (self.state.date_range === 'month') {
                startDate = new Date(today.getFullYear(), today.getMonth(), 1);
                endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
            } else if (self.state.date_range === 'last-month') {
                startDate = new Date(today.getFullYear(), today.getMonth() - 1, 1);
                endDate = new Date(today.getFullYear(), today.getMonth(), 0);
            } else if (self.state.date_range === 'last-year') {
                startDate = new Date(today.getFullYear() - 1, 0, 1);
                endDate = new Date(today.getFullYear() - 1, 11, 31);
            } else if (self.state.date_range === 'last-quarter') {
                const lastQuarter = Math.floor((today.getMonth() - 3) / 3);
                startDate = new Date(today.getFullYear(), lastQuarter * 3, 1);
                endDate = new Date(today.getFullYear(), (lastQuarter + 1) * 3, 0);
            }
        // Get the date components for start and end dates
        if (startDate) {
        startYear = startDate.getFullYear();
        startMonth = startDate.getMonth() + 1;
        startDay = startDate.getDate();
        }
        if (endDate) {
        endYear = endDate.getFullYear();
        endMonth = endDate.getMonth() + 1;
        endDay = endDate.getDate();
        }
        }
        let filters = {
            'partner': self.state.selected_partner_rec,
            'account': self.state.account,
            'options': self.state.options,
            'start_date': null,
            'end_date': null,
        };
        // Check if start and end dates are available before adding them to the filters object
        if (startYear !== undefined && startMonth !== undefined && startDay !== undefined &&
            endYear !== undefined && endMonth !== undefined && endDay !== undefined) {
            filters['start_date'] = `${startYear}-${startMonth < 10 ? '0' : ''}${startMonth}-${startDay < 10 ? '0' : ''}${startDay}`;
            filters['end_date'] = `${endYear}-${endMonth < 10 ? '0' : ''}${endMonth}-${endDay < 10 ? '0' : ''}${endDay}`;
        }
        return filters
    }
    async print_xlsx() {
        /**
         * Generates and downloads an XLSX report for the partner ledger.
         */
        var self = this;

        let partner_list = []
        let partner_value = []
        let partner_totals = ''
        let totals = {
            'total_debit':this.state.total_debit,
            'total_credit':this.state.total_credit,
            'currency':this.state.currency,
        }
        var action_title = self.props.action.display_name;
        var datas = {
            'partners': self.state.partners,
            'data': self.state.data,
            'total': self.state.total,
            'title': action_title,
            'filters': this.filter(),
            'grand_total': totals,
        }
        var action = {
            'data': {
                'model': 'account.partner.ledger',
                'data': JSON.stringify(datas),
                'output_format': 'xlsx',
                'report_action': self.props.action.xml_id,
                'report_name': action_title,
            },
        };
        BlockUI;
        await download({
            url: '/xlsx_report',
            data: action.data,
            complete: () => unblockUI,
            error: (error) => self.call('crash_manager', 'rpc_error', error),
        });
    }
    gotoJournalEntry(ev) {
        /**
         * Navigates to the journal entry form view based on the selected event target.
         *
         * @param {Event} ev - The event object triggered by the action.
         * @returns {Promise} - A promise that resolves to the result of the action.
         */
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: 'account.move',
            res_id: parseInt(ev.target.attributes["data-id"].value, 10),
            views: [[false, "form"]],
            target: "current",
        });
    }
    gotoJournalItem(ev) {
        /**
         * Navigates to the journal items list view based on the selected event target.
         *
         * @param {Event} ev - The event object triggered by the action.
         * @returns {Promise} - A promise that resolves to the result of the action.
         */
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: 'account.move.line',
            name: "Journal Items",
            views: [[false, "list"]],
            domain: [["partner_id", "=", parseInt(ev.target.attributes["data-id"].value, 10)], ['account_type', 'in', ['liability_payable', 'asset_receivable']]],
            target: "current",
        });
    }
    openPartner(ev) {
        /**
         * Opens the partner form view based on the selected event target.
         *
         * @param {Event} ev - The event object triggered by the action.
         * @returns {Promise} - A promise that resolves to the result of the action.
         */
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: 'res.partner',
            res_id: parseInt(ev.target.attributes["data-id"].value, 10),
            views: [[false, "form"]],
            target: "current",
        });
    }
    async applyFilter(val, ev, is_delete = false) {
        /**
         * Applies filters to the partner ledger report based on the provided values.
         *
         * @param {any} val - The value of the filter.
         * @param {Event} ev - The event object triggered by the action.
         * @param {boolean} is_delete - Indicates whether the filter value is being deleted.
         */
        let partner_list = []
        let partner_value = []
        let partner_totals = ''
        let month = null
        this.state.partners = null
        this.state.visible_partners = null
        this.state.data = null
        this.state.total = null
        this.state.filter_applied = true;
        let totalDebitSum = 0;
        let totalCreditSum = 0;
        if (ev) {
            if (ev.input && ev.input.attributes.placeholder.value == 'Partner' && !is_delete) {
                this.state.selected_partner.push(val[0].id)
                this.state.selected_partner_rec.push(val[0])
            } else if (is_delete) {
                let index = this.state.selected_partner_rec.indexOf(val)
                this.state.selected_partner_rec.splice(index, 1)
                this.state.selected_partner = this.state.selected_partner_rec.map((rec) => rec.id)
            }
        }
        else {
            if (val.target.name === 'start_date') {
                this.state.date_range = {
                    ...this.state.date_range,
                    start_date: val.target.value
                };
            } else if (val.target.name === 'end_date') {
                this.state.date_range = {
                    ...this.state.date_range,
                    end_date: val.target.value
                };
            } else if (val.target.attributes["data-value"].value == 'month') {
                this.state.date_range = val.target.attributes["data-value"].value
            } else if (val.target.attributes["data-value"].value == 'year') {
                this.state.date_range = val.target.attributes["data-value"].value
            } else if (val.target.attributes["data-value"].value == 'quarter') {
                this.state.date_range = val.target.attributes["data-value"].value
            } else if (val.target.attributes["data-value"].value == 'last-month') {
                this.state.date_range = val.target.attributes["data-value"].value
            } else if (val.target.attributes["data-value"].value == 'last-year') {
                this.state.date_range = val.target.attributes["data-value"].value
            } else if (val.target.attributes["data-value"].value == 'last-quarter') {
                this.state.date_range = val.target.attributes["data-value"].value
            } else if (val.target.attributes["data-value"].value === 'receivable') {
                // Check if the target has 'selected-filter' class
                if (val.target.classList.contains("selected-filter")) {
                    // Remove 'receivable' key from account
                    const { Receivable, ...updatedAccount } = this.state.account;
                    this.state.account = updatedAccount;
                    val.target.classList.remove("selected-filter");
                } else {
                    // Update receivable property in account
                    this.state.account = {
                        ...this.state.account,
                        'Receivable': true
                    };
                    val.target.classList.add("selected-filter"); // Add class "selected-filter"
                }
            } else if (val.target.attributes["data-value"].value === 'payable') {
                // Check if the target has 'selected-filter' class
                if (val.target.classList.contains("selected-filter")) {
                    // Remove 'receivable' key from account
                    const { Payable, ...updatedAccount } = this.state.account;
                    this.state.account = updatedAccount;
                    val.target.classList.remove("selected-filter");
                } else {
                    // Update receivable property in account
                    this.state.account = {
                        ...this.state.account,
                        'Payable': true
                    };
                    val.target.classList.add("selected-filter"); // Add class "selected-filter"
                }
            } else if (val.target.attributes["data-value"].value === 'draft') {
                // Check if the target has 'selected-filter' class
                if (val.target.classList.contains("selected-filter")) {
                    // Remove 'receivable' key from account
                    const { draft, ...updatedAccount } = this.state.options;
                    this.state.options = updatedAccount;
                    val.target.classList.remove("selected-filter");
                } else {
                    // Update receivable property in account
                    this.state.options = {
                        ...this.state.options,
                        'draft': true
                    };
                    val.target.classList.add("selected-filter"); // Add class "selected-filter"
                }
            }
        }
        await this.fetchLedgerData(1);
    }
    getDomain() {
        return [];
    }
    async unfoldAll(ev) {
        /**
         * Unfolds all items in the table body if the event target does not have the 'selected-filter' class,
         * or folds all items if the event target has the 'selected-filter' class.
         *
         * @param {Event} ev - The event object triggered by the action.
         */
        if (!ev.target.classList.contains("selected-filter")) {
            for (var length = 0; length < this.tbody.el.children.length; length++) {
                $(this.tbody.el.children[length])[0].classList.add('show')
            }
            ev.target.classList.add("selected-filter");
        } else {
            for (var length = 0; length < this.tbody.el.children.length; length++) {
                $(this.tbody.el.children[length])[0].classList.remove('show')
            }
            ev.target.classList.remove("selected-filter");
        }
    }

    // Pagination handlers
    async onFirstPage() {
        if (this.state.current_page > 1 && !this.state.is_loading) {
            await this.fetchLedgerData(1);
        }
    }

    async onPrevPage() {
        if (this.state.current_page > 1 && !this.state.is_loading) {
            await this.fetchLedgerData(this.state.current_page - 1);
        }
    }

    async onNextPage() {
        if (this.state.current_page < this.state.total_pages && !this.state.is_loading) {
            await this.fetchLedgerData(this.state.current_page + 1);
        }
    }

    async onLastPage() {
        if (this.state.current_page < this.state.total_pages && !this.state.is_loading) {
            await this.fetchLedgerData(this.state.total_pages);
        }
    }

    async onPageInputKeydown(ev) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            let p = parseInt(ev.target.value, 10);
            if (isNaN(p) || p < 1) p = 1;
            if (p > this.state.total_pages) p = this.state.total_pages;
            await this.fetchLedgerData(p);
        }
    }

    // Search partner handlers (queries database live with debounce)
    onSearchPartner(ev) {
        const term = ev.target.value;
        this.state.search_partner_term = term;
        if (this._searchTimeout) {
            clearTimeout(this._searchTimeout);
        }
        this._searchTimeout = setTimeout(() => {
            this.fetchLedgerData(1);
        }, 350);
    }

    onSearchPartnerKeydown(ev) {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            if (this._searchTimeout) {
                clearTimeout(this._searchTimeout);
            }
            this.fetchLedgerData(1);
        }
    }

    clearPartnerSearch() {
        this.state.search_partner_term = "";
        if (this._searchTimeout) {
            clearTimeout(this._searchTimeout);
        }
        this.fetchLedgerData(1);
    }
}
PartnerLedger.defaultProps = {
    resIds: [],
};
PartnerLedger.template = 'pl_template_new';
actionRegistry.add("p_l", PartnerLedger);
