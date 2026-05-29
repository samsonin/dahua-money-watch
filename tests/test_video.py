import subprocess

import pytest

from dahua_money_watch.video import extract_clip


def test_extract_clip_removes_partial_file_on_timeout(tmp_path, monkeypatch):
    target = tmp_path / "clip.mp4"

    def fake_run(*args, **kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"partial")
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr("dahua_money_watch.video.subprocess.run", fake_run)

    with pytest.raises(subprocess.TimeoutExpired):
        extract_clip(tmp_path / "source.dav", target, 0, 8, 28, "ultrafast", True, timeout_seconds=1)

    assert not target.exists()
