# Taiwan Migration Baseline

Date: 2026-08-19

## Repository baseline

- Working branch: `feature/tw-00-10-foundation`
- Starting `dev` SHA: `6a2a1062a2d006f4cd20bb85fd3e390eff92e528`
- Upstream repository: `https://github.com/jvanmelckebeke/fibenchi.git`
- Upstream `main` SHA observed: `41782993a60c0d987c18189517d169b0e466c71d`
- Upstream fork point: `c44c963b608f717a704f34446d940f0ddf406bae`
- Fork-point commit: `Merge pull request #623 from jvanmelckebeke/dev`

## Verification

| Gate | Command | Result |
| --- | --- | --- |
| Backend tests | `backend\\.venv\\Scripts\\python.exe -m pytest` | PASS — 840 passed, 764 warnings, 77.69s |
| Backend Ruff | `backend\\.venv\\Scripts\\python.exe -m ruff check .` | PASS — All checks passed |
| Frontend lint | `frontend\\pnpm run lint` | PASS |
| Frontend build | `frontend\\pnpm run build` | PASS — Vite build completed; one existing chunk-size warning over 600 kB |
| Frontend tests | `frontend\\pnpm run test` | PASS — 7 test files, 50 tests |
| Production image | `docker build -t fibenchi:baseline .` | NOT RUN — Docker is not installed on this machine |

The same Docker limitation prevents running the documented `docker compose exec`
commands. No Taiwan or Shioaji runtime behavior was added for TW-00.

## Environment notes

- `docker`, `podman`, `nerdctl`, `finch`, `colima`, and `act` were not available.
- Backend verification used an isolated `backend\\.venv` created from `backend/requirements-dev.txt`.
- Frontend dependencies were installed from the existing lockfile; no tracked dependency files changed.

