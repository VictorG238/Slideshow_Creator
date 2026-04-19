from __future__ import annotations

from pathlib import Path

from slideshow_creator.services.audio_service import AudioService


def _build_mp3_like_payload(frame_count: int = 10) -> bytes:
    header = bytes.fromhex("FFFB9064")
    frame = header + bytes(417 - len(header))
    id3_header = b"ID3" + bytes([4, 0, 0, 0, 0, 0, 0])
    return id3_header + frame * frame_count


def test_inspect_mp3_uses_internal_parser_without_ffprobe(tmp_path: Path, monkeypatch) -> None:
    mp3_path = tmp_path / "sample.mp3"
    mp3_path.write_bytes(_build_mp3_like_payload(frame_count=10))

    service = AudioService()
    monkeypatch.setattr(service, "_duration_from_ffprobe", lambda _target: None)

    track = service.inspect_mp3(str(mp3_path))

    assert track.validated is True
    assert track.duration_ms == 261
    assert track.loop_count == 0


def test_validate_mp3_rejects_non_mp3_extension(tmp_path: Path) -> None:
    bad_path = tmp_path / "sample.wav"
    bad_path.write_bytes(b"not an mp3")

    assert AudioService().validate_mp3(str(bad_path)) is False


def test_required_loops_returns_expected_count() -> None:
    service = AudioService()

    assert service.required_loops(track_seconds=2.0, video_seconds=10.0) == 4
    assert service.required_loops(track_seconds=10.0, video_seconds=10.0) == 0
    assert service.required_loops(track_seconds=0.0, video_seconds=10.0) == 0


def test_inspect_mp3_calculates_loop_count_when_video_longer(tmp_path: Path, monkeypatch) -> None:
    mp3_path = tmp_path / "loop_sample.mp3"
    mp3_path.write_bytes(_build_mp3_like_payload(frame_count=10))

    service = AudioService()
    monkeypatch.setattr(service, "_duration_from_ffprobe", lambda _target: None)

    track = service.inspect_mp3(str(mp3_path), video_seconds=1.1)

    assert track.validated is True
    assert track.duration_ms == 261
    assert track.loop_count == 4
