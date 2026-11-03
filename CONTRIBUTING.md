# Contributing to retvana

Thanks for helping. retvana is a model people may use to plan their retirement, so a change is only
done when the rules are written down and the checks prove the code follows them.

## The rules

1. **A behaviour change starts with a spec change.** The model's rules live in
   [.kiro/specs/engine-baseline/](.kiro/specs/engine-baseline/). Change the requirement (or add a new
   spec under `.kiro/specs/`) first, then the code, then the checks that prove it.
2. **Checks are never adjusted to fit the code.** If a check fails, the code is wrong or the spec is.
   Fix the code, or change the spec and then the check, in that order.
3. **A golden master is never regenerated to make a check pass.** `scripts/regression_golden.json` is
   written only by `scripts/make_regression_golden.py`. If `regression_check.py` fails, fix the code or
   update the spec. Regenerate the golden only for a deliberate, spec'd behaviour change or example plan
   change, and say which spec change justifies it in the pull request.
4. **`make verify` must pass** before a pull request is ready for review.
5. **No personal data**, anywhere: code, checks, examples, docs, issues, pull requests or commit
   messages. Use the example household, generic names ("Person 1", "Property 2") and round values.
   Never attach a real `plan.json` or a spreadsheet.

Hand-calculation checks read their inputs from `example_plan()` or a small plan built in the check, and
write out only the rule as plain arithmetic. Expected values never come from the function under test.

## Setup

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pre-commit install      # installs the pre-commit and pre-push hooks
make verify
```

The hooks run on every commit: gitleaks secret scanning, the forbidden-file check
(`scripts/forbidden_files.py`: no spreadsheets, notebooks, documents, archives, pickles or databases, no
unexpected binary files, no PNG metadata) and the commit email check. CI runs the same scans, plus
`make verify`, on every pull request, including pull requests from forks.

The gitleaks hook and the release gate use **gitleaks 8.30.1**. To run gitleaks outside pre-commit,
download version 8.30.1 from the [gitleaks releases](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1),
check it against the release's checksums file, put it on your `PATH`, and confirm with
`gitleaks version`.

## Commit email

Every commit's author and committer email must match `.github/allowed-emails.txt`, which allows only
GitHub noreply addresses. Commits with any other address fail the `commit-emails` check, and the pull
request cannot be merged.

1. In GitHub, open **Settings → Emails** and turn on **Keep my email addresses private**. Turning on
   **Block command line pushes that expose my email** as well is a good idea. With the first setting on,
   commits GitHub makes for you (web edits, squash merges) use your noreply address too.
2. The same page shows your noreply address, in the form `<id>+<username>@users.noreply.github.com`.
   Set it in your clone:

   ```bash
   git config user.email "<id>+<username>@users.noreply.github.com"
   ```

### If `commit-emails` fails on your pull request

Re-author your own commits with the noreply address, then update your branch:

```bash
git config user.email "<id>+<username>@users.noreply.github.com"
git rebase -r <base> --exec 'git commit --amend --no-edit --reset-author'
git push --force-with-lease
```

`<base>` is the commit your branch started from (for example `origin/main`, or `upstream/main` in a
fork). `--reset-author` sets both the author and the committer to your current identity. Check with
`git log --format='%h %ae %ce' <base>..HEAD` before you push.

The maintainer does not re-author contributor commits. A pull request with a commit that fails the check
waits until its author fixes it.

## Pull requests

- Keep each pull request to one change. The template asks whether a spec changed, whether
  `make verify` passed, and whether the golden was regenerated (and why).
- New checks are named `scripts/<area>_check.py` so `make verify` runs them. Checks are plain scripts
  that print PASS/FAIL lines and exit non-zero on failure.
- Dependencies are pinned exactly (`==`) in `pyproject.toml`; there are no `requirements*.txt` files. A
  new dependency needs a reason in the pull request.
- If you add or change an image, strip its metadata and look at it before you commit. Only
  `docs/images/*.png` may be binary.

## Maintainer notes

These apply to a maintainer clone, the clone a maintainer pushes to this repository from.

- **Set the maintainer flag** once per clone. It lives in the clone's own `.git/config` and is never
  pushed:

  ```bash
  git config --local retvana.maintainer true
  git config --type=bool --get retvana.maintainer    # prints true
  ```

  With the flag set, the pre-push hook runs the release gate on every push. Without it, the hook prints
  `release gate skipped: not a maintainer clone`. Clear it with
  `git config --local --unset retvana.maintainer`.
- **Install gitleaks 8.30.1** as above. The release gate fails if `gitleaks` is missing.
- **Do a de-identification review** of your own diff and commit messages before you push a change to
  docs, examples, specs or the example plan. Go through the Identifier_Checklist in the "De-identification
  review" section of [the open-source release design](.kiro/specs/open-source-release/design.md)
  category by category. The checklist names categories only; keep it that way and never add a real value
  to it, here or anywhere else.
- **Run the release gate** before pushing:

  ```bash
  .venv/bin/python scripts/release_gate.py
  ```

  It runs gitleaks over the working tree and the whole history, the forbidden-file check over the working
  tree and every blob in history, and the commit email check over every commit, and exits non-zero on
  any finding.
- **Push nothing to this repository until the release gate passes.** The pre-push hook blocks a push
  when it fails; do not bypass it with `--no-verify`.
- Releases are cut by pushing a `v*` tag. The release workflow runs the full CI scans first and creates
  the GitHub release from the matching [CHANGELOG.md](CHANGELOG.md) entry.
