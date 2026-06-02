import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import TypeAlias, cast

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
PACKAGE_SCRIPT = REPO_ROOT / "deploy" / "native" / "package-source-bundle.sh"
VERIFY_SCRIPT = REPO_ROOT / "deploy" / "native" / "verify-source-bundle.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "native" / "deploy-release.sh"
TEMPLATE_PATH = REPO_ROOT / "deploy" / "native" / "kt-demo-alarm.service.template"
SCRIPT_DIR = REPO_ROOT / "scripts" / "native"
ROOT_README_PATH = REPO_ROOT / "README.md"
LEGACY_DOCKER_DIR = REPO_ROOT / "legacy" / "docker-deploy"
LEGACY_BOOTSTRAP_README = REPO_ROOT / "legacy" / "bootstrap" / "README.md"
SETUP_EC2_SCRIPT = REPO_ROOT / "scripts" / "setup-ec2.sh"
ADVISORY_SCRIPT = REPO_ROOT / "scripts" / "ci" / "advisory_contract.py"
PLANS_DIR = REPO_ROOT / ".omx" / "plans"
ADVISORY_CONTRACT_GLOB = "advisory-contract-docker-free-next-action-*.md"
CONTRACT_ID = "template-only-advisory-v1"
YamlScalar: TypeAlias = str | int | float | bool | None
YamlValue: TypeAlias = YamlScalar | list["YamlValue"] | dict[str, "YamlValue"]
WorkflowJob: TypeAlias = dict[str, YamlValue]
WorkflowJobs: TypeAlias = dict[str, WorkflowJob]
WorkflowDocument: TypeAlias = dict[str, YamlValue]


def run_command(
    *args: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if env is not None:
        env = {**os.environ, **env}

    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )


def advisory_selectors() -> list[str]:
    result = run_command(sys.executable, str(ADVISORY_SCRIPT), "selectors", "--format", "newline")
    selectors = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert len(selectors) == 2
    return selectors


def advisory_contract_path() -> Path:
    matches = sorted(PLANS_DIR.glob(ADVISORY_CONTRACT_GLOB))
    assert len(matches) == 1
    return matches[0]


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


def test_advisory_contract_script_stays_narrow() -> None:
    selectors = advisory_selectors()

    assert len(selectors) == 2
    assert {Path(selector.split("::", maxsplit=1)[0]).name for selector in selectors} == {
        "test_notification_attendees.py",
        "test_notification_templates.py",
    }


def test_advisory_contract_plan_is_repo_tracked() -> None:
    contract_path = advisory_contract_path()
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(contract_path.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_deploy_workflow_matches_guarded_native_graph() -> None:
    jobs = workflow_jobs()

    assert set(jobs) == {
        "blocking-tests",
        "advisory-template-regression",
        "package-native-release",
        "deploy-native-preflight",
        "deploy-native-live",
        "public-health",
    }

    assert normalize_needs(jobs["package-native-release"]["needs"]) == ["blocking-tests"]
    assert normalize_needs(jobs["advisory-template-regression"]["needs"]) == ["blocking-tests"]
    assert set(normalize_needs(jobs["deploy-native-preflight"]["needs"])) == {
        "package-native-release",
        "advisory-template-regression",
    }
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


def test_active_workflow_uses_contract_id_without_raw_selector_duplication() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    active_text = uncommented_workflow_text()
    selectors = advisory_selectors()

    assert CONTRACT_ID in workflow_text
    for selector in selectors:
        assert selector not in workflow_text

    assert "scripts/ci/advisory_contract.py run-blocking-pytest" in active_text
    assert "scripts/ci/advisory_contract.py run-advisory-pytest" in active_text


def test_active_workflow_removes_docker_runtime_and_runner_env_rendering() -> None:
    active_text = uncommented_workflow_text()

    forbidden_patterns = [
        r"docker/setup-buildx-action",
        r"docker/build-push-action",
        r"docker\s+compose\s+(down|up|exec)",
        r"docker\s+load",
        r"gunzip\s+-c\s+.+image",
        r"printf '%s\\n'.+> \.env",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, active_text, flags=re.MULTILINE | re.DOTALL)

    assert "docker-compose.yml .env" not in active_text
    assert "docker-compose.yml" not in active_text


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
        names = sorted(
            (
                member.name[2:] if member.name.startswith("./") else member.name
            ).rstrip("/")
            for member in bundle.getmembers()
            if member.name not in {".", "./"}
        )

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
    deploy_text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "ALLOW_PORT_TAKEOVER" in deploy_text
    assert "ALLOW_DOCKER_CUTOVER" in deploy_text
    assert "verify-source-bundle.sh" in deploy_text
    assert 'sync --frozen --no-dev' in deploy_text
    assert "systemd-analyze" in deploy_text
    assert "No previous current symlink exists; first native deploy rollback is limited." in deploy_text
    assert "Restoring previous current symlink" in deploy_text


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
    assert "ExecStart=/usr/bin/env uv run --no-sync --no-dev uvicorn main:app --host ${APP_BIND_HOST} --port ${APP_PORT}" in unit
    assert "Restart=on-failure" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/srv/kt-demo-alarm/shared" in unit


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
    preflight_text = (SCRIPT_DIR / "preflight.sh").read_text(encoding="utf-8")

    assert "connect_ex" in preflight_text
    assert "[[ ! -w \"${required_dir}\" ]]" in preflight_text
    assert "docker compose ps --status running --services" in preflight_text
    assert "systemctl is-active --quiet" in preflight_text
    assert "systemctl start" not in preflight_text
    assert "systemctl stop" not in preflight_text
    assert "systemctl restart" not in preflight_text
    assert "docker compose down" not in preflight_text
    assert "docker compose up" not in preflight_text


def test_setup_runtime_contains_required_uv_and_playwright_paths() -> None:
    setup_text = (SCRIPT_DIR / "setup-runtime.sh").read_text(encoding="utf-8")

    assert "sync --frozen --no-dev" in setup_text
    assert "playwright install chromium --with-deps" in setup_text
    assert "playwright install chromium" in setup_text
    assert ".venv/bin/uvicorn" in setup_text
    assert "may also install supported OS dependencies" in setup_text


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
