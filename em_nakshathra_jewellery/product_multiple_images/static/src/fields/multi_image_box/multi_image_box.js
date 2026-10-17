/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { url } from "@web/core/utils/urls";
import { isBinarySize } from "@web/core/utils/binary";
import { fileTypeMagicWordMap, imageCacheKey } from "@web/views/fields/image/image_field";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, useRef } from "@odoo/owl";

const placeholder = "/web/static/img/placeholder.png";
const SLOTS = ["image_1920", "image_2_1920", "image_3_1920", "image_4_1920"];

export class MultiImageBox extends Component {
    static template = "product_multiple_images.MultiImageBox";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.fileInputRef = useRef("fileInput");
        this.state = useState({
            currentSlot: 1, // 1, 2, 3, or 4
        });
    }

    get rawCacheKey() {
        return this.props.record.data.write_date;
    }

    get currentFieldName() {
        return SLOTS[this.state.currentSlot - 1];
    }

    get currentVal() {
        return this.props.record.data[this.currentFieldName];
    }

    get currentImageUrl() {
        const val = this.currentVal;
        const fieldName = this.currentFieldName;
        const record = this.props.record;

        if (val) {
            if (isBinarySize(val)) {
                return url("/web/image", {
                    model: record.resModel,
                    id: record.resId,
                    field: fieldName,
                    unique: imageCacheKey(this.rawCacheKey),
                });
            } else {
                const magic = fileTypeMagicWordMap[val[0]] || "png";
                return `data:image/${magic};base64,${val}`;
            }
        }
        return placeholder;
    }

    hasImage(slot) {
        const field = SLOTS[slot - 1];
        return Boolean(this.props.record.data[field]);
    }

    goToSlot(slot) {
        if (slot >= 1 && slot <= 4) {
            this.state.currentSlot = slot;
        }
    }

    prevSlot() {
        this.state.currentSlot = this.state.currentSlot > 1 ? this.state.currentSlot - 1 : 4;
    }

    nextSlot() {
        this.state.currentSlot = this.state.currentSlot < 4 ? this.state.currentSlot + 1 : 1;
    }

    triggerFileInput() {
        if (this.fileInputRef.el && !this.props.readonly) {
            this.fileInputRef.el.click();
        }
    }

    onImageClick() {
        if (!this.hasImage(this.state.currentSlot)) {
            this.triggerFileInput();
        }
    }

    async onFilesSelected(ev) {
        const input = ev.target;
        if (!input.files || input.files.length === 0) {
            return;
        }
        const files = Array.from(input.files).slice(0, 4);
        const updates = {};

        if (files.length === 1) {
            // Single file selected: update currently active slot
            const b64 = await this.fileToBase64(files[0]);
            updates[this.currentFieldName] = b64;
        } else {
            // Multiple files selected (up to 4): populate slots 1..N
            for (let i = 0; i < files.length && i < 4; i++) {
                const targetField = SLOTS[i];
                updates[targetField] = await this.fileToBase64(files[i]);
            }
        }
        input.value = "";
        await this.props.record.update(updates);
    }

    async onDropFiles(ev) {
        if (this.props.readonly) return;
        const dt = ev.dataTransfer;
        if (!dt || !dt.files || dt.files.length === 0) return;
        const files = Array.from(dt.files).filter(f => f.type.startsWith("image/")).slice(0, 4);
        if (files.length === 0) return;
        const updates = {};
        if (files.length === 1) {
            updates[this.currentFieldName] = await this.fileToBase64(files[0]);
        } else {
            for (let i = 0; i < files.length && i < 4; i++) {
                updates[SLOTS[i]] = await this.fileToBase64(files[i]);
            }
        }
        await this.props.record.update(updates);
    }

    fileToBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const result = reader.result;
                if (typeof result === "string") {
                    const commaIdx = result.indexOf(",");
                    resolve(commaIdx !== -1 ? result.slice(commaIdx + 1) : result);
                } else {
                    resolve("");
                }
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async onClearCurrentSlot() {
        await this.props.record.update({ [this.currentFieldName]: false });
    }
}

export const multiImageBox = {
    component: MultiImageBox,
    displayName: _t("Multi Image Box (Up to 4)"),
    supportedFieldTypes: ["binary", "image"],
    fieldDependencies: [
        { name: "image_2_1920", type: "binary" },
        { name: "image_3_1920", type: "binary" },
        { name: "image_4_1920", type: "binary" },
        { name: "write_date", type: "datetime" },
    ],
};

registry.category("fields").add("multi_image_box", multiImageBox);
