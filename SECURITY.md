# APLSAI HOME Security Policy

## Beta V1 release gates

Before onboarding real clients or uploading real documents:

- keep production credentials only in environment variables or secret stores;
- do not commit passwords, database URLs, access tokens or private keys;
- run the Security Baseline successfully on the release commit;
- use private document storage and allow only explicitly trusted storage hosts;
- verify backup and restore for the production database;
- keep web service, database and document storage in the intended EU region;
- verify production deploy commit and execute a production smoke test;
- review repository visibility before storing proprietary or operationally sensitive implementation details.

## Access principles

- least privilege by role;
- Partner access only to explicitly assigned practices;
- account deactivation must invalidate subsequent authenticated requests;
- document URLs must never be exposed to Partner lists before authorization;
- denied sensitive accesses should be auditable.

## Incident rule

If a credential is ever committed, removing it from the latest file is not sufficient. Revoke/rotate the credential immediately and review repository history and access logs.
