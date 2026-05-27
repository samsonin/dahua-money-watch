from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union


@dataclass(frozen=True)
class Roi:
    x: int
    y: int
    w: int
    h: int


def load_config(path: Union[str, Path]) -> Dict[str, Any]:
    config_path = Path(path)
    data = json.loads(config_path.read_text())
    return data


def resolve_runtime_dir(config: Dict[str, Any], override: Optional[str] = None) -> Path:
    return Path(override or config["runtime_dir"]).expanduser().resolve()


def resolve_archive_root(config: Dict[str, Any], override: Optional[str] = None) -> Path:
    return Path(override or config["archive_root"]).expanduser().resolve()


def roi_from_config(config: Dict[str, Any]) -> Roi:
    roi = config["roi"]
    return Roi(int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"]))
