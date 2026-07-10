/** @odoo-module **/

import { Component, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STEPS = [
    { key: "upload",    label: "Upload File" },
    { key: "mapping",   label: "Field Mapping" },
    { key: "preview",   label: "Preview" },
    { key: "importing", label: "Importing" },
    { key: "done",      label: "Done" },
];

class LabelBulkImportWizard extends Component {
    static template = "product_label_bulk_import.LabelBulkImportWizard";
    static props = ["*"];

    setup() {
        this.rpc       = useService("rpc");
        this.actionSvc = useService("action");
        this.notif     = useService("notification");
        this.fileInput = useRef("fileInput");
        this.dropzone  = useRef("dropzone");

        this.steps = STEPS;

        this.state = useState({
            step:        "upload",
            loading:     false,
            globalError: null,

            // Upload step
            fileData:      null,   // base64 string
            fileName:      "",
            sheetNames:    [],
            selectedSheet: "",
            batchSize:     10000,
            uniqueField:   "name",
            autoCreateM2o: false,
            autoTransfer:  false,

            modelFields:   [],     // product.label fields
            loadingFields: false,

            // Mapping step
            headers: [],
            mapping: {},

            // Preview step
            previewRows: [],

            // Import / done steps
            jobId:         null,
            totalRows:     0,
            processedRows: 0,
            currentOffset: 0,
            currentBatch:  0,
            totalBatches:  0,
            batchRunning:  false,
            batchComplete: false,
            allDone:       false,
            batchStats:    { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0, transferred: 0 },
            totalStats:    { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0, transferred: 0 },
            skippedReasons: [],
            errorReasons:   [],

            // Transfer panel
            transferLoading: false,
            transferResult:  null,
        });

        this._loadFields();
        this._restoreSession();
    }

    // ── Field catalogue ──────────────────────────────────────────────────────

    async _loadFields() {
        this.state.loadingFields = true;
        try {
            const res = await this.rpc("/product_label/import/get_model_fields", {});
            if (!res.error) this.state.modelFields = res.fields || [];
        } catch (e) {
            this._setError("Could not load Product Label fields: " + e.message);
        } finally {
            this.state.loadingFields = false;
        }
    }

    // ── Utility ──────────────────────────────────────────────────────────────

    stepIndex(key) { return STEPS.findIndex(s => s.key === key); }

    progressPct() {
        if (!this.state.totalRows) return 0;
        return Math.round(this.state.processedRows / this.state.totalRows * 1000) / 10;
    }

    previewColumns() {
        if (!this.state.previewRows.length) return [];
        return Object.keys(this.state.previewRows[0]);
    }

    _setError(msg) {
        this.state.globalError = msg;
        this.state.loading = false;
    }

    // ── File handling ─────────────────────────────────────────────────────────

    triggerFileInput() { this.fileInput.el && this.fileInput.el.click(); }
    onDragOver() { this.dropzone.el && this.dropzone.el.classList.add("dragover"); }
    onDragLeave() { this.dropzone.el && this.dropzone.el.classList.remove("dragover"); }
    onDrop(e) {
        this.dropzone.el && this.dropzone.el.classList.remove("dragover");
        const file = e.dataTransfer && e.dataTransfer.files[0];
        if (file) this._readFile(file);
    }
    onFileChange(e) {
        const file = e.target.files[0];
        if (file) this._readFile(file);
    }

    _readFile(file) {
        const allowed = [".csv", ".xlsx", ".xls"];
        const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
        if (!allowed.includes(ext)) {
            this._setError("Only CSV and XLSX files are supported.");
            return;
        }
        const reader = new FileReader();
        reader.onload = async (ev) => {
            const b64 = ev.target.result.split(",")[1];
            this.state.fileData = b64;
            this.state.fileName = file.name;
            this.state.globalError = null;
            this.state.sheetNames = [];
            this.state.selectedSheet = "";
            const isXlsx = file.name.toLowerCase().match(/\.xlsx?$/);
            if (isXlsx) {
                try {
                    const res = await this.rpc("/product_label/import/get_sheet_names", {
                        file_data: b64,
                        file_name: file.name,
                    });
                    if (!res.error && res.sheets && res.sheets.length > 1) {
                        this.state.sheetNames = res.sheets;
                        this.state.selectedSheet = res.sheets[0];
                    }
                } catch (_e) { /* non-fatal */ }
            }
        };
        reader.readAsDataURL(file);
    }

    // ── Step navigation ───────────────────────────────────────────────────────

    async goToMapping() {
        if (!this.state.fileData) {
            this._setError("Please select a file first.");
            return;
        }
        this.state.loading = true;
        this.state.globalError = null;
        try {
            const res = await this.rpc("/product_label/import/parse_headers", {
                file_data:  this.state.fileData,
                file_name:  this.state.fileName,
                sheet_name: this.state.selectedSheet || null,
            });
            if (res.error) { this._setError(res.error); return; }
            this.state.headers = res.headers || [];

            let mapping = {};
            try {
                const am = await this.rpc("/product_label/import/auto_map", {
                    headers: this.state.headers,
                });
                mapping = am || {};
            } catch (_e) { /* fall through */ }
            for (const col of this.state.headers) {
                if (!mapping[col]) mapping[col] = this._autoDetect(col);
            }
            this.state.mapping = mapping;
            this.state.step = "mapping";
            this._saveSession();
        } catch (e) {
            this._setError(e.message || String(e));
        } finally {
            this.state.loading = false;
        }
    }

    _autoDetect(col) {
        const c = col.toLowerCase().replace(/[^a-z0-9]/g, "_");

        // Force critical mappings to avoid ambiguity/fallbacks
        const FORCE = {
            label_name: "name", labelname: "name", label: "name",
            source_location: "source_location_id", sourcelocation: "source_location_id",
            origin_location: "source_location_id",
            destination_location: "branch_location_id", destinationlocation: "branch_location_id",
            dest_location: "branch_location_id",
        };
        if (FORCE[c]) return FORCE[c];

        const labelAliases = {
            name:                        ['label_reference', 'label_ref', 'label_no', 'reference'],
            label_number:                ['label_number', 'label_num', 'tag_no', 'tag_number'],
            label_name:                  ['label_name', 'tag_name'],
            age_import:                  ['age', 'age_days', 'days', 'label_age', 'age_day'],
            product_id:                  ['product_variant', 'variant', 'product_var', 'product_variant_name',
                                          'variant_name', 'item_variant', 'product_code', 'item', 'sku'],
            product_tmpl_id:             ['product', 'product_template', 'template', 'product_tmpl',
                                          'product_template_name', 'product_name'],
            purchase_id:                 ['purchase_order', 'purchase_order_no', 'po', 'po_number',
                                          'po_no', 'po_ref', 'po_name'],
            branch_id:                   ['branch', 'branch_name'],
            branch_location_id:          ['destination_location', 'dest_location', 'branch_location', 'to_location'],
            source_location_id:          ['source_location', 'from_location', 'src_location'],
            purity_id:                   ['purity', 'purchase_purity', 'karat'],
            sale_purity_id:              ['sale_purity', 'sale_karat'],
            job_work_id:                 ['job_work', 'jobwork', 'jobs_work'],
            requisition_id:              ['requisition', 'req'],
            purchase_price_per_gram:     ['purchase_rate', 'purchase_rate_per_gram', 'purchase_fine_rate'],
            purchase_gross_weight:       ['purchase_gross_weight', 'gross_weight', 'gw', 'purchase_gw'],
            purchase_stone_weight:       ['purchase_stone_weight', 'stone_weight', 'sw', 'purchase_sw'],
            purchase_diamond_weight_gm:  ['purchase_diamond_weight_gm', 'diamond_weight_gm', 'dw_gm'],
            purchase_diamond_weight_ct:  ['purchase_diamond_weight_ct', 'diamond_weight_ct', 'dw_ct'],
            purchase_stone_rate:         ['purchase_stone_amount', 'stone_amount', 'purchase_stone_rate'],
            purchase_diamond_rate:       ['purchase_diamond_amount', 'diamond_amount', 'purchase_diamond_rate'],
            purchase_making_charge_type: ['purchase_mc_type', 'mc_type', 'making_charge_type'],
            purchase_making_charge_value:['purchase_mc_value', 'mc_value', 'making_charge_value', 'mc_percent'],
            purchase_metal_rate:         ['purchase_metal_amount', 'metal_amount', 'purchase_metal_rate'],
            sale_price_per_gram:         ['sale_rate', 'sale_rate_per_gram', 'sale_fine_rate'],
            sale_gross_weight:           ['sale_gross_weight', 'sale_gw'],
            sale_stone_weight:           ['sale_stone_weight', 'sale_sw'],
            sale_diamond_weight_gm:      ['sale_diamond_weight_gm', 'sale_dw_gm'],
            sale_diamond_weight_ct:      ['sale_diamond_weight_ct', 'sale_dw_ct'],
            sale_stone_rate:             ['sale_stone_amount', 'sale_stone_rate'],
            sale_diamond_rate:           ['sale_diamond_amount', 'sale_diamond_rate'],
            sale_making_charge_type:     ['sale_mc_type'],
            sale_making_charge_value:    ['sale_mc_value', 'sale_mc_max', 'sale_making_charge_value'],
            sale_making_charge_min:      ['sale_mc_min', 'sale_making_charge_min'],
            sale_metal_rate:             ['sale_metal_amount', 'sale_metal_rate'],
            tag_weight:                  ['tag_weight', 'tag_wt'],
            certification_charge:        ['certification_charge', 'cert_charge'],
            transportation_charge:       ['transportation_charge', 'transport_charge'],
            cargo_charge:                ['cargo_charge', 'cargo'],
            others:                      ['others', 'other_charges', 'other'],
        };

        // 1. Exact field name match
        if (this.state.modelFields.find(f => f.name === c)) return c;

        // 2. Alias match
        for (const [fieldName, aliasList] of Object.entries(labelAliases)) {
            if (aliasList.includes(c)) {
                if (!this.state.modelFields.length ||
                    this.state.modelFields.find(f => f.name === fieldName))
                    return fieldName;
            }
        }

        // 3. Fuzzy: col words all appear in a field's label
        if (this.state.modelFields.length) {
            const colWords = c.split("_").filter(Boolean);
            if (colWords.length) {
                const fuzzy = this.state.modelFields.find(f => {
                    const lbl = f.label.toLowerCase().replace(/[^a-z0-9]/g, "_");
                    return colWords.every(w => lbl.includes(w));
                });
                if (fuzzy) return fuzzy.name;
            }
        }
        return "";
    }

    async reAutoMap() {
        let mapping = {};
        try {
            const am = await this.rpc("/product_label/import/auto_map", { headers: this.state.headers });
            mapping = am || {};
        } catch (_e) { /* fall through */ }
        for (const col of this.state.headers) {
            if (!mapping[col]) mapping[col] = this._autoDetect(col);
        }
        this.state.mapping = mapping;
    }

    setMapping(col, value) {
        this.state.mapping = { ...this.state.mapping, [col]: value };
    }

    async goToPreview() {
        this.state.loading = true;
        this.state.globalError = null;
        try {
            const res = await this.rpc("/product_label/import/get_preview", {
                file_data: this.state.fileData,
                file_name: this.state.fileName,
                mapping:   this.state.mapping,
            });
            if (res.error) { this._setError(res.error); return; }
            this.state.previewRows = res.rows || [];
            this.state.step = "preview";
            this._saveSession();
        } catch (e) {
            this._setError(e.message || String(e));
        } finally {
            this.state.loading = false;
        }
    }

    // ── Import flow ───────────────────────────────────────────────────────────

    async startImport() {
        if (!this.state.fileData) {
            this._setError("File data is no longer available. Please go back and re-upload the file.");
            return;
        }
        this.state.loading = true;
        this.state.globalError = null;
        try {
            const res = await this.rpc("/product_label/import/create_job", {
                file_data:       this.state.fileData,
                file_name:       this.state.fileName,
                mapping:         this.state.mapping,
                batch_size:      this.state.batchSize,
                unique_field:    this.state.uniqueField || 'name',
                auto_create_m2o: this.state.autoCreateM2o,
                auto_transfer:   this.state.autoTransfer,
                sheet_name:      this.state.selectedSheet || null,
            });
            if (res.error) { this._setError(res.error); return; }

            Object.assign(this.state, {
                jobId:         res.job_id,
                totalRows:     res.total_rows,
                totalBatches:  res.total_batches,
                processedRows: 0,
                currentOffset: 0,
                currentBatch:  0,
                batchComplete: false,
                allDone:       false,
                step:          "importing",
            });
            await this._runBatch();
        } catch (e) {
            this._setError(e.message || String(e));
        } finally {
            this.state.loading = false;
        }
    }

    async continueImport() {
        if (this.state.batchRunning || this.state.allDone) return;
        await this._runBatch();
    }

    async _runBatch() {
        this.state.batchRunning = true;
        this.state.batchComplete = false;
        this.state.globalError = null;
        try {
            while (true) {
                const res = await this.rpc("/product_label/import/process_batch", {
                    job_id: this.state.jobId,
                });
                if (res.error) { this._setError(res.error); return; }

                Object.assign(this.state, {
                    currentBatch:  res.batch_number  || this.state.currentBatch,
                    totalBatches:  res.total_batches || this.state.totalBatches,
                    processedRows: res.total_stats ? res.total_stats.processed : this.state.processedRows,
                    currentOffset: res.offset        || this.state.currentOffset,
                    batchStats:    res.batch_stats   || this.state.batchStats,
                    totalStats:    res.total_stats   || this.state.totalStats,
                    batchComplete: true,
                    allDone:       res.done === true,
                    skippedReasons: res.skipped_reasons || [],
                    errorReasons:   res.error_reasons   || [],
                });
                this._saveSession();

                if (res.done) {
                    this.state.step = "done";
                    this.state.allDone = true;
                    this._saveSession();
                    return;
                }
            }
        } catch (e) {
            const detail = e?.data?.message || e?.cause?.message || e.message || String(e);
            this._setError(detail);
        } finally {
            this.state.batchRunning = false;
        }
    }

    async cancelImport() {
        if (!this.state.jobId) { this.state.step = "upload"; return; }
        try {
            await this.rpc("/product_label/import/cancel", { job_id: this.state.jobId });
            this.notif.add("Import cancelled.", { type: "warning" });
            this.state.step = "upload";
        } catch (e) {
            this._setError(e.message || String(e));
        }
    }

    // ── Session persistence ───────────────────────────────────────────────────

    _saveSession() {
        if (this.state.step === 'upload') return;
        const base = {
            step:          this.state.step,
            jobId:         this.state.jobId,
            fileName:      this.state.fileName,
            uniqueField:   this.state.uniqueField,
            autoCreateM2o: this.state.autoCreateM2o,
            autoTransfer:  this.state.autoTransfer,
            headers:       this.state.headers,
            mapping:       this.state.mapping,
            previewRows:   this.state.previewRows,
            totalRows:     this.state.totalRows,
            processedRows: this.state.processedRows,
            currentBatch:  this.state.currentBatch,
            totalBatches:  this.state.totalBatches,
            currentOffset: this.state.currentOffset,
            totalStats:    this.state.totalStats,
            allDone:       this.state.allDone,
        };
        for (const payload of [{ ...base, fileData: this.state.fileData }, base]) {
            try {
                localStorage.setItem('label_bulk_import_session', JSON.stringify(payload));
                return;
            } catch (_e) { /* QuotaExceeded – retry without fileData */ }
        }
    }

    _clearSession() {
        try { localStorage.removeItem('label_bulk_import_session'); } catch (e) {}
    }

    async _restoreSession() {
        try {
            const raw = localStorage.getItem('label_bulk_import_session');
            if (!raw) return;
            const saved = JSON.parse(raw);
            if (!saved.step || saved.step === 'upload') return;

            if (saved.step === 'importing' || saved.step === 'done') {
                if (!saved.jobId) return;
                const res = await this.rpc("/product_label/import/job_status", { job_id: saved.jobId });
                if (res.error || !res.state) { this._clearSession(); return; }
                if (res.state === 'cancelled') { this._clearSession(); return; }
                Object.assign(this.state, {
                    jobId:         saved.jobId,
                    fileName:      saved.fileName || '',
                    totalRows:     res.total_rows,
                    processedRows: res.processed_rows,
                    currentBatch:  res.current_batch,
                    totalBatches:  res.total_batches,
                    currentOffset: saved.currentOffset || 0,
                    totalStats:    res.stats || saved.totalStats,
                    allDone:       res.state === 'done',
                    batchComplete: res.state === 'paused' || res.state === 'done',
                    step:          res.state === 'done' ? 'done' : 'importing',
                });
            } else if (saved.step === 'mapping' || saved.step === 'preview') {
                Object.assign(this.state, {
                    step:          saved.step,
                    fileData:      saved.fileData      || null,
                    fileName:      saved.fileName      || '',
                    uniqueField:   saved.uniqueField   || 'name',
                    autoCreateM2o: !!saved.autoCreateM2o,
                    autoTransfer:  !!saved.autoTransfer,
                    headers:       saved.headers       || [],
                    mapping:       saved.mapping       || {},
                    previewRows:   saved.previewRows   || [],
                });
            }
        } catch (e) {
            this._clearSession();
        }
    }

    // ── Final buttons ─────────────────────────────────────────────────────────

    async backToMapping() {
        if (this.state.jobId) {
            try { await this.rpc("/product_label/import/cancel", { job_id: this.state.jobId }); }
            catch (e) { /* non-fatal */ }
        }
        this._clearSession();
        Object.assign(this.state, {
            step:          "mapping",
            jobId:         null,
            totalRows:     0,
            processedRows: 0,
            currentOffset: 0,
            currentBatch:  0,
            totalBatches:  0,
            batchComplete: false,
            batchRunning:  false,
            allDone:       false,
            globalError:   null,
            batchStats:    { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0, transferred: 0 },
            totalStats:    { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0, transferred: 0 },
            skippedReasons: [],
            errorReasons:   [],
        });
        const mapping = {};
        for (const col of this.state.headers) mapping[col] = this._autoDetect(col);
        this.state.mapping = mapping;
        this._saveSession();
    }

    startNewImport() {
        this._clearSession();
        Object.assign(this.state, {
            step:          "upload",
            fileData:      null,
            fileName:      "",
            uniqueField:   "name",
            autoCreateM2o: false,
            autoTransfer:  false,
            headers:       [],
            mapping:       {},
            previewRows:   [],
            jobId:         null,
            totalRows:     0,
            processedRows: 0,
            currentOffset: 0,
            currentBatch:  0,
            totalBatches:  0,
            batchComplete: false,
            allDone:       false,
            globalError:   null,
            transferResult: null,
            batchStats: { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0, transferred: 0 },
            totalStats: { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0, transferred: 0 },
            skippedReasons: [],
            errorReasons:   [],
        });
    }

    viewHistory() {
        this.actionSvc.doAction({
            type: "ir.actions.act_window",
            name: "Import Jobs",
            res_model: "label.import.job",
            view_mode: "tree,form",
            views: [[false, "tree"], [false, "form"]],
        });
    }

    async triggerLabelTransfers() {
        this.state.transferLoading = true;
        try {
            const res = await this.rpc("/product_label/import/trigger_label_transfers", {
                job_id: this.state.jobId || null,
            });
            if (res.error) {
                this.state.transferResult = { success: 0, failed: 0, errors: [res.error], failed_labels: [] };
            } else {
                this.state.transferResult = res;
                if (res.failed === 0) {
                    this.notif.add(`All ${res.success} labels transferred successfully.`, { type: "success" });
                }
            }
        } catch (e) {
            this.state.transferResult = { success: 0, failed: 1, errors: [String(e)], failed_labels: [] };
        } finally {
            this.state.transferLoading = false;
        }
    }
}

registry.category("actions").add("product_label_bulk_import_wizard", LabelBulkImportWizard);