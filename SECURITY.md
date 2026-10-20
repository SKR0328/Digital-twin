# Security and deployment scope

This is a local research application. It binds to loopback by default and has
no user authentication. Do not expose it directly to the internet or enter
identifiable patient information. The database inspection endpoints are intended
for the local developer.

Only install model artifacts from a source you trust. Joblib uses Python pickle
and loading a malicious artifact can execute code. Checksums detect accidental
changes; a checksum supplied by an attacker does not make an artifact safe.

Keep `.env`, credentials, datasets, local databases, logs and backups out of Git.
The export script uses an explicit allowlist; `.gitignore` alone does not filter
manual browser uploads. Third-party data has separate terms from the code.

Public hosting would require authentication, access control, upload hardening,
deployment-specific secret management and review of the data exposed by each
endpoint. This repository does not claim clinical, HIPAA or DPDP compliance.

For a suspected vulnerability, avoid publishing patient data, credentials or
exploit details in a public issue. Contact the repository maintainer through
their stated private contact channel.
