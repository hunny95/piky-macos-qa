# A temporary desktop on a hosted runner

`interactive-desktop.yml` is prepared and **not usable yet**: it needs three
secrets nobody has created. This page says what they are, what was checked
before writing it, and what is still unknown.

## Why it exists

The headed run drives macOS with generated events. Two things it cannot do:
answer a macOS prompt that ignores generated input, and judge anything by
eye or hand. A desktop a person can reach for fifteen minutes covers the
first; nothing on a virtual machine covers a trackpad.

## What was looked at, and what was not copied

The widely copied recipe for "VNC into a GitHub macOS runner" (an example:
`Affumii/MacOS-Workflow-VNC`, and its many forks) was read and rejected:

| It does | Why not here |
| --- | --- |
| Opens VNC to the internet through an ngrok TCP address | A public port. Anyone who learns the address reaches the login. |
| Prints that address into the workflow log | In a public repository the log is public. |
| Sets a legacy VNC password (8 characters, reversibly scrambled) | Weak, and passed on a command line. |
| Creates a second administrator account | Not needed. |
| Uses third-party actions by moving tag (`@v2`) with a shell on the machine | Unpinned code holding the session. |

What this repository does instead:

| | |
| --- | --- |
| Network | [Tailscale](https://tailscale.com): the runner joins **your** private network. No public port, no relay address to leak. |
| Node | Ephemeral and pre-approved, created by an OAuth client that can only make nodes with one tag. It disappears when the job ends. |
| Action | Tailscale's own `tailscale/github-action`, pinned to commit `d1b6cd2` (v4.2.0). Its source was read: on macOS it builds `tailscale` from source, runs `tailscaled` with `sudo`, marks the secret as masked, and logs out in a post step. Its shipped `dist/` bundle is 3.5 MB of compiled JavaScript and was **not** audited line by line; the pin is what holds it still. |
| Sign-in | The macOS account, with a password from your secret. No legacy VNC password. |
| Who can start it | `workflow_dispatch` only, and only the repository owner. Secrets live in an environment (`interactive-desktop`), where you can also require your own approval per run. |
| Logs | Nothing but the node's name is written. |
| Lifetime | 15, 30 or 45 minutes, then Screen Sharing is switched off, the node logs out, GitHub destroys the machine. |

No workflow in this repository runs on `pull_request` or `pull_request_target`,
so a stranger's pull request can never reach a secret.

## What you would have to create (all free)

1. **A Tailscale account** (Personal plan, free) at <https://login.tailscale.com>,
   and Tailscale on the Mac you will connect from.
2. **A tag** for the runner. In the admin console › Access controls, add:

       "tagOwners": { "tag:piky-qa": ["autogroup:admin"] },

   and, so the runner can be reached by you and can reach nothing of yours:

       "acls": [
         { "action": "accept", "src": ["autogroup:member"], "dst": ["tag:piky-qa:5900"] }
       ]

3. **An OAuth client** (admin console › Settings › OAuth clients): scope
   **Auth Keys: write**, tag `tag:piky-qa`. It shows a client ID and a secret once.
4. **Three secrets**, in this repository › Settings › Environments ›
   `interactive-desktop` (create it; add yourself as required reviewer):

   | Secret | Value |
   | --- | --- |
   | `TS_OAUTH_CLIENT_ID` | the OAuth client's ID |
   | `TS_OAUTH_SECRET` | the OAuth client's secret |
   | `QA_DESKTOP_PASSWORD` | a new random password of 20+ characters, used for nothing else |

Then: Actions › Interactive desktop (temporary) › Run workflow. On your Mac:
Finder › Go › Connect to Server › `vnc://piky-qa-macos-14`, user `runner`,
the password from the secret.

To take it all away again: delete the OAuth client and the environment.

## What is not known yet

- **Whether you can control the desktop, or only watch it.** Since macOS
  12.1, Screen Sharing switched on from the command line may be view-only:
  control needs a privacy permission for Apple's sharing agent that only a
  person at the Mac, or device management, can give. GitHub's image does not
  pre-allow it (`os/tcc-environment.txt` in any run's evidence). The headed
  run's optional probe only shows that the service starts and answers.
  This can only be settled by one real session.
- **Whether it helps with the prompts.** If control works, a person can
  click Open Anyway and switch on Accessibility by hand, which generated
  input may not be allowed to do.

It was not run: that needs the secrets above, which are yours to create.
