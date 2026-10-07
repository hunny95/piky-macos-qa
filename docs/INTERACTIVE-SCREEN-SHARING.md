# Fallback: macOS Screen Sharing over a private tailnet

`interactive-screen-sharing.yml` is the same interactive session as
`interactive-macos-qa.yml` with a different way in: Apple's own Screen
Sharing, reachable only inside your [Tailscale](https://tailscale.com)
network. It is **prepared and has never been run**. It exists because
RustDesk on the hosted Tahoe image could not be used to answer macOS's
password prompt (run 37671258943).

## What is not known

**Whether you can control the Mac, or only watch it.** Since macOS 12.1 Apple
gives full control to Screen Sharing that was switched on in System Settings
(or by device management). A script can only start the service with
`launchctl`, and GitHub's image does not pre-allow Apple's sharing agent. On
Sonoma the service started this way did answer on its port; nobody has yet
connected to it. The first session is the test. Nothing in this repository
writes to a permission database to get round it.

## How you sign in

Not as the runner's own account: its password is unknown and macOS will not
let a job change it. You sign in as the temporary administrator `pikyqa`.
Because another user is already at that Mac's screen, Screen Sharing asks:

- **Ask to share the display**: nobody is there to say yes. Do not choose it.
- **Log in as yourself**: you get a desktop of your own as `pikyqa`. Choose this.

That desktop is a user who has never run PIKY, which is what a clean test
wants. `pikyqa` is an administrator, so macOS's password prompts show its name
already and take the same password. The QA kit is in `/Users/Shared/PIKY-QA`.

## What you need to create (all free)

1. **A Tailscale account** (Personal plan) at <https://login.tailscale.com>, and
   the Tailscale app on your Mac, signed in.
2. **A tag for the runner.** Admin console › Access controls, add to the policy:

       "tagOwners": { "tag:piky-qa": ["autogroup:admin"] },

   and, so the runner can be reached by you on one port and can reach nothing
   of yours, replace the default allow-everything rule with:

       "acls": [
         { "action": "accept", "src": ["autogroup:member"], "dst": ["tag:piky-qa:5900"] }
       ]

   (If you have other devices that must reach each other, keep your own rules
   and add this one.)
3. **An OAuth client.** Admin console › Settings › OAuth clients › Generate:
   scope **Auth Keys: Write**, tag `tag:piky-qa`. It shows a client ID and a
   secret once.
4. **Two repository secrets**, typed in your own Terminal:

       gh secret set TS_OAUTH_CLIENT_ID -R hunny95/piky-macos-qa
       gh secret set TS_OAUTH_SECRET    -R hunny95/piky-macos-qa

   `QA_SESSION_PASSPHRASE` stays as it is.

The OAuth client can do one thing: create nodes that carry `tag:piky-qa`. The
workflow uses Tailscale's own action, pinned to commit `d1b6cd2` (v4.2.0),
which joins as an **ephemeral, pre-approved** node and logs it out when the job
ends. To take it all away again: delete the OAuth client.

## Each session

1. Actions › Interactive macOS QA (Screen Sharing fallback) › Run workflow.
   Joining the tailnet builds Tailscale from source on the runner, so allow
   about ten minutes before the Mac is ready.
2. Download and decrypt the session note exactly as for the RustDesk session.
   It gives the Mac's tailnet address, the name `pikyqa` and its password
   (12 lowercase letters and digits).
3. With Tailscale connected on your Mac: Finder › Go › Connect to Server ›
   `vnc://<address from the note>`. Sign in as `pikyqa`. Choose
   **Log in as yourself**.
4. To finish, delete "END SESSION - delete this file" in
   `/Users/Shared/PIKY-QA`, or let the time run out.

## What is the same as the RustDesk session

No port open to the internet. No VNC password. Session details uploaded only
as ciphertext. Passwords never printed and masked. Everything saved in
`Results` becomes a public artifact. Screen Sharing off, the temporary
administrator and every credential deleted at the end, also if the run is
cancelled. Standard hosted runner only: ₹0.
