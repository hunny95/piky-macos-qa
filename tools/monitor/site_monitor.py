#!/usr/bin/env python3
"""PIKY's public pieces, checked from outside, every half hour (.github/workflows/site-monitor.yml).

Checks:
  1. getpiky.com answers and offers the download;
  2. the release record (/api/v1/releases/latest) names one disk image;
  3. the update feed offers that same file: same build, size and address, with a signature;
  4. the Download link leads to that file (HEAD: the site never counts it);
  5. GitHub holds that file with the same SHA-256 and size;
  6. the feedback and privacy pages answer.

Nothing is counted anywhere: no browser user agent (so no Download press or visit),
no Sparkle user agent (so no update check), HEAD for the download. Exit 1 on any failure,
with one line per check; the workflow turns a failure into an alert.
"""
import base64, json, os, sys, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET

SITE = os.environ.get("PIKY_SITE", "https://www.getpiky.com").rstrip("/")
FEED = os.environ.get("PIKY_FEED", "https://updates.getpiky.com/macos/stable/appcast.xml")
REPO = os.environ.get("PIKY_RELEASES_REPO", "hunny95/piky-releases")
AGENT = "piky-site-monitor/1 (+https://github.com/hunny95/piky-macos-qa)"
SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
results = []

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def fetch(url, method="GET", follow=True, headers=None, timeout=20):
    request = urllib.request.Request(url, method=method, headers={"User-Agent": AGENT, **(headers or {})})
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(), time.monotonic() - started
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read(), time.monotonic() - started

def check(name, passed, detail=""):
    results.append((name, bool(passed), detail))
    return bool(passed)

def run():
    status, _, body, took = fetch(f"{SITE}/")
    check("homepage answers 200 in under 10 s", status == 200 and took < 10, f"{status}, {took:.1f} s")
    check("homepage offers Download for Mac", b"Download for Mac" in body)

    status, _, body, _ = fetch(f"{SITE}/api/v1/releases/latest?platform=macos")
    if not check("release record answers 200", status == 200, str(status)):
        return
    record = json.loads(body)
    url, build, version, size = record.get("download_url"), str(record.get("build")), record.get("version"), record.get("bytes")
    sha = (record.get("checksum") or {}).get("value")
    check("release record names a disk image with SHA-256 and size", bool(url and sha and size), f"{version} ({build})")

    status, headers, body, _ = fetch(FEED)
    if check("update feed answers 200", status == 200, str(status)):
        try:
            item = ET.fromstring(body).find("./channel/item")
            enclosure = item.find("enclosure") if item is not None else None
            check("feed offers the same build and version", item is not None and item.findtext(f"{SPARKLE}version") == build
                  and item.findtext(f"{SPARKLE}shortVersionString") == version)
            check("feed names the same file and size", enclosure is not None and enclosure.get("url") == url and enclosure.get("length") == str(size))
            signature = enclosure.get(f"{SPARKLE}edSignature", "") if enclosure is not None else ""
            check("feed carries a 64-byte EdDSA signature", len(base64.b64decode(signature or "")) == 64)
        except ET.ParseError as error:
            check("feed is well-formed XML", False, str(error))

    status, headers, _, _ = fetch(f"{SITE}/download/macos", method="HEAD", follow=False)
    location = headers.get("Location") or headers.get("location")
    check("Download leads to that file (HEAD, never counted)", status == 302 and location == url, f"{status} → {location}")

    token = os.environ.get("GITHUB_TOKEN")
    status, _, body, _ = fetch(f"https://api.github.com/repos/{REPO}/releases?per_page=20",
                               headers={"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})})
    if check("GitHub release list answers 200", status == 200, str(status)):
        assets = [a for r in json.loads(body) if not r.get("draft") for a in r.get("assets", [])]
        asset = next((a for a in assets if a.get("browser_download_url") == url), None)
        check("GitHub holds that file", asset is not None)
        if asset:
            check("GitHub's SHA-256 and size match the release record", asset.get("digest") == f"sha256:{sha}" and asset.get("size") == size,
                  f"{asset.get('digest', '')[:19]}…, {asset.get('size')}")

    status, _, body, _ = fetch(f"{SITE}/feedback")
    check("feedback page answers with its form", status == 200 and b"<form" in body, str(status))
    status, _, _, _ = fetch(f"{SITE}/privacy")
    check("privacy page answers", status == 200, str(status))

if __name__ == "__main__":
    try:
        run()
    except Exception as error:  # a network failure is a failed check, never a crash without a line
        check("monitor reached every piece", False, f"{type(error).__name__}: {error}")
    for name, passed, detail in results:
        print(f"  {'ok  ' if passed else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
    failed = [name for name, passed, _ in results if not passed]
    print(f"\n{len(results) - len(failed)} ok, {len(failed)} failed")
    if failed and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write("PIKY monitor failed:\n" + "\n".join(f"- {name}" for name in failed) + "\n")
    if failed:
        with open(os.environ.get("PIKY_MONITOR_FAILED", "/dev/null"), "w") as out:
            out.write("; ".join(failed))
    sys.exit(1 if failed else 0)
