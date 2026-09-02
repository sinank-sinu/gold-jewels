import sys

def run_fix():
    env = self.env
    
    # Find all pickings that meet the criteria
    pickings = env['stock.picking'].search([
        ('is_old_gold', '=', True),
        ('sale_old_id', '!=', False)
    ])
    
    to_delete = env['stock.picking']
    
    # Filter by product having 'old gold' in its name or the is_old_gold flag
    for p in pickings:
        is_match = False
        for m in p.move_ids:
            if m.product_id and ('old gold' in m.product_id.name.lower() or getattr(m.product_id, 'is_old_gold', False)):
                is_match = True
                break
        if is_match:
            to_delete |= p
            
    print(f"Found {len(to_delete)} Old Gold Transfers to clean up.")
    
    if not to_delete:
        print("Nothing to process.")
        return
        
    for index, picking in enumerate(to_delete, 1):
        print(f"[{index}/{len(to_delete)}] Reverting picking: {picking.name} (ID: {picking.id})")
        
        for move in picking.move_ids_without_package:
            if move.state == 'done':
                # Revert quants
                for sml in move.move_line_ids:
                    if sml.quantity > 0:
                        # Add back to source location
                        env['stock.quant']._update_available_quantity(move.product_id, sml.location_id, sml.quantity)
                        # Remove from destination location
                        env['stock.quant']._update_available_quantity(move.product_id, sml.location_dest_id, -sml.quantity)
                
                # Delete valuation layers if they exist
                if hasattr(move, 'stock_valuation_layer_ids'):
                    move.stock_valuation_layer_ids.sudo().unlink()
        
        # Change state to draft to bypass constraints during deletion
        picking.move_line_ids.write({'state': 'draft'})
        picking.move_ids.write({'state': 'draft'})
        picking.write({'state': 'draft'})
        
        # Delete related records
        picking.move_line_ids.unlink()
        picking.move_ids.unlink()
        picking.unlink()
        
    # Commit the transaction
    env.cr.commit()
    print("Cleanup complete and committed to database.")

try:
    run_fix()
except Exception as e:
    print(f"Error occurred: {e}")
    self.env.cr.rollback()
