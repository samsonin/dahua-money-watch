from pathlib import Path


def test_cleanup_storage_only_deletes_camera_archive_sources():
    script = Path("scripts/cleanup_storage.sh").read_text()

    assert 'delete_path "$day_dir"' in script
    assert "runtime_dir/clips" not in script
    assert "runtime_dir/thumbs" not in script
    assert "amount-frames" not in script
    assert "TRANSIENT_MAX_AGE_DAYS" not in script
