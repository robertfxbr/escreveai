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
        self.root.geometry("660x440")
        self.root.minsize(560, 420)
        self.root.configure(bg="#f5f7fb")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.url = tk.StringVar()
        self.folder = tk.StringVar()
        self.model = tk.StringVar(value="small")
        self.force_whisper = tk.BooleanVar(value=False)
        self.remove_fillers = tk.BooleanVar(value=False)
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

    def _start(self) -> None:
        url = self.url.get().strip()
        folder = Path(self.folder.get().strip())
        if not url:
            messagebox.showerror("Link ausente", "Cole o link de um vídeo ou playlist do YouTube.", parent=self.root)
            return
        if not self.folder.get().strip() or not folder.is_dir():
            messagebox.showerror("Pasta ausente", "Selecione uma pasta de destino existente.", parent=self.root)
            return
        self.result_path = None
        self.open_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.model_box.configure(state="disabled")
        self.whisper_checkbox.configure(state="disabled")
        self.fillers_checkbox.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Iniciando...")
        threading.Thread(
            target=self._run,
            args=(url, folder, self.model.get(), self.force_whisper.get(), self.remove_fillers.get()),
            daemon=True,
        ).start()

    def _run(self, url: str, folder: Path, model: str, force_whisper: bool, remove_fillers: bool) -> None:
        try:
            result = transcribe_url(
                url, folder, model,
                lambda message: self.events.put(("status", message)),
                force_whisper=force_whisper,
                remove_fillers=remove_fillers,
            )
        except Exception as exc:
            self.events.put(("error", str(exc)))
        else:
            self.events.put(("done", result))

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
                    summary = f"{len(result.saved)} arquivo(s) salvos; {len(result.failed)} falha(s)."
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
        self.model_box.configure(state="readonly")
        self.whisper_checkbox.configure(state="normal")
        self.fillers_checkbox.configure(state="normal")

    def _open_result(self) -> None:
        if self.result_path and self.result_path.exists():
            os.startfile(self.result_path)


def main() -> None:
    root = tk.Tk()
    TranscriptionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
