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

class POBulkImportWizard extends Component {
    static template = "purchase_order_bulk_import.POBulkImportWizard";
    static props = ["*"];

    setup() {
        this.rpc         = useService("rpc");
        this.actionSvc   = useService("action");
        this.notif       = useService("notification");
        this.fileInput   = useRef("fileInput");
        this.dropzone    = useRef("dropzone");

        this.steps = STEPS;

        // Bind methods called from template handlers via arrow functions so
        // OWL's compiled expression scope doesn't lose the `this` reference.
        this.selectModelItem     = this.selectModelItem.bind(this);
        this.selectLineModelItem = this.selectLineModelItem.bind(this);
        this.clearModel          = this.clearModel.bind(this);
        this.onModelSearch       = this.onModelSearch.bind(this);
        this.onModelSearchBlur   = this.onModelSearchBlur.bind(this);
        this.onLineModelSearch   = this.onLineModelSearch.bind(this);
        this.onLineModelSearchBlur = this.onLineModelSearchBlur.bind(this);

        this.state = useState({
            step:        "upload",
            loading:     false,
            globalError: null,

            // Upload step
            fileData:       null,   // base64 string
            fileName:       "",
            sheetNames:     [],     // sheet names in uploaded XLSX
            selectedSheet:  "",     // which sheet to import
            batchSize:      10000,
            matchField:     "name",   // kept for PO-specific path
            selectedModel:  "",       // e.g. "purchase.order"
            selectedModelName: "",    // human label
            uniqueField:    "",       // field name used as unique key
            modelList:      [],       // [{model, name}]
            modelFields:    [],       // [{name, label, type}] for selected model
            loadingModels:  false,
            loadingFields:  false,

            // Model search (Target Model)
            modelSearchQuery:    "",
            modelDropdownOpen:   false,

            // Model search (Line/Child Model)
            lineModelSearchQuery:  "",
            lineModelDropdownOpen: false,

            // Fields catalogue (PO-specific)
            poFields:    [],
            polFields:   [],

            // Header + Lines mode
            hasLines:       false,
            lineModel:      "",
            lineModelName:  "",
            lineModelFields: [],
            lineLinkField:  "",
            groupByField:   "",
            autoCreateM2o:  false,
            autoConfirmReceive: false,
            autoCreateBill:     false,
            loadingLineFields: false,

            // Target PO (direct-lines mode)
            targetPoId:     null,
            targetPoName:   "",
            targetPoVendor: "",
            poSearchQuery:  "",
            poSearchResults: [],
            poSearchLoading: false,

            // Mapping step
            headers:     [],
            mapping:     {},    // { excel_col: "h:field" | "l:field" | "" }

            // Preview step
            previewRows: [],

            // Import / done steps
            jobId:          null,
            totalRows:      0,
            processedRows:  0,
            currentOffset:  0,
            currentBatch:   0,
            totalBatches:   0,
            batchRunning:   false,
            batchComplete:  false,
            allDone:        false,
            batchStats:     { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0 },
            totalStats:     { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0 },
            skippedReasons: [],
            errorReasons:   [],

            // PO Summary panel (Done step)
            summaryLoading:  false,
            summaryVisible:  false,
            summaryData:     null,   // { po_count, pending_approve, pending_confirm }
            approveLoading:  false,
            confirmLoading:  false,
            transferLoading: false,
            transferResult:  null,

            // Vendor breakdown modal
            vendorModalOpen:    false,
            vendorLoading:      false,
            vendorBreakdown:    [],   // [{ vendor, po_name, line_count, state }]
        });

        // Load PO/POL fields and model list eagerly
        this._loadFields();
        this._loadModelList();
        this._restoreSession();
    }

    // ── Computed / filtered model lists ──────────────────────────────────────

    get filteredModels() {
        // When a model is already selected, show full list so user can switch
        if (this.state.selectedModel) return this.state.modelList.slice(0, 60);
        const q = (this.state.modelSearchQuery || "").toLowerCase();
        if (!q) return this.state.modelList.slice(0, 60);
        return this.state.modelList.filter(m =>
            m.name.toLowerCase().includes(q) || m.model.toLowerCase().includes(q)
        ).slice(0, 60);
    }

    get filteredLineModels() {
        if (this.state.lineModel) return this.state.modelList.slice(0, 60);
        const q = (this.state.lineModelSearchQuery || "").toLowerCase();
        if (!q) return this.state.modelList.slice(0, 60);
        return this.state.modelList.filter(m =>
            m.name.toLowerCase().includes(q) || m.model.toLowerCase().includes(q)
        ).slice(0, 60);
    }

    // ── Target Model search ───────────────────────────────────────────────────

    onModelSearch(e) {
        this.state.modelSearchQuery = e.target.value;
        this.state.modelDropdownOpen = true;
        // Clear current selection so the list re-filters
        if (this.state.selectedModel) {
            this.state.selectedModel = "";
            this.state.selectedModelName = "";
            this.state.modelFields = [];
            this.state.uniqueField = "";
        }
    }

    async selectModelItem(m) {
        this.state.modelSearchQuery = `${m.name} (${m.model})`;
        this.state.modelDropdownOpen = false;
        this.state.selectedModel = m.model;
        this.state.selectedModelName = m.name;
        this.state.uniqueField = "";
        this.state.modelFields = [];
        if (!m.model) return;

        this.state.loadingFields = true;
        try {
            const res = await this.rpc("/purchase/import/get_model_fields", { model_name: m.model });
            if (res.error) { this._setError(res.error); return; }
            this.state.modelFields = res.fields || [];
            const preferred = ['name', 'ref', 'code', 'partner_ref', 'x_name'];
            const auto = this.state.modelFields.find(f => preferred.includes(f.name));
            this.state.uniqueField = auto ? auto.name : (this.state.modelFields[0]?.name || "");
        } catch (err) {
            this._setError("Could not load fields: " + err.message);
        } finally {
            this.state.loadingFields = false;
        }
    }

    onModelSearchBlur() {
        // Delay so mousedown on dropdown items fires before blur closes the list
        setTimeout(() => { this.state.modelDropdownOpen = false; }, 180);
    }

    clearModel() {
        this.state.modelSearchQuery = "";
        this.state.selectedModel = "";
        this.state.selectedModelName = "";
        this.state.modelFields = [];
        this.state.uniqueField = "";
        this.state.modelDropdownOpen = false;
    }

    // ── Line Model search ─────────────────────────────────────────────────────

    onLineModelSearch(e) {
        this.state.lineModelSearchQuery = e.target.value;
        this.state.lineModelDropdownOpen = true;
        if (this.state.lineModel) {
            this.state.lineModel = "";
            this.state.lineModelName = "";
            this.state.lineModelFields = [];
            this.state.lineLinkField = "";
        }
    }

    async selectLineModelItem(m) {
        this.state.lineModelSearchQuery = `${m.name} (${m.model})`;
        this.state.lineModelDropdownOpen = false;
        this.state.lineModel = m.model;
        this.state.lineModelName = m.name;
        this.state.lineLinkField = "";
        this.state.lineModelFields = [];
        if (!m.model) return;

        this.state.loadingLineFields = true;
        try {
            const res = await this.rpc("/purchase/import/get_model_fields", { model_name: m.model });
            if (res.error) { this._setError(res.error); return; }
            this.state.lineModelFields = res.fields || [];
            const link = this.state.lineModelFields.find(
                f => f.type === 'many2one' && f.name.includes('order') || f.name === 'order_id'
            );
            this.state.lineLinkField = link ? link.name : "";
        } catch (err) {
            this._setError("Could not load line model fields: " + err.message);
        } finally {
            this.state.loadingLineFields = false;
        }
    }

    onLineModelSearchBlur() {
        setTimeout(() => { this.state.lineModelDropdownOpen = false; }, 180);
    }

    // ── Field catalogue ──────────────────────────────────────────────────────

    async _loadFields() {
        try {
            const res = await this.rpc("/purchase/import/get_fields", {});
            this.state.poFields  = res.po_fields  || [];
            this.state.polFields = res.pol_fields || [];
        } catch (e) {
            this._setError("Could not load Odoo field definitions: " + e.message);
        }
    }

    async _loadModelList() {
        this.state.loadingModels = true;
        try {
            const res = await this.rpc("/purchase/import/get_importable_models", {});
            this.state.modelList = res || [];

            // Pre-select: 1) active_model from action context  2) last used (localStorage)
            const activeModel = this.props?.action?.context?.active_model
                || localStorage.getItem('po_bulk_import_last_model') || '';
            if (activeModel) {
                const found = this.state.modelList.find(m => m.model === activeModel);
                if (found) await this.selectModelItem(found);
            }
        } catch (e) {
            // non-fatal – model selector just stays empty
        } finally {
            this.state.loadingModels = false;
        }
    }

    async searchPo() {
        this.state.poSearchLoading = true;
        try {
            const res = await this.rpc("/purchase/import/search_po", {
                query: this.state.poSearchQuery,
            });
            this.state.poSearchResults = res || [];
        } catch (e) {
            this._setError("PO search failed: " + e.message);
        } finally {
            this.state.poSearchLoading = false;
        }
    }

    selectPo(po) {
        this.state.targetPoId     = po.id;
        this.state.targetPoName   = po.name;
        this.state.targetPoVendor = po.vendor;
        this.state.poSearchResults = [];
        this.state.poSearchQuery  = "";
    }

    clearTargetPo() {
        this.state.targetPoId     = null;
        this.state.targetPoName   = "";
        this.state.targetPoVendor = "";
    }

    // ── Utility ──────────────────────────────────────────────────────────────

    stepIndex(key) {
        return STEPS.findIndex(s => s.key === key);
    }

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
        this.state.loading     = false;
    }

    // ── File handling ─────────────────────────────────────────────────────────

    triggerFileInput() {
        this.fileInput.el && this.fileInput.el.click();
    }

    onDragOver(e) {
        this.dropzone.el && this.dropzone.el.classList.add("dragover");
    }

    onDragLeave() {
        this.dropzone.el && this.dropzone.el.classList.remove("dragover");
    }

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
            this.state.fileData  = b64;
            this.state.fileName  = file.name;
            this.state.globalError  = null;
            this.state.sheetNames   = [];
            this.state.selectedSheet = "";
            // Detect sheets in XLSX files
            const isXlsx = file.name.toLowerCase().match(/\.xlsx?$/);
            if (isXlsx) {
                try {
                    const res = await this.rpc("/purchase/import/get_sheet_names", {
                        file_data: b64,
                        file_name: file.name,
                    });
                    if (!res.error && res.sheets && res.sheets.length > 1) {
                        this.state.sheetNames    = res.sheets;
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
            // If has-lines mode but line model fields aren't loaded yet, load them now
            if (this.state.hasLines && this.state.lineModel && !this.state.lineModelFields.length) {
                const lf = await this.rpc("/purchase/import/get_model_fields",
                                          { model_name: this.state.lineModel });
                if (!lf.error) this.state.lineModelFields = lf.fields || [];
            }

            const res = await this.rpc("/purchase/import/parse_headers", {
                file_data:   this.state.fileData,
                file_name:   this.state.fileName,
                sheet_name:  this.state.selectedSheet || null,
            });
            if (res.error) { this._setError(res.error); return; }

            this.state.headers = res.headers || [];

            // Server-side auto-map (uses actual Odoo field metadata)
            let mapping = {};
            try {
                const am = await this.rpc("/purchase/import/auto_map", {
                    headers:         this.state.headers,
                    model_name:      this.state.selectedModel || 'purchase.order',
                    line_model_name: this.state.hasLines ? (this.state.lineModel || '') : '',
                });
                mapping = am || {};
            } catch (_e) { /* fall through to client-side */ }

            // Fill any gaps with client-side heuristics
            for (const col of this.state.headers) {
                if (!mapping[col]) mapping[col] = this._autoDetect(col);
            }
            this.state.mapping = mapping;
            this.state.step    = "mapping";
            this._saveSession();
        } catch (e) {
            this._setError(e.message || String(e));
        } finally {
            this.state.loading = false;
        }
    }

    _autoDetect(col) {
        // Normalise: lower-case, replace non-alphanumeric with _
        const c = col.toLowerCase().replace(/[^a-z0-9]/g, "_");

        // Aliases that belong to the HEADER (parent / PO) model
        const headerAliases = {
            name:             ["po_number","order_number","po_no","po_num",
                               "po_ref","po","name","order_no","order_name",
                               "bill_reference","bill_ref","bill_no","invoice_ref"],
            partner_id:       ["vendor","supplier","partner","vendor_name","supplier_name",
                               "customer","vendor_id","supplier_id","partner_name","company",
                               "purchase_order"],
            partner_ref:      ["vendor_ref","vendor_reference","external_ref","source_ref",
                               "supplier_ref","reference","supplier_bill_no","vendor_bill_ref"],
            date_order:       ["order_date","po_date","date","created_date","purchase_date",
                               "order_dt","orderdate"],
            currency_id:      ["currency","currency_code","curr"],
            payment_term_id:  ["payment_term","payment_terms","pay_term","terms"],
            user_id:          ["purchase_rep","buyer","responsible","assigned_to"],
            notes:            ["notes","remarks","terms","comment","internal_notes","note"],
            incoterm_id:      ["incoterm","incoterms","delivery_terms"],
            company_id:       ["company","company_name"],
        };

        // Aliases that belong to the LINE (child) model
        const lineAliases = {
            product_id:       ["product","product_code","item","sku","product_name","item_code",
                               "product_ref","part_no","part_number","article","material",
                               "material_code","product_id"],
            name:             ["description","line_description","product_description","desc",
                               "item_description","detail"],
            product_qty:      ["qty","quantity","ordered_qty","qty_ordered","amount","count",
                               "order_qty","purchase_qty","qty_purchase","quantity_ordered"],
            price_unit:       ["price","unit_price","cost","rate","unit_cost","unit_rate",
                               "price_unit","rate_per_unit","up"],
            product_uom:      ["uom","unit","unit_of_measure","uom_name","measure","unit_type"],
            date_planned:     ["delivery_date","scheduled_date","expected_date","due_date",
                               "required_date","need_date","delivery_dt"],
            taxes_id:         ["tax","taxes","tax_name","gst","vat"],
        };

        if (this.state.hasLines) {
            // ── Has-Lines mode: return h:field or l:field ──────────────────

            // 1. Exact match against header model fields
            if (this.state.modelFields.find(f => f.name === c))
                return 'h:' + c;

            // 2. Exact match against line model fields
            if (this.state.lineModelFields.find(f => f.name === c))
                return 'l:' + c;

            // 3. Header alias match
            for (const [fieldName, aliasList] of Object.entries(headerAliases)) {
                if (aliasList.includes(c) && this.state.modelFields.find(f => f.name === fieldName))
                    return 'h:' + fieldName;
            }

            // 4. Line alias match
            for (const [fieldName, aliasList] of Object.entries(lineAliases)) {
                if (aliasList.includes(c) && this.state.lineModelFields.find(f => f.name === fieldName))
                    return 'l:' + fieldName;
            }

            // 5. Fuzzy match against header field labels
            const colWords = c.split("_").filter(Boolean);
            if (colWords.length) {
                const hFuzzy = this.state.modelFields.find(f => {
                    const lbl = f.label.toLowerCase().replace(/[^a-z0-9]/g, "_");
                    return colWords.every(w => lbl.includes(w));
                });
                if (hFuzzy) return 'h:' + hFuzzy.name;

                // 6. Fuzzy match against line field labels
                const lFuzzy = this.state.lineModelFields.find(f => {
                    const lbl = f.label.toLowerCase().replace(/[^a-z0-9]/g, "_");
                    return colWords.every(w => lbl.includes(w));
                });
                if (lFuzzy) return 'l:' + lFuzzy.name;
            }

            return "";
        }

        // ── product.label aliases ─────────────────────────────────────────────
        const labelAliases = {
            name:                        ['label_reference', 'label_ref', 'label_no', 'reference'],
            label_number:                ['label_number', 'label_num', 'tag_no', 'tag_number'],
            label_name:                  ['label_name', 'tag_name'],
            age_import:                  ['age', 'age_days', 'days', 'label_age', 'age_day',
                                          'age__days_', 'age_days_', 'age__days'],
            product_id:                  ['product_variant', 'variant', 'product_var', 'product_variant_name',
                                          'variant_name', 'item_variant', 'product', 'product_code',
                                          'item', 'sku', 'product_name'],
            product_tmpl_id:             ['product_template', 'template', 'product_tmpl', 'product_template_name'],
            purchase_id:                 ['purchase_order', 'purchase_order_no', 'po', 'po_number',
                                          'po_no', 'po_ref', 'po_name'],
            branch_id:                   ['branch', 'branch_name'],
            branch_location_id:          ['destination_location', 'dest_location', 'branch_location', 'to_location'],
            source_location_id:          ['source_location', 'from_location', 'src_location'],
            purity_id:                   ['purity', 'purchase_purity', 'karat'],
            sale_purity_id:              ['sale_purity', 'sale_karat'],
            job_work_id:                 ['job_work', 'jobwork', 'jobs_work', 'jobswork', 'jobs work', 'job work'],
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

        // ── Single-model mode ─────────────────────────────────────────────────

        // 1. Exact field name match
        if (this.state.modelFields.find(f => f.name === c)) return c;

        // 2. Alias match (header + line + label-specific aliases combined)
        const allAliases = Object.assign({}, headerAliases, lineAliases, labelAliases);
        for (const [fieldName, aliasList] of Object.entries(allAliases)) {
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
            const am = await this.rpc("/purchase/import/auto_map", {
                headers:         this.state.headers,
                model_name:      this.state.selectedModel || 'purchase.order',
                line_model_name: this.state.hasLines ? (this.state.lineModel || '') : '',
            });
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
            const res = await this.rpc("/purchase/import/get_preview", {
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
            // Remember the last used model for next page load
            if (this.state.selectedModel) {
                try { localStorage.setItem('po_bulk_import_last_model', this.state.selectedModel); } catch (_e) {}
            }

            const res = await this.rpc("/purchase/import/create_job", {
                file_data:       this.state.fileData,
                file_name:       this.state.fileName,
                mapping:         this.state.mapping,
                batch_size:      this.state.batchSize,
                match_field:     this.state.matchField,
                model_name:      this.state.selectedModel || 'purchase.order',
                unique_field:    this.state.uniqueField || 'name',
                has_lines:       this.state.hasLines,
                line_model:      this.state.lineModel,
                line_link_field: this.state.lineLinkField,
                group_by_field:  this.state.groupByField || this.state.uniqueField,
                auto_create_m2o:      this.state.autoCreateM2o,
                auto_confirm_receive: this.state.autoConfirmReceive,
                auto_create_bill:     this.state.autoCreateBill,
                sheet_name:           this.state.selectedSheet || null,
                target_po_id:         this.state.targetPoId || null,
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

            // Kick off first batch automatically
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
        this.state.batchRunning  = true;
        this.state.batchComplete = false;
        this.state.globalError   = null;
        try {
            // Auto-loop through all remaining batches so the user only needs
            // to click once. The loop exits when the server signals done=true
            // or when an error occurs (user can then click Continue to retry).
            while (true) {
                const res = await this.rpc("/purchase/import/process_batch", {
                    job_id: this.state.jobId,
                });
                if (res.error) { this._setError(res.error); return; }

                Object.assign(this.state, {
                    currentBatch:  res.batch_number   || this.state.currentBatch,
                    totalBatches:  res.total_batches  || this.state.totalBatches,
                    processedRows: res.total_stats ? res.total_stats.processed : this.state.processedRows,
                    currentOffset: res.offset         || this.state.currentOffset,
                    batchStats:    res.batch_stats    || this.state.batchStats,
                    totalStats:    res.total_stats    || this.state.totalStats,
                    batchComplete: true,
                    allDone:       res.done === true,
                    skippedReasons: res.skipped_reasons || [],
                    errorReasons:   res.error_reasons   || [],
                });

                this._saveSession();

                if (res.done) {
                    this.state.step    = "done";
                    this.state.allDone = true;
                    this._saveSession();
                    return;
                }
                // Not done yet — continue to next batch automatically
            }
        } catch (e) {
            // Odoo wraps server errors as e.message = "Odoo Server Error"
            // Try to extract the actual cause from e.data or e.cause
            const detail = e?.data?.message || e?.cause?.message || e.message || String(e);
            this._setError(detail);
        } finally {
            this.state.batchRunning = false;
        }
    }

    async cancelImport() {
        if (!this.state.jobId) { this.state.step = "upload"; return; }
        try {
            await this.rpc("/purchase/import/cancel", { job_id: this.state.jobId });
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
            step:               this.state.step,
            jobId:              this.state.jobId,
            fileName:           this.state.fileName,
            selectedModel:      this.state.selectedModel,
            selectedModelName:  this.state.selectedModelName,
            uniqueField:        this.state.uniqueField,
            headers:            this.state.headers,
            mapping:            this.state.mapping,
            previewRows:        this.state.previewRows,
            hasLines:           this.state.hasLines,
            lineModel:          this.state.lineModel,
            lineModelName:      this.state.lineModelName,
            lineLinkField:      this.state.lineLinkField,
            groupByField:       this.state.groupByField,
            autoCreateM2o:      this.state.autoCreateM2o,
            autoConfirmReceive: this.state.autoConfirmReceive,
            autoCreateBill:     this.state.autoCreateBill,
            totalRows:          this.state.totalRows,
            processedRows:      this.state.processedRows,
            currentBatch:       this.state.currentBatch,
            totalBatches:       this.state.totalBatches,
            currentOffset:      this.state.currentOffset,
            totalStats:         this.state.totalStats,
            allDone:            this.state.allDone,
        };
        // Try with fileData first; fall back without it if quota is exceeded
        for (const payload of [{ ...base, fileData: this.state.fileData }, base]) {
            try {
                localStorage.setItem('po_bulk_import_session', JSON.stringify(payload));
                return;
            } catch (_e) { /* QuotaExceededError – retry without fileData */ }
        }
    }

    _clearSession() {
        try { localStorage.removeItem('po_bulk_import_session'); } catch (e) {}
    }

    async _restoreSession() {
        try {
            const raw = localStorage.getItem('po_bulk_import_session');
            if (!raw) return;
            const saved = JSON.parse(raw);
            if (!saved.step || saved.step === 'upload') return;

            if (saved.step === 'importing' || saved.step === 'done') {
                if (!saved.jobId) return;
                const res = await this.rpc("/purchase/import/job_status", { job_id: saved.jobId });
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
                    step:               saved.step,
                    fileData:           saved.fileData           || null,
                    fileName:           saved.fileName           || '',
                    selectedModel:      saved.selectedModel      || '',
                    selectedModelName:  saved.selectedModelName  || '',
                    uniqueField:        saved.uniqueField        || '',
                    headers:            saved.headers            || [],
                    mapping:            saved.mapping            || {},
                    previewRows:        saved.previewRows        || [],
                    hasLines:           !!saved.hasLines,
                    lineModel:          saved.lineModel          || '',
                    lineModelName:      saved.lineModelName      || '',
                    lineLinkField:      saved.lineLinkField      || '',
                    groupByField:       saved.groupByField       || '',
                    autoCreateM2o:      !!saved.autoCreateM2o,
                    autoConfirmReceive: !!saved.autoConfirmReceive,
                    autoCreateBill:     !!saved.autoCreateBill,
                });
                // Reload field definitions so mapping dropdowns are populated
                if (saved.selectedModel) {
                    this.rpc("/purchase/import/get_model_fields", { model_name: saved.selectedModel })
                        .then(r => { if (!r.error) this.state.modelFields = r.fields || []; })
                        .catch(() => {});
                }
                if (saved.lineModel) {
                    this.rpc("/purchase/import/get_model_fields", { model_name: saved.lineModel })
                        .then(r => { if (!r.error) this.state.lineModelFields = r.fields || []; })
                        .catch(() => {});
                }
            }
        } catch (e) {
            this._clearSession();
        }
    }

    // ── Final buttons ─────────────────────────────────────────────────────────

    async backToMapping() {
        // Cancel any in-progress job, keep file + model, go back to mapping
        if (this.state.jobId) {
            try {
                await this.rpc("/purchase/import/cancel", { job_id: this.state.jobId });
            } catch (e) { /* non-fatal */ }
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
            batchStats:    { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0 },
            totalStats:    { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0 },
            skippedReasons: [],
            errorReasons:   [],
        });
        // Re-run auto-detect with current model fields
        const mapping = {};
        for (const col of this.state.headers) {
            mapping[col] = this._autoDetect(col);
        }
        this.state.mapping = mapping;
        this._saveSession();
    }

    startNewImport() {
        this._clearSession();
        Object.assign(this.state, {
            step:           "upload",
            fileData:       null,
            fileName:       "",
            selectedModel:  "",
            selectedModelName: "",
            modelSearchQuery: "",
            uniqueField:    "",
            modelFields:    [],
            headers:        [],
            mapping:        {},
            previewRows:    [],
            jobId:          null,
            totalRows:      0,
            processedRows:  0,
            currentOffset:  0,
            currentBatch:   0,
            totalBatches:   0,
            batchComplete:  false,
            allDone:        false,
            globalError:    null,
            targetPoId:     null,
            targetPoName:   "",
            targetPoVendor: "",
            poSearchQuery:  "",
            poSearchResults: [],
            batchStats: { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0 },
            totalStats: { created: 0, updated: 0, duplicates: 0, skipped: 0, errors: 0 },
            skippedReasons: [],
            errorReasons:   [],
        });
    }

    async loadPoSummary() {
        this.state.summaryLoading = true;
        this.state.summaryVisible = true;
        try {
            const data = await this.rpc("/purchase/import/get_po_summary", {
                job_id: this.state.jobId || null,
            });
            this.state.summaryData = data;
        } catch (e) {
            this.notif.add("Failed to load PO summary", { type: "danger" });
        } finally {
            this.state.summaryLoading = false;
        }
    }

    async approvePendingBills() {
        if (this.state.approveLoading) return;
        this.state.approveLoading = true;
        try {
            const res = await this.rpc("/purchase/import/approve_bills", {
                job_id: this.state.jobId || null,
            });
            if (res.error) {
                this.notif.add(res.error, { type: "danger" });
            } else {
                this.notif.add(`${res.approved} bill(s) approved successfully.`, { type: "success" });
                await this.loadPoSummary();
            }
        } catch (e) {
            this.notif.add("Failed to approve bills: " + (e.message || String(e)), { type: "danger" });
        } finally {
            this.state.approveLoading = false;
        }
    }

    async confirmPendingBills() {
        if (this.state.confirmLoading) return;
        this.state.confirmLoading = true;
        try {
            const res = await this.rpc("/purchase/import/confirm_bills", {
                job_id: this.state.jobId || null,
            });
            if (res.error) {
                this.notif.add(res.error, { type: "danger" });
            } else {
                this.notif.add(`${res.confirmed} bill(s) confirmed successfully.`, { type: "success" });
                await this.loadPoSummary();
            }
        } catch (e) {
            this.notif.add("Failed to confirm bills: " + (e.message || String(e)), { type: "danger" });
        } finally {
            this.state.confirmLoading = false;
        }
    }

    async openVendorModal() {
        if (!this.state.jobId) return;
        this.state.vendorModalOpen = true;
        this.state.vendorLoading   = true;
        this.state.vendorBreakdown = [];
        try {
            const rows = await this.rpc("/purchase/import/get_job_vendors", {
                job_id: this.state.jobId,
            });
            this.state.vendorBreakdown = rows || [];
        } catch (e) {
            this.notif.add("Failed to load vendor breakdown", { type: "danger" });
        } finally {
            this.state.vendorLoading = false;
        }
    }

    closeVendorModal() {
        this.state.vendorModalOpen = false;
    }

    viewHistory() {
        this.actionSvc.doAction({
            type: "ir.actions.act_window",
            name: "Import Jobs",
            res_model: "po.import.job",
            view_mode: "tree,form",
            views: [[false, "tree"], [false, "form"]],
        });
    }

    async triggerLabelTransfers() {
        this.state.transferLoading = true;
        try {
            const res = await this.rpc("/purchase/import/trigger_label_transfers", {
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

registry.category("actions").add("po_bulk_import_wizard", POBulkImportWizard);