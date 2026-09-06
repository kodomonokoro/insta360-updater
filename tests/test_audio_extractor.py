import pytest

from insta360_uploader.audio_extractor import AudioExtractionError, extract_mp3


def test_raises_if_ffmpeg_not_found(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")

    with pytest.raises(AudioExtractionError, match="ffmpeg not found"):
        extract_mp3(video, tmp_path / "out", ffmpeg_path="definitely-not-a-real-ffmpeg-binary")
