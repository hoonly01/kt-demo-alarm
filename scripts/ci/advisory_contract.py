#!/usr/bin/env python3
"""Advisory contract helpers for the docker-free native deploy first pass."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import cast


REPO_ROOT = Path(__file__).resolve().parents[2]
PLANS_DIR = REPO_ROOT / ".omx" / "plans"
CONTRACT_GLOB = "advisory-contract-docker-free-next-action-*.md"
CONTRACT_ID = "template-only-advisory-v1"
SELECTOR_ROW_PATTERN = re.compile(r"^\|\s*`([^`]+)`\s*\|")


def resolve_contract_path() -> Path:
    matches = sorted(PLANS_DIR.glob(CONTRACT_GLOB))
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one advisory contract matching {CONTRACT_GLOB}, found {len(matches)}"
        )
    return matches[0]


def load_contract_text() -> str:
    contract_path = resolve_contract_path()
    return contract_path.read_text(encoding="utf-8")


def parse_selectors(contract_text: str) -> list[str]:
    selectors: list[str] = []
    in_selector_table = False

    for raw_line in contract_text.splitlines():
        line = raw_line.strip()

        if line == "## Allowed advisory selectors":
            in_selector_table = True
            continue

        if in_selector_table and line.startswith("## "):
            break

        if not in_selector_table:
            continue

        match = SELECTOR_ROW_PATTERN.match(line)
        if match is None:
            continue

        selector = match.group(1)
        if selector == "Selector":
            continue
        selectors.append(selector)

    selectors = [selector for selector in selectors if selector]
    if len(selectors) != 2:
        raise SystemExit(
            f"{CONTRACT_ID} must contain exactly two advisory selectors, found {len(selectors)}"
        )
    if len(set(selectors)) != len(selectors):
        raise SystemExit(f"{CONTRACT_ID} contains duplicate advisory selectors")
    return selectors


def load_contract() -> tuple[Path, list[str]]:
    contract_path = resolve_contract_path()
    contract_text = contract_path.read_text(encoding="utf-8")
    if CONTRACT_ID not in contract_text:
        raise SystemExit(f"{contract_path} does not declare contract id {CONTRACT_ID}")
    return contract_path, parse_selectors(contract_text)


def run_pytest(mode: str, selectors: list[str], pytest_args: list[str]) -> int:
    command = ["uv", "run", "pytest", *pytest_args]
    if mode == "blocking":
        for selector in selectors:
            command.extend(["--deselect", selector])
    elif mode == "advisory":
        command.extend(selectors)
    else:
        raise SystemExit(f"Unsupported pytest mode: {mode}")

    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    return completed.returncode


def advisory_summary(exit_code: int, selectors: list[str], contract_path: Path) -> str:
    lines = [
        f"## Advisory lane — `{CONTRACT_ID}`",
        "",
        f"- Contract path: `{contract_path.relative_to(REPO_ROOT)}`",
        "- Allowed selectors:",
    ]
    lines.extend(f"  - `{selector}`" for selector in selectors)
    lines.append("")

    if exit_code == 0:
        lines.append("- Result: advisory selectors passed.")
    elif exit_code == 1:
        lines.append("- Result: known advisory selector failures remain non-blocking.")
    else:
        lines.append(f"- Result: advisory lane infrastructure error (exit {exit_code}).")

    return "\n".join(lines) + "\n"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    selectors_parser = subparsers.add_parser("selectors", help="Emit advisory selectors")
    _ = selectors_parser.add_argument(
        "--format",
        choices=("newline", "json"),
        default="newline",
        help="Selector output format",
    )

    blocking_parser = subparsers.add_parser(
        "run-blocking-pytest",
        help="Run pytest excluding advisory selectors",
    )
    _ = blocking_parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Additional pytest arguments after --",
    )

    advisory_parser = subparsers.add_parser(
        "run-advisory-pytest",
        help="Run pytest for the advisory selectors only",
    )
    _ = advisory_parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Additional pytest arguments after --",
    )

    summary_parser = subparsers.add_parser(
        "write-summary",
        help="Write a markdown summary for the advisory lane",
    )
    _ = summary_parser.add_argument("--exit-code", type=int, required=True)
    _ = summary_parser.add_argument(
        "--output",
        help="Optional output path. stdout is used when omitted.",
    )

    return parser


def normalize_pytest_args(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    contract_path, selectors = load_contract()
    command = cast(str, args.command)

    if command == "selectors":
        output_format = cast(str, args.format)
        if output_format == "json":
            print(json.dumps({"contractId": CONTRACT_ID, "selectors": selectors}, ensure_ascii=False))
        else:
            print("\n".join(selectors))
        return 0

    if command == "run-blocking-pytest":
        pytest_args = cast(list[str], args.pytest_args)
        return run_pytest("blocking", selectors, normalize_pytest_args(pytest_args))

    if command == "run-advisory-pytest":
        pytest_args = cast(list[str], args.pytest_args)
        return run_pytest("advisory", selectors, normalize_pytest_args(pytest_args))

    if command == "write-summary":
        exit_code = cast(int, args.exit_code)
        output = cast(str | None, args.output)
        content = advisory_summary(exit_code, selectors, contract_path)
        if output:
            write_text(Path(output), content)
        else:
            _ = sys.stdout.write(content)
        return 0

    raise AssertionError(f"Unsupported command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
