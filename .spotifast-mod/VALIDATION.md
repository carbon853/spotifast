# Maintenance validation

This setup changes the root agent guide and adds maintenance infrastructure,
one approved upstream submodule, and a static capability audit. It makes no
application feature changes and produces no application build.

`python3 -I .spotifast-mod/tool.py test` passes 18 fixture tests and then verifies
that the root equals the selected upstream tree plus the ordered series, and that
the submodule remains pristine at the recorded revision.

Covered cases:

- Deterministic refresh/replay with multiple ordered patches.
- File additions/deletions, binary data, executable modes and internal symlinks.
- Shell metacharacters and spaces in filenames without shell interpretation.
- Unstaged additions, source drift, dirty apply/update, staged-only edits and
  unmerged developer indexes.
- Repeated apply preserves file modification times and the developer index.
- Conflicting upstream updates name the failing patch and preserve source,
  submodule, pin and index; successful explicit updates are replayed first.
- Reserved upstream/patch paths, traversal/control characters, escaping/chained/
  cyclic symlinks and writes through symlink parents are rejected.
- Hook/filter/textconv/external-diff/fsmonitor/custom-submodule-command sentinel
  configuration never executes during maintenance operations.
- Both embedded submodule repositories and normal `.git` gitfiles work.
- Pins available only in the approved submodule's object database are supported.

`fresh_check.py` independently fetches an exact pushed fork commit and the exact
approved upstream submodule SHA over credential-free HTTPS. It inspects every
path and mode before materializing raw blobs, compares copied maintenance code
against the reviewed local copy, then runs the maintenance suite and replay
verification. No source-defined filter or checkout hook runs. The fresh root
index must remain byte-for-byte unchanged. Only `lib/spotifast` is initialized.

GitHub Actions is disabled at the fork repository level and is checked before
push and at delivery. Upstream workflow source is preserved. Maintenance tooling
uses only system Python, stdlib and controlled Git subprocesses; test fixtures
never compile Rust, execute the app, or import upstream modules.

Replay/path errors are preflighted before mutation. Power loss, disk errors and
concurrent external writers during multi-file materialization are outside the
transactional guarantee; individual file replacement is atomic. See README for
conservative apply behavior and recovery. The audit's findings are static;
application exploit tests and complete transitive dependency review are outside
this validation pass.
