# Afterglow Dump

Back up a Logitech Harmony remote, and make a copy of the backup that is safe to share.

Made by the [Afterglow](https://github.com/harmonic-afterglow/afterglow) project, which
builds configurations for Harmony remotes now that Logitech's service is gone. Copies
people share help it support more remotes.

## Using it

1. Plug the remote in with its USB cable and wait until its screen says it is connected.
2. Press **Back up my remote…** and choose where to save. This is your remote exactly as
   it is: keep it, it is how you get back to where you started. It is private.
3. When the backup is saved, it offers to **make a copy to share**. You can type the name
   and email you used with Logitech (optional) so it can look for them everywhere.

Already have a backup? **Clean an existing backup…** makes the copy to share from it.

Afterglow Dump never connects to the internet and sends nothing anywhere: you decide
what to share, and with whom.

## What the copy to share leaves out

Your name, your Logitech account ID and email addresses. Your devices, activities and
buttons stay - they are what makes a copy useful.

- In the zip-based format of the Harmony 900, 1000 and 1100, it cleans the places the
  owner is recorded, and any name, email, phone, address or account field.
- In every format it then searches the whole file for what it found and for what you
  typed, as whole words and in the text encodings these files use.
- Everything is replaced by a filler of exactly the same length, so nothing else in the
  file moves.

If the format is one it does not know, or it found nothing in the usual places, it tells
you it cannot be sure it found everything - check with whoever you share it with.

## Download

Get the file for your system from the [Releases](../../releases) page. Nothing else
needs installing.

- **Windows** (`afterglow-dump-windows-x86_64.exe`): run it. For a Harmony 900, 1000 or
  1100 it offers to turn on *direct access* the first time: it then talks to the remote
  through a USB driver that comes with Windows, which is faster and more reliable than
  Logitech's. Windows asks for administrator permission once.
- **macOS** (`afterglow-dump-macos-arm64.zip`, Apple Silicon): unzip it and open the
  app - no need to move it to Applications. It is not notarized, so the first time
  macOS refuses: go to System Settings > Privacy & Security and choose Open Anyway.
- **Linux** (`afterglow-dump-linux-x86_64`): make it executable
  (`chmod +x afterglow-dump-linux-x86_64`) and run it. If the remote cannot be opened
  yet, it offers to allow it, which asks for your password once.

Every Harmony remote that connects over USB and that Concordance can read should work.
It has been tested with a Harmony 900.

## Command line

    afterglow-dump --backup my-remote.ezhex
    afterglow-dump --share my-remote.ezhex my-copy.ezhex [--name "Your Name"] [--email you@example.com]

## Building

Needs Python 3.11 or later with PyQt6, and libconcord from Afterglow's fork of
Concordance ([harmonic-afterglow/concordance](https://github.com/harmonic-afterglow/concordance),
branch `usbnet-link`), which reaches the Harmony 900, 1000 and 1100 over USB without any
driver. `.github/workflows/build.yml` builds all three systems.

    pip install -e ".[dev]"
    pytest

## License

GPL-3.0-or-later.
