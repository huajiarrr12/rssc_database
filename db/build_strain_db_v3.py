#!/usr/bin/env python3
"""Reproducibly build strain_db_v3.sqlite from frozen v3 source files.

v2 is always opened read-only. Automatic layers are reconstructed from the
formal merged manifests; human-curated tables are migrated row-for-row from v2.
Output is written to a temporary database, validated, then atomically renamed.
"""
import argparse
import csv
import glob
import hashlib
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path("/data/wry/RSSC_DATABASE")
DB_DIR = PROJECT / "rssc_database" / "db"
V2_DB = DB_DIR / "strain_db_v2.sqlite"
V3_DB = DB_DIR / "strain_db_v3.sqlite"
SCHEMA_SQL = DB_DIR / "schema_v2.sql"
BUILD_DIR = DB_DIR / "v3_build"
BUILD_MAN = BUILD_DIR / "manifests"
BUILD_AUD = BUILD_DIR / "audits"
BUILD_SCRIPTS = BUILD_DIR / "scripts"
BUILD_BACKUPS = BUILD_DIR / "backups"
BUILD_LOGS = BUILD_DIR / "logs"

OLD_SAMPLES = PROJECT / "output" / "analysis_sample_manifest.tsv"
OLD_META = PROJECT / "output" / "master_metadata.tsv"
OLD_QC = PROJECT / "output" / "genome_qc_summary.tsv"
OLD_CLS = PROJECT / "output" / "genome_qc_classification.tsv"
OLD_BPMAP = PROJECT / "audit" / "ncbi_bioproject_members_all.tsv"

FINAL_META = PROJECT / "merged_rssc_final" / "manifests" / "sample_metadata_rssc_v3.tsv"
NEW_META = PROJECT / "metadata_v3_incremental" / "parsed" / "new467_sample_metadata.tsv"
NEW_INPUT = PROJECT / "metadata_v3_incremental" / "manifests" / "new467_samples.tsv"
NEW_BPV = PROJECT / "metadata_v3_incremental" / "parsed" / "new467_sample_bioprojects.tsv"
NEW_QC = PROJECT / "incremental_v3" / "manifests" / "new_genome_qc.tsv"
NEW_CLS = PROJECT / "incremental_v3" / "manifests" / "new_genome_qc_classification.tsv"
ANN_MAP = PROJECT / "annotation_rssc_final" / "manifests" / "annotation_sample_manifest_rssc.tsv"
FASTA_DIR = PROJECT / "all_genomes"

SUPPRESSED = {
    "SAMN44820513", "SAMN44820521", "SAMN44820522", "SAMN44820523",
    "SAMN44820524", "SAMN44820525", "SAMN44820526",
}

# Tables copied verbatim from v2.
V2_MIGRATE_TABLES = [
    "literature_metadata_candidates", "isolate_typing", "phenotypes",
    "publications", "manual_literature_review",
    "genome_rescue_candidates", "genome_rescue_read_audit",
    "genome_rescue_read_plan", "manual_metadata", "manual_phenotypes",
    "manual_curation_audit",
]


def e(msg):
    print(msg, file=sys.stderr)


def q(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_tsv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def n_na(value):
    if value in (None, "", "NA", "NULL", "None"):
        return None
    return value


t = lambda v: n_na(v)


def conv(kind, value):
    if kind == "REAL":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if kind == "INTEGER":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
    return value


def table_columns(conn, table):
    return [(row[1], row[2]) for row in q(conn, f"PRAGMA table_info({table})")]


def copy_table_rows(src, dst, table):
    cols = table_columns(src, table)
    names = [c for c, _ in cols]
    rows = q(src, f"SELECT {','.join(names)} FROM {table} ORDER BY rowid")
    placeholders = ",".join("?" * len(names))
    pks = [row[0] for row in q(src, f"PRAGMA table_info({table})") if row[5]]
    dst.executemany(
        f"INSERT INTO {table} ({','.join(names)}) VALUES ({placeholders})",
        rows,
    )
    return len(rows)


def get_v2_rows(conn, table):
    cols = table_columns(conn, table)
    return [dict(zip([c for c, _ in cols], row))
            for row in q(conn, f"SELECT {','.join([c for c,_ in cols])} FROM {table} ORDER BY rowid")]


def insert_rows(conn, table, rows, columns=None):
    if not rows:
        return 0
    cols = columns or [c for c, _ in table_columns(conn, table)]
    pkeys = [c for c in cols]
    placeholders = ",".join("?" for _ in cols)
    conn.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        [tuple(conv(dict(table_columns(conn, table))[c], row.get(c))
               if False else row.get(c) for c in cols) for row in rows],
    )
    return len(rows)


def expected_ok(db):
    # Snapshot v2 checksum and return hash.
    with open(db, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def log_file():
    BUILD_LOGS.mkdir(parents=True, exist_ok=True)
    return BUILD_LOGS / "build.log"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--output", default=str(V3_DB))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for d in (BUILD_MAN, BUILD_AUD, BUILD_SCRIPTS, BUILD_BACKUPS, BUILD_LOGS):
        d.mkdir(parents=True, exist_ok=True)

    v2_hash_before = expected_ok(V2_DB)
    # Open v2 read-only for metadata/schema/history.
    ro = sqlite3.connect(f"file:{V2_DB}?mode=ro", uri=True)
    ro.text_factory = str
    with open(BUILD_AUD / "preflight_v2_database.txt", "w", encoding="utf-8") as fh:
        fh.write(
            f"path={V2_DB}\nintegrity_check={q(ro, 'PRAGMA integrity_check')[0][0]}\n"
            f"size={V2_DB.stat().st_size}\nmtime_epoch={V2_DB.stat().st_mtime_ns}\n"
            f"sha256={v2_hash_before}\ncheck_type=preflight\n"
        )
    assert q(ro, "PRAGMA integrity_check")[0][0] == "ok"

    if args.dry_run:
        print("dry-run input paths:")
        for p in (OLD_SAMPLES, OLD_META, OLD_QC, OLD_CLS, FINAL_META,
                  NEW_META, NEW_INPUT, NEW_QC, NEW_CLS, ANN_MAP):
            print("  " + ("OK" if p.exists() else "MISSING"), p)
        print("v2 checksum", v2_hash_before)
        return 0

    final = {r["sample_id"]: r for r in read_tsv(FINAL_META)}
    assert len(final) == 1602, len(final)
    old_rows = {r["sample_id"]: r for r in read_tsv(OLD_SAMPLES)}
    new_rows = {s: final[s] for s in final if s not in old_rows}
    assert len(new_rows) == 467

    qc_old = {r["sample_id"]: r for r in read_tsv(OLD_QC)}
    cls_old = {r["sample_id"]: r for r in read_tsv(OLD_CLS)}
    qc_new = {r["sample_id"]: r for r in read_tsv(NEW_QC)}
    cls_new = {r["sample_id"]: r for r in read_tsv(NEW_CLS)}
    ann = {r["sample_id"]: r for r in read_tsv(ANN_MAP)}
    assert len(ann) == 1595

    # Gate: every new sample must have complete QC.
    missing = {}
    for sid in new_rows:
        if sid not in qc_new or qc_new[sid].get("qc_status") != "PASS_DATA_AVAILABLE":
            missing[sid] = "missing QUAST/CheckM2 PASS"
        if sid not in cls_new:
            missing.setdefault(sid, "missing CheckM2 QC classification")
    if missing:
        rows = [{
            "sample_id": sid, "preferred_assembly": new_rows[sid].get("preferred_assembly"),
            "has_fasta": "TRUE" if (FASTA_DIR / f"{sid}.fna").exists() else "FALSE",
            "has_quast": str(qc_new.get(sid) is not None),
            "has_checkm2": str(qc_new.get(sid) is not None),
            "has_qc_classification": str(cls_new.get(sid) is not None),
            "missing_component": missing[sid],
        } for sid in sorted(missing)]
        write_tsv(BUILD_AUD / "missing_genome_qc.tsv",
                  ["sample_id", "preferred_assembly", "has_fasta", "has_quast",
                   "has_checkm2", "has_qc_classification", "missing_component"], rows)
        e("DATABASE_BUILD_BLOCKED_BY_QC")
        return 2

    # Annotation map validation: 1595 files, unique targets, no extras formal.
    targets = defaultdict(set)
    for sid, r in ann.items():
        assert r["preferred_assembly"] not in ("", None), f"empty assembly {sid}"
        assert all((Path(r[k]).exists() for k in ("fna_link", "ffn_link", "faa_link", "gff3_link"))), sid
        for k in ("fna_link", "ffn_link", "faa_link", "gff3_link"):
            targets[k].add(Path(r[k]).resolve())

    # Formal fasta mapping from all_genomes/<BioSample>.fna.
    fasta_map = {}
    for sid in sorted(final):
        p = FASTA_DIR / f"{sid}.fna"
        if p.exists():
            fasta_map[sid] = p
    assert len(fasta_map) == 1595
    suppressed = [s for s in final if s not in fasta_map]
    assert suppressed == sorted(SUPPRESSED), (suppressed, sorted(SUPPRESSED))

    # Build temporary DB from the v2 real schema file + actual views.
    tmp = DB_DIR / f"strain_db_v3.tmp.{os.getpid()}"
    for stale in (tmp, Path(f"{tmp}-wal"), Path(f"{tmp}-shm"),
                  Path(f"{tmp}-journal")):
        stale.unlink(missing_ok=True)
    v3 = sqlite3.connect(tmp)
    v3.text_factory = str
    try:
        v3.execute("PRAGMA foreign_keys=OFF")  # controlled bulk load; recheck FK later
        v3.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
        # Views defined in actual v2 are not in schema_v2.sql, copy them.
        for view_name, in q(ro, "SELECT name FROM sqlite_master WHERE type='view'"):
            for (sql,) in q(ro, "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (view_name,)):
                v3.executescript(sql)

        # Add v3-only annotation/membership tables.
        v3.executescript(
            """
            CREATE TABLE IF NOT EXISTS sample_annotations (
                sample_id TEXT PRIMARY KEY REFERENCES samples(sample_id),
                annotation_tool TEXT,
                annotation_version TEXT,
                gff3_path TEXT,
                faa_path TEXT,
                ffn_path TEXT,
                fna_path TEXT,
                annotation_status TEXT,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS sample_bioprojects (
                sample_id TEXT NOT NULL REFERENCES samples(sample_id),
                bioproject_accession TEXT NOT NULL REFERENCES bioprojects(bioproject_accession),
                relationship TEXT,
                source TEXT,
                notes TEXT,
                PRIMARY KEY (sample_id, bioproject_accession)
            );
            """
        )

        # 1) samples: copy old values exactly; construct new values from frozen metadata.
        samples_cols = [c for c, _ in table_columns(v3, "samples")]
        sample_rows = []
        for sid in sorted(final):
            if sid in old_rows:
                sample_rows.append({c: old_rows[sid].get(c) for c in samples_cols})
            else:
                x = final[sid]
                sample_rows.append({
                    "sample_id": sid,
                    "biosample_accession": sid,
                    "sample_id_source": "biosample_accession",
                    "strain": x.get("strain"),
                    "isolate": x.get("isolate") or x.get("isolate_raw"),
                    "organism_name": x.get("organism_name"),
                    "preferred_assembly": x.get("preferred_assembly"),
                    "genbank_accession": x.get("genbank_accession"),
                    "refseq_accession": x.get("refseq_accession"),
                    "all_assembly_accessions": x.get("all_assembly_accessions")
                                               or ";".join(filter(None, (x.get("genbank_accession"), x.get("refseq_accession")))),
                    "n_assemblies": x.get("n_assemblies") or 1,
                    "duplicate_type": x.get("duplicate_type") or "unique",
                    "needs_assembly_qc_review": x.get("needs_assembly_qc_review") or "FALSE",
                    "bioproject_accession": x.get("bioproject_accession"),
                    "host_raw": x.get("host_raw") or x.get("host"),
                    "host_species": x.get("host_species"),
                    "host_cultivar": x.get("host_cultivar"),
                    "country": x.get("country"),
                    "admin1": x.get("admin1") or x.get("region"),
                    "locality": x.get("locality"),
                    "latitude": x.get("latitude"),
                    "longitude": x.get("longitude"),
                    "collection_year": x.get("collection_year"),
                    "sra_accessions": x.get("sra_accessions"),
                    "n_sra_runs": x.get("n_sra_runs") or x.get("sra_run_count"),
                    "sequencing_platforms": x.get("sequencing_platforms"),
                    "sra_lookup_status": x.get("sra_lookup_status")
                                         or ("found_ncbi" if x.get("sra_status") == "HAS_RUNS" else
                                             "verified_no_runs" if x.get("sra_status") == "VERIFIED_NO_RUNS" else None),
                    "core_metadata_complete": x.get("core_metadata_complete") or "FALSE",
                    "extended_metadata_complete": x.get("extended_metadata_complete") or "FALSE",
                    "needs_manual_review": x.get("needs_manual_review") or "FALSE",
                    "pmid": x.get("pmid"),
                    "doi": x.get("doi"),
                })
        insert_rows(v3, "samples", sample_rows, samples_cols)
        assert v3.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1602

        # 2) sample_metadata: old from v2, new constructed (automatic only).
        sm_cols = [c for c, _ in table_columns(v3, "sample_metadata")]
        sm_rows = []
        v2_meta = get_v2_rows(ro, "sample_metadata")
        v2_meta_by = {r["sample_id"]: r for r in v2_meta}
        for sid in sorted(final):
            if sid in v2_meta_by:
                sm_rows.append({c: v2_meta_by[sid].get(c) for c in sm_cols})
            else:
                x = final[sid]
                sm_rows.append({
                    "sample_id": sid,
                    "assembly_accession": x.get("preferred_assembly"),
                    "bioproject_accession": x.get("bioproject_accession"),
                    "strain": x.get("strain"),
                    "isolate": x.get("isolate"),
                    "sample_name": x.get("sample_name_raw"),
                    "organism_name": x.get("organism_name"),
                    "taxid": x.get("taxid"),
                    "assembly_level": x.get("assembly_level"),
                    "release_date": None,
                    "sequencing_tech": None,
                    "source_database": None,
                    "host_raw": x.get("host"),
                    "host_species": x.get("host"),
                    "host_cultivar": None,
                    "host_ncbi": x.get("host"),
                    "host_ena": None,
                    "host_conflict": "FALSE",
                    "host_source": "NCBI_ASSEMBLY_EMBEDDED_BIOSAMPLE" if x.get("host") else None,
                    "cultivar_ncbi": None,
                    "cultivar_ena": None,
                    "cultivar_conflict": "FALSE",
                    "cultivar_source": None,
                    "isolation_source": x.get("isolation_source"),
                    "isolation_source_source": "NCBI_ASSEMBLY_EMBEDDED_BIOSAMPLE" if x.get("isolation_source") else None,
                    "geo_loc_name_raw": None,
                    "country": x.get("country"),
                    "admin1": x.get("region"),
                    "locality": x.get("locality"),
                    "geo_ncbi": None,
                    "geo_ena": None,
                    "geo_conflict": "FALSE",
                    "geo_relation": None,
                    "geo_source": None,
                    "lat_lon_raw": None,
                    "latitude": x.get("latitude"),
                    "longitude": x.get("longitude"),
                    "latlon_source": None,
                    "collection_date_raw": x.get("collection_date_raw"),
                    "collection_year": x.get("collection_year"),
                    "collection_date_ncbi": x.get("collection_date_raw"),
                    "collection_date_ena": None,
                    "collection_date_conflict": "FALSE",
                    "collection_date_source": "NCBI_ASSEMBLY_EMBEDDED_BIOSAMPLE",
                    "sra_accession": None,
                    "sra_accessions": x.get("sra_accessions"),
                    "n_sra_runs": x.get("sra_run_count") or x.get("n_sra_runs"),
                    "sra_experiments": None,
                    "sequencing_platforms": None,
                    "sequencing_models": None,
                    "library_strategies": None,
                    "ena_accession": None,
                    "sra_source": "NCBI_SRA" if x.get("sra_status") == "HAS_RUNS" else
                                   ("verified_no_runs" if x.get("sra_status") == "VERIFIED_NO_RUNS" else None),
                    "sra_lookup_status": "found_ncbi" if x.get("sra_status") == "HAS_RUNS" else
                                          ("verified_no_runs" if x.get("sra_status") == "VERIFIED_NO_RUNS" else None),
                    "pmid": x.get("pmid"),
                    "doi": x.get("doi"),
                    "metadata_source": x.get("metadata_source"),
                    "metadata_confidence": "high" if x.get("metadata_source") else None,
                    "metadata_conflict": x.get("metadata_conflict") or "FALSE",
                    "needs_manual_review": "FALSE",
                    "biosample_attributes_json": None,
                    "notes": None,
                })
        insert_rows(v3, "sample_metadata", sm_rows, sm_cols)
        assert v3.execute("SELECT COUNT(*) FROM sample_metadata").fetchone()[0] == 1602

        # 3) genome_qc: old from v2, new from PASS QC rows.
        gq_cols = [c for c, _ in table_columns(v3, "genome_qc")]
        gq_rows = []
        v2_qc = get_v2_rows(ro, "genome_qc")
        v2_qc_by = {r["sample_id"]: r for r in v2_qc}
        for sid in sorted(final):
            if sid in v2_qc_by:
                gq_rows.append({c: v2_qc_by[sid].get(c) for c in gq_cols})
            else:
                x = final[sid]; qc = qc_new[sid]
                gq_rows.append({
                    "sample_id": sid,
                    "biosample_accession": sid,
                    "preferred_assembly": x.get("preferred_assembly"),
                    "assembly_level": qc.get("assembly_level") or x.get("assembly_level"),
                    "genome_size": qc.get("genome_size"),
                    "num_contigs": qc.get("num_contigs"),
                    "largest_contig": qc.get("largest_contig"),
                    "N50": qc.get("N50"),
                    "L50": qc.get("L50"),
                    "GC_percent": qc.get("GC_percent"),
                    "completeness": qc.get("completeness"),
                    "contamination": qc.get("contamination"),
                    "sra_lookup_status": "found_ncbi" if x.get("sra_status") == "HAS_RUNS" else
                                          ("verified_no_runs" if x.get("sra_status") == "VERIFIED_NO_RUNS" else None),
                    "n_sra_runs": x.get("sra_run_count") or x.get("n_sra_runs"),
                    "qc_status": "PASS_DATA_AVAILABLE",
                    "qc_notes": None,
                    "outlier_flags": None,
                })
        insert_rows(v3, "genome_qc", gq_rows, gq_cols)
        assert v3.execute("SELECT COUNT(*) FROM genome_qc").fetchone()[0] == 1602

        # 4) classification: old 1128 + new 467.
        cl_cols = [c for c, _ in table_columns(v3, "genome_qc_classification")]
        cl_rows = []
        v2_cls = get_v2_rows(ro, "genome_qc_classification")
        v2_cls_by = {r["sample_id"]: r for r in v2_cls}
        for sid in sorted(final):
            if sid in v2_cls_by:
                cl_rows.append({c: v2_cls_by[sid].get(c) for c in cl_cols})
            elif sid in SUPPRESSED:
                # seven suppressed old BioSamples intentionally have no classification
                continue
            else:
                assert sid in cls_new, sid
                row = cls_new[sid]
                cl_rows.append({
                    "sample_id": sid,
                    "biosample_accession": sid,
                    "strain": final[sid].get("strain"),
                    "preferred_assembly": final[sid].get("preferred_assembly"),
                    "assembly_level": row.get("assembly_level"),
                    "genome_size": row.get("genome_size"),
                    "num_contigs": row.get("num_contigs"),
                    "N50": row.get("N50"),
                    "GC_percent": row.get("GC_percent"),
                    "completeness": row.get("completeness"),
                    "contamination": row.get("contamination"),
                    "qc_class": row.get("qc_class"),
                    "qc_reason": row.get("qc_reason"),
                    "genome_size_outlier": row.get("genome_size_outlier"),
                    "gc_outlier": row.get("gc_outlier"),
                    "contig_outlier": row.get("contig_outlier"),
                    "n50_outlier": row.get("n50_outlier"),
                    "fragmentation_flag": row.get("fragmentation_flag"),
                    "low_completeness_flag": row.get("low_completeness_flag"),
                    "high_contamination_flag": row.get("high_contamination_flag"),
                })
        insert_rows(v3, "genome_qc_classification", cl_rows, cl_cols)
        assert v3.execute("SELECT COUNT(*) FROM genome_qc_classification").fetchone()[0] == 1595

        # 5) sample_fasta_map: 1595 formal paths.
        sf_cols = [c for c, _ in table_columns(v3, "sample_fasta_map")]
        sf_rows = []
        for sid in sorted(fasta_map):
            p = fasta_map[sid]
            sf_rows.append({
                "sample_id": sid,
                "biosample_accession": sid,
                "preferred_assembly": final[sid].get("preferred_assembly"),
                "original_fasta_name": p.name,
                "fasta_path": str(p),
            })
        insert_rows(v3, "sample_fasta_map", sf_rows, sf_cols)
        assert v3.execute("SELECT COUNT(*) FROM sample_fasta_map").fetchone()[0] == 1595

        # 6) annotations: 1595.
        ann_cols = ["sample_id", "annotation_tool", "annotation_version",
                    "gff3_path", "faa_path", "ffn_path", "fna_path",
                    "annotation_status", "notes"]
        ann_rows = [{
            "sample_id": sid,
            "annotation_tool": "bakta",
            "annotation_version": "1.12.0",
            "gff3_path": r["gff3_link"],
            "faa_path": r["faa_link"],
            "ffn_path": r["ffn_link"],
            "fna_path": r["fna_link"],
            "annotation_status": "OK",
            "notes": r.get("annotation_source"),
        } for sid, r in sorted(ann.items())]
        insert_rows(v3, "sample_annotations", ann_rows, ann_cols)
        assert v3.execute("SELECT COUNT(*) FROM sample_annotations").fetchone()[0] == 1595

        # 7) rebuild BioProject membership from old manual/audit map + new relationships.
        mship = {}
        for r in read_tsv(OLD_BPMAP):
            sid = r.get("biosample_accession")
            bp = r.get("bioproject_accession")
            if sid in final and bp:
                mship[(sid, bp)] = r.get("source", "ncbi_audit")
        for sid, r in final.items():
            bp = r.get("bioproject_accession")
            if bp:
                mship.setdefault((sid, bp), "sample_manifest")
        for r in read_tsv(NEW_BPV):
            sid = r.get("sample_id")
            bp = r.get("bioproject_accession")
            if sid in final and bp:
                mship[(sid, bp)] = r.get("relationship_source", "incremental")
        # Preserve every v2 bioproject row even if no membership rows.
        bp_preserve = get_v2_rows(ro, "bioprojects")
        bp_by = {r["bioproject_accession"]: r for r in bp_preserve}
        bp_cols = [c for c, _ in table_columns(v3, "bioprojects")]
        bp_rows = []
        all_bp = set(bp_by) | {bp for _, bp in mship}
        for bp in sorted(all_bp):
            prev = bp_by.get(bp, {})
            members = [sid for (sid, b) in mship if b == bp]
            sid_set = set(members)
            strains = {final.get(s, {}).get("strain") for s in sid_set}
            strains.discard(None); strains.discard("")
            row = {c: prev.get(c) for c in bp_cols}
            row.update({
                "bioproject_accession": bp,
                "n_samples": len(members),
                "n_unique_biosamples": len(sid_set),
                "n_unique_strains": len(strains),
                "n_isolates": len(strains),
                "strain_names": "; ".join(sorted(strains))[:2000] or None,
                "missing_host_count": sum(1 for s in sid_set if not final[s].get("host")),
                "missing_geo_count": sum(1 for s in sid_set if not final[s].get("country")),
                "missing_year_count": sum(1 for s in sid_set if final[s].get("collection_year") in (None, "", "NULL")),
                "missing_cultivar_count": sum(1 for s in sid_set if not final[s].get("host_cultivar")),
                "missing_sra_count": sum(1 for s in sid_set if not final[s].get("sra_accessions")),
                "core_metadata_complete": "TRUE" if all((
                    sum(1 for s in sid_set if not final[s].get("host")),
                    sum(1 for s in sid_set if not final[s].get("country")),
                    sum(1 for s in sid_set if final[s].get("collection_year") in (None, "", "NULL")),
                )) == (0, 0, 0) else "FALSE",
                "extended_metadata_complete": "TRUE" if all((
                    sum(1 for s in sid_set if not final[s].get("host")),
                    sum(1 for s in sid_set if not final[s].get("country")),
                    sum(1 for s in sid_set if final[s].get("collection_year") in (None, "", "NULL")),
                    sum(1 for s in sid_set if not final[s].get("host_cultivar")),
                )) == (0, 0, 0, 0) else "FALSE",
            })
            bp_rows.append(row)
        insert_rows(v3, "bioprojects", bp_rows, bp_cols)

        # separate membership table rows
        smship = [{
            "sample_id": sid, "bioproject_accession": bp,
            "relationship": None, "source": src, "notes": None,
        } for (sid, bp), src in sorted(mship.items())]
        insert_rows(v3, "sample_bioprojects", smship,
                    ["sample_id", "bioproject_accession", "relationship", "source", "notes"])

        # Historical source/candidate and curation tables: verbatim migration.
        for table in V2_MIGRATE_TABLES:
            v2_table_rows = get_v2_rows(ro, table)
            v3_table_cols = [c for c, _ in table_columns(v3, table)]
            insert_rows(v3, table,
                        [{c: row.get(c) for c in v3_table_cols} for row in v2_table_rows],
                        v3_table_cols)
        v3.commit()
    except Exception as exc:
        import traceback
        v3.rollback()
        e("build failed: " + traceback.format_exc())
        try:
            v3.close()
            tmp.unlink()
        except OSError:
            pass
        return 1

    # Re-enable FK check after bulk load.
    v3.execute("PRAGMA foreign_keys=ON")
    fk_viol = q(v3, "PRAGMA foreign_key_check")
    if fk_viol:
        e(f"foreign key violations: {len(fk_viol)}")
        v3.close(); tmp.unlink(); return 1

    v3.close()
    v2_hash_after = expected_ok(V2_DB)
    if v2_hash_after != v2_hash_before:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("v2 checksum changed during build")
    if os.path.exists(args.output):
        stamp = time.strftime("%Y%m%dT%H%M%S")
        backup = BUILD_BACKUPS / f"strain_db_v3.previous.{stamp}.sqlite"
        os.replace(args.output, backup)
    os.replace(tmp, args.output)
    elapsed = time.time() - t0
    print(f"built {args.output} in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
