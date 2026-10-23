# Dependency security

Reviewed 2026-10-23. ChromaDB 1.5.8 is affected by CVE-2026-45829
and CVE-2026-45833. The advisories list no patched release:

- https://github.com/advisories/GHSA-f4j7-r4q5-qw2c
- https://github.com/advisories/GHSA-36p7-vc44-83pf

Jarvis explicitly selects Chroma's embedded Rust backend. Do not run
`chroma run` or expose Chroma's collection-management HTTP endpoints.
The checked Compose setup publishes only Jarvis on loopback and has no
Chroma server service. This mitigates the documented HTTP attack paths;
it does not patch the dependency or certify a live deployment.

The dependency-audit GitHub workflow resolves and scans all three runtime
requirements sets, including transitive dependencies, on pushes, pull requests,
weekly, and manual runs. It deliberately does not ignore the Chroma advisories:
an audit may remain red until upstream fixes exist. Workflow activation requires
pushing these files to GitHub with Actions enabled.

For a local scan in a separate environment:

```sh
python -m pip install pip-audit==2.10.1
python -m pip_audit --strict -r requirements-cloud.txt
```

Before changing Chroma versions, back up the memory directory and verify
compatibility on a copy. Never test migrations against the only live archive.
