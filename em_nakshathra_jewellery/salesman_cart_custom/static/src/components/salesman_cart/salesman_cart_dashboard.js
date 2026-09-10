/** @odoo-module **/
/** ORIGINAL **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class SalesmanCartDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.userService = useService("user");
        
        this.state = useState({
            products: [],
            activeCart: null,
            cartLines: [],
            loading: false,
            searchQuery: "",
            inputWeights: {}
        });

        onWillStart(async () => {
            await this.loadProducts();
            await this.getOrCreateActiveCart();
        });
    }

    // Filters jewelry items in-memory checking display name, sub_name, and barcode, and sets in_tray status
    get filteredProducts() {
        const query = this.state.searchQuery.trim().toLowerCase();
        const inTrayLabelIds = new Set(
            this.state.cartLines.filter(l => l.label_id && l.label_id[0]).map(l => l.label_id[0])
        );
        const inTrayVaultProductIds = new Set(
            this.state.cartLines.filter(l => (!l.label_id || !l.label_id[0]) && l.product_id && l.product_id[0]).map(l => l.product_id[0])
        );

        let list = this.state.products;
        if (query) {
            list = list.filter(item => {
                const matchName = item.name && item.name.toLowerCase().includes(query);
                const matchSubName = item.sub_name && item.sub_name.toLowerCase().includes(query);
                const matchBarcode = item.barcode && item.barcode.toLowerCase().includes(query);
                return matchName || matchSubName || matchBarcode;
            });
        }

        for (const item of list) {
            item.in_tray = item.type === 'label'
                ? inTrayLabelIds.has(item.db_id)
                : inTrayVaultProductIds.has(item.product_id);
        }

        return list;
    }

    onWeightInput(uniqueId, ev) {
        const val = ev.target.value;
        this.state.inputWeights[uniqueId] = val;
        const item = this.state.products.find(p => p.unique_id === uniqueId);
        if (item) {
            item.inputWeight = val;
        }
    }

    onSearchInput(ev) {
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        this.searchTimeout = setTimeout(async () => {
            await this.loadProducts();
        }, 350);
    }

    async clearSearch() {
        this.state.searchQuery = "";
        await this.loadProducts();
    }

    async loadProducts() {
        this.state.loading = true;

        try {
            // 1. Fetch user's branch
            const userData = await this.orm.read("res.users", [this.userService.userId], ["branch_id"]);
            const userBranchId = userData[0].branch_id ? userData[0].branch_id[0] : false;
            console.log("User Branch ID:", userBranchId);

            if (!userBranchId) {
                this.state.products = [];
                this.state.loading = false;
                return;
            }

            // 2. Look up stock.location records that belong to this branch
            const branchLocations = await this.orm.searchRead(
                "stock.location",
                [["branch_id", "=", userBranchId], ["usage", "=", "internal"]],
                ["id", "complete_name"]
            );
            const branchLocationIds = branchLocations.map(l => l.id);
            console.log("Branch Locations:", branchLocations.map(l => l.complete_name), "IDs:", branchLocationIds);

            if (branchLocationIds.length === 0) {
                this.state.products = [];
                this.state.loading = false;
                this.notification.add("No stock locations found for your branch. Please contact administrator.", { type: "warning" });
                return;
            }

            const query = this.state.searchQuery.trim();

            // 3. Fetch current positive on-hand stock in branch internal locations
            const quants = await this.orm.searchRead(
                "stock.quant",
                [
                    ["location_id", "in", branchLocationIds],
                    ["quantity", ">", 0]
                ],
                ["product_id", "quantity", "location_id"]
            );
            const inStockProductIds = new Set(quants.map(q => q.product_id[0]));

            let unifiedList = [];

            // 4. Fetch Labeled Items (product.label) in the branch (Pic 2 style cards)
            let labelDomain = [
                ["branch_id", "=", userBranchId],
                ["active", "=", true]
            ];
            if (query) {
                labelDomain.push("|", "|",
                    ["name", "ilike", query],
                    ["barcode", "ilike", query],
                    ["product_id.name", "ilike", query]
                );
            }

            const labelRecords = await this.orm.searchRead(
                "product.label",
                labelDomain,
                ["id", "name", "barcode", "sale_gross_weight", "purchase_gross_weight", "product_id"],
                { limit: 250, order: "id desc" }
            );

            for (const lbl of labelRecords) {
                const pId = lbl.product_id ? lbl.product_id[0] : false;
                const pName = lbl.product_id ? lbl.product_id[1] : 'Unknown Product';

                if (!pId) continue;
                // Verify the product actually has stock in the branch
                if (!inStockProductIds.has(pId)) continue;

                unifiedList.push({
                    unique_id: 'label_' + lbl.id,
                    type: 'label',
                    db_id: lbl.id,
                    product_id: pId,
                    name: lbl.name || 'Unknown Label',
                    sub_name: pName,
                    weight: Number((lbl.sale_gross_weight || lbl.purchase_gross_weight || 0).toFixed(3)),
                    price_info: '',
                    barcode: lbl.barcode || '',
                    inputWeight: 1.0
                });
            }

            // 5. Fetch Vault Products ONLY (is_vault_item = True) (Pic 3 style cards)
            const vaultQuants = await this.orm.searchRead(
                "stock.quant",
                [
                    ["location_id", "in", branchLocationIds],
                    ["quantity", ">", 0],
                    ["product_id.product_tmpl_id.is_vault_item", "=", true]
                ],
                ["product_id", "quantity"]
            );

            const vaultProductMap = {};
            for (const vq of vaultQuants) {
                const pId = vq.product_id[0];
                const pName = vq.product_id[1];
                if (!vaultProductMap[pId]) {
                    vaultProductMap[pId] = {
                        productId: pId,
                        name: pName,
                        totalQty: 0
                    };
                }
                vaultProductMap[pId].totalQty += vq.quantity;
            }

            for (const pId in vaultProductMap) {
                const vp = vaultProductMap[pId];
                if (query && !vp.name.toLowerCase().includes(query.toLowerCase())) {
                    continue;
                }
                unifiedList.push({
                    unique_id: 'vault_' + vp.productId,
                    type: 'vault',
                    db_id: vp.productId,
                    product_id: vp.productId,
                    name: vp.name,
                    sub_name: 'Vault Item',
                    weight: Number(vp.totalQty.toFixed(3)),
                    price_info: '',
                    barcode: '',
                    inputWeight: 1.0
                });
            }

            // Unlabelled non-vault products are explicitly excluded from catalog.
            console.log("Unified catalog items:", unifiedList.length, "(labeled:", labelRecords.length, ", vault items:", Object.keys(vaultProductMap).length, ")");
            this.state.products = unifiedList;

        } catch (error) {
            console.error("Load Products Error:", error);
            const serverMessage = error.data?.message || error.message || "Failed to load your branch's jewelry catalog.";
            this.notification.add(`Catalog Error: ${serverMessage}`, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async getOrCreateActiveCart() {
        const carts = await this.orm.searchRead(
            "salesman.cart",
            [["state", "=", "draft"], ["create_uid", "=", this.userService.userId]],
            ["id", "name"],
            { limit: 1 }
        );

        if (carts.length > 0) {
            this.state.activeCart = carts[0];
            await this.loadCartLines(this.state.activeCart.id);
        } else {
            const cartId = await this.orm.create("salesman.cart", [{}]);
            this.state.activeCart = { id: cartId };
            this.state.cartLines = [];
        }
    }

    async loadCartLines(cartId) {
        this.state.cartLines = await this.orm.searchRead(
            "salesman.cart.line",
            [["cart_id", "=", cartId]],
            ["id", "product_id", "qty", "weight", "price_subtotal", "label_id", "is_locked"]
        );
    }

    async toggleLock(lineId) {
        this.state.loading = true;
        try {
            const line = this.state.cartLines.find(l => l.id === lineId);
            if (line) {
                await this.orm.write("salesman.cart.line", [lineId], { is_locked: !line.is_locked });
                await this.loadCartLines(this.state.activeCart.id);
            }
        } catch (error) {
            this.notification.add("Failed to toggle lock.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async addToCart(uniqueId) {
        this.state.loading = true;
        try {
            const item = this.state.products.find(p => p.unique_id === uniqueId);
            if (!item || !item.product_id) return;

            let productId = item.product_id;
            let labelId = item.type === 'label' ? item.db_id : false;
            const enteredVal = this.state.inputWeights[uniqueId] !== undefined
                ? this.state.inputWeights[uniqueId]
                : item.inputWeight;
            let qty = item.type === 'label' ? 1.0 : (parseFloat(enteredVal) || 1.0);

            if (qty <= 0) {
                this.notification.add("Please enter a valid weight greater than zero.", { type: "warning" });
                this.state.loading = false;
                return;
            }

            if (item.type === 'label' && this.state.cartLines.some(l => l.label_id && l.label_id[0] === item.db_id)) {
                this.notification.add("This labeled piece is already in your tray.", { type: "warning" });
                this.state.loading = false;
                return;
            }

            if ((item.type === 'vault' || item.type === 'product') && this.state.cartLines.some(l => (!l.label_id || !l.label_id[0]) && l.product_id && l.product_id[0] === productId)) {
                this.notification.add("This vault product is already in your tray. Remove it first if you wish to adjust the weight.", { type: "warning" });
                this.state.loading = false;
                return;
            }

            if ((item.type === 'vault' || item.type === 'product') && qty > item.weight) {
                this.notification.add(`Cannot add ${qty}g. Only ${item.weight}g available in stock.`, { type: "warning" });
                this.state.loading = false;
                return;
            }

            await this.orm.call(
                "salesman.cart",
                "action_add_product",
                [this.state.activeCart.id, productId, false, qty, labelId]
            );
            this.notification.add("Item secure in your showroom tray!", { type: "success" });
            await this.loadCartLines(this.state.activeCart.id);
        } catch (error) {
            const serverMessage = error.data?.message || error.message || "Unknown Inventory Constraint";
            this.notification.add(`Tray Update Denied: ${serverMessage}`, { type: "danger", sticky: true });
        } finally {
            this.state.loading = false;
        }
    }

    async removeFromCart(lineId) {
        this.state.loading = true;
        try {
            await this.orm.call(
                "salesman.cart",
                "action_remove_line",
                [this.state.activeCart.id, lineId]
            );
            this.notification.add("Item removed and returned to main safe stock.", { type: "info" });
            await this.loadCartLines(this.state.activeCart.id);
        } catch (error) {
            const serverMessage = error.data?.message || error.message || "Failed to remove item.";
            this.notification.add(`Removal Denied: ${serverMessage}`, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }
    
    async proceedToCheckout() {
        if (this.state.cartLines.length === 0) return;
        
        try {
            await this.orm.call(
                "salesman.cart",
                "action_checkout_to_so",
                [this.state.activeCart.id]
            );
            this.notification.add("Cart pushed to billing desk successfully!", { type: "success" });
            
            this.state.activeCart = null;
            await this.getOrCreateActiveCart();
        } catch (error) {
            const serverMessage = error.data?.message || error.message || "Please verify inventory balances.";
            this.notification.add(`Checkout failed: ${serverMessage}`, { type: "danger" });
        }
    }
}

SalesmanCartDashboard.props = {
    action: { type: Object, optional: true },
    actionId: { type: Number, optional: true },
    className: { type: String, optional: true },
    "*": true,
};
SalesmanCartDashboard.template = "salesman_cart.SalesmanCartDashboard";
registry.category("actions").add("salesman_cart_dashboard_tags", SalesmanCartDashboard);
