import sys
import logging

def run_correction(env):
    cr = env.cr
    
    # Find pickings linked to POs where location_id is not the partner's supplier location
    cr.execute("""
        SELECT sp.id, sp.name, sp.location_id, rp.property_stock_supplier, rp.id as partner_id
        FROM stock_picking sp
        JOIN purchase_order po ON sp.purchase_id = po.id
        JOIN res_partner rp ON po.partner_id = rp.id
        WHERE sp.state = 'done'
    """)
    rows = cr.fetchall()
    
    wrong_pickings = []
    for row in rows:
        picking_id, picking_name, loc_id, prop_supplier, partner_id = row
        partner = env['res.partner'].browse(partner_id)
        supplier_loc = partner.property_stock_supplier.id
        if loc_id != supplier_loc:
            wrong_pickings.append((picking_id, picking_name, loc_id, supplier_loc))
            
    print(f"Found {len(wrong_pickings)} pickings with wrong source location.")
    for wp in wrong_pickings[:10]:
        print(f"Picking {wp[1]} (ID {wp[0]}): currently {wp[2]}, should be {wp[3]}")

if __name__ == '__main__':
    run_correction(env)
    env.cr.commit()
