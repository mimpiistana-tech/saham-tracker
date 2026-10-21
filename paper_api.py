"""Read-only PAPER simulation readiness API; no orders or trading scheduler.

Report what is actually enabled instead of claiming automatic trades from a live
web server. Never expose per-user paper positions through a public endpoint.
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
        journal_path_configured=bool(os.environ.get("AUTO_PAPER_DB_PATH")),
        storage_check=storage["reason"],
        database_write_verified=probe["write_verified"],
        database_survived_restart=probe["retained_from_previous_process"],
        database_survived_deploy=probe["retained_across_code_deploy"],
        database_probe_status=probe["reason"],
        persistent_journal=storage["ready"] and probe["write_verified"],
        broker_order_enabled=False,
        note="Preview dari candle harian terakhir yang telah selesai; bukan sinyal entry. Entry/exit hanya simulasi berbasis candle harian selesai, tidak ada order uang asli."
    )
