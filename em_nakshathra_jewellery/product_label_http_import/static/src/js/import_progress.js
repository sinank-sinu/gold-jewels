/** @odoo-module **/

import { Component, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class ImportProgressPollerWidget extends Component {
    static template = "product_label_http_import.ImportProgressPoller";
    static props = {
        record: { type: Object },
        readonly: { type: Boolean, optional: true },
        "*": true,
    };

    setup() {
        this.pollTimer = null;

        onMounted(() => {
            this._startPolling();
        });

        onWillUnmount(() => {
            this._stopPolling();
        });
    }

    get stateName() {
        return (this.props.record && this.props.record.data && this.props.record.data.state) || "draft";
    }

    get isRunning() {
        return this.stateName === "running";
    }

    get totalRows() {
        return (this.props.record && this.props.record.data && this.props.record.data.total_rows) || 0;
    }

    get processedRows() {
        return (this.props.record && this.props.record.data && this.props.record.data.processed_rows) || 0;
    }

    get progressPct() {
        const val = (this.props.record && this.props.record.data && this.props.record.data.progress) || 0;
        return Math.min(100, Math.max(0, Math.round(val)));
    }

    _startPolling() {
        this._stopPolling();
        this.pollTimer = setInterval(async () => {
            if (this.isRunning && this.props.record && this.props.record.resId) {
                try {
                    await this.props.record.load();
                } catch (_e) {
                    this._stopPolling();
                }
            } else if (!this.isRunning) {
                this._stopPolling();
            }
        }, 1200);
    }

    _stopPolling() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    }
}

registry.category("view_widgets").add("label_import_progress", {
    component: ImportProgressPollerWidget,
});

