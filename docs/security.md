# Dependency security

Reviewed 2026-11-16. The failing GitHub audit was traced to the pinned
`certifi==2026.7.22`, `Pillow==12.2.0` and `chromadb==1.5.8` dependencies.
Certifi is now pinned to 2026.10.23 in both cloud and combined requirements;
Pillow is pinned to 13.0.0 in both device and combined requirements. The
updated device requirements pass a strict audit with no known vulnerabilities.

A clean installation also exposed VectorBT 1.1.0's use of a Plotly template
removed in Plotly 7. Plotly 6.9.0 is now pinned in both cloud and combined
requirements, and all 509 tests pass with the resolved dependencies. The workflow
now also installs the complete development requirements on Python 3.13, checks
dependency consistency and JavaScript syntax, and runs the existing test suite.

ChromaDB 1.5.8 remains affected by CVE-2026-45829, CVE-2026-45830,
CVE-2026-45831 and CVE-2026-45833. The published latest release (1.5.9)
still has no listed fix for these advisories, so an upgrade alone cannot
resolve the remaining cloud/combined audit failures:

- https://github.com/advisories/GHSA-f4j7-r4q5-qw2c
- https://github.com/advisories/GHSA-36p7-vc44-83pf
- https://github.com/advisories/GHSA-2wm9-hf6c-p5cr
- https://github.com/advisories/GHSA-xph7-9rjv-w5fr

Jarvis explicitly selects Chroma's embedded Rust backend. Do not run
`chroma run` or expose Chroma's collection-management HTTP endpoints.
The checked Compose setup publishes only Jarvis on loopback and has no
Chroma server service. This mitigates the documented HTTP attack paths;
it does not patch the dependency or certify a live deployment.

The dependency-audit GitHub workflow resolves and scans all three runtime
requirements sets, including transitive dependencies, on pushes, pull requests,
weekly, and manual runs. It deliberately does not ignore the Chroma advisories:
the cloud/combined audit remains red until upstream fixes exist or Chroma is
replaced through a separately validated memory migration. No vulnerability is
ignored and audit failures are not converted to success. Every job uploads its
JSON audit report for 14 days, including when the audit fails. Upload errors
do not replace the original audit's exit status.

For a local scan in a separate environment:

```sh
python -m pip install pip-audit==2.10.1
python -m pip_audit --strict -r requirements-cloud.txt
```

Before changing Chroma versions, back up the memory directory and verify
compatibility on a copy. Never test migrations against the only live archive.
