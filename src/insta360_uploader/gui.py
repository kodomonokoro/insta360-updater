"""Tkinter GUI: list videos in a folder, select which to process, run.

VideoBrowserFrame is intentionally generic (a scan function + an execute
function passed in) so that once the Insta360-SDK half of this tool exists,
browsing the camera itself can reuse the exact same widget as a second tab
— this NAS-folder tab is meant to stay around, not be replaced by it.
"""
from __future__ import annotations

import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from insta360_uploader.config import AppConfig, ConfigError, load_config
from insta360_uploader.gdrive_uploader import DriveError
from insta360_uploader.gdrive_uploader import run_oauth_flow as run_gdrive_oauth_flow
from insta360_uploader.nas_scanner import VideoFile, scan_video_folder
from insta360_uploader.pipeline import ProgressFn, process_videos
from insta360_uploader.pipeline_display import build_pipeline_text
from insta360_uploader.processed_store import ProcessedStore
from insta360_uploader.video_info import format_duration, format_size, probe_duration_seconds
from insta360_uploader.youtube_uploader import UploadError
from insta360_uploader.youtube_uploader import run_oauth_flow as run_youtube_oauth_flow

Logger = Callable[[str], None]
ExecuteFn = Callable[[list[VideoFile], Logger, ProgressFn], None]
ScanFn = Callable[[], list[VideoFile]]

_UNCHECKED = "☐"  # ☐
_CHECKED = "☑"  # ☑
_SEL_COLUMN = "sel"
_LOG_KEY_RE = re.compile(r"^\[([^\]]+)\] (.*)$")


class VideoBrowserFrame(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        scan_fn: ScanFn,
        store: ProcessedStore,
        on_execute: ExecuteFn,
        drive_enabled: bool,
    ):
        super().__init__(parent)
        self._scan_fn = scan_fn
        self._store = store
        self._on_execute = on_execute
        self._drive_enabled = drive_enabled
        self._videos: list[VideoFile] = []
        self._checked: dict[str, bool] = {}
        self._drive_skip_keys: set[str] = set()
        self._event_queue: queue.Queue[tuple] = queue.Queue()

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        self._refresh_btn = ttk.Button(toolbar, text="↻ 更新", command=self.refresh)
        self._refresh_btn.pack(side="left")
        self._run_btn = ttk.Button(toolbar, text="実行", command=self._on_run_clicked)
        self._run_btn.pack(side="left", padx=(6, 0))

        current_frame = ttk.LabelFrame(self, text="現在処理中")
        current_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._current_label = ttk.Label(current_frame, text="(待機中)", font=("", 11, "bold"))
        self._current_label.pack(anchor="w", padx=6, pady=4)

        progress_frame = ttk.Frame(self)
        progress_frame.pack(fill="x", padx=8, pady=(0, 4))
        progress_frame.columnconfigure(1, weight=1)
        ttk.Label(progress_frame, text="全体").grid(row=0, column=0, sticky="w")
        self._overall_progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self._overall_progress.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Label(progress_frame, text="個別").grid(row=1, column=0, sticky="w")
        self._file_progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self._file_progress.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self._tree = ttk.Treeview(
            tree_frame,
            columns=(_SEL_COLUMN, "key", "duration", "size", "status"),
            show="headings",
            height=12,
        )
        self._tree.heading(_SEL_COLUMN, text="全選択/解除", command=self._toggle_select_all)
        self._tree.heading("key", text="ファイル")
        self._tree.heading("duration", text="長さ")
        self._tree.heading("size", text="サイズ")
        self._tree.heading("status", text="進行状況")
        self._tree.column(_SEL_COLUMN, width=90, anchor="center", stretch=False)
        self._tree.column("key", width=220)
        self._tree.column("duration", width=70, anchor="e", stretch=False)
        self._tree.column("size", width=70, anchor="e", stretch=False)
        self._tree.column("status", width=320, stretch=False)
        self._tree.bind("<Button-1>", self._on_tree_click)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        ttk.Label(self, text="ログ").pack(anchor="w", padx=8)
        self._log = ScrolledText(self, height=10, state="disabled")
        self._log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.refresh()

    def refresh(self) -> None:
        try:
            self._videos = self._scan_fn()
        except FileNotFoundError as exc:
            messagebox.showerror("フォルダが見つかりません", str(exc))
            self._videos = []

        self._checked = {v.key: self._checked.get(v.key, False) for v in self._videos}

        self._tree.delete(*self._tree.get_children())
        for video in self._videos:
            self._tree.insert("", tk.END, iid=video.key, values=self._row_values(video))

    def _row_values(self, video: VideoFile) -> tuple[str, str, str, str, str]:
        record = self._store.get(video.key)
        status = build_pipeline_text(record, self._drive_enabled)

        duration_seconds = probe_duration_seconds(video.path)
        duration_str = format_duration(duration_seconds) if duration_seconds is not None else "—"

        try:
            size_str = format_size(video.path.stat().st_size)
        except OSError:
            size_str = "—"

        glyph = _CHECKED if self._checked.get(video.key) else _UNCHECKED
        return (glyph, video.key, duration_str, size_str, status)

    def _on_tree_click(self, event: tk.Event) -> None:
        if self._tree.identify_region(event.x, event.y) != "cell":
            return
        if self._tree.identify_column(event.x) != "#1":  # the sel column
            return
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._checked[row] = not self._checked.get(row, False)
        self._tree.set(row, _SEL_COLUMN, _CHECKED if self._checked[row] else _UNCHECKED)

    def _toggle_select_all(self) -> None:
        select_all = not all(self._checked.values()) if self._checked else True
        for key in self._checked:
            self._checked[key] = select_all
            self._tree.set(key, _SEL_COLUMN, _CHECKED if select_all else _UNCHECKED)

    def _log_line(self, message: str) -> None:
        # called from the worker thread; hand off to the main thread via queue
        self._event_queue.put(("log", message))

    def _progress_update(self, completed: int, total: int, fraction: float) -> None:
        self._event_queue.put(("progress", completed, total, fraction))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self._event_queue.get_nowait()
                if event[0] == "log":
                    _, message = event
                    self._log.configure(state="normal")
                    self._log.insert(tk.END, message + "\n")
                    self._log.see(tk.END)
                    self._log.configure(state="disabled")
                    self._apply_log_line_to_ui(message)
                elif event[0] == "progress":
                    _, completed, total, fraction = event
                    overall_pct = ((completed + fraction) / total * 100) if total else 0
                    self._overall_progress["value"] = overall_pct
                    self._file_progress["value"] = fraction * 100
        except queue.Empty:
            pass

    def _apply_log_line_to_ui(self, message: str) -> None:
        if message == "--- 完了 ---":
            self._current_label.configure(text="(待機中)")
            return

        match = _LOG_KEY_RE.match(message)
        if not match:
            return
        key, rest = match.group(1), match.group(2)
        self._current_label.configure(text=f"{key}: {rest}")

        if "skip" in rest.lower():
            self._drive_skip_keys.add(key)

        if self._tree.exists(key):
            record = self._store.get(key)
            text = build_pipeline_text(record, self._drive_enabled)
            if key in self._drive_skip_keys:
                # Distinguish "already there, left untouched" from an
                # actual upload this run — a checkmark would look like we
                # did the work when we didn't.
                text = text.replace("✓Drive", "−Drive")
            self._tree.set(key, "status", text)

    def _on_run_clicked(self) -> None:
        selected_keys = [key for key, checked in self._checked.items() if checked]
        if not selected_keys:
            messagebox.showinfo("選択なし", "処理対象の動画を選んでください。")
            return

        videos_by_key = {v.key: v for v in self._videos}
        selected = [videos_by_key[key] for key in selected_keys if key in videos_by_key]

        self._run_btn.configure(state="disabled")
        self._refresh_btn.configure(state="disabled")
        self._overall_progress["value"] = 0
        self._file_progress["value"] = 0
        self._current_label.configure(text="準備中...")
        self._drive_skip_keys.clear()

        # Clear any stale ✓/− from a previous run before this one starts,
        # so a re-run doesn't briefly look like it's already done.
        blank_status = build_pipeline_text(None, self._drive_enabled)
        for video in selected:
            if self._tree.exists(video.key):
                self._tree.set(video.key, "status", blank_status)

        def worker() -> None:
            try:
                self._on_execute(selected, self._log_line, self._progress_update)
            except Exception as exc:  # surface unexpected errors instead of dying silently
                self._log_line(f"予期しないエラー: {exc}")
            finally:
                self._log_line("--- 完了 ---")

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()
        self._poll_worker()

    def _poll_worker(self) -> None:
        self._drain_events()
        if self._worker_thread.is_alive():
            self.after(200, self._poll_worker)
        else:
            self._run_btn.configure(state="normal")
            self._refresh_btn.configure(state="normal")
            # Processed items shouldn't stay checked — leaving them checked
            # invites accidentally re-running them next time.
            self._checked.clear()
            self.refresh()


class App(tk.Tk):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.title("insta360-uploader")
        self.geometry("820x650")
        self._config = config

        auth_bar = ttk.Frame(self)
        auth_bar.pack(fill="x", padx=8, pady=(8, 0))
        self._youtube_auth_btn = ttk.Button(
            auth_bar, text="YouTube認証", command=self._on_auth_youtube_clicked
        )
        self._youtube_auth_btn.pack(side="left")
        self._youtube_auth_label = tk.Label(auth_bar, text="")
        self._youtube_auth_label.pack(side="left", padx=(6, 16))

        if config.drive is not None:
            self._drive_auth_btn = ttk.Button(
                auth_bar, text="Google Drive認証", command=self._on_auth_gdrive_clicked
            )
            self._drive_auth_btn.pack(side="left")
            self._drive_auth_label = tk.Label(auth_bar, text="")
            self._drive_auth_label.pack(side="left", padx=(6, 0))

        self._update_auth_labels()

        store = ProcessedStore()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        nas_tab = VideoBrowserFrame(
            notebook,
            scan_fn=lambda: scan_video_folder(config.nas_video_folder),
            store=store,
            on_execute=lambda videos, log, on_progress: process_videos(
                videos, config, store, log, on_progress=on_progress
            ),
            drive_enabled=config.drive is not None,
        )
        notebook.add(nas_tab, text="NASフォルダ")

    def _update_auth_labels(self) -> None:
        youtube_ok = self._config.youtube.token_path.is_file()
        self._youtube_auth_label.configure(
            text="✓ 認証済み" if youtube_ok else "未認証",
            fg="dark green" if youtube_ok else "red",
        )
        if self._config.drive is not None:
            drive_ok = self._config.drive.token_path.is_file()
            self._drive_auth_label.configure(
                text="✓ 認証済み" if drive_ok else "未認証",
                fg="dark green" if drive_ok else "red",
            )

    def _on_auth_youtube_clicked(self) -> None:
        self._youtube_auth_btn.configure(state="disabled")

        def worker() -> None:
            try:
                run_youtube_oauth_flow(self._config.youtube)
            except UploadError as exc:
                self.after(0, lambda: messagebox.showerror("認証エラー", str(exc)))
            else:
                self.after(
                    0, lambda: messagebox.showinfo("認証完了", "YouTubeの認証が完了しました。")
                )
            finally:
                self.after(0, lambda: self._youtube_auth_btn.configure(state="normal"))
                self.after(0, self._update_auth_labels)

        threading.Thread(target=worker, daemon=True).start()

    def _on_auth_gdrive_clicked(self) -> None:
        assert self._config.drive is not None
        self._drive_auth_btn.configure(state="disabled")

        def worker() -> None:
            try:
                run_gdrive_oauth_flow(self._config.drive)
            except DriveError as exc:
                self.after(0, lambda: messagebox.showerror("認証エラー", str(exc)))
            else:
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "認証完了", "Google Driveの認証が完了しました。"
                    ),
                )
            finally:
                self.after(0, lambda: self._drive_auth_btn.configure(state="normal"))
                self.after(0, self._update_auth_labels)

        threading.Thread(target=worker, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    config_path = argv[0] if argv else "config.yaml"

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        messagebox.showerror("設定エラー", str(exc))
        return 1

    app = App(config)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
