# Legacy bootstrap inventory

## Status

`scripts/setup-ec2.sh` is preserved as a legacy Docker bootstrap helper.

| Rule | Meaning |
|---|---|
| Not canonical | the active deploy path is the native workflow, not this script |
| Historical scope | the script still installs/configures Docker-era prerequisites for audit/reference purposes |
| Rewrite deferred | bootstrap redesign/relocation remains a follow-up task, not part of the first native pass |

## Operator note

Before using `scripts/setup-ec2.sh`, confirm that you intentionally need the legacy Docker bootstrap path.
The legacy Docker rules (inactive status, reactivation gate) are documented in
[`../docker-deploy/README.md`](../docker-deploy/README.md).

For the current canonical flow, use:

- `docs/native-linux-deploy-guide.md`
- `docs/deploy-runbook.md`

