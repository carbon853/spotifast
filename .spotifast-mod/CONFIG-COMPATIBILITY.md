# Preserving the installed configuration and sign-in

Static review compares upstream v0.13.3 (`a4c1b3ef6c9667507f198312453766f6ba953710`)
with the pinned v0.14.2 (`3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5`). No user
configuration, credential contents, keyring records or listening history were read.

The installer replaces only seven allowlisted system package files. It refuses
maintainer scripts, symlinks and unexpected files. It never purges Spotifast,
changes the app identity, resets settings, exports credentials or touches user
state. Package rollback has the same constraints. Tests use fresh fake data.

Both versions use the `spotifast` Linux per-user directories, with the same
ProjectDirs identifiers (`me`, `paolino`, `spotifast`). The new fastframe directory
wrapper adds Windows portable support. Linux installed builds retain the per-user
locations. The credential service is `rocks.spotifast.Spotifast`, with unchanged
`shared-web`, `personal-web`, `playback` and `proxy-password` slot names. Profile
keys derive from the state directory path using SHA-256. Therefore retaining the
same user and XDG state path is essential; relaunch carries HOME and all XDG
location overrides from the invoking desktop environment. Invoke installation
from the same user/session that normally starts the application.

Saved Web API grants contain the client ID they were issued to. Version 0.14.2
continues refreshing them with that saved ID (`src/api/client.rs`) and accepts
saved shared grants (`src/credentials.rs`). Its release notes explicitly preserve
already signed-in sessions. New sign-ins need a personal Spotify app, but upgrading
a valid saved grant does not itself require a new sign-in. Playback credentials
remain separate and retain their slot.

Expected result: existing settings and valid saved sign-ins remain usable. This
is a source-level compatibility conclusion, not a guarantee that Spotify will
accept a particular grant or that the desktop keyring is unlocked. We do not
probe live grants to prove it. Spotify revocation or a locked/unavailable keyring
can still prevent sign-in restoration. Restoring the old package cannot undo a
server-side revocation or normal token rotation/settings writes after a real launch.

Preservation does not mean byte-identical settings after the application runs.
Upstream 0.14.2 uses a new audio engine: it reads but ignores the old
`audio_backend` setting and omits that retired key on the next settings save.
It retains `audio_device` and other preferences; upstream regression tests cover
loading the older format. Restoring 0.13.3 after that save uses its default audio
backend. This migration is independent of sign-in storage and is not introduced
by the filtering modification.

Before initial replacement, review this limitation with the user and obtain the
requested confirmation once the actual package and rollback target are ready.
