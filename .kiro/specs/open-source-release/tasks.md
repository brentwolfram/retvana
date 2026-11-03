# Implementation Plan: Open-source release (Spec A)

## Overview

The plan follows the design's Migration stages 0 to 6, in order. Stages 0 to 4 run in the Staging_Folder
(`tree/` is the future Public_Repo content, `tooling/` is the Migration_Tooling). Stage 5 copies `tree/`
into the Public_Repo, and stage 6 proves the published code and closes the Migration. New public
components come in before they are needed: `plan_io.py` in stage 3, before the App needs it, and the
scanners, Release_Gate and hook configuration in stage 4, before stage 4's scan and stage 5's commits.

Every stage ends with a "Run stage N checks" task. A stage passes only when the comparison check, the
Parity_Check and every staged check pass (Req 5.2–5.4). On a failure, fix the stage and run it again; the
next stage never starts on a failure.

Steps marked **(author)** are done by the author personally. An agent must not do them.

No task writes private data into the Public_Repo. Private paths are named only as "the Data_Dir", "the
Staging_Folder" and "the Original_Folder", and the full stage output stays in
`<Data_Dir>/migration/evidence/`.

## Tasks

- [x] 1. Stage 0: prepare
  - [x] 1.1 Create the Staging_Folder and its environment
    - Create the Staging_Folder outside the Public_Repo and outside the Original_Folder, with empty `tree/`
      and `tooling/` subfolders
    - Create a Python 3.13 venv in the Staging_Folder; install the Old_Package's dependencies and the
      spreadsheet tools the Parity_Check needs
    - _Requirements: 5.1, 5.5_
  - [x] 1.2 Move the old-key working plan out of the way
    - Move the existing old-key `plan.json` in the Data_Dir to `<Data_Dir>/migration/app_plan.old.json`
      before any Retvana_Package code runs; do not open or copy its contents anywhere else
    - _Requirements: 5.6, 5.9_
  - [x] 1.3 Export the Spreadsheet_Plan
    - Using the Old_Package, export its `default_plan()` once to
      `<Data_Dir>/migration/spreadsheet_plan.old.json`
    - _Requirements: 5.3_
  - [x] 1.4 Copy the Parity_Check into the Migration_Tooling
    - Copy the parity check, the spreadsheet golden master (unchanged, as `tooling/parity_golden.json`) and
      its generator from the Original_Folder into `tooling/`; never into `tree/`
    - _Requirements: 4.3, 5.3, 5.5_
  - [x] 1.5 Write `tooling/run_stage.py`
    - Takes the stage number and the Original_Folder path on the command line; runs that stage's checks
      (baseline checks at stage 0; comparison, Parity_Check and every staged check from stage 1)
    - Writes the full output to `<Data_Dir>/migration/evidence/stage-<N>.txt`
    - Builds the record line from counts, maximum differences and PASS/FAIL only, and exits non-zero
      without printing a line if any field would hold another kind of value
    - Exits non-zero if any check fails
    - _Requirements: 5.4, 5.8_
  - [x] 1.6 Run stage 0 checks and record the result in the Migration record
    - Pass criteria: the Old_Package's own checks pass, and the Parity_Check passes on the Old_Package
      with the Spreadsheet_Plan (the baseline for Req 5.2–5.3); no comparison yet
    - Append the record line printed by `run_stage.py 0` to the Migration record below
    - _Requirements: 5.4, 5.8_

- [x] 2. Stage 1: package rename only
  - [x] 2.1 Copy the allowlisted files into `tree/`
    - Copy every file on the design's Allowlist into `tree/` in the target layout (`src/retvana/`,
      `app.py`, `scripts/`, Docker files, Makefile, `.streamlit/config.toml`); leave out every excluded
      file
    - Rename the import from the Old_Package's name to `retvana`; make no other change
    - _Requirements: 1.1, 2.1, 2.2_
  - [x] 2.2 Write `tree/pyproject.toml` and install the staged package
    - Package `retvana` in the `src/` layout, `requires-python = ">=3.13,<3.14"`, runtime and `[dev]`
      dependencies pinned with `==` to today's versions plus `platformdirs` and `pre-commit`
    - Do not copy `requirements*.txt` into `tree/`
    - Remove the `sys.path.insert` lines from the staged checks
    - `pip install -e tree[dev]` in the staging venv
    - _Requirements: 1.2, 1.3, 1.5_
  - [x] 2.3 Write `tooling/compare_check.py`
    - Imports the Old_Package from the Original_Folder path given on the command line and `retvana` from
      the editable install, in one process
    - Runs both on both Migration_Plans and compares every projection column, the vector engine and the
      summaries; in this stage it requires identical results
    - _Requirements: 1.1, 1.6, 5.2_
  - [x] 2.4 Run stage 1 checks and record the result in the Migration record
    - Pass criteria: the comparison gives identical results on both Migration_Plans; the Parity_Check
      passes; every staged check in `tree/` passes
    - _Requirements: 5.2, 5.3, 5.4, 5.8_

- [x] 3. Stage 2: key, field and label rename
  - [x] 3.1 Write `tooling/key_mapping.py`
    - Maps old person keys, renamed plan fields, property names and option fields to retvana, and old
      column names to new; maps a whole old-key plan dict to a retvana plan dict
    - Covers every renamed field, since `Plan.from_dict` drops unknown keys silently
    - _Requirements: 5.3, 5.7_
  - [x] 3.2 Rename person keys and per-person names in `tree/src/retvana/`
    - Person and owner keys to `'P1'`/`'P2'` (Person 1 is the first per-person spreadsheet block)
    - Mnemonic columns to `age_P1`, `T_P1`, `W_P1`, `CPP_P1`, `D_P1` and the P2 forms; starting-position
      fields to `nonreg_p1`, `reg_p1`, `tfsa_p1`, …; local variables; `base_nonreg_p2`, `p1_shareholder`
    - Edit only the uses in the design's table, not by text substitution; spreadsheet column letters,
      `CPP2`, `Qc` and `ADc` stay as they are
    - `default_plan()` still holds its current data in this stage
    - _Requirements: 1.6, 3.3_
  - [x] 3.3 Rename property labels and option names, and add `column_label`
    - Properties "Property 1" to "Property 3" with empty descriptions; mortgage names follow; empty
      `Townhouse.areas` default
    - `option_grants`, `options_share_price`, `options_marginal_rate`, `engine.options_net_proceeds()`
    - Generic labels in `engine.COLUMNS` and summary keys; `column_label(key, plan)` substitutes the
      plan's names for the App and the export
    - _Requirements: 1.6, 3.4, 3.5_
  - [x] 3.4 Update the staged App, export and checks to the new names
    - `app.py`, `export.py` and every staged check use the new keys, fields and labels; the App and the
      export show names through `column_label`
    - _Requirements: 1.5, 3.3, 3.4, 3.5_
  - [x] 3.5 Switch the comparison and the Parity_Check to the mapping
    - `compare_check.py` runs the Old_Package on each old-key plan and `retvana` on the mapped plan, and
      compares through the column map within $0.01 for the projection and 1e-9 relative for the vector
      engine
    - The Parity_Check builds its plan from the Spreadsheet_Plan through `key_mapping.py` and compares
      with the unchanged spreadsheet golden master
    - _Requirements: 5.2, 5.3_
  - [x] 3.6 Run stage 2 checks and record the result in the Migration record
    - Pass criteria: the comparison passes within $0.01 and 1e-9 relative on both Migration_Plans; the
      Parity_Check passes through the mapping; every staged check passes
    - _Requirements: 5.2, 5.3, 5.4, 5.8_

- [x] 4. Stage 3: example plan, rebased checks, regression golden and plan loading
  - [x] 4.1 Replace `default_plan()` with `example_plan()`
    - Write the Example_Plan from the design's table in `config.py`, with round synthetic values and no
      value taken from the Private_Plan; set generic dataclass defaults; build `fresh_plan()` on it
    - _Requirements: 1.6, 3.1, 3.2_
  - [x] 4.2 Write `src/retvana/plan_io.py`
    - `data_dir()`, `LoadResult`, `load_saved_plan()`, `save_plan()`, `PlanFileUnreadable` as in the
      design: `RETVANA_DATA_DIR` if set and non-empty, else `platformdirs.user_data_dir('retvana',
      appauthor=False)`
    - Unreadable on read, decode, JSON, type or value errors, or person keys other than `P1`/`P2`
    - Save re-reads any existing file and raises `PlanFileUnreadable` without writing if it is
      unreadable; otherwise writes `plan.json.tmp` and `os.replace`s it, removing the temp file on error
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.7, 7.8_
  - [x] 4.3 Rebase the staged checks on the Example_Plan
    - Replace literal private figures with reads from `example_plan()` or a small plan built in the
      check; keep public-rule constants literal; select by generic keys and indexes
    - Re-derive any expected value that held only for the private data from the rule, never from the
      function under test; tune example values where a qualitative outcome depends on them, and say so in
      the check
    - _Requirements: 4.1, 4.2_
  - [x] 4.4 Write `examples/example_household.json` and `scripts/examples_check.py`
    - The file is `example_plan().to_json()`; the check compares the two
    - _Requirements: 8.7_
  - [x] 4.5 Write `scripts/make_regression_golden.py` and generate the Regression_Golden
    - The 12 cases from the design; every column stored, dollars to cents, other columns unrounded; sorted
      keys, one year per line; `example_plan_sha256` and tolerances recorded
    - Asserts every feature-coverage path in the design and writes nothing if any assertion fails
    - Generate `scripts/regression_golden.json`
    - _Requirements: 4.4, 4.5_
  - [x] 4.6 Write `scripts/regression_check.py`
    - Opens the golden read-only and writes no file; compares each case within the stored tolerances,
      reports the first differing cells per case, checks the column set both ways
    - Fails with the regeneration instruction when the Example_Plan hash differs
    - _Requirements: 4.4, 4.6_
  - [x] 4.7 Write `scripts/plan_io_check.py`
    - Temp directories and env overrides: env set, env empty, platformdirs default, missing file, valid
      file, unreadable file, wrong person keys, save creates the directory, save refuses over an
      unreadable file, atomic write leaves no temp file
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 7.9_
  - [x] 4.8 Wire plan loading into the App and the deployment files
    - App resolves `data_dir()` once per session; missing file starts from `fresh_plan()`; unreadable file
      starts from `fresh_plan()` with `st.warning` naming the path and error, and "Save as default"
      disabled with the reason as help text; save errors shown in the sidebar; download file name
      `retvana_plan.json`
    - Rewrite the Dockerfile (`python:3.13-slim` by digest, non-root `retvana` user, `pip install .`),
      `docker-compose.yml` (mount `${RETVANA_HOST_DATA_DIR:?…}` at `/data`, `RETVANA_DATA_DIR=/data`,
      read-only root, dropped capabilities, `127.0.0.1` binding) and the Makefile (`PYTHON ?=
      .venv/bin/python`, host data dir default, retvana names)
    - Update `deploy_check.py` and `smoke_test.py` for the new mount, env and names
    - _Requirements: 1.4, 7.4, 7.6, 7.7, 7.9_
  - [x] 4.9 Update the Verify_Runner and the Migration_Tooling inputs
    - `scripts/verify.py` runs every `scripts/*_check.py` in name order, then the smoke test; its pattern
      cannot match the golden generator or the Release_Gate
    - Confirm `compare_check.py` and the Parity_Check read only the Migration_Plans, never
      `default_plan()` code
    - _Requirements: 4.5, 4.7, 5.9_
  - [x] 4.10 Run stage 3 checks and record the result in the Migration record
    - Pass criteria: the comparison passes within $0.01 and 1e-9 relative on both Migration_Plans; the
      Parity_Check passes; every staged check, including `regression_check.py`, `plan_io_check.py` and the
      smoke test, passes
    - _Requirements: 5.2, 5.3, 5.4, 5.8_

- [x] 5. Stage 4: leak guards, text de-identification, docs and GitHub configuration
  - [x] 5.1 Write `scripts/forbidden_files.py` and `.binary-allow`
    - Standard library only; no private data; behaves the same in every clone
    - Modes `--files`, `--tree`, `--dir`, `--history` (every blob reachable from any ref, with its path)
    - Rules: listed extensions; non-UTF-8 or NUL files outside `.binary-allow` (`docs/images/*.png`
      only); PNGs with `tEXt`, `iTXt`, `zTXt` or `eXIf` chunks
    - Reports only `path: forbidden file (<rule>)` (or `commit:path: …`), never file content, writes
      nothing to disk, exits 1 on any finding
    - _Requirements: 3.7, 6.2, 6.3, 6.4_
  - [x] 5.2 Write `.gitleaks.toml`
    - Default gitleaks rules plus any repo-specific allow entries the regression golden needs
    - _Requirements: 6.1, 6.6_
  - [x] 5.3 Write `scripts/forbidden_files_check.py`
    - Temp repo: every forbidden extension, non-UTF-8 and NUL files, `.binary-allow` patterns, PNGs with
      and without each metadata chunk, the `--files`, `--tree`, `--dir` and `--history` modes (a forbidden
      file committed and then deleted is still reported), output never contains file content, exit codes
    - _Requirements: 6.2, 6.3, 6.4_
  - [x] 5.4 Write `scripts/check_commit_emails.py` and `.github/allowed-emails.txt`
    - The list holds exactly `*@users.noreply.github.com` and `noreply@github.com`
    - `fnmatch`, case-insensitive; modes `--pending` and `--all`; `--allowed PATH` for tests
    - Failures print `<hash>: author email not allowed` or `committer email not allowed`, never the
      email; missing or empty list exits 2 naming the path
    - _Requirements: 6.10, 6.11, 6.12_
  - [x] 5.5 Write `scripts/commit_email_check.py`
    - Temp repo with allowed and disallowed author and committer identities; output never holds the
      email; the committed list holds exactly the two patterns
    - _Requirements: 6.10, 6.11_
  - [x] 5.6 Write `scripts/release_gate.py`
    - Steps: `gitleaks git --log-opts=--all` and `gitleaks dir .`; `forbidden_files.py --tree --history`;
      `check_commit_emails.py --all`; one summary line per step
    - Missing `gitleaks` fails its step; any failure exits non-zero
    - `--pre-push` in a Contributor_Clone prints the skip notice and exits 0; in a Maintainer_Clone, and
      always when run by hand, it runs every step
    - _Requirements: 6.6, 6.7, 6.8, 6.9_
  - [x] 5.7 Write `scripts/release_gate_check.py`
    - Temp repo with a stub `gitleaks`: a stub gitleaks finding, a forbidden file in history and a bad
      email each exit non-zero; a missing `gitleaks` fails its step; `--pre-push` without the
      Maintainer_Flag skips with the notice; with the flag it runs every step
    - _Requirements: 6.6, 6.7, 6.8, 6.9_
  - [x] 5.8 Write `.pre-commit-config.yaml` and update `.gitignore`
    - Hooks as in the design: gitleaks (pinned rev), forbidden-files over staged files, commit-email,
      release-gate at pre-push; install types pre-commit and pre-push
    - `.gitignore` adds data directories, `*.xlsx`, `plan.json` and plan JSON outside `examples/`,
      `.venv/`, `.kiro/settings/` and `tasks.meta.json` in every spec directory
    - _Requirements: 6.1, 6.2, 6.5, 6.7, 6.12, 10.4_
  - [x] 5.9 Write `scripts/repo_check.py`
    - No `requirements*.txt`; every pyproject dependency pinned with `==`; `.gitignore` entries present;
      Example_Plan person keys exactly `P1`/`P2`; no tracked forbidden file types; required docs, steering
      files and GitHub files present
    - _Requirements: 1.2, 1.3, 3.3, 6.5, 8.4, 9.2, 9.3, 10.1, 10.4_
  - [x] 5.10 De-identify code text, App labels and export labels
    - Rewrite comments, docstrings, App labels, Excel export labels, expense items and segment rationales
      in `tree/` generically, with no city, district, building, employer or person names
    - _Requirements: 3.5, 3.6_
  - [x] 5.11 Write the project docs
    - `README.md`, `CONTRIBUTING.md` (including maintainer notes that point to the Identifier_Checklist
      in this spec's design without copying any value, and the contributor email and re-authoring
      guidance), `SECURITY.md`, `CODE_OF_CONDUCT.md` ("Report content" first, private
      vulnerability reporting as the private fallback), `CHANGELOG.md` (`0.1.0`) and
      `docs/assumptions.md`, as in the design; no email address other than the noreply patterns
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.8_
  - [x] 5.12 (author) Capture and review the README screenshot
    - Run the staged App on the Example_Plan, capture `docs/images/app-overview.png` by hand, strip its
      metadata and review it by eye
    - _Requirements: 8.1_
  - [x] 5.13 Write the steering files
    - `.kiro/steering/product.md`, `tech.md` and `structure.md` as in the design
    - _Requirements: 10.1_
  - [x] 5.14 Write the public baseline spec and `tooling/spec_marker_check.py`
    - Rewrite `requirements.md`, `design.md` and `tasks.md` under `tree/.kiro/specs/engine-baseline/` with a
      new spec id, new keys, fields and paths, figures restated against the Example_Plan or generically,
      the original spreadsheet named only generically, and the parity check described as a one-time
      Migration check; keep every rule and marker
    - `spec_marker_check.py` reads the private baseline spec from the Original_Folder and compares the
      count of each marker per requirement; it keeps no copy of the comparison
    - _Requirements: 10.2, 10.3, 10.5_
  - [x] 5.15 Write the CI workflows and GitHub templates
    - `ci.yml`: triggers push and pull_request to main, `workflow_dispatch`, `workflow_call`; `contents:
      read`; actions pinned by SHA; `persist-credentials: false`, full history; jobs `verify`, `gitleaks`
      (checksum-verified binary), `commit-emails`, `forbidden-files`, all on every trigger including
      Fork_PRs; scanning jobs check out the PR head and run the scanners from a base-commit checkout; no
      secrets; no `pull_request_target`
    - `release.yml`: on `v*` tags, calls `ci.yml`, then a `release` job with `contents: write` that needs
      all four jobs
    - `dependabot.yml` (pip, github-actions, docker, weekly, grouped); bug report and feature request
      forms; `config.yml`; `PULL_REQUEST_TEMPLATE.md` checklist
    - _Requirements: 6.1, 6.2, 6.12, 9.1, 9.2, 9.3_
  - [x] 5.16 Scan `tree/` until clean
    - Run `forbidden_files.py --dir tree` and `gitleaks dir tree`; fix every finding by removing or
      rewriting the file, never by loosening `.gitleaks.toml` or the forbidden-file rules; repeat until both
      report zero
    - _Requirements: 3.7, 6.4_
  - [x] 5.17 (author) De-identification_Review of the full `tree/`
    - Read every file in `tree/`, including the regression golden, the example JSON and the PNG, and go
      through the Identifier_Checklist in the design category by category
    - Rewrite any finding (or change the example value, regenerating the golden) and repeat the review
      until it finds nothing; record only "done", never a value
    - _Requirements: 2.3, 3.6, 6.13, 6.14, 6.15_
  - [x] 5.18 Run stage 4 checks and record the result in the Migration record
    - Pass criteria: the comparison passes within $0.01 and 1e-9 relative; the Parity_Check passes; every
      staged check passes; `spec_marker_check.py` passes; both scans of `tree/` report zero findings; the
      De-identification_Review in 5.17 is done
    - _Requirements: 3.7, 5.2, 5.3, 5.4, 5.8, 6.13, 10.5_

- [x] 6. Stage 5: publish
  - [x] 6.1 (author) Set the Maintainer_Flag in the Public_Repo clone
    - `git config --local retvana.maintainer true`
    - _Requirements: 6.7, 6.8_
  - [x] 6.2 (author) Set the GitHub account email settings
    - Turn on "Keep my email addresses private" and "Block command line pushes that expose my email";
      confirm the clone's commit email is a noreply address
    - _Requirements: 6.10, 6.11_
  - [x] 6.3 (author) Configure the GitHub repository settings
    - Turn on secret scanning and push protection, private vulnerability reporting, Dependabot alerts and
      security updates; set the default `GITHUB_TOKEN` permission to read-only; require approval before
      workflows run for outside contributors; add no repository or Dependabot secrets
    - _Requirements: 6.1, 8.5, 9.1_
  - [x] 6.4 Install the hooks in the Public_Repo clone
    - Install the pinned `gitleaks` binary named in CONTRIBUTING and run `pre-commit install` (pre-commit
      and pre-push)
    - _Requirements: 6.1, 6.2, 6.7, 6.12_
  - [x] 6.5 Copy `tree/` into the Public_Repo and commit on a `migration` branch
    - Create `migration` from the initial commit; copy `tree/` into the working tree without overwriting
      this spec's own folder; add the files in a few topical commits (package, checks, app and deploy,
      docs, GitHub config, specs); every commit passes the hooks; no Migration_Tooling enters the repo
    - _Requirements: 2.1, 2.4, 4.3, 5.5_
  - [x] 6.6 Run the Release_Gate and its dry run
    - Run `python scripts/release_gate.py` until every step passes
    - On a scratch branch, commit a forbidden file (for example an empty `.xlsx`) and confirm the gate and
      the pre-push hook fail; delete the scratch branch without pushing it
    - _Requirements: 3.7, 6.6, 6.7, 6.9_
  - [x] 6.7 (author) De-identification_Review of the full stage 5 diff
    - Before the first push, review `git diff <initial commit>..migration` and every commit message on
      the branch against the Identifier_Checklist, category by category
    - Any finding goes back to stage 4: fix it in `tree/`, re-run stage 4 and rebuild the branch; record
      only "done", never a value
    - _Requirements: 2.3, 3.6, 4.3, 6.13, 6.14_
  - [x] 6.8 (author) Push the branch, open the pull request and merge
    - Push `migration` (the pre-push hook runs the Release_Gate again), open the pull request, squash-merge
      to main, and confirm `verify`, `gitleaks`, `commit-emails` and `forbidden-files` pass on the CI run
      on main
    - On this first pull request the base (the initial commit) has no scanners, so the three scanning jobs
      cannot run on the pull request; `verify` runs there, and all four jobs are confirmed on the push to
      main, which scans with main's own scanners
    - _Requirements: 4.7, 6.2, 6.9, 9.1_
  - [x] 6.9 (author) Turn on the branch ruleset on main
    - Require a pull request (0 approvals); required checks `verify`, `gitleaks`, `commit-emails`,
      `forbidden-files` with the branch up to date; block force pushes and deletion; linear history;
      squash merge only; no bypass
    - Confirm with a test pull request that a failing check blocks the merge (the Fork_PR test is task 7.7)
    - _Requirements: 6.12, 9.4_
  - [x] 6.10 Run stage 5 checks and record the result in the Migration record
    - Pass criteria: the comparison passes within $0.01 and 1e-9 relative; the Parity_Check passes; every
      staged check passes; the Release_Gate passed; the De-identification_Review in 6.7 is done; the four
      CI jobs passed on the CI run on main after the merge
    - _Requirements: 5.2, 5.3, 5.4, 5.8, 6.13_

- [ ] 7. Stage 6: close
  - [ ] 7.1 Re-prove the published code
    - In the staging venv, replace the editable install of `tree/` with an editable install of the
      Public_Repo at the merged main; run the comparison and the Parity_Check against it
    - _Requirements: 1.6, 5.2, 5.3_
  - [ ] 7.2 Convert the author's plan
    - Convert `<Data_Dir>/migration/app_plan.old.json` through `key_mapping.py` and write it to
      `<Data_Dir>/plan.json` with `plan_io.save_plan`
    - _Requirements: 5.7_
  - [ ] 7.3 Confirm the App loads the converted plan
    - Start the App from the Public_Repo with the default Data_Dir and confirm it loads `plan.json` with no
      warning and "Save as default" enabled
    - _Requirements: 5.7, 7.2, 7.3_
  - [ ] 7.4 Run stage 6 checks and record the result in the Migration record
    - Pass criteria: the comparison and the Parity_Check pass against the published main; `make verify`
      passes in the Public_Repo with `RETVANA_DATA_DIR` pointing at an empty temp directory, so no
      Original_Folder or `migration/` file is used; the App loaded the converted plan
    - _Requirements: 5.2, 5.3, 5.4, 5.8, 5.9_
  - [ ] 7.5 Delete the Staging_Folder
    - Delete the Staging_Folder with its venv, `tree/` and `tooling/`, including the copied parity check
      and golden master
    - _Requirements: 5.5_
  - [ ] 7.6 (author) Decide on the Original_Folder and the migration data
    - Decide whether to archive the original spreadsheets outside any repository, delete the
      Original_Folder, and delete `<Data_Dir>/migration/`
    - _Requirements: 5.9_
  - [ ]* 7.7 (author) Confirm the CI jobs on the first Fork_PR
    - On the first pull request from a fork, approve its workflows and confirm `verify`, `gitleaks`,
      `commit-emails` and `forbidden-files` all run and report
    - _Requirements: 6.1, 6.2, 6.12, 9.1_

## Notes

- The Migration record lives in this file, so record lines written after the ruleset is on reach main
  through a pull request like any other change. The `run_stage.py` record-line guard is the control on
  their content.
- The two De-identification_Reviews (5.17 and 6.7) record only that they were done. The
  Identifier_Checklist lists categories, never values.
- Tasks 5.1 to 5.9 build the guards stage 4's scan and stage 5's commits depend on; they are written in
  `tree/` and published with the rest.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.5"] },
    { "id": 2, "tasks": ["1.6"] },
    { "id": 3, "tasks": ["2.1", "2.3"] },
    { "id": 4, "tasks": ["2.2"] },
    { "id": 5, "tasks": ["2.4"] },
    { "id": 6, "tasks": ["3.1", "3.2"] },
    { "id": 7, "tasks": ["3.3", "3.5"] },
    { "id": 8, "tasks": ["3.4"] },
    { "id": 9, "tasks": ["3.6"] },
    { "id": 10, "tasks": ["4.1", "4.2"] },
    { "id": 11, "tasks": ["4.3", "4.4", "4.5", "4.7"] },
    { "id": 12, "tasks": ["4.6", "4.8", "4.9"] },
    { "id": 13, "tasks": ["4.10"] },
    { "id": 14, "tasks": ["5.1", "5.2", "5.4", "5.10", "5.13", "5.14"] },
    { "id": 15, "tasks": ["5.3", "5.5", "5.6", "5.8", "5.11", "5.15"] },
    { "id": 16, "tasks": ["5.7", "5.9", "5.12"] },
    { "id": 17, "tasks": ["5.16"] },
    { "id": 18, "tasks": ["5.17"] },
    { "id": 19, "tasks": ["5.18"] },
    { "id": 20, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 21, "tasks": ["6.4"] },
    { "id": 22, "tasks": ["6.5"] },
    { "id": 23, "tasks": ["6.6"] },
    { "id": 24, "tasks": ["6.7"] },
    { "id": 25, "tasks": ["6.8"] },
    { "id": 26, "tasks": ["6.9"] },
    { "id": 27, "tasks": ["6.10"] },
    { "id": 28, "tasks": ["7.1", "7.2"] },
    { "id": 29, "tasks": ["7.3"] },
    { "id": 30, "tasks": ["7.4"] },
    { "id": 31, "tasks": ["7.5"] },
    { "id": 32, "tasks": ["7.6"] },
    { "id": 33, "tasks": ["7.7"] }
  ]
}
```

## Migration record

One line per stage run, appended by hand from the line `tooling/run_stage.py` prints. The line holds only
counts, maximum differences and PASS or FAIL, in the design's format:
`Stage N | PASS | projection cols compared … , max diff $… | vector max rel … | parity …/… cases PASS | staged checks …/… PASS`.

Stage 0 | PASS | comparison n/a (baseline) | parity 8/8 cases PASS | old checks 15/15 PASS
Stage 1 | PASS | projection cols compared 2 plans × 98 cols × 48 yrs, max diff $0.00 | vector max rel 0.0 | parity 8/8 cases PASS | staged checks 14/14 PASS
Stage 2 | PASS | projection cols compared 2 plans × 98 cols × 48 yrs, max diff $0.00 | vector max rel 0.0 | parity 8/8 cases PASS | staged checks 14/14 PASS
Stage 3 | PASS | projection cols compared 2 plans × 98 cols × 48 yrs, max diff $0.00 | vector max rel 0.0 | parity 8/8 cases PASS | staged checks 17/17 PASS
Stage 4 | PASS | projection cols compared 2 plans × 98 cols × 48 yrs, max diff $0.00 | vector max rel 0.0 | parity 8/8 cases PASS | staged checks 21/21 PASS
Stage 5 | PASS | projection cols compared 2 plans × 98 cols × 48 yrs, max diff $0.00 | vector max rel 0.0 | parity 8/8 cases PASS | staged checks 21/21 PASS
