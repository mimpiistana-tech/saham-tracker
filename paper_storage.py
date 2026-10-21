"""Fail-closed Render persistent-disk check for StockRadar PAPER ONLY.

A path under the normal Render filesystem does not survive a redeploy.
Require an actual OS mount and a database path contained in that mount.
Do not return filesystem paths or other potentially private values to clients.
"""
import os


def storage_health():
    path = os.environ.get("AUTO_PAPER_DB_PATH", "").strip()
    mount = os.environ.get("AUTO_PAPER_DISK_MOUNT", "").strip()

    def no(reason):
        return {"ready": False, "reason": reason}
    if not path or not mount:
        return no("durable_disk_not_configured")
    if not os.path.isabs(path) or not os.path.isabs(mount):
        return no("storage_paths_must_be_absolute")
    # Resolve symlinks before testing containment (e.g. /var/data/../tmp).
    real_mount = os.path.realpath(mount)
    real_path = os.path.realpath(path)
    if real_mount != os.path.normpath(mount):
        return no("disk_mount_alias_not_allowed")
    if real_path == real_mount:
        return no("database_path_not_file")
    try:
        if os.path.commonpath([real_path, real_mount]) != real_mount:
            return no("journal_outside_durable_disk")
    except ValueError:
        return no("journal_outside_durable_disk")
    if not os.path.isdir(mount) or not os.path.ismount(mount):
        return no("persistent_disk_not_mounted")
    parent = os.path.dirname(real_path)
    if not os.path.isdir(parent) or not os.access(parent, os.W_OK):
        return no("journal_directory_unavailable")
    return {"ready": True, "reason": "mounted_disk_verified"}
