#!/usr/bin/python3
"""Writes the QA page from geometry.json, so the page and the Camera fixture
tests can never disagree about where things are.

    /usr/bin/python3 TestPage/build.py           # write index.html and assets/harbour.svg
    /usr/bin/python3 TestPage/build.py --check   # the committed page is what geometry.json describes

Everything is drawn or invented here: no photograph, no real name, no network
request, no web font. Open index.html from disk in any browser at 100% zoom.
"""
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

INTRO = (
    "This page exists so that the same things can be picked on every Mac. "
    "Select this paragraph for a text Pick: it is exactly four sentences long. "
    "The picture on the right, the two charts below and the cards around them have fixed sizes, written beside each one. "
    "Nothing on this page comes from a real person or a real company."
)
STORY = [
    "Scroll check. This paragraph sits below the first screen, so reaching it needs a scroll, and the Camera's outline has to follow the page.",
    "On Tuesday the checkout form began timing out for card payments. The first alert arrived eight minutes after the deploy, and the rollback took eleven more.",
    "By the afternoon the error rate was under half a percent again. The team agreed on three changes: an alert on the form's own latency, a slower rollout, and a note in the release checklist.",
    "Select from the word Scroll to the word checklist for a long text Pick. It is three paragraphs and should arrive as text, with its line breaks, not as a picture.",
]
MEMBERS = {
    "member-1": ("Primary on call", "Answers pages first. Invented person A.", "#F0226E"),
    "member-2": ("Secondary on call", "Covers after ten minutes. Invented person B.", "#12A594"),
    "member-3": ("Incident lead", "Runs the review on Friday. Invented person C.", "#E5A000"),
}
CARD_NUMBERS = {"card-revenue": "48,200", "card-errors": "0.4%", "card-users": "1,284"}

CSS = """
*{box-sizing:border-box}
html{background:#f4f5f7}
body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Helvetica,Arial,sans-serif;color:#1b1d22}
#stage{position:relative;margin:0;background:#fff;overflow:hidden}
[data-qa]{position:absolute;margin:0}
h1[data-qa]{font-size:30px;line-height:48px;font-weight:700;white-space:nowrap;overflow:hidden}
p[data-qa]{overflow:hidden}
p[data-qa] span{display:block;margin-bottom:12px}
img[data-qa]{display:block;border-radius:10px}
.section{background:#f0f2f6;border-radius:14px}
.group{background:#eef6f4;border-radius:14px}
.card{background:#fff;border-radius:12px;box-shadow:0 0 0 1px #d9dce3 inset,0 1px 3px rgba(0,0,0,.08)}
.caption{position:absolute;left:20px;top:14px;font-weight:600}
.number{position:absolute;left:20px;top:38px;font-size:26px;font-weight:700}
.sub{position:absolute;left:20px;top:22px;font-size:13px;font-weight:600;color:#4a4f5c;letter-spacing:.02em;text-transform:uppercase}
.who{position:absolute;left:136px;top:24px;right:16px}
.who b{display:block;font-size:17px}
.who i{font-style:normal;color:#5b6070}
svg[data-qa]{display:block;background:#fafbfc;border-radius:8px}
.scroll{overflow-y:scroll;background:#101216;color:#d8dbe2;border-radius:12px;font:13px/25px ui-monospace,Menlo,monospace}
.scroll div{height:25px;padding:0 16px;white-space:nowrap}
.scroll div:nth-child(odd){background:#161920}
.size{position:absolute;right:6px;bottom:4px;font:10px/1 ui-monospace,Menlo,monospace;color:#8a90a0;pointer-events:none}
#check{position:fixed;right:12px;bottom:12px;padding:6px 10px;border-radius:8px;font:12px/1.3 ui-monospace,Menlo,monospace;background:#1b1d22;color:#fff;max-width:420px;z-index:9}
#check.bad{background:#b3261e}
"""

# What the page says about itself: every element is where geometry.json put
# it. A browser zoomed in or out, or a changed default font size, shows red.
SCRIPT = """
(function () {
  var wrong = [];
  document.querySelectorAll('[data-qa]').forEach(function (node) {
    var want = node.getAttribute('data-rect').split(',').map(Number);
    var box = node.getBoundingClientRect();
    var got = [box.left + window.scrollX, box.top + window.scrollY, box.width, box.height];
    for (var i = 0; i < 4; i++) {
      if (Math.abs(got[i] - want[i]) > 0.5) { wrong.push(node.getAttribute('data-qa')); break; }
    }
  });
  var badge = document.getElementById('check');
  var zoom = Math.round(window.devicePixelRatio * 100) / 100;
  if (wrong.length) {
    badge.className = 'bad';
    badge.textContent = 'Layout differs for: ' + wrong.join(', ') + '. Set zoom to 100%.';
  } else {
    badge.textContent = 'QA page · ' + document.querySelectorAll('[data-qa]').length + ' elements in place · pixel ratio ' + zoom;
  }
  window.qaGeometry = function () {
    var out = {};
    document.querySelectorAll('[data-qa]').forEach(function (node) {
      var box = node.getBoundingClientRect();
      out[node.getAttribute('data-qa')] = [box.left + window.scrollX, box.top + window.scrollY, box.width, box.height];
    });
    return out;
  };
})();
"""


def bars(width, height):
    values = [0.35, 0.5, 0.42, 0.68, 0.8, 0.62, 0.9]
    left, bottom, gap = 24, height - 28, 10
    each = (width - 2 * left - gap * (len(values) - 1)) / len(values)
    out = ['<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#9aa0ae" stroke-width="1"/>' % (left, bottom, width - left, bottom)]
    for index, value in enumerate(values):
        tall = round((bottom - 20) * value)
        out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" rx="3" fill="#F0226E"/>' % (left + index * (each + gap), bottom - tall, each, tall))
    return "".join(out)


def line(width, height):
    values = [0.2, 0.25, 0.22, 0.6, 0.85, 0.4, 0.18, 0.15]
    left, top, bottom = 20, 14, height - 18
    step = (width - 2 * left) / (len(values) - 1)
    points = " ".join("%.1f,%.1f" % (left + i * step, bottom - (bottom - top) * v) for i, v in enumerate(values))
    return ('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#9aa0ae" stroke-width="1"/>' % (left, bottom, width - left, bottom)
            + '<polyline points="%s" fill="none" stroke="#2f6fed" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>' % points)


def harbour(width, height):
    """The page's one picture: a drawn harbour. Flat shapes, no gradient noise."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 360 220">'
        '<rect width="360" height="220" fill="#27304d"/>'
        '<rect y="120" width="360" height="100" fill="#1c5a74"/>'
        '<circle cx="270" cy="70" r="34" fill="#f6b35c"/>'
        '<polygon points="0,120 70,60 150,120" fill="#3a4470"/>'
        '<polygon points="110,120 200,40 300,120" fill="#333c63"/>'
        '<rect x="40" y="128" width="90" height="10" fill="#e9ecf2"/>'
        '<polygon points="60,128 85,84 110,128" fill="#f4f5f7"/>'
        '<rect x="210" y="150" width="70" height="8" fill="#e9ecf2"/>'
        '<polygon points="224,150 244,118 264,150" fill="#F0226E"/>'
        '</svg>\n' % (width, height)
    )


def render(elements):
    by_id = dict((e["id"], e) for e in elements)
    children = {}
    for element in elements:
        children.setdefault(element.get("parent"), []).append(element)

    def node(element, indent):
        pad = "  " * indent
        x, y, w, h = element["rect"]
        parent = by_id.get(element.get("parent"))
        left, top = (x - parent["rect"][0], y - parent["rect"][1]) if parent else (x, y)
        ident, kind, label = element["id"], element["kind"], html.escape(element["label"], quote=True)
        place = 'data-qa="%s" data-rect="%d,%d,%d,%d" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"' % (ident, x, y, w, h, left, top, w, h)
        size = '<span class="size">%s %d×%d</span>' % (ident, w, h)
        inner = "".join(node(child, indent + 1) for child in children.get(ident, []))
        if kind == "heading":
            return '%s<h1 %s>%s</h1>\n' % (pad, place, label)
        if kind == "paragraph":
            text = INTRO if ident == "intro" else "".join("<span>%s</span>" % html.escape(part) for part in STORY)
            return '%s<p %s>%s</p>\n' % (pad, place, html.escape(text) if ident == "intro" else text)
        if kind == "image":
            return '%s<img %s src="assets/harbour.svg" alt="%s" width="%d" height="%d">\n' % (pad, place, label, w, h)
        if kind in ("chart-bars", "chart-line"):
            drawing = bars(w, h) if kind == "chart-bars" else line(w, h)
            return '%s<svg %s role="img" aria-label="%s" viewBox="0 0 %d %d" width="%d" height="%d">%s</svg>\n' % (pad, place, label, w, h, w, h, drawing)
        if kind == "avatar":
            colour = MEMBERS[element["parent"]][2]
            face = ('<circle cx="48" cy="48" r="48" fill="%s"/><circle cx="48" cy="38" r="16" fill="#fff"/>'
                    '<path d="M18 84a30 26 0 0 1 60 0z" fill="#fff"/>' % colour)
            return '%s<svg %s role="img" aria-label="%s" viewBox="0 0 96 96" width="%d" height="%d">%s</svg>\n' % (pad, place, label, w, h, face)
        if kind == "section":
            return '%s<section class="section" %s aria-label="%s">\n%s  <span class="sub">%s</span>\n%s%s  %s\n%s</section>\n' % (pad, place, label, pad, label, inner, pad, size, pad)
        if kind == "group":
            return '%s<div class="group" %s role="group" aria-label="%s">\n%s  <span class="sub">%s</span>\n%s%s  %s\n%s</div>\n' % (pad, place, label, pad, label, inner, pad, size, pad)
        if kind == "card":
            if ident in MEMBERS:
                name, detail, _ = MEMBERS[ident]
                body = '<span class="who"><b>%s</b><i>%s</i></span>' % (html.escape(name), html.escape(detail))
            else:
                body = '<span class="caption">%s</span><span class="number">%s</span>' % (label, CARD_NUMBERS[ident])
            return '%s<div class="card" %s role="group" aria-label="%s">\n%s  %s\n%s%s  %s\n%s</div>\n' % (pad, place, label, pad, body, inner, pad, size, pad)
        if kind == "scroll":
            rows = "".join("<div>%02d:%02d  checkout  %s  request %04d</div>" % (9 + (i * 7) // 60, (i * 7) % 60, ("ok   ", "ok   ", "retry", "ok   ", "error")[i % 5], 4100 + i * 13)
                           for i in range(element["rows"]))
            return '%s<div class="scroll" %s role="region" aria-label="%s" tabindex="0">%s</div>\n' % (pad, place, label, rows)
        raise SystemExit("Unknown kind: %s" % kind)

    page = by_id["page"]
    body = "".join(node(child, 2) for child in children.get("page", []))
    _, _, width, height = page["rect"]
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=%d">\n<title>PIKY QA page</title>\n'
        '<!-- Generated by build.py from geometry.json. Do not edit by hand. -->\n'
        '<style>%s</style>\n</head>\n<body>\n'
        '  <main id="stage" data-qa="page" data-rect="0,0,%d,%d" style="position:relative;width:%dpx;height:%dpx">\n%s  </main>\n'
        '  <div id="check">checking…</div>\n<script>%s</script>\n</body>\n</html>\n'
    ) % (width, CSS, width, height, width, height, body, SCRIPT)


def outputs():
    with open(os.path.join(ROOT, "geometry.json"), encoding="utf-8") as handle:
        geometry = json.load(handle)
    elements = geometry["elements"]
    by_id = dict((e["id"], e) for e in elements)
    assert len(by_id) == len(elements), "duplicate ids"
    for element in elements:
        x, y, w, h = element["rect"]
        assert all(isinstance(v, int) for v in element["rect"]) and w > 0 and h > 0, element["id"]
        parent = by_id.get(element.get("parent"))
        if parent:
            px, py, pw, ph = parent["rect"]
            assert px <= x and py <= y and x + w <= px + pw and y + h <= py + ph, "%s is not inside %s" % (element["id"], parent["id"])
    photo = by_id["photo"]["rect"]
    return {"index.html": render(elements), os.path.join("assets", "harbour.svg"): harbour(photo[2], photo[3])}


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--check"]):
        sys.exit("Usage: build.py [--check]")
    stale = 0
    for name, text in outputs().items():
        path = os.path.join(ROOT, name)
        if sys.argv[1:] == ["--check"]:
            current = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
            if current == text:
                print("ok    %s" % name)
            else:
                print("FAIL  %s is not what geometry.json describes: run build.py" % name); stale += 1
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            print("Wrote %s" % name)
    sys.exit(1 if stale else 0)
