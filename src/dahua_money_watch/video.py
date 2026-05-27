from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator, Optional, Tuple

import numpy as np

from .config import Roi


def ffmpeg_gray_frames(
    path: Path,
    fps: float,
    width: int,
    height: int,
    start_s: Optional[float] = None,
    duration_s: Optional[float] = None,
    roi: Optional[Roi] = None,
) -> Iterator[Tuple[float, np.ndarray]]:
    vf_parts = [f"fps={fps}"]
    if roi:
        vf_parts.append(f"crop={roi.w}:{roi.h}:{roi.x}:{roi.y}")
    vf_parts.append(f"scale={width}:{height}")
    vf_parts.append("format=gray")

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if start_s is not None:
        cmd += ["-ss", f"{max(0.0, start_s):.3f}"]
    cmd += ["-i", str(path)]
    if duration_s is not None:
        cmd += ["-t", f"{max(0.1, duration_s):.3f}"]
    cmd += ["-an", "-vf", ",".join(vf_parts), "-f", "rawvideo", "-pix_fmt", "gray", "-"]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    frame_size = width * height
    index = 0
    while True:
        buf = proc.stdout.read(frame_size)
        if len(buf) < frame_size:
            break
        yield index / fps, np.frombuffer(buf, dtype=np.uint8).reshape((height, width))
        index += 1
    proc.wait()


def extract_clip(
    source: Path,
    target: Path,
    start_s: float,
    duration_s: float,
    crf: int,
    preset: str,
    audio: bool,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, start_s):.3f}",
        "-i",
        str(source),
        "-t",
        f"{max(0.5, duration_s):.3f}",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
    ]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "64k"]
    else:
        cmd += ["-an"]
    cmd.append(str(target))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def extract_frame(source: Path, target: Path, offset_s: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, offset_s):.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        str(target),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
