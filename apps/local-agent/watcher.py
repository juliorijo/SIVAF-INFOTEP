from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterable, Optional


class ScannerWatcher:
    """Observa una carpeta local del escáner y detecta nuevos PDFs."""

    def __init__(self, monitored_dir: str, callback: Optional[Callable[[str], None]] = None, poll_interval: float = 2.0):
        self.monitored_dir = Path(monitored_dir)
        self.callback = callback
        self.poll_interval = poll_interval
        self._seen_files: set[str] = set()

    def _iter_pdf_files(self) -> Iterable[Path]:
        if not self.monitored_dir.exists():
            return []
        return [
            path for path in self.monitored_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        ]

    def scan_once(self) -> list[str]:
        findings: list[str] = []
        for path in self._iter_pdf_files():
            path_str = str(path.resolve())
            if path_str not in self._seen_files:
                self._seen_files.add(path_str)
                findings.append(path_str)
                if self.callback is not None:
                    self.callback(path_str)
        return findings

    def watch(self, stop_after: Optional[int] = None) -> list[str]:
        discovered: list[str] = []
        iterations = 0

        while True:
            new_files = self.scan_once()
            if new_files:
                discovered.extend(new_files)

            if stop_after is not None and iterations >= stop_after:
                break

            iterations += 1
            time.sleep(self.poll_interval)

        return discovered
