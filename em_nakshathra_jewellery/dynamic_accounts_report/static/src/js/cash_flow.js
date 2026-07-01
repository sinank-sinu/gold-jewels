/** @odoo-module */
const { Component } = owl;
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRef, useState } from "@odoo/owl";
import { BlockUI } from "@web/core/ui/block_ui";
import { download } from "@web/core/network/download";
const actionRegistry = registry.category("actions");

class CashBook extends owl.Component {
    async setup() {
        super.setup(...arguments);
        this.initial_render = true;
        this.orm = useService('orm');
        this.action = useService('action');
        this.dialog = useService("dialog");
        this.tbody = useRef('tbody');
        this.unfoldButton = useRef('unfoldButton');
        this.state = useState({
            move_line: null,
            account_meta: {},   // {acc_name: {total, offset, account_id, expanded}}
            data: null,
            total: null,
            accounts: null,
            filter_applied: null,
            selected_partner: [],
            selected_partner_rec: [],
            date_range: null,
            options: null,
            selected_account_list: [],
            total_debit: null,
            total_credit: null,
            currency: null,
            message_list : [],
        });
        this.PAGE_SIZE = 500;
        this.load_data(self.initial_render = true);
    }

    async load_data() {
        let move_line_list = []
        let move_lines_total = ''
        let accounts = [];
        var self = this;
        let totalDebitSum = 0;
        let totalCreditSum = 0;
        let currency;
        var action_title = self.props.action.display_name;
        try {
            var self = this;
            self.state.data = await self.orm.call("cash.book.report", "view_report", []);
            for (const index in self.state.data) {
                const value = self.state.data[index];
                if (index !== 'move_lines_total' && index !== 'accounts' && index !== 'branches') {
                    move_line_list.push(index);
                } else if (index === 'accounts') {
                    self.state.accounts = value;
                } else if (index === 'move_lines_total') {
                    move_lines_total = value;
                    for (const moveLine of Object.values(move_lines_total)) {
                        currency = moveLine.currency_id;
                        totalDebitSum += moveLine.total_debit || 0;
                        totalCreditSum += moveLine.total_credit || 0;
                    }
                }
            }
            self.state.move_line = move_line_list
            self.state.total = move_lines_total
            self.state.currency = currency
            self.state.total_debit = totalDebitSum.toFixed(2)
            self.state.total_credit = totalCreditSum.toFixed(2)
        }
        catch (el) {
            window.location.href;
        }
    }

    // Lazy load line pagination helper
    async _fetchAccountPage(account_name, account_id, offset) {
        const known_total = this.state.account_meta[account_name]
            ? this.state.account_meta[account_name].total
            : (this.state.total[account_name]
                ? this.state.total[account_name].line_count
                : null);

        const result = await this.orm.call(
            "cash.book.report", "get_account_lines",
            [account_id,
             null, // resolved in python
             this.state.selected_partner || null,
             this.state.date_range || null,
             this.state.options || null,
             this.state.selected_branch_list || null, // branch_ids
             this.PAGE_SIZE,
             offset,
             known_total
            ]
        );
        this.state.data[account_name] = result.lines;
        this.state.account_meta[account_name] = {
            total:      result.total,
            offset:     result.offset,
            account_id: account_id,
            expanded:   true,
        };
    }

    async expandAccount(account_name, account_id) {
        const meta = this.state.account_meta[account_name];
        if (meta) {
            meta.expanded = !meta.expanded;
            return;
        }
        await this._fetchAccountPage(account_name, account_id, 0);
    }

    async nextAccountPage(account_name) {
        const meta = this.state.account_meta[account_name];
        if (meta && meta.offset + this.PAGE_SIZE < meta.total) {
            await this._fetchAccountPage(
                account_name, meta.account_id, meta.offset + this.PAGE_SIZE);
        }
    }

    async prevAccountPage(account_name) {
        const meta = this.state.account_meta[account_name];
        if (meta && meta.offset > 0) {
            await this._fetchAccountPage(
                account_name, meta.account_id,
                Math.max(0, meta.offset - this.PAGE_SIZE));
        }
    }

    // Load ALL lines for print/export
    async _loadAllAccountLines() {
        const accounts = this.state.move_line || [];
        for (const account of accounts) {
            if (!this.state.total || !this.state.total[account]) continue;
            const acc_id = this.state.total[account]['account_id'];
            const result = await this.orm.call(
                "cash.book.report", "get_account_lines",
                [acc_id,
                 null,
                 this.state.selected_partner || null,
                 this.state.date_range || null,
                 this.state.options || null,
                 this.state.selected_branch_list || null,
                 0,   // limit=0 -> no limit
                 0,
                ]
            );
            this.state.data[account] = result.lines;
        }
    }

    gotoJournalEntry(ev) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: 'account.move',
            res_id: parseInt(ev.target.attributes["data-id"].value, 10),
            views: [[false, "form"]],
            target: "current",
        });
    }

    getDomain() {
        return [];
    }

    async printPdf(ev) {
        ev.preventDefault();
        var self = this;
        // Fetch all lines before printing
        await this._loadAllAccountLines();
        let totals = {
            'total_debit':this.state.total_debit,
            'total_credit':this.state.total_credit,
            'currency':this.state.currency,
        }
        var action_title = self.props.action.display_name;
        return self.action.doAction({
            'type': 'ir.actions.report',
            'report_type': 'qweb-pdf',
            'report_name': 'dynamic_accounts_report.cash_book',
            'report_file': 'dynamic_accounts_report.cash_book',
            'data': {
                'move_lines': self.state.move_line,
                'filters': this.filter(),
                'grand_total': totals,
                'data': self.state.data,
                'total': self.state.total,
                'title': action_title,
                'report_name': self.props.action.display_name
            },
            'display_name': self.props.action.display_name,
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
            else{
                 startDate = new Date(self.state.date_range.start_date);
                 endDate = new Date(self.state.date_range.end_date);
            }
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
        const selectedAccountIDs = Object.values(self.state.selected_account_list);
        const selectedAccountNames = selectedAccountIDs.map((accountID) => {
            const matchingAccount = Object.values(self.state.accounts).find(account => account.id === accountID);
            return matchingAccount ? matchingAccount.display_name : '';
        });
        let filters = {
            'partner': self.state.selected_partner_rec,
            'account': selectedAccountNames,
            'options': self.state.options,
            'start_date': null,
            'end_date': null,
        };
        if (startYear !== undefined && startMonth !== undefined && startDay !== undefined &&
            endYear !== undefined && endMonth !== undefined && endDay !== undefined) {
            filters['start_date'] = `${startYear}-${startMonth < 10 ? '0' : ''}${startMonth}-${startDay < 10 ? '0' : ''}${startDay}`;
            filters['end_date'] = `${endYear}-${endMonth < 10 ? '0' : ''}${endMonth}-${endDay < 10 ? '0' : ''}${endDay}`;
        }
        return filters;
    }

    async print_xlsx() {
        var self = this;
        // Fetch all lines before exporting
        await this._loadAllAccountLines();
        var action_title = self.props.action.display_name;
        let totals = {
            'total_debit':this.state.total_debit,
            'total_credit':this.state.total_credit,
            'currency':this.state.currency,
        }
        var datas = {
            'move_lines': self.state.move_line,
            'data': self.state.data,
            'total': self.state.total,
            'title': action_title,
            'filters': this.filter(),
            'grand_total': totals,
        }
        var action = {
            'data': {
                'model': 'cash.book.report',
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

    async applyFilter(val, ev, is_delete = false) {
        let move_line_list = []
        let move_line_totals = ''
        this.state.move_line = null
        this.state.data = null
        this.state.total = null
        this.state.account_meta = {}; // Clear active pagination states
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
            } else if (val.target.attributes["data-value"].value === 'draft') {
                if (val.target.classList.contains("selected-filter")) {
                    const { draft, ...updatedAccount } = this.state.options;
                    this.state.options = updatedAccount;
                    val.target.classList.remove("selected-filter");
                } else {
                    this.state.options = {
                        ...this.state.options,
                        'draft': true
                    };
                    val.target.classList.add("selected-filter");
                }
            } else if (val.target.attributes["data-value"].value == 'account') {
                if (!val.target.classList.contains("selected-filter")) {
                    this.state.selected_account_list.push(parseInt(val.target.attributes["data-id"].value, 10))
                    val.target.classList.add("selected-filter");
                } else {
                    const updatedList = this.state.selected_account_list.filter(item => item !== parseInt(val.target.attributes["data-id"].value, 10));
                    this.state.selected_account_list = updatedList
                    val.target.classList.remove("selected-filter");
                }
            }
        }
        let filtered_data = await this.orm.call("cash.book.report", "get_filter_values", [this.state.selected_partner, this.state.date_range, this.state.selected_account_list, this.state.options,]);
        for (const index in filtered_data) {
            const value = filtered_data[index];

            if (index !== 'move_lines_total' && index !== 'accounts' && index !== 'branches') {
                move_line_list.push(index);
            } else if (index === 'move_lines_total') {
                move_line_totals = value;
                for (const moveLine of Object.values(move_line_totals)) {
                    totalDebitSum += moveLine.total_debit || 0;
                    totalCreditSum += moveLine.total_credit || 0;
                }
            }
        }
        this.state.move_line = move_line_list
        this.state.data = filtered_data
        this.state.total = move_line_totals
        this.state.total_debit = totalDebitSum.toFixed(2)
        this.state.total_credit = totalCreditSum.toFixed(2)
        if ($(this.unfoldButton.el.classList).find("selected-filter")) {
            this.unfoldButton.el.classList.remove("selected-filter")
        }
    }

    async unfoldAll(ev) {
        if (!ev.target.classList.contains("selected-filter")) {
            await this._loadAllAccountLines();
            for (const account of this.state.move_line || []) {
                if (this.state.account_meta[account]) {
                    this.state.account_meta[account].expanded = true;
                } else {
                    const acc_id = this.state.total[account]['account_id'];
                    this.state.account_meta[account] = {
                        total:      (this.state.data[account] || []).length,
                        offset:     0,
                        account_id: acc_id,
                        expanded:   true,
                    };
                }
            }
            ev.target.classList.add("selected-filter");
        } else {
            for (const account of this.state.move_line || []) {
                if (this.state.account_meta[account]) {
                    this.state.account_meta[account].expanded = false;
                }
            }
            ev.target.classList.remove("selected-filter");
        }
    }
}
CashBook.defaultProps = {
    resIds: [],
};
CashBook.template = 'csh_b_template_new';
actionRegistry.add("csh_b", CashBook);
