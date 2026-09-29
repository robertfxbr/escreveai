"""Command-line entry point for downloading one video from a supported site."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from downloader import download_video


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Baixa um vídeo de um site compatível com yt-dlp.")
    parser.add_argument("url", nargs="?", help="URL do vídeo")
    parser.add_argument("--pasta", type=Path, default=Path.cwd(), help="Pasta de destino")
    parser.add_argument("--cookies", type=Path, help="Arquivo cookies.txt para sites que exigem login")
    args = parser.parse_args()
    url = args.url or input("URL do vídeo: ").strip()
    try:
        saved = download_video(url, args.pasta, print, cookie_file=args.cookies)
    except KeyboardInterrupt:
        print("\nDownload interrompido. Execute novamente para tentar retomar.")
        return 130
    except Exception as exc:
        print(f"Erro: {exc}")
        return 1
    print(f"Concluído: {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
