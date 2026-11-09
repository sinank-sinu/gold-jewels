/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// Web Audio API Audio Synthesizer for instant audible feedback
function playChime(type = "success") {
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        const ctx = new AudioCtx();

        if (type === "success") {
            // High double-beep for verified
            const now = ctx.currentTime;
            const osc1 = ctx.createOscillator();
            const gain1 = ctx.createGain();
            osc1.type = "sine";
            osc1.frequency.setValueAtTime(880, now); // A5
            gain1.gain.setValueAtTime(0.2, now);
            gain1.gain.exponentialRampToValueAtTime(0.01, now + 0.08);
            osc1.connect(gain1);
            gain1.connect(ctx.destination);
            osc1.start(now);
            osc1.stop(now + 0.08);

            const osc2 = ctx.createOscillator();
            const gain2 = ctx.createGain();
            osc2.type = "sine";
            osc2.frequency.setValueAtTime(1320, now + 0.09); // E6
            gain2.gain.setValueAtTime(0.25, now + 0.09);
            gain2.gain.exponentialRampToValueAtTime(0.01, now + 0.22);
            osc2.connect(gain2);
            gain2.connect(ctx.destination);
            osc2.start(now + 0.09);
            osc2.stop(now + 0.22);
        } else if (type === "warning") {
            // Low double-pulse for already verified / warning
            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "triangle";
            osc.frequency.setValueAtTime(440, now);
            osc.frequency.setValueAtTime(350, now + 0.1);
            gain.gain.setValueAtTime(0.25, now);
            gain.gain.exponentialRampToValueAtTime(0.01, now + 0.25);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.25);
        } else {
            // Low buzz for not found / error
            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "sawtooth";
            osc.frequency.setValueAtTime(200, now);
            gain.gain.setValueAtTime(0.3, now);
            gain.gain.exponentialRampToValueAtTime(0.01, now + 0.3);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.3);
        }
    } catch (e) {
        // Audio might be blocked by browser policy until first user interaction
    }
}

export class BranchBarcodeScannerWidget extends Component {
    static template = "branch_label_verification.BranchBarcodeScanner";

    static props = {
        record: { type: Object },
        readonly: { type: Boolean, optional: true },
        slots: { type: Object, optional: true },
        model: { type: String, optional: true },
        method: { type: String, optional: true },
        '*': true,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.inputRef = useRef("barcodeInput");

        this.state = useState({
            barcode: "",
            isProcessing: false,
            feedbackType: "",
            feedbackMessage: "",
            lastScannedCode: "",
            soundEnabled: true,
            totalScannedCount: 0,
        });

        this.debounceTimeout = null;

        this._onDocumentClick = () => {
            // Automatically refocus input if clicked anywhere in scanner area
            if (this.inputRef.el && document.activeElement !== this.inputRef.el) {
                // Keep cursor ready for scanner
            }
        };

        onMounted(() => {
            this._focusInput();
            document.addEventListener("click", this._onDocumentClick);
        });

        onWillUnmount(() => {
            if (this.debounceTimeout) {
                clearTimeout(this.debounceTimeout);
            }
            document.removeEventListener("click", this._onDocumentClick);
        });
    }

    get recordId() {
        return this.props.record.resId || null;
    }

    get modelName() {
        return this.props.model || this.props.record.resModel || "branch.label.verification";
    }

    get targetMethod() {
        return this.props.method || "action_scan_barcode";
    }

    _focusInput() {
        setTimeout(() => {
            if (this.inputRef.el) {
                this.inputRef.el.focus();
                this.inputRef.el.select();
            }
        }, 80);
    }

    onInput(ev) {
        this.state.barcode = ev.target.value;
        if (this.debounceTimeout) {
            clearTimeout(this.debounceTimeout);
        }
        const val = (ev.target.value || "").trim();
        // Auto-verify if scanned without Enter key (300ms pause)
        if (val.length >= 4) {
            this.debounceTimeout = setTimeout(async () => {
                if (this.state.barcode && !this.state.isProcessing) {
                    await this.processBarcode();
                }
            }, 300);
        }
    }

    async onKeyDown(ev) {
        if (ev.key === "Enter" || ev.key === "Tab") {
            ev.preventDefault();
            ev.stopPropagation();
            if (this.debounceTimeout) {
                clearTimeout(this.debounceTimeout);
            }
            await this.processBarcode();
        }
    }

    toggleSound() {
        this.state.soundEnabled = !this.state.soundEnabled;
    }

    async processBarcode() {
        if (this.state.isProcessing) return;

        const code = (this.state.barcode || "").trim();
        if (!code) return;

        // Auto-save if record is draft or dirty
        if (this.props.record.isNew || this.props.record.isDirty) {
            try {
                await this.props.record.save();
            } catch (e) {
                this.notification.add(_t("Please save the audit before scanning."), { type: "warning" });
                return;
            }
        }

        if (!this.recordId) {
            this.notification.add(_t("Please save the audit first."), { type: "warning" });
            return;
        }

        this.state.isProcessing = true;
        this.state.lastScannedCode = code;

        try {
            const res = await this.orm.call(
                this.modelName,
                this.targetMethod,
                [this.recordId, code]
            );

            if (res.status === "verified" || res.success) {
                if (this.state.soundEnabled) playChime("success");
                this.state.feedbackType = "success";
                this.state.feedbackMessage = res.message || _t("Verified: %s", res.product || code);
                this.state.totalScannedCount += 1;
                // Reload record so line status and KPI counters update immediately
                await this.props.record.load();
            } else if (res.status === "warning" || res.warning) {
                if (this.state.soundEnabled) playChime("warning");
                this.state.feedbackType = "warning";
                this.state.feedbackMessage = res.message || res.error || _t("Already verified: %s", code);
            } else {
                if (this.state.soundEnabled) playChime("danger");
                this.state.feedbackType = "danger";
                this.state.feedbackMessage = res.error || res.message || _t("Not Found: %s", code);
            }
        } catch (err) {
            if (this.state.soundEnabled) playChime("danger");
            this.state.feedbackType = "danger";
            this.state.feedbackMessage = _t("Scanning error: %s", err.message || String(err));
        } finally {
            this.state.isProcessing = false;
            this.state.barcode = "";
            if (this.inputRef.el) {
                this.inputRef.el.value = "";
            }
            this._focusInput();
        }
    }
}

registry.category("view_widgets").add("branch_barcode_scanner", {
    component: BranchBarcodeScannerWidget,
    extractProps({ attrs }) {
        return {
            model: attrs.model || "",
            method: attrs.method || "",
        };
    },
});
