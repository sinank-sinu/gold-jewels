/** @odoo-module **/

import { SaleOrderLineProductField } from "@sale/js/sale_product_field";
import { patch } from "@web/core/utils/patch";

patch(SaleOrderLineProductField.prototype, {
    async getProductConfiguratorDialogProps(edit=false) {
        const saleOrderRecord = this.props.record.model.root;
        const data = saleOrderRecord.data;
        
        // The bug happens because sale_product_configurator assumes the root record is a Sale Order
        // and tries to access data.pricelist_id[0]. In Purchase Orders, this field is missing.
        const isPurchaseOrder = saleOrderRecord.resModel === 'purchase.order';
        const missingPricelist = !data.pricelist_id;
        
        if (isPurchaseOrder && missingPricelist) {
            // Temporarily mock pricelist_id to prevent crash in super.getProductConfiguratorDialogProps
            data.pricelist_id = [false];
            try {
                const props = await super.getProductConfiguratorDialogProps(...arguments);
                delete props.pricelistId;
                return props;
            } finally {
                // Remove the mock immediately after the call
                delete data.pricelist_id;
            }
        }
        
        return super.getProductConfiguratorDialogProps(...arguments);
    },
});
