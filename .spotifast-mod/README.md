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

No Cargo, Rust compilation, build scripts, proc macros, mise, package installers,
upstream tests, fetched scripts, or downloaded executables are run. Do not trust
this workspace in an automatic task runner. Root `AGENTS.md` makes this boundary
explicit and overrides upstream build instructions. GitHub Actions is disabled
at the repository level; workflow files remain present as source. Updates do
not grant execution permission or alter that setting. The installed app is
trusted; that trust does not extend to new builds or dependencies.

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
| `apply` | Apply the series to a pristine root source, or do nothing if it already matches. Refuse other source changes. |
| `verify` | Reconstruct and compare source bytes, file types and executable modes; also check the pristine submodule and its detached pin. Does not change source or the developer index. |
| `update <ref>` | Fetch that explicit ref from the hardcoded public upstream URL, validate it and preflight the whole series before changing root source, submodule source/HEAD and `upstream.json`. Source must match the series and the staged source. |
| `test` | Run this directory's fixture tests, then verify the real source/submodule. No app tests or network. |

The update command intentionally leaves the developer's index unchanged. Stage
`lib/spotifast`, `upstream.json` and the updated root source, verify, then commit
them together. A replay failure identifies the failing patch and leaves source,
pin and index unchanged. Downloaded Git objects may remain after a failed update.
There is no automatic upstream pull or implicit reference refresh.

## Editing and committing

1. Edit root source. Do not edit the submodule.
2. Stage new source files so capture can distinguish intended additions from
   unexpected untracked files. All untracked source, including ignored files,
   is checked; keep build output outside the root (builds are not authorized).
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
