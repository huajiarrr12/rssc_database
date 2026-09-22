#!/usr/bin/env python3
"""
Initialize the Ralstonia strain genomics database.

Usage:
    python init_db.py --schema schema.sql [--db strain_db.sqlite]

Creates the SQLite database from the schema definition.
Safe to re-run: uses IF NOT EXISTS for all tables.
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def init_database(schema_path: str, db_path: str = "strain_db.sqlite") -> None:
    """Create database from SQL schema file."""
    schema_file = Path(schema_path)
    if not schema_file.exists():
        print(f"ERROR: Schema file not found: {schema_path}", file=sys.stderr)
        sys.exit(1)

    schema_sql = schema_file.read_text(encoding="utf-8")

    db_file = Path(db_path)
    is_new = not db_file.exists()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        conn.executescript(schema_sql)
        conn.commit()

        if is_new:
            print(f"Database created: {db_path}")
        else:
            print(f"Database updated: {db_path}")

        # Print summary
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        views = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
        ).fetchall()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

        print(f"\nSchema summary:")
        print(f"  Tables:  {len(tables)}")
        print(f"  Views:   {len(views)}")
        print(f"  Indexes: {len(indexes)}")
        print(f"\nTables: {', '.join(t[0] for t in tables)}")
        print(f"Views:  {', '.join(v[0] for v in views)}")

    except sqlite3.Error as e:
        print(f"ERROR: Database initialization failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


def verify_database(db_path: str) -> None:
    """Run integrity checks on the database."""
    conn = sqlite3.connect(db_path)

    # Check foreign keys
    fk_check = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_check:
        print(f"WARNING: Foreign key violations found: {len(fk_check)}")
        for violation in fk_check:
            print(f"  Table: {violation[0]}, rowid: {violation[1]}, "
                  f"ref: {violation[2]}, fk_index: {violation[3]}")
    else:
        print("Foreign key integrity: OK")

    # Check database integrity
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    print(f"Database integrity: {integrity[0]}")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Initialize the Ralstonia strain genomics database"
    )
    parser.add_argument(
        "--schema", required=True,
        help="Path to schema.sql file"
    )
    parser.add_argument(
        "--db", default="strain_db.sqlite",
        help="Path for the SQLite database file (default: strain_db.sqlite)"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Run integrity checks after initialization"
    )

    args = parser.parse_args()
    init_database(args.schema, args.db)

    if args.verify:
        print()
        verify_database(args.db)