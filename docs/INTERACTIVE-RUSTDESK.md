# Testing PIKY by hand on a temporary hosted Mac

`interactive-macos-qa.yml` starts one standard GitHub-hosted Mac, puts the QA
kit on its Desktop, starts [RustDesk](https://github.com/rustdesk/rustdesk)
and waits while a person connects and tests PIKY with their own mouse and
keyboard. When the session ends, RustDesk is stopped, the temporary
administrator and every credential are deleted, and GitHub destroys the Mac.

It exists because the automated run cannot do two things a person can:
answer macOS's administrator prompt (Open Anyway, Accessibility, Screen
Recording), and judge anything by eye.

## Once: one secret

Artifacts of a public repository can be downloaded by **anyone signed in to
GitHub**. There is no private artifact here. So the session's RustDesk ID and
its two random passwords are uploaded only as ciphertext, and you hold the key:

    gh secret set QA_SESSION_PASSPHRASE -R hunny95/piky-macos-qa

Type a passphrase of 20 characters or more that you use for nothing else.
Nobody else, and no tool, needs to know it. Without the secret the workflow
stops before it creates anything.

## Each session

1. On your own Mac, install RustDesk (rustdesk.com) and **quit PIKY** (and
   Raycast or Alfred if they use ⌥Space): a shortcut your Mac holds never
   reaches the remote one.
2. Actions › Interactive macOS QA › Run workflow (macOS 14, minutes).
3. About five minutes later the run's summary says the Mac is ready. Fetch
   and open the session note:

       gh run download <run id> -R hunny95/piky-macos-qa -n piky-interactive-session-<run id> -D ~/Downloads/piky-session
       cd ~/Downloads/piky-session
       /usr/bin/openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -in session.txt.enc

   Type your passphrase. It prints the RustDesk ID and password, and the
   temporary administrator's name and password. Nothing is saved.
4. In RustDesk, enter the ID, then the RustDesk password.
5. On the remote Mac, open Desktop › PIKY-QA › READ ME FIRST.
6. To finish, move "END SESSION - delete this file" to the Trash, or let the
   time run out.

Everything saved in `PIKY-QA/Results` is uploaded as a **public** artifact.
Sign in to nothing on that Mac.

## What was taken from `brunusansi/github-mac-remote`, and what was not

That repository was read (commit `4658f47`). **No file of it is copied here**:
it has no licence, and its RustDesk path does things this repository must not.
Three ideas were kept, each rewritten from Apple's and RustDesk's own
documentation and source:

| Idea | Here |
| --- | --- |
| Start RustDesk's binary from the job, not through LaunchServices | Kept. macOS then counts it as part of GitHub's runner agent, which the image already allows to capture the screen and post input. This, not anything else in that repository, is what makes control work. |
| `RustDesk --password`, `--get-id` | Kept, checked against RustDesk 1.5.0's source (`src/core_main.rs`). |
| A second administrator account for macOS's password prompts | Kept: `sysadminctl -addUser … -admin`, verified with `dscl -authonly` before the session opens. The runner's own account is not touched. |

| That repository does | Why not here |
| --- | --- |
| Writes rows into the system TCC database for RustDesk | Never. No permission database is written by anything in this repository. |
| Uploads the passwords in a plain-text artifact and calls it private | It is not private in a public repository. Here only ciphertext is uploaded. |
| Prints the password in its set-up script, relies on masking alone | Passwords are never printed; masking is the second lock. |
| Downloads RustDesk with no checksum | One release, pinned by SHA-256; the signature is verified before it starts. |
| 12-character passwords, also written to `GITHUB_ENV` | Kept in one private file, never in the environment. The RustDesk password is about 99 bits (pasted on your own Mac). The temporary administrator's is 12 lowercase letters and digits, about 59 bits, because it has to be typed by hand into macOS's password box over a remote desktop. |
| Cloudflare WARP, IP tracking and rotation, Parsec, larger runners, six-hour and chained sessions | None of it. One standard runner, 5 to 120 minutes. |

## What is not known until a session is run

- **Whether control works.** RustDesk should be able to show the desktop and
  move the pointer because of how it is started (above). The workflow prints
  what a job-started program may do on the runner, which is the answer
  RustDesk gets. Only connecting proves it.
- **Whether the temporary administrator opens macOS's prompts.** macOS accepts
  any administrator's name and password in that sheet, and the workflow checks
  that macOS accepts these before the session opens. The sheet itself is only
  proven when a person types into it.

## What the first sessions showed

| | Sonoma, 14.8.9 (run 37660900631) | Tahoe, 26.6.2 (run 37671258943) |
| --- | --- | --- |
| RustDesk shows the desktop, pointer works | Yes | Yes (download, drag into Applications) |
| Typing the administrator's password into macOS's sheet | Worked: Open Anyway was completed | **Could not be done.** PIKY stayed blocked by Gatekeeper |
| RustDesk had to be started again | 0 times | 1 time, 29 minutes in |
| Result | Manual QA passed | **Remote-control tool limitation.** PIKY never ran, so nothing was learnt about PIKY |

Why the keys did not arrive on Tahoe is not known. It may be the link (lag,
dropped keys, the long hyphenated password that run still used), or macOS 26
may not accept keys injected by a remote-desktop tool in its password sheet.
The first can be improved; the second cannot, whatever the settings.

On the controlling side, in the toolbar of the remote window: **Display
Settings** › Optimize reaction time, Mute, Show quality monitor; **Keyboard
Settings** › Translate mode (Map mode if a key arrives wrong). Type a line in
TextEdit on the remote Mac before anything else.

Before a session is announced, RustDesk must now stand for 60 seconds as one
process with one ID. That is the only part of "is the connection good" a
workflow can see by itself: whether a person's keys and pointer arrive needs a
second machine connecting as that person would.

## Things to know

- The connection is brokered by RustDesk's public servers. Whoever has the ID
  and the password controls that Mac for as long as it exists. It holds
  nothing of yours unless you put it there.
- GitHub provides hosted runners for building and testing a repository's
  software. A short manual test of PIKY is that. Using runners as a general
  remote desktop is not, and GitHub can act against accounts that do.
- SIP is disabled on GitHub's image and the account is the image's own. A
  pass here is a pass on that machine, not on a retail Mac.
