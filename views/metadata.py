"""Metadata page — 4-layer view."""
import streamlit as st
import pandas as pd


def render(q, scalar):
    st.title("Metadata")
    summary = q(
        "SELECT sample_id, strain, organism_name, host_species, "
        "host_cultivar, country, collection_year, "
        "metadata_source, metadata_confidence "
        "FROM sample_metadata ORDER BY sample_id")
    st.dataframe(summary, hide_index=True, use_container_width=True, height=400)
    st.divider()
    sid = st.selectbox("Select sample for detail", summary["sample_id"].tolist())
    if not sid:
        return

    st.subheader("Current Database Metadata")
    row = q("SELECT * FROM sample_metadata WHERE sample_id = ?", [sid])
    if not row.empty:
        r = row.iloc[0]
        fields = [
            ("host_species", "Host"), ("host_cultivar", "Cultivar"),
            ("isolation_source", "Isolation source"),
            ("country", "Country"), ("admin1", "Region"),
            ("locality", "Locality"),
            ("collection_year", "Year"), ("collection_date_raw", "Date"),
            ("metadata_source", "Source"), ("metadata_confidence", "Confidence"),
        ]
        rows = [(lb, r[col]) for col, lb in fields
                if r.get(col) is not None
                and not (isinstance(r.get(col), float) and pd.isna(r.get(col)))]
        if rows:
            st.dataframe(pd.DataFrame(rows, columns=["Field", "Value"]),
                         hide_index=True, use_container_width=True)

    st.subheader("Literature Candidates")
    st.caption("Candidates are NOT automatically applied to metadata.")
    cands = q(
        "SELECT field, candidate_value, confidence, pmid, "
        "paper_title, match_method, needs_manual_review "
        "FROM literature_metadata_candidates "
        "WHERE sample_id = ? ORDER BY field", [sid])
    if cands.empty:
        st.info("No literature candidates for this sample")
    else:
        st.dataframe(cands, hide_index=True, use_container_width=True)

    st.subheader("Reviewed Manual Metadata")
    mm = q(
        "SELECT id, field, value, source_type, source_doi, "
        "source_table, notes, updated_at "
        "FROM manual_metadata "
        "WHERE sample_id = ? AND review_status = 'REVIEWED' "
        "ORDER BY field, updated_at DESC", [sid])
    if mm.empty:
        st.info("No reviewed manual records")
    else:
        st.dataframe(mm, hide_index=True, use_container_width=True)

    st.subheader("Resolved Metadata")
    rm = q("SELECT * FROM resolved_metadata WHERE sample_id = ?", [sid])
    if not rm.empty:
        r = rm.iloc[0]
        res_fields = [
            ("host", "host_source"), ("cultivar", "cultivar_source"),
            ("isolation_source", "isolation_source_source"),
            ("country", "country_source"), ("region", "region_source"),
            ("locality", "locality_source"),
            ("collection_year", "year_source"),
            ("collection_date", None),
            ("phylotype", "phylotype_source"),
            ("sequevar", "sequevar_source"),
            ("qc_class", None),
        ]
        rows = []
        for field, src_col in res_fields:
            val = r.get(field)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                src = r.get(src_col) if src_col else ""
                if src is None or (isinstance(src, float) and pd.isna(src)):
                    src = ""
                rows.append((field, val, src))
        if rows:
            st.dataframe(
                pd.DataFrame(rows, columns=["Field", "Value", "Source"]),
                hide_index=True, use_container_width=True)

    # Conflict check
    conflicts = q(
        "SELECT field, value, source_doi, updated_at "
        "FROM resolved_metadata_conflicts WHERE sample_id = ?", [sid])
    if not conflicts.empty:
        st.warning(f"Conflicts detected in {len(conflicts)} record(s)!")
        st.dataframe(conflicts, hide_index=True, use_container_width=True)
