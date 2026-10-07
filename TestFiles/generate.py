#!/usr/bin/python3
"""The QA fixture files, made from nothing but this script.

    /usr/bin/python3 TestFiles/generate.py           # write the files and MANIFEST.sha256
    /usr/bin/python3 TestFiles/generate.py --check   # the committed files are intact

Every byte is synthetic: invented words, drawn shapes. Nothing here was ever
on anyone's Mac, so a failing test can be shared with its inputs.

The files are committed, so the tests and the manual matrix never depend on
this script. --check does not regenerate (a different zlib would compress the
picture to different bytes): it compares the committed files with the
committed checksums and looks at each file's own structure.
"""
import hashlib
import os
import struct
import sys
import unicodedata
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
MANIFEST = "MANIFEST.sha256"


def incident_notes() -> bytes:
    return """# Incident Notes

QA fixture for PIKY. Invented content.

## Timeline

- 09:12 Checkout error rate rises from 0.4% to 6.1%.
- 09:20 Rollback of the payment form starts.
- 09:31 Error rate is back under 0.5%.

## What we know

1. Only the card form was affected; wallets kept working.
2. The first alert fired eight minutes after the deploy.

```text
POST /checkout 502 upstream timed out
```
""".encode("utf-8")


def hello_world() -> bytes:
    return b"hello world\n"


def unicode_note() -> bytes:
    return "これはPIKYのQA用メモです。\nUnicode: ✓ é ü ñ 你好 👋\n".encode("utf-8")


def accented_note() -> bytes:
    return "Résumé — café, naïve, façade.\nQA fixture for PIKY. Invented content.\n".encode("utf-8")


def meeting_notes() -> bytes:
    return "Meeting Notes — Q3\n\nAttendees: A, B, C (invented).\nDecision: ship the checkout fix on Tuesday.\n".encode("utf-8")


def budget_csv() -> bytes:
    return "quarter,item,amount\nQ3,hosting,1200\nQ3,support tools,340\nQ4,hosting,1250\n".encode("utf-8")


def launch_brief_pdf() -> bytes:
    """One page, three lines of Helvetica. Offsets are computed, not typed."""
    lines = ["Launch Brief", "QA fixture for PIKY. Invented content.", "Goal: checkout errors under 0.5% by Friday."]
    text = "BT /F1 24 Tf 72 720 Td (%s) Tj ET\n" % lines[0]
    y = 680
    for line in lines[1:]:
        text += "BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (y, line)
        y -= 20
    stream = text.encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info << /Title (Launch Brief) /Producer (PIKY QA generate.py) >> >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


def checkout_errors_png() -> bytes:
    """640 x 360: a dark panel, a red banner, six bars. Drawn, never captured."""
    width, height = 640, 360
    panel, banner, bar, axis = (24, 26, 32), (214, 48, 64), (240, 34, 110), (120, 124, 136)
    bars = [(80, 60), (160, 95), (240, 210), (320, 180), (400, 70), (480, 40)]

    def pixel(x: int, y: int):
        if 24 <= y < 72 and 24 <= x < width - 24:
            return banner
        if y == 320 and 60 <= x < 580:
            return axis
        for left, tall in bars:
            if left <= x < left + 48 and 320 - tall <= y < 320:
                return bar
        return panel

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        for x in range(width):
            raw += bytes(pixel(x, y))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


# Names are NFC, the form Git stores on macOS (core.precomposeunicode).
FILES = {
    "Incident Notes.md": incident_notes,
    "Launch Brief.pdf": launch_brief_pdf,
    "Checkout Errors.png": checkout_errors_png,
    "hello world.txt": hello_world,
    "日本語のメモ ✓.txt": unicode_note,
    "Résumé café.txt": accented_note,
    "Quarterly Review/Meeting Notes — Q3.txt": meeting_notes,
    "Quarterly Review/Budget 2026 (draft).csv": budget_csv,
}


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def write() -> None:
    lines = []
    for name, make in FILES.items():
        name = unicodedata.normalize("NFC", name)
        path = os.path.join(ROOT, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(make())
        lines.append("%s  %s\n" % (digest(path), name))
    with open(os.path.join(ROOT, MANIFEST), "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    print("Wrote %d files and %s in %s" % (len(FILES), MANIFEST, ROOT))


def check() -> int:
    failed = 0
    with open(os.path.join(ROOT, MANIFEST), encoding="utf-8") as handle:
        listed = dict((line.rstrip("\n").split("  ", 1)[1], line.split("  ", 1)[0]) for line in handle if line.strip())
    expected = set(unicodedata.normalize("NFC", name) for name in FILES)
    if set(listed) != expected:
        print("FAIL  %s lists %s, the generator makes %s" % (MANIFEST, sorted(listed), sorted(expected)))
        failed += 1
    for name, checksum in listed.items():
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            print("FAIL  missing: %s" % name); failed += 1; continue
        if digest(path) != checksum:
            print("FAIL  changed: %s" % name); failed += 1; continue
        with open(path, "rb") as handle:
            data = handle.read()
        if name.endswith(".png") and not (data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82")):
            print("FAIL  not a PNG: %s" % name); failed += 1; continue
        if name.endswith(".pdf") and not (data.startswith(b"%PDF-1.") and data.rstrip().endswith(b"%%EOF")):
            print("FAIL  not a PDF: %s" % name); failed += 1; continue
        if name.endswith((".md", ".txt", ".csv")):
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                print("FAIL  not UTF-8: %s" % name); failed += 1; continue
        print("ok    %s" % name)
    # Nothing else may sit beside the fixtures (a stray private file would be committed with them).
    known = expected | {MANIFEST, "generate.py", "README.md"}
    for folder, _, names in os.walk(ROOT):
        for name in names:
            relative = unicodedata.normalize("NFC", os.path.relpath(os.path.join(folder, name), ROOT))
            if relative not in known and name != ".DS_Store":
                print("FAIL  unexpected file: %s" % relative); failed += 1
    print("%d fixture files, %d problems" % (len(listed), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check())
    if sys.argv[1:]:
        sys.exit("Usage: generate.py [--check]")
    write()
