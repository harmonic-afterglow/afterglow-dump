"""A copy of a Harmony dump that is safe to share.

The dump's payload is recognised by its format, not by the remote: a zip (the "PK"
format of the 900/1000/1100 family) is unpacked and its known locations cleaned - the
owner block in any XML file, and personal fields such as names, email, phone, address,
user and account IDs. Then every value found there, plus any name or email the person
typed, is searched for in every byte of the dump - in the text encodings these files
use, as whole words - and replaced with a filler of the same length, so nothing moves.
A format with no known locations, or one where nothing was found in them, gets only
that search. Email addresses are found by their shape anywhere. Devices, activities and
buttons are kept.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

USER_CONFIG = "userconfig/UserConfiguration.xml"
OWNER = {"Id": "Your Logitech account ID", "FirstName": "Your first name",
         "LastName": "Your last name"}
PERSONAL_TAGS = ("FirstName", "LastName", "FullName", "UserName", "OwnerName", "Email",
                 "EMail", "EmailAddress", "Phone", "PhoneNumber", "Address", "Street",
                 "City", "PostalCode", "ZipCode", "UserId", "AccountId", "LoginName")
ENCODINGS = ("utf-8", "latin-1", "utf-16-le", "utf-16-be")
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
EMAIL_UTF16 = re.compile(rb"(?:[A-Za-z0-9._%+-]\x00)+@\x00(?:[A-Za-z0-9-]\x00)+"
                         rb"(?:\.\x00(?:[A-Za-z0-9-]\x00)+)+")
_CLOSE = b"</INFORMATION>"


class NotShareable(ValueError):
    pass


@dataclass
class Result:
    removed: list[str] = field(default_factory=list)
    found_elsewhere: int = 0            # extra matches the byte search replaced
    known_format: bool = False          # found the owner in a known location


def _split(raw: bytes) -> tuple[bytes, bytes]:
    end = raw.find(_CLOSE)
    if end < 0:
        raise NotShareable("This is not a Harmony configuration file.")
    start = end + len(_CLOSE)
    while start < len(raw) and raw[start] in (10, 13):
        start += 1
    return raw[:start], raw[start:]


def checksum(payload: bytes) -> int:
    value = 0x69
    for byte in payload:
        value ^= byte
    return value


def _filler(value: str, char: str = "x") -> str:
    """A replacement taking exactly as many UTF-8 bytes as `value`, so nothing moves."""
    return char * len(value.encode("utf-8"))


def _blank(value: str) -> bool:
    """Empty, or already a filler."""
    return not value.strip() or set(value.strip()) <= {"x"} or set(value.strip()) <= {"0"}


def _structured(text: str, secrets: set[str], removed: list[str]):
    """Clear the known personal fields of one XML file, remembering their values."""
    # The owner block; from the end, so earlier positions stay valid.
    for block in reversed(list(re.finditer(r"<User>.*?</User>", text, re.DOTALL))):
        user = block.group(0)
        for tag, label in OWNER.items():
            found = re.search(rf"<{tag}>([^<]*)</{tag}>", user)
            if found and not _blank(found.group(1)):
                secrets.add(found.group(1).strip())
                filler = _filler(found.group(1), "0" if tag == "Id" else "x")
                user = user.replace(found.group(0), f"<{tag}>{filler}</{tag}>", 1)
                removed.append(label)
        text = text[:block.start()] + user + text[block.end():]

    def clear(match):
        if _blank(match.group(2)):
            return match.group(0)
        secrets.add(match.group(2).strip())
        removed.append(f"A {match.group(1)} field")
        return f"<{match.group(1)}>{_filler(match.group(2))}</{match.group(1)}>"
    tags = "|".join(PERSONAL_TAGS)
    return re.sub(rf"<({tags})>([^<]*)</\1>", clear, text, flags=re.IGNORECASE)


def _variants(secret: str):
    """The byte forms a value can take in these files, each with a same-length filler."""
    for text in {secret, secret.lower(), secret.upper(), secret.title()}:
        for encoding in ENCODINGS:
            try:
                form = text.encode(encoding)
            except UnicodeEncodeError:
                continue
            # Same number of bytes as the original, whatever the encoding.
            unit = "x".encode(encoding)
            if len(form) % len(unit) == 0:
                yield encoding, form, unit * (len(form) // len(unit))


# What a device is, not who owns it: an owner whose surname is also a maker's name
# must not cost the device its manufacturer.
_EQUIPMENT = re.compile(rb"<(Manufacturer|Model|DeviceType|Brand)>[^<]*</\1>")


def _search(data: bytes, secrets: set[str]) -> tuple[bytes, int]:
    """Replace every whole-word occurrence of each secret, and every email address,
    outside the fields that describe equipment."""
    pieces, last = [], 0
    for match in _EQUIPMENT.finditer(data):
        pieces += [(data[last:match.start()], True), (match.group(0), False)]
        last = match.end()
    pieces.append((data[last:], True))
    total, out = 0, []
    for piece, searchable in pieces:
        if searchable:
            piece, hits = _search_piece(piece, secrets)
            total += hits
        out.append(piece)
    return b"".join(out), total


def _search_piece(data: bytes, secrets: set[str]) -> tuple[bytes, int]:
    hits = 0
    for secret in sorted(secrets, key=len, reverse=True):
        for encoding, form, filler in _variants(secret):
            if encoding.startswith("utf-16"):
                letter = rb"[A-Za-z0-9]\x00" if encoding.endswith("le") else rb"\x00[A-Za-z0-9]"
            else:
                letter = rb"[A-Za-z0-9]"
            pattern = re.compile(rb"(?<!" + letter + rb")" + re.escape(form) +
                                 rb"(?!" + letter + rb")")
            data, count = pattern.subn(filler, data)
            hits += count
    for pattern, width in ((EMAIL, 1), (EMAIL_UTF16, 2)):
        def mask(match, width=width):
            text = match.group(0)
            if b"example.com" in text.replace(b"\x00", b""):
                return text
            return (b"x" if width == 1 else b"x\x00") * (len(text) // width)
        data, count = pattern.subn(mask, data)
        hits += count
    return data, hits


def make_shareable(source, target, extra: tuple[str, ...] = ()) -> Result:
    """Write a cleaned copy of the dump `source` to `target`.

    `extra` is anything else to search for - the person's own name or email.
    """
    if Path(target).resolve() == Path(source).resolve():
        raise ValueError("the shareable copy must not replace the original")
    raw = Path(source).read_bytes()
    header, payload = _split(raw)
    result = Result()
    secrets = {value.strip() for value in extra if len(value.strip()) >= 3}
    typed = len(secrets)

    archive = None
    if payload.startswith(b"PK\x03\x04"):
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile:
            archive = None

    if archive is None:                 # no known locations: the search is all there is
        cleaned, hits = _search(payload, secrets)
        result.found_elsewhere = hits
    else:
        with archive:
            infos = archive.infolist()
            contents = {info.filename: archive.read(info) for info in infos}
        for name, data in contents.items():
            if name.lower().endswith((".xml", ".xml.backup")):
                original = data.decode("utf-8", "replace")
                text = _structured(original, secrets, result.removed)
                if text != original:
                    contents[name] = text.encode("utf-8")
        result.known_format = bool(result.removed)
        for name, data in contents.items():
            contents[name], hits = _search(data, secrets)
            result.found_elsewhere += hits
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as copy:
            for info in infos:
                clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                clone.compress_type = info.compress_type
                clone.external_attr = info.external_attr
                copy.writestr(clone, contents[info.filename])
        cleaned = out.getvalue()

    if typed and result.found_elsewhere:
        result.removed.append("What you typed in")
    header = re.sub(rb"<BINARYDATASIZE>\d+</BINARYDATASIZE>",
                    b"<BINARYDATASIZE>%d</BINARYDATASIZE>" % len(cleaned), header)
    header = re.sub(rb"<CHECKSUM>\d+</CHECKSUM>",
                    b"<CHECKSUM>%d</CHECKSUM>" % checksum(cleaned), header)
    Path(target).write_bytes(header + cleaned)
    result.removed = sorted(set(result.removed))
    return result
