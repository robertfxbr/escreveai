"""Command-line entry point for single videos and YouTube playlists."""

from __future__ import annotations

import argparse
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
    args = parser.parse_args()

    url = args.url or input("Link do vídeo ou playlist: ").strip()
    folder = args.pasta or Path.cwd()
    try:
        result = transcribe_url(
            url, folder, args.modelo, print,
            force_whisper=args.whisper,
            remove_fillers=args.limpar_cacoetes,
        )
    except Exception as exc:
        print(f"Erro: {exc}")
        return 1
    print(f"\nConcluído: {len(result.saved)} arquivo(s) salvo(s), {len(result.failed)} falha(s).")
    for path in result.saved:
        print(f"  {path}")
    for failed_url, error in result.failed:
        print(f"  FALHOU {failed_url}: {error}")
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
