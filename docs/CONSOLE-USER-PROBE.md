# Probe: can a known user be at the screen of a hosted Mac?

`console-user-probe.yml` answers one question on a standard GitHub-hosted
macOS 26 runner, with nobody connected:

> Can the temporary administrator `pikyqa` be made the **console user** (the
> user logged in at the screen) through macOS's own Fast User Switching and
> its login window?

## Why it is asked

On macOS 26, Gatekeeper's **Open Anyway** asks for the password of the user who
owns the desktop. On a hosted runner that user is GitHub's `runner`, whose
password nobody knows; another administrator's password is not accepted there.
So PIKY's Gatekeeper path can only be tested on a hosted runner if the desktop
itself belongs to a user whose password is known.

## What the probe does

1. Creates `pikyqa` (an administrator, 12-character random password, checked
   by macOS) exactly as the interactive session does.
2. Switches user the way a person does: the Users menu in the menu bar, or,
   failing that, Lock Screen and its Switch User button.
3. At macOS's login window, types `pikyqa`'s password with the same HID key
   events the harness has always used.
4. Checks what macOS reports, and that a program started inside that session
   can capture the desktop, type a line into TextEdit and read it back.

It is successful only if all of these hold:

| | |
| --- | --- |
| A | `stat -f %Su /dev/console` prints exactly `pikyqa` |
| B | `State:/Users/ConsoleUser` reports `pikyqa`, on the console, login complete |
| C | the Finder of the visible desktop runs as `pikyqa` |
| D | the Dock of the visible desktop runs as `pikyqa` |
| E | a process started inside that session captured the desktop, typed a line in TextEdit and read it back |
| F | the console user is still `pikyqa` after that |

`RESULT.md` in the run's artifact ends in one of two conclusions: the known
console session is proven, or it is a limitation of the hosted runner.

## What it changes on the machine, and what it never does

Each change is listed again in `RESULT.md`:

- **Fast User Switching is switched on** with `MultipleSessionEnabled`, the
  documented preference macOS reads for it. On macOS 26 a missing preference
  means "off", and a single-user image has none.
- **The Users menu is shown in the menu bar** with Control Center's own
  preference: the same setting as System Settings › Control Center › Fast User
  Switching.
- **The first-login tour of `pikyqa` is marked as seen** before its first
  login, so that no Apple Account, Siri or analytics screen has to be answered.
  If a screen appears anyway, only the button that skips it is pressed.
- **The driver is started inside sessions macOS has already created**, with
  `sudo launchctl bsexec` (the login window) and `sudo launchctl asuser`
  (`pikyqa`'s desktop). Both are public commands that place a program in an
  existing session. They create no session and log nobody in. Keys posted
  from the job's own session are tried first, and the result says which of
  the two reached the login window.

Never: a private Apple API (the switch is made through macOS's own UI only),
a TCC database, SIP, Gatekeeper, a quarantine attribute, auto-login, a restart,
a password reset, the runner's own account or credentials.

## The password

It is read from the session's private file into the probe's memory, handed to
the driver on standard input, and typed only at macOS's own login window. It
is never in a command line that is logged, a log line, a result or an
Accessibility dump (field contents are never read). No screenshot is taken
between typing it and a completed login. A harmless word is typed first, into
a document left in front in the runner's own session: if that word arrives
there, the job's keys are not reaching the login window and the password is
not typed that way.

## What a pass would and would not mean

A pass means an interactive session on `pikyqa`'s own desktop is worth
preparing. It does not show that Open Anyway accepts `pikyqa`'s password:
only a person at that prompt does. SIP is disabled on GitHub's image, and a
job-started program is counted under GitHub's runner agent, which the image
already allows to capture the screen and post input: a pass here is a pass on
that machine, not on a retail Mac.

Money this costs: none. One standard hosted runner on a public repository.
