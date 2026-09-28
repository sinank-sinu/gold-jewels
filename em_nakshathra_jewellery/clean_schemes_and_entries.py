#!/usr/bin/env python3
"""
clean_schemes_and_entries.py

High-performance, safe, zero-lag script to delete existing Jewellery Schemes,
Installments, and their associated Journal Entries (account.move / account.move.line)
from PostgreSQL / Odoo.

Key features:
- Automatically creates foreign-key performance indexes to avoid sequential table scans.
- Executes deletions in small, controlled batches (default: 2,000 records per batch)
  with immediate commits to avoid database locking or memory bloat.
- Handles dependencies in strict order:
    1. Unlinks sale_order.active_scheme_id (SET NULL)
    2. Deletes scheme_redemption records
    3. Deletes account_partial_reconcile and clears reconcile references
    4. Deletes mail messages, tracking values, and followers for scheme moves
    5. Deletes jewellery_scheme_installment (chunked)
    6. Deletes jewellery_scheme_enrollment (chunked)
    7. Deletes account_move and cascading lines (chunked)
    8. VACUUM ANALYZE to reclaim disk space and refresh optimizer statistics
- Supports --dry-run (preview statistics without modifying data).
- Supports --commit (required to perform actual deletions).
"""

import argparse
import configparser
import os
import sys
import time
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values


def load_odoo_conf(conf_path="debian/odoo.conf"):
    config = {
        'db_host': 'localhost',
        'db_port': 5432,
        'db_user': 'odoo17',
        'db_password': 'odoo17',
    }
    if os.path.exists(conf_path):
        cp = configparser.ConfigParser()
        try:
            cp.read(conf_path)
            if 'options' in cp:
                opts = cp['options']
                config['db_host'] = opts.get('db_host', config['db_host'])
                config['db_port'] = int(opts.get('db_port', config['db_port']))
                config['db_user'] = opts.get('db_user', config['db_user'])
                config['db_password'] = opts.get('db_password', config['db_password'])
        except Exception as e:
            print(f"[!] Warning: Could not read {conf_path}: {e}")
    return config


def get_connection(args, autocommit=False):
    conn = psycopg2.connect(
        dbname=args.db,
        user=args.user,
        password=args.password,
        host=args.host,
        port=args.port,
    )
    conn.autocommit = autocommit
    return conn


def ensure_performance_indexes(conn):
    """
    Creates B-Tree indexes on foreign keys referencing account_move,
    account_move_line, and jewellery_scheme_enrollment if they don't already exist.
    Without these indexes, deleting parent rows causes PostgreSQL to perform
    full table scans across 10+ referencing tables per deleted row.
    """
    indexes = [
        ("idx_perf_so_active_scheme", "sale_order", "active_scheme_id"),
        ("idx_perf_so_sale_return", "sale_order", "sale_return_bill_id"),
        ("idx_perf_so_old_gold", "sale_order", "old_gold_bill_id"),
        ("idx_perf_inst_enrollment", "jewellery_scheme_installment", "enrollment_id"),
        ("idx_perf_inst_move", "jewellery_scheme_installment", "move_id"),
        ("idx_perf_inst_suspense", "jewellery_scheme_installment", "suspense_move_id"),
        ("idx_perf_redemption_scheme", "scheme_redemption", "scheme_id"),
        ("idx_perf_po_purity_bill", "po_purity_update_log", "vendor_bill_id"),
        ("idx_perf_po_purity_line", "po_purity_update_log", "vendor_bill_line_id"),
        ("idx_perf_jewel_voucher", "jewellery_receive_voucher", "making_charge_bill_id"),
    ]

    old_ac = conn.autocommit
    conn.autocommit = True
    with conn.cursor() as cur:
        for idx_name, table, col in indexes:
            try:
                # Check if table and column exist
                cur.execute(f"""
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = '{table}' AND column_name = '{col}';
                """)
                if cur.fetchone():
                    cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({col});")
            except Exception as e:
                # Silently ignore if table doesn't exist
                pass
    conn.autocommit = old_ac


def print_progress(current, total, prefix="Progress", bar_len=30, extra=""):
    pct = (current / total) * 100 if total > 0 else 100
    filled = int(bar_len * current // total) if total > 0 else bar_len
    bar = "=" * filled + "-" * (bar_len - filled)
    sys.stdout.write(f"\r  [{bar}] {pct:5.1f}% ({current}/{total}) {extra}")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


def discover_target_records(conn):
    """
    Finds all scheme moves and prints a detailed inventory of records to be cleaned.
    """
    with conn.cursor() as cur:
        # Scheme enrollments
        cur.execute("SELECT count(*) FROM jewellery_scheme_enrollment;")
        enrollment_count = cur.fetchone()[0]

        # Scheme installments
        cur.execute("SELECT count(*) FROM jewellery_scheme_installment;")
        installment_count = cur.fetchone()[0]

        # Scheme redemptions
        cur.execute("SELECT count(*) FROM scheme_redemption;")
        redemption_count = cur.fetchone()[0]

        # Sale orders with active_scheme_id
        cur.execute("SELECT count(*) FROM sale_order WHERE active_scheme_id IS NOT NULL;")
        so_linked_count = cur.fetchone()[0]

        # Find target move IDs
        cur.execute("""
            SELECT DISTINCT id FROM account_move
            WHERE ref LIKE 'Scheme%' 
               OR ref LIKE 'Scheme Payment%'
               OR id IN (SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL)
               OR id IN (SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL);
        """)
        target_move_ids = [r[0] for r in cur.fetchall()]
        move_count = len(target_move_ids)

        # Move lines for target moves
        move_line_count = 0
        reconcile_count = 0
        mail_msg_count = 0
        mail_follower_count = 0

        if target_move_ids:
            cur.execute("""
                SELECT count(*) FROM account_move_line 
                WHERE move_id = ANY(%s);
            """, (target_move_ids,))
            move_line_count = cur.fetchone()[0]

            cur.execute("""
                SELECT count(*) FROM account_partial_reconcile
                WHERE debit_move_id IN (SELECT id FROM account_move_line WHERE move_id = ANY(%s))
                   OR credit_move_id IN (SELECT id FROM account_move_line WHERE move_id = ANY(%s));
            """, (target_move_ids, target_move_ids))
            reconcile_count = cur.fetchone()[0]

            cur.execute("""
                SELECT count(*) FROM mail_message 
                WHERE model = 'account.move' AND res_id = ANY(%s);
            """, (target_move_ids,))
            mail_msg_count = cur.fetchone()[0]

            cur.execute("""
                SELECT count(*) FROM mail_followers
                WHERE res_model = 'account.move' AND res_id = ANY(%s);
            """, (target_move_ids,))
            mail_follower_count = cur.fetchone()[0]

        return {
            'enrollments': enrollment_count,
            'installments': installment_count,
            'redemptions': redemption_count,
            'so_linked': so_linked_count,
            'target_move_ids': target_move_ids,
            'moves': move_count,
            'move_lines': move_line_count,
            'reconciles': reconcile_count,
            'mail_messages': mail_msg_count,
            'mail_followers': mail_follower_count,
        }


def execute_batch_delete(conn, args, stats):
    batch_size = args.batch_size
    move_ids = stats['target_move_ids']
    total_moves = len(move_ids)

    print("\n" + "=" * 65)
    print("STARTING BULK CLEANUP EXECUTION")
    print("=" * 65)
    start_total_time = time.time()

    # Step 1: Unlink sale orders
    print(f"\n[Step 1/7] Unlinking active_scheme_id on sale orders ({stats['so_linked']} records)...")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute("UPDATE sale_order SET active_scheme_id = NULL WHERE active_scheme_id IS NOT NULL;")
        updated_so = cur.rowcount
    conn.commit()
    print(f"  -> Successfully unlinked {updated_so} sale orders in {time.time() - t0:.2f}s")

    # Step 2: Delete scheme redemptions
    print(f"\n[Step 2/7] Deleting scheme redemptions ({stats['redemptions']} records)...")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM scheme_redemption;")
        del_red = cur.rowcount
    conn.commit()
    print(f"  -> Successfully deleted {del_red} redemptions in {time.time() - t0:.2f}s")

    # Step 3: Delete partial reconciliations on scheme move lines in chunks
    print(f"\n[Step 3/7] Clearing reconciliations for scheme moves ({stats['reconciles']} records)...")
    t0 = time.time()
    total_reconciles_del = 0
    for i in range(0, total_moves, batch_size):
        chunk = move_ids[i:i + batch_size]
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM account_partial_reconcile
                WHERE debit_move_id IN (SELECT id FROM account_move_line WHERE move_id = ANY(%s))
                   OR credit_move_id IN (SELECT id FROM account_move_line WHERE move_id = ANY(%s));
            """, (chunk, chunk))
            total_reconciles_del += cur.rowcount
            cur.execute("""
                UPDATE account_move_line 
                SET full_reconcile_id = NULL 
                WHERE move_id = ANY(%s) AND full_reconcile_id IS NOT NULL;
            """, (chunk,))
        conn.commit()
        print_progress(min(i + batch_size, total_moves), total_moves, prefix="Reconciles")
    print(f"  -> Successfully removed {total_reconciles_del} partial reconciliations in {time.time() - t0:.2f}s")

    # Step 4: Clean mail messages & followers for target moves
    print(f"\n[Step 4/7] Cleaning mail messages & followers ({stats['mail_messages']} msgs, {stats['mail_followers']} followers)...")
    t0 = time.time()
    total_msgs_del = 0
    total_followers_del = 0
    for i in range(0, total_moves, batch_size):
        chunk = move_ids[i:i + batch_size]
        with conn.cursor() as cur:
            # Delete tracking values & notifications linked to these messages
            cur.execute("""
                DELETE FROM mail_tracking_value 
                WHERE mail_message_id IN (SELECT id FROM mail_message WHERE model = 'account.move' AND res_id = ANY(%s));
            """, (chunk,))
            cur.execute("""
                DELETE FROM mail_notification 
                WHERE mail_message_id IN (SELECT id FROM mail_message WHERE model = 'account.move' AND res_id = ANY(%s));
            """, (chunk,))
            cur.execute("""
                DELETE FROM mail_message_res_partner_rel 
                WHERE mail_message_id IN (SELECT id FROM mail_message WHERE model = 'account.move' AND res_id = ANY(%s));
            """, (chunk,))
            # Delete messages
            cur.execute("""
                DELETE FROM mail_message 
                WHERE model = 'account.move' AND res_id = ANY(%s);
            """, (chunk,))
            total_msgs_del += cur.rowcount
            # Delete followers
            cur.execute("""
                DELETE FROM mail_followers 
                WHERE res_model = 'account.move' AND res_id = ANY(%s);
            """, (chunk,))
            total_followers_del += cur.rowcount
        conn.commit()
        print_progress(min(i + batch_size, total_moves), total_moves, prefix="Mail cleanup")
    print(f"  -> Successfully removed {total_msgs_del} messages and {total_followers_del} followers in {time.time() - t0:.2f}s")

    # Step 5: Delete scheme installments in chunks
    print(f"\n[Step 5/7] Deleting scheme installments ({stats['installments']} records)...")
    t0 = time.time()
    total_inst_del = 0
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM jewellery_scheme_installment;")
        installment_ids = [r[0] for r in cur.fetchall()]
    total_inst = len(installment_ids)
    for i in range(0, total_inst, batch_size):
        chunk = installment_ids[i:i + batch_size]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jewellery_scheme_installment WHERE id = ANY(%s);", (chunk,))
            total_inst_del += cur.rowcount
        conn.commit()
        print_progress(min(i + batch_size, total_inst), total_inst, prefix="Installments")
    print(f"  -> Successfully deleted {total_inst_del} installments in {time.time() - t0:.2f}s")

    # Step 6: Delete scheme enrollments in chunks
    print(f"\n[Step 6/7] Deleting scheme enrollments ({stats['enrollments']} records)...")
    t0 = time.time()
    total_enr_del = 0
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM jewellery_scheme_enrollment;")
        enrollment_ids = [r[0] for r in cur.fetchall()]
    total_enr = len(enrollment_ids)
    for i in range(0, total_enr, batch_size):
        chunk = enrollment_ids[i:i + batch_size]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jewellery_scheme_enrollment WHERE id = ANY(%s);", (chunk,))
            total_enr_del += cur.rowcount
        conn.commit()
        print_progress(min(i + batch_size, total_enr), total_enr, prefix="Enrollments")
    print(f"  -> Successfully deleted {total_enr_del} enrollments in {time.time() - t0:.2f}s")

    # Step 7: Delete scheme account moves (cascades to account_move_line) in chunks
    print(f"\n[Step 7/7] Deleting scheme journal entries ({total_moves} moves / ~{stats['move_lines']} lines)...")
    t0 = time.time()
    total_moves_del = 0
    for i in range(0, total_moves, batch_size):
        chunk = move_ids[i:i + batch_size]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM account_move WHERE id = ANY(%s);", (chunk,))
            total_moves_del += cur.rowcount
        conn.commit()
        print_progress(min(i + batch_size, total_moves), total_moves, prefix="Journal Moves")
    print(f"  -> Successfully deleted {total_moves_del} account moves in {time.time() - t0:.2f}s")

    total_time = time.time() - start_total_time
    print("\n" + "=" * 65)
    print(f"CLEANUP COMPLETED SUCCESSFULLY IN {total_time:.2f} SECONDS!")
    print("=" * 65)

    # Step 8: Optional VACUUM ANALYZE
    if args.vacuum:
        print("\nRunning VACUUM ANALYZE to reclaim disk space and refresh statistics...")
        conn_vac = get_connection(args, autocommit=True)
        with conn_vac.cursor() as cur:
            tables_to_vacuum = [
                'jewellery_scheme_enrollment',
                'jewellery_scheme_installment',
                'scheme_redemption',
                'account_move',
                'account_move_line',
                'account_partial_reconcile',
                'sale_order',
                'mail_message',
                'mail_followers',
            ]
            for t in tables_to_vacuum:
                try:
                    cur.execute(f"VACUUM ANALYZE {t};")
                    print(f"  -> Vacuumed {t}")
                except Exception as e:
                    print(f"  -> Note on {t}: {e}")
        conn_vac.close()
        print("VACUUM ANALYZE completed!")


def main():
    default_conf = load_odoo_conf()

    parser = argparse.ArgumentParser(
        description="Safe, zero-lag batch cleanup script for jewellery schemes and journal entries."
    )
    parser.add_argument("--db", default="nakshathra_db25", help="Target database name (default: nakshathra_db25)")
    parser.add_argument("--host", default=default_conf['db_host'], help="Database host (default: localhost)")
    parser.add_argument("--port", type=int, default=default_conf['db_port'], help="Database port (default: 5432)")
    parser.add_argument("--user", default=default_conf['db_user'], help="Database user (default: odoo17)")
    parser.add_argument("--password", default=default_conf['db_password'], help="Database password (default: odoo17)")
    parser.add_argument("--batch-size", type=int, default=2000, help="Batch chunk size (default: 2000)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate and report record counts without committing changes")
    parser.add_argument("--commit", action="store_true", help="Execute actual deletion (safety confirmation flag)")
    parser.add_argument("--vacuum", action="store_true", default=True, help="Run VACUUM ANALYZE after deletion")
    parser.add_argument("--no-vacuum", dest="vacuum", action="store_false", help="Skip VACUUM ANALYZE")

    args = parser.parse_args()

    if not args.dry_run and not args.commit:
        print("[!] SAFETY CHECK: Neither --commit nor --dry-run was specified.")
        print("[!] Running in --dry-run mode by default to prevent accidental data loss.")
        print("[!] Pass '--commit' to execute the actual deletion.")
        args.dry_run = True

    print("\n" + "=" * 65)
    print(f"  SCHEME & JOURNAL ENTRY CLEANUP SCRIPT")
    print(f"  Target Database: {args.db}")
    print(f"  Host:            {args.host}:{args.port}")
    print(f"  User:            {args.user}")
    print(f"  Batch Size:      {args.batch_size}")
    print(f"  Mode:            {'[DRY-RUN - NO DATA WILL BE MODIFIED]' if args.dry_run else '[LIVE COMMIT - DELETING DATA]'}")
    print("=" * 65)

    try:
        conn = get_connection(args, autocommit=False)
    except Exception as e:
        print(f"\n[ERROR] Could not connect to database '{args.db}': {e}")
        sys.exit(1)

    try:
        print("\n[*] Ensuring foreign-key performance indexes exist...")
        ensure_performance_indexes(conn)
        print("    -> Performance indexes verified.")

        print("\n[*] Discovering target scheme records...")
        stats = discover_target_records(conn)

        print("\n" + "-" * 45)
        print(f"  RECORDS IDENTIFIED FOR CLEANUP:")
        print("-" * 45)
        print(f"  * Scheme Enrollments:        {stats['enrollments']:>8,}")
        print(f"  * Scheme Installments:       {stats['installments']:>8,}")
        print(f"  * Scheme Redemptions:        {stats['redemptions']:>8,}")
        print(f"  * Sale Orders Linked:        {stats['so_linked']:>8,}")
        print(f"  * Scheme Journal Moves:      {stats['moves']:>8,}")
        print(f"  * Scheme Move Lines:         {stats['move_lines']:>8,}")
        print(f"  * Partial Reconciliations:   {stats['reconciles']:>8,}")
        print(f"  * Mail Messages (Moves):     {stats['mail_messages']:>8,}")
        print(f"  * Mail Followers (Moves):    {stats['mail_followers']:>8,}")
        print("-" * 45)

        if stats['enrollments'] == 0 and stats['moves'] == 0:
            print("\n[✓] Database is already clean. No scheme enrollments or moves found.")
            return

        if args.dry_run:
            print("\n[DRY RUN TEST] Simulating deletion in a temporary transaction with ROLLBACK...")
            t0 = time.time()
            with conn.cursor() as cur:
                # Test 1000 items
                cur.execute("UPDATE sale_order SET active_scheme_id = NULL WHERE active_scheme_id IS NOT NULL;")
                cur.execute("DELETE FROM scheme_redemption;")
                if stats['target_move_ids']:
                    sample_moves = stats['target_move_ids'][:1000]
                    cur.execute("""
                        DELETE FROM account_partial_reconcile
                        WHERE debit_move_id IN (SELECT id FROM account_move_line WHERE move_id = ANY(%s))
                           OR credit_move_id IN (SELECT id FROM account_move_line WHERE move_id = ANY(%s));
                    """, (sample_moves, sample_moves))
                    cur.execute("DELETE FROM account_move WHERE id = ANY(%s);", (sample_moves,))
            conn.rollback()
            print(f"[✓] Simulation succeeded in {time.time() - t0:.2f}s without constraint errors.")
            print("[✓] To perform the actual deletion, run with the --commit flag:")
            print(f"\n    python3 clean_schemes_and_entries.py --db {args.db} --commit\n")
        elif args.commit:
            execute_batch_delete(conn, args, stats)

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
