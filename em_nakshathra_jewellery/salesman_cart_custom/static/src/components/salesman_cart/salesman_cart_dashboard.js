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
        return this.state.products.filter(product => {
            const matchName = product.display_name && product.display_name.toLowerCase().includes(query);
            
            // Check if the product has an active label name and if it matches what was typed
            const matchLabel = product.active_label_name && product.active_label_name.toLowerCase().includes(query);
            
            // Return true if either condition matches
            return matchName || matchLabel;
        });
    }

    // async loadProducts() {
    //     this.state.products = await this.orm.searchRead(
    //         "product.product",
    //         [
    //             ["sale_ok", "=", true],
    //             ["qty_available", ">", 0],
    //             ["detailed_type", "=", "product"]
    //         ],
    //         ["id", "display_name", "lst_price", "weight", "qty_available", "active_label_name"],
    //         { 
    //             limit: 40 
    //         }
    //     );
    // }
    async loadProducts() {
        this.state.loading = true;

        try {
            // 1. Fetch the logged-in user's branch ID from their profile
            const userData = await this.orm.read(
                "res.users", 
                [this.userService.userId], 
                ["branch_id"]
            );
            
            // Extract the ID (handles many2one array format [id, "Name"] or false)
            const userBranchId = userData[0].branch_id ? userData[0].branch_id[0] : false;

            // 2. Base Domain: Must be sellable, in stock, and storable
            // We use explicit prefix '&' operators to avoid AST parsing errors in Odoo 17.
            let domain = [
                "&", "&", "&",
                ["sale_ok", "=", true],
                ["qty_available", ">", 0],
                ["detailed_type", "=", "product"]
            ];

            // 3. STRICT BRANCH FILTER: Only display products if they have labels in the user's branch
            if (userBranchId) {
                domain.push(["product_label_ids.branch_id", "=", userBranchId]);
            } else {
                // Defensive fallback: If the user has no branch assigned, show nothing to prevent security leak
                this.state.products = [];
                this.state.loading = false;
                return;
            }

            // 4. Handle search query input matching if typed
            const query = this.state.searchQuery.trim();
            if (query) {
                // Insert a root '&' operator for the new condition block
                domain.unshift("&");
                domain.push("|", "|",
                    ["display_name", "ilike", query],
                    ["barcode", "ilike", query],
                    ["product_label_ids.name", "ilike", query]
                );
            }

            // 5. Fetch the targeted branch catalog
            this.state.products = await this.orm.searchRead(
                "product.product",
                domain,
                ["id", "display_name", "lst_price", "weight", "qty_available", "active_label_name"],
                { limit: 40 }
            );

        } catch (error) {
            this.notification.add("Failed to load your branch's jewelry catalog.", { type: "danger" });
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
            ["id", "product_id", "qty", "weight", "price_subtotal", "active_label_name"]
        );
    }

    async addToCart(productId) {
        this.state.loading = true;
        try {
            await this.orm.call(
                "salesman.cart",
                "action_add_product",
                [this.state.activeCart.id, productId]
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

