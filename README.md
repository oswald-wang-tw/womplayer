# Podcast Practice

Turn English podcasts and their transcripts into offline listening practice with
**uv + Montreal Forced Aligner (MFA)**. The player supports click-to-seek sentences,
word highlighting, slower playback, sentence looping, pausing at sentence boundaries,
transcript hiding, search, and keyboard shortcuts.

Each audio-only episode produces a portable `player.html` with embedded audio,
SRT/VTT subtitles, word timestamps in JSON, and a TextGrid. Optional video players
use a `video.mp4` file beside the HTML; keep both files together for offline use.
All audio analysis runs locally, with no SaaS,
API keys, or subscriptions. Network access is needed for the initial setup, model
downloads, and importing videos from YouTube. Finished players work offline.

## Initial setup

Automatic setup supports **Linux x86_64** (Ubuntu 22.04/24.04 or a compatible
distribution is recommended), **Windows 10/11 x86_64**, and macOS 14 or later on
Intel and Apple Silicon. Linux ARM and Windows ARM are not supported by automatic
setup; the tool reports an unsupported platform instead of attempting to install
incompatible packages.

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git.
2. Clone the repository and set up the local runtime:

```sh
git clone https://github.com/oswald-wang-tw/podcast-practice.git
cd podcast-practice
uv sync --locked
uv run podcast-practice setup
uv run podcast-practice doctor
```

On Windows, run the same setup commands in **PowerShell**. Automatic setup uses
the official `win-64` micromamba package and the Windows Conda executable/DLL
layout, following the [official micromamba installation documentation](https://mamba.readthedocs.io/en/stable/installation/micromamba-installation.html).
WSL and an activated Conda shell are not required. Paths with spaces or
Chinese characters are supported; quote paths containing spaces:

```powershell
uv run podcast-practice build "C:\Podcasts\today.mp3" "C:\Podcasts\today.txt" --title "Today's episode" --offline --open
uv run podcast-practice serve --open
```

The multi-line `sh` examples below use Unix shell continuations (`\`). In
PowerShell, enter the command on one line or use a backtick (`` ` ``) at the end
of each continued line.

The coarse-alignment engine also requires the Windows Visual C++ runtime,
which is already installed on many computers. If it reports a missing runtime
DLL, install the x64 runtime linked in the
[CTranslate2 installation guide](https://opennmt.net/CTranslate2/installation.html).

You can also transfer an exported Git bundle to another computer:

```sh
git clone /path/to/podcast-practice.bundle podcast-practice
cd podcast-practice
uv sync --locked
uv run podcast-practice setup
```

**You do not need to install Python, Conda, or ffmpeg separately.** uv manages Python
and the project's Python dependencies. `setup` downloads the official micromamba
2.9.0 binary, creates an isolated MFA 3.4.2 environment with Kaldi and ffmpeg under
`.runtime/`, and downloads the English MFA/G2P models and the local `base.en` model
used for coarse alignment.

MFA's native dependencies cannot be installed with `uv pip install` alone. This
repository manages that environment without modifying system Python or requiring
you to activate Conda for daily use. See the
[official MFA installation guide](https://montreal-forced-aligner.readthedocs.io/en/latest/installation.html).

Allow several GB of disk space for the initial setup. Download and installation
times depend on your connection and computer; subsequent runs reuse the models.

## Daily use

Save an audio file and its UTF-8 transcript, then run:

```sh
uv run podcast-practice build /path/to/today.mp3 /path/to/today.txt \
  --title "Today's episode" --offline --open
```

Use a different pair of files for the next episode, without changing the code:

```sh
uv run podcast-practice build /path/to/another.m4a /path/to/another.txt \
  --title "Another podcast" --offline --open
```

- Audio: MP3, M4A, WAV, FLAC, and other formats supported by ffmpeg.
- Transcripts: English `.txt` or `.md`, or timestamped `.srt` or `.vtt` files.
  Markdown support covers text paragraphs and headings, not complex formatting.
- `--offline` prevents coarse-alignment model downloads. Install the MFA models with
  `setup` first. Inference always runs locally.
- Each episode gets a directory identified by a content fingerprint. Different
  inputs create a new episode; rerunning the same inputs reuses completed results.
- `--open` opens the finished player in your default browser. You can also open the
  generated HTML directly, without a server.

Browse your practice library:

```sh
uv run podcast-practice serve --open
```

The server listens only on `127.0.0.1:8766`. Press Ctrl+C to stop it. Individual
players remain usable offline after the server stops. Commands use `library/` in
the current working directory by default; run them from the repository directory
to use the same library.

## Add episodes from the browser

Run `uv run podcast-practice serve --open` and use the **Add an episode** area at
the top of the library. Drag an MP3 and its English transcript onto either file
box, or click the boxes to choose files. You can drop both files together or add
them one at a time. Enter an episode title, or use the audio filename as the title,
then click the add button.

- MP3 files: up to 512 MiB locally, or 90 MiB through an enabled public origin.
- UTF-8 transcripts: `.txt`, `.md`, `.srt`, or `.vtt`, up to 5 MiB.
- Files are stored on the computer running the server. Website uploads pass
  through the existing reverse proxy. Copies and build logs are retained under
  `library/.uploads/`; this directory is not served over HTTP.
- The existing offline MFA pipeline builds the player in the library served by the
  current command, using the runtime selected with `--runtime-dir`. Run `setup`
  before uploading; the browser does not install tools or download models.
- The page shows upload progress, then the current build stage and an expandable
  build log. Builds run in the background, one at a time. Reloading the page
  reconnects to the latest job.
- On success, the episode list updates and a link opens the finished player. On
  failure, correct the inputs or runtime issue and retry. Stopping the server also
  stops its active build; the inputs and logs remain available for diagnosis.

Browser uploads require the local server. Opening `index.html` through `file://`
disables uploading. Restart a server started before this feature was added to
enable its new upload endpoints.

## Add practice from a YouTube URL

Update dependencies with `uv sync --locked`, restart `uv run podcast-practice serve
--open`, and paste a video link into **YouTube 影片網址** at the top of the library.
The title is optional; leaving it empty uses the video's title. Click **從 YouTube
新增** to import the captions and audio and build the practice player in the
background. Progress and logs use the same area as file uploads, and reloading
reconnects to the current job. Only one upload/import/build runs at a time.

Select **同時下載影片，在逐字稿旁同步播放** to also download a video, up to 720p
and 2 GiB. This is unchecked by default. The finished player shows video beside
the transcript on desktop and above it on smaller screens. Video sound, word
highlighting, transcript/time jumps, sentence looping, sentence-end pauses,
playback speed and saved progress share the same video playback timeline. The
video's native controls also update transcript highlighting and playback progress.
Downloading video uses additional time and disk space; inputs and finished outputs
each retain a copy. Existing audio-only imports continue to work as before.

You can also import from the command line:

```sh
uv run podcast-practice youtube 'https://www.youtube.com/watch?v=VIDEO_ID' --open

# Include an MP4 video
uv run podcast-practice youtube 'https://www.youtube.com/watch?v=VIDEO_ID' --download-video --open
```

- Supports single-video `youtube.com/watch`, `youtu.be`, Shorts, embed and completed
  live-video links. A playlist parameter on a video link is ignored; playlist-only
  links are rejected. Start-time parameters are ignored: the full video is imported.
- Prefers uploaded English captions, then English automatic captions. Automatic
  translations from other languages are excluded. Automatic captions are labeled
  in the player because they can contain recognition errors.
- Requires English speech, publicly accessible audio and English captions. Missing captions,
  access restrictions and failed downloads produce an error; no finished practice
  is reported. Active/upcoming livestreams and videos longer than 3 hours are
  rejected. Downloaded audio is limited to 512 MiB, captions to 5 MiB.
- Caption timing is retained as the normal SRT input to MFA. Overlapping roll-up
  captions are cleaned to avoid repeated text. Speaker arrows and non-speech
  markers such as `[laughter]`, `[laughs]` and `[clears throat]` are excluded from spoken text.
  When overlapping captions leave an extremely short speech fragment, it is
  joined to nearby captions within their original time bounds. All spoken words
  remain in the transcript; isolated fragments that cannot be joined produce a
  timestamped error instead of an unusable alignment window.
  Uppercase caption words retain their displayed spelling while ordinary words
  are aligned as speech rather than spelled out letter by letter; common
  initialisms such as BBC and U.S. retain their spelling pronunciation.
  Final word timing comes from the
  existing local MFA pipeline, with its review warnings preserved. Speech that
  has no source caption is not supplied with invented text.
- Uses [yt-dlp](https://github.com/yt-dlp/yt-dlp), installed by `uv sync --locked`,
  and the existing runtime's ffmpeg. YouTube also needs an available **Node.js 22+
  or Deno 2.3+** on the server's `PATH`; both are detected automatically. The EJS
  scripts are included in the Python dependencies. See the
  [official JavaScript runtime guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
- Source captions, converted SRT, audio and source metadata are retained under
  `library/.uploads/`. This directory is not served over HTTP. The finished
  `alignment.json` records the video URL, title, channel and caption type.
- `--title` and `--library` work with the `youtube` command. Importing needs network
  access, while model inference and the finished player remain local/offline.
- Adding video to identical inputs reuses the completed MFA alignment and keeps
  the existing audio identity used for browser playback progress. An episode that
  already has a video retains it when importing the same inputs without the flag.
  For a video episode, copy `player.html` and `video.mp4` together for offline use.
- Retrying a failed YouTube import reuses complete saved audio, captions and video
  instead of downloading them again. Captions are regenerated using the current
  converter, and the original downloads/transcript/logs are retained. Invalid or
  missing downloads are fetched again. A new import after a completed job can
  refresh the online source. MFA errors identify the failed segment, its time
  range and text, with full details in `mfa.log` and `alignment-failure.json`.

If you already serve the library through a trusted reverse proxy, explicitly allow
that site's origin when starting the local server:

```sh
uv run podcast-practice serve --public-origin https://podcast.oswaldwang.com
```

The server still binds to loopback. Uploads require the page's request token and
an allowed origin; other origins are rejected. The public origin enables uploads;
trash management retains its local origin restrictions. Keep the authentication
and access restrictions of your existing reverse proxy in place. This deployment
uses its existing Cloudflare Access login.

Local uploads accept MP3 files up to 512 MiB. The public website accepts MP3 files
up to 90 MiB, with a 5 MiB transcript limit, so each request stays below the
reverse proxy's usual 100 MB request limit. Larger MP3 files can be added locally
and will appear in the same library on the website.

## Keyboard shortcuts

The player and library both have a shortcut-help button. Press `?` to open the
shortcut list and `Esc` to close it. Letter shortcuts do not require Shift.

| Player shortcut | Action |
| --- | --- |
| Space | Play / pause |
| Left / Right arrow | Previous / next sentence |
| Shift + Left / Right arrow | Seek backward / forward by 5 seconds |
| `R` | Replay the selected sentence |
| `[` / `]` | Decrease / increase playback speed |
| `L` | Toggle sentence looping |
| `P` | Toggle pausing at the end of a sentence |
| `F` | Toggle automatic transcript following |
| `H` | Hide / show the full transcript |
| `V` | Reveal / hide the current sentence while the transcript is hidden |
| `/` | Focus search and select the current search text |
| `Esc` in search | Clear the search and leave the search field |
| `?` | Open the shortcut list |

In the library, use Up / Down arrow to select an episode, Home / End to move to the
first / last episode, and Enter to open the selected episode. These navigation
shortcuts work when focus is on the page or an episode link.

Tab moves between controls. Space activates a focused button. Shortcuts leave text
input, form controls, input-method composition, and Ctrl / Alt / Command
combinations to their normal behavior. Holding a toggle key changes the option
only once; navigation, seeking, and speed shortcuts can repeat.

Update an existing episode's player without rerunning alignment:

```sh
uv run podcast-practice render library/episode-name-xxxxxxxx
```

The library server renders a lightweight version at the same `player.html` URL,
with audio loaded from the episode's `audio.mp3` using byte-range requests. This
avoids parsing a large embedded audio string when listening to long episodes or
seeking far into them. The exported `player.html` still embeds the complete audio
for single-file offline use. Playback updates only changed highlights and controls;
off-screen sentence contents skip layout in browsers supporting `content-visibility`.

## Browser playback progress

Each episode automatically saves its last playback position in this browser.
Reopening the player restores that position after the audio metadata loads and
leaves playback paused; press Play to continue. The library shows the last position
and its percentage of the episode, or that playback reached the end. **從頭開始**
in the player resets only that episode to the beginning and leaves it paused.

Progress is saved about every two seconds during playback, and immediately when
pausing, finishing a seek, reaching the end, hiding the page, or leaving it. Episodes
use their audio identity, so identical titles stay independent and regenerating a
player keeps its progress. Older exports without an audio identity use their
fingerprint or page path instead.

Records live in browser `localStorage`; they are not synced between devices,
browser profiles, or website origins (including different hostnames or ports).
Clearing site data clears progress. Direct `file://` playback depends on the
browser's local-file storage support; use the library server for consistent storage.
If storage is blocked or full, the player explains that saving is unavailable and
continues to play normally.

Update portable players with the `render` command above. Restart an existing
library server after updating the application, then refresh the player and library.

## Delete and restore episodes

Each episode in the library has a delete button. After deletion, use the undo
button or expand the trash section to restore it. Restoration remains available
after reloading the page or restarting the server.

Deleting an episode moves its entire output directory to `library/.trash/`. It
preserves original audio and transcript inputs, shared models, and alignment
caches. Items in the trash still use disk space. Delete and restore buttons are
disabled when opening `index.html` through `file://`; use `serve` or the CLI:

```sh
uv run podcast-practice delete episode-name-xxxxxxxx
uv run podcast-practice trash
uv run podcast-practice restore <trash-id>
```

Each item in the trash also has a permanent-delete button. Its confirmation dialog
shows the episode title and deletion scope. Confirming permanently removes that
episode's player, audio copy, subtitles, and other outputs; it cannot be restored
from the trash. Original inputs, shared models, and processing caches under
`.runtime/jobs/` are preserved.

The CLI requires an explicit `--yes` to delete an item permanently:

```sh
uv run podcast-practice purge <trash-id> --yes
```

Use `--library /path/to/library` for a custom library. Restoration refuses to
overwrite an existing directory with the same name.

## Transcript format

Plain transcripts do not need timestamps. Use normal English paragraphs, optionally
with speaker headings:

```text
Host
Welcome to today's episode. We will talk about a new idea.

[MUSIC PLAYING]

Alex Taylor
Thanks for having me. Let me explain how it works.

Host: What should listeners try first?
```

Speaker names are detected automatically. If needed, repeat `--speaker "Alex Taylor"`
to specify speakers explicitly.

Markers such as `[MUSIC PLAYING]` and `[AD PLAYING]` are excluded from spoken text.
URLs, Markdown headings, and FT sharing prompts are also skipped. Transcript files
are treated as data; commands or instructions inside them are never executed.

The recording can contain adverts or other audio omitted from the transcript.
Local recognition runs before the first MFA pass. When consecutive matched words
around sentence boundaries identify a long omitted interval, MFA aligns bounded
text blocks and leaves that interval blank. Long gaps between aligned sentences
also remain outside the sentence search windows. The original audio is retained;
no advertising text or placeholder subtitles are invented. The player clears its
active sentence and word highlights during subtitle gaps and resumes highlighting
when the next transcribed sentence begins.

Detected intervals are listed in `review.json` under `untranscribed_audio`. A final
subtitle crossing one of these intervals stops the export for review. Detection
requires matched context; it is not a guarantee that every omission will be found.
Check the surrounding sentences when recognition is uncertain, or when an advert
interrupts a sentence. Final word timestamps still come from MFA.

The displayed transcript preserves the original wording. Alignment input expands
numbers, percentages, years, and uppercase abbreviations into spoken English. If
the recording uses a different pronunciation, write the intended spoken form in
the input transcript. Only English is currently supported.

## Episode outputs

```text
library/
  index.html
  episode-name-xxxxxxxx/
    player.html         # Embedded audio; portable offline practice in one file
    audio.mp3
    transcript.txt
    subtitles.srt
    subtitles.vtt
    alignment.json      # Original text, speakers, word/sentence times, model metadata
    alignment.TextGrid
    review.json         # Segments recommended for manual review
    windows.json        # MFA sentence search windows; can be edited manually
```

Use `--output /path/to/episode` to choose an episode's output directory. Audio,
transcripts, models, `.venv`, processing caches, and libraries are excluded by
`.gitignore`; cloning the repository does not transfer those local files.

## Alignment workflow

1. Preserve the original display text and create normalized English pronunciation
   input.
2. Generate G2P pronunciations only for words missing from the dictionary. Cache
   them across episodes to avoid repeating work.
3. Run an initial MFA alignment over the full episode.
4. Run local faster-whisper recognition and match words to estimate coarse speech
   locations, excluding music, ads, and trailing audio missing from the transcript.
5. Run MFA again within the estimated sentence search windows to produce the final
   word timestamps.
6. Validate word completeness and timestamp ordering, then export the player,
   subtitles, and review report.

For SRT/VTT input, the supplied timestamps define search windows, so coarse
recognition is unnecessary. **Final word timestamps always come from MFA. Coarse
recognition does not replace your transcript.**

You do not need to hardcode music timestamps, speaker lists, or absolute file paths
for each episode. The tool stops and asks you to check the inputs when coarse word
match coverage falls below 35%. If the transcript is deliberately edited, you can
continue with `--allow-low-confidence`.

Automatic alignment can still produce inaccurate word boundaries. The player marks
sentences recommended for review. Missing transcript content, background music,
edited wording, and unusual pronunciations may require manual adjustment.

## Configuration and troubleshooting

Choose a smaller, faster coarse-alignment model:

```sh
uv run podcast-practice setup --asr-model tiny.en
```

`build` uses the model selected during setup by default. Use `--asr-model small.en`
for a larger model; download it before using `--offline`.

Reuse an existing MFA environment and model directories without downloading them
again. These paths are stored locally in `.runtime/config.json`:

```sh
uv run podcast-practice setup --mfa-prefix /path/to/mfa-env \
  --model-dir /path/to/MFA --asr-cache /path/to/asr-cache
```

On Windows, `--mfa-prefix` must point to the environment directory containing
`Scripts\mfa.exe`, `Library\bin\ffmpeg.exe`, and `Library\bin\ffprobe.exe`:

```powershell
uv run podcast-practice setup --mfa-prefix "C:\Tools\mfa-env" --model-dir "C:\Models\MFA" --asr-cache "C:\Models\asr-cache"
```

Use `build ... --no-asr` to skip coarse recognition. Check music and trailing audio
boundaries yourself in that mode. Timestamped SRT/VTT input still uses its supplied
times.

To correct a sentence, copy the episode's `windows.json`, edit its `begin` and `end`
values in seconds, and run:

```sh
uv run podcast-practice build /path/to/today.mp3 /path/to/today.txt \
  --title "Today's episode" --windows /path/to/windows.json --offline
```

You can supply only the entries you want to change, such as
`[{"id": 7, "begin": 41.0, "end": 45.0}]`. Sentence IDs start at 0. Windows must stay
within the audio duration and must not overlap neighboring sentences.

Refresh the player without rerunning alignment:

```sh
uv run podcast-practice render library/episode-name-xxxxxxxx
```

`--force` allows output replacement while preserving computation caches for the same
inputs. To recompute an episode from scratch, move its
`.runtime/jobs/<fingerprint>/` cache directory out of the way before rebuilding.
Failures and Ctrl+C preserve processing caches; detailed logs remain in the job
directory.

## Development and tests

```sh
uv sync --locked --group dev
uv run pytest
uv run ruff check .
```

Tests cover transcript formats, number and speaker parsing, automatic speech
windows, invalid or overlapping windows, original-text preservation, HTML escaping,
player and library keyboard behavior, Windows/Unix runtime installation layouts,
UTF-8 output, and stopping background builds together with their subprocesses.
The regular test suite does not download
speech models or require MFA. Real-audio alignment quality still needs listening
checks on the target machine.

On Windows, the symlink tests require Developer Mode or symlink privileges and
are skipped if those privileges are unavailable. The remaining tests run without
administrator rights.

Keyboard regression tests use Node.js without npm dependencies. When Node.js is
available, pytest runs them automatically; otherwise that test is skipped. You can
also run them directly:

```sh
node --test tests/keyboard.test.cjs
```

Package code lives in `src/podcast_practice/`; the reusable player template is
`src/podcast_practice/assets/player.html`. Python dependencies are locked in
`uv.lock`, and tool versions are defined in the runtime code. MFA is pinned to
3.4.2; its transitive native dependencies are resolved through conda-forge and are
not managed by `uv.lock`.
