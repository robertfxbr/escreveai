"""Optional Gemini analysis of public YouTube videos with resumable jobs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from transcriber import video_id_from_url


MODEL = "gemini-3.8-flash"
PROMPT = """Analise o que APARECE na tela durante este vídeo. Responda em português brasileiro.
Crie uma linha por observação visual relevante, no formato:
- [HH:MM:SS] descrição objetiva.
Inclua slides, diagramas, gráficos, códigos, demonstrações e textos importantes na tela.
Priorize informações visuais que acrescentam contexto ao áudio. Cubra o vídeo inteiro,
inclusive início, meio e fim, com até 60 observações. Não reescreva a fala, não invente
detalhes invisíveis e não afirme que viu um trecho que não examinou.
Se nada relevante aparecer, responda: Sem observações visuais relevantes.
"""


def _status_value(value: object) -> str:
    return str(getattr(value, "value", value)).lower()


def analyze_with_gemini(
    url: str,
    output_dir: Path,
    status: Callable[[str], None],
    api_key: str | None,
    *,
    client_factory: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    if not api_key:
        raise ValueError("Defina GEMINI_API_KEY para usar contexto visual.")
    if client_factory is None:
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "Dependência google-genai ausente. Instale requirements-vision.txt."
            ) from exc
        client_factory = genai.Client

    client = client_factory(api_key=api_key)
    video_id = video_id_from_url(url)
    job_file = Path(output_dir) / f".escreveai-vision-{video_id}.json"
    if job_file.exists():
        job = json.loads(job_file.read_text(encoding="utf-8"))
        if job.get("url") != url or job.get("model") != MODEL or not job.get("id"):
            raise ValueError(f"Estado de análise visual inválido: {job_file}")
        if job.get("notes"):
            status(f"Reaproveitando observações visuais prontas de {video_id}...")
            return job["notes"]
        job_id = job["id"]
        status(f"Retomando análise visual do vídeo {video_id}...")
    else:
        status(f"Enviando vídeo {video_id} para análise visual...")
        interaction = client.interactions.create(
            model=MODEL,
            input=[
                {"type": "video", "uri": url, "processing": "agentic"},
                {"type": "text", "text": PROMPT},
            ],
            background=True,
        )
        job_id = interaction.id
        if not job_id:
            raise RuntimeError("A API não retornou o identificador da análise visual.")
        job_file.write_text(
            json.dumps({"url": url, "model": MODEL, "id": job_id}, ensure_ascii=False),
            encoding="utf-8",
        )

    while True:
        interaction = client.interactions.get(job_id)
        state = _status_value(interaction.status)
        if state == "completed":
            notes = (interaction.output_text or "").strip()
            if not notes:
                raise RuntimeError("A API concluiu a análise sem retornar observações visuais.")
            cached = job_file.with_suffix(".json.tmp")
            cached.write_text(
                json.dumps({"url": url, "model": MODEL, "id": job_id, "notes": notes}, ensure_ascii=False),
                encoding="utf-8",
            )
            cached.replace(job_file)
            return notes
        if state in {"failed", "cancelled"}:
            job_file.unlink(missing_ok=True)
            raise RuntimeError(f"Análise visual {state}: {getattr(interaction, 'error', '')}")
        if state != "in_progress":
            raise RuntimeError(f"Análise visual pausada com estado inesperado: {state}")
        status(f"Análise visual do vídeo {video_id} em andamento...")
        sleep(10)
