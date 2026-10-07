# piky-macos-qa

A test harness for the **published** PIKY for macOS disk image. It answers one
question on machines nobody has to buy or keep: does the file people download
install, open and work on macOS 14, 15 and 26?

It contains no PIKY source code, no signing material and no secrets. The app
under test is the public download:

    https://github.com/hunny95/piky-releases/releases/download/v0.2.0-alpha.1/PIKY-0.2.0-universal.dmg
    5,019,073 bytes · SHA-256 98e824f265b352ed2e5f567559fd6af3dfb98bb507986aa87a54bc19d1fb3a44

(`release.env`; a run refuses any other bytes.)

## How it runs

**Actions › Headed QA › Run workflow**, choosing one macOS. That starts one
standard GitHub-hosted Apple silicon runner, which is free for a public
repository and is destroyed when the job ends. Nothing starts by itself: not
on a push, not on a pull request, not on a schedule. Only the repository
owner can start it.

On that machine the run does what a person would, in this order:

| | Step | How |
| --- | --- | --- |
| 1 | Download | Safari opens the release address and saves the file; its quarantine attribute and checksum are recorded |
| 2 | Gatekeeper | The image is opened, Finder copies PIKY to Applications, PIKY is opened; macOS's alert is read word for word; then System Settings › Privacy & Security › Open Anyway (and on macOS 14, Control-click › Open) |
| 3 | First run | The first-run window, active and inactive; the contrast of its Continue label, measured from the screenshot; the mark in the menu bar |
| 4 | Permissions | What macOS answers PIKY; PIKY's own request; the switch in System Settings |
| 5 | ⌥Space | Real key events, with TextEdit in front |
| 6 | Text Pick | A pointer drag and a triple-click over known paragraphs in TextEdit |
| 7 | Finder Pick | Clicks on five fixture files: a plain name, a space, non-Latin script, a PNG, a PDF |
| 8 | Camera | ⌥ held over a known page in Safari: outline, ⌥-click, ⌥-scroll, ⌥-drag |
| 9 | ⌘Return | Into `TestReceiver`, which logs exactly what arrived, in which order, with checksums |
| 10 | Library | Undo, New Pack, Library, quit, reopen, persistence |

Keys, clicks, drags and wheel notches are posted at the HID level (`tools/qa`),
so they pass through the window server like a device's. PIKY is never called
into: it is launched, typed at, clicked at and looked at.

## What comes back

One artifact per run: `RESULTS.md`, about a hundred screenshots, what macOS
Accessibility said at each step, the machine's security settings, quarantine
and Gatekeeper observations, the receiver's log, PIKY's own content-free
diagnostics, timings. Only QA fixtures are ever selected, picked or delivered.

Every check ends as one of:

| | |
| --- | --- |
| **PASS** | What a person would see, was seen |
| **FAIL** | PIKY did something wrong |
| **RUNNER ENVIRONMENT LIMITATION** | The hosted runner cannot show this |
| **INCONCLUSIVE** | The harness could not set the step up; it says nothing about PIKY |
| **NOT RUN** | An earlier step did not get there |

## What it cannot tell you

- **Whether a person can grant PIKY its permissions.** macOS does not accept a
  privacy grant from generated input, and this harness never edits the TCC
  database, changes SIP or removes a quarantine attribute. GitHub's image
  pre-allows its own agent for Accessibility and screen capture; when PIKY's
  own grant cannot be made, the working steps run PIKY's installed binary
  under the agent's permissions and **say so in every result**. That shows
  how PIKY behaves on that macOS. It is not a permission test.
- **Anything about a hand or a real display:** trackpad feel, swipe steps, a
  notch, Retina sharpness, two displays.
- **A real destination.** `TestReceiver` is an AppKit message box. Slack,
  Claude and browsers treat pastes and drops differently.

## In this repository

| | |
| --- | --- |
| `.github/workflows/headed-qa.yml` | The run. Manual, owner only, no secrets. |
| `.github/workflows/interactive-macos-qa.yml`, `interactive/` | A person tests by hand on a temporary hosted Mac through RustDesk. Manual, owner only, needs one secret: `docs/INTERACTIVE-RUSTDESK.md`. |
| `.github/workflows/interactive-screen-sharing.yml` | The same session through macOS Screen Sharing over a private tailnet. A fallback, prepared and **never run**; needs two more secrets: `docs/INTERACTIVE-SCREEN-SHARING.md`. |
| `.github/workflows/console-user-probe.yml`, `probe/` | An unattended probe: can a temporary administrator be the user at the screen of a hosted macOS 26 runner, through macOS's own Fast User Switching? No secrets, nobody connects: `docs/CONSOLE-USER-PROBE.md`. |
| `harness/run.py` | The stages above, and what counts as a pass |
| `harness/simulate.py` | A stand-in for the Mac, to walk `run.py` through without one: `QA_SIMULATE=1 QA_OUT=/tmp/x python3 harness/run.py` |
| `tools/qa/` | The driver: events, Accessibility reading, screenshot measurements |
| `TestReceiver/` | The message box that records what arrives |
| `TestFiles/`, `TestPage/` | Fixtures: invented words and drawn shapes, with checksums and known positions |
| `release.env` | The file under test: address, size, SHA-256 |

## Safety

`harness/run.py` installs into `/Applications`, presses real keys and moves the
real pointer. It refuses to start anywhere but a GitHub-hosted runner, and
stops if the machine already has PIKY or PIKY's data. Do not run it on a Mac
you use.

One thing a run changes on its disposable machine besides installing PIKY:
when macOS asks for the administrator's password, the run sets a random
password on the runner's account so it can type it into macOS's own prompt
(input `account_password`, on by default). The password exists only in the
run's memory and is never printed or stored.

Money this costs: none. Standard GitHub-hosted runners on a public repository
are not billed; no larger runner, self-hosted runner or outside service is used.
