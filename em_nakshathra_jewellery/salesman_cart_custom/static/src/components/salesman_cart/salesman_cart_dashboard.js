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
            searchQuery: "" // Added: Reactive search tracking key string
        });

        onWillStart(async () => {
            await this.loadProducts();
            await this.getOrCreateActiveCart();
        });
    }

    // Modified Getter: Filters jewelry items in-memory checking both display name and active label!

    get filteredProducts() {
        const query = this.state.searchQuery.trim().toLowerCase();
        if (!query) {
            return this.state.products;
        }
        return this.state.products.filter(item => {
            const matchName = item.name && item.name.toLowerCase().includes(query);
            const matchSubName = item.sub_name && item.sub_name.toLowerCase().includes(query);
            return matchName || matchSubName;
        });
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

            // 3. Fetch ALL stock.move.line records arriving at branch locations (done state)
            //    Both with and without label_id
            let smlDomain = [
                "&",
                ["location_dest_id", "in", branchLocationIds],
                ["state", "=", "done"]
            ];
            if (query) {
                smlDomain.unshift("&");
                smlDomain.push("|", "|",
                    ["product_id.name", "ilike", query],
                    ["label_id.name", "ilike", query],
                    ["label_id.barcode", "ilike", query]
                );
            }

            let allMoveLines = await this.orm.searchRead(
                "stock.move.line",
                smlDomain,
                ["id", "label_id", "product_id", "quantity", "location_dest_id"],
                { limit: 200, order: "id desc" }
            );
            console.log("All stock.move.line in branch (done):", allMoveLines.length);

            // 4. Separate into labeled and unlabeled lines
            const labeledLines = allMoveLines.filter(ml => ml.label_id && ml.label_id[0]);
            const unlabeledLines = allMoveLines.filter(ml => !ml.label_id || !ml.label_id[0]);

            // 5. Fetch extra label details (gross weight) for labeled lines
            const uniqueLabelIds = [...new Set(labeledLines.map(ml => ml.label_id[0]))];
            let labelDetails = {};
            if (uniqueLabelIds.length > 0) {
                const labelRecords = await this.orm.searchRead(
                    "product.label",
                    [["id", "in", uniqueLabelIds]],
                    ["id", "name", "sale_gross_weight", "barcode"]
                );
                for (let lr of labelRecords) {
                    labelDetails[lr.id] = lr;
                }
            }

            const allProductIds = [...new Set(allMoveLines.filter(ml => ml.product_id && ml.product_id[0]).map(ml => ml.product_id[0]))];

            // 6. Fetch current on-hand stock from stock.quant to verify stock still exists
            let quantDomain = [
                ["location_id", "in", branchLocationIds],
                ["quantity", ">", 0]
            ];
            if (allProductIds.length > 0) {
                quantDomain.push(["product_id", "in", allProductIds]);
            }
            let quants = await this.orm.searchRead(
                "stock.quant",
                quantDomain,
                ["product_id", "quantity", "location_id"]
            );
            const inStockProductIds = new Set(quants.map(q => q.product_id[0]));
            const inStockLabelIds = new Set();

            // For labeled lines, cross-check that the product still has stock in branch
            const seenLabelIds = new Set();
            const seenUnlabeledProductIds = new Set();
            let unifiedList = [];

            // A. Show labeled items (one card per unique label that still has stock)
            for (let ml of labeledLines) {
                const labelId = ml.label_id[0];
                const productId = ml.product_id ? ml.product_id[0] : false;

                if (seenLabelIds.has(labelId)) continue; // Already added this label
                if (productId && !inStockProductIds.has(productId)) continue; // Product no longer in stock
                if (!labelDetails[labelId]) continue; // Skip inactive or deleted labels

                seenLabelIds.add(labelId);
                const detail = labelDetails[labelId];
                unifiedList.push({
                    unique_id: 'label_' + labelId,
                    type: 'label',
                    db_id: labelId,
                    product_id: productId,
                    name: ml.label_id[1] || detail.name || 'Unknown Label',
                    sub_name: ml.product_id ? ml.product_id[1] : 'Unknown Product',
                    weight: detail.sale_gross_weight || ml.quantity,
                    price_info: '',
                    inputWeight: 1.0
                });
                if (productId) inStockLabelIds.add(productId); // Track that this product is covered by a label
            }

            // B. Show unlabeled products — grouped by product, only if still in stock
            //    Skip products that are already fully shown via a labeled card
            for (let ml of unlabeledLines) {
                const productId = ml.product_id ? ml.product_id[0] : false;
                if (!productId) continue;
                if (!inStockProductIds.has(productId)) continue; // No stock anymore
                if (seenUnlabeledProductIds.has(productId)) continue; // Already shown
                // If the product has a labeled card shown, still show it as a separate product card
                // (because this is a DIFFERENT transfer without a label)
                seenUnlabeledProductIds.add(productId);

                const prodQuants = quants.filter(q => q.product_id[0] === productId);
                const totalQty = prodQuants.reduce((sum, q) => sum + q.quantity, 0);

                unifiedList.push({
                    unique_id: 'product_' + productId,
                    type: 'product',
                    db_id: productId,
                    product_id: productId,
                    name: ml.product_id[1],
                    sub_name: 'Stock Item',
                    weight: totalQty,
                    price_info: '',
                    inputWeight: 1.0
                });
            }

            console.log("Unified catalog items:", unifiedList.length, "(labeled:", seenLabelIds.size, ", unlabeled products:", seenUnlabeledProductIds.size, ")");
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
            let qty = item.type === 'label' ? 1.0 : (parseFloat(item.inputWeight) || 1.0);

            if (qty <= 0) {
                this.notification.add("Please enter a valid weight greater than zero.", { type: "warning" });
                this.state.loading = false;
                return;
            }

            if (item.type === 'product' && qty > item.weight) {
                this.notification.add(`Cannot add ${qty}. Only ${item.weight} available in stock.`, { type: "warning" });
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





// /** @odoo-module **/

// import { registry } from "@web/core/registry";
// import { useService } from "@web/core/utils/hooks";
// import { Component, onWillStart, useState } from "@odoo/owl";

// export class SalesmanCartDashboard extends Component {
//     setup() {
//         this.orm = useService("orm");
//         this.actionService = useService("action");
//         this.notification = useService("notification");
//         this.userService = useService("user");
        
//         this.state = useState({
//             products: [],
//             activeCart: null,
//             cartLines: [],
//             loading: false,
//             searchQuery: "" 
//         });

//         onWillStart(async () => {
//             await this.loadProducts();
//             await this.getOrCreateActiveCart();
//         });
//     }

//     // Returns the live server-filtered product array directly
//     get filteredProducts() {
//         return this.state.products;
//     }

//     // Handles keystrokes dynamically
//     async onSearchInput(ev) {
//         // Debounce/short delay can be added later, for now query directly
//         await this.loadProducts();
//     }

//     // Clears search bar cleanly
//     async clearSearch() {
//         this.state.searchQuery = "";
//         await this.loadProducts();
//     }

//     async loadProducts() {
//         this.state.loading = true;
        
//         const domain = [
//             ["sale_ok", "=", true],
//             ["qty_available", ">", 0],
//             ["detailed_type", "=", "product"]
//         ];

//         const query = this.state.searchQuery.trim();
//         if (query) {
//             // Live SQL Join search matching layout properties or labels
//             domain.push("|", "|",
//                 ["display_name", "ilike", query],
//                 ["barcode", "ilike", query],
//                 ["product_label_ids.name", "ilike", query]
//             );
//         }

//         try {
//             this.state.products = await this.orm.searchRead(
//                 "product.product",
//                 domain,
//                 ["id", "display_name", "lst_price", "weight", "qty_available"],
//                 { limit: 40 }
//             );
//         } catch (error) {
//             this.notification.add("Search lookup request failed.", { type: "danger" });
//         } finally {
//             this.state.loading = false;
//         }
//     }

//     async getOrCreateActiveCart() {
//         const carts = await this.orm.searchRead(
//             "salesman.cart",
//             [["state", "=", "draft"], ["create_uid", "=", this.userService.userId]],
//             ["id", "name"],
//             { limit: 1 }
//         );

//         if (carts.length > 0) {
//             this.state.activeCart = carts[0];
//             await this.loadCartLines(this.state.activeCart.id);
//         } else {
//             const cartId = await this.orm.create("salesman.cart", [{}]);
//             this.state.activeCart = { id: cartId };
//             this.state.cartLines = [];
//         }
//     }

//     async loadCartLines(cartId) {
//         this.state.cartLines = await this.orm.searchRead(
//             "salesman.cart.line",
//             [["cart_id", "=", cartId]],
//             ["id", "product_id", "qty", "weight", "price_subtotal"]
//         );
//     }

//     async addToCart(productId) {
//         this.state.loading = true;
//         try {
//             await this.orm.call(
//                 "salesman.cart",
//                 "action_add_product",
//                 [this.state.activeCart.id, productId]
//             );
//             this.notification.add("Item secure in your showroom tray!", { type: "success" });
//             await this.loadCartLines(this.state.activeCart.id);
//         } catch (error) {
//             const serverMessage = error.data?.message || error.message || "Unknown Inventory Constraint";
//             this.notification.add(`Tray Update Denied: ${serverMessage}`, { type: "danger", sticky: true });
//         } finally {
//             this.state.loading = false;
//         }
//     }

//     async removeFromCart(lineId) {
//         this.state.loading = true;
//         try {
//             await this.orm.call(
//                 "salesman.cart",
//                 "action_remove_line",
//                 [this.state.activeCart.id, lineId]
//             );
//             this.notification.add("Item removed and returned to main safe stock.", { type: "info" });
//             await this.loadCartLines(this.state.activeCart.id);
//         } catch (error) {
//             const serverMessage = error.data?.message || error.message || "Failed to remove item.";
//             this.notification.add(`Removal Denied: ${serverMessage}`, { type: "danger" });
//         } finally {
//             this.state.loading = false;
//         }
//     }
    
//     async proceedToCheckout() {
//         if (this.state.cartLines.length === 0) return;
        
//         try {
//             await this.orm.call(
//                 "salesman.cart",
//                 "action_checkout_to_so",
//                 [this.state.activeCart.id]
//             );
//             this.notification.add("Cart pushed to billing desk successfully!", { type: "success" });
            
//             this.state.activeCart = null;
//             await this.getOrCreateActiveCart();
//         } catch (error) {
//             this.notification.add("Checkout failed. Please verify inventory balances.", { type: "danger" });
//         }
//     }
// }

// SalesmanCartDashboard.props = {
//     action: { type: Object, optional: true },
//     actionId: { type: Number, optional: true },
//     className: { type: String, optional: true },
//     "*": true,
// };
// SalesmanCartDashboard.template = "salesman_cart.SalesmanCartDashboard";
// registry.category("actions").add("salesman_cart_dashboard_tags", SalesmanCartDashboard);

