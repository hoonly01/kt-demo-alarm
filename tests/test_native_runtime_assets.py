import os
import re
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "native-runtime.yml"
SCRIPT_DIR = REPO_ROOT / "scripts" / "native"
SYSTEMD_TEMPLATE = REPO_ROOT / "deploy" / "systemd" / "kt-demo-alarm.service.template"


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


def test_native_workflow_is_manual_preflight_only() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    triggers = workflow["on"]
    assert set(triggers) == {"workflow_dispatch"}
    assert set(workflow["jobs"]) == {"preflight"}

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    forbidden_patterns = [
        r"secrets\.EC2_SSH_KEY",
        r"\bssh\b",
        r"\bscp\b",
        r"docker\s+compose\s+(down|up)",
        r"systemctl\s+(start|stop|restart|reload)",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, workflow_text)


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
        r"docker\s+compose\s+(down|up)",
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


def test_preflight_reports_conflicts_without_stop_start_mutation() -> None:
    preflight_text = (SCRIPT_DIR / "preflight.sh").read_text(encoding="utf-8")

    assert "connect_ex" in preflight_text
    assert "docker compose ps --status running --services" in preflight_text
    assert "systemctl is-active --quiet" in preflight_text
    assert "systemctl start" not in preflight_text
    assert "systemctl stop" not in preflight_text
    assert "docker compose down" not in preflight_text
    assert "docker compose up" not in preflight_text


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
