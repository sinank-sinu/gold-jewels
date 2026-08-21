import logging

_logger = logging.getLogger(__name__)

def fix_uom_g_to_gms(env):
    """
    Finds all done stock moves where the UoM is 'g' but the product's base UoM is different (e.g., 'GMS').
    This discrepancy causes Odoo to convert the quantity by a factor of 1000, 
    resulting in a massive under-reporting of received stock.
    This script fixes the UoM on the move and correctly adjusts the stock quants and SVLs.
    """
    g_uom = env['uom.uom'].search([('name', '=', 'g')], limit=1)
    if not g_uom:
        print("UOM 'g' not found")
        return
        
    # Search for all done moves that used 'g' as UoM
    moves = env['stock.move'].search([
        ('product_uom', '=', g_uom.id),
        ('state', '=', 'done')
    ])
    
    fixed_count = 0
    Quant = env['stock.quant'].sudo()
    
    print(f"Found {len(moves)} moves to analyze...")
    
    for move in moves:
        # Only process Storable Products, otherwise Odoo throws ValidationError when updating quants
        if move.product_id.type != 'product':
            continue
            
        base_uom = move.product_id.uom_id
        if base_uom.id != g_uom.id:
            # Calculate the quantity that was originally incorrectly added to quants.
            # Odoo does: qty_done * (move_uom_factor / product_uom_factor)
            # Since g factor is 1000 and GMS factor is 1, the wrong qty was qty_done / 1000
            wrong_qty_added = move.product_uom_qty / (g_uom.factor / base_uom.factor)
            delta = move.product_uom_qty - wrong_qty_added
            
            if delta <= 0:
                continue
                
            # 1. Update the UoM on the stock_move via SQL to bypass ORM restrictions
            env.cr.execute("UPDATE stock_move SET product_uom = %s WHERE id = %s", 
                           (base_uom.id, move.id))
                           
            # Update UoM on move lines if applicable
            try:
                env.cr.execute("UPDATE stock_move_line SET product_uom_id = %s WHERE move_id = %s", 
                               (base_uom.id, move.id))
            except Exception:
                pass
                
            # 2. Fix the stock valuation layer
            svls = env['stock.valuation.layer'].search([('stock_move_id', '=', move.id)])
            for svl in svls:
                # If SVL qty is wildly different (e.g., 0.05 instead of 48.28), update it
                if abs(svl.quantity - move.product_uom_qty) > 0.01:
                    env.cr.execute("UPDATE stock_valuation_layer SET quantity = %s WHERE id = %s", 
                                   (move.product_uom_qty, svl.id))
                                   
            # 3. Correct the Stock Quants
            # We must subtract the delta from the source location, and add it to the destination
            Quant._update_available_quantity(move.product_id, move.location_id, -delta)
            Quant._update_available_quantity(move.product_id, move.location_dest_id, delta)
                
            fixed_count += 1
            if fixed_count % 500 == 0:
                print(f"Fixed {fixed_count} moves so far...")
                env.cr.commit()

    # Commit all the SQL transactions and ORM updates
    env.cr.commit()
    print(f"Completed! Successfully fixed {fixed_count} moves with UoM mismatches.")

if __name__ == '__main__':
    fix_uom_g_to_gms(env)
