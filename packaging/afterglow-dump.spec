# PyInstaller spec: one file on Linux and Windows, an .app on macOS.
# AFTERGLOW_DUMP_LIBCONCORD names the libconcord to carry (built from Afterglow's fork).
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
binaries = []
library = os.environ.get("AFTERGLOW_DUMP_LIBCONCORD")
if library:
    if not Path(library).is_file():
        raise SystemExit(f"AFTERGLOW_DUMP_LIBCONCORD is not a file: {library}")
    binaries.append((library, "."))

# One window of Qt Widgets: none of Qt's network, QML, PDF or SVG parts, nor its
# translations, nor the GTK theme plugin (it drags in the whole of GTK). What stays: the
# Wayland and X11 platforms and the desktop portal (native
# file dialogs) on Linux, Cocoa and Windows platforms elsewhere.
UNUSED = ("QtNetwork", "QtQml", "QtQuick", "QtPdf", "QtSvg", "QtOpenGL", "QtMultimedia",
          "QtSql", "QtTest", "QtXml", "QtPrintSupport", "QtVirtualKeyboard", "QtWebSockets")
BRANDING = ROOT / "src" / "afterglow_dump" / "branding"
analysis = Analysis([str(ROOT / "packaging" / "main.py")], pathex=[str(ROOT / "src")],
                    binaries=binaries,
                    datas=[(str(BRANDING / "dump-icon.png"), "afterglow_dump/branding")],
                    excludes=["unittest", "pydoc", "test", "tkinter",
                              *(f"PyQt6.{module}" for module in UNUSED)])


# What the GTK theme plugin brings with it from the build machine: GTK, its drawing and
# text stack, image loaders, search, and a second copy of ICU (Qt carries its own).
GTK_STACK = ("libgtk-", "libgdk-", "libgdk_pixbuf", "libglycin", "libcairo", "libpango",
             "libatk", "libatspi", "libepoxy", "libtinysparql", "libcloudproviders",
             "libjson-glib", "libseccomp", "libpixman", "liblcms2", "libxml2", "libthai",
             "libdatrie", "libsqlite3", "libicudata.so.7", "libicuuc.so.7", "libicui18n.so.7")


def wanted(entry) -> bool:
    name = entry[0].replace("\\", "/")
    base = name.rsplit("/", 1)[-1]
    if "/" not in name and base.startswith(GTK_STACK) and not base.endswith(".so.73"):
        return False
    if any(f"{module}." in name or f"{module}5" in name or f"Qt6{module[2:]}" in name
           for module in UNUSED):
        return False
    return not any(part in name for part in ("/translations/", "/qml/", "/tls/",
                                             "/imageformats/libqsvg", "/imageformats/libqpdf",
                                             "/iconengines/", "/sqldrivers/",
                                             "platformthemes/libqgtk3"))


analysis.binaries = [entry for entry in analysis.binaries if wanted(entry)]
analysis.datas = [entry for entry in analysis.datas if wanted(entry)]
pyz = PYZ(analysis.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="afterglow-dump",
              console=False, icon=str(BRANDING / "dump-icon.icns"))
    collected = COLLECT(exe, analysis.binaries, analysis.datas, name="afterglow-dump")
    app = BUNDLE(collected, name="Afterglow Dump.app", icon=str(BRANDING / "dump-icon.icns"),
                 bundle_identifier="io.github.harmonic-afterglow.afterglow-dump",
                 version=os.environ.get("AFTERGLOW_DUMP_VERSION", "0.0.0"),
                 info_plist={"NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "11.0"})
else:
    exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
              name="afterglow-dump", console=sys.platform != "win32", upx=False,
              icon=str(BRANDING / "dump-icon.ico"))
