"""Making sure this program may open the remote before it tries.

Windows: the remote needs Windows' own USB driver ("direct access") instead of
Logitech's, which `windows_driver` switches with one administrator prompt.
Linux: the signed-in user needs access to the remote's USB device, which a one-line udev
rule gives, installed with one password prompt. macOS needs nothing.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import windows_driver

RULE_PATH = "/etc/udev/rules.d/70-afterglow-dump.rules"
RULE = """\
# Lets the signed-in user open a Logitech Harmony remote over USB (Afterglow Dump).
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="046d", ATTR{idProduct}=="c1[1-4][0-9a-f]", TAG+="uaccess"
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0400", ATTR{idProduct}=="c359", TAG+="uaccess"
"""
TITLE = "Afterglow Dump"


def _harmony_nodes() -> list[Path]:
    """The device files of every Harmony plugged in (Linux)."""
    nodes = []
    for device in Path("/sys/bus/usb/devices").glob("*"):
        try:
            vendor = (device / "idVendor").read_text().strip()
            product = int((device / "idProduct").read_text().strip(), 16)
            bus = int((device / "busnum").read_text())
            number = int((device / "devnum").read_text())
        except (OSError, ValueError):
            continue
        if (vendor == "046d" and 0xC110 <= product <= 0xC14F) or \
                (vendor == "0400" and product == 0xC359):
            nodes.append(Path(f"/dev/bus/usb/{bus:03d}/{number:03d}"))
    return nodes


def _ask(parent, text: str) -> bool:
    return QMessageBox.question(parent, TITLE, text) == QMessageBox.StandardButton.Yes


def _tell(parent, text: str, warn: bool = False) -> None:
    (QMessageBox.warning if warn else QMessageBox.information)(parent, TITLE, text)


def _linux_ready(parent) -> bool:
    blocked = [node for node in _harmony_nodes() if not os.access(node, os.R_OK | os.W_OK)]
    if not blocked:
        return True          # nothing plugged in, or already allowed: let libconcord say
    if not _ask(parent, "This computer does not let programs open the remote yet. Allow "
                        "it? This asks for your password once."):
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".rules", delete=False) as handle:
        handle.write(RULE)
    install = (f'install -Dm644 "$1" {RULE_PATH} && udevadm control --reload-rules '
               f'&& udevadm trigger --subsystem-match=usb --action=change')
    try:
        if not shutil.which("pkexec"):
            _tell(parent, "Run this in a terminal, then try again:\n\n"
                          f"sudo sh -c '{install}' sh {handle.name}")
            return False
        done = subprocess.run(["pkexec", "sh", "-c", install, "sh", handle.name], check=False)
    finally:
        if shutil.which("pkexec"):
            os.unlink(handle.name)
    if done.returncode != 0:
        _tell(parent, "Nothing was changed.")
        return False
    time.sleep(1)
    if any(not os.access(node, os.R_OK | os.W_OK) for node in _harmony_nodes()):
        _tell(parent, "Done. Unplug the remote and plug it back in, then try again.")
        return False
    return True


def _windows_ready(parent) -> bool:
    try:
        found = windows_driver.remotes()
    except Exception:                                              # noqa: BLE001
        return True
    if not windows_driver.needs_switch(found):
        return True
    on = " and ".join(sorted({windows_driver.describe(remote) for remote in found}))
    if not _ask(
            parent, f"The remote is connected through {on}. Afterglow Dump talks to it "
            "directly over USB instead, using a driver that comes with Windows - faster "
            "and more reliable than Logitech's.\n\nTurn on direct access? Windows asks "
            "for administrator permission once."):
        return True          # Logitech's driver may still work
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        ok, message = windows_driver.run_elevated(windows_driver.INSTALL)
    finally:
        QApplication.restoreOverrideCursor()
    if message == windows_driver.CANCELLED:
        return True
    if not ok:
        _tell(parent, f"Direct access was not turned on.\n\n{message}", warn=True)
    return True


def ready(parent) -> bool:
    """Whether to go ahead with a backup, after offering whatever access is missing."""
    if sys.platform.startswith("linux"):
        return _linux_ready(parent)
    if sys.platform == "win32":
        return _windows_ready(parent)
    return True
