# Release Notes

Packaging guidance for releasing the scripts and configuration:

- Include these files in the release:
  - `gcp_geninfo_report.py`
  - `setup_gcp.py`
  - `gcp_config.yaml` and `gcp_components.yaml`
  - `gcp_report_items.yaml` (optional)
  - `requirements.txt`
  - `docs/` folder

- Recommendations:
  - Pin versions in `requirements.txt` and verify in a clean environment.
  - Add a short `CHANGELOG.md` for user-visible changes.
  - Provide example `gcp_config.example.yaml` and `gcp_components.example.yaml` (already present).
