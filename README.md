# GoogleCloudPlatform_Utilities
Set of Python scripts for Google Cloud Platform.

Overview
--------
This repository contains small, focused Python utilities to help automate and
audit Google Cloud Platform projects.

Motivation
----------
Deploying GCP-based systems across multiple projects often requires repeating
the same setup steps: enabling APIs, creating service accounts and keys,
assigning IAM roles, configuring billing and quotas, and capturing quota
snapshots. Manually performing those steps across many projects is time
consuming, error-prone, and hard to track for auditing or compliance.

This project exists to make those tasks simple, repeatable, and auditable:

- **Configuration-driven automation:** Define desired setup and resources in
	YAML files (`gcp_components.yaml`, `gcp_config.yaml`) so the same
	procedures can be applied consistently across projects.
- **Safe dry-runs and verification:** `setup_gcp.py` supports preview modes
	so you can review changes before they are applied.
- **Comprehensive, logged reporting:** `gcp_geninfo_report.py` produces
	structured JSON and Markdown reports (with progressive partial writes)
	so each run leaves a clear audit trail of what was observed and applied.
- **Idempotent and repeatable:** The tooling focuses on repeatability and
	predictable outcomes so teams can standardize onboarding or project
	bootstrapping workflows.
- **Extensible and transparent:** YAML-driven items and modular report
	sections make it easy to add checks, new setup steps, or integrate into
	CI/CD pipelines.

The two primary tools are:

- `gcp_geninfo_report.py` — generate a structured project information report
	(JSON + optional Markdown) including enabled APIs, service accounts, IAM
	bindings, billing links and quota snapshots.
- `setup_gcp.py` — declarative setup automation driven by `gcp_components.yaml`
	to enable APIs, create service accounts, manage keys, and apply IAM
	bindings.

The project is intended for project bootstrap, team onboarding, and
lightweight audit/reporting tasks.

- Author: Cris Magalang (crismag)
- GitHub: https://github.com/crismag/GoogleCloudPlatform_Utilities
- Last Updated: 2026-03-23

Documentation
-------------
See the `docs/` folder for usage instructions and release notes:

- [gcp_geninfo_report.md](docs/gcp_geninfo_report.md)
- [setup_gcp.md](docs/setup_gcp.md)
- [release_notes.md](docs/release_notes.md)

Quickstart
----------
Run the report generator:

```bash
python gcp_geninfo_report.py --config gcp_config.yaml --debug-level 1
````
markdown
# GoogleCloudPlatform_Utilities

Utilities and automation scripts for Google Cloud Platform (GCP).

Keywords: GCP, Google Cloud, gcloud, automation, service accounts, IAM,
quota, reporting, billing, DevOps, onboarding, infrastructure, IaC, Python

Quickstart
----------
1. Review the example config files and copy them to create local configs:

```powershell
copy gcp_config.example.yaml gcp_config.yaml
copy gcp_components.example.yaml gcp_components.yaml
```

2. Generate a project report (safe, read-only):

```bash
python gcp_geninfo_report.py --config gcp_config.yaml --debug-level 1
```

3. Preview setup actions (dry-run) before applying changes:

```bash
python setup_gcp.py --dry-run --config gcp_config.yaml --components gcp_components.yaml
```

4. Run setup automation (will modify cloud resources):

```bash
python setup_gcp.py --config gcp_config.yaml --components gcp_components.yaml
```

Documentation
-------------
Full usage guides, examples, and release notes live in the `docs/` folder:

- [docs/gcp_geninfo_report.md](docs/gcp_geninfo_report.md)
- [docs/setup_gcp.md](docs/setup_gcp.md)
- [docs/release_notes.md](docs/release_notes.md)

Requirements
------------
- Python 3.8+ (3.11 recommended)
- Google Cloud SDK (`gcloud`) installed and authenticated
- Install Python deps:

```bash
pip install -r requirements.txt
```

Security & Sanitization
-----------------------
- Do not commit generated service account keys or sensitive files to source
	control. Add `credentials/` and any local environment files to `.gitignore`.
- Example config files are provided; replace placeholders before running.

Contributing & Support
----------------------
Feedback, suggestions, bug reports, and contributions are welcome. The
preferred ways to get in touch:

- Open an issue on this repository with details and reproduction steps.
- Submit a pull request with a clear description and tests/examples where
	applicable.

If you found this repository useful or have questions about usage, please
open an issue or a pull request — I'll respond and iterate quickly.


Acknowledgements
----------------
Inspired by common GCP automation and onboarding patterns; intended as a
small, practical toolkit rather than a full IaC framework.

````
