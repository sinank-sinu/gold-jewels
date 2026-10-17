# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # Variant specific storage (Image 1 is standard image_variant_1920)
    image_variant_2_1920 = fields.Image("Variant Image 2", max_width=1920, max_height=1920)
    image_variant_3_1920 = fields.Image("Variant Image 3", max_width=1920, max_height=1920)
    image_variant_4_1920 = fields.Image("Variant Image 4", max_width=1920, max_height=1920)

    # Computed image fields with fallback to product template (Image 1 is standard image_1920)
    image_2_1920 = fields.Image(
        "Image 2", compute='_compute_image_2_1920', inverse='_set_image_2_1920',
        max_width=1920, max_height=1920)
    image_3_1920 = fields.Image(
        "Image 3", compute='_compute_image_3_1920', inverse='_set_image_3_1920',
        max_width=1920, max_height=1920)
    image_4_1920 = fields.Image(
        "Image 4", compute='_compute_image_4_1920', inverse='_set_image_4_1920',
        max_width=1920, max_height=1920)

    @api.depends('image_variant_2_1920', 'product_tmpl_id.image_2_1920')
    def _compute_image_2_1920(self):
        for record in self:
            record.image_2_1920 = record.image_variant_2_1920 or record.product_tmpl_id.image_2_1920

    def _set_image_2_1920(self):
        return self._set_template_field('image_2_1920', 'image_variant_2_1920')

    @api.depends('image_variant_3_1920', 'product_tmpl_id.image_3_1920')
    def _compute_image_3_1920(self):
        for record in self:
            record.image_3_1920 = record.image_variant_3_1920 or record.product_tmpl_id.image_3_1920

    def _set_image_3_1920(self):
        return self._set_template_field('image_3_1920', 'image_variant_3_1920')

    @api.depends('image_variant_4_1920', 'product_tmpl_id.image_4_1920')
    def _compute_image_4_1920(self):
        for record in self:
            record.image_4_1920 = record.image_variant_4_1920 or record.product_tmpl_id.image_4_1920

    def _set_image_4_1920(self):
        return self._set_template_field('image_4_1920', 'image_variant_4_1920')
