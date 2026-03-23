# Google Cloud Setup Automation Guide

This document explains how to use `setup_gcp.py` as a reusable, config-driven
Google Cloud setup orchestrator.

## Purpose

`setup_gcp.py` automates common GCP setup operations in a repeatable and safe
way. It is intended for local setup, team onboarding, and project bootstrap.

The script is designed to be:

- **Declarative**: actions are defined in YAML, not hardcoded in Python
- **Portable**: reusable across projects and accounts
- **Idempotent**: safe to run multiple times
- **Extensible**: add actions by extending handler mapping in Python

## Architecture

The setup flow is split into two YAML files:

- `gcp_config.yaml` (runtime behavior)
- `gcp_components.yaml` (action orchestration)

The script performs two major phases:

1. **Runtime initialization**
   - load runtime config + defaults + CLI overrides
   - configure gcloud profile and auth
   - set gcloud project/region defaults
2. **Component execution**
   - execute each component action in order
   - skip already-configured resources when possible

## File Overview

- `setup_gcp.py`:
  - execution engine
  - command runner and error handling
  - action handlers
- `gcp_config.yaml`:
  - project and gcloud profile info
  - auth behavior
  - default settings for service account and credentials
  - components file path
- `gcp_components.yaml`:
  - ordered list of actionable setup components
- `gcp_config.example.yaml`, `gcp_components.example.yaml`:
  - templates for new environments/accounts

## Prerequisites

1. Install Google Cloud CLI (`gcloud`)
2. Install Python 3.11+
3. Install dependencies:

```bash
pip install -r requirements.txt
```

## First-Time Setup (New Environment)

1. Copy templates:

```bash
copy gcp_config.example.yaml gcp_config.yaml
copy gcp_components.example.yaml gcp_components.yaml
```

2. Edit `gcp_config.yaml` with your project values:

- `project.id`
- `project.name`
- `project.number`
- optional `gcloud.account`

3. Adjust `gcp_components.yaml` for required APIs/resources.

4. Preview everything without applying changes:

```bash
python setup_gcp.py --dry-run
```

5. Run actual setup:

```bash
python setup_gcp.py
```

## Runtime Config Reference (`gcp_config.yaml`)

### `project`

- `id` (required): GCP project ID
- `name` (optional): human-friendly label
- `number` (optional): project number

### `gcloud`

- `configuration_name`: named gcloud profile to create/activate
- `account`: preferred authenticated user account email
- `run_region`: default Cloud Run region
- `compute_region`: default Compute region
- `compute_zone`: default Compute zone

### `auth`

- `login_if_needed`: run `gcloud auth login` if no active account
- `create_application_default_credentials`: create local ADC if missing
- `set_quota_project_for_adc`: set ADC quota project

### `defaults`

These values are used by component actions unless overridden per component.

- `defaults.service_account`
  - `name`
  - `display_name`
  - `description`
- `defaults.credentials`
  - `key_file`, `key_path`
  - `overwrite_local_key`
  - `allow_new_key_creation_if_keys_exist`
  - `delete_existing_user_managed_keys_before_create`
  - `write_env_file`, `env_file`
  - `activate_service_account_for_gcloud`
  - `persist_google_application_credentials`
  - `persist_google_cloud_project`

### `components_config`

- `path`: path to orchestration config file (default `gcp_components.yaml`)

### `execution`

- `dry_run`: if true, print commands without applying remote changes

## Components Config Reference (`gcp_components.yaml`)

Each component item has this shape:

```yaml
- id: "unique-component-id"
  enabled: true
  action: "action_name"
  args:
    key: value
```

### Fields

- `id`: unique identifier used in logs
- `enabled`: if false, component is skipped
- `action`: handler to execute
- `args`: arguments for the action

### Supported Actions

- `enable_api`
- `ensure_service_account`
- `ensure_service_account_key`
- `ensure_project_iam_binding`
- `configure_local_credentials`

## Action Argument Reference

### `enable_api`

Required args:

- `service`: API service name (for example `run.googleapis.com`)

Behavior:

- checks enabled services first
- enables only when missing

### `ensure_service_account`

Supported args:

- `service_account_name` (or `name`)
- `display_name`
- `description`

Behavior:

- checks if service account exists
- creates only if missing

### `ensure_service_account_key`

Supported args:

- `service_account_name`
- `key_path`, `key_file`
- `overwrite_local_key`
- `allow_new_key_creation_if_keys_exist`
- `delete_existing_user_managed_keys_before_create`

Behavior:

- protects against accidental duplicate key creation
- supports key rotation behavior via explicit flags

### `ensure_project_iam_binding`

Supported args:

- `role` (required)
- `member` (required unless `service_account_name` is provided)
- `service_account_name` (helper for derived member)

Behavior:

- checks existing IAM policy
- applies binding only when missing

### `configure_local_credentials`

Supported args:

- `service_account_name`
- `key_path`, `key_file`
- `write_env_file`, `env_file`
- `persist_google_application_credentials`
- `persist_google_cloud_project`
- `activate_service_account_for_gcloud`

Behavior:

- writes `.env`-style credential file
- can optionally persist variables (Windows via `setx`)
- can optionally activate service account for gcloud

## Placeholder Templating in Component Args

String args support placeholders:

- `{project_id}`
- `{project_name}`
- `{project_number}`
- `{service_account_name}`
- `{service_account_email}`

Example:

```yaml
member: "serviceAccount:{service_account_email}"
```

## CLI Usage

Basic:

```bash
python setup_gcp.py
```

Dry run:

```bash
python setup_gcp.py --dry-run
```

Custom config paths:

```bash
python setup_gcp.py --config my_runtime.yaml --components-config my_components.yaml
```

Common overrides:

```bash
python setup_gcp.py \
  --project-id my-project-id \
  --gcloud-configuration-name my-profile \
  --run-region us-central1
```

## Idempotency and Re-Run Behavior

The script is safe to re-run and avoids duplicate operations where possible:

- skips already-enabled APIs
- skips existing service accounts
- skips existing IAM bindings
- skips duplicate key creation by default
- preserves local key unless overwrite is enabled

## Security Recommendations

- keep generated keys out of version control
- use least-privilege IAM roles
- rotate service-account keys regularly
- prefer keyless auth patterns when possible
- review and audit IAM bindings periodically

## Validation Checklist

After execution, verify:

```bash
gcloud config get-value project
gcloud services list --enabled --format="value(config.name)"
gcloud iam service-accounts list --format="value(email)"
gcloud projects get-iam-policy <PROJECT_ID> --format="json"
```

Also verify expected local files:

- `credentials/service-account-key.json` (if key creation is enabled)
- `.env.gcp` (if local credential configuration is enabled)

## Troubleshooting

### `project.id` missing

Ensure `project.id` is defined in `gcp_config.yaml` or use `--project-id`.

### Components config not found

Check `components_config.path` in `gcp_config.yaml`.

### Authentication prompts repeatedly

Set `gcloud.account` to your intended account and keep
`auth.login_if_needed: true`.

### Existing keys prevent new key creation

This is expected behavior for safety. Use one of these options in component
args when intentional:

- `allow_new_key_creation_if_keys_exist: true`
- `delete_existing_user_managed_keys_before_create: true`

## CI and Quality Gates

- Flake8 config: `.flake8` (max line length 90)
- CI workflow: `.github/workflows/ci.yml`
- CI checks:
  - `flake8 setup_gcp.py`
  - dry-run smoke test using example configs

## Extending the Script

To add a new component action:

1. Implement a new method in `setup_gcp.py`:
   - naming convention: `_execute_<action_name>`
2. Register it in `self.action_handlers`
3. Use the new action in `gcp_components.yaml`

This keeps orchestration declarative while allowing controlled Python
extensibility.
