"""Save one web video to a user-selected folder with yt-dlp."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


Status = Callable[[str], None]


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
    report(f"Vídeo salvo: {result.name}")
    return result
