from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Tuple


def load_license(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())


def license_status(data: Dict[str, Any]) -> Tuple[str, str]:
    license_data = data.get("license", {})
    expires_at = license_data.get("expires_at")
    if not expires_at:
        return "unknown", "No expires_at field"
    try:
        expiry = datetime.strptime(expires_at, "%Y-%m-%d").date()
    except ValueError:
        return "invalid", "Invalid expires_at format"
    today = date.today()
    if expiry < today:
        return "expired", "License expired"
    days = (expiry - today).days
    return "active", f"{days} days remaining"

