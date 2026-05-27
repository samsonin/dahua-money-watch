from pathlib import Path

from dahua_money_watch.dahua import parse_dahua_clip


def test_parse_dahua_clip_name():
    clip = parse_dahua_clip(Path("/archive/2026-05-27/001/dav/14/14.19.38-14.22.00[M][0@0][0].dav"))

    assert clip is not None
    assert clip.date == "2026-05-27"
    assert clip.duration_s == 142
    assert clip.start_clock == "14:19:38"
    assert clip.clock_at(2) == "14:19:40"

