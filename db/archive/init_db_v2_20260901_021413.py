#!/usr/bin/env python3
"""
Build strain_db_v2.sqlite from output/ TSV files.

Usage:
    python init_db_v2.py
    python init_db_v2.py --db /custom/path.sqlite
    python init_db_v2.py --verify-only  # just run QC on existing db

Deleting strain_db_v2.sqlite and re-running reproduces the same database.
"""

import argparse
import csv
import os
import sqlite3
import sys
from pathlib import Path

# ── Source paths (relative to PROJECT_ROOT) ─────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # /data/wry/RSSC_DATABASE
OUTPUT = PROJECT_ROOT / "output"

SCHEMA_FILE = Path(__file__).resolve().parent / "schema_v2.sql"
DEFAULT_DB = Path(__file__).resolve().parent / "strain_db_v2.sqlite"

SOURCES = {
    "samples":                       OUTPUT / "analysis_sample_manifest.tsv",
    "sample_metadata":               OUTPUT / "master_metadata.tsv",
    "genome_qc":                     OUTPUT / "genome_qc_summary.tsv",
    "genome_qc_classification":      OUTPUT / "genome_qc_classification.tsv",
    "literature_metadata_candidates": OUTPUT / "literature_metadata_candidates.tsv",
    "isolate_typing":                OUTPUT / "isolate_typing_candidates.tsv",
    "phenotypes":                    OUTPUT / "phenotype_candidates_long.tsv",
    "bioprojects":                   OUTPUT / "projects_for_literature_search.tsv",
    "publications":                  OUTPUT / "bioproject_publications.tsv",
    "manual_literature_review":      OUTPUT / "manual_literature_review.tsv",
    "sample_fasta_map":              OUTPUT / "sample_fasta_map.tsv",
    "genome_rescue_candidates":      OUTPUT / "genome_rescue_candidates.tsv",
    "genome_rescue_read_audit":      OUTPUT / "genome_rescue_read_audit.tsv",
    "genome_rescue_read_plan":       OUTPUT / "genome_rescue_read_plan.tsv",
}

# Column rename map for bioprojects (TSV header -> DB column)
BIOPROJECTS_RENAME = {
    "bioproject": "bioproject_accession",
    "number_of_assemblies": "n_samples",
    "number_of_unique_biosamples": "n_unique_biosamples",
    "number_of_unique_strains": "n_unique_strains",
    "number_of_isolates": "n_isolates",
}

# Tables where sample_id is PK (one row per sample)
SAMPLE_PK_TABLES = {
    "samples", "sample_metadata", "genome_qc",
    "genome_qc_classification", "sample_fasta_map",
    "genome_rescue_candidates",
}

# Tables with sample_id FK (check orphans)
SAMPLE_FK_TABLES = {
    "literature_metadata_candidates", "isolate_typing",
    "phenotypes", "genome_rescue_read_audit", "genome_rescue_read_plan",
}

# Tables with bioproject FK (check orphans)
BIOPROJECT_FK_TABLES = {"publications", "manual_literature_review"}


def read_tsv(path):
    """Read TSV, return (header_list, rows_as_dicts)."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
    return list(rows[0].keys()) if rows else [], rows


def get_db_columns(conn, table):
    """Return ordered list of column names for a table (excluding autoincrement row_id)."""
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols = []
    for row in info:
        name = row[1]
        pk = row[5]
        col_type = row[2]
        if name == "row_id" and pk == 1:
            continue
        cols.append(name)
    return cols


def import_table(conn, table, tsv_path, sample_ids=None,
                 bioproject_ids=None, rename_map=None,
                 filter_fn=None):
    """Import one TSV into a table with validation."""
    print(f"\n{'='*60}")
    print(f"Importing: {table}")
    print(f"Source:    {tsv_path}")

    if not tsv_path.exists():
        print(f"  ERROR: File not found: {tsv_path}")
        return False

    header, rows = read_tsv(tsv_path)
    print(f"  Header columns: {len(header)}")
    print(f"  Data rows:      {len(rows)}")

    if len(rows) == 0:
        print("  WARNING: Empty file, skipping")
        return True

    # Apply column rename
    if rename_map:
        new_rows = []
        for row in rows:
            new_row = {}
            for k, v in row.items():
                new_key = rename_map.get(k, k)
                new_row[new_key] = v
            new_rows.append(new_row)
        rows = new_rows
        header = [rename_map.get(h, h) for h in header]

    # Apply filter
    if filter_fn:
        before = len(rows)
        rows = [r for r in rows if filter_fn(r)]
        print(f"  Filtered: {before} -> {len(rows)} rows")

    # Get DB columns
    db_cols = get_db_columns(conn, table)

    # Map TSV columns to DB columns
    tsv_cols_set = set(header)
    db_cols_set = set(db_cols)

    mapped_cols = [c for c in db_cols if c in tsv_cols_set]
    unmapped_db = db_cols_set - tsv_cols_set
    extra_tsv = tsv_cols_set - db_cols_set

    if unmapped_db:
        print(f"  DB cols not in TSV (will be NULL): {sorted(unmapped_db)}")
    if extra_tsv:
        print(f"  TSV cols not in DB (ignored): {sorted(extra_tsv)}")

    if not mapped_cols:
        print(f"  ERROR: No columns match between TSV and DB!")
        return False

    # Validate sample_id
    if table in SAMPLE_PK_TABLES:
        sid_col = "sample_id"
        sids = [r.get(sid_col, "") for r in rows]
        blank = sum(1 for s in sids if not s)
        if blank:
            print(f"  ERROR: {blank} rows with blank sample_id")
            return False
        dupes = len(sids) - len(set(sids))
        if dupes:
            print(f"  WARNING: {dupes} duplicate sample_id values")

    # Check orphan sample_ids
    if sample_ids and "sample_id" in tsv_cols_set:
        orphans = set()
        for r in rows:
            sid = r.get("sample_id", "")
            if sid and sid not in sample_ids:
                orphans.add(sid)
        if orphans:
            print(f"  WARNING: {len(orphans)} orphan sample_ids "
                  f"(not in samples): {sorted(orphans)[:5]}...")

    # Check orphan bioproject_accessions
    if bioproject_ids and "bioproject_accession" in tsv_cols_set:
        orphans = set()
        for r in rows:
            bp = r.get("bioproject_accession", "")
            if bp and bp not in bioproject_ids:
                orphans.add(bp)
        if orphans:
            print(f"  WARNING: {len(orphans)} orphan bioproject_accessions "
                  f"(not in bioprojects): {sorted(orphans)[:5]}...")

    # Insert
    placeholders = ",".join(["?"] * len(mapped_cols))
    col_names = ",".join(mapped_cols)
    sql = f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"

    inserted = 0
    for row in rows:
        vals = []
        for c in mapped_cols:
            v = row.get(c, None)
            if v is None or v == "" or v == "NA" or v == "nan":
                vals.append(None)
            else:
                vals.append(v)
        try:
            conn.execute(sql, vals)
            inserted += 1
        except sqlite3.Error as e:
            print(f"  ERROR inserting row: {e}")
            print(f"  Row sample_id={row.get('sample_id','?')}")

    conn.commit()
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  Inserted: {inserted}, Total in table: {count}")
    return True


def verify_db(conn):
    """Run integrity and FK checks, print table stats."""
    print(f"\n{'='*60}")
    print("DATABASE VERIFICATION")
    print(f"{'='*60}")

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"Integrity check: {integrity}")

    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        print(f"Foreign key violations: {len(fk_errors)}")
        for e in fk_errors[:10]:
            print(f"  {e}")
    else:
        print("Foreign key check: OK")

    print(f"\n{'='*60}")
    print("TABLE ROW COUNTS")
    print(f"{'='*60}")
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name != 'sqlite_sequence' ORDER BY name"
    ).fetchall()
    for (t,) in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        unique_samples = ""
        try:
            us = conn.execute(
                f"SELECT COUNT(DISTINCT sample_id) FROM {t}"
            ).fetchone()[0]
            unique_samples = f"  (unique sample_id: {us})"
        except Exception:
            pass
        print(f"  {t:40s} {n:>8}{unique_samples}")

    # Cross-table coverage
    print(f"\n{'='*60}")
    print("CROSS-TABLE COVERAGE")
    print(f"{'='*60}")
    n_samples = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    print(f"Total samples: {n_samples}")

    for child in ["genome_qc", "genome_qc_classification",
                   "sample_metadata", "sample_fasta_map",
                   "genome_rescue_candidates"]:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {child}").fetchone()[0]
            missing = conn.execute(f"""
                SELECT COUNT(*) FROM samples s
                LEFT JOIN {child} c ON s.sample_id = c.sample_id
                WHERE c.sample_id IS NULL
            """).fetchone()[0]
            print(f"  {child}: {n} rows, {missing} samples without data")
        except Exception:
            pass

    for child in ["literature_metadata_candidates", "isolate_typing",
                   "phenotypes"]:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {child}").fetchone()[0]
            us = conn.execute(
                f"SELECT COUNT(DISTINCT sample_id) FROM {child}"
            ).fetchone()[0]
            print(f"  {child}: {n} rows across {us} samples")
        except Exception:
            pass

    n_bp = conn.execute(
        "SELECT COUNT(*) FROM bioprojects"
    ).fetchone()[0]
    n_pub = conn.execute(
        "SELECT COUNT(*) FROM publications"
    ).fetchone()[0]
    n_mlr = conn.execute(
        "SELECT COUNT(*) FROM manual_literature_review"
    ).fetchone()[0]
    print(f"  bioprojects: {n_bp}")
    print(f"  publications: {n_pub}")
    print(f"  manual_literature_review: {n_mlr}")


def main():
    parser = argparse.ArgumentParser(
        description="Build RSSC strain database v2 from output/ TSVs"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    db_path = args.db

    if args.verify_only:
        if not db_path.exists():
            print(f"ERROR: Database not found: {db_path}")
            sys.exit(1)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        verify_db(conn)
        conn.close()
        return

    # Check schema
    if not SCHEMA_FILE.exists():
        print(f"ERROR: Schema not found: {SCHEMA_FILE}")
        sys.exit(1)

    # Check all source files exist
    print("Checking source files...")
    all_ok = True
    for table, path in SOURCES.items():
        exists = path.exists()
        status = "OK" if exists else "MISSING"
        print(f"  {table:40s} {status}  {path.name}")
        if not exists:
            all_ok = False
    if not all_ok:
        print("\nERROR: Some source files are missing!")
        sys.exit(1)

    # Remove old db if exists
    if db_path.exists():
        print(f"\nRemoving existing: {db_path}")
        db_path.unlink()

    # Create database from schema
    print(f"\nCreating database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    print("Schema applied successfully")

    # 1. samples (must be first - parent table)
    import_table(conn, "samples", SOURCES["samples"])
    sample_ids = set(
        r[0] for r in conn.execute("SELECT sample_id FROM samples").fetchall()
    )
    print(f"\n  Loaded {len(sample_ids)} sample_ids as reference set")

    # 2. sample_metadata (special: keyed by biosample_accession,
    #    prefer GCF_ row for dup SAMEA117660702)
    def metadata_filter(row):
        bs = row.get("biosample_accession", "")
        aa = row.get("assembly_accession", "")
        if bs == "SAMEA117660702" and not aa.startswith("GCF_"):
            return False
        return True

    # For sample_metadata, the TSV is keyed by assembly_accession
    # but our table is keyed by sample_id. We need to add sample_id
    # from biosample_accession column.
    print(f"\n{'='*60}")
    print("Importing: sample_metadata (special handling)")
    tsv_path = SOURCES["sample_metadata"]
    header, rows = read_tsv(tsv_path)
    print(f"  Raw rows: {len(rows)}")

    # Filter dup
    rows = [r for r in rows if metadata_filter(r)]
    print(f"  After filtering dup: {len(rows)}")

    # Add sample_id from biosample_accession
    for r in rows:
        r["sample_id"] = r.get("biosample_accession", "")

    db_cols = get_db_columns(conn, "sample_metadata")
    tsv_cols_set = set(rows[0].keys()) if rows else set()
    mapped_cols = [c for c in db_cols if c in tsv_cols_set]

    orphan_count = 0
    inserted = 0
    placeholders = ",".join(["?"] * len(mapped_cols))
    col_names = ",".join(mapped_cols)
    sql = f"INSERT OR IGNORE INTO sample_metadata ({col_names}) VALUES ({placeholders})"
    for row in rows:
        sid = row.get("sample_id", "")
        if sid not in sample_ids:
            orphan_count += 1
            continue
        vals = []
        for c in mapped_cols:
            v = row.get(c, None)
            if v is None or v == "" or v == "NA" or v == "nan":
                vals.append(None)
            else:
                vals.append(v)
        conn.execute(sql, vals)
        inserted += 1
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM sample_metadata").fetchone()[0]
    print(f"  Inserted: {inserted}, Orphans: {orphan_count}, Total: {count}")

    # 3-4. genome_qc tables
    import_table(conn, "genome_qc", SOURCES["genome_qc"],
                 sample_ids=sample_ids)
    import_table(conn, "genome_qc_classification",
                 SOURCES["genome_qc_classification"],
                 sample_ids=sample_ids)

    # 5-7. literature/typing/phenotype candidates
    import_table(conn, "literature_metadata_candidates",
                 SOURCES["literature_metadata_candidates"],
                 sample_ids=sample_ids)
    import_table(conn, "isolate_typing", SOURCES["isolate_typing"],
                 sample_ids=sample_ids)
    import_table(conn, "phenotypes", SOURCES["phenotypes"],
                 sample_ids=sample_ids)

    # 8. bioprojects (column rename needed)
    import_table(conn, "bioprojects", SOURCES["bioprojects"],
                 rename_map=BIOPROJECTS_RENAME)
    bioproject_ids = set(
        r[0] for r in conn.execute(
            "SELECT bioproject_accession FROM bioprojects"
        ).fetchall()
    )

    # 9. publications
    import_table(conn, "publications", SOURCES["publications"],
                 bioproject_ids=bioproject_ids)

    # 10. manual_literature_review
    import_table(conn, "manual_literature_review",
                 SOURCES["manual_literature_review"],
                 bioproject_ids=bioproject_ids)

    # 11. sample_fasta_map
    import_table(conn, "sample_fasta_map", SOURCES["sample_fasta_map"],
                 sample_ids=sample_ids)

    # 12. genome rescue tables
    import_table(conn, "genome_rescue_candidates",
                 SOURCES["genome_rescue_candidates"],
                 sample_ids=sample_ids)
    import_table(conn, "genome_rescue_read_audit",
                 SOURCES["genome_rescue_read_audit"],
                 sample_ids=sample_ids)
    import_table(conn, "genome_rescue_read_plan",
                 SOURCES["genome_rescue_read_plan"],
                
                 sample_ids=sample_ids)

    # Verify
    verify_db(conn)
    conn.close()
    print(f"\nDatabase written to: {db_path}")
    print(f"Size: {db_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
