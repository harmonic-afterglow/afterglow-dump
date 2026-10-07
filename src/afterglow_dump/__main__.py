"""afterglow-dump [--backup FILE | --share BACKUP COPY [--name N] [--email E]]

With no arguments, opens the window.
"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--usb-driver" in argv:                 # the elevated half of the Windows switch
        from .windows_driver import main as usb_driver
        return usb_driver(argv)
    if "--version" in argv:
        from . import __version__
        print(__version__)
        return 0
    if "--self-check" in argv:
        from . import concord
        lib = concord._library()
        link = hasattr(lib, "_Z15UsbNetLink_Openj")
        print(f"libconcord: loaded ({lib._name}), USB link: {link}")
        return 0 if link else 1
    if "--backup" in argv:
        from . import concord
        target = argv[argv.index("--backup") + 1]
        said = set()

        def say(stage, *_):
            if stage not in said:
                said.add(stage)
                print(f"{stage}...")
        print("Connecting to the remote...")
        identity = concord.dump(target, say)
        print(f"Saved a backup of your {identity['model']} ({identity['bytes']:,} bytes) "
              f"to {target}")
        return 0
    if "--share" in argv:
        from . import clean
        source, target = argv[argv.index("--share") + 1: argv.index("--share") + 3]
        extra = tuple(argv[argv.index(flag) + 1] for flag in ("--name", "--email")
                      if flag in argv)
        extra += tuple(argv[argv.index("--name") + 1].split()) if "--name" in argv else ()
        result = clean.make_shareable(source, target, extra)
        for line in result.removed:
            print(f"Removed: {line}")
        if result.found_elsewhere:
            print(f"Also replaced in {result.found_elsewhere} other places")
        if not result.known_format:
            print("This remote's format is not fully known: check before sharing.")
        print(f"Saved {target}")
        return 0
    if argv:
        print(__doc__)
        return 2
    from .app import main as window
    return window()


if __name__ == "__main__":
    raise SystemExit(main())
