"""Import one public YouTube video's English captions and audio for local practice."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .errors import PracticeError
from .render import render_player, timestamp, update_library
from .runtime import Runtime
from .transcript import parse_transcript, spoken_tokens

MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_CAPTION_BYTES = 5 * 1024 * 1024
MAX_DURATION = 3 * 60 * 60
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
CAPTION_REVISION = 3
CAPTION_EVENT = re.compile(
    r"\[(?:music|laugh(?:ter|ing|s)?|applause|silence|inaudible|crosstalk|"
    r"clears? throat|snorts?|sighs?|cheering|sound)[^\]]*\]",
    re.I,
)


def caption_intervals(cues: list[list]) -> list[list]:
    """Keep clipped speaker interjections with adjacent speech, using source time bounds."""

    def too_short(cue: list) -> bool:
        words = sum(len(spoken_tokens(w, caption_style=True)) for w in cue[2].split())
        return cue[1] - cue[0] < max(0.35, words * 0.08)

    result: list[list] = []
    index = 0
    while index < len(cues):
        cue = list(cues[index])
        index += 1
        while too_short(cue):
            if (
                index < len(cues)
                and cues[index][0] - cue[1] <= 0.5
                and cues[index][1] - cue[0] <= 20
            ):
                following = cues[index]
                cue = [cue[0], following[1], cue[2] + " " + following[2]]
                index += 1
            elif result and cue[0] - result[-1][1] <= 0.5 and cue[1] - result[-1][0] <= 20:
                previous = result.pop()
                cue = [previous[0], cue[1], previous[2] + " " + cue[2]]
            else:
                raise PracticeError(
                    f"字幕在 {timestamp(cue[0])}–{timestamp(cue[1])} 的語音範圍過短，"
                    "且無法與相鄰字幕合併；請修正字幕時間後重試。"
                )
        result.append(cue)
    return result


class CachedDownloadError(PracticeError):
    """Saved downloads are unavailable or invalid, so a fresh download is needed."""


def reuse_youtube_source(
    runtime: Runtime, url: str, folder: Path, *, include_video: bool = False
) -> tuple[Path, Path, dict]:
    """Rebuild captions from saved JSON3 while retaining the original downloaded inputs."""
    url = youtube_url(url)
    names = {
        "audio.mp3": MAX_DOWNLOAD_BYTES,
        "captions.json": MAX_CAPTION_BYTES,
        "source.json": 64 * 1024,
    }
    if include_video:
        names["video.mp4"] = MAX_VIDEO_BYTES
    try:
        if folder.is_symlink() or any(
            (folder / name).is_symlink()
            or not (folder / name).is_file()
            or not 0 < (folder / name).stat().st_size <= limit
            for name, limit in names.items()
        ):
            raise ValueError("Incomplete saved download")
        source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
        if (
            not isinstance(source, dict)
            or source.get("provider") != "youtube"
            or source.get("url") != url
        ):
            raise ValueError("Saved source belongs to a different video")
        audio = folder / "audio.mp3"
        result = subprocess.run(
            [
                str(runtime.ffprobe),
                "-v",
                "error",
                "-f",
                "mp3",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(audio),
            ],
            env=runtime.environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=True,
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION + 2:
            raise ValueError("Invalid saved audio duration")
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise CachedDownloadError("已下載檔案未通過完整性檢查。") from exc
    transcript = folder / f"transcript-v{CAPTION_REVISION}.srt"
    temporary = transcript.with_suffix(".srt.tmp")
    try:
        converted = caption_srt((folder / "captions.json").read_bytes(), duration)
    except PracticeError as exc:
        if isinstance(exc.__cause__, (ValueError, KeyError, TypeError, AttributeError)):
            raise CachedDownloadError("已下載的字幕內容無效。") from exc
        raise
    temporary.write_text(converted, encoding="utf-8")
    temporary.replace(transcript)
    parse_transcript(transcript, caption_style=True)
    source["caption_revision"] = CAPTION_REVISION
    (folder / f"source-v{CAPTION_REVISION}.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("YouTube：重用已下載的音訊、字幕" + ("與影片。" if include_video else "。"), flush=True)
    return audio, transcript, source


def youtube_url(value: str) -> str:
    """Accept video links only; discard playlist, timestamp and tracking parameters."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise PracticeError("請輸入有效的 YouTube 影片網址。")
    value = value.strip()
    if any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        raise PracticeError("請輸入有效的 YouTube 影片網址。")
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
        ):
            raise ValueError("Invalid URL")
        host = parsed.hostname
        if host == "youtu.be":
            identifier = parsed.path.removeprefix("/")
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if parsed.path == "/watch":
                videos = parse_qs(parsed.query).get("v", [])
                identifier = videos[0] if len(videos) == 1 else ""
            else:
                match = re.fullmatch(r"/(?:shorts|embed|live)/([\w-]{11})/?", parsed.path)
                identifier = match[1] if match else ""
        else:
            identifier = ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier):
            raise ValueError("Invalid video ID")
    except ValueError as exc:
        raise PracticeError("請貼上單支 YouTube 影片網址（watch、youtu.be 或 Shorts）。") from exc
    return f"https://www.youtube.com/watch?v={identifier}"


def youtube_request(data: dict) -> dict:
    if not isinstance(data, dict):
        raise PracticeError("請求內容必須是 JSON 物件。")
    title = data.get("title", "")
    if not isinstance(title, str) or len(title) > 200 or any(ord(c) < 32 for c in title):
        raise PracticeError("集數名稱需為 200 字以內的單行文字。")
    video = data.get("download_video", False)
    if type(video) is not bool:
        raise PracticeError("下載影片選項必須是核取方塊的布林值。")
    return {"url": youtube_url(data.get("url")), "title": title.strip(), "download_video": video}


def english_caption(info: dict) -> tuple[str, bool, dict]:
    """Prefer uploaded English tracks, then native English ASR; exclude auto translations."""
    for automatic, key in ((False, "subtitles"), (True, "automatic_captions")):
        tracks = info.get(key) or {}
        languages = sorted(tracks, key=lambda lang: (lang != "en", lang != "en-orig", lang))
        for language in languages:
            if not re.fullmatch(r"en(?:-[A-Za-z0-9]+)*", language):
                continue
            for track in tracks[language]:
                address = urlsplit(track.get("url", ""))
                if (
                    track.get("ext") == "json3"
                    and "tlang" not in parse_qs(address.query)
                    and address.scheme == "https"
                    and address.hostname in {"www.youtube.com", "youtube.com"}
                ):
                    return language, automatic, track
    raise PracticeError(
        "這支影片沒有可取得的英文字幕。請選擇有英文字幕或英文自動字幕的影片，"
        "也可以改用 MP3 與英文原稿上傳。"
    )


def caption_srt(payload: bytes, duration: float) -> str:
    """Convert JSON3 cues, removing overlapping roll-up repeats while retaining cue timing."""
    try:
        data = json.loads(payload)
        events = data["events"]
        if not isinstance(events, list):
            raise ValueError("Invalid events")
        cues: list[list] = []
        previous_words: list[str] = []
        previous_end = 0.0
        previous_start = -1.0
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("Invalid caption event")
            if not event.get("segs"):
                continue  # Window/style events contain no spoken text.
            start = float(event["tStartMs"]) / 1000
            end = min(duration, start + float(event.get("dDurationMs", 0)) / 1000)
            if not math.isfinite(start) or not math.isfinite(end) or start < previous_start:
                raise ValueError("Invalid caption time")
            previous_start = start
            if start < 0 or end <= start:
                continue
            text = "".join(segment.get("utf8", "") for segment in event["segs"])
            text = html.unescape(re.sub(r"<[^>]*>", "", text))
            text = re.sub(r"(?:^|\s)>>+\s*", " ", text)
            text = CAPTION_EVENT.sub(" ", text)
            words = text.split()
            if not words:
                continue  # ASR append/newline events must not reset the roll-up history.
            original = words[:]
            if start < previous_end:
                for count in range(min(len(previous_words), len(words)), 0, -1):
                    if previous_words[-count:] == words[:count]:
                        words = words[count:]
                        break
            previous_words, previous_end = original, end
            if not words:
                continue
            if cues and cues[-1][1] > start:
                if start <= cues[-1][0]:
                    # Same-start roll-up updates belong to the same cue.
                    cues[-1][1] = max(cues[-1][1], end)
                    cues[-1][2] += " " + " ".join(words)
                    continue
                cues[-1][1] = start
            cues.append([start, end, " ".join(words)])
        if not cues:
            raise ValueError("Empty captions")
        return (
            "\n\n".join(
                f"{index}\n{timestamp(start, comma=True)} --> {timestamp(end, comma=True)}\n{text}"
                for index, (start, end, text) in enumerate(caption_intervals(cues), 1)
            )
            + "\n"
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PracticeError("英文字幕內容或時間格式無效，無法建立練習。") from exc


def download_youtube(
    runtime: Runtime, url: str, folder: Path, *, include_video: bool = False
) -> tuple[Path, Path, dict]:
    # Import lazily so file-only workflows and help remain lightweight.
    from yt_dlp import YoutubeDL
    from yt_dlp.networking.exceptions import RequestError
    from yt_dlp.utils import DownloadError

    url = youtube_url(url)
    folder.mkdir(parents=True, exist_ok=True)
    audio, transcript = folder / "audio.mp3", folder / "transcript.srt"

    def progress(status: dict) -> None:
        if status.get("downloaded_bytes", 0) > MAX_DOWNLOAD_BYTES:
            raise PracticeError("YouTube 音訊超過 512 MB，請選擇較短的影片。")

    options = {
        "format": (
            "bestaudio[language^=en][ext=m4a]/bestaudio[language^=en]/bestaudio[ext=m4a]/bestaudio"
        ),
        "outtmpl": str(folder / "audio.%(ext)s"),
        "noplaylist": True,
        "allowed_extractors": ["youtube"],
        "socket_timeout": 20,
        "retries": 2,
        "extractor_retries": 2,
        "fragment_retries": 2,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        "cachedir": False,
        "noprogress": True,
        "progress_hooks": [progress],
        "ffmpeg_location": str(runtime.bin),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}
        ],
        "extractor_args": {"youtube": {"skip": ["translated_subs"]}},
    }
    runtimes = {name: {"path": path} for name in ("deno", "node") if (path := shutil.which(name))}
    if runtimes:
        options["js_runtimes"] = runtimes
    try:
        with YoutubeDL(options) as downloader:
            print("YouTube：讀取影片與英文字幕…", flush=True)
            info = downloader.extract_info(url, download=False)
            if not info or info.get("_type", "video") != "video":
                raise PracticeError("每次只支援匯入一支 YouTube 影片。")
            if info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
                raise PracticeError("直播中或尚未處理完成的影片無法匯入，請選擇已完成的影片。")
            spoken_language = info.get("language")
            if spoken_language and not re.fullmatch(r"en(?:-[A-Za-z0-9]+)*", spoken_language):
                raise PracticeError("這支影片的音訊語言不是英文，請選擇英文發音的影片。")
            duration = info.get("duration")
            if not isinstance(duration, (float, int)) or not 0 < duration <= MAX_DURATION:
                raise PracticeError("目前支援長度在 3 小時內、可取得完整音訊的 YouTube 影片。")
            language, automatic, track = english_caption(info)
            label = "英文自動字幕（可能有辨識錯誤）" if automatic else "英文字幕"
            print(f"YouTube 字幕：{label} · {language}", flush=True)
            with downloader.urlopen(track["url"]) as response:
                payload = response.read(MAX_CAPTION_BYTES + 1)
            if len(payload) > MAX_CAPTION_BYTES:
                raise PracticeError("YouTube 字幕超過 5 MB，請選擇較短的影片。")
            (folder / "captions.json").write_bytes(payload)
            transcript.write_text(caption_srt(payload, duration), encoding="utf-8")
            parse_transcript(transcript, caption_style=True)
            video_info = deepcopy(info) if include_video else None
            print("YouTube 音訊：下載並轉換 MP3…", flush=True)
            downloader.process_ie_result(info, download=True)
        if not audio.is_file() or not 0 < audio.stat().st_size <= MAX_DOWNLOAD_BYTES:
            raise PracticeError("沒有取得完整的 YouTube 音訊，請查看紀錄後重試。")
        if include_video:
            downloaded: dict[str, int] = {}

            def video_progress(status: dict) -> None:
                name = status.get("filename", "video")
                downloaded[name] = max(downloaded.get(name, 0), status.get("downloaded_bytes", 0))
                if sum(downloaded.values()) > MAX_VIDEO_BYTES:
                    raise PracticeError("影片下載超過 2 GB，請選擇較短的影片或取消下載影片。")

            video_options = {
                **options,
                "format": (
                    "bestvideo[ext=mp4][vcodec^=avc1][height<=720]+"
                    "bestaudio[ext=m4a][language^=en]/"
                    "bestvideo[ext=mp4][vcodec^=avc1][height<=720]+bestaudio[ext=m4a]/"
                    "best[ext=mp4][vcodec^=avc1][height<=720]"
                ),
                "outtmpl": str(folder / "video.%(ext)s"),
                "merge_output_format": "mp4",
                "max_filesize": MAX_VIDEO_BYTES,
                "postprocessors": [],
                "progress_hooks": [video_progress],
            }
            print("YouTube 影片：下載最高 720p MP4…", flush=True)
            with YoutubeDL(video_options) as downloader:
                downloader.process_ie_result(video_info, download=True)
            video = folder / "video.mp4"
            if not video.is_file() or not 0 < video.stat().st_size <= MAX_VIDEO_BYTES:
                raise PracticeError("沒有取得完整的 MP4 影片，請查看紀錄或取消下載影片後重試。")
    except DownloadError as exc:
        raise PracticeError(
            "無法取得 YouTube 影片、字幕或音訊。影片可能需要登入、受到地區限制，"
            "或 YouTube 暫時拒絕連線；請確認影片可公開播放後重試。"
            f"\n詳細原因：{exc}"
        ) from exc
    except (OSError, ValueError, RequestError) as exc:
        raise PracticeError(f"YouTube 匯入失敗，請稍後重試。詳細原因：{exc}") from exc
    source = {
        "provider": "youtube",
        "url": url,
        "video_id": info["id"],
        "title": " ".join(str(info.get("title") or info["id"]).split())[:200],
        "channel": info.get("channel") or info.get("uploader"),
        "caption_language": language,
        "automatic_captions": automatic,
        "caption_revision": CAPTION_REVISION,
        "imported": datetime.now(timezone.utc).isoformat(),
    }
    (folder / "source.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return audio, transcript, source


def attach_video(runtime: Runtime, episode: Path, video: Path) -> None:
    """Attach a validated MP4 without changing alignment or the audio progress identity."""
    data = json.loads((episode / "alignment.json").read_text(encoding="utf-8"))
    try:
        result = subprocess.run(
            [
                str(runtime.ffprobe),
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "stream=codec_type,codec_name,height:format=duration",
                "-of",
                "json",
                str(video),
            ],
            env=runtime.environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=True,
        )
        probe = json.loads(result.stdout)
        streams = probe["streams"]
        duration = float(probe["format"]["duration"])
        pictures = [s for s in streams if s.get("codec_type") == "video"]
        sound = [s for s in streams if s.get("codec_type") == "audio"]
        if (
            not pictures
            or pictures[0].get("codec_name") != "h264"
            or not sound
            or sound[0].get("codec_name") != "aac"
            or not math.isfinite(duration)
            or duration <= 0
            or abs(duration - data["duration"]) > 2
        ):
            raise ValueError("Video format or duration does not match audio")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        raise PracticeError("影片格式無效或長度與練習音訊不一致，請查看紀錄後重試。") from exc
    target = episode / "video.mp4"
    temporary = episode / "video.mp4.tmp"
    shutil.copyfile(video, temporary)
    temporary.replace(target)
    with target.open("rb") as content:
        digest = hashlib.file_digest(content, "sha256").hexdigest()
    data["video"] = {
        "file": "video.mp4",
        "sha256": digest,
        "duration": duration,
        "height": pictures[0].get("height"),
    }
    render_player(data, episode / "audio.mp3", episode / "player.html")
    manifest = episode / "alignment.json.tmp"
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest.replace(episode / "alignment.json")
    update_library(episode.parent)
    print("YouTube 影片：已加入練習播放器。", flush=True)
