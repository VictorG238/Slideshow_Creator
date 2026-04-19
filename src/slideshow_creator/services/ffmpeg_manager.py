"""FFmpeg availability manager with auto-download support."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional


class FFmpegManager:
    """Detect, cache, and download FFmpeg as needed."""

    DOWNLOAD_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    CACHE_DIR = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "slideshow-creator" / "ffmpeg"

    @staticmethod
    def _is_usable_ffmpeg(path: Path) -> bool:
        """Check if ffmpeg binary can actually start and report version."""
        try:
            completed = subprocess.run(
                [str(path), "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
            )
            return completed.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _bundled_ffmpeg_path() -> Path:
        """Resolve bundled ffmpeg path for source and frozen executable."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base_dir = Path(getattr(sys, "_MEIPASS"))
        else:
            base_dir = Path(__file__).resolve().parents[3]
        return base_dir / "assets" / "ffmpeg" / "ffmpeg.exe"

    @staticmethod
    def find_ffmpeg() -> Optional[str]:
        """Find FFmpeg in order of preference."""
        # 1. Check environment override
        if env_path := os.getenv("SLIDESHOW_FFMPEG_PATH"):
            if Path(env_path).exists() and FFmpegManager._is_usable_ffmpeg(Path(env_path)):
                return env_path

        # 2. Check project bundled location (packaged in .exe)
        bundled = FFmpegManager._bundled_ffmpeg_path()
        if bundled.exists() and FFmpegManager._is_usable_ffmpeg(bundled):
            print(f"[slideshow] Using bundled FFmpeg: {bundled}")
            return str(bundled)

        # 3. Check system PATH before cache so a valid global install is preferred
        if system_ffmpeg := shutil.which("ffmpeg"):
            system_path = Path(system_ffmpeg)
            if FFmpegManager._is_usable_ffmpeg(system_path):
                print(f"[slideshow] Using system FFmpeg: {system_ffmpeg}")
                return system_ffmpeg

        # 4. Check cached location (from previous auto-download)
        cached = FFmpegManager.CACHE_DIR / "ffmpeg.exe"
        if cached.exists() and FFmpegManager._is_usable_ffmpeg(cached):
            print(f"[slideshow] Using cached FFmpeg: {cached}")
            return str(cached)

        return None

    @staticmethod
    def ensure_ffmpeg() -> str:
        """
        Ensure FFmpeg is available, downloading if necessary.
        
        Returns:
            Path to ffmpeg.exe
            
        Raises:
            RuntimeError: If FFmpeg cannot be found or downloaded.
        """
        if ffmpeg_path := FFmpegManager.find_ffmpeg():
            return ffmpeg_path

        print("[slideshow] FFmpeg not found. Attempting auto-download...")
        return FFmpegManager._download_ffmpeg()

    @staticmethod
    def _download_ffmpeg() -> str:
        """Download and cache FFmpeg."""
        FFmpegManager.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        zip_path = None
        try:
            # Download
            print(f"[slideshow] Downloading FFmpeg from {FFmpegManager.DOWNLOAD_URL}...")
            zip_path = Path(tempfile.gettempdir()) / "ffmpeg_download.zip"
            
            import urllib.request
            urllib.request.urlretrieve(FFmpegManager.DOWNLOAD_URL, str(zip_path))
            print(f"[slideshow] Downloaded to {zip_path}")

            # Extract
            print(f"[slideshow] Extracting FFmpeg...")
            with tempfile.TemporaryDirectory() as tmpdir:
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extractall(tmpdir)
                
                # Find extracted ffmpeg.exe
                extracted_ffmpeg = None
                for root, dirs, files in os.walk(tmpdir):
                    if "ffmpeg.exe" in files:
                        extracted_ffmpeg = Path(root) / "ffmpeg.exe"
                        break
                
                if not extracted_ffmpeg:
                    raise RuntimeError("ffmpeg.exe not found in downloaded archive")
                
                # Copy to cache
                shutil.copy(extracted_ffmpeg, FFmpegManager.CACHE_DIR / "ffmpeg.exe")
                
                # Also copy ffprobe if available
                extracted_ffprobe = extracted_ffmpeg.parent / "ffprobe.exe"
                if extracted_ffprobe.exists():
                    shutil.copy(extracted_ffprobe, FFmpegManager.CACHE_DIR / "ffprobe.exe")
            
            ffmpeg_cache = FFmpegManager.CACHE_DIR / "ffmpeg.exe"
            print(f"[slideshow] FFmpeg cached to {ffmpeg_cache}")
            return str(ffmpeg_cache)

        except Exception as e:
            raise RuntimeError(
                f"Failed to auto-download FFmpeg: {e}\n"
                "Please install FFmpeg manually: https://ffmpeg.org/download.html\n"
                "Or set SLIDESHOW_FFMPEG_PATH environment variable."
            )
        finally:
            if zip_path and zip_path.exists():
                try:
                    zip_path.unlink()
                except Exception:
                    pass


def setup_ffmpeg() -> None:
    """Initialize FFmpeg environment for the application."""
    try:
        ffmpeg_path = FFmpegManager.ensure_ffmpeg()
        os.environ["SLIDESHOW_FFMPEG_PATH"] = ffmpeg_path
        print(f"[slideshow] FFmpeg ready: {ffmpeg_path}")
    except RuntimeError as e:
        print(f"[slideshow] ERROR: {e}")
        raise
