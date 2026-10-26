# Spotifast modification workspace

The editable application source lives at the repository root. `lib/spotifast`
is the only approved submodule, pinned to the revision in `upstream.json`.
`patches/` plus the explicit `series` file reproduce the root source from that
revision. The initial patch changes only the root agent guide. The installed
application, its settings, and its credentials are outside this workspace.

## Execution boundary

Run only reviewed maintenance code, using the system Python in isolated mode:

```sh
/usr/bin/python3 -I .spotifast-mod/tool.py status
/usr/bin/python3 -I .spotifast-mod/tool.py test
```

Feature builds are explicitly authorized only through the reviewed local pipeline
below. Source, dependencies, build scripts and proc macros run in Bubblewrap,
without host credentials, app data, desktop sockets or external networking.
Dependency and toolchain acquisition is separate from compilation. Never run
host Cargo, mise, fetched scripts, package workflows or automatic workspace
tasks. GitHub Actions remains disabled at the fork repository level.

Requirements: Linux/POSIX, `/usr/bin/git`, `/usr/bin/python3` (3.11+), and a regular
checkout with a real `.git` directory. Linked root worktrees, submodules other
than the approved one, filenames containing control characters/backslashes,
unsafe symlinks, and source paths under the reserved namespaces are refused.
No third-party Python packages are needed.

## Commands

| Command | Effect |
| --- | --- |
| `status` | Print the pin, ordered series, root source drift, detached submodule HEAD and unstaged additions. No fetch. |
| `capture <name>` | Append a deterministically numbered, binary-capable patch for current root edits. Stage new files first. Names use lowercase letters, digits and hyphens. |
| `refresh` | Replace only the final patch with the difference from upstream plus preceding patches. |
| `apply` | Apply the series to a pristine root source, or do nothing if it already matches. Refuse other worktree or staged source changes. |
| `verify` | Reconstruct and compare source bytes, file types and executable modes; also check the pristine submodule and its detached pin. Does not change source or the developer index. |
| `update <ref>` | Retired entry point; use the explicit staging rebase workflow below. |
| `test` | Run maintenance, deployment-failure and rebase fixture tests, then verify real source/submodule. No app tests or network. |

Source integration is separate from local deployment. The old internal updater
is retained for maintenance regression fixtures; the CLI directs agents to the
staging workflow. No command implicitly rebases.

## Editing and committing

1. Edit root source. Do not edit the submodule.
2. Stage new source files so capture can distinguish intended additions from
   unexpected untracked files. All untracked source, including ignored files,
   is checked; build output stays in reserved, ignored `.spotifast-mod/local/`.
3. Run `capture descriptive-name`, or `refresh` while revising the latest feature.
4. Run `test`. Commit root source and its patches together, including the series.
5. Before pushing, check that fork Actions remains disabled:
   `gh api repos/carbon853/spotifast/actions/permissions` must show `enabled: false`.

For ordinary Git staging/committing, use the reviewed local config and an empty
system/global config. Do not introduce local `include`, filter, hook, fsmonitor,
external diff or submodule command settings. For example, in a shell with no
inherited `GIT_*` overrides:

```sh
GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
  git -c core.hooksPath=/dev/null -c core.fsmonitor=false add -- src/example.rs
```

Use explicit paths; stage only intended files. Git author identity must be set
explicitly when committing with the global configuration disabled. Authentication
for a push is a separate GitHub operation; the maintenance CLI never obtains or
uses credentials.

The maintenance commands create their own bare Git directory and temporary index
under ignored `scratch/`, sharing only object databases. They never read the root
Git configuration and never use the developer index for reconstruction. They read
its stage-zero entries only to identify staged additions and protect staged edits.
Hashing uses `--no-filters`; diffs disable text conversion and external commands;
replay uses `git apply --cached`. Materialization writes raw reviewed blobs with
Python. Git subprocesses use argument arrays, an allowlisted environment, HTTPS
only, no credentials, no recursive submodule fetch, and no hooks/templates or
automatic maintenance. They do not import application modules.

`.spotifast-mod/`, `.gitmodules`, `.git/`, and the entire `lib/` namespace are
reserved for infrastructure and excluded from source patches. A new upstream
entry in a reserved namespace is rejected rather than silently skipped. New
upstream submodules likewise require separate review and tool changes. The guide
is source and is intentionally captured in `0001-infrastructure.patch`.

## Fresh checkout and verification

Use the reviewed local fresh-check helper with an exact pushed fork commit:

```sh
/usr/bin/python3 -I .spotifast-mod/fresh_check.py <40-character-fork-commit>
```

It independently fetches the fork and approved submodule over HTTPS into ignored
scratch, inspects paths/modes before writing raw blobs, compares maintenance code
to this reviewed copy before running it, verifies replay and runs the fixture
suite. It checks that the root index stays unchanged and deletes the temporary
checkout afterward. It does not recursively fetch modules or use credentials.

For a persistent checkout, fetch the fork with `--no-checkout --no-recurse-submodules` over HTTPS using the
configuration restrictions above. Inspect its `ls-tree -rz` listing before
checkout, including modes, symlink targets, the maintenance code and `.gitmodules`.
Only `lib/spotifast` may be a gitlink, and its HTTPS URL must be
`https://github.com/crmne/spotifast.git`. Review this directory's code before running
it. No source-defined hooks or filters are needed to materialize the tree.

Initialize only that submodule, without recursion; fetch its exact gitlink SHA
with no checkout, inspect that tree, then detach at the approved SHA. Do not use
`submodule update --remote`. `test` must then pass with the root and submodule
unchanged. Both embedded `.git` directories and normal submodule gitfiles under
the root's `.git/modules/` are supported. A full-history clone of the fork retains
upstream ancestry; a fresh approved submodule supplies future upstream pins that
are not ancestors of the fork branch.

## Safety limits and recovery

This tooling defends against untrusted fetched source and patch paths, not a
concurrent hostile local process modifying the checkout or maintenance files.
Maintenance commands serialize with a lock; stop editors/other writers during
apply/update. Existing symlink parents and file/directory collisions are refused.
File/directory shape changes that need removing a parent require manual review.

Replay/path failures are preflighted before writes. Individual file replacements
are atomic, but a filesystem failure or interrupted process during a multi-file
materialization is not a transactional rollback. Keep work committed before an
update. If interrupted, preserve any work, inspect source/pin/submodule HEAD and
restore the prior committed tree before retrying. Never blindly force an apply.

`apply` is intentionally conservative: it accepts either the recorded pristine
baseline or the exact expected result. It does not erase edits or guess whether
an old, edited patch should replace an earlier applied version. `refresh` records
intentional root changes without rewriting earlier patches.

## Audit

See [the capability audit](audit/CAPABILITIES.md), [exact source/dependency pins](audit/source-inventory.json),
and [installed package metadata](audit/installed-metadata.json). This is a static
capability review, not a claim that the installed binary matches a source tree or
that every transitive dependency has been audited.

## Local build and deployment

Run `python3 -I .spotifast-mod/local.py COMMAND` as the desktop user:

| Command | Effect |
| --- | --- |
| `doctor` | Report clean-source/replay, native dependency, toolchain, sandbox, disk and rollback readiness. |
| `doctor --prepare` | Acquire Rust 1.98.0 using the installed trusted rustup in an isolated network sandbox. Download and validate the installed version's rollback package against release checksums and installed file hashes. No compilation or installation. |
| `build` | Snapshot the exact clean main commit, acquire locked dependencies, run offline checks, compile default features including MilkDrop, smoke-test the production login window, and package a versioned amd64 `.deb`. |
| `install <build-id>` | Revalidate source, manifest, archive and an install transaction affecting only Spotifast; gracefully quit through MPRIS, replace the package, check ownership/hashes/version/startup, and relaunch if it was running. |
| `deploy` | Build, then install that exact build. Never fetch/integrate upstream source. |
| `status` | Report installed package/hash, recorded pin and deployment journal, without app data. |
| `rollback` | Restore the retained previous package, with the same transaction/shutdown/verification safeguards. |

Requirements include Bubblewrap with user namespaces, 20 GiB available for build
outputs on internal storage (reusable caches count toward this, with at least
8 GiB still free), Rust 1.98.0 (acquired privately), a C/C++ toolchain, CMake,
libclang, pkg-config, ALSA/PipeWire/Wayland/XKB/OpenGL/OpenSSL/DBus development
libraries, Ruby with development headers, Xvfb, xdotool and dbus-run-session. `doctor` reports exact gaps. The
pipeline never installs system prerequisites. Run final installation from your
own terminal after `sudo -v`; it uses `sudo -n` and will stop before quitting the
app if privilege is unavailable.

Builds use a read-only source snapshot and separate writable Cargo cache and
target directory. Baseline and candidate demo builds own separate targets, seeded
by copying the completed dependency cache without hard links. A second disk check
reserves the baseline copy plus 4 GiB of headroom. Completed test executables are
removed before this step; baseline outputs are removed after their captures.
The acquisition sandbox has network but no host home or bus.
The compile/test sandbox has no external network. Both use an allowlisted
environment and minimal filesystem mounts. No desktop credential store is
available. Ruby gems are acquired against Gemfile.lock checksums, then installed and the
documentation built offline. Before/after demo captures cover light/dark themes
at 1280×800 and 800×600 on a private X server; their hashes go in the manifest.
Review these captures before initial installation. The production executable has
no demo feature. Native ELF dependencies
are inferred with dpkg-shlibdeps and supplemented with the runtime dlopen
libraries from the packaging policy. Packages cannot contain maintainer scripts,
symlinks, unexpected files or user-data paths.

The manifest records the commit, upstream pin, ordered patch hashes, toolchain,
features, package hash and every payload hash. Failed builds never become
installable artifacts. Successful build scratch is removed; failed build scratch
is retained for diagnosis and should be removed after recording the failure.
The current rollback package must remain in `local/packages/`. Do not move this
storage to `/tmp` or removable storage.

Installation preserves the package name, `/usr/bin/spotifast`, launcher/icon,
license, readme and Omarchy assets. It does not purge the package or write to user
configuration, state, caches or credential stores. Relaunch preserves HOME and
XDG location overrides. All production smoke tests use private dummy directories,
a private X server and a private DBus session. See [configuration compatibility](CONFIG-COMPATIBILITY.md).

A failed install or startup attempts to restore the matching previous package.
A failed graceful shutdown never force-kills the app. The journal is written
before package replacement; an interrupted transaction leaves its previous
package recorded for explicit `rollback`. Package rollback cannot reverse any
normal configuration updates or token refreshes performed by a real app launch.
Do not copy, export or inspect private grants/history to validate deployment.

## Explicit rebase agent playbook

Run `python3 -I .spotifast-mod/rebase.py COMMAND`:

1. `check` fetches public upstream HEAD into the object database and reports
   commits, paths and execution-control changes. It changes neither the recorded
   pin nor source. Recommend integration only for meaningful security, Spotify
   compatibility, playback, reliability, performance or relevant interface work.
   Documentation/formatting alone is insufficient. Deployment does not call it.
2. Only after an explicit `rebase <ref>` or `update <ref>` request, run
   `start <ref>`. It resolves the ref once to an immutable commit and stages a
   candidate under `scratch/rebase/`, preserving the working tree and installation.
3. Read `upstream.diff` and `execution-controls.diff`. Review Cargo manifests and
   lock changes, build scripts, toolchain, `.cargo`, workflows, packaging and agent
   policies. Fill `review.json` with the exact pin, reason and behavioral review.
   This record is an agent's review attestation, not a request for new permission.
4. Run `continue`. The ordered patches replay against the candidate. On conflict,
   compare the original patch, upstream change and staging source. Resolve only
   staging source, preserve type-to-filter, the green fixed indicator, execution
   controls and deployment separation. Do not blanket-select ours/theirs. Record
   each resolution in `resolved_patches`, then continue. Unmerged binary/delete
   conflicts require manual, intent-preserving edits. Patches are regenerated and
   replayed independently. An empty patch requires a `redundant_patches` entry
   documenting equivalent upstream behavior and verification before removal.
   The initial infrastructure patch cannot be removed.
5. A verified candidate remains staged for review. `continue --author-name NAME
   --author-email EMAIL` publishes one linear local commit with source, regenerated
   patches, submodule pin and review record. It does not build, push or install.
   Source must remain clean and unchanged since start. The first infrastructure
   patch is retained in series order, with later policy changes in their own patch.
6. `abort` discards a pre-publication candidate without changing source, pin or
   installation. If publication was interrupted, preserve `recovery.json` and
   inspect changes before restoring the recorded commit and submodule. Do not
   reset unrelated edits. Abort refuses to erase that recovery evidence.
7. Run maintenance tests, review the resulting linear commit, check Actions stays
   disabled, and push without rewriting published history. App execution and
   installation require their own explicit task after a future rebase.
