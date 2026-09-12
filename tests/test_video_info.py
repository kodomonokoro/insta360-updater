from insta360_uploader.video_info import (
    format_duration,
    format_resolution,
    format_size,
    probe_duration_seconds,
    probe_resolution_fps,
    resolution_label,
)


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


def test_probe_resolution_fps_returns_none_when_ffprobe_missing(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")

    result = probe_resolution_fps(video, ffprobe_path="definitely-not-a-real-ffprobe-binary")

    assert result is None


def test_resolution_label_matches_known_widths():
    assert resolution_label(7680) == "8K"
    assert resolution_label(6016) == "6K"
    assert resolution_label(3840) == "4K"


def test_resolution_label_absorbs_minor_rounding():
    assert resolution_label(7683) == "8K"


def test_resolution_label_none_for_unknown_width():
    assert resolution_label(1920) is None


def test_format_resolution_shows_label_and_whole_number_fps():
    assert format_resolution(7680, 3840, 29.97) == "8K 30fps"


def test_format_resolution_falls_back_to_pixels_for_unknown_width():
    assert format_resolution(1920, 1080, 30.0) == "1920x1080 30fps"


def test_format_resolution_omits_unstable_fps():
    # Not close to any whole number -- e.g. a genuinely variable rate --
    # isn't a single meaningful value worth showing.
    assert format_resolution(1920, 1080, 24.6) == "1920x1080"


def test_format_resolution_omits_missing_fps():
    assert format_resolution(6016, 3008, None) == "6K"


def test_format_resolution_label_override_for_raw_lens_track():
    # A raw .insv's per-lens track width (e.g. 3840) doesn't correspond to
    # any equirect "K" bucket directly -- it stitches to 8K, not 4K -- so
    # an explicit label must win over the width-based lookup.
    assert format_resolution(3840, 3840, 29.97, label="8K") == "8K 30fps"
