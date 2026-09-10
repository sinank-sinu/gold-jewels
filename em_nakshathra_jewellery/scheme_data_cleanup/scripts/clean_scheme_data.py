#!/usr/bin/env python3
"""
Standalone Script: Revert and Clean Scheme Data
Usage 1 (via odoo-bin shell):
    ./venv/bin/python3 ./odoo-bin shell -c odoo_nakshathra.conf -d <dbname> --no-http < custom_addons/em_nakshathra-main/em_nakshathra_jewellery/scheme_data_cleanup/scripts/clean_scheme_data.py

Usage 2 (directly via python/psycopg2):
    ./venv/bin/python3 custom_addons/em_nakshathra-main/em_nakshathra_jewellery/scheme_data_cleanup/scripts/clean_scheme_data.py --dbname pro_7 --commit
"""

import sys
import argparse
import psycopg2


def get_preview_counts(cur):
    counts = {}

    def table_exists(tbl):
        cur.execute("SELECT to_regclass(%s);", [tbl])
        res = cur.fetchone()
        return bool(res and res[0])

    if table_exists('jewellery_scheme_enrollment'):
        cur.execute("SELECT count(*) FROM jewellery_scheme_enrollment;")
        counts['jewellery_scheme_enrollment'] = cur.fetchone()[0]

    if table_exists('jewellery_scheme_installment'):
        cur.execute("SELECT count(*) FROM jewellery_scheme_installment;")
        counts['jewellery_scheme_installment'] = cur.fetchone()[0]

        cur.execute("""
            SELECT count(DISTINCT id) FROM account_move
            WHERE id IN (
                SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                UNION
                SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
            )
            OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%');
        """)
        counts['account_move (scheme)'] = cur.fetchone()[0]

        cur.execute("""
            SELECT count(*) FROM account_move_line
            WHERE move_id IN (
                SELECT id FROM account_move
                WHERE id IN (
                    SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
                    UNION
                    SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
                )
                OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%')
            );
        """)
        counts['account_move_line (scheme)'] = cur.fetchone()[0]

    if table_exists('scheme_redemption'):
        cur.execute("SELECT count(*) FROM scheme_redemption;")
        counts['scheme_redemption'] = cur.fetchone()[0]

    if table_exists('pinelabs_payment_wizard'):
        cur.execute("SELECT count(*) FROM pinelabs_payment_wizard WHERE scheme_installment_id IS NOT NULL;")
        counts['pinelabs_payment_wizard'] = cur.fetchone()[0]

    return counts


def execute_cleanup(cur, commit=False):
    print("=" * 60)
    print("STARTING SCHEME DATA CLEANUP & JOURNAL REVERSAL")
    print("=" * 60)

    def table_exists(tbl):
        cur.execute("SELECT to_regclass(%s);", [tbl])
        res = cur.fetchone()
        return bool(res and res[0])

    # 1. Identify scheme account moves
    cur.execute("""
        CREATE TEMP TABLE tmp_scheme_moves_to_delete AS
        SELECT DISTINCT id FROM account_move
        WHERE id IN (
            SELECT move_id FROM jewellery_scheme_installment WHERE move_id IS NOT NULL
            UNION
            SELECT suspense_move_id FROM jewellery_scheme_installment WHERE suspense_move_id IS NOT NULL
        )
        OR (ref ILIKE 'Scheme Payment:%' OR ref ILIKE 'Scheme Transfer%');
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tmp_scheme_moves ON tmp_scheme_moves_to_delete(id);")
    cur.execute("SELECT count(*) FROM tmp_scheme_moves_to_delete;")
    total_moves = cur.fetchone()[0]
    print(f"[Step 1] Found {total_moves:,} scheme journal entries to revert and delete.")

    # 2. Clear foreign keys on sale_order
    if table_exists('sale_order'):
        cur.execute("""
            SELECT count(*) FROM information_schema.columns 
            WHERE table_name = 'sale_order' AND column_name = 'active_scheme_id';
        """)
        if cur.fetchone()[0] > 0:
            cur.execute("UPDATE sale_order SET active_scheme_id = NULL WHERE active_scheme_id IS NOT NULL;")
            print(f"[Step 2] Cleared active_scheme_id on {cur.rowcount} sale order(s).")

    # 3. Delete pinelabs payment wizards linked to scheme installments
    if table_exists('pinelabs_payment_wizard'):
        cur.execute("DELETE FROM pinelabs_payment_wizard WHERE scheme_installment_id IS NOT NULL;")
        print(f"[Step 3] Deleted {cur.rowcount} pinelabs_payment_wizard record(s).")

    # 4. Delete scheme redemptions
    if table_exists('scheme_redemption'):
        cur.execute("DELETE FROM scheme_redemption;")
        print(f"[Step 4] Deleted {cur.rowcount} scheme_redemption record(s).")

    # 5. Check customer_scheme & customer_scheme_payment
    if table_exists('customer_scheme_payment'):
        cur.execute("DELETE FROM customer_scheme_payment;")
        print(f"[Step 5a] Deleted {cur.rowcount} customer_scheme_payment record(s).")
    if table_exists('customer_scheme'):
        cur.execute("DELETE FROM customer_scheme;")
        print(f"[Step 5b] Deleted {cur.rowcount} customer_scheme record(s).")

    if total_moves > 0:
        # 6. Unlink partial reconciliations
        if table_exists('account_partial_reconcile'):
            cur.execute("""
                DELETE FROM account_partial_reconcile
                WHERE debit_move_id IN (
                    SELECT id FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete)
                )
                OR credit_move_id IN (
                    SELECT id FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete)
                );
            """)
            print(f"[Step 6] Removed {cur.rowcount} partial reconciliation(s).")

        # 7. Unlink account_payment
        if table_exists('account_payment'):
            cur.execute("DELETE FROM account_payment WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
            print(f"[Step 7] Removed {cur.rowcount} account_payment record(s).")

        # 8. Unlink mail followers and messages on scheme moves
        if table_exists('mail_followers'):
            cur.execute("""
                DELETE FROM mail_followers
                WHERE res_model = 'account.move'
                  AND res_id IN (SELECT id FROM tmp_scheme_moves_to_delete);
            """)
            print(f"[Step 8a] Removed {cur.rowcount} mail.followers on scheme moves.")

        if table_exists('mail_message'):
            cur.execute("""
                DELETE FROM mail_message
                WHERE model = 'account.move'
                  AND res_id IN (SELECT id FROM tmp_scheme_moves_to_delete);
            """)
            print(f"[Step 8b] Removed {cur.rowcount} mail.message records on scheme moves.")

        # 9. Delete account move lines
        cur.execute("DELETE FROM account_move_line WHERE move_id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
        print(f"[Step 9] Deleted {cur.rowcount:,} account_move_line record(s).")

    # 10. Disconnect move references and delete installments FIRST
    # (Emptying this table first avoids slow Postgres FK sequential scans when deleting account_move)
    if table_exists('jewellery_scheme_installment'):
        cur.execute("UPDATE jewellery_scheme_installment SET move_id = NULL, suspense_move_id = NULL;")
        cur.execute("DELETE FROM jewellery_scheme_installment;")
        print(f"[Step 10] Deleted {cur.rowcount:,} scheme installment(s).")

    # 11. Delete enrollments
    if table_exists('jewellery_scheme_enrollment'):
        cur.execute("DELETE FROM jewellery_scheme_enrollment;")
        print(f"[Step 11] Deleted {cur.rowcount:,} scheme enrollment(s).")

    # 12. Delete account moves (now instantaneous because installments table is empty!)
    if total_moves > 0:
        cur.execute("DELETE FROM account_move WHERE id IN (SELECT id FROM tmp_scheme_moves_to_delete);")
        print(f"[Step 12] Deleted {cur.rowcount:,} account_move record(s).")

    print("\nVerifying remaining counts...")
    post_counts = get_preview_counts(cur)
    for k, v in post_counts.items():
        print(f"  {k}: {v}")

    if not commit:
        print("\n[DRY RUN] Transaction rolled back. No changes saved.")
    else:
        print("\n[COMMIT] Changes committed successfully.")


def main():
    if 'env' in globals():
        env_obj = globals()['env']
        cr = env_obj.cr
        print("Running inside Odoo Shell...")
        print("Initial counts:")
        for k, v in get_preview_counts(cr).items():
            print(f"  {k}: {v}")
        execute_cleanup(cr, commit=True)
        env_obj.invalidate_all()
        cr.commit()
        return

    parser = argparse.ArgumentParser(description="Revert and clean scheme data.")
    parser.add_argument("--dbname", required=True, help="Database name")
    parser.add_argument("--host", default="localhost", help="PostgreSQL host")
    parser.add_argument("--port", default=5432, type=int, help="PostgreSQL port")
    parser.add_argument("--user", default="akhil", help="PostgreSQL user")
    parser.add_argument("--password", default="1234", help="PostgreSQL password")
    parser.add_argument("--commit", action="store_true", help="Commit changes (otherwise dry-run)")

    args = parser.parse_args()

    conn = psycopg2.connect(
        dbname=args.dbname,
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
    )
    cur = conn.cursor()

    print(f"Connected to database: {args.dbname}")
    print("Initial counts:")
    for k, v in get_preview_counts(cur).items():
        print(f"  {k}: {v}")

    try:
        execute_cleanup(cur, commit=args.commit)
        if args.commit:
            conn.commit()
            print("Successfully committed transaction.")
        else:
            conn.rollback()
            print("Successfully rolled back transaction.")
    except Exception as e:
        conn.rollback()
        print(f"Error during cleanup: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
