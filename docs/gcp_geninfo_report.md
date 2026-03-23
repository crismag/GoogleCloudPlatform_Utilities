# gcp_geninfo_report.py

Generates a structured Google Cloud project information report (JSON and optional Markdown).

Usage
-----

```bash
python gcp_geninfo_report.py --config gcp_config.yaml --output-json gcp_project_geninfo_report.json --output-md gcp_project_geninfo_report.md --debug-level 1
```

Features
--------
- Collects project metadata, enabled APIs, service accounts, IAM policy, billing info, and compute project info using `gcloud`.
- Supports REST-based quota snapshots via `gcp_report_items.yaml`.
- Writes partial JSON/Markdown outputs as sections are collected (useful for long runs).
- Configurable timeouts/retries via `gcp_config.yaml`.

Notes
-----
- The script requires the Google Cloud SDK (`gcloud`) installed and authenticated.
- On Windows the script resolves `gcloud.cmd` automatically.

Output
------
The script writes the following files by default:
- `gcp_project_geninfo_report.json`
- `gcp_project_geninfo_report.md`

See the example report output in the repository root.
