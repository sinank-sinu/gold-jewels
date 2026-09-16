#!/usr/bin/env python3
"""
Script: fix_salesman_cart_source_location.py
Purpose: Production-safe script to correct the source location (location_id)
         on stock.picking records created by Salesman Cart transfers,
         fetching the accurate source location directly from stock.move.line.

Safety features:
  - NO default database: database name MUST be explicitly provided.
  - Strict targeting: ONLY touches Salesman Cart transfers and their returns.
  - Ambiguity protection: skips pickings if move lines have conflicting locations.
  - Dry-run mode: test and preview without modifying the database.
  - Interactive confirmation prompt before committing changes.
  - Full transaction rollback on any failure.
"""

import sys
import os
import argparse

try:
    import psycopg2
except ImportError:
    # If invoked with a python environment missing psycopg2, auto-reexec with project venv
    venv_py = os.path.expanduser('~/odoo17/venv/bin/python')
    if os.path.exists(venv_py) and sys.executable != venv_py:
        os.execv(venv_py, [venv_py] + sys.argv)
    else:
        print("Error: psycopg2 is not installed. Please install it or activate the odoo venv.")
        sys.exit(1)

DEFAULT_HOST = 'localhost'
DEFAULT_PORT = 5432
DEFAULT_USER = 'odoo17'
DEFAULT_PASS = 'odoo17'


def get_available_databases(host=DEFAULT_HOST, port=DEFAULT_PORT, user=DEFAULT_USER, password=DEFAULT_PASS):
    """Retrieve list of available databases from PostgreSQL."""
    try:
        conn = psycopg2.connect(
            dbname='postgres',
            host=host,
            port=port,
            user=user,
            password=password
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT datname FROM pg_database 
            WHERE datistemplate = false 
              AND datname NOT IN ('postgres')
            ORDER BY datname ASC;
        """)
        dbs = [r[0] for r in cur.fetchall()]
        conn.close()
        return dbs
    except Exception:
        return []


def get_connection(dbname, host=DEFAULT_HOST, port=DEFAULT_PORT, user=DEFAULT_USER, password=DEFAULT_PASS):
    return psycopg2.connect(
        dbname=dbname,
        host=host,
        port=port,
        user=user,
        password=password
    )


def fix_salesman_cart_locations(dbname, dry_run=False, auto_confirm=False):
    print("=" * 75)
    print(f" Connecting to database: '{dbname}'...")
    try:
        conn = get_connection(dbname=dbname)
        cur = conn.cursor()
    except Exception as e:
        print(f" ERROR: Failed to connect to database '{dbname}': {e}")
        sys.exit(1)

    print(" Connected successfully.")
    print("=" * 75)

    # Production-safe filter:
    # Strictly targets ONLY Salesman Cart transfers and returns of Salesman Cart transfers
    salesman_cart_filter = """
        (
            sp.origin LIKE 'Salesman Cart %'
            OR sp.id IN (SELECT picking_id FROM salesman_cart_line WHERE picking_id IS NOT NULL)
            OR sp.id IN (
                SELECT ret.id
                FROM stock_picking ret
                JOIN stock_picking orig ON ret.origin = 'Return of ' || orig.name
                WHERE orig.origin LIKE 'Salesman Cart %'
                   OR orig.id IN (SELECT picking_id FROM salesman_cart_line WHERE picking_id IS NOT NULL)
            )
        )
    """

    # 1. Safety check: Check if any salesman cart pickings have MULTIPLE conflicting move line source locations
    cur.execute(f"""
        SELECT sp.id, sp.name, sp.origin, COUNT(DISTINCT sml.location_id) AS loc_count
        FROM stock_picking sp
        JOIN stock_move_line sml ON sml.picking_id = sp.id
        WHERE {salesman_cart_filter}
        GROUP BY sp.id, sp.name, sp.origin
        HAVING COUNT(DISTINCT sml.location_id) > 1;
    """)
    conflicting = cur.fetchall()
    if conflicting:
        print(f" WARNING: Found {len(conflicting)} pickings with multiple distinct move line source locations.")
        print(" For safety, these pickings will be SKIPPED from automated correction:")
        for cid, cname, corigin, cloc_count in conflicting:
            print(f"   • Picking {cname} (ID {cid}, Origin: {corigin}): {cloc_count} distinct source locations.")
        print("-" * 75)
        conflicting_ids = tuple(c[0] for c in conflicting)
        skip_conflict_clause = f"AND sp.id NOT IN {conflicting_ids if len(conflicting_ids) > 1 else f'({conflicting_ids[0]})'}"
    else:
        skip_conflict_clause = ""

    # 2. Find all Salesman Cart pickings where stock_picking.location_id != stock_move_line.location_id
    query_mismatches = f"""
        WITH target_pickings AS (
            SELECT 
                sp.id AS picking_id,
                sp.name AS picking_name,
                sp.origin AS origin,
                sp.state AS state,
                sp.location_id AS old_loc_id,
                old_loc.complete_name AS old_loc_name,
                sml.location_id AS new_loc_id,
                new_loc.complete_name AS new_loc_name,
                ROW_NUMBER() OVER(PARTITION BY sp.id ORDER BY sml.id ASC) AS rn
            FROM stock_picking sp
            JOIN stock_move_line sml ON sml.picking_id = sp.id
            LEFT JOIN stock_location old_loc ON sp.location_id = old_loc.id
            LEFT JOIN stock_location new_loc ON sml.location_id = new_loc.id
            WHERE {salesman_cart_filter}
              {skip_conflict_clause}
              AND sp.location_id != sml.location_id
        )
        SELECT picking_id, picking_name, origin, state, old_loc_id, old_loc_name, new_loc_id, new_loc_name
        FROM target_pickings
        WHERE rn = 1
        ORDER BY picking_id DESC;
    """

    cur.execute(query_mismatches)
    mismatched_pickings = cur.fetchall()
    total_pickings = len(mismatched_pickings)

    # 3. Check if any stock_move records within salesman cart pickings have mismatched locations
    query_moves = f"""
        SELECT COUNT(DISTINCT sm.id)
        FROM stock_move sm
        JOIN stock_move_line sml ON sml.move_id = sm.id
        JOIN stock_picking sp ON sm.picking_id = sp.id
        WHERE {salesman_cart_filter}
          {skip_conflict_clause}
          AND sm.location_id != sml.location_id;
    """
    cur.execute(query_moves)
    mismatched_moves_count = cur.fetchone()[0]

    print(f" Target: Salesman Cart transfers & returns only")
    print(f" Found {total_pickings} stock pickings where source location != move line source location.")
    print(f" Found {mismatched_moves_count} stock moves where move location != move line source location.")
    print("-" * 75)

    if total_pickings == 0 and mismatched_moves_count == 0:
        print(" [OK] All Salesman Cart stock pickings and moves are already in sync!")
        conn.close()
        return

    # Display sample of records to be updated
    sample_count = min(15, total_pickings)
    if sample_count > 0:
        print(f" Sample of pickings to be updated (showing {sample_count} of {total_pickings}):")
        for r in mismatched_pickings[:sample_count]:
            pid, pname, origin, state, old_id, old_name, new_id, new_name = r
            print(f"   • {pname:<16} | Origin: {str(origin):<26} | {old_name}  ==>  {new_name}")

        if total_pickings > sample_count:
            print(f"   ... and {total_pickings - sample_count} more pickings.")
        print("-" * 75)

    # Dry-run check
    if dry_run:
        print(" [DRY-RUN MODE] No changes were written to the database.")
        print(" To apply these corrections, re-run without --dry-run:")
        print(f"   python3 fix_salesman_cart_source_location.py --db {dbname}")
        print("=" * 75)
        conn.close()
        return

    # Production confirmation prompt
    if not auto_confirm:
        print(f" CAUTION: You are about to update {total_pickings} picking records in database '{dbname}'.")
        try:
            confirm = input(f" Are you sure you want to proceed? Type 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                print(" Aborted by user. No changes were made.")
                conn.close()
                return
        except (KeyboardInterrupt, EOFError):
            print("\n Aborted by user. No changes were made.")
            conn.close()
            return

    # 4. Apply updates atomically inside transaction
    print(" Applying updates...")
    try:
        # Update stock.picking location_id from move line location_id
        update_pickings_sql = f"""
            WITH target_locs AS (
                SELECT 
                    sp.id AS picking_id,
                    sml.location_id AS correct_loc_id,
                    ROW_NUMBER() OVER(PARTITION BY sp.id ORDER BY sml.id ASC) AS rn
                FROM stock_picking sp
                JOIN stock_move_line sml ON sml.picking_id = sp.id
                WHERE {salesman_cart_filter}
                  {skip_conflict_clause}
                  AND sp.location_id != sml.location_id
            )
            UPDATE stock_picking sp
            SET location_id = tl.correct_loc_id
            FROM target_locs tl
            WHERE sp.id = tl.picking_id AND tl.rn = 1;
        """
        cur.execute(update_pickings_sql)
        updated_pickings_count = cur.rowcount

        # Update stock.move location_id if any were mismatched
        updated_moves_count = 0
        if mismatched_moves_count > 0:
            update_moves_sql = f"""
                UPDATE stock_move sm
                SET location_id = sml.location_id
                FROM stock_move_line sml
                JOIN stock_picking sp ON sml.picking_id = sp.id
                WHERE sml.move_id = sm.id
                  AND {salesman_cart_filter}
                  {skip_conflict_clause}
                  AND sm.location_id != sml.location_id;
            """
            cur.execute(update_moves_sql)
            updated_moves_count = cur.rowcount

        # Commit transaction
        conn.commit()
        print(f" -> Successfully updated {updated_pickings_count} stock.picking records.")
        if updated_moves_count > 0:
            print(f" -> Successfully updated {updated_moves_count} stock.move records.")
        print(" Transaction committed successfully!")
        print("=" * 75)

    except Exception as e:
        conn.rollback()
        print(f" ERROR: Failed to apply updates: {e}")
        print(" Transaction rolled back completely. No changes were saved.")
        conn.close()
        sys.exit(1)

    # 5. Verification check
    cur.execute(query_mismatches)
    remaining = len(cur.fetchall())
    print(f" Verification check: Remaining mismatched Salesman Cart pickings = {remaining}")
    if remaining == 0:
        print(" [SUCCESS] All Salesman Cart stock pickings now match their move line source locations!")
    else:
        print(f" [WARNING] {remaining} pickings still have mismatches.")
    print("=" * 75)

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Production-safe script to correct source location on Salesman Cart stock.picking records."
    )
    parser.add_argument(
        '-d', '--db',
        dest='db',
        default=None,
        help="Database name (REQUIRED. No default database is selected for production safety)"
    )
    parser.add_argument(
        'db_pos',
        nargs='?',
        default=None,
        help="Database name (positional alternative to --db)"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Preview changes without writing to database"
    )
    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help="Skip interactive confirmation prompt"
    )
    parser.add_argument(
        '--list-dbs',
        action='store_true',
        help="List available databases on PostgreSQL server and exit"
    )
    args = parser.parse_args()

    # Handle --list-dbs
    if args.list_dbs:
        dbs = get_available_databases()
        print("Available databases in PostgreSQL:")
        for db_name in dbs:
            print(f"  • {db_name}")
        sys.exit(0)

    target_db = args.db or args.db_pos

    # Enforce explicit database specification (NO AUTOMATIC DEFAULT)
    if not target_db:
        dbs = get_available_databases()
        print("=" * 75)
        print(" ERROR: No database specified!")
        print(" For production safety, this script will NOT automatically pick a default database.")
        print(" You must explicitly provide the target database name.")
        print("=" * 75)
        print(" Usage:")
        print("   python3 fix_salesman_cart_source_location.py --db <dbname> [--dry-run] [-y]")
        print("   python3 fix_salesman_cart_source_location.py <dbname> [--dry-run] [-y]")
        if dbs:
            print("\n Available databases on this server:")
            for db_name in dbs:
                print(f"   • {db_name}")
        print("=" * 75)
        sys.exit(1)

    fix_salesman_cart_locations(
        dbname=target_db,
        dry_run=args.dry_run,
        auto_confirm=args.yes
    )


if __name__ == '__main__':
    main()
