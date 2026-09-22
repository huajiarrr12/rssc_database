"""Manual Curation page — Single Sample and BioProject Batch modes."""
import datetime
from pathlib import Path
import streamlit as st
import pandas as pd

DB_PATH = (Path(__file__).resolve().parents[1] / "db" /
           "strain_db_v3.sqlite").resolve()
ORGANISM_FIELD = "organism_name"
CURATION_FIELDS = [
    "host", "cultivar", "isolation_source",
    "country", "region", "locality",
    "collection_year", "collection_date",
    "phylotype", "sequevar", "sequence_type_ST",
    "lineage", "race_or_pathotype",
]
SOURCE_TYPES = ["paper", "supplement", "manual_review", "database_correction", "other"]
REVIEW_STATUSES = ["IN_PROGRESS", "REVIEWED", "REJECTED"]
BATCH_FIELDS = {
    "organism_name": "manual_organism",
    "host": "manual_host", "cultivar": "manual_cultivar",
    "country": "manual_country", "region": "manual_region",
    "locality": "manual_locality", "collection_year": "manual_year",
    "phylotype": "manual_phylotype", "sequevar": "manual_sequevar",
}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _v(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return val


def _load_latest_manual(q, sid, field):
    df = q(
        "SELECT id, field, value, review_status, source_type, source_paper, "
        "source_doi, source_pmid, source_table, source_file, source_url, "
        "evidence, notes, updated_at "
        "FROM manual_metadata WHERE sample_id=? AND field=? "
        "ORDER BY updated_at DESC, id DESC LIMIT 1",
        [sid, field],
    )
    if df.empty:
        return None
    return df.iloc[0]


def _manual_payload(sid, field, value, stype, spaper, sdoi, spmid,
                    stable, sfile, surl, evidence, notes, rstatus):
    value = "" if value is None else str(value).strip()
    if not value:
        raise ValueError(f"Manual value is empty for {sid}/{field}")
    if rstatus not in REVIEW_STATUSES:
        raise ValueError(f"Invalid review status: {rstatus}")
    return {
        "sample_id": sid,
        "field": field,
        "value": value,
        "source_type": stype or None,
        "source_paper": spaper or None,
        "source_doi": sdoi or None,
        "source_pmid": spmid or None,
        "source_table": stable or None,
        "source_file": sfile or None,
        "source_url": surl or None,
        "evidence": evidence or None,
        "notes": notes or None,
        "review_status": rstatus,
    }


def _connection_path(conn):
    row = conn.execute(
        "SELECT file FROM pragma_database_list WHERE name='main'"
    ).fetchone()
    return Path(row[0]).resolve() if row and row[0] else None


def _save_manual_changes(conn, changes, provenance, expected_db_path=DB_PATH):
    """Persist a confirmed batch atomically and verify every record."""
    if not changes:
        return {
            "attempted": 0, "inserted": 0, "updated": 0,
            "committed": False, "verified": 0, "errors": [],
            "db_path": str(expected_db_path.resolve()),
        }

    expected_db_path = Path(expected_db_path).resolve()
    actual_db_path = _connection_path(conn)
    if actual_db_path != expected_db_path:
        raise RuntimeError(
            f"Unexpected database path: {actual_db_path}; "
            f"expected {expected_db_path}"
        )

    payloads = [
        _manual_payload(
            c["sample_id"], c["field"], c["new"],
            provenance.get("source_type"), provenance.get("source_paper"),
            provenance.get("source_doi"), provenance.get("source_pmid"),
            provenance.get("source_table"), provenance.get("source_file"),
            provenance.get("source_url"), provenance.get("evidence"),
            provenance.get("notes"), provenance.get("review_status"),
        )
        for c in changes
    ]
    inserted = 0
    updated = 0
    persisted_ids = []
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        for payload in payloads:
            where = (
                "sample_id=? AND field=? AND value=? "
                "AND source_type IS ? AND source_paper IS ? "
                "AND source_doi IS ? AND source_pmid IS ? "
                "AND source_table IS ? AND source_file IS ? "
                "AND source_url IS ? AND evidence IS ? AND notes IS ?"
            )
            match_params = (
                payload["sample_id"], payload["field"], payload["value"],
                payload["source_type"], payload["source_paper"],
                payload["source_doi"], payload["source_pmid"],
                payload["source_table"], payload["source_file"],
                payload["source_url"], payload["evidence"], payload["notes"],
            )
            existing = conn.execute(
                "SELECT id, value, review_status FROM manual_metadata "
                f"WHERE {where} ORDER BY id DESC LIMIT 1", match_params
            ).fetchone()
            now = _now()
            if existing:
                mm_id, old_value, old_status = existing
                conn.execute(
                    "UPDATE manual_metadata SET source_type=?, "
                    "source_paper=?, source_doi=?, source_pmid=?, "
                    "source_table=?, source_file=?, source_url=?, "
                    "evidence=?, notes=?, review_status=?, updated_at=? "
                    "WHERE id=?",
                    (
                        payload["source_type"], payload["source_paper"],
                        payload["source_doi"], payload["source_pmid"],
                        payload["source_table"], payload["source_file"],
                        payload["source_url"], payload["evidence"],
                        payload["notes"], payload["review_status"], now,
                        mm_id,
                    ),
                )
                action = "REJECT" if payload["review_status"] == "REJECTED" else "UPDATE"
                conn.execute(
                    "INSERT INTO manual_curation_audit "
                    "(manual_metadata_id,action,old_value,new_value,timestamp) "
                    "VALUES (?,?,?,?,?)",
                    (mm_id, action, old_value, payload["value"], now),
                )
                updated += 1
            else:
                cur = conn.execute(
                    "INSERT INTO manual_metadata "
                    "(sample_id,field,value,source_type,source_paper,"
                    "source_doi,source_pmid,source_table,source_file,"
                    "source_url,evidence,notes,review_status,created_at,"
                    "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        payload["sample_id"], payload["field"],
                        payload["value"], payload["source_type"],
                        payload["source_paper"], payload["source_doi"],
                        payload["source_pmid"], payload["source_table"],
                        payload["source_file"], payload["source_url"],
                        payload["evidence"], payload["notes"],
                        payload["review_status"], now, now,
                    ),
                )
                mm_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO manual_curation_audit "
                    "(manual_metadata_id,action,old_value,new_value,timestamp) "
                    "VALUES (?,?,?,?,?)",
                    (mm_id, "INSERT", None, payload["value"], now),
                )
                inserted += 1
            persisted_ids.append((mm_id, payload))

        conn.commit()

        verified = 0
        for mm_id, payload in persisted_ids:
            row = conn.execute(
                "SELECT sample_id, field, value, review_status, "
                "source_type, source_paper, source_doi, source_pmid, "
                "source_table, source_file, source_url, evidence, notes "
                "FROM manual_metadata WHERE id=?", (mm_id,)
            ).fetchone()
            expected = tuple(payload[col] for col in (
                "sample_id", "field", "value", "review_status",
                "source_type", "source_paper", "source_doi", "source_pmid",
                "source_table", "source_file", "source_url", "evidence",
                "notes",
            ))
            if row != expected:
                raise RuntimeError(
                    f"Persistence verification failed for manual_metadata.id={mm_id}"
                )
            verified += 1
        return {
            "attempted": len(payloads), "inserted": inserted,
            "updated": updated, "committed": True, "verified": verified,
            "errors": [], "db_path": str(actual_db_path),
        }
    except Exception:
        conn.rollback()
        raise


def _save_one_manual(conn, sid, field, value, stype, spaper,
                     sdoi, spmid, stable, sfile, surl,
                     evidence, notes, rstatus):
    return _save_manual_changes(
        conn,
        [{"sample_id": sid, "field": field, "new": value, "old": ""}],
        {
            "source_type": stype, "source_paper": spaper,
            "source_doi": sdoi, "source_pmid": spmid,
            "source_table": stable, "source_file": sfile,
            "source_url": surl, "evidence": evidence, "notes": notes,
            "review_status": rstatus,
        },
    )


def _clear_query_cache(q):
    clear = getattr(q, "clear", None)
    if clear is not None:
        clear()


def _show_save_result(result):
    st.success("Save completed")
    st.write(f"Attempted changes: {result['attempted']}")
    st.write(f"Inserted: {result['inserted']}")
    st.write(f"Updated: {result['updated']}")
    st.write(f"Database verified: {result['verified']}/{result['attempted']}")
    st.write(f"Committed: {result['committed']}")
    st.write(f"Review status: {result['review_status']}")
    st.write(f"Database: `{result['db_path']}`")


def _insert_manual(conn, sid, field, value, stype, spaper,
                   sdoi, spmid, stable, sfile, surl,
                   evidence, notes, rstatus):
    """Compatibility wrapper for the single-record UI."""
    try:
        result = _save_one_manual(
            conn, sid, field, value, stype, spaper, sdoi, spmid,
            stable, sfile, surl, evidence, notes, rstatus,
        )
        return True, (
            f"Saved {result['attempted']} record(s): "
            f"{result['inserted']} inserted, {result['updated']} updated, "
            f"verified {result['verified']}/{result['attempted']}"
        )
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"Manual metadata save failed: {exc}") from exc

def _show_identity(q, sid):
    row = q(
        "SELECT s.sample_id, s.biosample_accession, s.strain, "
        "s.isolate, COALESCE(NULLIF(sm.organism_name, ''), "
        "s.organism_name) AS "
        "current_organism, sm.taxid AS current_taxid, "
        "s.bioproject_accession, "
        "s.preferred_assembly, gc.qc_class "
        "FROM samples s "
        "LEFT JOIN sample_metadata sm ON s.sample_id = sm.sample_id "
        "LEFT JOIN genome_qc_classification gc "
        "ON s.sample_id = gc.sample_id WHERE s.sample_id = ?",
        [sid])
    if row.empty:
        return None
    r = row.iloc[0]
    c1, c2 = st.columns(2)
    for c, items in [(c1, [
        ("sample_id", r["sample_id"]),
        ("BioSample", r["biosample_accession"]),
        ("strain", _v(r.get("strain"))),
        ("isolate", _v(r.get("isolate"))),
    ]), (c2, [
        ("current_organism", _v(r.get("current_organism"))),
        ("current_taxid", _v(r.get("current_taxid"))),
        ("BioProject", _v(r.get("bioproject_accession"))),
        ("assembly", _v(r.get("preferred_assembly"))),
        ("QC class", _v(r.get("qc_class"))),
    ])]:
        for label, val in items:
            c.markdown(f"**{label}:** {val or '—'}")
    return r


def _show_db_metadata(q, sid):
    meta = q("SELECT * FROM sample_metadata WHERE sample_id=?", [sid])
    if meta.empty:
        st.info("No database metadata")
        return
    r = meta.iloc[0]
    fields = [
        ("host_species", "Host"), ("host_cultivar", "Cultivar"),
        ("isolation_source", "Isolation source"),
        ("country", "Country"), ("admin1", "Region"),
        ("locality", "Locality"),
        ("collection_year", "Year"), ("collection_date_raw", "Date"),
    ]
    rows = [(lb, r.get(col)) for col, lb in fields
            if _v(r.get(col))]
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["Field", "Value"]),
                     hide_index=True, use_container_width=True)
    else:
        st.info("All metadata fields are empty")


def _show_lit_cands(q, sid):
    df = q(
        "SELECT field, candidate_value, confidence, pmid, "
        "paper_title, sheet_or_table, match_method, "
        "needs_manual_review "
        "FROM literature_metadata_candidates "
        "WHERE sample_id=? ORDER BY field", [sid])
    if df.empty:
        st.info("No literature candidates")
    else:
        st.dataframe(df, hide_index=True, use_container_width=True)


def _show_typing_cands(q, sid):
    df = q(
        "SELECT typing_scheme, typing_value, confidence, "
        "pmid, paper_title FROM isolate_typing "
        "WHERE sample_id=? ORDER BY typing_scheme", [sid])
    if df.empty:
        st.info("No typing candidates")
    else:
        st.dataframe(df, hide_index=True, use_container_width=True)


def _show_manual(q, sid):
    df = q(
        "SELECT id, field, value, review_status, source_type, "
        "source_doi, source_table, notes, updated_at "
        "FROM manual_metadata WHERE sample_id=? "
        "ORDER BY field, updated_at DESC", [sid])
    if df.empty:
        st.info("No manual records yet")
    else:
        st.dataframe(df, hide_index=True, use_container_width=True)

def _render_single(q, get_write_conn):
    term = st.text_input(
        "Search sample",
        placeholder="sample_id, BioSample, strain, BioProject, assembly")
    if not term:
        st.info("Enter a search term to begin.")
        return
    pat = f"%{term}%"
    hits = q(
        "SELECT sample_id, biosample_accession, strain, "
        "bioproject_accession, preferred_assembly FROM samples "
        "WHERE sample_id LIKE ? OR biosample_accession LIKE ? "
        "OR strain LIKE ? OR bioproject_accession LIKE ? "
        "OR preferred_assembly LIKE ? ORDER BY sample_id",
        [pat, pat, pat, pat, pat])
    if hits.empty:
        st.warning("No matches")
        return
    st.success(f"Found **{len(hits)}** sample(s)")
    sid = st.selectbox("Select sample", hits["sample_id"].tolist())
    if not sid:
        return

    st.subheader("Identity")
    identity = _show_identity(q, sid)
    st.subheader("Current Database Metadata")
    _show_db_metadata(q, sid)
    st.subheader("Literature Candidates")
    _show_lit_cands(q, sid)
    st.subheader("Typing Candidates")
    _show_typing_cands(q, sid)
    st.subheader("Existing Manual Records")
    _show_manual(q, sid)

    org = _load_latest_manual(q, sid, ORGANISM_FIELD)
    st.divider()
    st.subheader("Organism Review")
    if identity is not None:
        current_organism = str(_v(identity.get("current_organism")))
        current_taxid = str(_v(identity.get("current_taxid")))
    else:
        current_organism = ""
        current_taxid = ""
    if org is not None:
        manual_organism = str(_v(org.get("value")))
        org_status = org.get("review_status") or REVIEW_STATUSES[0]
        org_stype = org.get("source_type") or SOURCE_TYPES[0]
        org_paper = str(_v(org.get("source_paper")))
        org_doi = str(_v(org.get("source_doi")))
        org_pmid = str(_v(org.get("source_pmid")))
        org_table = str(_v(org.get("source_table")))
        org_file = str(_v(org.get("source_file")))
        org_url = str(_v(org.get("source_url")))
        org_evidence = str(_v(org.get("evidence")))
        org_notes = str(_v(org.get("notes")))
    else:
        manual_organism = ""
        org_status = REVIEW_STATUSES[0]
        org_stype = SOURCE_TYPES[0]
        org_paper = org_doi = org_pmid = org_table = ""
        org_file = org_url = org_evidence = org_notes = ""
    c1, c2 = st.columns(2)
    c1.text_input("Current organism", value=current_organism,
                  disabled=True, key=f"org_current_{sid}")
    c2.text_input("Current taxid", value=current_taxid,
                  disabled=True, key=f"org_taxid_{sid}")
    manual_organism = st.text_input("Manual organism", value=manual_organism,
                                    key=f"org_manual_{sid}")
    stype_idx = SOURCE_TYPES.index(org_stype) if org_stype in SOURCE_TYPES else 0
    stype = st.selectbox("Source type", SOURCE_TYPES,
                         index=stype_idx,
                         key=f"org_stype_{sid}")
    c3, c4 = st.columns(2)
    spaper = c3.text_input("Paper title", value=org_paper, key=f"org_paper_{sid}")
    sdoi = c4.text_input("DOI", value=org_doi, key=f"org_doi_{sid}")
    spmid = c3.text_input("PMID", value=org_pmid, key=f"org_pmid_{sid}")
    stable = c4.text_input("Source table", value=org_table, key=f"org_table_{sid}")
    sfile = c3.text_input("Source file", value=org_file, key=f"org_file_{sid}")
    surl = c4.text_input("Source URL", value=org_url, key=f"org_url_{sid}")
    evidence = st.text_area("Evidence", value=org_evidence, key=f"org_evidence_{sid}",
                            height=68)
    notes = st.text_area("Notes", value=org_notes, key=f"org_notes_{sid}",
                         height=68)
    rstatus_idx = (REVIEW_STATUSES.index(org_status)
                   if org_status in REVIEW_STATUSES else 0)
    rstatus = st.selectbox("Review status", REVIEW_STATUSES,
                           index=rstatus_idx,
                           key=f"org_rstatus_{sid}")

    if st.button("Save organism review", type="primary", key="org_save"):
        if not manual_organism:
            st.error("Manual organism is required")
        else:
            conn = get_write_conn()
            try:
                result = _save_one_manual(
                    conn, sid, ORGANISM_FIELD, manual_organism, stype,
                    spaper, sdoi, spmid, stable, sfile, surl,
                    evidence, notes, rstatus,
                )
                _clear_query_cache(q)
                result["review_status"] = rstatus
                _show_save_result(result)
            except Exception as exc:
                conn.rollback()
                st.error(f"SAVE FAILED: {exc}")
            finally:
                conn.close()

    st.divider()
    st.subheader("Add Manual Record")
    field = st.selectbox("Field", CURATION_FIELDS + ["(other)"],
                         key="mc_field")
    if field == "(other)":
        field = st.text_input("Custom field name", key="mc_custom")
    if not field:
        return
    value = st.text_input("Value", key="mc_value")
    stype = st.selectbox("Source type", SOURCE_TYPES, key="mc_stype")
    c1, c2 = st.columns(2)
    spaper = c1.text_input("Paper title", key="mc_paper")
    sdoi = c2.text_input("DOI", key="mc_doi")
    spmid = c1.text_input("PMID", key="mc_pmid")
    stable = c2.text_input("Source table", key="mc_table")
    sfile = c1.text_input("Source file", key="mc_file")
    surl = c2.text_input("Source URL", key="mc_url")
    evidence = st.text_area("Evidence", key="mc_evidence", height=68)
    notes = st.text_area("Notes", key="mc_notes", height=68)
    rstatus = st.selectbox("Review status", REVIEW_STATUSES,
                           key="mc_rstatus")

    # conflict check
    existing = q(
        "SELECT id, value, review_status FROM manual_metadata "
        "WHERE sample_id=? AND field=?", [sid, field])
    if not existing.empty:
        diff = existing[existing["value"] != value]
        if not diff.empty:
            st.warning(
                f"CONFLICT: {len(diff)} existing record(s) for "
                f"{sid}/{field} with different value(s). "
                "Saving is still allowed.")

    with st.expander("Preview record"):
        st.json({
            "sample_id": sid, "field": field, "value": value,
            "source_type": stype, "source_paper": spaper,
            "source_doi": sdoi, "source_pmid": spmid,
            "source_table": stable, "review_status": rstatus,
        })

    if st.button("Save manual record", type="primary"):
        if not value:
            st.error("Value is required")
            return
        conn = get_write_conn()
        try:
            result = _save_one_manual(
                conn, sid, field, value, stype,
                spaper, sdoi, spmid, stable, sfile, surl,
                evidence, notes, rstatus,
            )
            _clear_query_cache(q)
            result["review_status"] = rstatus
            _show_save_result(result)
        except Exception as exc:
            conn.rollback()
            st.error(f"SAVE FAILED: {exc}")
        finally:
            conn.close()

def _render_batch(q, get_write_conn):
    previous_result = st.session_state.pop("bp_last_save_result", None)
    if previous_result:
        _show_save_result(previous_result)

    bps = q("SELECT DISTINCT bioproject_accession FROM samples "
            "WHERE bioproject_accession IS NOT NULL "
            "ORDER BY bioproject_accession")
    bp = st.selectbox("BioProject", bps["bioproject_accession"].tolist(),
                      key="bp_sel")
    if not bp:
        return

    manual_fields = list(BATCH_FIELDS)
    placeholders = ",".join("?" for _ in manual_fields)
    provenance_row = q(
        "SELECT mm.source_type, mm.source_paper, mm.source_doi, "
        "mm.source_pmid, mm.source_table, mm.source_file, mm.source_url, "
        "mm.evidence, mm.notes, mm.review_status "
        "FROM manual_metadata mm JOIN samples s "
        "ON mm.sample_id=s.sample_id "
        "WHERE s.bioproject_accession=? "
        f"AND mm.field IN ({placeholders}) "
        "ORDER BY mm.updated_at DESC, mm.id DESC LIMIT 1",
        [bp, *manual_fields],
    )
    if provenance_row.empty:
        provenance_defaults = {
            "source_type": SOURCE_TYPES[0],
            "source_paper": "", "source_doi": "", "source_pmid": "",
            "source_table": "", "source_file": "", "source_url": "",
            "evidence": "", "notes": "",
            "review_status": REVIEW_STATUSES[0],
        }
    else:
        provenance_defaults = provenance_row.iloc[0].to_dict()

    st.subheader("Provenance (applies to all records)")
    c1, c2 = st.columns(2)
    default_stype = provenance_defaults["source_type"] or SOURCE_TYPES[0]
    stype_idx = (SOURCE_TYPES.index(default_stype)
                 if default_stype in SOURCE_TYPES else 0)
    stype = c1.selectbox(
        "Source type", SOURCE_TYPES, index=stype_idx, key=f"bp_stype_{bp}")
    default_status = (provenance_defaults["review_status"]
                      or REVIEW_STATUSES[0])
    rstatus_idx = (REVIEW_STATUSES.index(default_status)
                   if default_status in REVIEW_STATUSES else 0)
    rstatus = c2.selectbox(
        "Review status", REVIEW_STATUSES, index=rstatus_idx, key=f"bp_rs_{bp}")
    spaper = c1.text_input(
        "Paper title", value=provenance_defaults["source_paper"] or "",
        key=f"bp_paper_{bp}")
    sdoi = c2.text_input(
        "DOI", value=provenance_defaults["source_doi"] or "",
        key=f"bp_doi_{bp}")
    spmid = c1.text_input(
        "PMID", value=provenance_defaults["source_pmid"] or "",
        key=f"bp_pmid_{bp}")
    stable = c2.text_input(
        "Source table", value=provenance_defaults["source_table"] or "",
        key=f"bp_table_{bp}")
    sfile = c1.text_input(
        "Source file", value=provenance_defaults["source_file"] or "",
        key=f"bp_file_{bp}")
    surl = c2.text_input(
        "Source URL", value=provenance_defaults["source_url"] or "",
        key=f"bp_url_{bp}")
    evidence = st.text_area(
        "Evidence", value=provenance_defaults["evidence"] or "",
        key=f"bp_evidence_{bp}", height=68)
    notes = st.text_input(
        "Notes", value=provenance_defaults["notes"] or "",
        key=f"bp_notes_{bp}")

    st.divider()
    samples = q(
        "SELECT s.sample_id, s.strain, "
        "COALESCE(NULLIF(sm.organism_name, ''), s.organism_name) "
        "AS current_organism, "
        "sm.taxid AS current_taxid, "
        "sm.host_species AS current_host, "
        "sm.country AS current_country, "
        "sm.admin1 AS current_region, "
        "sm.collection_year AS current_year "
        "FROM samples s "
        "LEFT JOIN sample_metadata sm ON s.sample_id=sm.sample_id "
        "WHERE s.bioproject_accession=? ORDER BY s.sample_id", [bp])
    if samples.empty:
        st.warning("No samples in this BioProject")
        return

    typing = q(
        "SELECT it.sample_id, it.typing_scheme, it.typing_value "
        "FROM isolate_typing it JOIN samples s "
        "ON it.sample_id=s.sample_id "
        "WHERE s.bioproject_accession=?", [bp])
    phylo_map, seq_map = {}, {}
    if not typing.empty:
        for _, r in typing.iterrows():
            if r["typing_scheme"] == "phylotype":
                phylo_map[r["sample_id"]] = r["typing_value"]
            elif r["typing_scheme"] == "sequevar":
                seq_map[r["sample_id"]] = r["typing_value"]
    samples["current_phylotype"] = (
        samples["sample_id"].map(phylo_map).fillna(""))
    samples["current_sequevar"] = (
        samples["sample_id"].map(seq_map).fillna(""))

    manual = q(
        "SELECT mm.sample_id, mm.value, mm.updated_at, mm.id "
        ", mm.field, mm.review_status "
        "FROM manual_metadata mm JOIN samples s "
        "ON mm.sample_id=s.sample_id "
        "WHERE s.bioproject_accession=? "
        f"AND mm.field IN ({placeholders}) "
        "ORDER BY mm.sample_id, mm.field, mm.updated_at DESC, mm.id DESC",
        [bp, *manual_fields])
    manual_map = {}
    if not manual.empty:
        latest = manual.drop_duplicates(
            subset=["sample_id", "field"], keep="first")
        for _, r in latest.iterrows():
            manual_map[(r["sample_id"], r["field"])] = r.to_dict()
    for field, col in BATCH_FIELDS.items():
        samples[col] = samples["sample_id"].apply(
            lambda sid, f=field: manual_map.get(
                (sid, f), {}).get("value", ""))
    samples = samples.fillna("")
    st.write(f"**{len(samples)}** samples in {bp}")

    col_cfg = {}
    for c in ["sample_id", "strain", "current_organism", "current_taxid",
              "current_host", "current_country",
              "current_region", "current_year",
              "current_phylotype", "current_sequevar"]:
        col_cfg[c] = st.column_config.TextColumn(c, disabled=True)
    col_cfg["current_organism"] = st.column_config.TextColumn(
        "current_organism", disabled=True, width="large")
    col_cfg["manual_organism"] = st.column_config.TextColumn(
        "manual_organism", width="large")
    for col in BATCH_FIELDS.values():
        if col != "manual_organism":
            col_cfg[col] = st.column_config.TextColumn(col)

    original = samples.copy()
    edited = st.data_editor(
        samples, hide_index=True, use_container_width=True,
        column_config=col_cfg, num_rows="fixed",
        key="bp_editor", height=500)

    changes = []
    for idx in range(len(edited)):
        sid = edited.iloc[idx]["sample_id"]
        for field, col in BATCH_FIELDS.items():
            old_val = str(original.iloc[idx][col]).strip()
            new_val = str(edited.iloc[idx][col]).strip()
            existing = manual_map.get((sid, field))
            status_changed = (
                existing is not None
                and (existing.get("review_status") or REVIEW_STATUSES[0])
                != rstatus
            )
            if new_val and (new_val != old_val or status_changed):
                changes.append({"sample_id": sid, "field": field,
                                "old": old_val, "new": new_val})

    pending_bp = st.session_state.get("bp_pending_bioproject")
    if pending_bp and pending_bp != bp:
        for key in (
            "bp_pending_changes", "bp_pending_provenance",
            "bp_pending_bioproject",
        ):
            st.session_state.pop(key, None)

    if changes and st.button("Preview changes", key="bp_preview"):
        st.session_state["bp_pending_changes"] = changes
        st.session_state["bp_pending_provenance"] = {
            "source_type": stype,
            "source_paper": spaper or None,
            "source_doi": sdoi or None,
            "source_pmid": spmid or None,
            "source_table": stable or None,
            "source_file": sfile or None,
            "source_url": surl or None,
            "evidence": evidence or None,
            "notes": notes or None,
            "review_status": rstatus,
        }
        st.session_state["bp_pending_bioproject"] = bp
        st.rerun()

    pending = st.session_state.get("bp_pending_changes")
    pending_provenance = st.session_state.get("bp_pending_provenance")
    if not pending or not pending_provenance:
        st.info("Edit cells above, then preview changes.")
        return

    ch = pending
    n_samp = len(set(c["sample_id"] for c in ch))
    n_new = sum(1 for c in ch if not c["old"])
    n_upd = sum(1 for c in ch if c["old"])
    st.write(f"**{len(ch)}** field changes across "
             f"**{n_samp}** samples ({n_new} new, {n_upd} updates)")
    st.dataframe(pd.DataFrame(ch), hide_index=True,
                 use_container_width=True)

    if st.button("Confirm Save", type="primary", key="bp_confirm"):
        conn = get_write_conn()
        try:
            result = _save_manual_changes(
                conn, ch, pending_provenance)
            result["review_status"] = pending_provenance["review_status"]
            _clear_query_cache(q)
            st.session_state["bp_last_save_result"] = result
            for key in (
                "bp_pending_changes", "bp_pending_provenance",
                "bp_pending_bioproject", "bp_editor",
            ):
                st.session_state.pop(key, None)
            st.rerun()
        except Exception as exc:
            conn.rollback()
            st.error(f"SAVE FAILED: {exc}")
        finally:
            conn.close()


def render(q, scalar, get_write_conn):
    st.title("Manual Curation")
    mode = st.radio("Mode", ["Single Sample", "BioProject Batch"],
                    horizontal=True)
    if mode == "Single Sample":
        _render_single(q, get_write_conn)
    else:
        _render_batch(q, get_write_conn)
