import logging
import sys

_logger = logging.getLogger("migration")
_logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
_logger.addHandler(handler)

def migrate_attribute(env, old_name, new_name):
    cr = env.cr
    changed_variant_ids = set()
    
    _logger.info(f"Looking for '{old_name}' in db...")
    cr.execute("SELECT id FROM product_attribute_value WHERE name::text ILIKE %s", (f'%{old_name}%',))
    old_ids = [r[0] for r in cr.fetchall()]
    
    if not old_ids:
        _logger.info(f"Old attribute '{old_name}' not found. Nothing to do.")
        return
        
    cr.execute("SELECT id FROM product_attribute_value WHERE name::text ILIKE %s AND id NOT IN %s", (f'%{new_name}%', tuple(old_ids)))
    new_ids = [r[0] for r in cr.fetchall()]
    
    if not new_ids:
        _logger.info(f"New attribute '{new_name}' not found. Renaming old attribute(s)...")
        for old_id in old_ids:
            # Find all variants using this old attribute before we rename it
            cr.execute("""
                SELECT pvc.product_product_id 
                FROM product_variant_combination pvc
                JOIN product_template_attribute_value ptav ON ptav.id = pvc.product_template_attribute_value_id
                WHERE ptav.product_attribute_value_id = %s
            """, (old_id,))
            changed_variant_ids.update([r[0] for r in cr.fetchall()])
            
            cr.execute("UPDATE product_attribute_value SET name = %s WHERE id = %s", ('{"en_US": "' + new_name + '"}', old_id))
        _logger.info("Done renaming.")
        _logger.info(f"Affected Variant IDs: {list(changed_variant_ids)}")
        return
        
    # We take the first new_id as target
    new_id = new_ids[0]
    _logger.info(f"Migrating from OLD IDs {old_ids} to NEW ID {new_id}...")
    
    for old_id in old_ids:
        if old_id == new_id:
            continue
            
        # 1. Update product_attribute_value_product_template_attribute_line_rel
        cr.execute("SELECT product_template_attribute_line_id FROM product_attribute_value_product_template_attribute_line_rel WHERE product_attribute_value_id = %s", (old_id,))
        ptal_ids = [r[0] for r in cr.fetchall()]
        
        for ptal_id in ptal_ids:
            # Check if NEW ID is already in this PTAL
            cr.execute("SELECT 1 FROM product_attribute_value_product_template_attribute_line_rel WHERE product_attribute_value_id = %s AND product_template_attribute_line_id = %s", (new_id, ptal_id))
            if cr.fetchone():
                # Already there, just delete the OLD ID link
                cr.execute("DELETE FROM product_attribute_value_product_template_attribute_line_rel WHERE product_attribute_value_id = %s AND product_template_attribute_line_id = %s", (old_id, ptal_id))
            else:
                # Not there, update OLD to NEW
                cr.execute("UPDATE product_attribute_value_product_template_attribute_line_rel SET product_attribute_value_id = %s WHERE product_attribute_value_id = %s AND product_template_attribute_line_id = %s", (new_id, old_id, ptal_id))
                
        # 2. Merge PTAVs
        cr.execute("SELECT id, attribute_line_id FROM product_template_attribute_value WHERE product_attribute_value_id = %s", (old_id,))
        old_ptavs = cr.fetchall()
        
        # Get all tables that reference product_template_attribute_value(id)
        cr.execute("""
            SELECT tc.table_name, kcu.column_name 
            FROM information_schema.table_constraints AS tc 
            JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name 
            JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name 
            WHERE constraint_type = 'FOREIGN KEY' AND ccu.table_name = 'product_template_attribute_value' AND ccu.column_name = 'id';
        """)
        fkey_tables = cr.fetchall()
        
        for old_ptav_id, ptal_id in old_ptavs:
            # Collect affected variants for this PTAV
            cr.execute("SELECT product_product_id FROM product_variant_combination WHERE product_template_attribute_value_id = %s", (old_ptav_id,))
            changed_variant_ids.update([r[0] for r in cr.fetchall()])
            
            # Check if there is already a PTAV for the NEW ID on this PTAL
            cr.execute("SELECT id FROM product_template_attribute_value WHERE product_attribute_value_id = %s AND attribute_line_id = %s", (new_id, ptal_id))
            target_ptav = cr.fetchone()
            
            if target_ptav:
                new_ptav_id = target_ptav[0]
                _logger.info(f"Merging PTAV {old_ptav_id} into {new_ptav_id} on PTAL {ptal_id}")
                # We need to update all foreign keys pointing to old_ptav_id to point to new_ptav_id
                for tbl, col in fkey_tables:
                    # some tables might have unique constraints that fail when we update.
                    # specifically product_variant_combination has unique (product_product_id, product_template_attribute_value_id)
                    if tbl == 'product_variant_combination':
                        cr.execute(f"SELECT product_product_id FROM {tbl} WHERE {col} = %s", (old_ptav_id,))
                        affected_variants = [r[0] for r in cr.fetchall()]
                        for v_id in affected_variants:
                            cr.execute(f"SELECT 1 FROM {tbl} WHERE product_product_id = %s AND {col} = %s", (v_id, new_ptav_id))
                            if cr.fetchone():
                                cr.execute(f"DELETE FROM {tbl} WHERE product_product_id = %s AND {col} = %s", (v_id, old_ptav_id))
                            else:
                                cr.execute(f"UPDATE {tbl} SET {col} = %s WHERE product_product_id = %s AND {col} = %s", (new_ptav_id, v_id, old_ptav_id))
                    else:
                        # try catch to handle unique violations on other rel tables
                        try:
                            with cr.savepoint():
                                cr.execute(f"UPDATE {tbl} SET {col} = %s WHERE {col} = %s", (new_ptav_id, old_ptav_id))
                        except Exception as e:
                            _logger.warning(f"Could not update {tbl}.{col} entirely. Fallback to row-by-row...")
                            cr.execute(f"SELECT ctid FROM {tbl} WHERE {col} = %s", (old_ptav_id,))
                            for r in cr.fetchall():
                                try:
                                    with cr.savepoint():
                                        cr.execute(f"UPDATE {tbl} SET {col} = %s WHERE ctid = %s", (new_ptav_id, r[0]))
                                except Exception:
                                    # likely duplicate, delete the old link
                                    with cr.savepoint():
                                        cr.execute(f"DELETE FROM {tbl} WHERE ctid = %s", (r[0],))
                # Delete old PTAV
                cr.execute("DELETE FROM product_template_attribute_value WHERE id = %s", (old_ptav_id,))
            else:
                _logger.info(f"Simply updating PTAV {old_ptav_id} to point to NEW attribute {new_id}")
                cr.execute("UPDATE product_template_attribute_value SET product_attribute_value_id = %s WHERE id = %s", (new_id, old_ptav_id))

        # 3. Archive or delete OLD attribute value
        try:
            with cr.savepoint():
                cr.execute("DELETE FROM product_attribute_value WHERE id = %s", (old_id,))
                _logger.info(f"Deleted old attribute value {old_id}")
        except Exception:
            _logger.info(f"Could not delete {old_id} due to constraints. Leaving it alone.")
            
    cr.commit()
    _logger.info("Migration finished successfully.")
    
    # Format and print the changed variants
    variant_list = sorted(list(changed_variant_ids))
    _logger.info(f"Total Variants Affected: {len(variant_list)}")
    _logger.info(f"Affected Variant IDs: {variant_list}")

migrate_attribute(env, 'Chain - Pendant', 'Chain With Pendant')
