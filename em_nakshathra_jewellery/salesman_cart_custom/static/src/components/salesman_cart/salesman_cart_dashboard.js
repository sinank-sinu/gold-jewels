/** @odoo-module **/

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

    // Added Getter: Seamlessly filters jewelry items in-memory on keypress
    get filteredProducts() {
        const query = this.state.searchQuery.trim().toLowerCase();
        if (!query) {
            return this.state.products;
        }
        return this.state.products.filter(product => 
            product.display_name && product.display_name.toLowerCase().includes(query)
        );
    }

    async loadProducts() {
        this.state.products = await this.orm.searchRead(
            "product.product",
            [
                ["sale_ok", "=", true],
                ["qty_available", ">", 0],
                ["detailed_type", "=", "product"]
            ],
            ["id", "display_name", "lst_price", "weight", "qty_available"],
            { 
                limit: 40 
            }
        );
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
            ["id", "product_id", "qty", "weight", "price_subtotal"]
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
            this.notification.add("Checkout failed. Please verify inventory balances.", { type: "danger" });
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
