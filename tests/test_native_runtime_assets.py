import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import TypeAlias, cast

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
PACKAGE_SCRIPT = REPO_ROOT / "deploy" / "native" / "package-source-bundle.sh"
VERIFY_SCRIPT = REPO_ROOT / "deploy" / "native" / "verify-source-bundle.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "native" / "deploy-release.sh"
HEALTHCHECK_SCRIPT = REPO_ROOT / "deploy" / "native" / "healthcheck.sh"
TEMPLATE_PATH = REPO_ROOT / "deploy" / "native" / "kt-demo-alarm.service.template"
SCRIPT_DIR = REPO_ROOT / "scripts" / "native"
NATIVE_GUIDE_PATH = REPO_ROOT / "docs" / "native-linux-deploy-guide.md"
RUNBOOK_PATH = REPO_ROOT / "docs" / "docker-free-fastapi-deploy-runbook.md"
NATIVE_ASSET_README_PATH = REPO_ROOT / "deploy" / "native" / "README.md"
ROOT_README_PATH = REPO_ROOT / "README.md"
LEGACY_DOCKER_DIR = REPO_ROOT / "legacy" / "docker-deploy"
LEGACY_BOOTSTRAP_README = REPO_ROOT / "legacy" / "bootstrap" / "README.md"
SETUP_EC2_SCRIPT = REPO_ROOT / "scripts" / "setup-ec2.sh"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"
ADVISORY_CONTRACT_SCRIPT = REPO_ROOT / "scripts" / "ci" / "advisory_contract.py"
YamlScalar: TypeAlias = str | int | float | bool | None
YamlValue: TypeAlias = YamlScalar | list["YamlValue"] | dict[str, "YamlValue"]
WorkflowJob: TypeAlias = dict[str, YamlValue]
WorkflowJobs: TypeAlias = dict[str, WorkflowJob]
WorkflowDocument: TypeAlias = dict[str, YamlValue]


def run_command(
    *args: str,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    if env is not None:
        env = {**os.environ, **env}

    return subprocess.run(
        args,
        cwd=cwd or REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
        env=env,
    )


def workflow() -> WorkflowDocument:
    loaded = cast(WorkflowDocument, yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8")))
    assert isinstance(loaded, dict)
    return loaded


def workflow_jobs() -> WorkflowJobs:
    jobs = workflow()["jobs"]
    assert isinstance(jobs, dict)
    return cast(WorkflowJobs, jobs)


def normalize_needs(value: YamlValue) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def uncommented_workflow_text() -> str:
    return "\n".join(
        line
        for line in WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def uncommented_text(path: Path) -> str:
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def _python_version(executable: str | Path) -> tuple[int, int]:
    inspect = run_command(
        str(executable),
        "-c",
        "import json, sys; print(json.dumps(list(sys.version_info[:2])))",
    )
    major, minor = json.loads(inspect.stdout)
    return int(major), int(minor)


def _compatible_python_or_skip(*names: str, require_non_home: bool = False) -> Path:
    home = Path.home().resolve()
    for name in names:
        python_bin = shutil.which(name)
        if python_bin is None:
            continue
        resolved = Path(python_bin).resolve()
        if _python_version(resolved) < (3, 12):
            continue
        if require_non_home and resolved.is_relative_to(home):
            continue
        return resolved

    scope = "non-HOME " if require_non_home else ""
    pytest.skip(f"{scope}Python 3.12+ interpreter is required for this test")


def test_deploy_workflow_matches_guarded_native_graph() -> None:
    jobs = workflow_jobs()

    assert set(jobs) == {
        "blocking-tests",
        "package-native-release",
        "deploy-native-preflight",
        "deploy-native-live",
        "public-health",
    }

    assert normalize_needs(jobs["package-native-release"]["needs"]) == ["blocking-tests"]
    assert normalize_needs(jobs["deploy-native-preflight"]["needs"]) == ["package-native-release"]
    assert normalize_needs(jobs["deploy-native-live"]["needs"]) == ["deploy-native-preflight"]
    assert normalize_needs(jobs["public-health"]["needs"]) == ["deploy-native-live"]

    deploy_live = jobs["deploy-native-live"]
    assert deploy_live["if"] == "${{ vars.KT_NATIVE_DEPLOY_ENABLED == '1' }}"
    deploy_environment = cast(dict[str, YamlValue], deploy_live["environment"])
    assert deploy_environment["name"] == "native-live"

    public_health = jobs["public-health"]
    assert public_health["if"] == "${{ needs.deploy-native-live.result == 'success' }}"


def test_blocking_workflow_installs_playwright_browser_for_smoke_test() -> None:
    jobs = workflow_jobs()
    blocking_steps = cast(list[dict[str, YamlValue]], jobs["blocking-tests"]["steps"])
    run_text = "\n".join(str(step.get("run", "")) for step in blocking_steps)

    assert "playwright install chromium" in run_text
    assert "uv run pytest -q" in run_text
    assert "advisory_contract.py" not in run_text


def test_active_workflow_retires_advisory_contract_lane() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    active_text = uncommented_workflow_text()

    assert "ADVISORY_CONTRACT_ID" not in workflow_text
    assert "advisory-template-regression" not in active_text
    assert "scripts/ci/advisory_contract.py" not in active_text


def test_active_workflow_removes_docker_runtime_and_runner_env_rendering() -> None:
    for job in workflow_jobs().values():
        steps = cast(list[dict[str, YamlValue]], job.get("steps", []))
        for step in steps:
            uses = str(step.get("uses", ""))
            run = str(step.get("run", ""))

            assert not re.search(r"(?i)^docker/", uses)
            assert not re.search(r"(?i)(^|\s)docker(?:\s+compose|[-_/][\w-]+|\b)", run)
            assert not re.search(r"docker-compose\.yml", run)
            assert not re.search(r">\s*\.env\b", run)


def test_deploy_workflow_normalizes_incoming_permissions_for_service_group() -> None:
    workflow_text = uncommented_workflow_text()

    assert 'chmod 700 ${remote_incoming_dir_q}' not in workflow_text
    assert '"set -euo pipefail' not in workflow_text
    assert '"set -eu' in workflow_text
    assert 'resolved_app_user="${APP_USER:-${APP_NAME}}"' in workflow_text
    assert 'resolved_app_group="${APP_GROUP:-${resolved_app_user}}"' in workflow_text
    assert 'remote_incoming_root="${APP_ROOT}/incoming"' in workflow_text
    assert 'remote_incoming_owner_q="$(quote_remote "${EC2_USERNAME}:${resolved_app_group}")"' in workflow_text
    assert re.search(
        r"^\s*sudo chgrp .*resolved_app_group.*remote_incoming_root.*remote_incoming_dir.*$",
        workflow_text,
        re.MULTILINE,
    )
    assert re.search(
        r"^\s*sudo chown .*remote_incoming_owner.*remote_incoming_dir.*$",
        workflow_text,
        re.MULTILINE,
    )
    assert re.search(
        r"^\s*sudo chmod g\+rx .*remote_incoming_root.*remote_incoming_dir.*$",
        workflow_text,
        re.MULTILINE,
    )
    assert re.search(r"^\s*sudo chmod u\+rwx .*remote_incoming_dir.*$", workflow_text, re.MULTILINE)
    assert re.search(
        r"^\s*sudo chmod o-rwx .*remote_incoming_root.*remote_incoming_dir.*$",
        workflow_text,
        re.MULTILINE,
    )
    assert re.search(
        r"^\s*sudo chmod g\+s .*remote_incoming_root.*remote_incoming_dir.*$",
        workflow_text,
        re.MULTILINE,
    )
    assert "APP_NAME=%q APP_USER=%q APP_GROUP=%q APP_ROOT=%q" in workflow_text


def test_package_and_verify_source_bundle_contract(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()

    _ = run_command("bash", str(PACKAGE_SCRIPT), str(artifact_dir))

    bundle_path = artifact_dir / "source-bundle.tar.gz"
    checksum_path = artifact_dir / "source-bundle.sha256"

    assert bundle_path.exists()
    assert checksum_path.exists()

    _ = run_command("bash", str(VERIFY_SCRIPT), str(bundle_path), str(checksum_path))

    with tarfile.open(bundle_path, "r:gz") as bundle:
        members = bundle.getmembers()
        names = sorted(
            (
                member.name[2:] if member.name.startswith("./") else member.name
            ).rstrip("/")
            for member in members
            if member.name not in {".", "./"}
        )

    assert not any(member.issym() or member.islnk() for member in members)

    required_entries = {
        "bundle-manifest.txt",
        "main.py",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "deploy/native/deploy-release.sh",
        "deploy/native/verify-source-bundle.sh",
        "deploy/native/package-source-bundle.sh",
        "deploy/native/healthcheck.sh",
        "deploy/native/kt-demo-alarm.service.template",
        "docs/native-linux-deploy-guide.md",
        "docs/docker-free-fastapi-deploy-runbook.md",
    }
    for entry in required_entries:
        assert entry in names

    denied_patterns = [
        ".env",
        ".env.example",
        "docker-compose.yml",
        "Dockerfile",
        "attachments",
        "topis_attachments",
        "topis_cache",
    ]
    for denied in denied_patterns:
        assert all(name != denied and not name.startswith(f"{denied}/") for name in names)


def test_verify_source_bundle_accepts_relocated_artifact(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    relocated_dir = tmp_path / "relocated"
    artifact_dir.mkdir()
    relocated_dir.mkdir()

    _ = run_command("bash", str(PACKAGE_SCRIPT), str(artifact_dir))

    bundle_path = artifact_dir / "source-bundle.tar.gz"
    checksum_path = artifact_dir / "source-bundle.sha256"
    relocated_bundle = relocated_dir / bundle_path.name
    relocated_checksum = relocated_dir / checksum_path.name

    shutil.move(bundle_path, relocated_bundle)
    shutil.move(checksum_path, relocated_checksum)

    _ = run_command("bash", str(VERIFY_SCRIPT), str(relocated_bundle), str(relocated_checksum))


def test_package_source_bundle_rejects_symlinks(tmp_path: Path) -> None:
    temp_repo = tmp_path / "repo"
    artifact_dir = tmp_path / "artifact"
    (temp_repo / "app").mkdir(parents=True)
    (temp_repo / "deploy" / "native").mkdir(parents=True)
    (temp_repo / "docs").mkdir(parents=True)

    shutil.copy2(PACKAGE_SCRIPT, temp_repo / "deploy" / "native" / PACKAGE_SCRIPT.name)
    (temp_repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    (temp_repo / "main.py").write_text("app = None\n", encoding="utf-8")
    (temp_repo / "pyproject.toml").write_text(
        "[project]\nname = \"tmp-native-bundle\"\nversion = \"0.0.0\"\nrequires-python = \">=3.12\"\n",
        encoding="utf-8",
    )
    (temp_repo / "uv.lock").write_text("version = 1\nrevision = 1\n", encoding="utf-8")
    (temp_repo / ".python-version").write_text("3.12\n", encoding="utf-8")
    (temp_repo / "docs" / "native-linux-deploy-guide.md").write_text("# guide\n", encoding="utf-8")
    (temp_repo / "docs" / "docker-free-fastapi-deploy-runbook.md").write_text(
        "# runbook\n",
        encoding="utf-8",
    )

    outside_target = tmp_path / "outside.txt"
    outside_target.write_text("outside\n", encoding="utf-8")
    os.symlink(outside_target, temp_repo / "app" / "external-link")

    result = run_command(
        "bash",
        str(temp_repo / "deploy" / "native" / PACKAGE_SCRIPT.name),
        str(artifact_dir),
        cwd=temp_repo,
        check=False,
    )

    assert result.returncode == 1
    assert "Symlinks are not allowed in source bundle staging area:" in result.stderr
    assert "app/external-link" in result.stderr


def test_package_source_bundle_accepts_relative_output_dir(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    relative_output_dir = os.path.relpath(artifact_dir, REPO_ROOT)

    _ = run_command("bash", str(PACKAGE_SCRIPT), relative_output_dir)

    bundle_path = artifact_dir / "source-bundle.tar.gz"
    checksum_path = artifact_dir / "source-bundle.sha256"

    assert bundle_path.exists()
    assert checksum_path.exists()

    _ = run_command("bash", str(VERIFY_SCRIPT), str(bundle_path), str(checksum_path))


def test_package_source_bundle_accepts_repo_local_relative_output_dir() -> None:
    artifact_dir = REPO_ROOT / ".pytest-package-artifact"

    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)

    try:
        _ = run_command("bash", str(PACKAGE_SCRIPT), artifact_dir.name)

        bundle_path = artifact_dir / "source-bundle.tar.gz"
        checksum_path = artifact_dir / "source-bundle.sha256"

        assert bundle_path.exists()
        assert checksum_path.exists()

        _ = run_command("bash", str(VERIFY_SCRIPT), str(bundle_path), str(checksum_path))
    finally:
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)


def test_deploy_release_script_contains_required_preflight_and_rollback_guards() -> None:
    deploy_text = uncommented_text(DEPLOY_SCRIPT)

    assert re.search(
        r'^\s*PYTHON_BIN="\$\{PYTHON_BIN:-\$\{KT_NATIVE_PYTHON_BIN:-python3\}\}"$',
        deploy_text,
        re.MULTILINE,
    )
    assert re.search(r'^\s*PYTHON_REQUEST="\$\{PYTHON_BIN\}"$', deploy_text, re.MULTILINE)
    assert re.search(r'^\s*PYTHON_MODE="system"$', deploy_text, re.MULTILINE)
    assert re.search(
        r'^\s*MANAGED_PYTHON_VERSION="\$\{MANAGED_PYTHON_VERSION:-3\.12\}"$',
        deploy_text,
        re.MULTILINE,
    )
    assert re.search(
        r'^\s*MANAGED_PYTHON_INSTALL_DIR="\$\{UV_PYTHON_INSTALL_DIR:-\$\{SHARED_DIR\}/uv/python\}"$',
        deploy_text,
        re.MULTILINE,
    )
    assert re.search(
        r'^\s*UNIT_CANDIDATE="\$\{RELEASE_DIR\}/\$\{APP_NAME\}\.candidate\.service"$',
        deploy_text,
        re.MULTILINE,
    )
    assert re.search(r'^\s*elif is_truthy "\$\{ALLOW_PORT_TAKEOVER\}"; then$', deploy_text, re.MULTILINE)
    assert re.search(r'^\s*if is_truthy "\$\{ALLOW_DOCKER_CUTOVER\}"; then$', deploy_text, re.MULTILINE)
    assert re.search(
        r'^\s*bash "\$\{VERIFY_SOURCE_BUNDLE_BIN\}" "\$\{BUNDLE_PATH\}" "\$\{CHECKSUM_PATH\}"$',
        deploy_text,
        re.MULTILINE,
    )
    assert "PYTHON_BIN_WAS_EXPLICIT=0" in deploy_text
    assert 'if [[ -n "${PYTHON_BIN:-}" || -n "${KT_NATIVE_PYTHON_BIN:-}" ]]; then' in deploy_text
    assert re.search(r"^\s*python_candidate_paths\(\) \{$", deploy_text, re.MULTILINE)
    assert re.search(r"^\s*python_path_probe\(\) \{$", deploy_text, re.MULTILINE)
    assert re.search(r"^\s*path_is_under_home\(\) \{$", deploy_text, re.MULTILINE)
    assert re.search(r"^\s*python_path_satisfies_contract\(\) \{$", deploy_text, re.MULTILINE)
    assert re.search(r"^\s*resolve_python_candidate_path\(\) \{$", deploy_text, re.MULTILINE)
    assert re.search(r"^\s*log_python_candidate_details\(\) \{$", deploy_text, re.MULTILINE)
    assert re.search(r"^\s*prepare_managed_python_install_dir\(\) \{$", deploy_text, re.MULTILINE)
    assert re.search(r"^\s*normalize_managed_python_install_permissions\(\) \{$", deploy_text, re.MULTILINE)
    assert 'path_is_under_home "${candidate_executable}" && return 1' in deploy_text
    assert '! path_is_under_home "${MANAGED_PYTHON_INSTALL_DIR}"' in deploy_text
    assert 'location = "user-home"' in deploy_text
    assert 'candidates+=("python3.12")' in deploy_text
    assert 'Using compatible system Python candidate ${candidate} instead of default ${PYTHON_BIN}' in deploy_text
    assert 'Using system Python binary ${PYTHON_BIN}' in deploy_text
    assert 'log_python_candidate_details "python3.12"' in deploy_text
    assert 'PYTHON_REQUEST="${MANAGED_PYTHON_VERSION}"' in deploy_text
    assert 'log "Falling back to uv-managed Python ${MANAGED_PYTHON_VERSION} under ${MANAGED_PYTHON_INSTALL_DIR}"' in deploy_text
    assert 'Managed Python install dir must not live under HOME: ${MANAGED_PYTHON_INSTALL_DIR}' in deploy_text
    assert "Python 3.12 or newer is required" in deploy_text
    assert re.search(r'^\s*"\$\{SYSTEMD_ANALYZE_BIN\}" verify "\$\{UNIT_CANDIDATE\}"$', deploy_text, re.MULTILINE)
    assert "resolve_runtime_uv_bin" not in deploy_text
    assert re.search(
        r'^\s*log "No previous current symlink exists; first native deploy rollback is limited\."$',
        deploy_text,
        re.MULTILINE,
    )
    assert re.search(
        r'^\s*log "Restoring previous current symlink: \$\{PREVIOUS_CURRENT\}"$',
        deploy_text,
        re.MULTILINE,
    )
    assert re.search(
        r'^\s*run_privileged "\$\{SYSTEMCTL_BIN\}" --no-pager --full status "\$\{APP_NAME\}" \|\| true$',
        deploy_text,
        re.MULTILINE,
    )
    assert re.search(
        r'^\s*run_privileged "\$\{JOURNALCTL_BIN\}" --no-pager -u "\$\{APP_NAME\}" -n "\$\{DIAGNOSTIC_JOURNAL_LINES\}" \|\| true$',
        deploy_text,
        re.MULTILINE,
    )
    assert re.search(r'^\s*"\$\{NAMEI_BIN\}" -om "\$\{path\}" \|\| true$', deploy_text, re.MULTILINE)
    rollback_match = re.search(r"rollback_after_switch\(\) \{\n(?P<body>.*?)\n\}", deploy_text, re.DOTALL)
    assert rollback_match is not None
    assert "capture_runtime_diagnostics" in rollback_match.group("body")
    diagnostics_match = re.search(r"capture_runtime_diagnostics\(\) \{\n(?P<body>.*?)\n\}", deploy_text, re.DOTALL)
    assert diagnostics_match is not None
    diagnostics_body = diagnostics_match.group("body")
    for required_path in (
        '"${CURRENT_LINK}"',
        '"${CURRENT_LINK}/.venv/bin/python"',
        '"${CURRENT_LINK}/.venv/bin/uvicorn"',
        '"${RELEASE_DIR}"',
        '"${SHARED_DIR}"',
        '"${MANAGED_PYTHON_INSTALL_DIR}"',
        '"${ENV_FILE}"',
        '"${DATABASE_PATH}"',
        '"${LOG_DIR}"',
        '"${CACHE_FILE}"',
        '"${ATTACHMENT_FOLDER}"',
    ):
        assert required_path in diagnostics_body


def test_deploy_release_script_normalizes_release_permissions_for_service_group() -> None:
    deploy_text = uncommented_text(DEPLOY_SCRIPT)
    safe_managed_chmod = (
        'run_privileged find -P "${MANAGED_PYTHON_INSTALL_DIR}" \\( -type d -o -type f \\) -exec chmod g-w {} +'
    )
    safe_release_chmod = 'run_privileged find -P "${RELEASE_DIR}" \\( -type d -o -type f \\) -exec chmod g-w {} +'

    assert re.search(r"^\s*normalize_release_root_permissions\(\) \{$", deploy_text, re.MULTILINE)
    assert 'run_privileged chgrp "${APP_GROUP}" "${RELEASES_DIR}" "${RELEASE_DIR}"' in deploy_text
    assert 'run_privileged chmod g+rx "${RELEASES_DIR}" "${RELEASE_DIR}"' in deploy_text
    assert 'run_privileged chmod g+s "${RELEASES_DIR}" "${RELEASE_DIR}"' in deploy_text
    assert re.search(r"^\s*normalize_release_tree_permissions\(\) \{$", deploy_text, re.MULTILINE)
    assert 'run_privileged find -P "${RELEASE_DIR}" -type d -exec chgrp "${APP_GROUP}" {} +' in deploy_text
    assert 'run_privileged find -P "${RELEASE_DIR}" -type d -exec chmod g+rx,g+s {} +' in deploy_text
    assert 'run_privileged find -P "${RELEASE_DIR}" -type f -exec chgrp "${APP_GROUP}" {} +' in deploy_text
    assert 'run_privileged find -P "${RELEASE_DIR}" -type f -exec chmod g+r {} +' in deploy_text
    assert 'run_privileged find -P "${RELEASE_DIR}" -type f -perm /111 -exec chmod g+rx {} +' in deploy_text
    assert 'run_privileged install -d -o "${MANAGED_PYTHON_INSTALL_OWNER}" -g "${APP_GROUP}" -m 2775 "${MANAGED_PYTHON_INSTALL_DIR}"' in deploy_text
    assert safe_managed_chmod in deploy_text
    assert 'run_privileged find -P "${MANAGED_PYTHON_INSTALL_DIR}" -exec chmod g-w {} +' not in deploy_text
    assert 'run_privileged find -P "${MANAGED_PYTHON_INSTALL_DIR}" -type d -exec chgrp "${APP_GROUP}" {} +' in deploy_text
    assert 'run_privileged find -P "${MANAGED_PYTHON_INSTALL_DIR}" -type d -exec chmod g+rx,g+s {} +' in deploy_text
    assert 'run_privileged find -P "${MANAGED_PYTHON_INSTALL_DIR}" -type f -exec chgrp "${APP_GROUP}" {} +' in deploy_text
    assert 'run_privileged find -P "${MANAGED_PYTHON_INSTALL_DIR}" -type f -exec chmod g+r {} +' in deploy_text
    assert 'run_privileged find -P "${MANAGED_PYTHON_INSTALL_DIR}" -type f -perm /111 -exec chmod g+rx {} +' in deploy_text
    assert safe_release_chmod in deploy_text
    assert 'run_privileged find -P "${RELEASE_DIR}" -exec chmod g-w {} +' not in deploy_text

    managed_match = re.search(
        r"normalize_managed_python_install_permissions\(\) \{\n(?P<body>.*?)\n\}",
        deploy_text,
        re.DOTALL,
    )
    assert managed_match is not None
    managed_body = managed_match.group("body")
    assert managed_body.index(safe_managed_chmod) < managed_body.index(
        'run_privileged find -P "${MANAGED_PYTHON_INSTALL_DIR}" -type d -exec chmod g+rx,g+s {} +'
    )

    release_tree_match = re.search(
        r"normalize_release_tree_permissions\(\) \{\n(?P<body>.*?)\n\}",
        deploy_text,
        re.DOTALL,
    )
    assert release_tree_match is not None
    release_tree_body = release_tree_match.group("body")
    assert release_tree_body.index(safe_release_chmod) < release_tree_body.index(
        'run_privileged find -P "${RELEASE_DIR}" -type d -exec chmod g+rx,g+s {} +'
    )

    prepare_match = re.search(r"prepare_release_dirs\(\) \{\n(?P<body>.*?)\n\}", deploy_text, re.DOTALL)
    assert prepare_match is not None
    assert "normalize_release_root_permissions" in prepare_match.group("body")
    assert "prepare_managed_python_install_dir" in prepare_match.group("body")

    unpack_match = re.search(r"unpack_release\(\) \{\n(?P<body>.*?)\n\}", deploy_text, re.DOTALL)
    assert unpack_match is not None
    unpack_body = unpack_match.group("body")
    assert unpack_body.index('tar -xzf "${BUNDLE_PATH}" -C "${RELEASE_DIR}"') < unpack_body.index(
        "normalize_release_tree_permissions"
    )

    sync_match = re.search(r"sync_dependencies\(\) \{\n(?P<body>.*?)\n\}", deploy_text, re.DOTALL)
    assert sync_match is not None
    sync_body = sync_match.group("body")
    assert 'UV_PYTHON_INSTALL_DIR="${MANAGED_PYTHON_INSTALL_DIR}" \\' in sync_body
    assert '"${UV_BIN}" sync --frozen --no-dev --python "${PYTHON_REQUEST}" --managed-python' in sync_body
    assert '"${UV_BIN}" sync --frozen --no-dev --python "${PYTHON_REQUEST}" --no-managed-python --no-python-downloads' in sync_body
    assert sync_body.index("normalize_managed_python_install_permissions") < sync_body.index(
        "normalize_release_tree_permissions"
    )


def test_safe_find_chmod_normalization_skips_symlink_targets_outside_root(tmp_path: Path) -> None:
    normalization_root = tmp_path / "normalization-root"
    normalization_root.mkdir()
    inside_file = normalization_root / "inside-file.txt"
    inside_dir = normalization_root / "inside-dir"
    outside_file = tmp_path / "outside-file.txt"
    outside_dir = tmp_path / "outside-dir"
    link_to_outside_file = normalization_root / "outside-file-link"
    link_to_outside_dir = normalization_root / "outside-dir-link"

    inside_file.write_text("inside\n", encoding="utf-8")
    inside_dir.mkdir()
    outside_file.write_text("outside\n", encoding="utf-8")
    outside_dir.mkdir()
    link_to_outside_file.symlink_to(outside_file)
    link_to_outside_dir.symlink_to(outside_dir, target_is_directory=True)

    os.chmod(normalization_root, 0o775)
    os.chmod(inside_file, 0o664)
    os.chmod(inside_dir, 0o775)
    os.chmod(outside_file, 0o664)
    os.chmod(outside_dir, 0o775)

    outside_file_mode_before = outside_file.stat().st_mode & 0o777
    outside_dir_mode_before = outside_dir.stat().st_mode & 0o777

    _ = run_command(
        "find",
        "-P",
        str(normalization_root),
        "(",
        "-type",
        "d",
        "-o",
        "-type",
        "f",
        ")",
        "-exec",
        "chmod",
        "g-w",
        "{}",
        "+",
    )

    assert (normalization_root.stat().st_mode & 0o777) == 0o755
    assert (inside_file.stat().st_mode & 0o777) == 0o644
    assert (inside_dir.stat().st_mode & 0o777) == 0o755
    assert (outside_file.stat().st_mode & 0o777) == outside_file_mode_before
    assert (outside_dir.stat().st_mode & 0o777) == outside_dir_mode_before
    assert link_to_outside_file.is_symlink()
    assert link_to_outside_dir.is_symlink()


def test_rendered_systemd_unit_has_required_directives() -> None:
    assert TEMPLATE_PATH.exists()

    render_env = {
        "KT_NATIVE_CURRENT_LINK": "/srv/kt-demo-alarm/current",
        "KT_NATIVE_SHARED_DIR": "/srv/kt-demo-alarm/shared",
        "KT_NATIVE_ENV_FILE": "/srv/kt-demo-alarm/shared/.env",
        "KT_NATIVE_PORT": "18000",
        "KT_NATIVE_SERVICE_USER": "demo-user",
        "KT_NATIVE_SERVICE_GROUP": "demo-group",
    }

    result = run_command("bash", str(SCRIPT_DIR / "render-systemd-unit.sh"), env=render_env)
    unit = result.stdout

    assert "__" not in unit
    assert "Type=exec" in unit
    assert "User=demo-user" in unit
    assert "Group=demo-group" in unit
    assert "WorkingDirectory=/srv/kt-demo-alarm/current" in unit
    assert "EnvironmentFile=/srv/kt-demo-alarm/shared/.env" in unit
    assert (
        "ExecStart=/srv/kt-demo-alarm/current/.venv/bin/python -m uvicorn main:app --host ${APP_BIND_HOST} --port ${APP_PORT}"
        in unit
    )
    assert "/.venv/bin/uvicorn main:app" not in unit
    assert "uv run --no-sync --no-dev" not in unit
    assert "Restart=on-failure" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/srv/kt-demo-alarm/shared" in unit


def test_systemd_analyze_can_verify_a_valid_service_filename(tmp_path: Path) -> None:
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is required for unit verification")

    unit_path = tmp_path / "kt-demo-alarm.candidate.service"
    unit_path.write_text(
        "\n".join(
            [
                "[Unit]",
                "Description=KT Demo Alarm verification fixture",
                "[Service]",
                "Type=oneshot",
                "ExecStart=/bin/true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    _ = run_command("systemd-analyze", "verify", str(unit_path))


def test_native_preflight_scripts_are_syntax_valid_and_non_mutating_by_default() -> None:
    scripts = sorted(SCRIPT_DIR.glob("*.sh"))
    assert {script.name for script in scripts} == {
        "native-defaults.sh",
        "preflight.sh",
        "render-systemd-unit.sh",
        "setup-runtime.sh",
    }

    _ = run_command("bash", "-n", *[str(script) for script in scripts])
    _ = run_command(
        "bash",
        "-n",
        *[str(script) for script in (REPO_ROOT / "deploy" / "native").glob("*.sh")],
    )

    combined = "\n".join(script.read_text(encoding="utf-8") for script in scripts)
    assert "sudo" not in combined
    assert "systemctl start" not in combined
    assert "systemctl stop" not in combined
    assert "systemctl restart" not in combined
    assert "docker compose down" not in combined
    assert "docker compose up" not in combined


def test_preflight_reports_conflicts_without_service_mutation() -> None:
    preflight_text = uncommented_text(SCRIPT_DIR / "preflight.sh")

    assert "connect_ex" in preflight_text
    assert "[[ ! -w \"${required_dir}\" ]]" in preflight_text
    assert re.search(
        r'^\s*if docker compose ps --status running --services 2>/dev/null \| grep -qx "\$\{KT_NATIVE_SERVICE_NAME\}"; then$',
        preflight_text,
        re.MULTILINE,
    )
    assert re.search(
        r'^\s*if systemctl is-active --quiet "\$\{KT_NATIVE_SERVICE_NAME\}" 2>/dev/null; then$',
        preflight_text,
        re.MULTILINE,
    )
    assert re.search(
        r'''^\s*"\$\{KT_NATIVE_UV_BIN\}" run --no-sync --no-dev python - <<'PY'$''',
        preflight_text,
        re.MULTILINE,
    )
    assert "systemctl start" not in preflight_text
    assert "systemctl stop" not in preflight_text
    assert "systemctl restart" not in preflight_text
    assert "docker compose down" not in preflight_text
    assert "docker compose up" not in preflight_text


def test_setup_runtime_contains_required_uv_and_playwright_paths() -> None:
    setup_text = uncommented_text(SCRIPT_DIR / "setup-runtime.sh")

    assert re.search(
        r'^\s*"\$\{KT_NATIVE_UV_BIN\}" sync --frozen --no-dev --python "\$\{KT_NATIVE_PYTHON_BIN\}" --no-managed-python --no-python-downloads$',
        setup_text,
        re.MULTILINE,
    )
    assert re.search(
        r'^\s*"\$\{KT_NATIVE_UV_BIN\}" run --no-dev playwright install chromium --with-deps$',
        setup_text,
        re.MULTILINE,
    )
    assert re.search(
        r'^\s*"\$\{KT_NATIVE_UV_BIN\}" run --no-dev playwright install chromium$',
        setup_text,
        re.MULTILINE,
    )
    assert re.search(r'^\s*\[\[ -x \.venv/bin/uvicorn \]\] \|\| native_fail ', setup_text, re.MULTILINE)
    assert "may also install supported OS dependencies" in setup_text


def test_uv_sync_uses_requested_system_python_for_project_venv(tmp_path: Path) -> None:
    uv_bin = shutil.which("uv")
    assert uv_bin is not None

    project_dir = tmp_path / "uv-system-python-check"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "uv-system-python-check"',
                'version = "0.0.0"',
                'requires-python = ">=3.12"',
                "dependencies = []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    requested_python = _compatible_python_or_skip("python3.12", "python3")

    _ = run_command(
        uv_bin,
        "lock",
        "--python",
        str(requested_python),
        "--no-managed-python",
        "--no-python-downloads",
        cwd=project_dir,
    )
    _ = run_command(
        uv_bin,
        "sync",
        "--frozen",
        "--no-dev",
        "--python",
        str(requested_python),
        "--no-managed-python",
        "--no-python-downloads",
        cwd=project_dir,
    )

    venv_python = project_dir / ".venv" / "bin" / "python"
    assert venv_python.exists()

    inspect = run_command(
        str(venv_python),
        "-c",
        (
            "import json, pathlib, sys; "
            "print(json.dumps({"
            "'executable': str(pathlib.Path(sys.executable).resolve()), "
            "'base_executable': str(pathlib.Path(getattr(sys, '_base_executable', sys.executable)).resolve()), "
            "'prefix': str(pathlib.Path(sys.prefix).resolve())"
            "}))"
        ),
        cwd=project_dir,
    )
    runtime_info = json.loads(inspect.stdout)
    assert Path(runtime_info["prefix"]) == (project_dir / ".venv").resolve()
    assert Path(runtime_info["base_executable"]) == requested_python


def test_uv_sync_can_use_custom_managed_python_install_dir_for_project_venv(tmp_path: Path) -> None:
    uv_bin = shutil.which("uv")
    assert uv_bin is not None

    project_dir = tmp_path / "uv-managed-python-check"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "uv-managed-python-check"',
                'version = "0.0.0"',
                'requires-python = ">=3.12"',
                "dependencies = []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    managed_python_root = tmp_path / "shared-python"
    env = {"UV_PYTHON_INSTALL_DIR": str(managed_python_root)}

    _ = run_command(
        uv_bin,
        "lock",
        "--python",
        "3.12",
        "--managed-python",
        cwd=project_dir,
        env=env,
    )
    _ = run_command(
        uv_bin,
        "sync",
        "--frozen",
        "--no-dev",
        "--python",
        "3.12",
        "--managed-python",
        cwd=project_dir,
        env=env,
    )

    venv_python = project_dir / ".venv" / "bin" / "python"
    assert venv_python.exists()

    inspect = run_command(
        str(venv_python),
        "-c",
        (
            "import json, pathlib, sys; "
            "print(json.dumps({"
            "'executable': str(pathlib.Path(sys.executable).resolve()), "
            "'base_executable': str(pathlib.Path(getattr(sys, '_base_executable', sys.executable)).resolve()), "
            "'prefix': str(pathlib.Path(sys.prefix).resolve())"
            "}))"
        ),
        cwd=project_dir,
    )
    runtime_info = json.loads(inspect.stdout)
    base_executable = Path(runtime_info["base_executable"])
    assert Path(runtime_info["prefix"]) == (project_dir / ".venv").resolve()
    assert managed_python_root.exists()
    assert base_executable.is_relative_to(managed_python_root.resolve())
    assert base_executable.is_relative_to(Path.home() / ".local" / "share" / "uv" / "python") is False


def test_deploy_release_preflight_prefers_python312_candidate_when_default_python3_fails(
    tmp_path: Path,
) -> None:
    compatible_python = _compatible_python_or_skip("python3.12", "python3", require_non_home=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    fake_python3 = fake_bin / "python3"
    fake_python3.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_python3.chmod(0o755)
    (fake_bin / "python3.12").symlink_to(compatible_python)
    for helper in ("bash", "date", "dirname", "id"):
        helper_path = shutil.which(helper)
        assert helper_path is not None
        (fake_bin / helper).symlink_to(Path(helper_path).resolve())

    script_copy = tmp_path / "deploy-release-preflight.sh"
    script_copy.write_text(
        DEPLOY_SCRIPT.read_text(encoding="utf-8").replace(
            'main "$@"',
            'preflight_python\nprintf "selected=%s\\nrequest=%s\\n" "${PYTHON_BIN}" "${PYTHON_REQUEST}"',
        ),
        encoding="utf-8",
    )
    script_copy.chmod(0o755)

    env = {name: value for name, value in os.environ.items() if name != "HOME"}
    env["PATH"] = str(fake_bin)
    result = subprocess.run(
        ("bash", str(script_copy)),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    assert "Using compatible system Python candidate python3.12 instead of default python3" in result.stdout
    assert f"Using system Python binary {fake_bin / 'python3.12'}" in result.stdout
    assert f"selected={fake_bin / 'python3.12'}" in result.stdout
    assert f"request={fake_bin / 'python3.12'}" in result.stdout


def test_deploy_release_preflight_falls_back_to_shared_managed_python_when_no_system_candidate(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    fake_python3 = fake_bin / "python3"
    fake_python3.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_python3.chmod(0o755)
    for helper in ("bash", "date", "dirname", "id"):
        helper_path = shutil.which(helper)
        assert helper_path is not None
        (fake_bin / helper).symlink_to(Path(helper_path).resolve())

    script_copy = tmp_path / "deploy-release-preflight-managed.sh"
    script_copy.write_text(
        DEPLOY_SCRIPT.read_text(encoding="utf-8").replace(
            'main "$@"',
            (
                'preflight_python\n'
                'printf "mode=%s\\nrequest=%s\\ndir=%s\\n" '
                '"${PYTHON_MODE}" "${PYTHON_REQUEST}" "${MANAGED_PYTHON_INSTALL_DIR}"'
            ),
        ),
        encoding="utf-8",
    )
    script_copy.chmod(0o755)

    shared_dir = tmp_path / "shared"
    result = run_command(
        "bash",
        str(script_copy),
        env={
            "PATH": str(fake_bin),
            "HOME": str(tmp_path / "home"),
            "SHARED_DIR": str(shared_dir),
        },
    )

    assert f"Falling back to uv-managed Python 3.12 under {shared_dir / 'uv' / 'python'}" in result.stdout
    assert "mode=managed" in result.stdout
    assert "request=3.12" in result.stdout
    assert f"dir={shared_dir / 'uv' / 'python'}" in result.stdout


def test_active_native_docs_retire_advisory_lane() -> None:
    docs_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (NATIVE_GUIDE_PATH, RUNBOOK_PATH, NATIVE_ASSET_README_PATH)
    )

    assert "template-only-advisory-v1" not in docs_text
    assert "advisory-template-regression" not in docs_text
    assert "scripts/ci/advisory_contract.py" not in docs_text
    assert "uv run pytest -q" in docs_text


def test_repo_does_not_track_omx_runtime_state() -> None:
    tracked_omx = run_command("git", "ls-files", ".omx").stdout.splitlines()
    gitignore_text = GITIGNORE_PATH.read_text(encoding="utf-8")

    assert tracked_omx == []
    assert re.search(r"(?m)^\.omx/$", gitignore_text)
    assert not ADVISORY_CONTRACT_SCRIPT.exists()


def test_preflight_can_run_in_non_mutating_test_mode(tmp_path: Path) -> None:
    uv_bin = shutil.which("uv")
    assert uv_bin is not None

    shared_dir = tmp_path / "shared"
    runtime_dirs = {
        "KT_NATIVE_APP_ROOT": str(tmp_path / "app-root"),
        "KT_NATIVE_SHARED_DIR": str(shared_dir),
        "KT_NATIVE_DATA_DIR": str(shared_dir / "data"),
        "KT_NATIVE_LOG_DIR": str(shared_dir / "logs"),
        "KT_NATIVE_CACHE_DIR": str(shared_dir / "topis_cache"),
        "KT_NATIVE_ATTACHMENT_DIR": str(shared_dir / "topis_attachments"),
        "KT_NATIVE_PLAYWRIGHT_BROWSERS_PATH": str(shared_dir / "ms-playwright"),
        "KT_NATIVE_PYTHON_BIN": sys.executable,
        "KT_NATIVE_UV_BIN": uv_bin,
    }
    for path in runtime_dirs.values():
        if path in {sys.executable, uv_bin}:
            continue
        Path(path).mkdir(parents=True, exist_ok=True)

    _ = run_command(
        "bash",
        str(SCRIPT_DIR / "preflight.sh"),
        "--skip-port-check",
        env=runtime_dirs,
    )


def test_healthcheck_bounds_each_curl_attempt_to_remaining_deadline() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.2)
    port = listener.getsockname()[1]

    stop_event = threading.Event()
    accepted_connections: list[socket.socket] = []

    def serve() -> None:
        try:
            while not stop_event.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                accepted_connections.append(connection)
        finally:
            for connection in accepted_connections:
                connection.close()
            listener.close()

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()

    try:
        start = time.monotonic()
        result = run_command(
            "bash",
            str(HEALTHCHECK_SCRIPT),
            env={
                "HEALTH_URL": f"http://127.0.0.1:{port}/",
                "HEALTH_TIMEOUT_SECONDS": "2",
                "HEALTH_INTERVAL_SECONDS": "1",
            },
            check=False,
        )
        elapsed = time.monotonic() - start
    finally:
        stop_event.set()
        server_thread.join(timeout=1)

    assert result.returncode == 1
    assert elapsed < 6
    assert f"Local health check failed within 2s: http://127.0.0.1:{port}/" in result.stderr


def test_required_docs_are_not_gitignored() -> None:
    docs = [
        "docs/native-linux-deploy-guide.md",
        "docs/docker-free-fastapi-deploy-runbook.md",
        "legacy/docker-deploy/README.md",
        "legacy/bootstrap/README.md",
    ]

    result = subprocess.run(
        ["git", "check-ignore", *docs],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr


def test_legacy_docker_inventory_is_preserved_outside_root_active_path() -> None:
    assert LEGACY_DOCKER_DIR.exists()
    assert (LEGACY_DOCKER_DIR / "README.md").exists()
    assert (LEGACY_DOCKER_DIR / "Dockerfile").exists()
    assert (LEGACY_DOCKER_DIR / "docker-compose.yml").exists()
    assert (LEGACY_DOCKER_DIR / ".dockerignore").exists()

    assert not (REPO_ROOT / "Dockerfile").exists()
    assert not (REPO_ROOT / "docker-compose.yml").exists()
    assert not (REPO_ROOT / ".dockerignore").exists()

    legacy_notice = (LEGACY_DOCKER_DIR / "README.md").read_text(encoding="utf-8")
    assert "inactive" in legacy_notice
    assert "new PRD" in legacy_notice
    assert "explicit operator approval" in legacy_notice


def test_root_operator_surfaces_redirect_to_native_path_and_mark_legacy_bootstrap() -> None:
    readme_text = ROOT_README_PATH.read_text(encoding="utf-8")
    bootstrap_readme_text = LEGACY_BOOTSTRAP_README.read_text(encoding="utf-8")
    setup_script_text = SETUP_EC2_SCRIPT.read_text(encoding="utf-8")
    _ = run_command("bash", "-n", str(SETUP_EC2_SCRIPT))

    assert "docs/native-linux-deploy-guide.md" in readme_text
    assert "legacy/docker-deploy/" in readme_text
    assert "scripts/setup-ec2.sh" in readme_text

    assert "legacy Docker bootstrap" in bootstrap_readme_text
    assert "docs/native-linux-deploy-guide.md" in bootstrap_readme_text
    assert "scripts/setup-ec2.sh" in bootstrap_readme_text

    assert "legacy Docker bootstrap" in setup_script_text
    assert "docs/native-linux-deploy-guide.md" in setup_script_text
