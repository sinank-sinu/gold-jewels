/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
const actionRegistry = registry.category("actions");

// Fetch the existing instance out from Action Component registry safely
const CashBookComponent = actionRegistry.get("csh_b");

patch(CashBookComponent.prototype, {
    async setup() {
        await super.setup(...arguments);
        // Safely add our custom properties to the existing reactive state
        this.state.branches = [];
        this.state.selected_branch_list = [];
    },

    async load_data() {
        await super.load_data(...arguments);
        // Separate out branches array properties from table row keys
        if (this.state.data && this.state.data.branches) {
            this.state.branches = this.state.data.branches;
            // Clean up row keys collection array tracking
            this.state.move_line = this.state.move_line.filter(key => key !== 'branches');
        }
    },

    async applyFilter(val, ev, is_delete = false) {
        if (!ev) {
            const targetValue = val.target.attributes["data-value"] ? val.target.attributes["data-value"].value : '';
            if (targetValue === 'branch') {
                const idVal = parseInt(val.target.attributes["data-id"].value, 10);
                if (!val.target.classList.contains("selected-filter")) {
                    this.state.selected_branch_list.push(idVal);
                    val.target.classList.add("selected-filter");
                } else {
                    this.state.selected_branch_list = this.state.selected_branch_list.filter(item => item !== idVal);
                    val.target.classList.remove("selected-filter");
                }
                
                // Trigger the RPC call specifically for branch changes
                return this._triggerFilteredRpc();
            }
        }
        // Run standard base filtering code logic mapping rules
        await super.applyFilter(...arguments);
    },

    async _triggerFilteredRpc() {
        let move_line_list = [];
        let move_line_totals = '';
        this.state.move_line = null;
        this.state.data = null;
        this.state.total = null;
        this.state.filter_applied = true;
        let totalDebitSum = 0;
        let totalCreditSum = 0;

        let filtered_data = await this.orm.call("cash.book.report", "get_filter_values", [
            this.state.selected_partner, 
            this.state.date_range, 
            this.state.selected_account_list, 
            this.state.options,
            this.state.selected_branch_list
        ]);

        for (const [index, value] of Object.entries(filtered_data)) {
            if (index !== 'move_lines_total' && index !== 'accounts' && index !== 'branches') {
                move_line_list.push(index);
            } else if (index === 'move_lines_total') {
                move_line_totals = value;
                Object.values(move_line_totals).forEach(move_line => {
                    totalDebitSum += move_line.total_debit || 0;
                    totalCreditSum += move_line.total_credit || 0;
                });
            }
        }
        this.state.move_line = move_line_list;
        this.state.data = filtered_data;
        this.state.total = move_line_totals;
        this.state.total_debit = totalDebitSum.toFixed(2);
        this.state.total_credit = totalCreditSum.toFixed(2);
        if ($(this.unfoldButton.el.classList).find("selected-filter")) {
            this.unfoldButton.el.classList.remove("selected-filter");
        }
    }
});