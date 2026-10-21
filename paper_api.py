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
        journal_path_configured=bool(os.environ.get("AUTO_PAPER_DB_PATH")),
        storage_check=storage["reason"],
        persistent_journal=storage["ready"],
        broker_order_enabled=False,
        note="Preview dari candle harian terakhir yang telah selesai; bukan sinyal entry. Jurnal permanen dan auto paper entry/exit belum aktif."
    )
