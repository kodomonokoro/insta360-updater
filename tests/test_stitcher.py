import json
from pathlib import Path

import pytest

from insta360_uploader import stitcher
from insta360_uploader.config import MediaSdkConfig
from insta360_uploader.stitcher import StitchError, _detect_stitch_profile, detect_profile_label, stitch_to_mp4


class _FakeProcess:
    def __init__(self, stdout_lines, returncode):
        self.stdout = iter(stdout_lines)
        self._returncode = returncode

    def wait(self):
        return self._returncode


class _FakeProbeResult:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _lens_streams_json(width: int, height: int | None = None) -> str:
    height = width if height is None else height
    return json.dumps({"streams": [{"width": width, "height": height}, {"width": width, "height": height}]})


def _output_probe_json(width: int, height: int, duration: float = 5.0) -> str:
    return json.dumps({"streams": [{"width": width, "height": height}], "format": {"duration": str(duration)}})


def _media_sdk(tmp_path) -> MediaSdkConfig:
    exe = tmp_path / "MediaSDKTest.exe"
    exe.write_bytes(b"0")
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    return MediaSdkConfig(exe_path=exe, model_root_dir=model_dir)


# ---- profile detection (pure, no subprocess) ----


def test_detect_profile_8k(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(_lens_streams_json(3840))
    )
    profile = _detect_stitch_profile(tmp_path / "clip.insv", "ffprobe")
    assert profile.label == "8K"
    assert profile.output_size == "7680x3840"
    assert profile.bitrate == 154_000_000


def test_detect_profile_6k(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(_lens_streams_json(3008))
    )
    profile = _detect_stitch_profile(tmp_path / "clip.insv", "ffprobe")
    assert profile.label == "6K"
    assert profile.output_size == "6016x3008"
    assert profile.bitrate == 50_000_000


def test_detect_profile_label_8k(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(_lens_streams_json(3840))
    )
    assert detect_profile_label(tmp_path / "clip.insv") == "8K"


def test_detect_profile_label_none_for_unrecognized_width(tmp_path, monkeypatch):
    # Never guesses (e.g. via a width-doubling formula) — matches
    # _detect_stitch_profile's own refusal, just without raising.
    monkeypatch.setattr(
        stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(_lens_streams_json(1920))
    )
    assert detect_profile_label(tmp_path / "clip.insv") is None


def test_detect_profile_unrecognized_width_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(_lens_streams_json(1920))
    )
    with pytest.raises(StitchError, match="unrecognized per-lens track width"):
        _detect_stitch_profile(tmp_path / "clip.insv", "ffprobe")


def test_detect_profile_wrong_stream_count_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stitcher.subprocess,
        "run",
        lambda *a, **k: _FakeProbeResult(json.dumps({"streams": [{"width": 3840, "height": 3840}]})),
    )
    with pytest.raises(StitchError, match="expected 2 lens video streams"):
        _detect_stitch_profile(tmp_path / "clip.insv", "ffprobe")


def test_detect_profile_non_square_stream_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(_lens_streams_json(3840, height=1920))
    )
    with pytest.raises(StitchError, match="not a square frame"):
        _detect_stitch_profile(tmp_path / "clip.insv", "ffprobe")


def test_detect_profile_mismatched_lens_widths_raises(tmp_path, monkeypatch):
    mismatched = json.dumps(
        {"streams": [{"width": 3840, "height": 3840}, {"width": 3008, "height": 3008}]}
    )
    monkeypatch.setattr(stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(mismatched))
    with pytest.raises(StitchError, match="different resolutions"):
        _detect_stitch_profile(tmp_path / "clip.insv", "ffprobe")


def test_detect_profile_only_checks_first_stream_is_a_bug_guard(tmp_path, monkeypatch):
    """Regression guard: a lopsided pair (one stream matches a known width,
    the other doesn't) must not silently pass by only looking at streams[0]."""
    lopsided = json.dumps(
        {"streams": [{"width": 3840, "height": 3840}, {"width": 1920, "height": 1920}]}
    )
    monkeypatch.setattr(stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(lopsided))
    with pytest.raises(StitchError, match="different resolutions"):
        _detect_stitch_profile(tmp_path / "clip.insv", "ffprobe")


# ---- stitch_to_mp4 end-to-end ----


def _patch_ffprobe_for_8k(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "-select_streams" in command and command[command.index("-select_streams") + 1] == "v":
            return _FakeProbeResult(_lens_streams_json(3840))
        return _FakeProbeResult(_output_probe_json(7680, 3840))

    monkeypatch.setattr(stitcher.subprocess, "run", fake_run)
    return calls


def test_stitch_success_uses_8k_profile_and_verifies_output(tmp_path, monkeypatch):
    media_sdk = _media_sdk(tmp_path)
    insv = tmp_path / "clip.insv"
    insv.write_bytes(b"0")
    output = tmp_path / "out" / "clip.mp4"
    _patch_ffprobe_for_8k(monkeypatch)

    popen_commands = []

    def fake_popen(command, **kwargs):
        popen_commands.append(command)
        part_path = Path(command[command.index("-output") + 1])
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(b"stitched")
        return _FakeProcess(["process = 50%", "process = 100%"], 0)

    monkeypatch.setattr(stitcher.subprocess, "Popen", fake_popen)

    progress_values: list[float] = []
    log_lines: list[str] = []
    result = stitch_to_mp4(
        insv, output, media_sdk=media_sdk,
        progress_callback=progress_values.append, log=log_lines.append,
    )

    assert result == output
    assert output.is_file()
    assert not output.with_name(output.name + ".part").exists()
    assert progress_values == [0.50, 1.00]

    command = popen_commands[0]
    assert command[0] == str(media_sdk.exe_path)
    assert "-output_size" in command and command[command.index("-output_size") + 1] == "7680x3840"
    assert "-bitrate" in command and command[command.index("-bitrate") + 1] == "154000000"
    assert "-enable_h265_encoder" in command
    assert "-stitch_type" in command and command[command.index("-stitch_type") + 1] == "aistitch"
    assert "-enable_flowstate" in command
    assert "-enable_denoise" in command
    assert "-enable_stitchfusion" in command
    assert "-camera_accessory_type" in command and command[command.index("-camera_accessory_type") + 1] == "0"
    # No framerate override of any kind — source fps must be left alone.
    assert not any("fps" in str(arg).lower() for arg in command)

    assert any("detected 8K source" in line for line in log_lines)
    assert any(line.startswith("running: ") for line in log_lines)


def test_stitch_unrecognized_resolution_never_launches_sdk(tmp_path, monkeypatch):
    media_sdk = _media_sdk(tmp_path)
    insv = tmp_path / "clip.insv"
    insv.write_bytes(b"0")
    output = tmp_path / "clip.mp4"
    monkeypatch.setattr(
        stitcher.subprocess, "run", lambda *a, **k: _FakeProbeResult(_lens_streams_json(1280))
    )

    def fail_if_called(*a, **k):
        raise AssertionError("MediaSDKTest.exe should never be launched for an unrecognized resolution")

    monkeypatch.setattr(stitcher.subprocess, "Popen", fail_if_called)

    with pytest.raises(StitchError, match="unrecognized per-lens track width"):
        stitch_to_mp4(insv, output, media_sdk=media_sdk)


def test_stitch_output_resolution_mismatch_raises_and_cleans_up(tmp_path, monkeypatch):
    media_sdk = _media_sdk(tmp_path)
    insv = tmp_path / "clip.insv"
    insv.write_bytes(b"0")
    output = tmp_path / "clip.mp4"

    def fake_run(command, **kwargs):
        if command[command.index("-select_streams") + 1] == "v":
            return _FakeProbeResult(_lens_streams_json(3840))
        # SDK claimed success but actually wrote the wrong resolution.
        return _FakeProbeResult(_output_probe_json(1920, 960))

    monkeypatch.setattr(stitcher.subprocess, "run", fake_run)

    def fake_popen(command, **kwargs):
        part_path = Path(command[command.index("-output") + 1])
        part_path.write_bytes(b"stitched")
        return _FakeProcess(["process = 100%"], 0)

    monkeypatch.setattr(stitcher.subprocess, "Popen", fake_popen)

    with pytest.raises(StitchError, match="expected 7680x3840"):
        stitch_to_mp4(insv, output, media_sdk=media_sdk)

    assert not output.exists()
    assert not output.with_name(output.name + ".part").exists()


def test_stitch_missing_exe_raises(tmp_path):
    media_sdk = MediaSdkConfig(exe_path=tmp_path / "nope.exe", model_root_dir=tmp_path)

    with pytest.raises(StitchError, match="MediaSDKTest.exe not found"):
        stitch_to_mp4(tmp_path / "clip.insv", tmp_path / "clip.mp4", media_sdk=media_sdk)


def test_stitch_missing_ffprobe_raises(tmp_path, monkeypatch):
    media_sdk = _media_sdk(tmp_path)
    monkeypatch.setattr(stitcher.shutil, "which", lambda name: None)

    with pytest.raises(StitchError, match="ffprobe not found"):
        stitch_to_mp4(tmp_path / "clip.insv", tmp_path / "clip.mp4", media_sdk=media_sdk)


def test_stitch_failure_raises_and_cleans_up_part_file(tmp_path, monkeypatch):
    media_sdk = _media_sdk(tmp_path)
    insv = tmp_path / "clip.insv"
    insv.write_bytes(b"0")
    output = tmp_path / "clip.mp4"
    _patch_ffprobe_for_8k(monkeypatch)

    def fake_popen(command, **kwargs):
        part_path = Path(command[command.index("-output") + 1])
        part_path.write_bytes(b"incomplete")
        return _FakeProcess(["error: something went wrong"], 1)

    monkeypatch.setattr(stitcher.subprocess, "Popen", fake_popen)

    with pytest.raises(StitchError):
        stitch_to_mp4(insv, output, media_sdk=media_sdk)

    assert not output.exists()
    assert not output.with_name(output.name + ".part").exists()
