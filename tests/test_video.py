import hashlib
import json
from types import SimpleNamespace

import pytest

from podcast_practice.errors import PracticeError
from podcast_practice.runtime import Runtime
from podcast_practice.youtube import attach_video


@pytest.fixture
def video_episode(tmp_path, monkeypatch):
    episode = tmp_path / "library" / "episode"
    episode.mkdir(parents=True)
    audio = b"original MP3"
    (episode / "audio.mp3").write_bytes(audio)
    data = {
        "title": "Video practice",
        "created": "2026-11-15",
        "duration": 10,
        "audio_sha256": hashlib.sha256(audio).hexdigest(),
        "fingerprint": "original-id",
        "sentences": [
            {
                "id": 0,
                "text": "Hello.",
                "start": 1,
                "end": 2,
                "speaker": "Host",
                "words": [{"text": "Hello.", "start": 1, "end": 2}],
            }
        ],
        "review": {"warnings": []},
        "chapters": [{"title": "Start", "sentence": 0}],
    }
    (episode / "alignment.json").write_text(json.dumps(data))
    (episode / "player.html").write_text("original player")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"downloaded MP4")
    probe = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "height": 720},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "10.02"},
    }
    monkeypatch.setattr(
        "podcast_practice.youtube.subprocess.run",
        lambda *a, **kw: SimpleNamespace(stdout=json.dumps(probe)),
    )
    return episode, source, data, probe


def test_attaching_video_preserves_alignment_and_progress_identity(video_episode, tmp_path):
    episode, source, original, _ = video_episode
    attach_video(Runtime(tmp_path / "runtime"), episode, source)
    data = json.loads((episode / "alignment.json").read_text())
    for key in ("audio_sha256", "fingerprint", "sentences", "review"):
        assert data[key] == original[key]
    assert (episode / "audio.mp3").read_bytes() == b"original MP3"
    assert data["video"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (episode / "video.mp4").read_bytes() == source.read_bytes()
    page = (episode / "player.html").read_text()
    assert 'audio.src="video.mp4"' in page and "data:audio/mpeg;base64," not in page
    assert "Video practice" in (episode.parent / "index.html").read_text()


@pytest.mark.parametrize("invalid", ["duration", "silent", "codec"])
def test_invalid_video_does_not_replace_an_existing_player(video_episode, tmp_path, invalid):
    episode, source, original, probe = video_episode
    if invalid == "duration":
        probe["format"]["duration"] = "100"
    elif invalid == "silent":
        probe["streams"].pop()
    else:
        probe["streams"][0]["codec_name"] = "av1"
    with pytest.raises(PracticeError, match="影片格式無效"):
        attach_video(Runtime(tmp_path / "runtime"), episode, source)
    assert json.loads((episode / "alignment.json").read_text()) == original
    assert (episode / "player.html").read_text() == "original player"
    assert not (episode / "video.mp4").exists()
