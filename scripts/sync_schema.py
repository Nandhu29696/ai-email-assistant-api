"""Bring an existing database up to the current schema, idempotently.

For databases that were created outside Alembic (e.g. UAT, which has no
``alembic_version`` table). Every step checks the live schema first and only
creates what is missing, so it is safe to run repeatedly:

    python -m scripts.sync_schema --dry-run   # show what would change
    python -m scripts.sync_schema --apply     # make the changes

Steps:
  1. create missing tables;
  2. add missing columns (NOT NULL columns get their server default);
  3. add missing indexes / foreign keys / unique constraints the code relies on,
     and drop the obsolete global UNIQUE(message_id) on emails and email_batches;
  4. data fixes: "employee" role -> "client", revoke sessions whose refresh token
     is still stored in plaintext (users sign in again), start existing mailboxes
     from "now" so their old backlog is not auto-replied;
  5. record the Alembic head revision so future ``alembic upgrade head`` works;
  6. verify nothing is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Index, MetaData, Table, inspect, text  # noqa: E402
from sqlalchemy.schema import AddConstraint, CreateColumn, CreateIndex, DropConstraint  # noqa: E402
from sqlalchemy import UniqueConstraint  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  (register all models)


class Plan:
    def __init__(self, apply: bool):
        self.apply = apply
        self.actions: list[str] = []

    def run(self, description: str, statement=None, params: dict | None = None) -> None:
        self.actions.append(description)
        print(("APPLY  " if self.apply else "PLAN   ") + description)
        if self.apply and statement is not None:
            with engine.begin() as conn:
                conn.execute(statement if not isinstance(statement, str) else text(statement), params or {})


def _unique_single_column(insp, table: str, column: str) -> str | None:
    for uc in insp.get_unique_constraints(table):
        if uc.get("column_names") == [column]:
            return uc.get("name")
    for ix in insp.get_indexes(table):
        if ix.get("unique") and ix.get("column_names") == [column]:
            return ix.get("name")
    return None


def _has_index_on(insp, table: str, columns: list[str]) -> bool:
    return any(ix.get("column_names") == columns for ix in insp.get_indexes(table)) or any(
        uc.get("column_names") == columns for uc in insp.get_unique_constraints(table)
    )


def _alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def sync(apply: bool, backup_dir: str | None = None) -> int:
    plan = Plan(apply)
    dialect = engine.dialect
    insp = inspect(engine)
    print(f"Database: {settings.DB_TYPE} at {settings.DB_HOST}/{settings.DB_NAME}  mode={'APPLY' if apply else 'DRY-RUN'}\n")

    # Rollback record of rows the data fixes touch.
    if apply:
        snapshot_dir = backup_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "storage", "schema_sync_backups",
        )
        os.makedirs(snapshot_dir, exist_ok=True)
        with engine.connect() as conn:
            snapshot = {
                "users": [dict(r._mapping) for r in conn.execute(text("SELECT id, role FROM users"))],
                "active_sessions": [r[0] for r in conn.execute(
                    text("SELECT id FROM user_sessions WHERE is_active = :t"), {"t": True})]
                if insp.has_table("user_sessions") else [],
            }
        path = os.path.join(snapshot_dir, f"before_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, default=str, indent=2)
        print(f"Saved rollback snapshot: {os.path.abspath(path)}\n")

    # 1. Missing tables (created with their columns, indexes and FKs)
    for name, table in Base.metadata.tables.items():
        if not insp.has_table(name):
            plan.run(f"create table {name}", None)
            if apply:
                table.create(bind=engine, checkfirst=True)
    insp = inspect(engine)

    # 2. Missing columns
    for name, table in Base.metadata.tables.items():
        if not insp.has_table(name):
            continue
        existing = {c["name"] for c in insp.get_columns(name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = str(CreateColumn(column).compile(dialect=dialect)).strip()
            if not column.nullable and column.server_default is None:
                ddl = ddl.replace(" NOT NULL", "")  # cannot add NOT NULL without a default to a populated table
            plan.run(f"add column {name}.{column.name}", f"ALTER TABLE {name} ADD COLUMN {ddl}")
    insp = inspect(engine)

    # 3a. Uniqueness model: per-mailbox message ids
    for table_name, uq_name in (("emails", "uq_emails_integration_message"),
                                ("email_batches", "uq_email_batches_integration_message")):
        if not insp.has_table(table_name):
            continue
        if not _has_index_on(insp, table_name, ["integration_id", "message_id"]):
            table = Table(table_name, MetaData(), autoload_with=engine)
            plan.run(f"add unique {uq_name} on {table_name}(integration_id, message_id)",
                     AddConstraint(UniqueConstraint(table.c.integration_id, table.c.message_id, name=uq_name)))
        legacy = _unique_single_column(insp, table_name, "message_id")
        if legacy:
            table = Table(table_name, MetaData(), autoload_with=engine)
            plan.run(f"drop obsolete global unique {legacy} on {table_name}(message_id)",
                     DropConstraint(UniqueConstraint(table.c.message_id, name=legacy)))
        insp = inspect(engine)
        if not _has_index_on(insp, table_name, ["message_id"]):
            table = Table(table_name, MetaData(), autoload_with=engine)
            plan.run(f"add index ix_{table_name}_message_id",
                     CreateIndex(Index(f"ix_{table_name}_message_id", table.c.message_id)))
        insp = inspect(engine)
    for column in ("outcome", "priority"):
        if insp.has_table("email_batches") and not _has_index_on(insp, "email_batches", [column]):
            table = Table("email_batches", MetaData(), autoload_with=engine)
            if column in table.c:
                plan.run(f"add index ix_email_batches_{column}",
                         CreateIndex(Index(f"ix_email_batches_{column}", table.c[column])))
    insp = inspect(engine)

    # 4. Data fixes
    with engine.connect() as conn:
        employees = conn.execute(text("SELECT COUNT(*) FROM users WHERE role = 'employee'")).scalar()
        plaintext_sessions = conn.execute(text(
            "SELECT COUNT(*) FROM user_sessions WHERE is_active = :t AND LENGTH(refresh_token) <> 64"
        ), {"t": True}).scalar()
        integration_columns = {c["name"] for c in inspect(engine).get_columns("email_integrations")}
        unstarted_mailboxes = conn.execute(text(
            "SELECT COUNT(*) FROM email_integrations WHERE process_since IS NULL"
        )).scalar() if "process_since" in integration_columns else -1
    if employees:
        plan.run(f"convert {employees} user(s) with role 'employee' to 'client'",
                 "UPDATE users SET role = 'client' WHERE role = 'employee'")
    if plaintext_sessions:
        plan.run(f"revoke {plaintext_sessions} session(s) with plaintext refresh tokens (users sign in again)",
                 "UPDATE user_sessions SET is_active = :f, revoked_at = CURRENT_TIMESTAMP "
                 "WHERE is_active = :t AND LENGTH(refresh_token) <> 64", {"f": False, "t": True})
    if unstarted_mailboxes:
        # Only mail arriving from now on is processed, so existing mailboxes do not
        # auto-reply to their old backlog when the new flow starts.
        plan.run("start processing existing mailboxes from now (old emails are not auto-replied)",
                 "UPDATE email_integrations SET process_since = :now WHERE process_since IS NULL",
                 {"now": datetime.now(timezone.utc).replace(tzinfo=None)})

    # 5. Record the Alembic revision
    head = _alembic_head()
    insp = inspect(engine)
    current = None
    if insp.has_table("alembic_version"):
        with engine.connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if current != head:
        if not insp.has_table("alembic_version"):
            plan.run("create table alembic_version",
                     "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, PRIMARY KEY (version_num))")
        plan.run(f"set alembic_version to {head} (was {current})", None)
        if apply:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM alembic_version"))
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": head})

    # 6. Verify
    if apply:
        insp = inspect(engine)
        problems = [f"missing table {n}" for n in Base.metadata.tables if not insp.has_table(n)]
        for name, table in Base.metadata.tables.items():
            if insp.has_table(name):
                existing = {c["name"] for c in insp.get_columns(name)}
                problems += [f"missing column {name}.{c.name}" for c in table.columns if c.name not in existing]
        print("\nVerification:", "OK — schema matches the code" if not problems else problems)
        return 1 if problems else 0

    print(f"\n{len(plan.actions)} change(s) planned. Re-run with --apply to execute.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.exit(sync(apply=args.apply))
