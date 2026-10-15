# Development environment

Recorded 2026-10-15 (milestone M0a, task T-0.1).

| Tool | Version | Notes |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | Git Bash used as the shell |
| Python | 3.12.5 | Design requires 3.11+ |
| git | 2.48.1.windows.1 | |
| Docker | 29.3.1 | Docker Desktop must be running |
| Docker Compose | v5.1.1 | |
| uv | 0.11.18 | Installed but not required; the project uses pip + venv |
| psql | not installed | Not needed: use `docker compose exec db psql ...` |

## Pinned versions (checked 2026-10-15)

- PostgreSQL image `postgres:18.6-bookworm` (latest stable; 19 was beta). PostgreSQL 18 images store data under `/var/lib/postgresql/18/`, so the volume is mounted at `/var/lib/postgresql`.
- Python packages: see `requirements.txt` and `requirements-dev.txt`.

## Notes

- The project folder is inside OneDrive by the owner's choice. `.env` is therefore synced to OneDrive (not to GitHub). The database lives in a named Docker volume, not in this folder. If OneDrive sync ever causes file-lock errors in `.venv`, recreate the virtual environment outside the project folder.
- Ports used: 5432 (PostgreSQL, bound to 127.0.0.1 only), 8000 (API, M9), 8501 (UI, M9).
