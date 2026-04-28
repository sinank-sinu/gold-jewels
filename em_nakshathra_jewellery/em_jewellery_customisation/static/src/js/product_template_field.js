/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";
import { useService } from "@web/core/utils/hooks";

export class ProductTemplateField extends Many2OneField {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
    }

    async updateRecord(value) {
        // 1. Execute standard Many2One logic
        await super.updateRecord(value);
        
        if (!value) return;

        const templateId = value[0];

        // 2. Local update to the field
        await this.props.record.update({
            product_tmpl_id: value,
        });

        // 3. FORCE SAVE (Matches the switchToForm pattern)
        // This ensures the record exists in DB before we try to link a wizard to it
        console.log("Saving record to ensure data consistency...");
        const isSaved = await this.props.record.save();

        if (!isSaved) {
            // If save fails (e.g. required field missing), stop here
            return;
        }

        // 4. Determine if we need a wizard
        const result = await this.orm.call(
            "product.template",
            "get_variant_info_for_label",
            [templateId]
        );

        if (result.count === 1) {
            // Auto-set the single variant
            const productData = await this.orm.call(
                "product.product",
                "read",
                [result.product_id, ["display_name"]]
            );

            await this.props.record.update({
                product_id: [result.product_id, productData[0].display_name],  
            });
            
            // Final save to commit the auto-selected product
            await this.props.record.save();
        } 
        else {
            // Open the selection wizard
            const action = await this.orm.call(
                "product.template",
                "action_open_variant_wizard",
                [templateId],
                {
                    context: {
                        ...this.props.record.context,
                        label_id: this.props.record.resId,
                    },
                }
            );

            if (action) {
                this.action.doAction(action, {
                    onClose: async () => {
                        // Refresh the view so the product chosen in the wizard appears
                        await this.props.record.load();   
                    },
                });
            }
        }
    }
}

registry.category("fields").add("product_template_variant_selector", {
    component: ProductTemplateField,
    supportedTypes: ["many2one"],
});
