# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub private vulnerability reporting: open the
**Security** tab of this repository and choose **Report a vulnerability**
([direct link](https://github.com/brentwolfram/retvana/security/advisories/new)).

Do not open a public issue, discussion or pull request for a vulnerability, and do not include real
financial data or a real plan file in a report. Use the example household to reproduce a problem.

The maintainer replies, and coordinates the fix and any advisory with you, through the private report.

## Supported versions

Only the latest release receives security fixes.

| Version | Supported |
|---|---|
| latest release | yes |
| older releases | no |

## Deployment model

retvana is a single-user app that runs on your own machine. It has **no login** and binds to
localhost by design: Streamlit listens on `localhost`, and the Docker container publishes its port on
`127.0.0.1` only. Do not expose it on a network or put it behind a public proxy; anyone who can reach
it can read and change the plan in your data directory.

The container runs as a non-root user with a read-only root filesystem and no capabilities. Plans are
stored only in your data directory, outside the repository.

Reports about exposing the app on a network against this guidance are out of scope.
