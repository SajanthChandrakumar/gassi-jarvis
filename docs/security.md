# Dependency security

Reviewed 2026-11-16. The failing GitHub audit was traced to the pinned
`certifi==2026.7.22`, `Pillow==12.2.0` and `chromadb==1.5.8` dependencies.
Certifi is now pinned to 2026.10.23 in both cloud and combined requirements;
Pillow is pinned to 13.0.0 in both device and combined requirements.

A clean installation also exposed VectorBT 1.1.0's use of a Plotly template
removed in Plotly 7. Plotly 6.9.0 is now pinned in both cloud and combined
requirements. The workflow
now also installs the complete development requirements on Python 3.13, checks
dependency consistency and JavaScript syntax, and runs the existing test suite.

ChromaDB has been removed from the runtime requirements and application
imports. At review time, neither the old pin (1.5.8) nor the latest published
release (1.5.9) had a listed fix for CVE-2026-45829, CVE-2026-45830,
CVE-2026-45831 and CVE-2026-45833:

- https://github.com/advisories/GHSA-f4j7-r4q5-qw2c
- https://github.com/advisories/GHSA-36p7-vc44-83pf
- https://github.com/advisories/GHSA-2wm9-hf6c-p5cr
- https://github.com/advisories/GHSA-xph7-9rjv-w5fr

Jarvis now stores personal memory in embedded SQLite and runs the same
MiniLM ONNX model locally for semantic search. Model downloads use a fixed
URL and pinned SHA-256, reject redirects and unsafe archive entries, and
enforce size limits. Memory text is never sent to the model host. Existing
Chroma data is imported read-only from an integrity-checked backup, with
facts and the completion marker committed together. See
[memory storage and migration](memory-storage.md) before a production rollout.

The dependency-audit GitHub workflow resolves and scans all three runtime
requirements sets, including transitive dependencies, on pushes, pull requests,
weekly, and manual runs. No vulnerability is ignored and audit failures are
not converted to success. All three updated runtime requirements sets pass
strict local audits with no known vulnerabilities. Every audit job uploads its
JSON audit report for 14 days, including when the audit fails. Upload errors
do not replace the original audit's exit status.

For a local scan in a separate environment:

```sh
python -m pip install pip-audit==2.10.1
python -m pip_audit --strict -r requirements-cloud.txt
```

Passing repository checks does not certify a running deployment or migrate a
production volume. Back up the memory directory and verify the migration on
a copy before updating a live instance.
