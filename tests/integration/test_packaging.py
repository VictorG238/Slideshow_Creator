"""PyInstaller packaging smoke test.

Covers:
  T040 – Verify the PyInstaller spec is parseable and the entry script exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SPEC_FILE = _PROJECT_ROOT / "build" / "slideshow_creator.spec"


class TestPackagingSmoke:
    """T040: PyInstaller configuration and entry-point smoke tests."""

    def test_spec_file_exists(self) -> None:
        assert _SPEC_FILE.exists(), f"Build spec not found at {_SPEC_FILE}"

    def test_entry_script_exists(self) -> None:
        entry = _PROJECT_ROOT / "src" / "slideshow_creator" / "__main__.py"
        assert entry.exists(), f"Entry script not found at {entry}"

    def test_spec_references_entry_script(self) -> None:
        content = _SPEC_FILE.read_text(encoding="utf-8")
        assert "__main__.py" in content

    def test_spec_includes_ffmpeg_assets(self) -> None:
        content = _SPEC_FILE.read_text(encoding="utf-8")
        assert "ffmpeg" in content.lower()

    def test_spec_references_pyside6_hidden_imports(self) -> None:
        content = _SPEC_FILE.read_text(encoding="utf-8")
        assert "PySide6.QtCore" in content
        assert "PySide6.QtWidgets" in content

    def test_spec_is_valid_python(self) -> None:
        """The spec file should be parseable Python (it is exec'd by PyInstaller)."""
        content = _SPEC_FILE.read_text(encoding="utf-8")
        # compile() checks syntax without executing
        compile(content, str(_SPEC_FILE), "exec")

    def test_ffmpeg_assets_directory_exists(self) -> None:
        assets_dir = _PROJECT_ROOT / "assets" / "ffmpeg"
        assert assets_dir.exists(), f"FFmpeg assets dir not found at {assets_dir}"

    @pytest.mark.skipif(
        not (_PROJECT_ROOT / ".venv" / "Scripts" / "pyinstaller.exe").exists()
        and not (_PROJECT_ROOT / ".venv" / "bin" / "pyinstaller").exists(),
        reason="PyInstaller not installed in venv",
    )
    def test_pyinstaller_importable(self) -> None:
        """Verify PyInstaller is importable in the current environment."""
        import PyInstaller
        assert PyInstaller.__version__
