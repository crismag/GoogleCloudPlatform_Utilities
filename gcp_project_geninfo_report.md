# GCP Project Configuration Report (Example)

This file is an example output produced by `gcp_geninfo_report.py`. It is
included to show the structure of the generated JSON and Markdown reports.

Key fields

Generated (UTC): 2026-01-01T00:00:00+00:00
Project ID: your-project-id
Runtime Config (example): gcp_config.yaml
Components Config (example): gcp_components.yaml

Summary

- Enabled APIs: 30
- Service Accounts: 3
Enabled APIs: 3 (example)
Service Accounts: 1 (example)

Notes

- Some sections may be empty if the authenticated account lacks permissions.
- Billing details may require billing-specific IAM permissions.

Errors (example):

The billing section failed in the example run due to missing `beta` components
or insufficient local permissions when invoking the `gcloud beta` subcommand.

Example error message (redacted):

```
ERROR: (gcloud) insufficient permissions to perform this action.
```
