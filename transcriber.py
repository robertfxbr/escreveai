"""Download one YouTube video's audio and save its full speech transcript."""

from __future__ import annotations

import os
import re
import tempfile
from html import unescape
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qs, urlparse


Status = Callable[[str], None]


@dataclass(frozen=True)
class VideoInfo:
    title: str
    url: str
    video_id: str
    duration: int | None
    method: str = "Whisper local"


@dataclass(frozen=True)
class BatchResult:
    saved: list[Path]
    failed: list[tuple[str, str]]
    skipped: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class PlaylistVideo:
    url: str
    title: str


def validate_youtube_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {
        "youtube.com", "www.youtube.com", "m.youtube.com",
        "music.youtube.com", "youtu.be", "www.youtu.be",
    }:
        raise ValueError("Cole um link válido de vídeo do YouTube.")
    parts = [part for part in parsed.path.split("/") if part]
    playlist_id = parse_qs(parsed.query).get("list", [""])[0]
    video_id = parse_qs(parsed.query).get("v", [""])[0]
    safe_video_id = lambda value: bool(re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value))
    safe_playlist_id = lambda value: bool(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value))
    if host.endswith("youtu.be"):
        valid = len(parts) == 1 and safe_video_id(parts[0])
    elif parsed.path == "/playlist":
        valid = safe_playlist_id(playlist_id)
    elif parsed.path == "/watch":
        valid = safe_video_id(video_id) or safe_playlist_id(playlist_id)
    else:
        valid = (
            len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}
            and safe_video_id(parts[1])
        )
    if not valid:
        raise ValueError("O link deve apontar para um único vídeo do YouTube.")
    return url


def is_playlist_url(url: str) -> bool:
    parsed = urlparse(validate_youtube_url(url))
    return bool(parse_qs(parsed.query).get("list", [""])[0])


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def render_markdown(
    info: VideoInfo, segments: Iterable[object], *, remove_fillers: bool = False,
) -> str:
    title = " ".join(info.title.split()) or "Vídeo sem título"
    lines = [f"# {title}", "", f"**Fonte:** {info.url}"]
    if info.duration is not None:
        lines.append(f"**Duração:** {format_timestamp(info.duration)}")
    lines.append(f"**Origem da transcrição:** {info.method}")
    lines.extend(["", "## Transcrição", ""])
    count = 0
    previous = ""
    for segment in segments:
        speech = " ".join(unescape(str(segment.text)).split())
        if remove_fillers:
            speech = re.sub(r"(?i)^(?:(?:ahn+|hã+|éé+|uh+)[,.;:\s]+)+", "", speech).strip()
        if not speech or speech.casefold() == previous:
            continue
        seconds = max(0, int(segment.start))
        stamp = format_timestamp(seconds)
        link = f"https://www.youtube.com/watch?v={info.video_id}&t={seconds}s"
        lines.append(f"[{stamp}]({link}) {speech}")
        lines.append("")
        count += 1
        previous = speech.casefold()
    if count == 0:
        raise ValueError("Nenhuma fala foi detectada neste vídeo.")
    return "\n".join(lines).rstrip() + "\n"


def safe_filename(title: str, video_id: str) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title)
    base = re.sub(r"\s+", " ", base).strip(" .")[:90].rstrip(" .")
    if not base or base.upper() in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        base = "Transcrição"
    return f"{base} [{video_id}]"


def video_id_from_url(url: str) -> str:
    parsed = urlparse(validate_youtube_url(url))
    if (parsed.hostname or "").lower().endswith("youtu.be"):
        return parsed.path.strip("/")
    if parsed.path == "/watch":
        return parse_qs(parsed.query)["v"][0]
    return parsed.path.strip("/").split("/")[1]


def fetch_playlist_urls(url: str, status: Status) -> list[PlaylistVideo]:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("Dependência yt-dlp ausente. Execute iniciar.bat para instalar.") from exc

    status("Carregando a lista de vídeos da playlist...")
    options = {
        "extract_flat": "in_playlist", "skip_download": True,
        "ignoreerrors": True, "quiet": True, "no_warnings": True,
        "js_runtimes": {"node": {}},
    }
    with YoutubeDL(options) as ydl:
        data = ydl.extract_info(url, download=False)
    if not data or data.get("_type") != "playlist":
        raise ValueError("Não foi possível abrir a playlist.")
    urls = []
    for entry in data.get("entries") or []:
        if not entry:
            continue
        video_id = entry.get("id") or ""
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            urls.append(PlaylistVideo(
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=entry.get("title") or f"Vídeo {video_id}",
            ))
    if not urls:
        raise ValueError("A playlist não contém vídeos acessíveis.")
    return urls


def fetch_captions(url: str, status: Status) -> tuple[VideoInfo, list[object]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError("Dependência youtube-transcript-api ausente. Execute iniciar.bat.") from exc

    video_id = video_id_from_url(url)
    status("Buscando legendas do YouTube...")
    tracks = list(YouTubeTranscriptApi().list(video_id))
    if not tracks:
        raise ValueError("Vídeo sem legendas disponíveis.")

    def preference(track: object) -> tuple[int, int]:
        language = str(track.language_code).lower()
        rank = 0 if language.startswith("pt") else 1 if language.startswith("en") else 2
        return rank, int(track.is_generated)

    track = min(tracks, key=preference)
    fetched = list(track.fetch())
    if not fetched:
        raise ValueError("As legendas do vídeo estão vazias.")
    duration = int(max(part.start + part.duration for part in fetched))
    info = VideoInfo(
        title=f"Vídeo {video_id}", url=url, video_id=video_id,
        duration=duration,
        method=f"Legendas do YouTube ({track.language_code})",
    )
    return info, fetched


def download_audio(url: str, temp_dir: Path, status: Status) -> tuple[VideoInfo, Path]:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("Dependência yt-dlp ausente. Execute iniciar.bat para instalar.") from exc

    status("Baixando o áudio do YouTube...")
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(temp_dir / "audio.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "js_runtimes": {"node": {}},
    }
    cookie_file = os.environ.get("YOUTUBE_COOKIES_FILE")
    if cookie_file:
        if not Path(cookie_file).is_file():
            raise ValueError("O arquivo cookies.txt selecionado não existe.")
        options["cookiefile"] = cookie_file
    stem = "audio"
    try:
        with YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=True)
    except Exception:
        status("Tentando rota alternativa de áudio do YouTube...")
        options["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        options["outtmpl"] = str(temp_dir / "audio-fallback.%(ext)s")
        stem = "audio-fallback"
        with YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=True)
    if not data or data.get("_type") == "playlist":
        raise ValueError("O link não retornou um vídeo individual.")
    files = [path for path in temp_dir.glob(f"{stem}.*") if path.is_file() and not path.name.endswith(".part")]
    if len(files) != 1:
        raise RuntimeError("Não foi possível localizar o áudio baixado.")
    info = VideoInfo(
        title=data.get("title") or "Vídeo sem título",
        url=data.get("webpage_url") or url,
        video_id=data.get("id") or "video",
        duration=data.get("duration"),
    )
    return info, files[0]


def transcribe_audio(audio: Path, model_name: str, status: Status) -> list[object]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Dependência faster-whisper ausente. Execute iniciar.bat para instalar.") from exc

    status(f"Carregando modelo {model_name} (na primeira vez, ele será baixado)...")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    status("Transcrevendo o vídeo completo...")
    pieces, _ = model.transcribe(str(audio), beam_size=5, vad_filter=False)
    result = []
    last_reported = -1
    for piece in pieces:
        result.append(piece)
        minute = int(piece.end // 60)
        if minute > last_reported:
            status(f"Transcrevendo... até {format_timestamp(piece.end)}")
            last_reported = minute
    return result


def transcribe_video(
    url: str,
    output_dir: Path,
    model_name: str = "small",
    status: Status | None = None,
    *,
    downloader: Callable | None = None,
    transcriber: Callable | None = None,
    caption_fetcher: Callable | None = None,
    force_whisper: bool = False,
    remove_fillers: bool = False,
    title_hint: str | None = None,
) -> Path:
    url = validate_youtube_url(url)
    if is_playlist_url(url):
        raise ValueError("Use transcribe_url para processar uma playlist.")
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise ValueError("Selecione uma pasta de destino existente.")
    if model_name not in {"tiny", "base", "small", "medium"}:
        raise ValueError("Selecione um modelo de transcrição válido.")
    report = status or (lambda _: None)
    download = downloader or download_audio
    transcribe = transcriber or transcribe_audio
    captions = caption_fetcher or fetch_captions

    content = None
    if not force_whisper:
        try:
            info, segments = captions(url, report)
            if title_hint:
                info = VideoInfo(title_hint, info.url, info.video_id, info.duration, info.method)
            content = render_markdown(info, segments, remove_fillers=remove_fillers)
        except Exception as exc:
            report(f"Legendas indisponíveis ({exc}). Usando Whisper local...")
    if content is None:
        with tempfile.TemporaryDirectory(prefix="youtube-transcricao-") as name:
            info, audio = download(url, Path(name), report)
            segments = transcribe(audio, model_name, report)
            content = render_markdown(info, segments, remove_fillers=remove_fillers)

    stem = safe_filename(info.title, info.video_id)
    for suffix in range(1, 10000):
        filename = f"{stem}.md" if suffix == 1 else f"{stem} ({suffix}).md"
        destination = output_dir / filename
        try:
            with destination.open("x", encoding="utf-8", newline="\n") as file:
                file.write(content)
            return destination
        except FileExistsError:
            continue
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    raise RuntimeError("Há arquivos demais com esse título na pasta selecionada.")


def existing_transcript(output_dir: Path, video_id: str) -> Path | None:
    ending = re.compile(rf"\[{re.escape(video_id)}\](?: \(\d+\))?\.md$")
    files = [path for path in output_dir.glob("*.md") if ending.search(path.name)]
    if files:
        return max(files, key=lambda path: path.stat().st_mtime)
    source = re.compile(
        rf"^\*\*Fonte:\*\* https://www\.youtube\.com/watch\?v={re.escape(video_id)}(?:\s|&|$)",
        re.MULTILINE,
    )
    for path in output_dir.glob("*.md"):
        try:
            with path.open("r", encoding="utf-8") as file:
                header = file.read(1024)
        except (OSError, UnicodeError):
            continue
        if source.search(header) and "## Transcrição" in header:
            return path
    return None


def visual_notes_to_markdown(notes: str, video_id: str) -> str:
    notes = notes.strip()
    if not notes:
        raise ValueError("A análise visual não retornou observações.")

    def link_stamp(match: re.Match[str]) -> str:
        stamp = match.group(1)
        parts = [int(part) for part in stamp.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            total = minutes * 60 + seconds
        else:
            hours, minutes, seconds = parts
            total = hours * 3600 + minutes * 60 + seconds
        if seconds >= 60 or (len(parts) == 3 and minutes >= 60):
            return match.group(0)
        return f"[{format_timestamp(total)}](https://www.youtube.com/watch?v={video_id}&t={total}s)"

    body = re.sub(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\](?!\()", link_stamp, notes)
    return (
        "\n\n## Contexto visual\n\n"
        "> Observações automáticas sobre o que aparece na tela; confira os detalhes no vídeo.\n\n"
        f"{body}\n"
    )


def transcribe_with_vision(
    url: str,
    output_dir: Path,
    model_name: str,
    report: Status,
    *,
    visual_analyzer: Callable | None,
    api_key: str | None,
    caption_fetcher: Callable | None,
    downloader: Callable | None,
    transcriber: Callable | None,
    force_whisper: bool,
    remove_fillers: bool,
    title_hint: str | None,
) -> Path:
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if visual_analyzer is None and not key:
        raise ValueError("Defina GEMINI_API_KEY ou informe a chave no app para usar contexto visual.")
    video_id = video_id_from_url(url)
    existing = existing_transcript(output_dir, video_id)
    if existing is None:
        existing = transcribe_video(
            url, output_dir, model_name, report,
            caption_fetcher=caption_fetcher, downloader=downloader,
            transcriber=transcriber, force_whisper=force_whisper,
            remove_fillers=remove_fillers, title_hint=title_hint,
        )
    content = existing.read_text(encoding="utf-8")
    if "\n## Contexto visual\n" in content:
        report(f"Contexto visual já concluído para {video_id}; pulando.")
        return existing

    if visual_analyzer is None:
        from vision import analyze_with_gemini
        visual_analyzer = analyze_with_gemini
    report(f"Analisando imagens do vídeo {video_id}...")
    notes = visual_analyzer(url, output_dir, report, key)
    addition = visual_notes_to_markdown(notes, video_id)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", suffix=".tmp",
        prefix="escreveai-", dir=output_dir, delete=False,
    ) as file:
        temporary = Path(file.name)
        file.write(content.rstrip() + "\n" + addition)
    try:
        os.replace(temporary, existing)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    (output_dir / f".escreveai-vision-{video_id}.json").unlink(missing_ok=True)
    return existing


def transcribe_url(
    url: str,
    output_dir: Path,
    model_name: str = "small",
    status: Status | None = None,
    *,
    playlist_fetcher: Callable | None = None,
    caption_fetcher: Callable | None = None,
    downloader: Callable | None = None,
    transcriber: Callable | None = None,
    force_whisper: bool = False,
    remove_fillers: bool = False,
    visual_mode: bool = False,
    visual_analyzer: Callable | None = None,
    api_key: str | None = None,
    max_new_videos: int | None = None,
) -> BatchResult:
    url = validate_youtube_url(url)
    if max_new_videos is not None and max_new_videos < 0:
        raise ValueError("O limite de vídeos deve ser zero ou maior.")
    report = status or (lambda _: None)
    urls = (playlist_fetcher or fetch_playlist_urls)(url, report) if is_playlist_url(url) else [url]
    saved: list[Path] = []
    failed: list[tuple[str, str]] = []
    skipped: list[Path] = []
    attempted = 0
    for index, video in enumerate(urls, 1):
        video_url = video.url if isinstance(video, PlaylistVideo) else video
        title_hint = video.title if isinstance(video, PlaylistVideo) else None
        prior = existing_transcript(Path(output_dir), video_id_from_url(video_url))
        if prior and (not visual_mode or "\n## Contexto visual\n" in prior.read_text(encoding="utf-8")):
            saved.append(prior)
            skipped.append(prior)
            if visual_mode:
                (Path(output_dir) / f".escreveai-vision-{video_id_from_url(video_url)}.json").unlink(
                    missing_ok=True
                )
            report(f"Vídeo {index}/{len(urls)}: já concluído; pulando.")
            continue
        if max_new_videos and attempted >= max_new_videos:
            report(f"Limite de {max_new_videos} vídeo(s) novos atingido nesta execução.")
            break
        attempted += 1
        report(f"Vídeo {index}/{len(urls)}: iniciando...")
        try:
            if visual_mode:
                path = transcribe_with_vision(
                    video_url, Path(output_dir), model_name, report,
                    visual_analyzer=visual_analyzer, api_key=api_key,
                    caption_fetcher=caption_fetcher, downloader=downloader,
                    transcriber=transcriber, force_whisper=force_whisper,
                    remove_fillers=remove_fillers, title_hint=title_hint,
                )
            else:
                path = transcribe_video(
                    video_url, output_dir, model_name, report,
                    caption_fetcher=caption_fetcher, downloader=downloader,
                    transcriber=transcriber, force_whisper=force_whisper,
                    remove_fillers=remove_fillers, title_hint=title_hint,
                )
        except Exception as exc:
            failed.append((video_url, str(exc)))
            report(f"Vídeo {index}/{len(urls)}: falhou — {exc}")
        else:
            saved.append(path)
            report(f"Vídeo {index}/{len(urls)}: salvo em {path.name}")
    return BatchResult(saved, failed, skipped)
