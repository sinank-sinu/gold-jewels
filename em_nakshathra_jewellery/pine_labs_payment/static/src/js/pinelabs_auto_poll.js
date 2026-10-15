/** @odoo-module **/

/**
 * Pine Labs Auto-Poller
 * =====================
 * Patches the FormController so that when a pinelabs.payment.wizard
 * dialog is open in 'waiting' state, it automatically polls the
 * server every `poll_interval` seconds.
 *
 * On success  → closes the dialog and shows a success notification.
 * On failure  → closes the dialog and shows an error notification.
 * On timeout  → stops polling, keeps dialog open so user can click
 *               the manual "Check Status" button.
 *
 * The manual "Check Status" button still works independently.
 */

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount, useEffect } from "@odoo/owl";

// ── Constants ─────────────────────────────────────────────────────────────────
const WIZARD_MODEL = "pinelabs.payment.wizard";
const WAITING_STATE = "waiting";
const DEFAULT_INTERVAL_MS = 5000; // fallback if field not set

// ── Patch ─────────────────────────────────────────────────────────────────────
patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);

        // Only activate for the Pine Labs wizard
        if (this.props.resModel !== WIZARD_MODEL) {
            return;
        }

        this._plTimer = null;          // setInterval handle
        this._plPolling = false;       // guard to avoid concurrent polls
        this._plStopped = false;       // set to true to permanently stop
        this._notificationService = useService("notification");
        this._actionService = useService("action");
        this.orm = useService("orm");

        onMounted(() => this._pinelabs_startPollingIfNeeded());

        // Re-check whenever the record reloads
        useEffect(
            () => { this._pinelabs_startPollingIfNeeded(); },
            () => [this.model.root.data?.state]
        );

        onWillUnmount(() => this._pinelabs_stopPolling());
    },

    // ── Public helpers ────────────────────────────────────────────────────────

    _pinelabs_startPollingIfNeeded() {
        if (this.props.resModel !== WIZARD_MODEL) return;
        if (this._plStopped) return;

        const state = this.model?.root?.data?.state;
        if (state === WAITING_STATE && !this._plTimer) {
            this._pinelabs_startPolling();
        } else if (state !== WAITING_STATE && this._plTimer) {
            this._pinelabs_stopPolling();
        }
    },

    _pinelabs_startPolling() {
        if (this._plTimer) return; // already running

        // Read interval from record field (default 5 s)
        const intervalMs =
            (this.model?.root?.data?.poll_interval || 5) * 1000;

        // Update the status label in the DOM
        this._pinelabs_updateStatusLabel(0,
            this.model?.root?.data?.max_polls || 10, false);

        this._plTimer = setInterval(
            () => this._pinelabs_doPoll(),
            intervalMs
        );
        console.info("[PineLabs] Auto-polling started every", intervalMs / 1000, "s");
    },

    _pinelabs_stopPolling() {
        if (this._plTimer) {
            clearInterval(this._plTimer);
            this._plTimer = null;
            console.info("[PineLabs] Auto-polling stopped.");
        }
    },

    async _pinelabs_doPoll() {
        if (this._plPolling) return; // skip if previous call still in flight
        this._plPolling = true;

        const wizardId = this.props.resId || this.model?.root?.resId;
        if (!wizardId) {
            this._plPolling = false;
            return;
        }

        let result;
        try {
            result = await this.orm.call(
                WIZARD_MODEL,
                "action_auto_check_status",
                [[wizardId]],
                { context: {} }
            );
        } catch (err) {
            console.warn("[PineLabs] Poll RPC error:", err);
            this._plPolling = false;
            return;
        }

        const status     = result?.status || "pending";
        const pollCount  = result?.poll_count || 0;
        const maxPolls   = result?.max_polls  || 10;
        const message    = result?.message    || "";

        console.info("[PineLabs] Poll result:", status, `(${pollCount}/${maxPolls})`);

        // Update progress label
        this._pinelabs_updateStatusLabel(pollCount, maxPolls,
            status === "timeout");

        if (status === "success") {
            this._pinelabs_stopPolling();
            this._plStopped = true;
            this._notificationService.add(
                "✅ Pine Labs payment confirmed! Invoice reconciled automatically.",
                { title: "Payment Successful", type: "success", sticky: false }
            );
            // Close the dialog
            await this._actionService.doAction({ type: "ir.actions.act_window_close" });

        } else if (status === "failed") {
            this._pinelabs_stopPolling();
            this._plStopped = true;
            if (this.model?.root?.data?.state !== "failed") {
                const isCancelled = message && message.toLowerCase().includes("cancel");
                this._notificationService.add(
                    message || (isCancelled ? "Pine Labs transaction was cancelled." : "Pine Labs payment was declined by the terminal."),
                    {
                        title: isCancelled ? "Transaction Cancelled" : "Payment Failed",
                        type: isCancelled ? "warning" : "danger",
                        sticky: true,
                    }
                );
            }
            // Reload so wizard shows 'failed' state
            await this.model.root.load();
            this.render(true);

        } else if (status === "timeout") {
            this._pinelabs_stopPolling();
            this._plStopped = false; // allow manual retry to restart if needed
            this._notificationService.add(
                message || "Auto-check timed out. Use 'Check Status' to retry manually.",
                { title: "Polling Timed Out", type: "warning", sticky: true }
            );
            // Keep dialog open, reload to refresh counters
            await this.model.root.load();
            this.render(true);

        } else if (status === "error") {
            this._pinelabs_stopPolling();
            this._notificationService.add(
                message || "An error occurred while checking payment status.",
                { title: "Poll Error", type: "warning", sticky: false }
            );

        }
        // else "pending" → continue polling

        this._plPolling = false;
    },

    /**
     * Inject a small status line into the waiting-state div so the user
     * can see live "Checking… 3 / 10" progress without any extra XML field.
     */
    _pinelabs_updateStatusLabel(count, max, timedOut) {
        // Find the spinner alert inside the dialog
        const el = document.querySelector(
            ".o_dialog .o_form_view .alert.alert-warning #pl_poll_status"
        );
        // If not found yet just skip — will be updated on next tick
        if (!el) {
            // Try to inject the element after a short delay
            setTimeout(() => {
                const alertEl = document.querySelector(
                    ".o_dialog .o_form_view .alert.alert-warning"
                );
                if (alertEl && !alertEl.querySelector("#pl_poll_status")) {
                    const span = document.createElement("div");
                    span.id = "pl_poll_status";
                    span.style.cssText =
                        "margin-top:8px; font-size:12px; color:#92400e; font-weight:500;";
                    alertEl.appendChild(span);
                    this._pinelabs_setLabelText(span, count, max, timedOut);
                }
            }, 300);
            return;
        }
        this._pinelabs_setLabelText(el, count, max, timedOut);
    },

    _pinelabs_setLabelText(el, count, max, timedOut) {
        if (timedOut) {
            el.innerHTML =
                `⏱ Auto-check timed out (${count}/${max} attempts). ` +
                `Click <strong>Check Status</strong> to retry manually.`;
        } else {
            const pct = max > 0 ? Math.round((count / max) * 100) : 0;
            el.innerHTML =
                `🔄 Auto-checking status… attempt <strong>${count}/${max}</strong>` +
                `<div style="margin-top:4px; height:4px; background:#fde68a; border-radius:4px;">` +
                `  <div style="height:4px; background:#d97706; border-radius:4px; width:${pct}%;` +
                `   transition: width 0.4s ease;"></div>` +
                `</div>`;
        }
    },
});
