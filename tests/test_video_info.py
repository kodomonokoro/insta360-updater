from pathlib import Path

from insta360_uploader.video_info import format_duration, format_size, probe_duration_seconds


def test_format_duration_under_an_hour():
    assert format_duration(75) == "1:15"


def test_format_duration_over_an_hour():
    assert format_duration(3725) == "1:02:05"


def test_format_duration_rounds():
    assert format_duration(59.6) == "1:00"


def test_format_size_bytes():
    assert format_size(500) == "500B"


def test_format_size_kb():
    assert format_size(2048) == "2.0KB"


def test_format_size_mb():
    assert format_size(5 * 1024 * 1024) == "5.0MB"


def test_format_size_gb():
    assert format_size(3 * 1024 * 1024 * 1024) == "3.0GB"


def test_probe_duration_returns_none_when_ffprobe_missing(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")

    result = probe_duration_seconds(video, ffprobe_path="definitely-not-a-real-ffprobe-binary")

    assert result is None
