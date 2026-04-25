"""Version checking and update logic against GitHub Releases."""

import json
import logging
import subprocess
import sys
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

GITHUB_RELEASES_API = "https://api.github.com/repos/theOSCARP2/agent-linux/releases/latest"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/theOSCARP2/agent-linux/master"


def get_latest_version(timeout: int = 10) -> Optional[str]:
    """Fetch the latest release tag from GitHub. Returns e.g. '1.2.0' or None on failure."""
    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-linux"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        tag = data.get("tag_name", "")
        return tag.lstrip("v") if tag else None
    except Exception as e:
        logger.debug("Failed to fetch latest version: %s", e)
        return None


def is_newer(latest: str, current: str) -> bool:
    """Return True if latest > current using semantic versioning."""
    def _parse(v: str) -> tuple:
        try:
            return tuple(int(x) for x in v.split(".")[:3])
        except ValueError:
            return (0, 0, 0)
    return _parse(latest) > _parse(current)


def check_for_update(current_version: str) -> Optional[str]:
    """Return the latest version string if an update is available, else None."""
    latest = get_latest_version()
    if latest and is_newer(latest, current_version):
        return latest
    return None


def perform_update(current_version: str) -> dict:
    """Download and install the latest release. Returns a result dict."""
    latest = get_latest_version()
    if not latest:
        return {"success": False, "message": "Could not reach GitHub to check for updates."}

    if not is_newer(latest, current_version):
        return {"success": True, "message": f"Already up to date (v{current_version})."}

    logger.info("Updating from v%s to v%s…", current_version, latest)

    try:
        package_url = f"https://github.com/theOSCARP2/agent-linux/archive/refs/tags/v{latest}.tar.gz"
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", package_url],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "message": f"pip install failed:\n{result.stderr}",
            }
        return {
            "success": True,
            "from_version": current_version,
            "to_version": latest,
            "message": f"Updated v{current_version} → v{latest}. Restart the service to apply.",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}
