# Backup & Restore

## Overview

`scripts/backup.py` creates atomic snapshots of all data files (`*.db`, `*.json`) under `RIKS_DATA_DIR` (default: `data/`). SQLite databases are backed up using the online backup API — never raw file copy — so backups are safe even while the engine is running. JSON files are validated before writing.

## Running a Backup

```bash
python scripts/backup.py
```

A timestamped snapshot is created at `data/backups/<UTC-timestamp>/`, preserving the original directory structure including tenant subdirectories.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `RIKS_DATA_DIR` | `data` | Root data directory to back up |
| `RIKS_BACKUP_KEEP` | `7` | Number of snapshots to keep (0 = no rotation) |

## Scheduled Backups (cron)

Run backups every 6 hours:

```cron
0 */6 * * * cd /path/to/riks-context-engine && /path/to/venv/bin/python scripts/backup.py >> /var/log/riks-backup.log 2>&1
```

## Integrity Check

Check data health without modifying anything:

```bash
riks doctor
```

- Exit 0: all files OK
- Exit 1: corruption detected — the output includes the path to the latest backup

The same check runs automatically when the MCP server starts. Set `RIKS_SKIP_INTEGRITY_CHECK=1` to bypass it.

## Restoring from Backup

1. Stop the engine / MCP server.
2. Identify the snapshot to restore:
   ```bash
   ls -lt data/backups/
   ```
3. Copy the files back, preserving structure:
   ```bash
   cp -r data/backups/<timestamp>/* data/
   ```
4. Verify:
   ```bash
   riks doctor
   ```
5. Restart the engine.

## How It Works

- **SQLite files**: backed up via `sqlite3.Connection.backup()` — consistent even under concurrent writes. Each backup is verified with `PRAGMA integrity_check`.
- **JSON files**: source is parsed with `json.loads()` first (up to 3 retries), then written to a temp file and atomically moved with `os.replace()`.
- **Retention**: only timestamp-named directories are rotated; other contents of `data/backups/` are left alone.
- **Safety**: `data/backups/` is excluded from subsequent backups to prevent recursive growth.
