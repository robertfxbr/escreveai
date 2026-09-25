"""Windows desktop interface for YouTube-to-Markdown transcription."""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from transcriber import BatchResult, transcribe_url


class TranscriptionApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("YouTube para Markdown")
        self.root.geometry("660x620")
        self.root.minsize(560, 590)
        self.root.configure(bg="#f5f7fb")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.url = tk.StringVar()
        self.folder = tk.StringVar()
        self.cookies = tk.StringVar()
        self.model = tk.StringVar(value="small")
        self.force_whisper = tk.BooleanVar(value=False)
        self.remove_fillers = tk.BooleanVar(value=False)
        self.visual_mode = tk.BooleanVar(value=False)
        self.api_key = tk.StringVar()
        self.visual_limit = tk.IntVar(value=3)
        self.status = tk.StringVar(value="Pronto para transcrever.")
        self.result_path: Path | None = None
        self._build()
        self.root.after(100, self._process_events)

    def _build(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f7fb")
        style.configure("TLabel", background="#f5f7fb", foreground="#263348", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 20), foreground="#14233b")
        style.configure("Hint.TLabel", font=("Segoe UI", 9), foreground="#607086")
        style.configure("TEntry", padding=7)
        style.configure("TButton", padding=(11, 7), font=("Segoe UI", 10))
        style.configure("Accent.TButton", background="#1967d2", foreground="white")
        style.map("Accent.TButton", background=[("active", "#1557b0"), ("disabled", "#a8bedf")])

        main = ttk.Frame(self.root, padding=24)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="YouTube → Markdown", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            main, text="Cole um vídeo ou playlist e salve um .md por vídeo na pasta escolhida.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(3, 21))

        ttk.Label(main, text="Link do vídeo ou playlist").pack(anchor="w")
        self.url_entry = ttk.Entry(main, textvariable=self.url)
        self.url_entry.pack(fill="x", pady=(5, 16))
        self.url_entry.focus_set()

        ttk.Label(main, text="Pasta para salvar o .md").pack(anchor="w")
        folder_row = ttk.Frame(main)
        folder_row.pack(fill="x", pady=(5, 16))
        ttk.Entry(folder_row, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        self.browse_button = ttk.Button(folder_row, text="Selecionar...", command=self._choose_folder)
        self.browse_button.pack(side="left", padx=(8, 0))

        ttk.Label(main, text="Cookies do YouTube (opcional, para vídeos que exigem login)").pack(anchor="w")
        cookie_row = ttk.Frame(main)
        cookie_row.pack(fill="x", pady=(5, 16))
        self.cookie_entry = ttk.Entry(cookie_row, textvariable=self.cookies)
        self.cookie_entry.pack(side="left", fill="x", expand=True)
        self.cookie_browse_button = ttk.Button(cookie_row, text="Selecionar...", command=self._choose_cookies)
        self.cookie_browse_button.pack(side="left", padx=(8, 0))

        options = ttk.Frame(main)
        options.pack(fill="x")
        ttk.Label(options, text="Modelo de transcrição").pack(side="left")
        self.model_box = ttk.Combobox(
            options, textvariable=self.model, values=("tiny", "base", "small", "medium"),
            state="readonly", width=11,
        )
        self.model_box.pack(side="left", padx=(12, 12))
        ttk.Label(options, text="small: equilíbrio entre velocidade e qualidade", style="Hint.TLabel").pack(side="left")

        self.whisper_checkbox = ttk.Checkbutton(
            main, text="Usar sempre Whisper (mais lento)", variable=self.force_whisper,
        )
        self.whisper_checkbox.pack(anchor="w", pady=(12, 0))
        self.fillers_checkbox = ttk.Checkbutton(
            main, text="Remover cacoetes iniciais comuns", variable=self.remove_fillers,
        )
        self.fillers_checkbox.pack(anchor="w", pady=(3, 0))
        self.visual_checkbox = ttk.Checkbutton(
            main, text="Adicionar contexto visual com Gemini (opcional)", variable=self.visual_mode,
        )
        self.visual_checkbox.pack(anchor="w", pady=(3, 0))
        ttk.Label(main, text="Chave Gemini API (ou defina GEMINI_API_KEY)", style="Hint.TLabel").pack(
            anchor="w", pady=(8, 2)
        )
        self.key_entry = ttk.Entry(main, textvariable=self.api_key, show="•")
        self.key_entry.pack(fill="x")
        limit_row = ttk.Frame(main)
        limit_row.pack(fill="x", pady=(6, 0))
        ttk.Label(limit_row, text="Vídeos novos por execução (modo visual)", style="Hint.TLabel").pack(side="left")
        self.limit_box = ttk.Spinbox(limit_row, from_=1, to=100, textvariable=self.visual_limit, width=5)
        self.limit_box.pack(side="left", padx=(9, 0))

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(23, 12))
        self.start_button = ttk.Button(
            actions, text="Transcrever", style="Accent.TButton", command=self._start,
        )
        self.start_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Abrir resultado", command=self._open_result, state="disabled")
        self.open_button.pack(side="left", padx=(9, 0))

        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill="x")
        ttk.Label(main, textvariable=self.status, wraplength=600).pack(anchor="w", pady=(9, 0))

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(parent=self.root, title="Selecione a pasta de destino")
        if chosen:
            self.folder.set(chosen)

    def _choose_cookies(self) -> None:
        chosen = filedialog.askopenfilename(
            parent=self.root, title="Selecione o cookies.txt do YouTube",
            filetypes=(("Arquivos de texto", "*.txt"), ("Todos os arquivos", "*.*")),
        )
        if chosen:
            self.cookies.set(chosen)

    def _start(self) -> None:
        url = self.url.get().strip()
        folder = Path(self.folder.get().strip())
        if not url:
            messagebox.showerror("Link ausente", "Cole o link de um vídeo ou playlist do YouTube.", parent=self.root)
            return
        if not self.folder.get().strip() or not folder.is_dir():
            messagebox.showerror("Pasta ausente", "Selecione uma pasta de destino existente.", parent=self.root)
            return
        cookie_file = self.cookies.get().strip()
        if cookie_file and not Path(cookie_file).is_file():
            messagebox.showerror("Cookies ausentes", "Selecione um arquivo cookies.txt existente.", parent=self.root)
            return
        if self.visual_mode.get() and not (self.api_key.get().strip() or os.environ.get("GEMINI_API_KEY")):
            messagebox.showerror(
                "Chave ausente", "Informe uma chave Gemini API ou defina GEMINI_API_KEY.", parent=self.root,
            )
            return
        if self.visual_mode.get() and self.visual_limit.get() < 1:
            messagebox.showerror("Limite inválido", "Use pelo menos 1 vídeo por execução.", parent=self.root)
            return
        self.result_path = None
        self.open_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.cookie_entry.configure(state="disabled")
        self.cookie_browse_button.configure(state="disabled")
        self.model_box.configure(state="disabled")
        self.whisper_checkbox.configure(state="disabled")
        self.fillers_checkbox.configure(state="disabled")
        self.visual_checkbox.configure(state="disabled")
        self.key_entry.configure(state="disabled")
        self.limit_box.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Iniciando...")
        threading.Thread(
            target=self._run,
            args=(url, folder, self.model.get(), self.force_whisper.get(),
                  self.remove_fillers.get(), self.visual_mode.get(), self.api_key.get().strip(),
                  self.visual_limit.get(), cookie_file),
            daemon=True,
        ).start()

    def _run(
        self, url: str, folder: Path, model: str, force_whisper: bool,
        remove_fillers: bool, visual_mode: bool, api_key: str, visual_limit: int,
        cookie_file: str,
    ) -> None:
        previous_cookies = os.environ.get("YOUTUBE_COOKIES_FILE")
        if cookie_file:
            os.environ["YOUTUBE_COOKIES_FILE"] = cookie_file
        try:
            result = transcribe_url(
                url, folder, model,
                lambda message: self.events.put(("status", message)),
                force_whisper=force_whisper,
                remove_fillers=remove_fillers,
                visual_mode=visual_mode,
                api_key=api_key,
                max_new_videos=visual_limit if visual_mode else None,
            )
        except Exception as exc:
            self.events.put(("error", str(exc)))
        else:
            self.events.put(("done", result))
        finally:
            if cookie_file:
                if previous_cookies is None:
                    os.environ.pop("YOUTUBE_COOKIES_FILE", None)
                else:
                    os.environ["YOUTUBE_COOKIES_FILE"] = previous_cookies

    def _process_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status.set(str(payload))
                elif kind == "error":
                    self._finish()
                    self.status.set("Não foi possível concluir a transcrição.")
                    messagebox.showerror("Erro na transcrição", str(payload), parent=self.root)
                elif kind == "done":
                    self._finish()
                    result: BatchResult = payload
                    if result.saved:
                        self.result_path = result.saved[0] if len(result.saved) == 1 else result.saved[0].parent
                        self.open_button.configure(state="normal")
                    new_count = len(result.saved) - len(result.skipped)
                    summary = (
                        f"{new_count} novo(s); {len(result.skipped)} já pronto(s); "
                        f"{len(result.failed)} falha(s)."
                    )
                    self.status.set(summary)
                    if result.failed:
                        details = "\n".join(f"{url}: {error}" for url, error in result.failed[:5])
                        messagebox.showwarning("Processamento concluído", f"{summary}\n\n{details}", parent=self.root)
                    else:
                        messagebox.showinfo("Transcrição concluída", summary, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def _finish(self) -> None:
        self.progress.stop()
        self.start_button.configure(state="normal")
        self.browse_button.configure(state="normal")
        self.cookie_entry.configure(state="normal")
        self.cookie_browse_button.configure(state="normal")
        self.model_box.configure(state="readonly")
        self.whisper_checkbox.configure(state="normal")
        self.fillers_checkbox.configure(state="normal")
        self.visual_checkbox.configure(state="normal")
        self.key_entry.configure(state="normal")
        self.limit_box.configure(state="normal")

    def _open_result(self) -> None:
        if self.result_path and self.result_path.exists():
            os.startfile(self.result_path)


def main() -> None:
    root = tk.Tk()
    TranscriptionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
