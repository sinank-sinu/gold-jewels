import sys
import logging
from odoo import api, SUPERUSER_ID, registry

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("Fix Source Location")

def fix_po_locations(env):
    _logger.info("Looking for Purchase Order pickings with incorrect source locations...")
    
    # We find all POs that have pickings
    pos = env['purchase.order'].search([('picking_ids', '!=', False)])
    
    to_fix = []
    
    for po in pos:
        supplier_loc_id = po.partner_id.property_stock_supplier.id
        for picking in po.picking_ids.filtered(lambda p: p.state in ['done', 'assigned', 'confirmed']):
            if picking.location_id.id != supplier_loc_id:
                to_fix.append({
                    'picking_id': picking.id,
                    'picking_name': picking.name,
                    'po_name': po.name,
                    'current_loc_id': picking.location_id.id,
                    'correct_loc_id': supplier_loc_id
                })
            
    if not to_fix:
        _logger.info("No pickings found with incorrect source locations.")
        return
        
    _logger.info(f"Found {len(to_fix)} pickings to correct.")
    
    cr = env.cr
    for item in to_fix:
        picking_id = item['picking_id']
        correct_loc_id = item['correct_loc_id']
        _logger.info(f"Fixing Picking {item['picking_name']} (PO: {item['po_name']}) -> Set Source Location to {correct_loc_id}")
        
        # Update stock.picking
        cr.execute("UPDATE stock_picking SET location_id = %s WHERE id = %s", (correct_loc_id, picking_id))
        
        # Update stock.move
        cr.execute("UPDATE stock_move SET location_id = %s WHERE picking_id = %s", (correct_loc_id, picking_id))
        
        # Update stock.move.line
        cr.execute("UPDATE stock_move_line SET location_id = %s WHERE picking_id = %s", (correct_loc_id, picking_id))

    _logger.info("Fix applied successfully. Don't forget to commit.")

if __name__ == '__main__':
    # You can run this in Odoo shell
    # Usage: python3 /home/empireae/odoo17/odoo-bin shell -c /etc/odoo/odoo.conf -d <your_db_name> < fix_source_location.py
    # or just run fix_po_locations(env) and then env.cr.commit() inside the shell
    if 'env' in locals():
        fix_po_locations(env)
        env.cr.commit()
