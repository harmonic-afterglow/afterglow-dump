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
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

USER_CONFIG = "userconfig/UserConfiguration.xml"
OWNER = {"Id": "Logitech account ID", "FirstName": "First name", "LastName": "Last name"}
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
    removed: dict[str, str] = field(default_factory=dict)   # the text removed -> what it is
    places: Counter = field(default_factory=Counter)         # the text removed -> how often
    found_elsewhere: int = 0            # matches the whole-file search replaced
    known_format: bool = False          # found the owner in a known location

    def lines(self) -> list[str]:
        """What was removed, as the person would read it: "First name: Ada (3 places)"."""
        out = []
        for value, what in self.removed.items():
            count = self.places[value]
            out.append(f"{what}: {value}" + (f" ({count} places)" if count > 1 else ""))
        return out


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


def _structured(text: str, secrets: set[str], result: Result):
    """Clear the known personal fields of one XML file, remembering their values."""
    # The owner block; from the end, so earlier positions stay valid.
    for block in reversed(list(re.finditer(r"<User>.*?</User>", text, re.DOTALL))):
        user = block.group(0)
        for tag, label in OWNER.items():
            found = re.search(rf"<{tag}>([^<]*)</{tag}>", user)
            if found and not _blank(found.group(1)):
                value = found.group(1).strip()
                secrets.add(value)
                result.removed.setdefault(value, label)
                result.places[value] += 1
                filler = _filler(found.group(1), "0" if tag == "Id" else "x")
                user = user.replace(found.group(0), f"<{tag}>{filler}</{tag}>", 1)
        text = text[:block.start()] + user + text[block.end():]

    def clear(match):
        if _blank(match.group(2)):
            return match.group(0)
        value = match.group(2).strip()
        secrets.add(value)
        result.removed.setdefault(value, re.sub(r"(?<=[a-z])(?=[A-Z])", " ",
                                                match.group(1)).capitalize())
        result.places[value] += 1
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


def _search(data: bytes, secrets: set[str], result: Result) -> bytes:
    """Replace every whole-word occurrence of each secret, and every email address,
    outside the fields that describe equipment."""
    pieces, last = [], 0
    for match in _EQUIPMENT.finditer(data):
        pieces += [(data[last:match.start()], True), (match.group(0), False)]
        last = match.end()
    pieces.append((data[last:], True))
    out = []
    for piece, searchable in pieces:
        out.append(_search_piece(piece, secrets, result) if searchable else piece)
    return b"".join(out)


def _search_piece(data: bytes, secrets: set[str], result: Result) -> bytes:
    # Email addresses first, whole, before a name inside one is blanked.
    for pattern, width in ((EMAIL, 1), (EMAIL_UTF16, 2)):
        def mask(match, width=width):
            text = match.group(0)
            address = text.replace(b"\x00", b"").decode("ascii", "replace")
            if address.endswith("example.com"):
                return text
            result.removed.setdefault(address, "Email")
            result.places[address] += 1
            result.found_elsewhere += 1
            return (b"x" if width == 1 else b"x\x00") * (len(text) // width)
        data = pattern.sub(mask, data)
    for secret in sorted(secrets, key=len, reverse=True):
        for encoding, form, filler in _variants(secret):
            if encoding.startswith("utf-16"):
                letter = rb"[A-Za-z0-9]\x00" if encoding.endswith("le") else rb"\x00[A-Za-z0-9]"
            else:
                letter = rb"[A-Za-z0-9]"
            pattern = re.compile(rb"(?<!" + letter + rb")" + re.escape(form) +
                                 rb"(?!" + letter + rb")")
            data, count = pattern.subn(filler, data)
            if count:
                result.removed.setdefault(secret, "What you typed")
                result.places[secret] += count
                result.found_elsewhere += count
    return data


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

    archive = None
    if payload.startswith(b"PK\x03\x04"):
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile:
            archive = None

    if archive is None:                 # no known locations: the search is all there is
        cleaned = _search(payload, secrets, result)
    else:
        with archive:
            infos = archive.infolist()
            contents = {info.filename: archive.read(info) for info in infos}
        for name, data in contents.items():
            if name.lower().endswith((".xml", ".xml.backup")):
                original = data.decode("utf-8", "replace")
                text = _structured(original, secrets, result)
                if text != original:
                    contents[name] = text.encode("utf-8")
        result.known_format = any(what in OWNER.values() for what in result.removed.values())
        for name, data in contents.items():
            contents[name] = _search(data, secrets, result)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as copy:
            for info in infos:
                clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                clone.compress_type = info.compress_type
                clone.external_attr = info.external_attr
                copy.writestr(clone, contents[info.filename])
        cleaned = out.getvalue()

    header = re.sub(rb"<BINARYDATASIZE>\d+</BINARYDATASIZE>",
                    b"<BINARYDATASIZE>%d</BINARYDATASIZE>" % len(cleaned), header)
    header = re.sub(rb"<CHECKSUM>\d+</CHECKSUM>",
                    b"<CHECKSUM>%d</CHECKSUM>" % checksum(cleaned), header)
    Path(target).write_bytes(header + cleaned)
    return result
