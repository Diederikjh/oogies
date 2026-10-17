# Target 1: race-safe export file accounting

Status: **approved for implementation on 17 October 2026**.
Prepared: 17 October 2026 (Africa/Johannesburg).
Baseline: `480c85c`. Estimated effort: 0.5-1 focused developer day, including tests.
Parent: [architecture refactoring targets](refactoring-targets.md).

## Tests are part of this change

Add the seven focused backend tests below in
[`tests/test_export_jobs.py`](../tests/test_export_jobs.py), alongside the
existing export tests. Write the regression first and demonstrate its failure
on the current implementation, then apply the accounting fix. These tests are
required work for target 1; they are not deferred to the broader testing refactor.
Names below are proposed names for the new tests, not tests already implemented.

1. **`test_accounting_survives_partial_rename_after_metadata_read`**
   Create a real partial file in a temporary export directory. A targeted hook
   obtains its real metadata, atomically renames it to `clip.mp4`, then returns
   that metadata. Current code tries to read the old path again and fails.
   Assert that the fixed accounting completes, other jobs remain counted, and a
   subsequent stable scan reports the final file's size exactly once. This is
   the primary deterministic red-to-green regression.
2. **`test_accounting_skips_disappearing_candidates_and_keeps_survivors`**
   Parameterize removal of the file itself and of its containing directory
   after enumeration but before metadata is obtained. Keep another known-size
   clip present. Assert that scanning succeeds and returns the survivor's size,
   rather than failing or returning zero for the entire store.
3. **`test_accounting_counts_matching_regular_files`**
   Use known-size final/partial MP4s, an unrelated file and a directory whose
   name matches `clip*.mp4`. Assert the exact sum of matching regular files and
   zero for an empty store. This protects the existing selection/type behavior.
4. **`test_accounting_preserves_unexpected_io_errors`**
   Parameterize `PermissionError` and a distinct unrelated `OSError` for a
   candidate metadata read. Assert that each error remains visible. Broadly
   swallowing errors or declaring unreadable storage empty must fail this test.
5. **`test_http_export_list_succeeds_during_finalization`**
   Use the real HTTP handler and a controlled synthetic capture. Coordinate
   `GET /api/exports` with atomic finalization through events. Assert HTTP 200,
   valid JSON with numeric `storage_used_bytes`, and the correct final size on
   the next stable response. This verifies the user-visible request that the
   accounting race can break, beyond testing a private method.
6. **`test_create_preserves_storage_limit_when_candidate_disappears`**
   Run the real job-creation path with a disappearing partial and a surviving
   completed clip. Set the storage limit so the survivor plus required
   finalization headroom exceeds capacity. Assert the existing storage-full
   rejection (409), rather than admitting a job because the whole scan was
   incorrectly treated as empty. No capture or extra reservation should start.
7. **`test_queue_continues_after_accounting_candidate_disappears`**
   Gate a synthetic capture and force a candidate disappearance during the
   export runner's actual storage check. Assert that the runner remains alive,
   the next queued job is captured and becomes ready, and the final reservation
   count returns to zero. Count acquire/release transitions to catch duplicate
   release as well as leaked slots. Drive the interleaving with events, not a
   lucky sleep.

For the direct accounting tests, construct `ExportJobs` with `start=False` so
the background thread cannot consume a fault intended for the test. Exercise
active threads only in the dedicated HTTP/queue cases, with hooks scoped to the
chosen candidate and operation. Keep actual temporary-file creation, rename,
removal and size measurements; replace neither `_used_bytes()` nor its result.

The existing FIFO/cancellation, storage-limit, download retention, expiry and
restart-recovery tests also remain required. The seven additions need no real
camera, SDK connection, FFmpeg invocation or browser. Existing CI discovers
them through its normal backend test command.

## Intended result

Listing exports and checking export storage should tolerate a clip disappearing
during normal capture, finalization or cleanup. A missing partial file must not
turn an otherwise healthy export-list request into an error or interrupt queue
storage checks. Accounting should continue to include other observable clip
files, and converge to the correct total after the filesystem is stable.

This is a small correction in the current accounting path. It does not require
a new storage abstraction, manifest schema, API or synchronization model.

## Evidence and cause

[`ExportJobs._used_bytes()`](../docker/hikvision-sdk/export_jobs.py) currently
enumerates `*/clip*.mp4`, calls `is_file()`, then independently calls `stat()` for
the size. The following interleaving is possible:

1. Accounting observes `clip.partial.mp4` as a regular file.
2. Capture finalization renames or removes that path.
3. Accounting calls `stat()` on the old path and raises `FileNotFoundError`.

The complete backend run recorded this in
`test_queue_bound_fifo_and_cancelled_waiter`, via `ExportJobs.list()` and
`_used_bytes()`. A subsequent run passed without code changes. Private evidence:
`.local/two-high-rollout-backend-tests.log` and
`.local/two-high-rollout-backend-rerun.log`.

The production [encoder](../docker/hikvision-sdk/export_encoder.py) publishes a
validated MP4 with `partial.replace(final)` and removes remaining partial files
in cleanup. This filesystem work happens outside the worker condition lock,
while accounting takes place under that lock. The current synthetic capture
fixture instead writes the final file and then unlinks the partial. Both can
invalidate an observed partial path; tests must cover the production rename as
well as removal, without depending on scheduler luck.

`_used_bytes()` is used by export listing, queue admission and the export runner's
storage check. A fix should live there so those callers share the same policy.

## Chosen behavior

- Keep the current directory and filename selection (`*/clip*.mp4`), including
  partial and final MP4 files. Retain filtering of non-regular entries.
- For each candidate, obtain one `stat()` result and use that same result for
  regular-file classification and size. Avoid an existence/type check followed
  by a second metadata read.
- Catch `FileNotFoundError` for that individual candidate and continue the scan.
  A parent directory disappearing is covered when its candidate's `stat()` fails.
- Continue counting other files when one vanishes. Do not return zero for the
  entire scan and do not suppress permission errors or unrelated I/O failures.
- Keep the result an observation of a changing directory, not an atomic quota
  snapshot. A rename during enumeration can affect this sample; once activity
  settles, the next scan must report the stable total accurately. Do not claim
  exact concurrent totals or strict quota guarantees from this change.
- Preserve existing queue admission, runner storage rechecks, file-size limits,
  two-file finalization headroom, downloads and retention behavior. Those checks
  remain the existing policy, not a proof that directory scans are transactional.

Use an explicit short loop in `_used_bytes()` with regular-file classification
from the returned mode. A separate helper is justified only if tests or another
existing caller benefit; no repository or filesystem interface is needed here.

## Alternatives considered

| Approach | Benefit | Cost / reason for choice |
| --- | --- | --- |
| Single metadata read and per-file missing-path handling | Small, directly addresses the observed race; straightforward deterministic tests | Selected. Retains best-effort accounting during concurrent filesystem changes. |
| Make encoder rename/cleanup take the shared application lock | Could serialize participating accounting and file changes | Broadens lock ownership and can delay unrelated frame work; does not cover external file disappearance. Leave lock redesign to target 5. |
| Maintain a transactional artifact-size ledger | Could support stronger reservation/accounting semantics | Requires ownership of capture growth, restart recovery, deletion and publication. Too much scope for this demonstrated failure; revisit only if strict accounting becomes a requirement. |

## Implementation sequence after review

1. **Add a deterministic reproduction before the fix.** Use a temporary export
   directory and a narrowly scoped metadata-read hook. After obtaining metadata
   for the chosen partial file, rename it to the final path before returning the
   observation. The existing separate size read should then fail. Other paths
   use real filesystem operations. Do not use sleeps or repeated random runs to
   induce the race, and do not mock `_used_bytes()` itself.
2. **Add the accounting policy tests.** Cover a file already gone when metadata
   is requested, surviving files, regular-file filtering, stable totals and
   unrelated I/O errors. Scope hooks to the test's candidate paths and restore
   them before fixture teardown.
3. **Change `_used_bytes()` only as described above.** Avoid modifying queue
   states, the encoder protocol, API responses or lock ownership. Use the
   existing production encoder's atomic finalization behavior as the reference.
4. **Exercise the actual export-list and queue paths.** Coordinate capture
   finalization with accounting through events/barriers. The capture may rename
   its file without acquiring the condition lock; the test must not wait for a
   job-state update that needs the lock currently held by the list request.
   Ensure test gates are released in cleanup even after assertion failure.
5. **Run the checks below and record results.** Document the behavior and any
   remaining accounting limitations in the export guide and progress log.

## Test acceptance rules

The metadata hook should demonstrate the actual check/read gap, not just assert
the new implementation's shape. Additional missing-path tests verify the
exception policy independently. An event-coordinated integration case covers
the caller and background-worker interaction. A browser test is not needed for
this backend-only change unless verification exposes an actual UI regression.
Every forced interleaving must assert its hook or event actually fired so a test
cannot pass simply because it missed the race. Bound all waits and release all
gates in cleanup. Assert exact totals after activity settles; concurrent scans
remain best-effort as described above.

## Checks and completion criteria

Run focused export tests first:

```sh
python3 -m unittest discover -s tests -p test_export_jobs.py -v
```

Then run the complete backend suite (currently 100 tests before additions):

```sh
python3 -m unittest discover -s tests -v
git diff --check
python3 tools/check_publication.py --history
```

If the existing host library overrides interfere with Python, prefix these
Python commands with `env -u LD_LIBRARY_PATH -u LD_PRELOAD`, as in earlier local
runs. No additional host dependencies, SDK tools, recorder login, real camera
footage or service restart are required. Use synthetic files and the existing
offline worker/encoder fixtures. Existing CI discovers added backend tests.

Completion requires the deterministic red-to-green reproduction, all seven new
tests (including their parameterized cases), existing export regressions,
passing backend/privacy/whitespace checks and updated
documentation. Report stable totals separately from concurrent-scan limitations.
The implementation should remain concentrated in `export_jobs.py` and focused
export tests; treat a need for new storage ownership or lock restructuring as a
reason to reassess the scope before continuing.

The owner reviewed this plan and authorized implementation after committing it.
