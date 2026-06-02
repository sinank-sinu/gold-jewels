/** @odoo-module */
import { register_payment_method } from "@point_of_sale/app/store/pos_store";
import { PaymentPineLabs } from "@pine_labs_payment/js/payment_pinelabs";

register_payment_method("pine_labs", PaymentPineLabs);
