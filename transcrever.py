"""Command-line entry point for single videos and YouTube playlists."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from transcriber import transcribe_url


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Transcreve vídeo ou playlist do YouTube em arquivos Markdown separados."
    )
    parser.add_argument("url", nargs="?", help="Link do vídeo ou da playlist")
    parser.add_argument("--pasta", type=Path, help="Pasta de destino (padrão: pasta atual)")
    parser.add_argument("--modelo", choices=("tiny", "base", "small", "medium"), default="small")
    parser.add_argument("--whisper", action="store_true", help="Usar Whisper mesmo quando há legendas")
    parser.add_argument("--limpar-cacoetes", action="store_true", help="Remove cacoetes no início de trechos")
    parser.add_argument("--visao", action="store_true", help="Adiciona contexto visual com Gemini (GEMINI_API_KEY)")
    parser.add_argument("--limite", type=int, default=3, help="Vídeos novos por execução com --visao (0 = sem limite)")
    args = parser.parse_args()

    url = args.url or input("Link do vídeo ou playlist: ").strip()
    folder = args.pasta or Path.cwd()
    if args.visao and not os.environ.get("GEMINI_API_KEY"):
        print("Erro: defina GEMINI_API_KEY para usar --visao.")
        return 1
    try:
        result = transcribe_url(
            url, folder, args.modelo, print,
            force_whisper=args.whisper,
            remove_fillers=args.limpar_cacoetes,
            visual_mode=args.visao,
            max_new_videos=args.limite if args.visao else None,
        )
    except Exception as exc:
        print(f"Erro: {exc}")
        return 1
    print(
        f"\nConcluído: {len(result.saved) - len(result.skipped)} novo(s), "
        f"{len(result.skipped)} já pronto(s), {len(result.failed)} falha(s)."
    )
    for path in result.saved:
        print(f"  {path}")
    for failed_url, error in result.failed:
        print(f"  FALHOU {failed_url}: {error}")
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
