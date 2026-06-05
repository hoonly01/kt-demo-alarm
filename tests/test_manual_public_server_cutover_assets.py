import os
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANUAL_CUTOVER_SCRIPT = REPO_ROOT / "scripts" / "manual" / "public-server-cutover.sh"
NATIVE_DEFAULTS_SCRIPT = REPO_ROOT / "scripts" / "native" / "native-defaults.sh"
PACKAGE_SCRIPT = REPO_ROOT / "deploy" / "native" / "package-source-bundle.sh"
VERIFY_SCRIPT = REPO_ROOT / "deploy" / "native" / "verify-source-bundle.sh"
MANUAL_GUIDE = REPO_ROOT / "docs" / "manual-public-server-cutover-guide.md"
NATIVE_GUIDE = REPO_ROOT / "docs" / "native-linux-deploy-guide.md"


def run_command(
    *args: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env is not None:
        merged_env.update(env)

    return subprocess.run(
        args,
        cwd=cwd or REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
        env=merged_env,
    )


def _build_prepare_artifact_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"

    (repo / "app").mkdir(parents=True)
    (repo / "deploy" / "native").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "scripts" / "manual").mkdir(parents=True)
    (repo / "scripts" / "native").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)

    shutil.copy2(MANUAL_CUTOVER_SCRIPT, repo / "scripts" / "manual" / "public-server-cutover.sh")
    shutil.copy2(NATIVE_DEFAULTS_SCRIPT, repo / "scripts" / "native" / "native-defaults.sh")
    shutil.copy2(PACKAGE_SCRIPT, repo / "deploy" / "native" / "package-source-bundle.sh")
    shutil.copy2(VERIFY_SCRIPT, repo / "deploy" / "native" / "verify-source-bundle.sh")

    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "main.py").write_text("app = None\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'tmp-manual-cutover'\nversion = '0.0.0'\nrequires-python = '>=3.12'\n",
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (repo / ".python-version").write_text("3.12\n", encoding="utf-8")
    (repo / "docs" / "native-linux-deploy-guide.md").write_text("# Native Guide\n", encoding="utf-8")
    (repo / "docs" / "docker-free-fastapi-deploy-runbook.md").write_text("# Runbook\n", encoding="utf-8")
    (repo / "tests" / "test_native_runtime_assets.py").write_text(
        "def test_native_assets_placeholder() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_smoke.py").write_text(
        "def test_smoke_placeholder() -> None:\n    assert True\n",
        encoding="utf-8",
    )

    return repo


def _write_shared_state(root: Path, layout: str) -> tuple[Path, Path, Path, Path]:
    if layout == "native-shared":
        base = root / "shared"
    else:
        base = root

    data_file = base / "data" / "kt_demo_alarm.db"
    cache_file = base / "topis_cache" / "topis_cache.json"
    attachment_file = base / "topis_attachments" / "sample.txt"
    log_file = base / "logs" / "app.log"

    data_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    attachment_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    data_file.write_text("db", encoding="utf-8")
    cache_file.write_text("{}", encoding="utf-8")
    attachment_file.write_text("attachment", encoding="utf-8")
    log_file.write_text("log", encoding="utf-8")

    return data_file, cache_file, attachment_file, log_file


def test_manual_public_cutover_help_lists_required_subcommands() -> None:
    result = run_command("bash", str(MANUAL_CUTOVER_SCRIPT), "help")

    for subcommand in (
        "prepare-artifact",
        "detect-source-layout",
        "export-shared-state",
        "preflight-dest",
        "push",
        "restore-shared",
        "deploy",
        "postcheck",
        "followup-checklist",
    ):
        assert subcommand in result.stdout

    assert 'no default "all" or one-shot cutover action' in result.stdout
    assert "\n  all" not in result.stdout


def test_manual_public_cutover_prepare_artifact_creates_bundle_and_checksum(tmp_path: Path) -> None:
    repo = _build_prepare_artifact_repo(tmp_path)
    artifact_dir = tmp_path / "artifact"

    _ = run_command(
        "bash",
        str(repo / "scripts" / "manual" / "public-server-cutover.sh"),
        "prepare-artifact",
        cwd=repo,
        env={
            "ARTIFACT_DIR": str(artifact_dir),
            "PREPARE_ARTIFACT_NATIVE_TEST_CMD": f"{sys.executable} -m pytest tests/test_native_runtime_assets.py -q",
            "PREPARE_ARTIFACT_FULL_TEST_CMD": f"{sys.executable} -m pytest -q",
        },
    )

    bundle_path = artifact_dir / "source-bundle.tar.gz"
    checksum_path = artifact_dir / "source-bundle.sha256"

    assert bundle_path.exists()
    assert checksum_path.exists()

    with tarfile.open(bundle_path, "r:gz") as bundle:
        names = {member.name.removeprefix("./").rstrip("/") for member in bundle.getmembers()}

    assert "bundle-manifest.txt" in names
    assert "app/__init__.py" in names
    assert "deploy/native/package-source-bundle.sh" in names
    assert "deploy/native/verify-source-bundle.sh" in names
    assert "docs/native-linux-deploy-guide.md" in names
    assert "docs/docker-free-fastapi-deploy-runbook.md" in names


@pytest.mark.parametrize("layout", ["native-shared", "legacy-flat"])
def test_manual_public_cutover_shared_state_round_trip_supports_native_and_legacy_layouts(
    tmp_path: Path,
    layout: str,
) -> None:
    src_root = tmp_path / f"{layout}-src"
    dest_root = tmp_path / f"{layout}-dest"
    artifact_dir = tmp_path / f"{layout}-artifact"
    artifact_dir.mkdir()

    expected_files = _write_shared_state(src_root, layout)

    (artifact_dir / "source-bundle.tar.gz").write_text("bundle", encoding="utf-8")
    (artifact_dir / "source-bundle.sha256").write_text("checksum", encoding="utf-8")

    layout_result = run_command(
        "bash",
        str(MANUAL_CUTOVER_SCRIPT),
        "detect-source-layout",
        env={
            "SRC_HOST": "local",
            "SRC_APP_ROOT": str(src_root),
            "ARTIFACT_DIR": str(artifact_dir),
        },
    )
    assert layout_result.stdout.strip() == layout

    _ = run_command(
        "bash",
        str(MANUAL_CUTOVER_SCRIPT),
        "export-shared-state",
        env={
            "SRC_HOST": "local",
            "SRC_APP_ROOT": str(src_root),
            "ARTIFACT_DIR": str(artifact_dir),
        },
    )

    release_id = f"{layout}-20260604TTESTZ"
    _ = run_command(
        "bash",
        str(MANUAL_CUTOVER_SCRIPT),
        "push",
        env={
            "DEST_HOST": "local",
            "DEST_APP_ROOT": str(dest_root),
            "ARTIFACT_DIR": str(artifact_dir),
            "RELEASE_ID": release_id,
        },
    )
    incoming_dir = dest_root / "incoming" / release_id
    assert (incoming_dir / "shared-state.tar.gz").exists()
    (artifact_dir / "shared-state.tar.gz").unlink()

    _ = run_command(
        "bash",
        str(MANUAL_CUTOVER_SCRIPT),
        "restore-shared",
        env={
            "DEST_HOST": "local",
            "DEST_APP_ROOT": str(dest_root),
            "ARTIFACT_DIR": str(artifact_dir),
            "RELEASE_ID": release_id,
        },
    )

    assert (incoming_dir / "source-bundle.tar.gz").exists()
    assert (incoming_dir / "source-bundle.sha256").exists()
    assert (incoming_dir / "shared-state.tar.gz").exists()
    assert (incoming_dir / "deploy-release.sh").exists()
    assert (incoming_dir / "verify-source-bundle.sh").exists()

    restored_files = (
        dest_root / "shared" / "data" / "kt_demo_alarm.db",
        dest_root / "shared" / "topis_cache" / "topis_cache.json",
        dest_root / "shared" / "topis_attachments" / "sample.txt",
        dest_root / "shared" / "logs" / "app.log",
    )
    for source_file, restored_file in zip(expected_files, restored_files, strict=True):
        assert restored_file.read_text(encoding="utf-8") == source_file.read_text(encoding="utf-8")


def test_manual_public_cutover_remote_dry_run_previews_commands(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    (artifact_dir / "source-bundle.tar.gz").write_text("bundle", encoding="utf-8")
    (artifact_dir / "source-bundle.sha256").write_text("checksum", encoding="utf-8")
    (artifact_dir / "shared-state.tar.gz").write_text("shared", encoding="utf-8")

    common_env = {
        "DEST_HOST": "dest.example",
        "DEST_USER": "operator",
        "DEST_APP_ROOT": "/srv/kt-demo-alarm",
        "ARTIFACT_DIR": str(artifact_dir),
        "RELEASE_ID": "20260604TTESTZ",
    }

    push_result = run_command(
        "bash",
        str(MANUAL_CUTOVER_SCRIPT),
        "push",
        "--dry-run",
        env=common_env,
    )
    assert "ssh" in push_result.stdout
    assert "scp" in push_result.stdout
    assert "/srv/kt-demo-alarm/incoming/20260604TTESTZ" in push_result.stdout
    assert "deploy-release.sh" in push_result.stdout
    assert "verify-source-bundle.sh" in push_result.stdout

    preflight_result = run_command(
        "bash",
        str(MANUAL_CUTOVER_SCRIPT),
        "preflight-dest",
        "--dry-run",
        env=common_env,
    )
    assert "systemctl --version" in preflight_result.stdout
    assert "uv --version" in preflight_result.stdout
    assert "docker ps" in preflight_result.stdout
    assert "ss -ltn" in preflight_result.stdout

    deploy_result = run_command(
        "bash",
        str(MANUAL_CUTOVER_SCRIPT),
        "deploy",
        "--dry-run",
        "--allow-docker-cutover",
        "--allow-port-takeover",
        env=common_env,
    )
    assert "ALLOW_DOCKER_CUTOVER=true" in deploy_result.stdout
    assert "ALLOW_PORT_TAKEOVER=true" in deploy_result.stdout
    assert "deploy-release.sh" in deploy_result.stdout

    postcheck_result = run_command(
        "bash",
        str(MANUAL_CUTOVER_SCRIPT),
        "postcheck",
        "--dry-run",
        env=common_env,
    )
    assert "readlink -f" in postcheck_result.stdout
    assert "systemctl status" in postcheck_result.stdout
    assert "curl -fsS http://127.0.0.1:8000/" in postcheck_result.stdout
    assert "journalctl -u" in postcheck_result.stdout


def test_manual_public_cutover_docs_keep_minimal_cutover_and_followup_split() -> None:
    guide_text = MANUAL_GUIDE.read_text(encoding="utf-8")
    native_guide_text = NATIVE_GUIDE.read_text(encoding="utf-8")

    assert "minimal-cutover" in guide_text
    assert "## 8. follow-up checklist" in guide_text
    assert ".env" in guide_text
    assert "전송 금지" in guide_text
    assert "native-live" in guide_text
    assert "legacy/docker-deploy/" in native_guide_text
    assert "scripts/setup-ec2.sh" in native_guide_text
