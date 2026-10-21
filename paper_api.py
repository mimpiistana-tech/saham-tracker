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
    storage_path = os.environ.get("AUTO_PAPER_DB_PATH", "").strip()
    # A path alone does not prove storage survives redeploys or restarts.
    journal_path_configured = bool(storage_path) and os.path.isdir(
        os.path.dirname(os.path.abspath(storage_path))
    )
    from server_scan import status as scan_status
    scan = scan_status()
    return jsonify(
        success=True,
        paper_only=True,
        server_online=True,
        checked_at=datetime.now(timezone.utc).isoformat(),
        candidate_validation=True,
        auto_scan=scan["enabled"],
        scan_preview=scan,
        auto_entry=False,
        auto_exit=False,
        scheduler=False,
        journal_path_configured=journal_path_configured,
        persistent_journal=False,
        broker_order_enabled=False,
        note="Preview dari candle harian terakhir yang telah selesai; bukan sinyal entry. Jurnal permanen dan auto paper entry/exit belum aktif."
    )
