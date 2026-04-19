"""Package entry point for python -m slideshow_creator."""

from slideshow_creator.app import main
from slideshow_creator.services.ffmpeg_manager import setup_ffmpeg


if __name__ == "__main__":
    setup_ffmpeg()
    raise SystemExit(main())
