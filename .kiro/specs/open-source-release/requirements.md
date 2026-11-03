# Requirements Document

## Introduction

This spec (Spec A) publishes the retirement drawdown planner as **retvana**, an Apache-2.0 open-source
project. The planner models a Canadian two-person household under 2026 Ontario rules. It has a
projection engine, a vectorized Monte Carlo engine, a property sale model, a market-risk Monte Carlo, a
spending solver, an Excel export, a Streamlit app and Docker/Makefile deployment.

The code today lives in the author's original private folder, mixed with the author's personal plan, the
original spreadsheet and ad-hoc scripts. This spec moves only the essential files into the public repo,
renames the package, replaces all personal data with a synthetic example household, rebases the checks
on that household, and guards the public repo against personal data through its structure (an
allowlisted tree on a fresh root commit, `.gitignore` rules and forbidden file types), generic scanners
(gitleaks and the commit email check) and a manual de-identification review by the author.

The model's behaviour does not change. The move is a one-time Migration, done in a temporary staging
folder and proved stage by stage against the old package and the original spreadsheet's golden master.
Once the final stage passes, the original private folder is no longer needed and the author may delete
it. After that, the only private data that persists is the Data_Dir, and the public Regression_Golden is
the behaviour guard.

Out of scope:
- storage abstraction (multiple plans, schema versions, backups) and an onboarding questionnaire: Spec B;
- cloud storage: Spec C;
- any change to model rules, tax values or rates;
- git identity and git configuration, which the author handles, apart from the Maintainer_Flag.

## Glossary

- **Public_Repo:** the public GitHub repository for retvana.
- **Original_Folder:** the author's original private folder holding the old package, the private plan,
  the original spreadsheet and its parity check. It is used only as a source during the Migration and
  may be deleted after it.
- **Old_Package:** the engine package in the Original_Folder, under its old name.
- **Retvana_Package:** the Python package `retvana`, the renamed Old_Package.
- **App:** the Streamlit app (`app.py`) in the Public_Repo.
- **Example_Plan:** the plan returned by `example_plan()`: a synthetic two-person Ontario household with
  made-up names and round, plausible values.
- **Data_Dir:** the directory named by `RETVANA_DATA_DIR`, or else the platform user data directory for
  `retvana` from `platformdirs`. It is outside every repository and is the only long-lived private data.
- **Private_Plan:** the author's own plan, stored as `plan.json` in the Data_Dir in retvana keys.
- **Personal_Identifier:** any of the author's household names, birth years or ages tied to a person,
  property, street, building or area names, employer or stock-grant names, names of the original
  spreadsheet, a workbook or the Original_Folder, the author's email addresses or numeric GitHub account
  id, and any balance, price, mortgage or pension-estimate figure taken from the Private_Plan or the
  original spreadsheet. Generic public rates (tax brackets, OAS amounts, TFSA limit, RRIF rules) are not
  Personal_Identifiers.
- **Identifier_Checklist:** the written list of Personal_Identifier categories used by the
  De-identification_Review. It names categories only, never an actual personal value, and is kept in
  this spec's design.
- **De-identification_Review:** the author's manual, category-by-category review of files against the
  Identifier_Checklist.
- **Forbidden_File_Check:** `scripts/forbidden_files.py` in the Public_Repo, which rejects forbidden file
  types, unexpected binary files and image metadata. It uses no private data.
- **Binary_Allowlist:** the committed file `.binary-allow`, listing the path patterns allowed to be binary.
- **Leak_Scan:** the gitleaks secret scan together with the Forbidden_File_Check.
- **Allowed_Email_List:** the committed, public list of email patterns that commit author and committer
  emails must match.
- **Commit_Email_Check:** the check that every commit's author email and committer email match the
  Allowed_Email_List.
- **Release_Gate:** `scripts/release_gate.py` in the Public_Repo, which runs the full Leak_Scan and the
  Commit_Email_Check over a clone before a push.
- **Maintainer_Flag:** the local git setting `retvana.maintainer=true` in a clone's own git config.
- **Maintainer_Clone:** a clone of the Public_Repo with the Maintainer_Flag set.
- **Contributor_Clone:** a clone of the Public_Repo without the Maintainer_Flag.
- **Fork_PR:** a pull request to the Public_Repo opened from a branch of a fork rather than from a branch
  of the Public_Repo itself.
- **Allowlist:** the explicit list of files copied from the Original_Folder into the Public_Repo.
- **Regression_Golden:** a golden master of projection results generated from the Example_Plan by a script
  in the Public_Repo.
- **Migration:** the one-time, staged procedure that moves the code from the Original_Folder into the
  Public_Repo.
- **Staging_Folder:** the temporary folder outside the Public_Repo in which the Migration is done.
- **Migration_Tooling:** the one-time scripts and data used only during the Migration: the key and label
  mapping, the comparison script, the spreadsheet parity check with its golden master, and the
  marker-count comparison.
- **Migration_Plans:** the old-key plan files kept in `<Data_Dir>/migration/` during the Migration: the
  Spreadsheet_Plan and the earlier old-key export of the app-defaults plan.
- **Spreadsheet_Plan:** the frozen spreadsheet-settings plan in the old keys, exported once from the
  Old_Package.
- **Parity_Check:** the Migration_Tooling check comparing the engine with the original spreadsheet's
  golden master.
- **Migration_Record:** the "Migration record" section of this spec's `tasks.md`, holding each stage's
  result.
- **Verify_Runner:** `scripts/verify.py`, run by `make verify`, which runs every check and reports the
  overall result.
- **CI:** the GitHub Actions workflows of the Public_Repo.

## Requirements

### Requirement 1: Rename and packaging

**User Story:** As a maintainer, I want the engine published as an installable `retvana` package, so that
users and contributors install one codebase in a standard way.

#### Acceptance Criteria

1. THE Retvana_Package SHALL contain every module of the Old_Package under the import name `retvana`.
2. THE Public_Repo SHALL define the package, its Python version and its dependencies in `pyproject.toml`,
   with every runtime and development dependency pinned to an exact version.
3. THE Public_Repo SHALL contain no `requirements*.txt` files.
4. THE App, the Docker image, the compose service and the Makefile targets SHALL use the name `retvana`.
5. THE check scripts in the Public_Repo SHALL import the engine from the installed `retvana` package.
6. THE Retvana_Package SHALL keep every model rule, rate and default switch of the Old_Package unchanged;
   only names, labels and the default plan data change.

### Requirement 2: Allowlist migration

**User Story:** As the author, I want only reviewed, essential files copied into a fresh repo, so that no
personal file or history is published by accident.

#### Acceptance Criteria

1. THE Public_Repo SHALL receive only the files on the Allowlist: the engine package, `app.py`, the check
   scripts, the Verify_Runner, the smoke test, the Dockerfile, `docker-compose.yml`, the Makefile and
   `.streamlit/config.toml`.
2. THE Allowlist SHALL exclude spreadsheets, ad-hoc scripts, AppleScripts, scratch text files, the
   spreadsheet-derived golden master and its generator, the backlog, and report and screenshot scripts.
3. WHERE an excluded file is needed in the Public_Repo, THE file SHALL be added only after it has been
   reviewed and de-identified, and SHALL then be listed on the Allowlist.
4. THE Public_Repo SHALL contain no commits from the Original_Folder history; the migrated files SHALL
   enter as new commits on top of the existing initial commit.

### Requirement 3: De-identification of code and data

**User Story:** As the author, I want every personal detail replaced with synthetic or generic values, so
that the public code reveals nothing about my household.

#### Acceptance Criteria

1. THE Retvana_Package SHALL provide `example_plan()` in place of `default_plan()`, returning the
   Example_Plan.
2. THE Example_Plan SHALL use made-up person names, round birth years, round balances, round property
   values and round mortgage amounts, and SHALL exercise the same features as the spreadsheet settings
   (registered and TFSA accounts, employee stock options, property sales and a townhouse purchase).
3. THE Retvana_Package SHALL use the person keys `P1` and `P2` in place of the current initials.
4. THE Retvana_Package SHALL use generic property labels (for example "Property 1") in place of the current
   property names.
5. THE Retvana_Package and the App SHALL use the generic term "employee stock options" in place of any
   employer-specific term.
6. THE code comments, docstrings, App labels, Excel export labels and docs in the Public_Repo SHALL contain
   no Personal_Identifier.
7. WHEN the Leak_Scan runs over the Public_Repo working tree, THE Leak_Scan SHALL report zero findings.

### Requirement 4: Checks rebased on the example plan

**User Story:** As a maintainer, I want every check to run in the public repo without private data, so that
contributors can prove a change keeps the model's behaviour.

#### Acceptance Criteria

1. THE check scripts in the Public_Repo SHALL use only the Example_Plan or a plan built inside the check.
2. THE hand-calculation checks SHALL compute their expected values from constants of the Example_Plan
   written out as plain arithmetic, not by calling the function under test.
3. THE Parity_Check and the spreadsheet-derived golden master SHALL exist only in the Staging_Folder
   during the Migration, and SHALL never be committed to the Public_Repo.
4. THE Public_Repo SHALL provide a Regression_Golden and a generator script, and a check that compares the
   engine's Projections columns with the Regression_Golden within $0.01.
5. THE Regression_Golden SHALL be written only by its generator, a separate script that the
   Verify_Runner does not run.
6. THE regression check SHALL open the Regression_Golden read-only and SHALL write no file.
7. WHEN `make verify` runs in the Public_Repo, THE Verify_Runner SHALL run every check, including the
   regression check and the smoke test, and SHALL exit with status 0 only if all pass.

### Requirement 5: One-time migration

**User Story:** As the author, I want the move proved stage by stage against my old code and the original
spreadsheet, so that I can trust retvana with my own plan and then retire the original private folder.

#### Acceptance Criteria

1. THE Migration SHALL be done in a Staging_Folder outside the Public_Repo, in these stages in order:
   package rename, key and label rename, example plan with rebased checks, text de-identification, and
   publish.
2. WHEN a stage is complete, THE Migration_Tooling SHALL compare the Old_Package, run from the
   Original_Folder, with the staged Retvana_Package on the Migration_Plans, and SHALL pass only if every
   compared column matches within $0.01 for the projection and within a relative difference of 1e-9 for
   the vector engine.
3. WHEN a stage is complete, THE Parity_Check SHALL build its plan from the Spreadsheet_Plan through the
   key and label mapping, and SHALL pass against the unchanged spreadsheet golden master.
4. IF the comparison or the Parity_Check fails at a stage, THEN THE Migration SHALL stay at that stage
   until both pass.
5. THE Migration_Tooling SHALL live in the Staging_Folder only, SHALL never be committed to the
   Public_Repo, and SHALL be deleted with the Staging_Folder.
6. WHEN the Migration starts, THE Migration SHALL move the existing old-key `plan.json` from the Data_Dir
   into `<Data_Dir>/migration/` before any Retvana_Package code reads the Data_Dir.
7. WHEN the final stage passes, THE Migration SHALL convert the author's plan to retvana keys once and
   write the result to `<Data_Dir>/plan.json`.
8. WHEN a stage passes or fails, THE Migration SHALL record the stage's result in the Migration_Record
   using only counts, maximum differences and PASS or FAIL, with no personal values.
9. THE Retvana_Package, its checks and the App SHALL depend on no file in the Original_Folder or in
   `<Data_Dir>/migration/`.

### Requirement 6: Leak prevention

**User Story:** As the author, I want structural guards, generic scans before every commit and push and
in CI, and a manual review before the release, so that a personal detail cannot reach the public repo
unnoticed.

#### Acceptance Criteria

1. THE Public_Repo SHALL run gitleaks secret scanning as a pre-commit hook, and in CI on every push to main
   and every pull request to main, including Fork_PRs.
2. THE Public_Repo SHALL run the Forbidden_File_Check as a pre-commit hook over staged files in every
   clone, and in CI on every push and pull request to main including Fork_PRs, on manual dispatch and
   before each release.
3. IF the Forbidden_File_Check finds a forbidden file, THEN THE pre-commit hook SHALL block the commit and
   THE CI job SHALL fail, reporting the file path and the rule broken but not the file's content.
4. THE Forbidden_File_Check SHALL treat as forbidden every file with a spreadsheet, notebook, document,
   archive, pickle or database extension, every file that is not valid UTF-8 or contains a NUL byte
   unless its path matches the Binary_Allowlist, and every allowed PNG that carries text or EXIF metadata
   chunks.
5. THE `.gitignore` SHALL exclude data directories, `*.xlsx`, `plan.json` and any plan JSON outside
   `examples/`, `.venv/` and `.kiro/settings/`.
6. THE Release_Gate SHALL run gitleaks over the working tree and the entire git history, the
   Forbidden_File_Check over the working tree and every blob in the git history, and the
   Commit_Email_Check over every commit, and SHALL exit with a non-zero status on any finding or failure.
7. WHEN a push is started from a Maintainer_Clone, THE pre-push hook SHALL run the Release_Gate.
8. WHILE the pre-push hook runs in a Contributor_Clone, THE pre-push hook SHALL skip the Release_Gate and
   print a notice that the gate was skipped.
9. IF the Release_Gate exits with a non-zero status during a push, THEN THE pre-push hook SHALL block the
   push.
10. THE Allowed_Email_List SHALL be a committed file `.github/allowed-emails.txt` containing the patterns
    `*@users.noreply.github.com` and `noreply@github.com`.
11. IF a commit's author email or committer email does not match the Allowed_Email_List, THEN THE
    Commit_Email_Check SHALL fail, reporting the commit hash and which of the two emails failed, but not
    the email itself.
12. THE Commit_Email_Check SHALL run as a pre-commit hook in every clone, in the Release_Gate, and in CI
    on every push and pull request to main including Fork_PRs, on manual dispatch and before each
    release.
13. THE Migration SHALL include a De-identification_Review of the full staged tree at the text
    de-identification stage, and of the full publish diff before the first push to the Public_Repo,
    covering every category of the Identifier_Checklist.
14. IF a De-identification_Review finds a Personal_Identifier, THEN THE Migration SHALL stay at that stage
    until the text or example value is rewritten and the review is repeated.
15. THE Identifier_Checklist SHALL list Personal_Identifier categories only and SHALL contain no actual
    personal value.

### Requirement 7: Private plan loading

**User Story:** As a user, I want the app to load my plan from a private location outside the repo, so that
my data stays off GitHub.

#### Acceptance Criteria

1. WHEN the App starts AND `RETVANA_DATA_DIR` is set, THE App SHALL use that directory as the Data_Dir.
2. WHEN the App starts AND `RETVANA_DATA_DIR` is not set, THE App SHALL use the platform user data
   directory for `retvana` from `platformdirs` as the Data_Dir (on macOS,
   `~/Library/Application Support/retvana`).
3. WHEN the App starts AND `plan.json` exists in the Data_Dir, THE App SHALL load that plan.
4. WHEN the App starts AND `plan.json` does not exist in the Data_Dir, THE App SHALL start from the
   Example_Plan with the app defaults.
5. WHEN the user clicks "Save as default", THE App SHALL write the plan to `plan.json` in the Data_Dir,
   creating the Data_Dir if needed.
6. THE Docker compose service SHALL mount a host data directory into the container and set
   `RETVANA_DATA_DIR` to the mount point.
7. IF `plan.json` in the Data_Dir cannot be read or parsed, THEN THE App SHALL start from the Example_Plan
   with the app defaults and show a warning naming the file and the error.
8. IF `plan.json` in the Data_Dir cannot be read or parsed, THEN THE App SHALL NOT overwrite or delete
   that file.
9. WHILE `plan.json` in the Data_Dir cannot be read or parsed, THE App SHALL disable "Save as default" and
   show the reason next to the disabled control.
10. **(limitation)** Full schema validation and migration of saved plans are left to Spec B.

### Requirement 8: Documentation

**User Story:** As a new user or contributor, I want clear docs, so that I can run the planner, understand
its assumptions and contribute safely.

#### Acceptance Criteria

1. THE README SHALL state the purpose, show a screenshot captured by hand from the App running the
   Example_Plan with the PNG metadata removed, give a quick start for local and Docker use, state the tax
   year and province modelled, and carry a "not financial advice" disclaimer.
2. THE CONTRIBUTING guide SHALL state that a behaviour change starts with a spec change, that checks are
   never adjusted to fit the code, that a golden master is never regenerated to make a check pass (fix
   the code or update the spec instead), that `make verify` must pass, how to install the pre-commit
   hooks, and that commits use the contributor's GitHub noreply email address.
3. THE CONTRIBUTING guide SHALL include maintainer notes covering how to set the Maintainer_Flag, how to
   do a De-identification_Review against the Identifier_Checklist in this spec's design, how to run the
   Release_Gate, and that nothing is pushed to the Public_Repo until the Release_Gate passes.
4. THE Public_Repo SHALL include SECURITY, CODE_OF_CONDUCT and CHANGELOG files.
5. THE SECURITY file SHALL route security reports through GitHub private vulnerability reporting, THE
   CODE_OF_CONDUCT file SHALL route conduct reports first to GitHub's "Report content" feature and
   then to GitHub private vulnerability reporting as the private route to the maintainer, and neither
   file SHALL contain an email address.
6. THE `docs/` directory SHALL describe the model's assumptions, including the rules marked (inherited) and
   (simplification) in the engine baseline spec.
7. THE Public_Repo SHALL include `examples/example_household.json`, equal to `example_plan()` serialized
   with `Plan.to_json`.
8. THE CONTRIBUTING guide SHALL explain how a contributor turns on GitHub's "Keep my email addresses
   private" setting and how the contributor re-authors existing commits with the noreply address when
   the Commit_Email_Check fails on a pull request, and SHALL state that the maintainer does not
   re-author contributor commits.

### Requirement 9: GitHub configuration

**User Story:** As a maintainer, I want CI, templates and branch protection, so that every change to main is
checked.

#### Acceptance Criteria

1. THE CI SHALL run `make verify`, gitleaks, the Forbidden_File_Check and the Commit_Email_Check on every
   push and pull request to main, including Fork_PRs, on manual dispatch and before each release.
2. THE Public_Repo SHALL include issue templates (bug report, feature request) and a pull request template
   that asks whether a spec was changed and whether `make verify` passed.
3. THE Public_Repo SHALL include a Dependabot configuration for pip, GitHub Actions and Docker
   dependencies.
4. THE main branch SHALL be protected so that a merge requires the CI jobs to pass.

### Requirement 10: Kiro steering and public baseline spec

**User Story:** As a contributor using Kiro, I want steering files and a public baseline spec, so that the
model's rules are documented as a contract without personal data.

#### Acceptance Criteria

1. THE Public_Repo SHALL include `.kiro/steering/product.md`, `tech.md` and `structure.md`.
2. THE Public_Repo SHALL include a de-identified rewrite of the engine baseline spec under
   `.kiro/specs/engine-baseline/`, describing the same rules against the Example_Plan.
3. THE public baseline spec SHALL keep every rule and every (inherited), (simplification) and (limitation)
   marker of the private baseline spec, and SHALL refer to the original spreadsheet only generically.
4. THE `.gitignore` SHALL exclude `tasks.meta.json` in every spec directory.
5. WHEN the public baseline spec is written during the Migration, THE Migration_Tooling SHALL compare the
   count of each marker per requirement in the private and public baseline specs once, and SHALL pass only
   if every count is equal.
