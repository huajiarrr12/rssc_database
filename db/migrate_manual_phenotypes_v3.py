#!/usr/bin/env python3
"""Idempotently add per-host sample-size columns to manual_phenotypes."""
import argparse
import sqlite3
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parent / "strain_db_v3.sqlite"
REQUIRED_COLUMNS = {
    "n_inoculated": "INTEGER",
    "n_responded": "INTEGER",
}


def migrate_manual_phenotypes(conn):
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_phenotypes'"
    ).fetchone()
    if not table_exists:
        raise RuntimeError("manual_phenotypes table does not exist.")

    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(manual_phenotypes)")
    }
    added = []
    try:
        for name, definition in REQUIRED_COLUMNS.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE manual_phenotypes ADD COLUMN {name} {definition}"
                )
                added.append(name)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mp_trait_host "
            "ON manual_phenotypes(trait, host_species, host_cultivar)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite database path (default: {DEFAULT_DB})",
    )
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    try:
        added = migrate_manual_phenotypes(conn)
    finally:
        conn.close()
    print(
        f"manual_phenotypes migration complete for {args.db}: "
        f"{', '.join(added) if added else 'already current'}"
    )


if __name__ == "__main__":
    main()
