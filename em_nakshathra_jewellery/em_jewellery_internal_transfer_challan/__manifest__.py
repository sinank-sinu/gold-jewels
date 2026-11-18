# -*- coding: utf-8 -*-
{
    'name': 'Jewellery Internal Transfer Delivery Challan (Rule 55)',
    'version': '17.0.1.0.0',
    'summary': 'Rule 55 Stock Transfer Delivery Challan report and transit details for internal jewellery stock transfers.',
    'description': """
Jewellery Internal Transfer Delivery Challan (Rule 55)
=====================================================
- Rule 55 compliant Delivery Challan report for internal branch transfers (stock.picking).
- Transit details tab on internal transfers: E-Way Bill Number, Vehicle Number, Transporter Name, Batch No., Challan Remarks.
- Clean 5-column product summary without variant attributes, rates, or taxes:
  Sl No | Product Name | No of Pieces | Gross Wt (g) | Net Wt (g)
- Detailed tag / barcode annexure breakdown on page 2.
- Integrates directly with Odoo standard Delivery Slip print action.
    """,
    'category': 'Jewellery Management',
    'author': 'Nakshathra ERP Team',
    'depends': [
        'stock',
        'em_jewellery_management',
    ],
    'data': [
        'views/stock_picking_views.xml',
        'report/stock_transfer_challan_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

