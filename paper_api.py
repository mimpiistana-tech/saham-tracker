"""Read-only PAPER simulation readiness API; no broker orders are possible.

Completed daily bars create plans, confirm paper entries, and manage exits.
Never expose positions.
"""
import os
from datetime import datetime, timezone
from flask import Blueprint, jsonify

paper_api = Blueprint("paper_api", __name__, url_prefix="/api/auto-paper")


@paper_api.get("/status")
def status():
    from paper_storage import storage_health
    storage = storage_health()
    from server_scan import status as scan_status
    scan = scan_status()
    from paper_disk_probe import probe_database
    probe = probe_database()
    from daily_paper_runner import summary as paper_summary
    paper = paper_summary()
    from daily_paper_runner import waiting_entries
    from daily_paper_logic import normalize_waiting_order, MAX_WAIT_SESSIONS
    pending_entries = []
    for order in waiting_entries():
        waited = int(order.get("waited") or 0)
        preview = normalize_waiting_order(order)
        changed = any(preview.get(k) != order.get(k) for k in
                      ("entry","cut_loss","tp1","tp2","lots","status"))
        reason = ("Batas sesi habis; menunggu siklus harian untuk kedaluwarsa" if waited >= MAX_WAIT_SESSIONS
                  else "Harga entry belum tersentuh pada candle yang sudah diproses" if waited
                  else "Menunggu candle selesai setelah tanggal sinyal")
        pending_entries.append({
            **{k:order.get(k) for k in ("ticker","signal_day","entry","cut_loss","tp1","tp2",
                                       "mode","last_bar_day","last_bar_low","last_bar_high","lots")},
            "waited_sessions":waited, "max_wait_sessions":MAX_WAIT_SESSIONS,
            "remaining_sessions":max(0,MAX_WAIT_SESSIONS-waited),
            "waiting_reason":reason,
            "rounding_pending":changed,
            "next_session_levels":({k:preview.get(k) for k in
                                    ("entry","cut_loss","tp1","tp2","lots","status","exit_reason")}
                                   if changed else None),
        })
    return jsonify(
        success=True,
        paper_only=True,
        server_online=True,
        checked_at=datetime.now(timezone.utc).isoformat(),
        candidate_validation=True,
        auto_scan=scan["enabled"],
        scan_preview=scan,
        auto_entry=paper["configured"] and paper["positions_on_server"] and scan["enabled"],
        auto_exit=paper["configured"] and paper["positions_on_server"] and scan["enabled"],
        scheduler=paper["configured"] and scan["enabled"],
        paper_engine=paper,
        pending_entries=pending_entries,
        journal_path_configured=bool(os.environ.get("AUTO_PAPER_DB_PATH")),
        storage_check=storage["reason"],
        database_write_verified=probe["write_verified"],
        database_survived_restart=probe["retained_from_previous_process"],
        database_survived_deploy=probe["retained_across_code_deploy"],
        database_probe_status=probe["reason"],
        persistent_journal=storage["ready"] and probe["write_verified"],
        broker_order_enabled=False,
        note="Rencana, entry, dan exit paper hanya diproses dari candle harian IDX yang sudah selesai dan tervalidasi. Tidak ada order uang asli."
    )
