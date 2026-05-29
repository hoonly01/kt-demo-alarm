import os
import re
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "native-runtime.yml"
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
SCRIPT_DIR = REPO_ROOT / "scripts" / "native"
SYSTEMD_TEMPLATE = REPO_ROOT / "deploy" / "systemd" / "kt-demo-alarm.service.template"
REMOVED_DOCKER_ASSETS = (
    REPO_ROOT / "Dockerfile",
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / ".dockerignore",
)


def run_command(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    env = kwargs.pop("env", None)
    if env is not None:
        env = {**os.environ, **env}

    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
        env=env,
        **kwargs,
    )


def uncommented_lines(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_native_workflow_is_manual_preflight_only() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    triggers = workflow["on"]
    assert set(triggers) == {"workflow_dispatch"}
    assert set(workflow["jobs"]) == {"preflight"}

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "${{ inputs['app-dir'] }}" in workflow_text
    assert "${{ inputs.app-dir }}" not in workflow_text

    forbidden_patterns = [
        r"secrets\.EC2_SSH_KEY",
        r"\bssh\b",
        r"\bscp\b",
        r"docker\s+compose\s+(down|up)",
        r"systemctl\s+(start|stop|restart|reload)",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, workflow_text)


def test_deploy_workflow_runs_native_ec2_deploy_with_test_and_docker_build_commented() -> None:
    workflow = yaml.load(DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    triggers = workflow["on"]
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]
    assert set(workflow["jobs"]) == {"deploy-native"}
    assert "needs" not in workflow["jobs"]["deploy-native"]

    workflow_text = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    active_workflow_text = uncommented_lines(workflow_text)

    assert "# test:" in workflow_text
    assert "# build-docker:" in workflow_text
    assert "#     - run: uv run pytest" in workflow_text
    assert "#     - uses: docker/setup-buildx-action@v3" in workflow_text
    assert "#     - uses: docker/build-push-action@v5" in workflow_text

    assert "uv run pytest" not in active_workflow_text
    assert "docker" not in active_workflow_text.lower()
    assert "git archive --format=tar.gz" in active_workflow_text
    assert 'ssh "${ssh_options[@]}"' in active_workflow_text
    assert 'scp "${ssh_options[@]}"' in active_workflow_text
    assert "scripts/native/setup-runtime.sh" in active_workflow_text
    assert "scripts/native/preflight.sh --skip-port-check --allow-active-systemd" in active_workflow_text
    assert "sudo systemctl restart" in active_workflow_text
    assert "scripts/native/healthcheck.sh" in active_workflow_text


def test_docker_runtime_assets_are_removed() -> None:
    for path in REMOVED_DOCKER_ASSETS:
        assert not path.exists()

    runtime_paths = [
        REPO_ROOT / "scripts" / "setup-ec2.sh",
        REPO_ROOT / "legacy" / "cloudflare-setup.sh",
        *SCRIPT_DIR.glob("*.sh"),
    ]
    for path in runtime_paths:
        text = path.read_text(encoding="utf-8")
        assert "docker" not in text.lower(), path


def test_native_scripts_are_syntax_valid_and_non_mutating_by_default() -> None:
    scripts = sorted(SCRIPT_DIR.glob("*.sh"))
    assert {script.name for script in scripts} == {
        "healthcheck.sh",
        "native-defaults.sh",
        "preflight.sh",
        "render-systemd-unit.sh",
        "setup-runtime.sh",
    }

    run_command("bash", "-n", *[str(script) for script in scripts])

    combined = "\n".join(script.read_text(encoding="utf-8") for script in scripts)
    forbidden_patterns = [
        r"\bsudo\b",
        r"\bdocker\b",
        r"systemctl\s+(start|stop|restart|reload)",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, combined)


def test_setup_runtime_contains_required_uv_and_playwright_paths() -> None:
    setup_text = (SCRIPT_DIR / "setup-runtime.sh").read_text(encoding="utf-8")

    assert "sync --frozen --no-dev" in setup_text
    assert "playwright install chromium --with-deps" in setup_text
    assert "playwright install chromium" in setup_text
    assert ".venv/bin/uvicorn" in setup_text
    assert "may also install supported OS dependencies" in setup_text


def test_preflight_reports_conflicts_without_stop_start_mutation() -> None:
    preflight_text = (SCRIPT_DIR / "preflight.sh").read_text(encoding="utf-8")

    assert "connect_ex" in preflight_text
    assert "[[ ! -w \"${required_dir}\" ]]" in preflight_text
    assert "systemctl is-active --quiet" in preflight_text
    assert "systemctl start" not in preflight_text
    assert "systemctl stop" not in preflight_text
    assert "docker" not in preflight_text.lower()


def test_rendered_systemd_unit_has_required_directives() -> None:
    assert SYSTEMD_TEMPLATE.exists()

    result = run_command(
        "bash",
        "scripts/native/render-systemd-unit.sh",
        env={
            "KT_NATIVE_APP_DIR": "/srv/kt-demo-alarm",
            "KT_NATIVE_PORT": "18000",
            "KT_NATIVE_SERVICE_USER": "demo-user",
            "KT_NATIVE_SERVICE_GROUP": "demo-group",
        },
    )
    unit = result.stdout

    assert "{{" not in unit
    assert "}}" not in unit
    assert "Type=exec" in unit
    assert "User=demo-user" in unit
    assert "Group=demo-group" in unit
    assert "WorkingDirectory=/srv/kt-demo-alarm" in unit
    assert "EnvironmentFile=" in unit
    assert "ExecStart=/srv/kt-demo-alarm/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 18000" in unit
    assert "Restart=on-failure" in unit
    assert "RestartSec=" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=" in unit


def test_preflight_can_run_in_non_mutating_test_mode(tmp_path: Path) -> None:
    runtime_dirs = {
        "KT_NATIVE_DATA_DIR": str(tmp_path / "data"),
        "KT_NATIVE_LOG_DIR": str(tmp_path / "logs"),
        "KT_NATIVE_CACHE_DIR": str(tmp_path / "topis_cache"),
        "KT_NATIVE_ATTACHMENT_DIR": str(tmp_path / "topis_attachments"),
    }
    for path in runtime_dirs.values():
        Path(path).mkdir(parents=True, exist_ok=True)

    run_command(
        "bash",
        "scripts/native/preflight.sh",
        "--skip-port-check",
        env={
            **runtime_dirs,
        },
    )
