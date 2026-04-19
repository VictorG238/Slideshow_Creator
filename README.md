# Slideshow Creator

Desktop application that generates countdown slideshow videos from internet images with optional looped MP3 background music.

Type a search term, pick how many slides you want, and the app searches multiple image providers, assembles a numbered countdown sequence, and exports a single video file -- all from one window.

---

## Demo


https://github.com/user-attachments/assets/c0d44120-615e-4da2-8763-37c589076df0


---

## Features

- **Multi-engine image search** -- Uses selected providers (Google, Bing, DuckDuckGo, Openverse), URL canonicalization, and fallback probing when one engine returns no usable results.
- **Visual duplicate control** -- Adds image-signature checks to reduce duplicate content even when URLs differ.
- **Countdown slideshow builder** -- Generates intro title cards, numbered countdown overlays, and image slides in the correct order while spreading unavoidable image reuse.
- **Background music** -- Optionally attach an MP3 file; the audio is automatically looped or trimmed to match the video length.
- **Automatic codec selection** -- Detects NVIDIA NVENC for GPU-accelerated encoding and falls back to CPU `libx264` / `libvpx-vp9` when unavailable.
- **Format flexibility** -- Export as MP4 or WebM; the app corrects the file extension if the chosen encoder requires a different container.
- **Target file size** -- Set a size cap in megabytes and the encoder calculates the optimal bitrate.
- **Responsive dark UI** -- Four-section dashboard with KPI summary cards, live progress bar, and phase indicators that reflow between single-column and two-column layouts.

---

## Quick Start (from source)

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python      | 3.14+   |
| FFmpeg      | Any recent build (`ffmpeg` and `ffprobe` in PATH or in `assets/ffmpeg/`) |
| OS          | Windows 10 / 11 |

### Install and run

```bash
# Clone the repository
git clone https://github.com/VictorG238/Slideshow_Creator.git
cd Slideshow_Creator

# Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]

# Launch the application
python -m slideshow_creator
```

Or use the included helper script:

```bash
run_app.bat
run_app.bat --doctor   # verify environment and FFmpeg
```

---

## Download (standalone .exe)

Pre-built Windows executables are available on the [Releases](https://github.com/VictorG238/Slideshow_Creator/releases) page. No Python installation required.

1. Download `slideshow_creator.exe` from the latest release.
2. Place FFmpeg binaries (`ffmpeg.exe`, `ffprobe.exe`) next to it or ensure they are in your system PATH.
3. Double-click the exe to launch.

---

## Building the .exe yourself

```bash
# Inside the activated virtual environment
pip install -e .[dev]
pyinstaller --noconfirm --clean build/slideshow_creator.spec
```

The single-file executable is written to `dist/slideshow_creator.exe`.

---

## Project Structure

```
Slideshow_Creator/
  src/slideshow_creator/
    app.py              # Application controller and thread orchestration
    models/domain.py    # Data classes (GenerationRequest, AppError, ExportJob)
    services/
      image_search.py   # Multi-provider image search with fallback
      slideshow_builder.py  # Countdown slide composition
      audio_service.py  # MP3 validation, duration, loop count
      export_service.py # FFmpeg encoding, codec detection, progress
    ui/
      main_window.py    # PySide6 main window
      styles.py         # Design tokens and stylesheet
  tests/
    unit/               # Fast isolated tests
    ui/                 # pytest-qt GUI tests
    integration/        # FFmpeg pipeline and packaging smoke tests
  build/
    slideshow_creator.spec  # PyInstaller build config
  assets/ffmpeg/        # Optional bundled FFmpeg binaries
```

---

## Running Tests

```bash
# All tests (skips FFmpeg integration tests if ffmpeg is not installed)
pytest

# Unit and UI tests only (no FFmpeg needed)
pytest tests/unit/ tests/ui/

# Include slow export smoke test
pytest --run-slow
```

---

## How It Works

1. **Search** -- The user enters a search term and slide count. The app probes selected providers, canonicalizes URLs, applies fallback probes when needed, and optionally validates candidates using lightweight visual signatures.
2. **Build** -- A slideshow is composed: one intro title card, then for each slide a numbered countdown overlay followed by the downloaded image. If fewer unique images are available than requested, the app reuses images while trying to avoid adjacent and first/last repeats.
3. **Export** -- The rendered frames are fed to FFmpeg as a concat sequence. The encoder is chosen based on hardware capability and the user's format preference. A progress callback updates the UI in real time.
4. **Audio** -- If an MP3 is selected, the service calculates how many loops are needed to cover the video duration and muxes the audio stream into the output file.

---

## Configuration Notes

- Export format fallback (MP4 / WebM) is automatic when a preferred encoder is unavailable.
- Audio is optional. When omitted the video is exported without an audio stream.
- Large slideshow counts (100+ slides) are supported with per-image retry logic during download.
- Image search providers can be toggled per run from the GUI checkboxes.
- Downloaded image licensing and attribution workflow is intentionally out of scope for v1; users are responsible for legal reuse.

---

## License

This project is licensed under the Attribution Free Use License v1.0.

You may use, modify, and distribute it for free, including commercial use.
If you publish a modified version, you must give credit to the original
author.

See LICENSE for full terms.
