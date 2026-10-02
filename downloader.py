"""Save one web video to a user-selected folder with yt-dlp."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


Status = Callable[[str], None]

HEVC_CODECS = {"hevc", "h265"}
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class DownloadCancelled(Exception):
    """The user stopped a video download."""


def validate_media_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in url)
    ):
        raise ValueError("Cole uma URL http ou https de um vídeo acessível.")
    return url


def download_video(
    url: str,
    output_dir: Path,
    status: Status | None = None,
    *,
    cookie_file: Path | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Download a single video; leave .part files for a later retry if stopped."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("Dependência yt-dlp ausente. Execute iniciar.bat para instalar.") from exc

    url = validate_media_url(url)
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise ValueError("Selecione uma pasta de destino existente.")
    if cookie_file is not None:
        cookie_file = Path(cookie_file)
        if not cookie_file.is_file():
            raise ValueError("O arquivo cookies.txt selecionado não existe.")

    report = status or (lambda _: None)

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("Download cancelado pelo usuário.")

    last_percent = -5

    def progress(update: dict) -> None:
        nonlocal last_percent
        check_cancelled()
        if update.get("status") != "downloading":
            return
        total = update.get("total_bytes") or update.get("total_bytes_estimate")
        done = update.get("downloaded_bytes") or 0
        if total:
            percent = min(100, int(done * 100 / total))
            if percent >= last_percent + 5 or percent == 100:
                report(f"Baixando vídeo... {percent}%")
                last_percent = percent

    options = {
        "outtmpl": str(output_dir / "%(title).150s [%(extractor_key)s-%(id)s].%(ext)s"),
        "noplaylist": True,
        "nooverwrites": True,
        "continuedl": True,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [progress],
        "js_runtimes": {"node": {}},
    }
    if cookie_file is not None:
        options["cookiefile"] = str(cookie_file)

    check_cancelled()
    report("Verificando o link e os formatos disponíveis...")
    with YoutubeDL(options) as ydl:
        preview = ydl.extract_info(url, download=False)
        check_cancelled()
        if not preview or preview.get("_type") == "playlist":
            raise ValueError("Esta modalidade aceita uma URL de vídeo por vez, não uma playlist.")
        report("Baixando vídeo na melhor qualidade disponível...")
        info = ydl.extract_info(url, download=True)
        check_cancelled()
        if not info or info.get("_type") == "playlist":
            raise RuntimeError("O site não retornou um vídeo individual.")
        filename = info.get("filepath") or ydl.prepare_filename(info)

    result = Path(filename).resolve()
    if not result.is_relative_to(output_dir.resolve()) or not result.is_file():
        raise RuntimeError("O arquivo final não foi encontrado na pasta selecionada.")
    convert_hevc_to_h264(result, report, cancel_event)
    report(f"Vídeo salvo: {result.name}")
    return result


def _video_codec(path: Path, ffprobe: str) -> str:
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    return completed.stdout.strip().lower()


def _duration_seconds(path: Path, ffprobe: str) -> float | None:
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    try:
        return float(completed.stdout.strip())
    except ValueError:
        return None


def convert_hevc_to_h264(
    path: Path, status: Status | None = None, cancel_event: threading.Event | None = None,
) -> bool:
    """Re-encode an HEVC video to H.264 in place so default Windows players can open it.

    Returns True when the file was converted. Without FFmpeg the HEVC file is kept.
    """
    report = status or (lambda _: None)
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        report("FFmpeg não encontrado; o vídeo foi mantido no codec original.")
        return False
    if _video_codec(path, ffprobe) not in HEVC_CODECS:
        return False

    duration = _duration_seconds(path, ffprobe)
    temporary = path.with_name(f"{path.stem}.h264-tmp{path.suffix}")
    report("Convertendo HEVC para H.264...")
    process = subprocess.Popen(
        [ffmpeg, "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", str(path),
         "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(temporary)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=_NO_WINDOW,
    )
    last_percent = -10
    try:
        for line in process.stdout:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                process.wait()
                raise DownloadCancelled("Conversão cancelada; o vídeo original foi mantido.")
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and duration and value.isdigit():
                percent = min(100, int(int(value) / 1_000_000 * 100 / duration))
                if percent >= last_percent + 10:
                    report(f"Convertendo para H.264... {percent}%")
                    last_percent = percent
        if process.wait() != 0:
            report("O FFmpeg não conseguiu converter para H.264; o vídeo foi mantido em HEVC.")
            return False
        temporary.replace(path)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()
        temporary.unlink(missing_ok=True)
    return True
