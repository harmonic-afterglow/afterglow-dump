"""The window: back up the remote, and make a copy to share."""
from __future__ import annotations

import datetime
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, access, clean, concord

TITLE = "Afterglow Dump"
UNKNOWN_FORMAT = (
    "Afterglow Dump did not find your details where it knows to look, so it searched the "
    "whole file instead. It cannot promise it found every place they are kept - check "
    "with the person you share it with first.")


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: gray;")
    return label


class ExtraDialog(QDialog):
    """The person's name and email, to search for as well. Both optional."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Make a copy to share")
        layout = QVBoxLayout(self)
        intro = QLabel("Afterglow Dump removes your name, Logitech account ID and email "
                       "addresses. To be thorough, type the name and email you used with "
                       "Logitech too - it searches the whole file for them. Both optional.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.name, self.email = QLineEdit(), QLineEdit()
        form.addRow("Your name", self.name)
        form.addRow("Your email", self.email)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continue")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, ...]:
        name, email = self.name.text().strip(), self.email.text().strip()
        # A full name is also searched for word by word.
        return tuple(value for value in (name, email, *name.split()) if value)


class _Signals(QObject):
    status = pyqtSignal(str)
    finished = pyqtSignal(object, object)       # result, error


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.last_dump: Path | None = None
        self._target: Path | None = None
        self.signals = _Signals()
        self.signals.status.connect(lambda text: self.status.setText(text))
        self.signals.finished.connect(self._backed_up)

        layout = QVBoxLayout(self)
        self.status = QLabel("Plug your Harmony in with its USB cable, wait for its screen "
                             "to say it is connected, then press Back up my remote.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.backup = QPushButton("Back up my remote…")
        self.backup.setDefault(True)
        self.backup.clicked.connect(self.do_backup)
        layout.addWidget(self.backup)
        layout.addWidget(_hint("Saves your remote exactly as it is - keep that file "
                               "private. Then it offers to make a copy you can share."))
        layout.addSpacing(8)
        self.share = QPushButton("Clean an existing backup…")
        self.share.clicked.connect(lambda: self.do_share())
        layout.addWidget(self.share)
        layout.addWidget(_hint("Already have a backup? Make a copy of it to share, with "
                               "your name, account ID and email addresses removed."))
        layout.addSpacing(8)
        layout.addWidget(_hint(f"Version {__version__}"))
        self.setFixedWidth(self.fontMetrics().averageCharWidth() * 62)

    def _busy(self, busy: bool):
        self.backup.setEnabled(not busy)
        self.share.setEnabled(not busy)
        self.progress.setVisible(busy)

    # backing up -------------------------------------------------------------------------
    def do_backup(self):
        if not access.ready(self):
            return
        stamp = datetime.datetime.now().astimezone().date().isoformat()
        target, _ = QFileDialog.getSaveFileName(
            self, "Save the backup", str(Path.home() / f"harmony-backup-{stamp}.ezhex"),
            "Harmony configuration (*.ezhex)")
        if not target:
            return
        self._target = Path(target)
        self._busy(True)
        self.status.setText("Connecting to the remote… (this can take up to 20 seconds)")

        def work():
            try:
                result = concord.dump(self._target,
                                      lambda stage, *_: self.signals.status.emit(f"{stage}…"))
                self.signals.finished.emit(result, None)
            except Exception as exc:                               # noqa: BLE001
                self.signals.finished.emit(None, exc)
        threading.Thread(target=work, daemon=True).start()

    def _backed_up(self, identity, error):
        self._busy(False)
        if error:
            self.status.setText("The backup did not work.")
            QMessageBox.critical(self, TITLE, f"{error}\n\nCheck the remote is plugged in "
                                 "and its screen says it is connected, then try again.")
            return
        self.last_dump = self._target
        self.status.setText(f"Saved a backup of your {identity['model']} "
                            f"({identity['bytes']:,} bytes) to {self._target.name}.")
        answer = QMessageBox.question(self, TITLE, "Your backup is saved. Make a copy to "
                                      "share as well?")
        if answer == QMessageBox.StandardButton.Yes:
            self.do_share(self._target)

    # sharing ----------------------------------------------------------------------------
    def do_share(self, source: Path | None = None):
        if source is None:
            start = str(self.last_dump.parent) if self.last_dump else str(Path.home())
            name, _ = QFileDialog.getOpenFileName(
                self, "Choose a backup to make a shareable copy of", start,
                "Harmony configuration (*.ezhex *.EZHex);;All files (*)")
            if not name:
                return
            source = Path(name)
        extra = ExtraDialog(self)
        if not extra.exec():
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Save the copy to share",
            str(source.parent / f"{source.stem}-shareable.ezhex"),
            "Harmony configuration (*.ezhex)")
        if not target:
            return
        try:
            result = clean.make_shareable(source, target, extra.values())
        except (clean.NotShareable, ValueError, OSError) as exc:
            QMessageBox.critical(self, TITLE, str(exc))
            return
        self.status.setText(f"Saved {Path(target).name}.")
        removed = "\n".join(f"- {line}" for line in result.lines()) or "- Nothing was found"
        if result.known_format:
            QMessageBox.information(self, TITLE, f"Removed from the copy:\n\n{removed}"
                                    "\n\nIt is safe to share.")
        else:
            QMessageBox.warning(self, TITLE, f"Removed from the copy:\n\n{removed}\n\n"
                                + UNKNOWN_FORMAT)


def main():
    app = QApplication([])
    app.setApplicationName(TITLE)
    app.setDesktopFileName("afterglow-dump")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "branding" / "dump-icon.png")))
    window = Window()
    window.show()
    return app.exec()
