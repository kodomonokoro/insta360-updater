import pytest
from pathlib import Path
from types import SimpleNamespace

from insta360_uploader.audio_extractor import AudioExtractionError, extract_mp3


def test_raises_if_ffmpeg_not_found(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")

    with pytest.raises(AudioExtractionError, match="ffmpeg not found"):
        extract_mp3(video, tmp_path / "out", ffmpeg_path="definitely-not-a-real-ffmpeg-binary")


@pytest.mark.parametrize("exit_code", [0, 1])
def test_output_only_becomes_visible_after_success(tmp_path, monkeypatch, exit_code):
    from insta360_uploader import audio_extractor
    monkeypatch.setattr(audio_extractor.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(audio_extractor, "probe_duration_seconds", lambda *args: 1)
    output = tmp_path / "out" / "clip.mp3"

    def popen(command, **kwargs):
        part = Path(command[-1])
        assert part.name == "clip.mp3.part"
        part.write_bytes(b"audio")
        assert not output.exists()
        return SimpleNamespace(stdout=[], wait=lambda: exit_code)

    monkeypatch.setattr(audio_extractor.subprocess, "Popen", popen)
    if exit_code:
        with pytest.raises(AudioExtractionError):
            extract_mp3(tmp_path / "clip.mp4", output.parent)
        assert not output.exists()
    else:
        assert extract_mp3(tmp_path / "clip.mp4", output.parent) == output
        assert output.read_bytes() == b"audio"
    assert not output.with_name("clip.mp3.part").exists()
