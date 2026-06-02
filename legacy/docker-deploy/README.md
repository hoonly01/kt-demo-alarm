# Legacy Docker deploy inventory

## Status

`legacy/docker-deploy/` is an inactive historical inventory for the pre-native deploy path.

| Rule | Meaning |
|---|---|
| Inactive legacy asset | active workflow/runtime must not build, load, or start Docker from this directory |
| Audit preservation | the original Docker deploy files remain version-controlled for rollback planning and provenance |
| Reactivation gate | re-enabling any Docker runtime path requires a new PRD and explicit operator approval |

## Included files

- `legacy/docker-deploy/Dockerfile`
- `legacy/docker-deploy/docker-compose.yml`
- `legacy/docker-deploy/.dockerignore`

## Current canonical path

The canonical operator path for this repository is the native deploy flow documented in:

- `docs/native-linux-deploy-guide.md`
- `docs/docker-free-fastapi-deploy-runbook.md`

`legacy/docker-deploy/` exists so historical Docker assets do not influence the active service/deploy path.

