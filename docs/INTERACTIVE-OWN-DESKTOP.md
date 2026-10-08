# Testing PIKY by hand on a hosted Mac, on a desktop whose password you know

`interactive-own-desktop.yml` is the interactive session of
`docs/INTERACTIVE-RUSTDESK.md` with one difference that matters on macOS 26:
**the desktop you get belongs to the temporary administrator `pikyqa`**, not
to GitHub's `runner` account.

## Why

On macOS 26, Gatekeeper's **Open Anyway** asks for the password of the user who
owns the desktop. On the runner's own desktop that is GitHub's account, whose
password nobody knows, and another administrator's password is not accepted
there. The console-user probe (`docs/CONSOLE-USER-PROBE.md`, run 37695904701)
showed that `pikyqa` can be made the user at the screen through macOS's own
Fast User Switching and login window, and that the job keeps running.

## What the workflow does before you are told the Mac is ready

| | Step | It stops if |
| --- | --- | --- |
| 1 | Creates `pikyqa` (administrator, 12-character password, checked by macOS) | macOS does not accept the password |
| 2 | Clicks the Users menu in the menu bar, then `PIKY QA Admin`; types the password at macOS's login window | the switch or the login does not happen |
| 3 | Checks `/dev/console`, `State:/Users/ConsoleUser`, and that Finder and Dock run as `pikyqa` | any of them says otherwise |
| 4 | **Control gate, with no screenshot:** opens TextEdit on that desktop, types a line with HID key events, reads it back from the document through Accessibility, changes which application is in front by clicks | the line does not arrive (GUI CONTROL FAILURE) |
| 5 | Takes its first screenshot only now. On a new account macOS answers that with its own consent dialog ("… is requesting to bypass the system private window picker and directly access your screen and audio"). The job clicks **Allow** in that dialog, as a person would | the dialog cannot be answered through macOS's own UI (RUSTDESK SCREEN-RECORDING LIMITATION) |
| 6 | Starts RustDesk **inside `pikyqa`'s session** (never under `runner`), sets the session password, waits 60 seconds for one stable ID | RustDesk does not stand, or does not run as `pikyqa` |
| 7 | Ready gate: still the console user, RustDesk is an application of that session, a click and typed keys still arrive, no consent dialog remains | any of them fails |

Only then is the encrypted session note uploaded. No screenshot is taken
while RustDesk's window (which shows the session's ID) is on screen.

## What you do

Exactly as in `docs/INTERACTIVE-RUSTDESK.md`: download the session artifact,
decrypt it with your passphrase, connect with RustDesk. Then:

- You are logged in as `pikyqa`. When macOS asks for a password (Open Anyway,
  Accessibility, Screen Recording) it wants the user at the screen: type
  `pikyqa`'s password from the note.
- The QA kit is the `PIKY-QA` folder on the Desktop.
- To end, move its "END SESSION - delete this file" to the Trash.

## What it changes on the machine, and what it never does

- Fast User Switching is switched on with `MultipleSessionEnabled`, the
  documented preference macOS reads for it; the Users menu is shown with
  Control Center's own preference; `pikyqa`'s first-login tour is marked as
  seen. (As in the probe.)
- Programs are placed inside `pikyqa`'s session with `sudo launchctl asuser`:
  a public command that puts a program in a session macOS has already created.
- macOS's screen-capture consent is given by a click on **Allow** in macOS's
  own dialog. If macOS asks for a password there, `pikyqa`'s is typed into
  macOS's password field.

Never: a private Apple API, a TCC database, SIP, Gatekeeper, a quarantine
attribute, auto-login, a restart, a password reset, the runner's own account
or its credentials.

## What the gates cannot see

Whether RustDesk's own picture and input reach **you**. The workflow shows
that a program started the same way, in the same session, captures windows
and that its clicks and keys arrive. Only your connection shows RustDesk
itself; type a line in TextEdit first.

SIP is disabled on GitHub's image, and a job-started program is counted under
what the image already allows. A pass here is a pass on that machine, not on a
retail Mac. Money this costs: none.
