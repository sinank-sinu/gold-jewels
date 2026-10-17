# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    image_2_1920 = fields.Image("Image 2", max_width=1920, max_height=1920)
    image_3_1920 = fields.Image("Image 3", max_width=1920, max_height=1920)
    image_4_1920 = fields.Image("Image 4", max_width=1920, max_height=1920)
