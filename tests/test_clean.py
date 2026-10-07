import io
import zipfile

import pytest

from afterglow_dump import clean

USER = ("<Root><User><Id>4815162342</Id><Properties/><Presentation>"
        "<FirstName>Ada</FirstName><LastName>Lovelace</LastName></Presentation></User>"
        "<Device><Name>Living room TV</Name><Manufacturer>Lovelace</Manufacturer>"
        "<Note>ada@example.org</Note></Device></Root>")


def dump(protocol=15, skin=61, user=USER) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("userconfig/UserConfiguration.xml", user)
        archive.writestr("userconfig/SsIr.bin", b"\x00\x01")
    payload = payload.getvalue()
    header = (f"<INFORMATION><INTENDEDVERSION><PROTOCOL>{protocol}</PROTOCOL>"
              f"<SKIN>{skin}</SKIN></INTENDEDVERSION><BINARYDATASIZE>{len(payload)}"
              f"</BINARYDATASIZE><CHECKSUM>{clean.checksum(payload)}</CHECKSUM>"
              "</INFORMATION>\r\n").encode()
    return header + payload


def test_the_format_not_the_remote_decides(tmp_path):
    # A zip payload is cleaned in its known locations whatever remote the header names.
    source, target = tmp_path / "any.ezhex", tmp_path / "copy.ezhex"
    source.write_bytes(dump(protocol=99, skin=1))
    assert clean.make_shareable(source, target).known_format


def binary_dump(payload: bytes) -> bytes:
    header = ("<INFORMATION><INTENDEDVERSION><PROTOCOL>2</PROTOCOL><SKIN>37</SKIN>"
              f"</INTENDEDVERSION><BINARYDATASIZE>{len(payload)}</BINARYDATASIZE>"
              f"<CHECKSUM>{clean.checksum(payload)}</CHECKSUM></INFORMATION>\r\n").encode()
    return header + payload


def test_an_unknown_binary_format_is_searched_for_what_was_typed(tmp_path):
    payload = (b"GSPM\x00\x01Ada Lovelace\x00" + "Ada".encode("utf-16-le")
               + b"\x00\x00ada@example.org\x00Adapter\x00Timer")
    source, target = tmp_path / "880.ezhex", tmp_path / "copy.ezhex"
    source.write_bytes(binary_dump(payload))
    result = clean.make_shareable(source, target, extra=("Ada Lovelace", "Ada"))
    _header, cleaned = clean._split(target.read_bytes())
    assert not result.known_format and result.found_elsewhere >= 3
    assert len(cleaned) == len(payload), "binary layouts keep their offsets"
    for gone in (b"Ada Lovelace", "Ada".encode("utf-16-le"), b"ada@example.org"):
        assert gone not in cleaned
    assert b"Adapter" in cleaned, "whole words only"


def test_names_ids_and_emails_go_and_everything_else_stays(tmp_path):
    source, target = tmp_path / "900.ezhex", tmp_path / "copy.ezhex"
    source.write_bytes(dump())
    removed = clean.make_shareable(source, target)

    result = removed
    assert result.known_format
    assert result.removed["4815162342"] == "Logitech account ID"
    assert result.removed["Ada"] == "First name"
    assert result.removed["ada@example.org"] == "Email"
    assert "First name: Ada" in result.lines()
    header, payload = clean._split(target.read_bytes())
    text = zipfile.ZipFile(io.BytesIO(payload)).read(clean.USER_CONFIG).decode()
    outside_equipment = text.replace("<Manufacturer>Lovelace</Manufacturer>", "")
    for gone in ("4815162342", "Ada", "Lovelace", "ada@example.org"):
        assert gone not in outside_equipment
    assert "<Manufacturer>Lovelace</Manufacturer>" in text, "equipment is not the owner"
    assert "<Id>0000000000</Id>" in text and "<FirstName>xxx</FirstName>" in text
    original = zipfile.ZipFile(io.BytesIO(clean._split(source.read_bytes())[1]))
    assert len(text.encode()) == len(original.read(clean.USER_CONFIG)), "nothing moves"
    assert "Living room TV" in text, "devices are what makes a dump useful"
    assert zipfile.ZipFile(io.BytesIO(payload)).read("userconfig/SsIr.bin") == b"\x00\x01"
    assert f"<CHECKSUM>{clean.checksum(payload)}</CHECKSUM>".encode() in header
    assert f"<BINARYDATASIZE>{len(payload)}</BINARYDATASIZE>".encode() in header


def test_the_original_is_never_replaced(tmp_path):
    source = tmp_path / "900.ezhex"
    source.write_bytes(dump())
    with pytest.raises(ValueError):
        clean.make_shareable(source, source)
