/** @odoo-module */

/**
 * Pine Labs POS Payment Interface
 *
 * This class integrates Pine Labs physical terminal with Odoo POS.
 * Flow:
 *  1. send_payment_request() → calls pos.payment.method::pinelabs_initiate_payment()
 *  2. POS changes status to 'waitingCard'
 *  3. poll loop calls pos.payment.method::pinelabs_fetch_payment_status() every 5s
 *  4. On success → updates payment line fields → returns true
 *  5. On cancel → calls send_payment_cancel() → stops polling
 */

import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/payment/payment_interface";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";

const POLL_INTERVAL_MS = 5000;   // poll every 5 seconds
const MAX_POLL_ATTEMPTS = 60;   // ~5 minutes timeout

export class PaymentPineLabs extends PaymentInterface {
    /**
     * @Override
     * Sends a payment request to the Pine Labs terminal.
     */
    async send_payment_request(cid) {
        await super.send_payment_request(...arguments);
        const order = this.pos.selectedOrder;
        const paymentLine = order?.selected_paymentline;
        if (!paymentLine) return false;

        const amount = paymentLine.amount;
        const billingRef = order.name
            ? order.name.replace(/[^A-Za-z0-9]/g, "").substring(0, 20)
            : `POS${Date.now()}`;

        paymentLine.set_payment_status("waitingCard");

        // Step 1: initiate payment on the terminal
        const initResponse = await this._makeRequest(
            "pinelabs_initiate_payment",
            [amount, billingRef]
        );
        if (!initResponse || initResponse.error) {
            this._showError(initResponse?.error || _t("Failed to reach Pine Labs terminal."), "Pine Labs");
            paymentLine.set_payment_status("force_done");
            return false;
        }

        const plutusRefId =
            initResponse.PlutusTransactionReferenceID ||
            initResponse.plutusTransactionReferenceID;

        if (!plutusRefId) {
            this._showError(
                _t("Pine Labs did not return a transaction reference. Response: %s", JSON.stringify(initResponse)),
                "Pine Labs"
            );
            paymentLine.set_payment_status("force_done");
            return false;
        }

        // Step 2: poll for status
        const pollResult = await this._pollStatus(plutusRefId, paymentLine);
        if (pollResult && pollResult.status === "success") {
            paymentLine.pinelabs_txn_ref = String(plutusRefId);
            paymentLine.pinelabs_approval_code = pollResult.approval_code || "";
            paymentLine.pinelabs_card_type = pollResult.card_type || "";
            paymentLine.pinelabs_payment_mode = pollResult.payment_mode || "";
            paymentLine.pinelabs_rrn = pollResult.rrn || "";
            paymentLine.pinelabs_issuer_bank = pollResult.issuer_bank || "";
            return true;
        }
        if (pollResult && pollResult.status === "cancelled") {
            return false;  // user cancelled
        }
        paymentLine.set_payment_status("force_done");
        return false;
    }

    /**
     * @Override
     * Handles the user clicking "Cancel" in POS payment screen.
     */
    async send_payment_cancel(order, cid) {
        await super.send_payment_cancel(...arguments);
        this._cancelPolling = true;
        const paymentLine = order?.selected_paymentline;
        if (paymentLine) {
            paymentLine.set_payment_status("retry");
        }
        clearTimeout(this._pollTimeout);
        return true;
    }

    // ────────────────────────────────────────────────────────────────
    // Private helpers
    // ────────────────────────────────────────────────────────────────

    /**
     * Poll the backend every POLL_INTERVAL_MS for the transaction status.
     * Returns { status: 'success'|'failed'|'cancelled'|'timeout', ...details }
     */
    async _pollStatus(plutusRefId, paymentLine) {
        this._cancelPolling = false;
        let attempts = 0;
        return new Promise((resolve) => {
            const poll = async () => {
                if (this._cancelPolling) {
                    return resolve({ status: "cancelled" });
                }
                if (attempts >= MAX_POLL_ATTEMPTS) {
                    this._showError(_t("Timed out waiting for Pine Labs terminal response."), "Pine Labs Timeout");
                    return resolve({ status: "timeout" });
                }
                attempts++;
                try {
                    const data = await this.env.services.orm.silent.call(
                        "pos.payment.method",
                        "pinelabs_fetch_payment_status",
                        [[this.payment_method.id], plutusRefId]
                    );
                    if (data?.error) {
                        this._showError(data.error, "Pine Labs");
                        return resolve({ status: "failed" });
                    }
                    const status = data?.status;
                    if (status === "success") {
                        paymentLine.set_payment_status("done");
                        return resolve(data);
                    } else if (status === "failed") {
                        this._showError(data?.message || _t("Transaction declined."), "Pine Labs");
                        return resolve({ status: "failed" });
                    } else {
                        // still pending – schedule next poll
                        this._pollTimeout = setTimeout(poll, POLL_INTERVAL_MS);
                    }
                } catch (error) {
                    this._showError(
                        _t("Error checking Pine Labs status: %s", String(error)),
                        "Pine Labs"
                    );
                    return resolve({ status: "failed" });
                }
            };
            // Start first poll immediately
            poll();
        });
    }

    /**
     * Helper: call a method on pos.payment.method via ORM RPC.
     */
    async _makeRequest(methodName, extraArgs = []) {
        try {
            return await this.env.services.orm.silent.call(
                "pos.payment.method",
                methodName,
                [[this.payment_method.id], ...extraArgs]
            );
        } catch (error) {
            _logger.warn("Pine Labs RPC error:", error);
            return { error: String(error) };
        }
    }

    _showError(message, title) {
        this.env.services.popup.add(ErrorPopup, {
            title: title || _t("Pine Labs Error"),
            body: typeof message === "string" ? message : JSON.stringify(message),
        });
    }
}
