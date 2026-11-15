import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yt_dlp

from podcast_practice import cli
from podcast_practice.errors import PracticeError
from podcast_practice.render import player_html
from podcast_practice.runtime import Runtime
from podcast_practice.transcript import parse_subtitles, parse_transcript
from podcast_practice.youtube import (
    MAX_CAPTION_BYTES,
    CachedDownloadError,
    caption_srt,
    download_youtube,
    english_caption,
    reuse_youtube_source,
    youtube_request,
    youtube_url,
)

VIDEO_ID = "jNQXAC9IVRw"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.mark.parametrize(
    "url",
    [
        URL + "&list=ignored&t=30",
        f"https://youtu.be/{VIDEO_ID}?si=tracking",
        f"https://m.youtube.com/shorts/{VIDEO_ID}",
        f"http://youtube.com/embed/{VIDEO_ID}",
        f"youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}",
    ],
)
def test_video_links_are_canonical_single_video_urls(url):
    assert youtube_url(url) == URL


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "--exec=bad",
        "file:///etc/passwd",
        "http://127.0.0.1/test",
        f"https://youtube.com.evil.test/watch?v={VIDEO_ID}",
        f"https://youtube.com@evil.test/watch?v={VIDEO_ID}",
        f"https://user:password@youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com:8766/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}/extra",
        "https://youtube.com/playlist?list=one",
        f"https://youtube.com/watch?v={VIDEO_ID}&v=another",
        URL + "\n--exec",
        "https://www.youtube.com/watch?v=invalid",
        "https://[invalid",
    ],
)
def test_invalid_urls_are_rejected_before_network_access(url):
    with pytest.raises(PracticeError):
        youtube_url(url)


def track(**changes):
    return {"ext": "json3", "url": "https://www.youtube.com/api/timedtext?v=test", **changes}


def test_prefers_uploaded_english_over_automatic_and_ignores_other_languages():
    manual, auto = track(), track(url="https://www.youtube.com/api/timedtext?kind=asr")
    info = {"subtitles": {"en-US": [manual]}, "automatic_captions": {"en": [auto]}}
    assert english_caption(info) == ("en-US", False, manual)
    assert english_caption({"automatic_captions": {"en-orig": [auto]}}) == ("en-orig", True, auto)


@pytest.mark.parametrize(
    "info",
    [
        {},
        {"subtitles": {"zh-TW": [track()]}},
        {"automatic_captions": {"en": [track(url=track()["url"] + "&tlang=en")]}},
        {"subtitles": {"en": [track(url="http://127.0.0.1/captions")]}},
    ],
)
def test_missing_english_or_auto_translations_are_not_used(info):
    with pytest.raises(PracticeError, match="沒有可取得的英文字幕"):
        english_caption(info)


def event(start, end, text):
    return {"tStartMs": start, "dDurationMs": end - start, "segs": [{"utf8": text}]}


def captions(events):
    return json.dumps({"events": events}).encode()


def test_caption_rollup_deduplication_retains_non_overlapping_repetitions():
    payload = captions(
        [
            {"tStartMs": 0},
            event(0, 3000, "Hello world"),
            event(2000, 5000, "Hello world and goodbye."),
            event(5000, 7000, "Hello world"),
            event(7000, 10000, "&lt;Music&gt; <i>Repeat.</i>"),
        ]
    )
    rows = parse_subtitles(caption_srt(payload, 9))
    assert [row[1] for row in rows] == ["Hello world", "and goodbye.", "Hello world", "Repeat."]
    assert [(row[2], row[3]) for row in rows] == [(0, 2), (2, 5), (5, 7), (7, 9)]


def test_caption_same_start_rollup_is_one_cue():
    rows = parse_subtitles(
        caption_srt(captions([event(0, 2000, "Hello"), event(0, 3000, "Hello world.")]), 3)
    )
    assert rows == [("Narrator", "Hello world.", 0, 3)]


def test_asr_newline_events_do_not_repeat_the_previous_caption():
    rows = parse_subtitles(
        caption_srt(
            captions(
                [
                    event(0, 3000, "Hello world"),
                    event(1000, 1001, "\n"),
                    event(2000, 5000, "Hello world again."),
                ]
            ),
            5,
        )
    )
    assert [row[1] for row in rows] == ["Hello world", "again."]


def test_caption_speaker_and_noise_markers_do_not_become_mfa_utterances(tmp_path):
    payload = captions(
        [
            event(0, 1500, ">> THAT WOULD BE MEAN."),
            event(1500, 1505, ">> [laughter]"),
            event(1505, 2000, ">> [clears throat and laughter]"),
            event(2000, 2500, "[snorts]"),
            event(2500, 4500, ">> Yes, [laughter] it would."),
        ]
    )
    path = tmp_path / "captions.srt"
    path.write_text(caption_srt(payload, 5))
    transcript = parse_transcript(path, caption_style=True)
    assert [s.text for s in transcript.sentences] == ["THAT WOULD BE MEAN.", "Yes, it would."]
    assert transcript.normalized == ["that", "would", "be", "mean", "yes", "it", "would"]
    assert transcript.sentences[1].supplied_start == 2.5


def test_overlapping_speaker_interjection_keeps_words_and_gets_a_usable_interval(tmp_path):
    payload = captions(
        [
            event(891504, 892944, "investigations lined up already."),
            event(892944, 893644, "[Laughs] Yeah. They really do."),
            event(893004, 895784, "I mean, there are so many rocks to turn over here."),
            event(895844, 896544, "Yeah."),
            event(895924, 900864, "And it does not stop here."),
        ]
    )
    path = tmp_path / "overlapping.srt"
    path.write_text(caption_srt(payload, 901))
    transcript = parse_transcript(path, caption_style=True)
    assert [s.text for s in transcript.sentences] == [
        "investigations lined up already.",
        "Yeah. They really do. I mean, there are so many rocks to turn over here.",
        "Yeah. And it does not stop here.",
    ]
    assert [(s.supplied_start, s.supplied_end) for s in transcript.sentences] == [
        (891.504, 892.944),
        (892.944, 895.784),
        (895.844, 900.864),
    ]
    assert "laughs" not in transcript.normalized


def test_short_last_caption_joins_previous_but_does_not_reach_across_a_long_gap():
    rows = parse_subtitles(
        caption_srt(captions([event(1000, 3000, "That is all."), event(3000, 3020, "Yes.")]), 4)
    )
    assert rows == [("Narrator", "That is all. Yes.", 1, 3.02)]
    with pytest.raises(PracticeError, match="無法與相鄰字幕合併"):
        caption_srt(captions([event(1000, 1020, "Yes."), event(10000, 12000, "Next topic.")]), 13)


@pytest.mark.parametrize(
    "payload",
    [
        b"not JSON",
        b"[]",
        b"{}",
        b'{"events": []}',
        captions([event(0, 1000, "Hello"), event(-1, 1000, "Invalid")]),
    ],
)
def test_malformed_captions_fail_without_a_practice(payload):
    with pytest.raises(PracticeError, match="字幕內容或時間格式無效"):
        caption_srt(payload, 10)


@pytest.fixture
def fake_downloader(monkeypatch):
    state = {
        "info": {
            "id": VIDEO_ID,
            "title": "An English video",
            "duration": 10,
            "subtitles": {"en": [track()]},
        },
        "payload": captions([event(0, 2000, "Hello, world.")]),
        "audio_downloads": 0,
        "video_downloads": 0,
    }

    class Downloader:
        def __init__(self, options):
            state["options"] = options
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            assert url == URL and download is False
            return state["info"]

        def urlopen(self, url):
            assert url == track()["url"]
            if state.get("caption_error"):
                raise state["caption_error"]
            return io.BytesIO(state["payload"])

        def process_ie_result(self, info, download):
            assert info["id"] == VIDEO_ID and download is True
            if self.options["postprocessors"]:
                state["audio_downloads"] += 1
                template = self.options["outtmpl"].replace("%(ext)s", "mp3")
                Path(template).write_bytes(b"MP3 fixture")
            else:
                state["video_downloads"] += 1
                if not state.get("skip_video"):
                    template = self.options["outtmpl"].replace("%(ext)s", "mp4")
                    Path(template).write_bytes(b"MP4 fixture")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    return state


def test_import_preserves_captions_and_source_before_downloading_audio(tmp_path, fake_downloader):
    audio, transcript, source = download_youtube(Runtime(tmp_path / "runtime"), URL, tmp_path)
    assert audio.read_bytes() == b"MP3 fixture"
    assert "Hello, world." in transcript.read_text()
    assert source["url"] == URL and source["automatic_captions"] is False
    assert json.loads((tmp_path / "source.json").read_text()) == source
    assert (tmp_path / "captions.json").read_bytes() == fake_downloader["payload"]
    assert fake_downloader["audio_downloads"] == 1
    assert fake_downloader["options"]["noplaylist"] is True


def test_video_is_downloaded_only_when_selected_without_changing_source_identity(
    tmp_path, fake_downloader
):
    _, _, original = download_youtube(Runtime(tmp_path / "runtime"), URL, tmp_path)
    assert fake_downloader["video_downloads"] == 0
    _, _, with_video = download_youtube(
        Runtime(tmp_path / "runtime"), URL, tmp_path, include_video=True
    )
    assert fake_downloader["video_downloads"] == 1
    assert (tmp_path / "video.mp4").read_bytes() == b"MP4 fixture"
    assert {k: v for k, v in original.items() if k != "imported"} == {
        k: v for k, v in with_video.items() if k != "imported"
    }
    assert fake_downloader["options"]["merge_output_format"] == "mp4"


def test_missing_video_is_reported_as_failure(tmp_path, fake_downloader):
    fake_downloader["skip_video"] = True
    with pytest.raises(PracticeError, match="沒有取得完整的 MP4"):
        download_youtube(Runtime(tmp_path / "runtime"), URL, tmp_path, include_video=True)


@pytest.mark.parametrize("value", ["true", 1, None, []])
def test_video_option_requires_a_boolean(value):
    with pytest.raises(PracticeError, match="布林值"):
        youtube_request({"url": URL, "download_video": value})


def test_reuses_downloaded_inputs_and_regenerates_captions_without_network(tmp_path, monkeypatch):
    (tmp_path / "audio.mp3").write_bytes(b"existing MP3")
    (tmp_path / "video.mp4").write_bytes(b"existing video")
    raw = captions([event(1000, 1700, "[Laughs] Yes."), event(1020, 3000, "A new topic.")])
    (tmp_path / "captions.json").write_bytes(raw)
    (tmp_path / "transcript.srt").write_text("original transcript retained")
    source = {"provider": "youtube", "url": URL, "title": "Original", "imported": "original-time"}
    (tmp_path / "source.json").write_text(json.dumps(source))
    monkeypatch.setattr(
        "podcast_practice.youtube.subprocess.run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps({"format": {"duration": "4"}})),
    )

    def no_network(*_args, **_kwargs):
        raise AssertionError("Saved inputs must not access YouTube")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", no_network)
    audio, transcript, metadata = reuse_youtube_source(
        Runtime(tmp_path / "runtime"), URL, tmp_path, include_video=True
    )
    assert audio.read_bytes() == b"existing MP3"
    assert (tmp_path / "video.mp4").read_bytes() == b"existing video"
    assert (tmp_path / "transcript.srt").read_text() == "original transcript retained"
    assert (tmp_path / "captions.json").read_bytes() == raw
    assert "Yes. A new topic." in transcript.read_text()
    assert metadata["imported"] == "original-time" and metadata["caption_revision"] == 3
    assert json.loads((tmp_path / "source.json").read_text()) == source


def test_saved_inputs_from_another_video_are_not_reused(tmp_path):
    (tmp_path / "audio.mp3").write_bytes(b"audio")
    (tmp_path / "captions.json").write_bytes(b"{}")
    (tmp_path / "source.json").write_text(json.dumps({"provider": "youtube", "url": "different"}))
    with pytest.raises(CachedDownloadError):
        reuse_youtube_source(Runtime(tmp_path / "runtime"), URL, tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"subtitles": {}},
        {"language": "fr"},
        {"duration": 10801},
        {"live_status": "is_live"},
        {"live_status": "is_upcoming"},
        {"_type": "playlist"},
    ],
)
def test_unavailable_sources_do_not_download_audio(tmp_path, fake_downloader, changes):
    fake_downloader["info"].update(changes)
    with pytest.raises(PracticeError):
        download_youtube(Runtime(tmp_path / "runtime"), URL, tmp_path)
    assert fake_downloader["audio_downloads"] == 0
    assert not (tmp_path / "audio.mp3").exists()


@pytest.mark.parametrize("payload", [b"invalid", b"x" * (MAX_CAPTION_BYTES + 1)])
def test_invalid_or_oversized_captions_do_not_download_audio(tmp_path, fake_downloader, payload):
    fake_downloader["payload"] = payload
    with pytest.raises(PracticeError):
        download_youtube(Runtime(tmp_path / "runtime"), URL, tmp_path)
    assert fake_downloader["audio_downloads"] == 0


def test_caption_network_failure_has_actionable_error_and_no_audio(tmp_path, fake_downloader):
    from yt_dlp.networking.exceptions import TransportError

    fake_downloader["caption_error"] = TransportError("Connection timed out")
    with pytest.raises(PracticeError, match="YouTube 匯入失敗"):
        download_youtube(Runtime(tmp_path / "runtime"), URL, tmp_path)
    assert fake_downloader["audio_downloads"] == 0


def test_download_size_limit_aborts_in_progress_downloads(tmp_path, fake_downloader):
    from podcast_practice.youtube import MAX_DOWNLOAD_BYTES

    download_youtube(Runtime(tmp_path / "runtime"), URL, tmp_path)
    hook = fake_downloader["options"]["progress_hooks"][0]
    with pytest.raises(PracticeError, match="超過 512 MB"):
        hook({"downloaded_bytes": MAX_DOWNLOAD_BYTES + 1})


def test_youtube_cli_uses_normal_offline_build_and_writes_result_only_on_success(
    tmp_path, fake_downloader, monkeypatch
):
    monkeypatch.setattr(Runtime, "require_ready", lambda self: None)
    observed = []
    destination = tmp_path / "library" / "episode"

    def build(runtime, options):
        observed.append(options)
        return destination

    monkeypatch.setattr(cli, "build", build)
    result = tmp_path / "result.json"
    args = [
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "youtube",
        URL,
        "--source-dir",
        str(tmp_path),
        "--library",
        str(tmp_path / "library"),
        "--result-json",
        str(result),
    ]
    assert cli.main(args) == 0
    options = observed[0]
    assert options.title == "An English video"
    assert options.offline is True and options.no_asr is False
    assert options.force is False and options.allow_low_confidence is False
    assert options.media_source["provider"] == "youtube"
    assert json.loads(result.read_text())["directory"] == str(destination)
    result.unlink()
    fake_downloader["info"]["subtitles"] = {}
    assert cli.main(args) == 2
    assert not result.exists()


def test_import_title_validation_and_player_caption_label():
    with pytest.raises(PracticeError):
        youtube_request({"url": URL, "title": "bad\ntitle"})
    assert youtube_request({"url": URL})["title"] == ""
    page = player_html(
        {"title": "YT", "media_source": {"provider": "youtube", "automatic_captions": True}},
        "audio.mp3",
    )
    assert "YouTube 英文自動字幕（可能有辨識錯誤）" in page
