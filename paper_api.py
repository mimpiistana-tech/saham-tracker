"""Paper-only API endpoints, intentionally inactive without durable storage.

Import and register on the Flask app explicitly. The V3 production app is not
modified until tested and reviewed. This module does not schedule scans.
"""
import os
from flask import Blueprint, jsonify, request

paper_api = Blueprint("paper_api", __name__, url_prefix="/api/auto-paper")

def _storage_ready():
    path = os.environ.get("AUTO_PAPER_DB_PATH", "").strip()
    return bool(path) and os.path.isdir(os.path.dirname(os.path.abspath(path)))

@paper_api.get("/status")
def status():
    persistence = _storage_ready()
    write_enabled = os.environ.get("AUTO_PAPER_WRITE_ENABLED") == "1" and persistence
    return jsonify(success=True, paper_only=True, candidate_validation=True,
                   auto_scan=False, auto_entry=False, auto_exit=False,
                   persistent_journal=persistence, scheduler=False,
                   manual_paper_writes_enabled=write_enabled,
                   broker_order_enabled=False,
                   reason="Automated scanner and scheduler not configured")

@paper_api.get("/trades")
def trades():
    from auto_paper_journal import paper_list
    try:
        return jsonify(success=True, **paper_list())
    except (RuntimeError, OSError) as exc:
        return jsonify(success=False, error=str(exc)), 503

# Mutating routes are deliberately NOT exposed until authenticated access,
# durable shared storage, and an audited completed-candle feed are configured.
