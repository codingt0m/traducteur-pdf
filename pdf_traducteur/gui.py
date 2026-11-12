"""Interface graphique (Tkinter, inclus avec Python).

Arguments facultatifs : [dossier_source] [dossier_destination] [--lancer] [--quitter]
Glisser un dossier sur l'exécutable pré-remplit la source.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .files import cache_dir, list_pdfs, output_path, report_path
from .languages import LANGUAGES
from .pipeline import translate_document
from .translators import make_translator

SETTINGS_FILE = Path(os.environ.get("APPDATA", Path.home())) / "TraducteurPDF" / "parametres.json"


def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_settings(settings: dict) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings), encoding="utf-8")
    except OSError:
        pass  # préférence non essentielle


def _lang_label(code: str) -> str:
    return f"{LANGUAGES[code]} ({code})"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Traducteur de PDF")
        self.minsize(640, 420)
        self.events: queue.Queue = queue.Queue()  # fil de travail -> interface
        self.worker: threading.Thread | None = None
        self.stop_flag = threading.Event()

        code = _load_settings().get("langue", "fr")
        self.src = tk.StringVar()
        self.dst = tk.StringVar()
        self.lang = tk.StringVar(value=_lang_label(code if code in LANGUAGES else "fr"))
        self.skip_done = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Choisissez les dossiers puis cliquez sur « Lancer ».")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.poll)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(5, weight=1)

        for row, (label, var, cmd) in enumerate(
            [("PDF à traduire :", self.src, self.pick_src), ("Destination :", self.dst, self.pick_dst)]
        ):
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", **pad)
            ttk.Entry(frm, textvariable=var).grid(row=row, column=1, sticky="ew", **pad)
            ttk.Button(frm, text="Parcourir…", command=cmd).grid(row=row, column=2, **pad)

        ttk.Label(frm, text="Langue cible :").grid(row=2, column=0, sticky="w", **pad)
        opts = ttk.Frame(frm)
        opts.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        values = [_lang_label(c) for c in LANGUAGES]
        ttk.Combobox(opts, textvariable=self.lang, values=values, state="readonly", width=26).pack(side="left")
        ttk.Checkbutton(opts, text="Ignorer les PDF déjà traduits", variable=self.skip_done).pack(
            side="left", padx=(16, 0)
        )

        bar = ttk.Frame(frm)
        bar.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)
        bar.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(bar, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.btn = ttk.Button(bar, text="Lancer", command=self.start)
        self.btn.grid(row=0, column=1)
        ttk.Button(bar, text="Ouvrir la destination", command=self.open_dst).grid(row=0, column=2, padx=(8, 0))

        ttk.Label(frm, textvariable=self.status).grid(row=4, column=0, columnspan=3, sticky="w", **pad)

        logf = ttk.Frame(frm)
        logf.grid(row=5, column=0, columnspan=3, sticky="nsew", **pad)
        self.log = tk.Text(logf, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---- choix -------------------------------------------------------------
    def target(self) -> str:
        v = self.lang.get()
        return v[v.rfind("(") + 1 : -1] if "(" in v else "fr"

    def pick_src(self) -> None:
        d = filedialog.askdirectory(title="Dossier contenant les PDF à traduire", initialdir=self.src.get() or None)
        if d:
            self.src.set(d)
            if not self.dst.get():
                self.dst.set(str(Path(d) / "traductions"))

    def pick_dst(self) -> None:
        d = filedialog.askdirectory(title="Dossier de destination", initialdir=self.dst.get() or self.src.get() or None)
        if d:
            self.dst.set(d)

    def open_dst(self) -> None:
        d = Path(self.dst.get())
        if d.is_dir():
            os.startfile(d)  # Windows uniquement

    # ---- traitement --------------------------------------------------------
    def start(self) -> None:
        src_txt, dst_txt = self.src.get().strip(), self.dst.get().strip()
        if not src_txt or not Path(src_txt).is_dir():
            messagebox.showerror("Dossier source", "Choisissez un dossier source existant.")
            return
        if not dst_txt:
            messagebox.showerror("Destination", "Choisissez un dossier de destination.")
            return
        src, dst, target = Path(src_txt), Path(dst_txt), self.target()
        _save_settings({"langue": target})

        files = [f for f in list_pdfs([src]) if f.parent != dst]  # ne pas retraduire les sorties
        if self.skip_done.get():
            files = [f for f in files if not output_path(f, dst, target).exists()]
        if not files:
            messagebox.showinfo("Rien à faire", "Aucun PDF à traduire dans ce dossier (ou tous déjà traduits).")
            return

        dst.mkdir(parents=True, exist_ok=True)
        self.btn.configure(state="disabled")
        self.progress.configure(maximum=len(files), value=0)
        self.clear_log()
        self.stop_flag.clear()
        self.worker = threading.Thread(target=self.run, args=(files, dst, target), daemon=True)
        self.worker.start()

    def run(self, files: list[Path], dst: Path, target: str) -> None:
        """Fil de travail : ne touche jamais aux widgets, passe par self.events."""
        t0, ok, ko = time.time(), 0, 0
        translator = make_translator(target, cache_dir=cache_dir(dst))
        self.events.put(("log", f"Langue cible : {_lang_label(target)}"))
        for i, f in enumerate(files, 1):
            if self.stop_flag.is_set():
                break
            out = output_path(f, dst, target)
            self.events.put(("status", f"[{i}/{len(files)}] {f.name}"))
            self.events.put(("log", f"• {f.name}"))
            try:
                s = translate_document(
                    f, out, translator, report_path=report_path(f, dst), log=lambda m: self.events.put(("log", m))
                )
                n = sum(v for k, v in s["statuts"].items() if k.startswith("traduit"))
                self.events.put(("log", f"  ✔ {out.name} ({s['duree_s']} s, {n} paragraphes traduits)"))
                ok += 1
            except Exception as e:  # un PDF défaillant ne doit pas arrêter les suivants
                ko += 1
                self.events.put(("log", f"  ✘ échec : {e}\n{traceback.format_exc(limit=3)}"))
            self.events.put(("progress", i))
        self.events.put(("done", (ok, ko, time.time() - t0)))

    def poll(self) -> None:
        try:
            while True:
                kind, val = self.events.get_nowait()
                if kind == "log":
                    self.append_log(val)
                elif kind == "status":
                    self.status.set(val)
                elif kind == "progress":
                    self.progress.configure(value=val)
                elif kind == "done":
                    ok, ko, dt = val
                    self.btn.configure(state="normal")
                    msg = f"Terminé en {dt:.0f} s : {ok} PDF traduit(s)" + (f", {ko} échec(s)" if ko else "") + "."
                    self.status.set(msg)
                    self.append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    # ---- journal -----------------------------------------------------------
    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Traduction en cours", "Une traduction est en cours. Quitter quand même ?"):
                return
            self.stop_flag.set()
        self.destroy()

    def quit_when_done(self) -> None:
        if self.worker is not None and not self.worker.is_alive() and self.events.empty():
            self.destroy()
        else:
            self.after(500, self.quit_when_done)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    try:  # rendu net sur les écrans avec mise à l'échelle Windows
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (ImportError, AttributeError, OSError):
        pass
    app = App()
    paths = [a for a in argv if not a.startswith("--")]
    if paths:
        app.src.set(paths[0])
        app.dst.set(paths[1] if len(paths) > 1 else str(Path(paths[0]) / "traductions"))
    if "--lancer" in argv:
        app.after(300, app.start)
    if "--quitter" in argv:
        app.after(1000, app.quit_when_done)
    app.mainloop()


if __name__ == "__main__":
    main()
