#!/usr/bin/env python3
"""Generate a structured Google Cloud project information report.

Author: Cris Magalang (crismag)
GitHub: https://github.com/crismag/GoogleCloudPlatform_Utilities
Last Updated: 2026-03-23

Purpose
-------
This script collects retrievable GCP project information using the `gcloud`
CLI and writes a structured report to JSON, with an optional Markdown summary.

The report includes:
- project metadata and runtime context
- enabled APIs
- service accounts
- IAM policy bindings summary
- billing project linkage (when retrievable)
- comparison between configured components and actual cloud state

Usage
-----
- Default files:
    python gcp_geninfo_report.py
- Override runtime config:
    python gcp_geninfo_report.py --config custom_runtime.yaml
- Override project ID directly:
    python gcp_geninfo_report.py --project-id my-project-id
- Custom output paths:
    python gcp_geninfo_report.py --output-json report.json --output-md report.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import shutil
import time

import yaml
import urllib.request
import urllib.parse

# Module-level defaults and constants
DEFAULT_SUBPROCESS_TIMEOUT = 30
DEFAULT_SUBPROCESS_RETRIES = 1
DEFAULT_REPORT_ITEMS_FILENAME = "gcp_report_items.yaml"
SERVICEUSAGE_BASE_URL = "https://serviceusage.googleapis.com/v1"
REPORT_VERSION = "1.0"

# Built-in report command templates. These are the default CLI calls used by
# the reporter; templates may contain `{project_id}` which will be formatted at
# runtime. Users who want to customize these calls can override them by adding
# equivalent sections to `gcp_report_items.yaml`.
DEFAULT_BUILTIN_REPORT_COMMANDS: Dict[str, List[str]] = {
    "project_description": [
        "gcloud",
        "projects",
        "describe",
        "{project_id}",
        "--format=json",
    ],
    "gcloud_config": ["gcloud", "config", "list", "--format=json"],
    "gcloud_auth_accounts": ["gcloud", "auth", "list", "--format=json"],
    "enabled_apis": [
        "gcloud",
        "services",
        "list",
        "--enabled",
        "--project",
        "{project_id}",
        "--format=json",
    ],
    "service_accounts": [
        "gcloud",
        "iam",
        "service-accounts",
        "list",
        "--project",
        "{project_id}",
        "--format=json",
    ],
    "iam_policy": [
        "gcloud",
        "projects",
        "get-iam-policy",
        "{project_id}",
        "--format=json",
    ],
    "billing": [
        "gcloud",
        "beta",
        "billing",
        "projects",
        "describe",
        "{project_id}",
        "--format=json",
    ],
    "compute_project_info": [
        "gcloud",
        "compute",
        "project-info",
        "describe",
        "--project",
        "{project_id}",
        "--format=json",
    ],
    "active_configurations": [
        "gcloud",
        "config",
        "configurations",
        "list",
        "--filter=is_active:true",
    ],
}

DEFAULT_RUNTIME_CONFIG: Dict[str, Any] = {
    "project": {"id": "", "name": "", "number": ""},
    "components_config": {"path": "gcp_components.yaml"},
}


def deep_merge_dictionaries(
    base_dictionary: Dict[str, Any],
    override_dictionary: Dict[str, Any],
) -> Dict[str, Any]:
    """Recursively merge dictionaries and return merged output."""
    merged_dictionary = dict(base_dictionary)
    for key, override_value in override_dictionary.items():
        base_value = merged_dictionary.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            merged_dictionary[key] = deep_merge_dictionaries(base_value, override_value)
        else:
            merged_dictionary[key] = override_value
    return merged_dictionary


class GCloudProjectInfoReporter:
    """Collect GCP project information and generate report artifacts."""

    def __init__(
        self,
        runtime_config_path: str,
        components_config_override: Optional[str],
        project_id_override: Optional[str],
        debug_level: int = 0,
    ) -> None:
        """Initialize reporter from runtime config and optional overrides."""
        self.runtime_config_path = runtime_config_path
        self.runtime_config_directory = Path(runtime_config_path).resolve().parent

        self.runtime_configuration = self._load_runtime_configuration()
        if project_id_override:
            self.runtime_configuration.setdefault("project", {})[
                "id"
            ] = project_id_override

        if components_config_override:
            self.runtime_configuration.setdefault("components_config", {})[
                "path"
            ] = components_config_override

        self.project_id = (
            self.runtime_configuration.get("project", {}).get("id", "").strip()
        )
        if not self.project_id:
            raise ValueError("Missing project.id in runtime config or --project-id")

        self.components_configuration = self._load_components_configuration()
        # runtime behavior
        self.debug_level = int(debug_level or 0)
        # gcloud executable resolution for Windows support
        self.gcloud_executable = self._resolve_gcloud_executable()
        # subprocess defaults
        self.subprocess_timeout = int(
            self.runtime_configuration.get("execution", {}).get(
                "timeout", DEFAULT_SUBPROCESS_TIMEOUT
            )
        )
        self.subprocess_retries = int(
            self.runtime_configuration.get("execution", {}).get(
                "retries", DEFAULT_SUBPROCESS_RETRIES
            )
        )
        # Optional output paths (set by caller/main) to enable progressive writes
        self.output_json_path: Optional[Path] = None
        self.output_markdown_path: Optional[Path] = None
        self.generate_markdown: bool = True

    def _resolve_gcloud_executable(self) -> str:
        if shutil.which("gcloud.cmd"):
            return shutil.which("gcloud.cmd")
        if shutil.which("gcloud"):
            return shutil.which("gcloud")
        return "gcloud"

    def _status(self, message: str, level: int = 1) -> None:
        """Print a timestamped status message when `debug_level` is high enough.

        Use `level` to control verbosity; higher level requires higher
        `debug_level` to be displayed.
        """
        try:
            if int(self.debug_level or 0) >= int(level or 0):
                ts = datetime.now(timezone.utc).isoformat()
                print(f"[{ts}] {message}")
        except Exception:
            # Never raise from logging helper
            pass

    def check_prerequisites(self) -> bool:
        """Verify `gcloud` CLI is available and responding on PATH.

        Returns True when a basic `gcloud --version` succeeds, False otherwise.
        """
        try:
            result = subprocess.run(
                [self.gcloud_executable, "--version"], capture_output=True, text=True
            )
            if result.returncode != 0:
                print("✗ gcloud CLI unavailable or failing; install and authenticate.")
                return False
            return True
        except FileNotFoundError:
            print("✗ gcloud CLI not found on PATH; install from:")
            print("https://cloud.google.com/sdk/docs/install-gcloud-cli")
            return False

    def _load_runtime_configuration(self) -> Dict[str, Any]:
        """Load runtime YAML config from path and merge with defaults.

        Returns the merged runtime configuration dictionary. The file at
        `self.runtime_config_path` is loaded if present. Values are merged
        with `DEFAULT_RUNTIME_CONFIG` so callers can rely on expected keys.
        """
        config_path = Path(self.runtime_config_path)
        runtime_data: Dict[str, Any] = {}

        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as config_file:
                loaded_data = yaml.safe_load(config_file)
                runtime_data = loaded_data if isinstance(loaded_data, dict) else {}

        return deep_merge_dictionaries(DEFAULT_RUNTIME_CONFIG, runtime_data)

    def _load_components_configuration(self) -> Dict[str, Any]:
        """Load components orchestration configuration if available.

        This resolves a relative path (relative to the runtime config
        directory) and returns a dictionary with a `_path` field pointing to
        the file location. If the components file is missing a `_missing`
        key is added to indicate the missing path.
        """
        relative_path = self.runtime_configuration.get("components_config", {}).get(
            "path",
            "gcp_components.yaml",
        )
        components_path = self._resolve_path(relative_path)

        if not components_path.exists():
            return {"components": [], "_missing": str(components_path)}

        with open(components_path, "r", encoding="utf-8") as components_file:
            loaded_data = yaml.safe_load(components_file)
            components_data = loaded_data if isinstance(loaded_data, dict) else {}

        components_data["_path"] = str(components_path)
        return components_data

    def _load_report_items(self) -> Dict[str, Any]:
        """Load report items configuration (gcp_report_items.yaml) if present."""
        """Load report items configuration (gcp_report_items.yaml) if present.

        Returns the parsed YAML mapping or an empty dict when the file is not
        present. The file is resolved relative to the runtime configuration
        directory.
        """
        candidate = self._resolve_path(DEFAULT_REPORT_ITEMS_FILENAME)
        if not candidate.exists():
            return {}
        with open(candidate, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            return loaded if isinstance(loaded, dict) else {}

    # --- Subprocess helper -------------------------------------------------
    def _invoke_subprocess_once(
        self, cmd: List[str]
    ) -> Tuple[Optional[subprocess.CompletedProcess], Optional[str]]:
        """Run a single subprocess invocation and return (completed, error).

        This helper centralizes the single-call subprocess.run invocation so
        the retry loop in callers can remain simple. Returns the
        CompletedProcess on success, or (None, error_message) on timeout or
        other exceptions.
        """
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.subprocess_timeout,
            )
            return completed, None
        except subprocess.TimeoutExpired:
            return None, "timeout"
        except FileNotFoundError as fnf:
            return None, str(fnf)
        except Exception as exc:  # pragma: no cover - environment/runtime
            return None, str(exc)

    # --- Report item handlers ----------------------------------------------
    def _handle_compute_region_quotas(
        self,
        name: str,
        spec: Dict[str, Any],
        report_sections: Dict[str, Any],
        retrieval_errors: Dict[str, Any],
    ) -> None:
        regions = spec.get("regions")
        if not regions:
            regions_list, err = self._run_gcloud_json(
                ["gcloud", "compute", "regions", "list", "--format=json"]
            )
            if err:
                retrieval_errors[name] = err
                return
            if not isinstance(regions_list, list):
                retrieval_errors[name] = "unexpected regions list format"
                return
            regions = [
                r.get("name")
                for r in regions_list
                if isinstance(r, dict) and r.get("name")
            ]

        region_results: Dict[str, Any] = {}
        command_template = spec.get("command", [])
        for region in regions:
            command_for_region = [
                str(arg).format(project_id=self.project_id, region=region)
                for arg in command_template
            ]
            data, err = self._run_gcloud_json(command_for_region)
            if err:
                retrieval_errors[f"{name}:{region}"] = err
                continue
            region_results[region] = (
                data.get("quotas")
                if isinstance(data, dict) and "quotas" in data
                else data
            )

        report_sections[name] = {"regions": region_results}

    def _handle_rest_report_item(
        self,
        name: str,
        spec: Dict[str, Any],
        report_sections: Dict[str, Any],
        retrieval_errors: Dict[str, Any],
    ) -> None:
        self._status(f"Preparing REST snapshot for: {name}", level=1)
        token, err = self._get_access_token_for_rest()
        if err or not token:
            retrieval_errors[name] = err or "failed to obtain access token"
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        mode = spec.get("mode", "none")
        if mode == "none":
            retrieval_errors[name] = "REST snapshots disabled via config (mode: none)"
            return

        if mode == "single":
            service_name = spec.get("service_name") or spec.get("service", {}).get(
                "service_name"
            )
            if not service_name:
                retrieval_errors[name] = "mode=single but no service_name provided"
                return
            self._rest_snapshot_single(
                name,
                service_name,
                headers,
                report_sections,
                retrieval_errors,
            )
            return

        if mode == "services":
            self._rest_snapshot_services(name, headers, report_sections, retrieval_errors)
            return

    def _handle_generic_report_item(
        self,
        name: str,
        spec: Dict[str, Any],
        report_sections: Dict[str, Any],
        retrieval_errors: Dict[str, Any],
    ) -> None:
        fmt_map = {"project_id": self.project_id}
        command_template = spec.get("command", [])
        cmd = [str(a).format_map(fmt_map) for a in command_template]
        if any("--format=json" in str(a) for a in cmd):
            data, err = self._run_gcloud_json(cmd)
            if err:
                retrieval_errors[name] = err
                return
            report_sections[name] = {
                "count": len(data) if isinstance(data, list) else 0,
                "items": data if isinstance(data, list) else data,
            }
            return
        text, err = self._run_gcloud_text(cmd)
        if err:
            retrieval_errors[name] = err
            return
        report_sections[name] = text

    # --- REST helpers ----------------------------------------------------
    def _rest_get_json(
        self, url: str, headers: Dict[str, str]
    ) -> Tuple[Optional[Any], Optional[str]]:
        request_obj = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(
                request_obj, timeout=self.subprocess_timeout
            ) as resp:
                body = resp.read().decode("utf-8")
                try:
                    return json.loads(body), None
                except json.JSONDecodeError as jde:
                    return None, f"json decode error: {jde}"
        except Exception as exc:  # pragma: no cover - network/runtime
            return None, str(exc)

    def _rest_snapshot_single(
        self,
        name: str,
        service_name: str,
        headers: Dict[str, str],
        report_sections: Dict[str, Any],
        retrieval_errors: Dict[str, Any],
    ) -> None:
        encoded = urllib.parse.quote(service_name, safe="")
        url = (
            SERVICEUSAGE_BASE_URL
            + "/projects/"
            + self.project_id
            + "/services/"
            + encoded
            + "/consumerQuotaMetrics"
        )
        data, reterr = self._rest_get_json(url, headers)
        if reterr:
            retrieval_errors[name] = reterr
            return
        report_sections[name] = {"service": service_name, "quota_metrics": data}

    def _rest_snapshot_services(
        self,
        name: str,
        headers: Dict[str, str],
        report_sections: Dict[str, Any],
        retrieval_errors: Dict[str, Any],
    ) -> None:
        enabled_services, eerr = self._run_gcloud_json(
            [
                "gcloud",
                "services",
                "list",
                "--enabled",
                "--project",
                self.project_id,
                "--format=json",
            ]
        )
        if eerr:
            retrieval_errors[name] = eerr
            return
        if not isinstance(enabled_services, list):
            retrieval_errors[name] = "unexpected enabled services format"
            return

        services_map: Dict[str, Any] = {}
        for svc in enabled_services:
            if isinstance(svc, dict):
                svc_name = svc.get("config", {}).get("name")
            else:
                svc_name = None
            if not svc_name:
                continue
            encoded = urllib.parse.quote(svc_name, safe="")
            url = (
                SERVICEUSAGE_BASE_URL
                + "/projects/"
                + self.project_id
                + "/services/"
                + encoded
                + "/consumerQuotaMetrics"
            )
            data, reterr = self._rest_get_json(url, headers)
            if reterr:
                retrieval_errors[f"{name}:{svc_name}"] = reterr
                services_map[svc_name] = None
                continue
            services_map[svc_name] = data

        report_sections[name] = {"services": services_map}

    def _get_access_token_for_rest(self) -> Tuple[Optional[str], Optional[str]]:
        token_out, token_err = self._run_gcloud_json(
            ["gcloud", "auth", "print-access-token", "--format=json"]
        )
        if token_err:
            return None, token_err
        if isinstance(token_out, str):
            return token_out.strip('"'), None
        token_text, token_err2 = self._run_gcloud_text(
            ["gcloud", "auth", "print-access-token"]
        )  # fallback
        if token_err2:
            return None, token_err2
        return token_text.strip(), None

    # --- Expected-resources helpers -------------------------------------
    def _extract_expected_apis(self, component_items: List[Any]) -> List[str]:
        apis: List[str] = []
        for component_item in component_items:
            if not isinstance(component_item, dict):
                continue
            if component_item.get("enabled", True) is False:
                continue
            if component_item.get("action") == "enable_api":
                args = component_item.get("args", {}) or {}
                service_name = str(args.get("service", "")).strip()
                if service_name:
                    apis.append(service_name)
        return apis

    def _extract_expected_service_accounts(self, component_items: List[Any]) -> List[str]:
        accounts: List[str] = []
        for component_item in component_items:
            if not isinstance(component_item, dict):
                continue
            if component_item.get("enabled", True) is False:
                continue
            action_name = component_item.get("action")
            if action_name in {
                "ensure_service_account",
                "ensure_service_account_key",
                "configure_local_credentials",
            }:
                args = component_item.get("args", {}) or {}
                service_account_name = str(args.get("service_account_name", "")).strip()
                if service_account_name:
                    domain = ".iam.gserviceaccount.com"
                    accounts.append(f"{service_account_name}@{self.project_id}" + domain)
        return accounts

    def _extract_expected_iam_bindings(
        self, component_items: List[Any]
    ) -> List[Dict[str, str]]:
        bindings: List[Dict[str, str]] = []
        for component_item in component_items:
            if not isinstance(component_item, dict):
                continue
            if component_item.get("enabled", True) is False:
                continue
            if component_item.get("action") != "ensure_project_iam_binding":
                continue
            args = component_item.get("args", {}) or {}
            role_name = str(args.get("role", "")).strip()
            member_name = str(args.get("member", "")).strip()
            service_account_name = str(args.get("service_account_name", "")).strip()
            if "{service_account_email}" in member_name and service_account_name:
                service_account_email = (
                    f"{service_account_name}@{self.project_id}.iam.gserviceaccount.com"
                )
                member_name = member_name.replace(
                    "{service_account_email}", service_account_email
                )
            if role_name and member_name:
                bindings.append({"role": role_name, "member": member_name})
        return bindings

    def _run_report_item(
        self,
        name: str,
        spec: Dict[str, Any],
        report_sections: Dict[str, Any],
        retrieval_errors: Dict[str, Any],
    ) -> None:
        """Execute a configured report item and store results into report_sections.

        The `spec` argument is a dictionary loaded from `gcp_report_items.yaml`.
        This runner supports three modes:
        - simple gcloud CLI commands (list form)
        - region-expanded commands for `compute_region_quotas`
        - REST-based snapshots for `api_quota_snapshot` (controlled via `mode`)

        Results are written into `report_sections[name]` on success. Any
        collection errors are recorded into `retrieval_errors[name]`.
        """
        if not spec.get("enabled", False):
            self._status(f"Skipping disabled report item: {name}", level=2)
            return

        command_template = spec.get("command", [])
        if not isinstance(command_template, list) or not command_template:
            retrieval_errors[name] = "invalid or missing command template"
            return

        self._status(f"Running report item: {name}", level=1)
        # Dispatch to smaller handlers based on the report item type.
        if name == "compute_region_quotas":
            self._handle_compute_region_quotas(
                name, spec, report_sections, retrieval_errors
            )
            # write progress after handler
            try:
                self._write_partial_report(report_sections, retrieval_errors)
            except Exception:
                pass
            return

        first = str(command_template[0])
        if first.startswith("REST:"):
            self._handle_rest_report_item(name, spec, report_sections, retrieval_errors)
            # write progress after handler
            try:
                self._write_partial_report(report_sections, retrieval_errors)
            except Exception:
                pass
            return

        # default generic handler
        self._handle_generic_report_item(name, spec, report_sections, retrieval_errors)
        # write progress after generic handler
        try:
            self._write_partial_report(report_sections, retrieval_errors)
        except Exception:
            pass

    def _extract_expected_components(self) -> Dict[str, Any]:
        """Extract expected resources from components configuration."""
        component_items = self.components_configuration.get("components", [])
        if not isinstance(component_items, list):
            component_items = []

        return {
            "apis": self._extract_expected_apis(component_items),
            "service_accounts": self._extract_expected_service_accounts(component_items),
            "iam_bindings": self._extract_expected_iam_bindings(component_items),
        }

    def _build_intent_comparison(
        self, expected_resources: Dict[str, Any], report_sections: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compare expected resources against retrieved state and report missing items."""
        enabled_apis_items = report_sections.get("enabled_apis", {}).get("items", [])
        enabled_api_names: List[str] = []
        for item in enabled_apis_items:
            if isinstance(item, dict):
                name = (
                    item.get("config", {}).get("name")
                    or item.get("name")
                    or item.get("serviceName")
                )
                if name:
                    enabled_api_names.append(name)

        actual_service_account_emails = {
            item.get("email", "")
            for item in report_sections.get("service_accounts", {}).get("items", [])
            if isinstance(item, dict)
        }

        iam_policy_bindings = report_sections.get("iam_policy", {}).get("bindings", [])
        actual_binding_pairs = set()
        for binding in iam_policy_bindings:
            if not isinstance(binding, dict):
                continue
            role_name = binding.get("role", "")
            members = binding.get("members", [])
            if not isinstance(members, list):
                continue
            for member_name in members:
                actual_binding_pairs.add((role_name, member_name))

        missing_apis = [
            api_name
            for api_name in expected_resources.get("apis", [])
            if api_name not in enabled_api_names
        ]

        missing_service_accounts = [
            account_email
            for account_email in expected_resources.get("service_accounts", [])
            if account_email not in actual_service_account_emails
        ]

        missing_bindings: List[Dict[str, str]] = []
        for binding in expected_resources.get("iam_bindings", []):
            role_name = binding.get("role", "")
            member_name = binding.get("member", "")
            if (role_name, member_name) not in actual_binding_pairs:
                missing_bindings.append(binding)

        return {
            "expected": expected_resources,
            "missing": {
                "apis": missing_apis,
                "service_accounts": missing_service_accounts,
                "iam_bindings": missing_bindings,
            },
            "status": {
                "apis_ok": len(missing_apis) == 0,
                "service_accounts_ok": len(missing_service_accounts) == 0,
                "iam_bindings_ok": len(missing_bindings) == 0,
            },
        }

    def _collect_and_assign(
        self,
        key: str,
        command_template: List[str],
        report_sections: Dict[str, Any],
        retrieval_errors: Dict[str, Any],
        mode: str = "json_single",
    ) -> None:
        """Run a gcloud command and assign results into `report_sections`.

        Modes:
        - "json_single": expect a JSON object, store dict or {}.
        - "json_items": expect a JSON list, store {count, items}.
        - "text": run command and store plain text output.
        """
        # prepare command, allowing `{project_id}` templates
        cmd = [
            s.format(project_id=self.project_id) if isinstance(s, str) else s
            for s in command_template
        ]

        self._status(f"Collecting '{key}' (mode={mode})", level=1)
        if mode == "text":
            self._status(f"Running text command: {' '.join(cmd)}", level=2)
            text, err = self._run_gcloud_text(cmd)
            report_sections[key] = text
            if err:
                retrieval_errors[key] = err
            # persist partial report after collecting this section
            try:
                self._write_partial_report(report_sections, retrieval_errors)
            except Exception:
                pass
            return

        self._status(f"Running json command: {' '.join(cmd)}", level=2)
        data, err = self._run_gcloud_json(cmd)
        if mode == "json_items":
            report_sections[key] = {
                "count": len(data) if isinstance(data, list) else 0,
                "items": data if isinstance(data, list) else [],
            }
        else:
            report_sections[key] = data or {}

        if err:
            retrieval_errors[key] = err
        # persist partial report after collecting this section
        try:
            self._write_partial_report(report_sections, retrieval_errors)
        except Exception:
            pass

    def _collect_builtin_sections(
        self,
        report_sections: Dict[str, Any],
        retrieval_errors: Dict[str, Any],
    ) -> str:
        """Collect the built-in report sections and return active configuration name."""
        # Use helper to reduce repetition and complexity
        self._collect_and_assign(
            "project_description",
            DEFAULT_BUILTIN_REPORT_COMMANDS["project_description"],
            report_sections,
            retrieval_errors,
            mode="json_single",
        )

        self._collect_and_assign(
            "gcloud_config",
            DEFAULT_BUILTIN_REPORT_COMMANDS["gcloud_config"],
            report_sections,
            retrieval_errors,
            mode="json_single",
        )

        self._collect_and_assign(
            "gcloud_auth_accounts",
            DEFAULT_BUILTIN_REPORT_COMMANDS["gcloud_auth_accounts"],
            report_sections,
            retrieval_errors,
            mode="json_single",
        )

        self._collect_and_assign(
            "enabled_apis",
            DEFAULT_BUILTIN_REPORT_COMMANDS["enabled_apis"],
            report_sections,
            retrieval_errors,
            mode="json_items",
        )

        self._collect_and_assign(
            "service_accounts",
            DEFAULT_BUILTIN_REPORT_COMMANDS["service_accounts"],
            report_sections,
            retrieval_errors,
            mode="json_items",
        )

        self._collect_and_assign(
            "iam_policy",
            DEFAULT_BUILTIN_REPORT_COMMANDS["iam_policy"],
            report_sections,
            retrieval_errors,
            mode="json_single",
        )

        self._collect_and_assign(
            "billing",
            DEFAULT_BUILTIN_REPORT_COMMANDS["billing"],
            report_sections,
            retrieval_errors,
            mode="json_single",
        )

        self._collect_and_assign(
            "compute_project_info",
            DEFAULT_BUILTIN_REPORT_COMMANDS["compute_project_info"],
            report_sections,
            retrieval_errors,
            mode="json_single",
        )

        active_configuration_name, error = self._run_gcloud_text(
            DEFAULT_BUILTIN_REPORT_COMMANDS["active_configurations"]
        )
        report_sections["active_gcloud_configuration"] = active_configuration_name
        if error:
            retrieval_errors["active_gcloud_configuration"] = error

        return active_configuration_name

    def _resolve_path(self, raw_path: str) -> Path:
        """Resolve relative paths based on runtime config directory."""
        candidate_path = Path(raw_path)
        if candidate_path.is_absolute():
            return candidate_path
        return (self.runtime_config_directory / candidate_path).resolve()

    def _build_completed_error(
        self, p: subprocess.CompletedProcess, ctext: str
    ) -> Dict[str, Any]:
        """Build a standardized error dictionary from a CompletedProcess."""
        stderr_text = p.stderr.strip() if p.stderr else ""
        stdout_text = p.stdout.strip() if p.stdout else ""
        return {
            "cmd": ctext,
            "returncode": p.returncode,
            "stderr": stderr_text,
            "stdout": stdout_text,
        }

    def _write_partial_report(
        self, report_sections: Dict[str, Any], retrieval_errors: Dict[str, Any]
    ) -> None:
        """Write a partial JSON (and optional Markdown) report if output paths
        were provided to the reporter instance.

        This function is safe to call frequently during collection; failures
        are logged to status output but do not raise.
        """
        if not self.output_json_path:
            return
        try:
            expected_resources = self._extract_expected_components()
            intent_comparison = self._build_intent_comparison(
                expected_resources, report_sections
            )

            generated_timestamp = datetime.now(timezone.utc).isoformat()
            report_data = {
                "report_metadata": {
                    "report_version": REPORT_VERSION,
                    "generated_at_utc": generated_timestamp,
                    "project_id": self.project_id,
                    "runtime_config_path": str(
                        Path(self.runtime_config_path).resolve()
                    ),
                    "components_config_path": self.components_configuration.get(
                        "_path", ""
                    ),
                    "components_config_missing": self.components_configuration.get(
                        "_missing", ""
                    ),
                },
                "runtime_configuration": self.runtime_configuration,
                "components_configuration": {
                    "components": self.components_configuration.get("components", []),
                },
                "retrieved_state": report_sections,
                "intent_comparison": intent_comparison,
                "retrieval_errors": retrieval_errors,
            }

            # write JSON
            try:
                Path(self.output_json_path).write_text(
                    json.dumps(report_data, indent=2, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as exc:  # pragma: no cover - I/O
                self._status(f"Failed writing partial JSON report: {exc}", level=1)

            # optionally write markdown
            if self.generate_markdown and self.output_markdown_path:
                try:
                    md = build_markdown_report(report_data)
                    Path(self.output_markdown_path).write_text(md, encoding="utf-8")
                except Exception as exc:  # pragma: no cover - I/O
                    self._status(f"Failed writing partial Markdown report: {exc}", level=1)
        except Exception as exc:  # pragma: no cover - defensive
            self._status(f"Partial report generation failed: {exc}", level=1)

    def _invoke_with_retries(
        self, command_list: List[str], cmd_text: str
    ) -> Tuple[Optional[subprocess.CompletedProcess], Optional[Dict[str, Any]]]:
        """Invoke `_invoke_subprocess_once` with retries and return a
        successful CompletedProcess or an error dict when exhausted.

        Returns a tuple `(CompletedProcess, None)` on success or
        `(None, error_dict)` on failure.
        """
        for attempt in range(max(1, self.subprocess_retries)):
            completed_process, invoke_err = self._invoke_subprocess_once(
                command_list
            )
            if invoke_err:
                err = {"cmd": cmd_text, "error": invoke_err}
                if self.debug_level:
                    time.sleep(1)
                if attempt + 1 < max(1, self.subprocess_retries):
                    continue
                return None, err

            if completed_process is None:
                return None, {"cmd": cmd_text, "error": "no result"}

            if completed_process.returncode != 0:
                err = self._build_completed_error(completed_process, cmd_text)
                if attempt + 1 < max(1, self.subprocess_retries):
                    time.sleep(1 + attempt)
                    continue
                return None, err

            return completed_process, None

        return None, {"cmd": cmd_text, "error": "retries exhausted"}

    def _run_gcloud_json(
        self,
        command_arguments: List[str],
    ) -> Tuple[Optional[Any], Optional[str]]:
        """Run gcloud command and parse JSON response.

        Returns:
            tuple(data, error_message)
        """
        # normalize gcloud executable on Windows
        cmd = list(command_arguments)
        if cmd and cmd[0] == "gcloud":
            cmd[0] = self.gcloud_executable

        cmd_text = " ".join(cmd)

        self._status(f"Invoking gcloud json: {cmd_text}", level=2)
        completed_process, err = self._invoke_with_retries(cmd, cmd_text)
        if err:
            return None, err

        if completed_process is None:
            return None, {"cmd": cmd_text, "error": "no result"}

        output_text = completed_process.stdout.strip()
        if not output_text:
            return None, None

        try:
            return json.loads(output_text), None
        except json.JSONDecodeError as decode_error:
            err_info = {
                "cmd": cmd_text,
                "error": f"JSON parsing failed: {decode_error}",
                "stdout": output_text,
            }
            return None, err_info

    def _run_gcloud_text(
        self,
        command_arguments: List[str],
    ) -> Tuple[str, Optional[str]]:
        """Run gcloud command and return plain-text output."""
        cmd = list(command_arguments)
        if cmd and cmd[0] == "gcloud":
            cmd[0] = self.gcloud_executable

        command_text = " ".join(cmd)
        last_error: Optional[Dict[str, Any]] = None
        self._status(f"Invoking gcloud text: {command_text}", level=2)
        for attempt in range(max(1, self.subprocess_retries)):
            completed_process, invoke_err = self._invoke_subprocess_once(cmd)
            if invoke_err:
                last_error = {"cmd": command_text, "error": invoke_err}
                if self.debug_level:
                    time.sleep(1)
                if attempt + 1 < max(1, self.subprocess_retries):
                    continue
                return "", last_error

            if completed_process is None:
                last_error = {"cmd": command_text, "error": "no result"}
                return "", last_error

            if completed_process.returncode != 0:
                stderr_text = (
                    completed_process.stderr.strip() if completed_process.stderr else ""
                )
                stdout_text = (
                    completed_process.stdout.strip() if completed_process.stdout else ""
                )
                last_error = {
                    "cmd": command_text,
                    "returncode": completed_process.returncode,
                    "stderr": stderr_text,
                    "stdout": stdout_text,
                }
                if attempt + 1 < max(1, self.subprocess_retries):
                    time.sleep(1 + attempt)
                    continue
                return "", last_error

                return completed_process.stdout.strip(), None

        return "", last_error

    def collect_report_data(self) -> Dict[str, Any]:
        """Collect project metadata and retrievable cloud configuration info."""
        report_sections: Dict[str, Any] = {}
        retrieval_errors: Dict[str, str] = {}
        # collect built-in sections
        self._collect_builtin_sections(report_sections, retrieval_errors)

        # Load and execute additional report items defined in gcp_report_items.yaml
        report_items = self._load_report_items().get("reports", {})
        for item_name, item_spec in report_items.items():
            # Avoid re-running items already collected by the built-in flows
            if item_name in report_sections:
                continue
            try:
                self._run_report_item(
                    item_name,
                    item_spec or {},
                    report_sections,
                    retrieval_errors,
                )
            except Exception as exc:  # keep report generation resilient
                retrieval_errors[item_name] = f"internal error: {exc}"

        expected_resources = self._extract_expected_components()
        intent_comparison = self._build_intent_comparison(
            expected_resources,
            report_sections,
        )

        generated_timestamp = datetime.now(timezone.utc).isoformat()
        report_data = {
            "report_metadata": {
                "report_version": REPORT_VERSION,
                "generated_at_utc": generated_timestamp,
                "project_id": self.project_id,
                "runtime_config_path": str(Path(self.runtime_config_path).resolve()),
                "components_config_path": self.components_configuration.get("_path", ""),
                "components_config_missing": self.components_configuration.get(
                    "_missing", ""
                ),
            },
            "runtime_configuration": self.runtime_configuration,
            "components_configuration": {
                "components": self.components_configuration.get("components", []),
            },
            "retrieved_state": report_sections,
            "intent_comparison": intent_comparison,
            "retrieval_errors": retrieval_errors,
        }
        return report_data


def build_markdown_report(report_data: Dict[str, Any]) -> str:
    """Build a human-readable markdown summary from report data.

    The function builds a short summary including counts and missing items
    and returns a Markdown string.
    """
    metadata = report_data.get("report_metadata", {})
    retrieved_state = report_data.get("retrieved_state", {})
    intent_comparison = report_data.get("intent_comparison", {})

    enabled_apis = retrieved_state.get("enabled_apis", {}).get("count", 0)
    service_accounts = retrieved_state.get("service_accounts", {}).get("count", 0)

    missing_apis = intent_comparison.get("missing", {}).get("apis", [])
    missing_block = intent_comparison.get("missing", {})
    missing_service_accounts = missing_block.get("service_accounts", [])
    missing_bindings = missing_block.get("iam_bindings", [])

    lines: List[str] = []
    lines.append("# GCP Project Configuration Report")
    lines.append("")
    lines.append(f"- Generated (UTC): {metadata.get('generated_at_utc', '')}")
    lines.append(f"- Project ID: {metadata.get('project_id', '')}")
    lines.append(f"- Runtime Config: {metadata.get('runtime_config_path', '')}")

    components_path = metadata.get("components_config_path", "")
    components_missing = metadata.get("components_config_missing", "")
    if components_path:
        lines.append(f"- Components Config: {components_path}")
    if components_missing:
        lines.append(f"- Components Config Missing: {components_missing}")

    lines.append("")
    lines.append("## Retrieved State Summary")
    lines.append("")
    lines.append(f"- Enabled APIs: {enabled_apis}")
    lines.append(f"- Service Accounts: {service_accounts}")

    lines.append("")
    lines.append("## Intent Comparison")
    lines.append("")
    lines.append(f"- Missing APIs: {len(missing_apis)}")
    lines.append(f"- Missing Service Accounts: {len(missing_service_accounts)}")
    lines.append(f"- Missing IAM Bindings: {len(missing_bindings)}")

    # intent and errors
    lines.extend(_build_markdown_intent_lines(report_data))

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Some sections may be empty if the authenticated account lacks permissions."
    )
    lines.append("- Billing details may require billing-specific IAM permissions.")

    return "\n".join(lines) + "\n"


def parse_arguments() -> argparse.Namespace:
    """Parse CLI arguments for report generation."""
    parser = argparse.ArgumentParser(
        description="Generate structured GCP project configuration report",
    )
    parser.add_argument(
        "--config",
        default="gcp_config.yaml",
        help="Path to runtime configuration YAML",
    )
    parser.add_argument(
        "--components-config",
        default=None,
        help="Optional override path for components configuration YAML",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Optional project ID override",
    )
    parser.add_argument(
        "--output-json",
        default="gcp_project_geninfo_report.json",
        help="Output JSON report file path",
    )
    parser.add_argument(
        "--output-md",
        default="gcp_project_geninfo_report.md",
        help="Output Markdown report file path",
    )
    parser.add_argument(
        "--no-markdown",
        action="store_true",
        help="Disable markdown report generation",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print key report summary to stdout",
    )
    parser.add_argument(
        "--debug-level",
        default=0,
        type=int,
        help="Debug verbosity level: 0 (quiet) - 3 (very verbose)",
    )
    return parser.parse_args()


def _build_markdown_intent_lines(report_data: Dict[str, Any]) -> List[str]:
    """Return markdown lines describing intent comparison and retrieval errors."""
    intent_comparison = report_data.get("intent_comparison", {})
    retrieval_errors = report_data.get("retrieval_errors", {})

    missing_apis = intent_comparison.get("missing", {}).get("apis", [])
    missing_block = intent_comparison.get("missing", {})
    missing_service_accounts = missing_block.get("service_accounts", [])
    missing_bindings = missing_block.get("iam_bindings", [])

    lines: List[str] = []
    if missing_apis:
        lines.append("")
        lines.append("### Missing APIs")
        for api_name in missing_apis:
            lines.append(f"- {api_name}")

    if missing_service_accounts:
        lines.append("")
        lines.append("### Missing Service Accounts")
        for service_account_email in missing_service_accounts:
            lines.append(f"- {service_account_email}")

    if missing_bindings:
        lines.append("")
        lines.append("### Missing IAM Bindings")
        for binding in missing_bindings:
            role_name = binding.get("role", "")
            member_name = binding.get("member", "")
            lines.append(f"- {member_name} -> {role_name}")

    if retrieval_errors:
        lines.append("")
        lines.append("## Retrieval Errors")
        lines.append("")
        for section_name, error_message in retrieval_errors.items():
            lines.append(f"- {section_name}: {error_message}")

    return lines


def print_summary(report_data: Dict[str, Any]) -> None:
    """Print compact summary to stdout for quick visibility."""
    metadata = report_data.get("report_metadata", {})
    retrieved_state = report_data.get("retrieved_state", {})
    intent_comparison = report_data.get("intent_comparison", {})

    enabled_api_count = retrieved_state.get("enabled_apis", {}).get("count", 0)
    service_account_count = retrieved_state.get("service_accounts", {}).get("count", 0)

    missing_apis = len(intent_comparison.get("missing", {}).get("apis", []))
    missing_service_accounts = len(
        intent_comparison.get("missing", {}).get("service_accounts", [])
    )
    missing_bindings = len(intent_comparison.get("missing", {}).get("iam_bindings", []))

    print("GCP Project Configuration Summary")
    print(f"- Project ID: {metadata.get('project_id', '')}")
    print(f"- Generated (UTC): {metadata.get('generated_at_utc', '')}")
    print(f"- Enabled APIs: {enabled_api_count}")
    print(f"- Service Accounts: {service_account_count}")
    print(f"- Missing APIs vs Components: {missing_apis}")
    print(f"- Missing Service Accounts vs Components: {missing_service_accounts}")
    print(f"- Missing IAM Bindings vs Components: {missing_bindings}")


def main() -> None:
    """Entry point for generating project information reports."""
    arguments = parse_arguments()

    try:
        reporter = GCloudProjectInfoReporter(
            runtime_config_path=arguments.config,
            components_config_override=arguments.components_config,
            project_id_override=arguments.project_id,
            debug_level=arguments.debug_level,
        )
    except ValueError as value_error:
        print(f"Configuration error: {value_error}", file=sys.stderr)
        sys.exit(1)

    # Ensure CLI prerequisites are met before attempting to collect data
    if not reporter.check_prerequisites():
        print("Prerequisite check failed; aborting report generation.", file=sys.stderr)
        sys.exit(2)

    # configure reporter to write partial progress if output paths are provided
    reporter.output_json_path = Path(arguments.output_json).resolve()
    reporter.output_markdown_path = (
        Path(arguments.output_md).resolve() if not arguments.no_markdown else None
    )
    reporter.generate_markdown = not arguments.no_markdown

    report_data = reporter.collect_report_data()

    output_json_path = Path(arguments.output_json).resolve()
    output_json_path.write_text(
        json.dumps(report_data, indent=2, sort_keys=False),
        encoding="utf-8",
    )

    if not arguments.no_markdown:
        output_markdown_path = Path(arguments.output_md).resolve()
        markdown_content = build_markdown_report(report_data)
        output_markdown_path.write_text(markdown_content, encoding="utf-8")

    if arguments.print_summary:
        print_summary(report_data)

    print(f"JSON report written to: {output_json_path}")
    if not arguments.no_markdown:
        print(f"Markdown report written to: {Path(arguments.output_md).resolve()}")


if __name__ == "__main__":
    main()
