# Spotifast capability and execution audit

Static review completed 2026-10-25. No application build, dependency build,
upstream test, installer, downloaded executable, or app setting change was
performed. No stored credentials, logs, caches or private listening history were
read. The installed app remains trusted as requested. This report concerns what
reviewed source can do, not a sandbox guarantee or certification of the binary.

## Exact subjects

| Subject | Identity |
| --- | --- |
| Installed package | `spotifast 0.13.3`, amd64, Debian package installed at `/usr/bin/spotifast` |
| Installed executable | 42,585,264 bytes; SHA-256 `bc75f305284296448831ba3805eea57163b30a75cb56f484401f0eb4cbe79949` |
| R: source corresponding to upstream tag v0.13.3 | `a4c1b3ef6c9667507f198312453766f6ba953710` |
| B: selected fork baseline, Cargo version 0.14.2 | `3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5` |
| R fastframe v0.6.0 | `0d65ca99eb6d00f10ff556bf985249658feed469` |
| B fastframe v0.14.0 | `dfd2db7bc6a5ae0c62a98383c84235f64da2cace` |
| R librespot | `847125198bb251d1d4497f46bebbfa4868b7d5d7` |
| B librespot | `3ba977f1f918582edce566cfc16617f8eccdfb1e` |
| Both hyper-proxy2 | `efca4811371ddae81c06be168de54194938d70b1` |
| Both reqwest | crates.io 0.12.28; fetched archive SHA-256 verified against Cargo.lock: `eddd3ca559203180a307f12d114c268abf583f59b03cb906fd0b3ff8646c1147` |

[Installed metadata](installed-metadata.json) records the observation time.
[Source inventory](source-inventory.json) records all Git dependency sources and
priority package versions/checksums. R has 769 lockfile packages; B has 788.
These counts include target-specific/optional packages, not a resolved runtime
binary inventory. Version labels do **not** establish binary/source equivalence;
no reproducible rebuild or installed-binary provenance proof was attempted.

## Overall assessment

No standalone app analytics SDK, crash uploader, advertising integration, or
Spotifast-operated reporting endpoint was found in the reviewed application
paths, lockfiles, fastframe logging/update code, or selected librespot network
paths. Confidence is moderate: the review traced relevant calls and defaults,
but did not inspect every transitive dependency or capture runtime traffic.
Spotify receives authenticated service traffic and device/platform identifiers;
that is substantial data transmission even without a separate telemetry SDK.

The upstream privacy page is broadly consistent with those paths, but its
phrases about sending no identifying information to lyrics services and only
connecting to listed services need qualification. Requests reveal network IP,
app version/user agent and timing; artwork URLs and redirects can choose other
hosts. The website includes Plausible JavaScript; that script is not part of the
native application. [B privacy][Bprivacy], [B website][Bwebsite], [R website][Rwebsite].

## Network capability inventory

Evidence links marked R and B refer to exact immutable commits, not moving branches.

| Capability | R (0.13.3 source) | B (fork baseline) | Destinations, fields, credentials and trigger |
| --- | --- | --- | --- |
| OAuth browser sign-in | Separate playback, shared Web API and optional personal grant | Playback plus personal Web API; prior shared-client flow retired | `accounts.spotify.com/authorize` and `/api/token`; client ID, scopes, redirect URI, PKCE challenge/verifier, state, code and refresh token. Access/refresh tokens remain sensitive. Requests begin on sign-in or token refresh. Loopback callbacks discussed below. [R auth][Rauth], [B auth][Bauth] |
| Spotify catalogue/account operations | Library, search, playlists, upload artwork, account/playback operations | Same broad capabilities with expanded session-based fallbacks and Pathfinder reads | `api.spotify.com/v1`, `api-partner.spotify.com/pathfinder/v2/query`, session-resolved Spotify endpoints; search strings, account/playlist/track IDs, image bytes for user-selected cover uploads, playback commands. Web API uses per-request Bearer authorization; Pathfinder uses Bearer plus `client-token`. [R API][Rapi], [B API][Bapi], [B session reads][Bsession] |
| Personalized Home shelves | Home query uses a verified Web API context token | Same with paginated shelves and expanded fallbacks | `api-partner.spotify.com/pathfinder/v2/query`; Login5 Bearer plus `client-token`, and the Web API access token in JSON `variables.sp_t`, country and time zone. Triggered by Home shelf loading; cached per account. These multiple credentials go to Spotify, not LRCLIB. [R Home][Rhome], [B Home][Bhome] |
| Playback and Connect session | Pinned librespot fork | Different pinned fork; adds configured local-file lookup integration | `apresolve.spotify.com`, dynamically resolved accesspoint/dealer/spclient hosts, `login5.spotify.com`, `clienttoken.spotify.com`, audio CDN URLs. Device ID, account credentials/tokens, client version, platform/kernel/architecture, track/queue/volume/play state and connection identifiers. Persistent session/Connect messages support remote control from Spotify devices. `device_id` is SHA-1 of the configured device name, stable across restarts. [R player][Rplayer], [B player][Bplayer], [R session][RLsession], [B session][BLsession], [B client token][BLspclient] |
| Lyrics | Spotify lyrics first, LRCLIB fallback | Embedded local-file lyrics first, then Spotify, then LRCLIB | `lrclib.net/api/get` and `/search`; artist, title, optional album, duration; no Spotify Authorization attached on LRCLIB requests. Triggered when lyrics are requested/open; new tracks refresh while the panel is open. Cache hits can avoid a request. [R lyrics][Rlyrics], [R backend][Rbackend], [B lyrics][Blyrics], [B backend][Bbackend], [B UI trigger][Blyricstrigger] |
| Artwork | Remote images and disk cache | Same; includes local embedded artwork paths | HTTP(S) URLs supplied by metadata, typically `i.scdn.co`/`mosaic.scdn.co`, not a host allowlist. Ordinary shared client requests, without Spotify bearer headers. Loaded as views/art require them. [R images][Rimages], [B images][Bimages] |
| Update metadata and payloads | Enabled daily checks; automatic downloads off by default | Same defaults; AppImage self-update support added | `api.github.com`, `github.com`, `release-assets.githubusercontent.com`, `objects.githubusercontent.com`; repo/release/platform asset names and `Spotifast/<version>` user agent. No Spotify bearer header. Signed checksums and SHA-256 precede execution; portable download itself can execute the result. [R settings][Rsettings], [B settings][Bsettings], [R update][Rupdates], [B update][Bupdates], [B transport][BFtransport] |
| MilkDrop preset acquisition | Optional packs downloaded on use | Same mutable upstream pack URLs | GitHub projectM preset repositories at `refs/heads/master.zip`, normally redirected to GitHub archive hosting. Shared configured proxy/client. Whole archive downloaded into memory, `.milk` entries written to config and consumed by projectM. Not the signed application updater. [R presets][Rpresets], [B presets][Bpresets] |
| LAN receiver discovery/activation | Connect and Cast discovery | Same, with additional bounded provisional Cast discovery updates | mDNS `_spotify-connect._tcp.local.` and `_googlecast._tcp.local.`. Discovery probes Connect `getInfo` before selection; selection sends encrypted reusable Spotify credentials to the receiver's advertised DH key. Cast exchanges a receiver-specific Spotify token after device authentication. LAN HTTP bypasses configured proxies. [R LAN][Rlan], [B LAN][Blan], [R Cast][Rcast], [B Cast][Bcast] |
| Demo artwork | Development feature uses online placeholder artwork | Same | `picsum.photos/seed/spotifast...` and any redirects: deterministic demo data is not fully offline. No private account data is needed for these images. [R demo][Rdemo], [B demo][Bdemo] |
| Browser handoff | External URLs/folders through desktop opener | Same | User-opened help, repository, skin museum and Spotify links leave the app and use the browser's independent network/proxy/cookie settings. [R opener][Ropener], [B opener][Bopener] |

### Redirects and proxy behavior

Both revisions default to System proxy mode. The shared reqwest client uses
native trust roots and inherits system/environment proxy behavior; Off calls
`no_proxy`, manual HTTP/SOCKS uses the configured proxy. The configured password
uses protected storage. These are not universal routing guarantees: librespot
accepts only a compatible unauthenticated HTTP proxy, rejects credential-bearing
proxy URLs, and does not support SOCKS for the engine. LAN and desktop/browser
handoffs have separate transport paths. [R HTTP][Rhttp], [B HTTP][Bhttp],
[R proxy][Rproxy], [B proxy][Bproxy], [B librespot HTTP][BLhttp], [proxy fork][proxy].

Ordinary reqwest requests retain its default redirect policy (up to ten hops),
with HTTPS-only mode not enabled globally. Cross-host/port redirects strip
standard Authorization, Cookie and Proxy-Authorization headers; arbitrary custom
headers such as `client-token` are not on that stripping list. This is a source
observation, not evidence that Spotify currently redirects a token-bearing
request off origin. Both revisions' collection-write clients disable redirects
and retries. Update transport separately disables automatic redirects and checks
each hop against its release-host policy (maximum five). LAN `getInfo` clients
have `no_proxy` but do not set `Policy::none`. [reqwest redirect source][reqredirect],
[B HTTP][Bhttp], [B update transport][BFtransport], [B LAN][Blan].

## Local capabilities and controls

| Area | R evidence and behavior | B evidence and differences |
| --- | --- | --- |
| Credential storage | Linux Secret Service, macOS Keychain, Windows Credential Manager; protected-store worker and migration of old token files. Librespot credential cache explicitly uses memory. The `StoredToken::save` JSON writer is `cfg(test)`, not current production persistence. [R credentials][Rcredentials], [R auth][Rauth], [R player][Rplayer] | Same native stores, plus Windows DPAPI-sealed fallback/copy and portable-profile identity handling. Read/write/revocation errors are surfaced; ordinary state is not a replacement store. [B credentials][Bcredentials], [B paths][Bpaths] |
| Settings, history, cache | Settings include last 12 searches; session/recent-play history, audio, art, lyrics and account-scoped library/home/playlist caches are local files. These are private user data even though they are not secrets. [R paths][Rpaths], [R settings][Rsettings] | Same categories; extra device-history/profile/local-file-related state and portable Windows data directory. Sign-out cleanup is account-aware, but this review does not guarantee every historical file is erased. [B paths][Bpaths], [B settings][Bsettings], [B history][Bhistory] |
| Logs and panics | Local `spotifast.log` and `panic.log`; no uploader in reviewed logging crate. Startup records app version, OS, architecture. Panic URL redaction enabled. Environment `RUST_LOG` can broaden diagnostics. [R entry][Rentry], [R logger][RFlog] | Same architecture. Ordinary logs are not guaranteed to contain no sensitive metadata: redaction of panic links is not universal redaction of every dependency log. [B entry][Bentry], [B logger][BFlog] |
| OAuth listener | `127.0.0.1`, playback port 8898 and Web API port 8989, `/login`; PKCE S256 plus random state; 10-minute overall wait, 5-second request-line timeout, 8-KiB request-line bound. [R auth][Rauth] | Same loopback constraints. Not a LAN HTTP API. [B auth][Bauth] |
| Local IPC/control | Per-user Unix socket on Linux/macOS; on Windows a loopback listener with random token stored beside lock. Commands include playback, volume, transfer, now-playing/device reads. Same-user processes can use this interface; now-playing reveals listening metadata. [R IPC][Ripc], [R instance][RFinstance] | Same design plus portable instance scoping and expanded commands. Unix directory 0700/socket 0600; bounded request and token checking in fastframe. [B IPC][Bipc], [B instance][BFinstance] |
| Desktop integration | Tray, media keys/MPRIS, system media controls, notifications/window behavior, URL scheme and browser handoff. Text inputs and copy controls access clipboard. [R entry][Rentry], [R IPC][Ripc] | fastframe now-playing integration; explicit Copy/Paste menu routes and selected-text actions. No continuous clipboard collection found in reviewed paths. [B entry][Bentry], [B widgets][Bwidgets] |
| Local content access | User-selected skins, themes, presets, cover images and installed fonts; archive/media/font parsers operate with user permissions | Adds chosen local music folder, tag/art/lyrics reading and librespot recursive file lookup; default folder is `None`. `.milk` presets drive native projectM rendering in a child process. [B settings][Bsettings], [B local tags][Btags], [B local lookup][BLlocal], [B preset process][Bmilkhost] |
| Autostart | User-selectable fastframe integration, platform startup mechanisms | XDG desktop/Flatpak background portal on Linux, LaunchAgent on macOS, registry startup on Windows. Reads current registration; setter modifies it on requested changes. This audit did not query or change installed registration. [R autostart][RFautostart], [B autostart][BFautostart] |
| Subprocesses and executable replacement | Desktop opener, MilkDrop child, updater helper/relaunch, package ownership probes, `tar -xOf`, platform installers/tools | Same broad capability; additional AppImage path. Updater extracts one named executable to a newly created destination, rather than unpacking an arbitrary archive tree. Staging is randomized and private (0700 on Unix); signed manifest, asset hash, version check and helper/rollback checks are present. System package installs are detected via package ownership probes and excluded from self-replacement. [R updater download][RFdownload], [B updater download][BFdownload], [B host][BFhost], [B detection][BFdetect] |

## Findings and proposed follow-up patches

Severity describes the observed capability/risk, not a demonstrated exploit.
No application fixes were applied in this setup pass.

| ID | Severity / confidence | Affected source | Finding and concrete next change |
| --- | --- | --- | --- |
| F1 | Medium / high | R and B, portable update path; B also AppImage | **Download is an execution step.** After signature/hash validation, `download` invokes the new executable with `--version`. Automatic download defaults off, and a Debian-owned executable is normally excluded. Move this probe behind explicit install authorization, or label download as execution and run probing in an appropriately constrained process. Test that downloading alone starts no new binary. [R download][RFdownload], [B download][BFdownload], [B host][BFhost] |
| F2 | Medium / high | R and B MilkDrop | **Mutable, unsigned content supply chain and resource limits.** Packs use branch ZIP URLs, no pinned digest/signature, and `response.bytes()` buffers the whole download. The ZIP reader has a 64-MiB per-entry inflate limit, but that is not an archive/aggregate limit. Presets are flattened to plain `.milk` basenames; existing destination symlinks are not explicitly rejected before `fs::write`. Pin pack commits/digests, bound compressed/aggregate decoded bytes and count, and write without following existing links. Test oversized packs, duplicate basenames and symlink destinations. This does not establish arbitrary native code execution from a preset. [R presets][Rpresets], [B presets][Bpresets], [B ZIP reader][Bzip] |
| F3 | Medium / high for policy gap; exploitability untested | R and B Connect LAN HTTP | **LAN discovery is not a strict network boundary.** mDNS data chooses address/port/path, and direct `getInfo`/activation clients retain default redirects. A hostile receiver can influence where a direct request goes; the advertised DH key is not an identity certificate. Set redirects to none, constrain endpoint/address classes and paths, bound responses and clearly identify a selected receiver before credential handoff. Keep Cast's separate device-authentication checks. [R LAN][Rlan], [B LAN][Blan], [B activation][Bactivation] |
| F4 | Low / high for implementation; conditional consequence | Both general HTTP clients and Pathfinder custom header | **Service HTTP policy is broader than intended destinations.** Artwork accepts arbitrary HTTP(S) URLs and normal requests permit cross-origin redirects. Reqwest strips standard bearer headers, but not custom `client-token`. Use separate clients: HTTPS-only Spotify/auth endpoints with same-origin or no redirects, artwork with explicit URL/address policy, and isolated LAN transport. Add redirect/header fixtures before changing behavior. No off-origin Spotify redirect or actual token disclosure was observed. [B API][Bapi], [B images][Bimages], [B HTTP][Bhttp], [reqwest source][reqredirect] |
| F5 | Low / high | R and B | **Third-party lyrics and daily update checks disclose metadata.** LRCLIB receives song fields; service operators also see IP/timing and app version. Keep precise disclosure and, in a future approved feature task, consider a per-service opt-out or Spotify-only lyrics mode. Closing lyrics and disabling automatic update checks already limit these paths. Demo images need bundled fixtures for genuinely offline development. [R lyrics][Rlyrics], [B lyrics][Blyrics], [B settings][Bsettings], [B demo][Bdemo] |
| F6 | Informational / high | R and B runtime and build inputs | **Trust boundaries are wider than the installed executable.** Native parsers, same-user IPC, local data files, build scripts/proc macros, package tooling and workflows all carry capabilities. Keep this pass's no-build/no-workflow boundary. Before a future build, review pinned build dependencies and CI actions, select explicit features/platforms, and isolate credentials/network as appropriate. [B build][Bbuild], [B workflows][Bci] |

Positive controls worth preserving: platform credential stores already in R;
PKCE/state and loopback callbacks; signed update manifests before payload use;
strict update-host redirect policy; package-manager self-update refusal; bounded
Cast frames and device-authentication challenge before token delivery. The
Cast TLS custom verifier alone is **not** evidence of unauthenticated token
handoff: the application performs its own nonce/certificate-chain validation
before proceeding. [R Cast][Rcast], [B Cast][Bcast].

## Build, dependency and workflow review

Application `build.rs` calls fastframe's PO catalogue compiler, embeds Windows
resources, and locates native GLEW libraries. That build compiler reads PO files
and emits Rust. Librespot `core/build.rs` derives Git/build metadata and a build
ID; `protocol/build.rs` generates Rust from protobufs. Building also executes
registry proc macros (for example serde/clap/thiserror/tokio derives/macros) and
native build dependencies. These were inventoried as execution surfaces, not
executed or exhaustively reviewed. `mise.toml` declares Rust 1.98 and a moving
`mr-boxington = "latest"`; no mise trust was granted. `.cargo/config.toml` holds
Windows static-runtime flags, not an execution exemption. [B build][Bbuild],
[B Cargo manifest][Bcargo], [B libre build][BLbuild], [B proto build][BLproto],
[B i18n build][BFi18n], [Cargo build-script behavior](https://doc.rust-lang.org/cargo/reference/build-scripts.html).

Git dependencies in both lockfiles are all under `github.com/crmne/`. Fastframe
uses a manifest tag but the lockfile records an exact commit. Egui/winit,
projectm-rs and B's cpal are additional pinned forks. Registry package checksums
and exact Git revisions constrain retrieval; they are not attestations of safe
behavior. Selected fastframe logging, IPC, autostart, update transport/download/
extraction/signing, librespot auth/client-token/proxy/session/local-file paths,
and hyper-proxy2 CONNECT handling were read. Reqwest's exact crate checksum and
redirect implementation were verified. The remaining GUI/audio/native parsers,
keyring providers and transitive build/macro crates remain unreviewed internally.

CI compiles/tests Rust and runs source policy scripts. Release/packaging workflows
build binaries, consume signing credentials, package/publish releases and call
shared native-packages workflows; docs deploys a website; issue assessment calls
external triage automation. Several action references are mutable version tags.
These files were inspected as source, not run. Actions on `carbon853/spotifast`
was disabled via the repository permissions API **before setup changes were
pushed**, and rechecked during delivery. No upstream programs are called by the
maintenance CLI. [B CI][Bci], [B release][Brelease], [B packaging][Bpackaging],
[B triage][Btriage], [R CI][Rci].

Git host package is `1:2.48.1-0ubuntu1.1`; the Debian/Ubuntu changelog confirms
backports for CVE-2025-48384 and CVE-2025-48385, alongside the other fixes in
[Ubuntu USN-7626-1](https://ubuntu.com/security/notices/USN-7626-1).
This verifies those fixes, not an assertion that an older distribution's Git has
every subsequently published security fix. No Git package upgrade was performed.
The maintenance CLI additionally isolates configuration, disables hooks/filter
use/fsmonitor/external diff, allows HTTPS only, and never recursively initializes
submodules.

## Limits and follow-up scope

No runtime packet capture, binary reverse engineering, adversarial app execution,
full dependency advisory scan, cryptographic proof of a release's build process,
or Windows/macOS live validation was performed. Dynamic Spotify/CDN destinations
cannot be enumerated exhaustively from static code. Secret Service/OS keychain
access policies, filesystem ACLs, actual user settings and installed autostart
were not inspected. Lack of a telemetry match is not proof of absence across
all 788 dependencies. Findings are static observations with suggested tests for
a later explicitly authorized implementation pass.

[Bprivacy]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/docs/_reference/privacy.md#L7

[Bwebsite]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/docs/_includes/jekyll_vitepress/head_end.html#L1

[Bauth]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/auth.rs#L30

[Bapi]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/api/client.rs#L22

[Bsession]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/session_reads.rs#L1

[Bplayer]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/player.rs#L40

[Blyrics]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/lyrics.rs#L120

[Bbackend]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/backend.rs

[Blyricstrigger]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/app.rs#L3694

[Bimages]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/images.rs#L100

[Bsettings]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/settings.rs

[Bupdates]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/updates.rs#L15

[Bpresets]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/milkdrop.rs#L92

[Blan]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/zeroconf.rs

[Bcast]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/cast.rs#L120

[Bdemo]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/demo.rs#L22

[Bopener]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/opener.rs#L1

[Bhttp]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/http.rs#L65

[Bproxy]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/settings.rs

[Bcredentials]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/credentials.rs#L252

[Bpaths]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/paths.rs

[Bhistory]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/history.rs

[Bentry]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/entrypoint.rs

[Bipc]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/single_instance.rs

[Bwidgets]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/ui/widgets.rs#L3132

[Btags]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/local_tags.rs

[Bmilkhost]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/milkdrop/host.rs#L100

[Bzip]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/skin/zip.rs#L20

[Bactivation]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/backend.rs#L4063

[Bbuild]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/build.rs#L47

[Bcargo]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/Cargo.toml

[Bci]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/.github/workflows/ci.yml

[Brelease]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/.github/workflows/release.yml

[Bpackaging]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/.github/workflows/packaging.yml

[Btriage]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/.github/workflows/issue-assessment.yml

[Rwebsite]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/docs/_includes/jekyll_vitepress/head_end.html#L1

[Rauth]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/auth.rs#L30

[Rapi]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/api/client.rs#L22

[Rplayer]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/player.rs#L40

[Rlyrics]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/lyrics.rs#L120

[Rbackend]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/backend.rs

[Rimages]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/images.rs#L100

[Rsettings]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/settings.rs

[Rupdates]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/updates.rs#L15

[Rpresets]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/milkdrop.rs#L92

[Rlan]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/zeroconf.rs

[Rcast]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/cast.rs#L120

[Rdemo]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/demo.rs#L22

[Ropener]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/opener.rs#L1

[Rhttp]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/http.rs#L65

[Rproxy]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/settings.rs

[Rcredentials]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/credentials.rs#L252

[Rpaths]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/paths.rs

[Rentry]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/entrypoint.rs

[Ripc]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/single_instance.rs

[Rci]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/.github/workflows/ci.yml

[BFtransport]: https://github.com/crmne/fastframe/blob/dfd2db7bc6a5ae0c62a98383c84235f64da2cace/crates/fastframe-update/src/transport.rs#L90

[BFlog]: https://github.com/crmne/fastframe/blob/dfd2db7bc6a5ae0c62a98383c84235f64da2cace/crates/fastframe-log/src/logger.rs#L96

[BFinstance]: https://github.com/crmne/fastframe/blob/dfd2db7bc6a5ae0c62a98383c84235f64da2cace/crates/fastframe-instance/src/lib.rs#L250

[BFautostart]: https://github.com/crmne/fastframe/blob/dfd2db7bc6a5ae0c62a98383c84235f64da2cace/crates/fastframe-autostart/src/linux.rs#L15

[BFdownload]: https://github.com/crmne/fastframe/blob/dfd2db7bc6a5ae0c62a98383c84235f64da2cace/crates/fastframe-update/src/download.rs#L30

[BFhost]: https://github.com/crmne/fastframe/blob/dfd2db7bc6a5ae0c62a98383c84235f64da2cace/crates/fastframe-update/src/host.rs#L185

[BFdetect]: https://github.com/crmne/fastframe/blob/dfd2db7bc6a5ae0c62a98383c84235f64da2cace/crates/fastframe-update/src/detect.rs#L200

[BFi18n]: https://github.com/crmne/fastframe/blob/dfd2db7bc6a5ae0c62a98383c84235f64da2cace/crates/fastframe-i18n/src/build.rs#L74

[RFlog]: https://github.com/crmne/fastframe/blob/0d65ca99eb6d00f10ff556bf985249658feed469/crates/fastframe-log/src/logger.rs#L96

[RFinstance]: https://github.com/crmne/fastframe/blob/0d65ca99eb6d00f10ff556bf985249658feed469/crates/fastframe-instance/src/lib.rs#L250

[RFautostart]: https://github.com/crmne/fastframe/blob/0d65ca99eb6d00f10ff556bf985249658feed469/crates/fastframe-autostart/src/linux.rs#L15

[RFdownload]: https://github.com/crmne/fastframe/blob/0d65ca99eb6d00f10ff556bf985249658feed469/crates/fastframe-update/src/download.rs#L30

[BLsession]: https://github.com/crmne/librespot/blob/3ba977f1f918582edce566cfc16617f8eccdfb1e/core/src/session.rs#L150

[BLspclient]: https://github.com/crmne/librespot/blob/3ba977f1f918582edce566cfc16617f8eccdfb1e/core/src/spclient.rs#L153

[BLhttp]: https://github.com/crmne/librespot/blob/3ba977f1f918582edce566cfc16617f8eccdfb1e/core/src/http_client.rs#L148

[BLlocal]: https://github.com/crmne/librespot/blob/3ba977f1f918582edce566cfc16617f8eccdfb1e/playback/src/local_file.rs#L56

[BLbuild]: https://github.com/crmne/librespot/blob/3ba977f1f918582edce566cfc16617f8eccdfb1e/core/build.rs#L1

[BLproto]: https://github.com/crmne/librespot/blob/3ba977f1f918582edce566cfc16617f8eccdfb1e/protocol/build.rs#L1

[RLsession]: https://github.com/crmne/librespot/blob/847125198bb251d1d4497f46bebbfa4868b7d5d7/core/src/session.rs#L150

[reqredirect]: https://docs.rs/crate/reqwest/0.12.28/source/src/redirect.rs
[proxy]: https://github.com/crmne/hyper-proxy2/blob/efca4811371ddae81c06be168de54194938d70b1/src/lib.rs#L457

[Rhome]: https://github.com/crmne/spotifast/blob/a4c1b3ef6c9667507f198312453766f6ba953710/src/made_for_you.rs#L120
[Bhome]: https://github.com/crmne/spotifast/blob/3bc6bb48e2f83e63780e2b0f10b40bda17c5eed5/src/made_for_you.rs#L215
