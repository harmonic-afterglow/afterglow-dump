"""The few libconcord calls a dump needs: find the remote, say what it is, read it.

Every call runs on one long-lived thread. hidapi ties its macOS device manager to the
thread that first initialised it and libconcord never releases it, so calls from
short-lived threads crash on Apple Silicon.
"""
from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import queue
import shutil
import sys
import tempfile
import threading
from concurrent.futures import Future
from pathlib import Path

LIBRARY_NAMES = (
    "libconcord.so.6", "libconcord.so",
    "libconcord.6.dylib", "libconcord.dylib",
    "libconcord-6.dll", "libconcord.dll",
)
LC_CALLBACK = ctypes.CFUNCTYPE(
    None, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
    ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
STAGES = {7: "Identifying the remote", 14: "Reading the configuration"}


class NotAvailable(RuntimeError):
    pass


class RemoteError(RuntimeError):
    pass


def _candidates():
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        for pattern in ("libconcord*.so*", "libconcord*.dylib", "*concord*.dll"):
            yield from sorted(Path(bundled).glob(pattern))
    yield from LIBRARY_NAMES
    found = ctypes.util.find_library("concord")
    if found:
        yield found


def _load():
    for candidate in _candidates():
        try:
            return ctypes.CDLL(str(candidate))
        except OSError:
            continue
    raise NotAvailable("libconcord was not found. Use the download from the releases "
                       "page, which includes it.")


class _LibraryThread:
    """Calls into the library, each made on the one thread libconcord runs on.

    A daemon, so it outlives interpreter shutdown: libconcord releases hidapi from a C
    atexit handler, which must still find the thread hidapi was scheduled on.
    """

    NAME = "libconcord"
    _queue = None
    _lock = threading.Lock()

    @classmethod
    def _serve(cls, jobs):
        while True:
            future, function, args = jobs.get()
            try:
                future.set_result(function(*args))
            except BaseException as exc:                           # noqa: BLE001
                future.set_exception(exc)

    @classmethod
    def call(cls, function, *args):
        if threading.current_thread().name == cls.NAME:
            return function(*args)
        with cls._lock:
            if cls._queue is None:
                cls._queue = queue.SimpleQueue()
                threading.Thread(target=cls._serve, args=(cls._queue,), name=cls.NAME,
                                 daemon=True).start()
        future = Future()
        cls._queue.put((future, function, args))
        return future.result()


_lib = None


def _library():
    global _lib
    if _lib is None:
        lib = _load()
        for name, restype, argtypes in (
            ("init_concord", ctypes.c_int, []),
            ("deinit_concord", ctypes.c_int, []),
            ("lc_strerror", ctypes.c_char_p, [ctypes.c_int]),
            ("get_mfg", ctypes.c_char_p, []),
            ("get_model", ctypes.c_char_p, []),
            ("get_skin", ctypes.c_int, []),
            ("get_arch", ctypes.c_int, []),
            ("get_fw_ver_maj", ctypes.c_int, []),
            ("get_fw_ver_min", ctypes.c_int, []),
            ("is_config_dump_supported", ctypes.c_int, []),
            ("get_identity", ctypes.c_int, [LC_CALLBACK, ctypes.c_void_p]),
            ("read_config_from_remote", ctypes.c_int,
             [ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
              ctypes.POINTER(ctypes.c_uint32), LC_CALLBACK, ctypes.c_void_p]),
            ("delete_blob", None, [ctypes.POINTER(ctypes.c_uint8)]),
            ("write_config_to_file", ctypes.c_int,
             [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32, ctypes.c_char_p,
              ctypes.c_int]),
        ):
            function = getattr(lib, name)
            function.restype, function.argtypes = restype, argtypes
        _lib = lib
    return _lib


def available() -> bool:
    try:
        _library()
        return True
    except NotAvailable:
        return False


def _callback(on_progress):
    def relay(stage, _count, current, total, _kind, _arg, _stages):
        if on_progress:
            with contextlib.suppress(Exception):   # a failing window must not stop a read
                on_progress(STAGES.get(stage, "Working"), current, total)
    return LC_CALLBACK(relay)


def _native(path) -> bytes:
    """A path as libconcord's C `fopen` reads it: the ANSI code page on Windows."""
    if os.name == "nt":
        return str(path).encode("mbcs", "strict")
    return os.fsencode(str(path))


@contextlib.contextmanager
def _staged():
    """A file path libconcord can open; the user's own path may not be one."""
    parents = [tempfile.gettempdir()] + [os.environ[name] for name in ("PUBLIC", "ProgramData")
                                         if os.environ.get(name)]
    for parent in parents:
        try:
            _native(parent)
            folder = Path(tempfile.mkdtemp(prefix="afterglow-dump-", dir=parent))
        except (UnicodeEncodeError, OSError):
            continue
        try:
            yield folder / "remote.ezhex"
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return
    raise RemoteError("No temporary folder libconcord can open; set TMP to a plain "
                      "folder such as C:\\Temp.")


def _check(lib, err, what):
    if err:
        message = lib.lc_strerror(err)
        raise RemoteError(f"{what}: {message.decode() if message else f'error {err}'}")


def _dump(path: Path, on_progress) -> dict:
    lib = _library()
    _check(lib, lib.init_concord(), "Could not find the remote")
    try:
        callback = _callback(on_progress)
        _check(lib, lib.get_identity(callback, None), "Could not identify the remote")

        def text(value):
            return value.decode(errors="replace") if value else ""
        identity = {
            "mfg": text(lib.get_mfg()), "model": text(lib.get_model()),
            "skin": lib.get_skin(), "arch": lib.get_arch(),
            "firmware": f"{lib.get_fw_ver_maj()}.{lib.get_fw_ver_min()}",
        }
        if path is None:
            return identity
        if lib.is_config_dump_supported() != 0:
            raise RemoteError(f"libconcord cannot read the configuration of a "
                              f"{identity['model']}.")
        blob = ctypes.POINTER(ctypes.c_uint8)()
        size = ctypes.c_uint32()
        _check(lib, lib.read_config_from_remote(ctypes.byref(blob), ctypes.byref(size),
                                                callback, None),
               "Could not read the configuration")
        try:
            with _staged() as staged:
                # write_config_to_file adds the header the file needs to be read back.
                _check(lib, lib.write_config_to_file(blob, size.value, _native(staged), 0),
                       "Could not save the configuration")
                shutil.move(str(staged), str(path))
        finally:
            lib.delete_blob(blob)
        identity["bytes"] = size.value
        return identity
    finally:
        lib.deinit_concord()


def identify(on_progress=None) -> dict:
    """What remote is plugged in: `{"mfg", "model", "skin", "arch", "firmware"}`."""
    return _LibraryThread.call(_dump, None, on_progress)


def dump(path, on_progress=None) -> dict:
    """Read the remote's configuration into `path`; returns its identity and size."""
    return _LibraryThread.call(_dump, Path(path), on_progress)
