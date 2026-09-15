import json
import logging
import threading
import time
import odoo
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Source IDs (Company 6: NAKSHATHRA 916 GOLD AND DIAMONDS SILVER LLP)
SRC_COMPANY_ID = 6
SRC_JOURNAL_ID = 81      # OB
SRC_OB_ACCOUNT_ID = 246  # 100163 Opening Balance
SRC_DR_ACCOUNT_ID = 55   # 100400 Debtors

# Target IDs (Company 5: NAKSHATHRA GOLD AND DIAMOND LLP)
TGT_COMPANY_ID = 5
TGT_JOURNAL_ID = 9       # OPN
TGT_OB_ACCOUNT_ID = 50   # 202001 Opening Balance
TGT_DR_ACCOUNT_ID = 51   # 100401 Debtors
TGT_BRANCH_ID = 1        # Head Office Main

EXPECTED_COUNT = 57602
EXPECTED_AMOUNT = 191225000.00

# Global in-memory progress tracker
_PROGRESS = {
    'status': 'IDLE',      # IDLE, RUNNING, DONE, ERROR
    'percent': 0,
    'current_step': 'Ready',
    'logs': [],
    'is_dry_run': False,
    'action': 'to_company_5',
}


def _resolve_entities(cr):
    cr.execute("SELECT id, name FROM res_company WHERE name ILIKE '%916%';")
    src_c = cr.dictfetchone()
    src_comp_id = src_c["id"] if src_c else 6
    src_comp_name = src_c["name"] if src_c else "NAKSHATHRA 916 GOLD AND DIAMONDS SILVER LLP"

    cr.execute("SELECT id, name FROM res_company WHERE name = 'NAKSHATHRA GOLD AND DIAMOND LLP';")
    tgt_c = cr.dictfetchone()
    tgt_comp_id = tgt_c["id"] if tgt_c else 5
    tgt_comp_name = tgt_c["name"] if tgt_c else "NAKSHATHRA GOLD AND DIAMOND LLP"

    cr.execute("SELECT id FROM account_account WHERE company_id = %s AND code = '100163';", (src_comp_id,))
    row = cr.fetchone()
    src_ob_id = row[0] if row else 246

    cr.execute("SELECT id FROM account_account WHERE company_id = %s AND code = '100400';", (src_comp_id,))
    row = cr.fetchone()
    src_dr_id = row[0] if row else 55

    cr.execute("SELECT id FROM account_account WHERE company_id = %s AND code = '202001';", (tgt_comp_id,))
    row = cr.fetchone()
    tgt_ob_id = row[0] if row else 50

    cr.execute("SELECT id FROM account_account WHERE company_id = %s AND code = '100401';", (tgt_comp_id,))
    row = cr.fetchone()
    tgt_dr_id = row[0] if row else 51

    cr.execute("SELECT id FROM account_journal WHERE company_id = %s AND code = 'OB';", (src_comp_id,))
    row = cr.fetchone()
    src_j_id = row[0] if row else 81

    cr.execute("SELECT id FROM account_journal WHERE company_id = %s AND code = 'OPN';", (tgt_comp_id,))
    row = cr.fetchone()
    tgt_j_id = row[0] if row else 9

    cr.execute("SELECT id FROM res_branch WHERE company_id = %s AND name ILIKE '%%Head Office%%';", (tgt_comp_id,))
    row = cr.fetchone()
    tgt_b_id = row[0] if row else 1

    return {
        'src_comp_id': src_comp_id, 'src_comp_name': src_comp_name,
        'tgt_comp_id': tgt_comp_id, 'tgt_comp_name': tgt_comp_name,
        'src_ob_id': src_ob_id, 'src_dr_id': src_dr_id,
        'tgt_ob_id': tgt_ob_id, 'tgt_dr_id': tgt_dr_id,
        'src_j_id': src_j_id, 'tgt_j_id': tgt_j_id,
        'tgt_b_id': tgt_b_id
    }


def _fetch_status(cr):
    ent = _resolve_entities(cr)
    status = {
        'src_comp_name': ent['src_comp_name'],
        'tgt_comp_name': ent['tgt_comp_name'],
        'src_ob_count': 0,
        'src_ob_debit': 0.0,
        'src_dr_credit': 0.0,
        'tgt_ob_count': 0,
        'tgt_ob_debit': 0.0,
        'tgt_dr_credit': 0.0,
        'journal_81_moves': 0,
        'journal_9_moves': 0,
        'current_location': 'unknown',
    }

    cr.execute("""
        SELECT 
            account_id, 
            count(*) as cnt, 
            COALESCE(sum(debit), 0.0) as deb, 
            COALESCE(sum(credit), 0.0) as cred
        FROM account_move_line
        WHERE account_id IN (%s, %s, %s, %s)
        GROUP BY account_id;
    """, (ent['src_ob_id'], ent['src_dr_id'], ent['tgt_ob_id'], ent['tgt_dr_id']))

    for row in cr.dictfetchall():
        aid = row['account_id']
        if aid == ent['src_ob_id']:
            status['src_ob_count'] = row['cnt']
            status['src_ob_debit'] = float(row['deb'])
        elif aid == ent['src_dr_id']:
            status['src_dr_credit'] = float(row['cred'])
        elif aid == ent['tgt_ob_id']:
            status['tgt_ob_count'] = row['cnt']
            status['tgt_ob_debit'] = float(row['deb'])
        elif aid == ent['tgt_dr_id']:
            status['tgt_dr_credit'] = float(row['cred'])

    cr.execute("SELECT count(*) FROM account_move WHERE journal_id = %s;", (ent['src_j_id'],))
    status['journal_81_moves'] = cr.fetchone()[0]

    cr.execute("SELECT count(*) FROM account_move WHERE journal_id = %s;", (ent['tgt_j_id'],))
    status['journal_9_moves'] = cr.fetchone()[0]

    if status['tgt_ob_count'] >= EXPECTED_COUNT:
        status['current_location'] = f"Company {ent['tgt_comp_id']} ({ent['tgt_comp_name']})"
    elif status['src_ob_count'] >= EXPECTED_COUNT:
        status['current_location'] = f"Company {ent['src_comp_id']} ({ent['src_comp_name']})"
    else:
        status['current_location'] = 'Split or Custom'

    return status


def _run_transfer_thread(dbname, action_type='to_company_5', commit=False):
    global _PROGRESS
    _PROGRESS['status'] = 'RUNNING'
    _PROGRESS['percent'] = 5
    _PROGRESS['current_step'] = 'Initializing database connection...'
    _PROGRESS['logs'] = []
    _PROGRESS['is_dry_run'] = not commit
    _PROGRESS['action'] = action_type

    def log(msg, percent=None):
        timestamp = time.strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}"
        _PROGRESS['logs'].append(line)
        if percent is not None:
            _PROGRESS['percent'] = percent
            _PROGRESS['current_step'] = msg
        _logger.info(line)

    mode_label = "LIVE EXECUTION (COMMIT)" if commit else "SAFE SIMULATION (DRY-RUN / ROLLBACK)"
    log("=" * 66, 5)
    log(f"STARTING SCHEME OPENING BALANCE TRANSFER", 5)
    log(f"Mode:   {mode_label}")
    log(f"Action: {action_type}")
    log(f"DB:     {dbname}")
    log("=" * 66, 8)

    db = odoo.sql_db.db_connect(dbname)
    with db.cursor() as cr:
        try:
            env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
            ent = _resolve_entities(cr)
            src_comp_id = ent['src_comp_id']
            tgt_comp_id = ent['tgt_comp_id']
            src_ob_id = ent['src_ob_id']
            src_dr_id = ent['src_dr_id']
            tgt_ob_id = ent['tgt_ob_id']
            tgt_dr_id = ent['tgt_dr_id']
            src_j_id = ent['src_j_id']
            tgt_j_id = ent['tgt_j_id']
            tgt_b_id = ent['tgt_b_id']

            log(f"Source: {ent['src_comp_name']} (ID {src_comp_id}) - Journal {src_j_id} - OB Acc {src_ob_id}", 10)
            log(f"Target: {ent['tgt_comp_name']} (ID {tgt_comp_id}) - Journal {tgt_j_id} - OB Acc {tgt_ob_id}", 10)

            if action_type == 'to_company_5':
                # Transfer 6 -> 5
                log("[Step 0] Validating source entries in Source Company...", 12)
                cr.execute("""
                    SELECT count(DISTINCT m.id) as move_cnt, count(l.id) as line_cnt, sum(l.debit) as deb
                    FROM account_move_line l
                    JOIN account_move m ON l.move_id = m.id
                    WHERE l.account_id = %s AND m.journal_id = %s;
                """, (src_ob_id, src_j_id))
                stats = cr.dictfetchone()

                if stats['move_cnt'] == 0:
                    # Check if already in Company 5
                    cr.execute("SELECT count(*) FROM account_move_line WHERE account_id = %s;", (tgt_ob_id,))
                    tgt_cnt = cr.fetchone()[0]
                    if tgt_cnt >= EXPECTED_COUNT:
                        log(f"NOTICE: All {tgt_cnt:,} opening entries are ALREADY in Target Company (Account 202001)!", 100)
                        log(f"Total Debit: ₹{EXPECTED_AMOUNT:,.2f}. No transfer needed.", 100)
                        _PROGRESS['status'] = 'DONE'
                        return
                    raise ValueError(f"No moves found on source Account {src_ob_id} and not in target!")

                log(f"Found {stats['move_cnt']:,} moves totaling ₹{float(stats['deb']):,.2f} to transfer.", 20)

                # Step 1: Unreconcile 168 lines
                log("[Step 1] Checking and cleaning cross-company reconciliations...", 25)
                cr.execute("""
                    SELECT pr.id, pr.debit_move_id, pr.full_reconcile_id
                    FROM account_partial_reconcile pr
                    WHERE pr.credit_move_id IN (
                        SELECT l.id FROM account_move_line l
                        WHERE l.account_id = %s AND l.move_id IN (
                            SELECT DISTINCT move_id FROM account_move_line WHERE account_id = %s
                        )
                    );
                """, (src_dr_id, src_ob_id))
                part_recs = cr.dictfetchall()
                log(f"Found {len(part_recs)} partial reconciliations to clean.", 30)

                if part_recs:
                    part_ids = tuple(r['id'] for r in part_recs)
                    deb_ids = tuple(set(r['debit_move_id'] for r in part_recs))
                    full_ids = tuple(set(r['full_reconcile_id'] for r in part_recs if r['full_reconcile_id']))

                    if full_ids:
                        cr.execute("UPDATE account_move_line SET full_reconcile_id = NULL WHERE full_reconcile_id IN %s;", (full_ids,))
                        cr.execute("DELETE FROM account_full_reconcile WHERE id IN %s;", (full_ids,))
                        log(f"Cleared {len(full_ids)} full reconciliation records.", 35)

                    cr.execute("DELETE FROM account_partial_reconcile WHERE id IN %s;", (part_ids,))
                    log(f"Deleted {len(part_ids)} partial reconciliation records.", 40)

                    for d_id in deb_ids:
                        cr.execute("""
                            UPDATE account_move_line l
                            SET 
                                amount_residual = l.debit - COALESCE((
                                    SELECT sum(pr.amount) FROM account_partial_reconcile pr WHERE pr.debit_move_id = l.id
                                ), 0.0),
                                amount_residual_currency = l.debit - COALESCE((
                                    SELECT sum(pr.amount) FROM account_partial_reconcile pr WHERE pr.debit_move_id = l.id
                                ), 0.0),
                                reconciled = (
                                    (l.debit - COALESCE((
                                        SELECT sum(pr.amount) FROM account_partial_reconcile pr WHERE pr.debit_move_id = l.id
                                    ), 0.0)) = 0.0
                                )
                            WHERE l.id = %s
                            RETURNING l.move_id, l.amount_residual, l.debit;
                        """, (d_id,))
                        row = cr.dictfetchone()
                        if row:
                            res, deb = float(row['amount_residual']), float(row['debit'])
                            pstate = "paid" if res == 0 else ("partial" if res < deb else "not_paid")
                            cr.execute("UPDATE account_move SET payment_state = %s WHERE id = %s;", (pstate, row['move_id']))

                # Reset residual on all credit lines
                cr.execute("""
                    UPDATE account_move_line
                    SET amount_residual = -credit, amount_residual_currency = -credit, reconciled = false, full_reconcile_id = NULL
                    WHERE account_id = %s AND move_id IN (
                        SELECT DISTINCT move_id FROM account_move_line WHERE account_id = %s
                    );
                """, (src_dr_id, src_ob_id))
                log(f"Reset residual on {cr.rowcount:,} credit lines.", 48)

                # Step 2: Update account_move
                log(f"[Step 2] Moving {EXPECTED_COUNT:,} account_move records to Company {tgt_comp_id}...", 52)
                cr.execute("""
                    UPDATE account_move
                    SET company_id = %s, journal_id = %s, branch_id = COALESCE(branch_id, %s)
                    WHERE journal_id = %s 
                      AND id IN (SELECT DISTINCT move_id FROM account_move_line WHERE account_id = %s);
                """, (tgt_comp_id, tgt_j_id, tgt_b_id, src_j_id, src_ob_id))
                log(f"Updated {cr.rowcount:,} account_move records to Journal {tgt_j_id} (OPN).", 65)

                # Step 3: Update account_move_line
                log("[Step 3] Updating account_move_line accounts...", 70)
                # 3a Debit lines
                cr.execute("""
                    UPDATE account_move_line
                    SET account_id = %s, company_id = %s, journal_id = %s, branch_id = COALESCE(branch_id, %s)
                    WHERE account_id = %s;
                """, (tgt_ob_id, tgt_comp_id, tgt_j_id, tgt_b_id, src_ob_id))
                log(f"Updated {cr.rowcount:,} debit lines (Account {src_ob_id} -> {tgt_ob_id}).", 78)

                # 3b Credit lines
                cr.execute("""
                    UPDATE account_move_line l
                    SET account_id = %s, company_id = %s, journal_id = %s, branch_id = COALESCE(l.branch_id, %s)
                    FROM account_move m
                    WHERE l.move_id = m.id
                      AND m.company_id = %s
                      AND m.journal_id = %s
                      AND l.account_id = %s;
                """, (tgt_dr_id, tgt_comp_id, tgt_j_id, tgt_b_id,
                      tgt_comp_id, tgt_j_id, src_dr_id))
                log(f"Updated {cr.rowcount:,} credit lines (Account {src_dr_id} -> {tgt_dr_id}).", 85)

                # Step 4: Update scheme installments
                log("[Step 4] Updating jewellery_scheme_installment records...", 88)
                cr.execute("""
                    UPDATE jewellery_scheme_installment
                    SET journal_id = %s
                    WHERE move_id IN (
                        SELECT id FROM account_move WHERE company_id = %s AND journal_id = %s AND name LIKE 'OB/%%'
                    );
                """, (tgt_j_id, tgt_comp_id, tgt_j_id))
                log(f"Updated {cr.rowcount:,} scheme installments to Journal {tgt_j_id}.", 92)

            elif action_type == 'revert_to_company_6':
                # Revert 5 -> 6 (for testing/demo)
                log("[Step 0] Validating entries in Target Company to revert...", 15)
                cr.execute("""
                    SELECT count(DISTINCT m.id) as move_cnt, sum(l.debit) as deb
                    FROM account_move_line l
                    JOIN account_move m ON l.move_id = m.id
                    WHERE l.account_id = %s AND m.journal_id = %s AND m.name LIKE 'OB/%%';
                """, (tgt_ob_id, tgt_j_id))
                stats = cr.dictfetchone()

                if not stats or stats['move_cnt'] == 0:
                    raise ValueError(f"No scheme opening moves found in Target Company to revert!")

                log(f"Found {stats['move_cnt']:,} moves totaling ₹{float(stats['deb']):,.2f} to revert.", 25)

                # Step 1: Update moves
                log("[Step 1] Moving account_move records back to Source Company...", 40)
                cr.execute("""
                    UPDATE account_move
                    SET company_id = %s, journal_id = %s
                    WHERE company_id = %s AND journal_id = %s AND name LIKE 'OB/%%';
                """, (src_comp_id, src_j_id, tgt_comp_id, tgt_j_id))
                log(f"Reverted {cr.rowcount:,} account_move records to Journal {src_j_id} (OB).", 55)

                # Step 2: Update debit lines
                log("[Step 2] Updating debit lines back to Account 100163...", 65)
                cr.execute("""
                    UPDATE account_move_line
                    SET account_id = %s, company_id = %s, journal_id = %s
                    WHERE account_id = %s;
                """, (src_ob_id, src_comp_id, src_j_id, tgt_ob_id))
                log(f"Reverted {cr.rowcount:,} debit lines to Account {src_ob_id}.", 75)

                # Step 3: Update credit lines
                log("[Step 3] Updating credit lines back to Account 100400...", 80)
                cr.execute("""
                    UPDATE account_move_line l
                    SET account_id = %s, company_id = %s, journal_id = %s
                    FROM account_move m
                    WHERE l.move_id = m.id
                      AND m.company_id = %s
                      AND m.journal_id = %s
                      AND l.account_id = %s;
                """, (src_dr_id, src_comp_id, src_j_id,
                      src_comp_id, src_j_id, tgt_dr_id))
                log(f"Reverted {cr.rowcount:,} credit lines to Account {src_dr_id}.", 88)

                # Step 4: Update scheme installments
                log("[Step 4] Updating scheme installments back to Journal 81...", 92)
                cr.execute("""
                    UPDATE jewellery_scheme_installment
                    SET journal_id = %s
                    WHERE move_id IN (
                        SELECT id FROM account_move WHERE company_id = %s AND journal_id = %s AND name LIKE 'OB/%%'
                    );
                """, (src_j_id, src_comp_id, src_j_id))
            # Invalidate ORM cache
            env.invalidate_all()
            log("Invalidated Odoo registry cache.", 97)

            if commit:
                cr.commit()
                log("==================================================================", 100)
                log("SUCCESS: MIGRATION COMMITTED TO DATABASE!", 100)
                log("All changes are permanently saved.", 100)
                log("==================================================================", 100)
                _PROGRESS['status'] = 'DONE'
            else:
                cr.rollback()
                log("==================================================================", 100)
                log("DRY-RUN SIMULATION FINISHED SUCCESSFULLY!", 100)
                log("Transaction was rolled back. No database changes were persisted.", 100)
                log("==================================================================", 100)
                _PROGRESS['status'] = 'DONE'

        except Exception as e:
            cr.rollback()
            _logger.exception("Error in Scheme OB Transfer")
            log(f"ERROR: {str(e)}", 100)
            _PROGRESS['status'] = 'ERROR'


def _get_active_dbname():
    if hasattr(request, 'session') and getattr(request.session, 'db', None):
        return request.session.db
    if hasattr(request, 'env') and getattr(request.env, 'cr', None) and getattr(request.env.cr, 'dbname', None):
        return request.env.cr.dbname
    if odoo.tools.config.get('db_name'):
        return odoo.tools.config['db_name']
    try:
        dbs = odoo.service.db.list_dbs(True)
        if dbs:
            return dbs[0]
    except Exception:
        pass
    return "Production backup (15 Sep | 04:04 AM )"


class SchemeOBTransferController(http.Controller):

    @http.route('/scheme_ob_transfer', type='http', auth='public')
    def dashboard(self, **kwargs):
        dbname = _get_active_dbname()
        db = odoo.sql_db.db_connect(dbname)
        with db.cursor() as cr:
            status = _fetch_status(cr)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scheme Opening Balance Transfer Console</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-body: #090d16;
            --card-bg: #111827;
            --card-border: #1f293d;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-blue: #3b82f6;
            --accent-red: #ef4444;
            --text-primary: #f8fafc;
            --text-muted: #94a3b8;
            --terminal-bg: #030712;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg-body);
            color: var(--text-primary);
            padding: 30px 20px;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 25px;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(6, 182, 212, 0.12);
            color: var(--accent-cyan);
            border: 1px solid rgba(6, 182, 212, 0.3);
            border-radius: 9999px;
            padding: 4px 14px;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 10px;
        }}
        .header h1 {{
            font-size: 26px;
            font-weight: 700;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 6px;
        }}
        .header p {{
            color: var(--text-muted);
            font-size: 14px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .card-title {{
            font-size: 14px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .company-name {{
            font-size: 15px;
            font-weight: 700;
            color: #fff;
            margin-bottom: 12px;
        }}
        .stat-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px dashed rgba(255, 255, 255, 0.05);
            font-size: 14px;
        }}
        .stat-label {{ color: var(--text-muted); }}
        .stat-val {{ font-weight: 600; font-family: 'JetBrains Mono', monospace; }}
        .stat-val.highlight {{ color: var(--accent-cyan); }}
        .stat-val.green {{ color: var(--accent-green); }}

        /* Control Panel */
        .controls {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            align-items: center;
            justify-content: space-between;
        }}
        .action-group {{
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
        }}
        select.custom-select {{
            background: #1e293b;
            color: #fff;
            border: 1px solid #334155;
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            cursor: pointer;
        }}
        .btn {{
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
        }}
        .btn-dry {{
            background: rgba(6, 182, 212, 0.15);
            color: var(--accent-cyan);
            border: 1px solid rgba(6, 182, 212, 0.4);
        }}
        .btn-dry:hover {{
            background: rgba(6, 182, 212, 0.25);
        }}
        .btn-exec {{
            background: linear-gradient(135deg, #059669, #10b981);
            color: #fff;
            box-shadow: 0 2px 10px rgba(16, 185, 129, 0.3);
        }}
        .btn-exec:hover {{
            background: linear-gradient(135deg, #047857, #059669);
        }}
        .btn:disabled {{
            opacity: 0.4;
            cursor: not-allowed;
        }}
        .confirm-wrapper {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: var(--text-muted);
        }}
        .confirm-wrapper input[type="checkbox"] {{
            accent-color: var(--accent-green);
            width: 16px;
            height: 16px;
            cursor: pointer;
        }}

        /* Progress & Terminal */
        .terminal-box {{
            background: var(--terminal-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
        }}
        .terminal-header {{
            background: #111827;
            padding: 10px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--card-border);
        }}
        .terminal-dots {{
            display: flex;
            gap: 6px;
        }}
        .dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
        .dot-red {{ background: #ef4444; }}
        .dot-yellow {{ background: #f59e0b; }}
        .dot-green {{ background: #10b981; }}
        .terminal-title {{
            font-size: 12px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }}
        .progress-bar-container {{
            background: #1e293b;
            height: 5px;
            width: 100%;
        }}
        .progress-bar {{
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #06b6d4, #10b981);
            transition: width 0.3s;
        }}
        .terminal-content {{
            padding: 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            line-height: 1.6;
            height: 380px;
            overflow-y: auto;
            color: #d1d5db;
        }}
        .log-entry {{ margin-bottom: 2px; white-space: pre-wrap; }}
        .log-entry.step {{ color: var(--accent-cyan); font-weight: 600; }}
        .log-entry.success {{ color: var(--accent-green); font-weight: 700; }}
        .log-entry.error {{ color: var(--accent-red); font-weight: 700; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="badge">
                <span>⚡</span> Database Utility Dashboard
            </div>
            <h1>Scheme Opening Balance Transfer Console</h1>
            <p>Transfer ₹19,12,25,000 (57,602 lines) between companies with live terminal output</p>
        </div>

        <div class="grid">
            <!-- Source Card: Company 6 -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Source Company (ID 6)</span>
                    <span style="font-size:12px; color:var(--text-muted);">Journal: <strong>OB (81)</strong></span>
                </div>
                <div class="company-name">NAKSHATHRA 916 GOLD AND DIAMONDS SILVER LLP</div>
                <div class="stat-row">
                    <span class="stat-label">100163 Opening Balance</span>
                    <span class="stat-val highlight" id="srcObCount">{status['src_ob_count']:,} lines</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Opening Debit Balance</span>
                    <span class="stat-val highlight" id="srcObDebit">₹{status['src_ob_debit']:,.2f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">100400 Debtors Total Credit</span>
                    <span class="stat-val" id="srcDrCredit">₹{status['src_dr_credit']:,.2f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Journal 81 (OB) Moves</span>
                    <span class="stat-val" id="j81Moves">{status['journal_81_moves']:,} moves</span>
                </div>
            </div>

            <!-- Target Card: Company 5 -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Target Company (ID 5)</span>
                    <span style="font-size:12px; color:var(--text-muted);">Journal: <strong>OPN (9)</strong></span>
                </div>
                <div class="company-name">NAKSHATHRA GOLD AND DIAMOND LLP</div>
                <div class="stat-row">
                    <span class="stat-label">202001 Opening Balance</span>
                    <span class="stat-val green" id="tgtObCount">{status['tgt_ob_count']:,} lines</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Opening Debit Balance</span>
                    <span class="stat-val green" id="tgtObDebit">₹{status['tgt_ob_debit']:,.2f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">100401 Debtors Total Credit</span>
                    <span class="stat-val" id="tgtDrCredit">₹{status['tgt_dr_credit']:,.2f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Journal 9 (OPN) Moves</span>
                    <span class="stat-val" id="j9Moves">{status['journal_9_moves']:,} moves</span>
                </div>
            </div>
        </div>

        <!-- Controls -->
        <div class="controls">
            <div class="action-group">
                <label style="font-size:13px; color:var(--text-muted); font-weight:600;">Action:</label>
                <select id="actionSelect" class="custom-select">
                    <option value="to_company_5">Transfer to Company 5 (NAKSHATHRA GOLD AND DIAMOND LLP)</option>
                    <option value="revert_to_company_6">Revert to Company 6 (for testing/demo)</option>
                </select>
            </div>

            <div class="action-group">
                <button class="btn btn-dry" id="btnDryRun" onclick="startExecution(false)">
                    <span>🧪</span> Simulate (Dry Run)
                </button>

                <div class="confirm-wrapper">
                    <input type="checkbox" id="chkConfirm">
                    <label for="chkConfirm">I confirm live DB update</label>
                </div>

                <button class="btn btn-exec" id="btnExecute" onclick="startExecution(true)" disabled>
                    <span>⚡</span> Execute Live
                </button>
            </div>
        </div>

        <!-- Terminal Output -->
        <div class="terminal-box">
            <div class="terminal-header">
                <div class="terminal-dots">
                    <span class="dot dot-red"></span>
                    <span class="dot dot-yellow"></span>
                    <span class="dot dot-green"></span>
                </div>
                <div class="terminal-title" id="terminalStatus">bash - scheme_ob_transfer.py (IDLE)</div>
                <div style="font-size:12px; color:var(--accent-cyan); font-weight:600;" id="percentText">0%</div>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar" id="progressBar"></div>
            </div>
            <div class="terminal-content" id="terminalOutput">
                <div class="log-entry" style="color:var(--text-muted);">Ready to run. Click [Simulate (Dry Run)] or [Execute Live] to begin...</div>
            </div>
        </div>
    </div>

    <script>
        const chkConfirm = document.getElementById('chkConfirm');
        const btnExecute = document.getElementById('btnExecute');
        const btnDryRun = document.getElementById('btnDryRun');
        const actionSelect = document.getElementById('actionSelect');
        const terminalOutput = document.getElementById('terminalOutput');
        const progressBar = document.getElementById('progressBar');
        const percentText = document.getElementById('percentText');
        const terminalStatus = document.getElementById('terminalStatus');

        chkConfirm.addEventListener('change', () => {{
            btnExecute.disabled = !chkConfirm.checked;
        }});

        let pollInterval = null;
        let seenLogsCount = 0;

        function logToTerminal(text) {{
            const div = document.createElement('div');
            div.className = 'log-entry';
            if (text.includes('SUCCESS') || text.includes('FINISHED SUCCESSFULLY') || text.includes('COMMITTED')) {{
                div.className += ' success';
            }} else if (text.includes('ERROR') || text.includes('aborted')) {{
                div.className += ' error';
            }} else if (text.includes('[Step ') || text.includes('STARTING')) {{
                div.className += ' step';
            }}
            div.textContent = text;
            terminalOutput.appendChild(div);
            terminalOutput.scrollTop = terminalOutput.scrollHeight;
        }}

        function refreshStatus() {{
            fetch('/scheme_ob_transfer/status')
                .then(r => r.json())
                .then(data => {{
                    document.getElementById('srcObCount').innerText = data.src_ob_count.toLocaleString() + ' lines';
                    document.getElementById('srcObDebit').innerText = '₹' + data.src_ob_debit.toLocaleString(undefined, {{minimumFractionDigits: 2}});
                    document.getElementById('srcDrCredit').innerText = '₹' + data.src_dr_credit.toLocaleString(undefined, {{minimumFractionDigits: 2}});
                    document.getElementById('j81Moves').innerText = data.journal_81_moves.toLocaleString() + ' moves';

                    document.getElementById('tgtObCount').innerText = data.tgt_ob_count.toLocaleString() + ' lines';
                    document.getElementById('tgtObDebit').innerText = '₹' + data.tgt_ob_debit.toLocaleString(undefined, {{minimumFractionDigits: 2}});
                    document.getElementById('tgtDrCredit').innerText = '₹' + data.tgt_dr_credit.toLocaleString(undefined, {{minimumFractionDigits: 2}});
                    document.getElementById('j9Moves').innerText = data.journal_9_moves.toLocaleString() + ' moves';
                }});
        }}

        function startExecution(commit) {{
            if (commit && !chkConfirm.checked) {{
                alert('Please check the confirmation box to authorize live execution.');
                return;
            }}

            const action = actionSelect.value;
            seenLogsCount = 0;
            terminalOutput.innerHTML = '';
            progressBar.style.width = '5%';
            percentText.innerText = '5%';
            terminalStatus.innerText = 'bash - scheme_ob_transfer.py (' + (commit ? 'LIVE EXECUTION' : 'DRY RUN') + ')';

            btnDryRun.disabled = true;
            btnExecute.disabled = true;

            fetch('/scheme_ob_transfer/start', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ commit: commit, action: action }})
            }})
            .then(r => r.json())
            .then(res => {{
                if (res.error) {{
                    alert(res.error);
                    btnDryRun.disabled = false;
                    btnExecute.disabled = !chkConfirm.checked;
                    return;
                }}
                if (pollInterval) clearInterval(pollInterval);
                pollInterval = setInterval(pollProgress, 800);
            }})
            .catch(err => {{
                alert('Failed to start transfer: ' + err);
                btnDryRun.disabled = false;
                btnExecute.disabled = !chkConfirm.checked;
            }});
        }}

        function pollProgress() {{
            fetch('/scheme_ob_transfer/progress')
                .then(r => r.json())
                .then(data => {{
                    progressBar.style.width = data.percent + '%';
                    percentText.innerText = data.percent + '%';
                    terminalStatus.innerText = 'bash - scheme_ob_transfer.py (' + data.current_step + ')';

                    if (data.logs && data.logs.length > seenLogsCount) {{
                        for (let i = seenLogsCount; i < data.logs.length; i++) {{
                            logToTerminal(data.logs[i]);
                        }}
                        seenLogsCount = data.logs.length;
                    }}

                    if (data.status === 'DONE' || data.status === 'ERROR') {{
                        clearInterval(pollInterval);
                        pollInterval = null;
                        refreshStatus();
                        btnDryRun.disabled = false;
                        btnExecute.disabled = !chkConfirm.checked;
                        terminalStatus.innerText = 'bash - scheme_ob_transfer.py (' + (data.status === 'DONE' ? 'COMPLETED' : 'ERROR') + ')';
                    }}
                }});
        }}
    </script>
</body>
</html>"""
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    @http.route('/scheme_ob_transfer/status', type='http', auth='public', methods=['GET'])
    def get_status(self, **kwargs):
        dbname = _get_active_dbname()
        db = odoo.sql_db.db_connect(dbname)
        with db.cursor() as cr:
            status = _fetch_status(cr)
        return request.make_response(json.dumps(status), headers=[('Content-Type', 'application/json')])

    @http.route('/scheme_ob_transfer/start', type='http', auth='public', methods=['POST'], csrf=False)
    def start_transfer(self, **kwargs):
        global _PROGRESS
        if _PROGRESS.get('status') == 'RUNNING':
            return request.make_response(
                json.dumps({'error': 'A transfer process is already running.'}),
                headers=[('Content-Type', 'application/json')]
            )

        try:
            data = json.loads(request.httprequest.data or '{}')
        except Exception:
            data = kwargs

        commit = bool(data.get('commit', False))
        action = str(data.get('action', 'to_company_5'))
        dbname = _get_active_dbname()

        thread = threading.Thread(target=_run_transfer_thread, args=(dbname, action, commit))
        thread.daemon = True
        thread.start()

        return request.make_response(
            json.dumps({'status': 'STARTED', 'commit': commit, 'action': action}),
            headers=[('Content-Type', 'application/json')]
        )

    @http.route('/scheme_ob_transfer/progress', type='http', auth='public', methods=['GET'])
    def get_progress(self, **kwargs):
        global _PROGRESS
        return request.make_response(json.dumps(_PROGRESS), headers=[('Content-Type', 'application/json')])

