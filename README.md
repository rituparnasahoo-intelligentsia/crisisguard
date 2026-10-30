# CrisisGuard AI - hospital-wide resource coordination (backend, Phases 1-3)

A **fictional-data prototype** of a human-supervised hospital emergency coordination flow:
an AI *proposes* resource assignments, deterministic Python *validates* them, a human
*reviews* them, and only then are changes committed to PostgreSQL.

> **Not a medical device.** Simulated data only. Not clinically validated; must not be used in
> a real hospital or with real patient or staff data. Clinical policy and ICU placement rules
> in this repo are **demo placeholders** that real deployments would need qualified clinicians to define.

## Status

| Phase | Content | State |
|---|---|---|
| 1 | Audit of the nurse-only project | Done |
| 2 | Hospital-wide entity design | Done: `docs/erd.md` |
| 3 | Migrations, Docker, fictional seed data | Done and tested (below) |
| 4+ | State retrieval, multi-resource validator and approval, AI agents, API, simulator, React | Not built yet |

The original **nurse-only workflow still works** (`validator.py`, `approval.py`, all original
tests). It will be replaced by the bundle workflow in later phases.

Test status when this was packaged: **51 passed** (28 original + 23 schema tests) against a
throwaway PostgreSQL 16 server. The Docker Compose file and the Windows commands below have
not been run by the author of this package; confirm them on your machine.

---

## 1. Quick start (Windows PowerShell, Python 3.12, Docker Desktop)

```powershell
# 1. Virtual environment and dependencies
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt

# 2. Local config (then open .env and change the password in BOTH places)
Copy-Item .env.example .env

# 3. Start PostgreSQL and wait until it says (healthy)
docker compose up -d
docker compose ps

# 4. Create the separate TEST database (used only by pytest)
docker compose exec db psql -U crisisguard -d crisisguard -c "CREATE DATABASE crisisguard_test;"

# 5. Create/upgrade the tables and insert the fictional data
python -m scripts.init_db

# 6. Verify
pytest
```

Expected output of step 5 on a fresh database: `Applied migrations: 001_nurse_only_baseline.sql,
002_hospital_wide.sql`, then row counts: hospitals 2, wards 6, beds 25, nurses 6, doctors 6,
equipment_units 8, patients 3, incidents 2, and 0 for proposals, allocations and audit logs.
Running it again prints `none (already up to date)` and changes nothing.

### Upgrading a database from the earlier nurse-only version

1. **Back it up first** (the upgrade alters existing tables):
   ```powershell
   docker compose exec db pg_dump -U crisisguard crisisguard > backup_before_upgrade.sql
   ```
2. Replace the project files, then run `python -m scripts.init_db`.
3. Existing nurses move into hospital `H01` with shift `day`; existing proposals, approvals and
   audit rows are kept unchanged and the old workflow keeps working.

### Inspecting the data

```powershell
docker compose exec db psql -U crisisguard -d crisisguard
```
Inside `psql`: `\dt` (tables), `\d beds` (describe), `\q` (quit), and for example:

```sql
SELECT hospital_id, name, operational_status, max_concurrent_patients FROM hospitals;
SELECT ward_id, ward_type, capacity FROM wards ORDER BY ward_id;
SELECT status, count(*) FROM beds GROUP BY status;
SELECT unit_id, status FROM equipment_units WHERE status <> 'available';
SELECT version, applied_at FROM schema_migrations ORDER BY version;
```

### Docker commands

| Goal | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop (data kept) | `docker compose down` |
| Status / health | `docker compose ps` |
| Logs | `docker compose logs db` |
| **Delete all data** (removes the volume) | `docker compose down -v` - **destructive and permanent; only if you truly want a blank database** |

## 2. Container, volume, schema, seed, runtime inserts: what is what

| Concept | What it is | Where it comes from |
|---|---|---|
| Container | The running PostgreSQL program | `docker compose up` |
| Persistent volume | Disk storage holding the database files; survives container restarts | Named volume in `docker-compose.yml` |
| Schema | Tables, constraints, indexes | Migration files, applied by `python -m scripts.migrate` / `init_db` |
| Seed data | The initial fictional demo records | `backend/seed.sql` (safe to re-run, never overwrites) |
| Runtime inserts | New patients, resources and proposals during operation | API endpoints (later phase), never hand-written SQL |

## 3. Changing the schema safely

1. **Never edit** an applied migration. The runner stores a checksum and refuses to continue if an applied file changed.
2. Add the next numbered file, for example `backend/migrations/003_add_something.sql`. Write changes as `ALTER TABLE ...` (migrations are applied once, in order, each in its own transaction).
3. Back up with `pg_dump`, run `python -m scripts.init_db`, then `pytest`.
4. For a deliberate wipe of demo data (structure kept): `python -m scripts.reset_demo` (shows counts, requires typing `RESET`).

## 4. Project layout

```
backend/
  migrations/       001_nurse_only_baseline.sql, 002_hospital_wide.sql
  seed.sql          fictional demo data
  schemas.py, database.py, hospital_state.py, validator.py, approval.py, evaluation.py   (nurse-only workflow, still working)
scripts/            migrate.py, init_db.py, reset_demo.py, db_tools.py
tests/              test_validator.py, test_approval.py, test_scenarios.py, test_schema.py
docs/erd.md         entity relationship diagram and rule table
docker-compose.yml, .env.example, .gitignore, pytest.ini, requirements.txt
```

## 5. Tests

- **Unit tests** need no database. **Integration tests** (marked `integration`) use `TEST_DATABASE_URL`, apply the real migrations, then empty and re-seed every table before each test. They refuse to run unless the database name ends in `_test` and differs from `DATABASE_URL`. Without PostgreSQL they are skipped.
- `tests/test_schema.py` proves the database itself rejects invalid states: cross-hospital resources, over-capacity wards, double-booked beds and equipment, one active allocation per patient, malformed allocation items, non-fictional patients, and edits to audit rows. It also covers migration repeatability and detection of edited migrations.

## 6. Open decisions for you and your teammates

1. The design here uses my recommended choices: two hospitals, individually tracked equipment units, one allocation bundle per patient, per-row versions, JWT roles (administrator, reviewer) in a later phase. Confirm or change them before Phase 4.
2. `schemas.py` is shared with Persons A and C and will change substantially from Phase 5 onward.
3. `policy_settings` holds **demo placeholder** values (including the ICU rule). Real values need qualified clinical input.
4. The API database role should later be restricted (no `TRUNCATE`) so audit protection is complete.
