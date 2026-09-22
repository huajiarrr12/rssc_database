"""Strain Browser -- main sample exploration page."""
import streamlit as st
import pandas as pd


# Search mode -> SQL column mapping
_SEARCH_COLS = {
    "sample_id": "sample_id",
    "BioSample": "biosample_accession",
    "strain": "strain",
    "BioProject": "bioproject_accession",
    "assembly": "preferred_assembly",
}

_RESULTS_COLS = [
    "sample_id", "strain", "organism_name",
    "preferred_assembly", "bioproject_accession", "country",
]


def _fmt(val, decimals=1):
    if val is None or pd.isna(val):
        return "—"
    try:
        return f"{float(val):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def _v(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    return val

def render(q, scalar):
    st.title("Strain Browser")

    mode = st.radio("Search by", list(_SEARCH_COLS.keys()), horizontal=True)
    term = st.text_input(
        f"Search {mode}",
        placeholder=f"Enter {mode} (supports % wildcards)",
    )

    if not term:
        st.info("Enter a search term above, or use **%** to browse all.")
        return

    col = _SEARCH_COLS[mode]
    sql = f"SELECT * FROM samples WHERE {col} LIKE ? ORDER BY sample_id"
    results = q(sql, params=[f"%{term}%"])

    if results.empty:
        st.warning(f"No samples matched **{term}** in `{col}`.")
        return

    st.success(f"Found **{len(results)}** matching sample(s).")
    dcols = [c for c in _RESULTS_COLS if c in results.columns]
    st.dataframe(results[dcols], hide_index=True, use_container_width=True)

    st.divider()
    ids = results["sample_id"].tolist()
    sel = st.selectbox("Select a sample to inspect", ids)
    if not sel:
        return

    tabs = st.tabs([
        "Identity", "Metadata", "Genome QC",
        "Typing", "Phenotypes", "Literature",
    ])
    with tabs[0]:
        _tab_identity(q, sel)
    with tabs[1]:
        _tab_metadata(q, sel)
    with tabs[2]:
        _tab_genome_qc(q, sel)
    with tabs[3]:
        _tab_typing(q, sel)
    with tabs[4]:
        _tab_phenotypes(q, sel)
    with tabs[5]:
        _tab_literature(q, sel)

def _tab_identity(q, sid):
    id_sql = (
        "SELECT sample_id, biosample_accession, strain, isolate, "
        "organism_name, bioproject_accession, preferred_assembly, "
        "genbank_accession, refseq_accession "
        "FROM samples WHERE sample_id = ?"
    )
    row = q(id_sql, params=[sid])
    if row.empty:
        st.warning("Sample not found.")
        return
    r = row.iloc[0]

    c1, c2 = st.columns(2)
    c1.markdown(f"**Sample ID:** {_v(r['sample_id'])}")
    c1.markdown(f"**BioSample:** {_v(r['biosample_accession'])}")
    c1.markdown(f"**Strain:** {_v(r.get('strain'))}")
    c1.markdown(f"**Isolate:** {_v(r.get('isolate'))}")
    c1.markdown(f"**Organism:** {_v(r.get('organism_name'))}")
    c2.markdown(f"**BioProject:** {_v(r.get('bioproject_accession'))}")
    c2.markdown(f"**Preferred Assembly:** {_v(r.get('preferred_assembly'))}")
    c2.markdown(f"**GenBank:** {_v(r.get('genbank_accession'))}")
    c2.markdown(f"**RefSeq:** {_v(r.get('refseq_accession'))}")

    al = q("SELECT assembly_level FROM sample_metadata WHERE sample_id = ?",
           params=[sid])
    if not al.empty and al.iloc[0, 0]:
        c2.markdown(f"**Assembly Level:** {al.iloc[0, 0]}")

    fp = q("SELECT fasta_path FROM sample_fasta_map WHERE sample_id = ?",
           params=[sid])
    if not fp.empty and fp.iloc[0, 0]:
        st.markdown(f"**FASTA path:** `{fp.iloc[0, 0]}`")
    ann = q("SELECT annotation_status FROM sample_annotations WHERE sample_id = ?",
            params=[sid])
    if not ann.empty:
        st.markdown(f"**Annotation status:** {_v(ann.iloc[0, 0])}")

def _tab_metadata(q, sid):
    row = q("SELECT * FROM sample_metadata WHERE sample_id = ?", params=[sid])
    if row.empty:
        st.info("No extended metadata available for this sample.")
        return
    r = row.iloc[0]

    st.subheader("Host & Isolation")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Host species:** {_v(r.get('host_species'))}")
    c1.markdown(f"**Host cultivar:** {_v(r.get('host_cultivar'))}")
    c1.markdown(f"**Isolation source:** {_v(r.get('isolation_source'))}")
    c2.markdown(f"**Host (raw):** {_v(r.get('host_raw'))}")
    c2.markdown(f"**Host source:** {_v(r.get('host_source'))}")

    st.subheader("Geography")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Country:** {_v(r.get('country'))}")
    c1.markdown(f"**Admin1:** {_v(r.get('admin1'))}")
    c1.markdown(f"**Locality:** {_v(r.get('locality'))}")
    c2.markdown(f"**Latitude:** {_v(r.get('latitude'))}")
    c2.markdown(f"**Longitude:** {_v(r.get('longitude'))}")
    c2.markdown(f"**Geo source:** {_v(r.get('geo_source'))}")

    st.subheader("Collection & Sequencing")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Collection year:** {_v(r.get('collection_year'))}")
    c1.markdown(f"**Collection date (raw):** {_v(r.get('collection_date_raw'))}")
    c2.markdown(f"**Sequencing tech:** {_v(r.get('sequencing_tech'))}")
    c2.markdown(f"**Platforms:** {_v(r.get('sequencing_platforms'))}")

    st.subheader("Provenance")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Source database:** {_v(r.get('source_database'))}")
    c1.markdown(f"**Metadata source:** {_v(r.get('metadata_source'))}")
    c2.markdown(f"**Metadata confidence:** {_v(r.get('metadata_confidence'))}")
    c2.markdown(f"**Needs manual review:** {_v(r.get('needs_manual_review'))}")

    with st.expander("Full metadata record"):
        display = r.dropna()
        st.dataframe(
            pd.DataFrame({"Field": display.index, "Value": display.values}),
            hide_index=True, use_container_width=True,
        )

def _tab_genome_qc(q, sid):
    qc_raw = q("SELECT qc_status FROM genome_qc WHERE sample_id = ?",
               params=[sid])
    suppressed = (
        not qc_raw.empty
        and qc_raw.iloc[0, 0] == "SUPPRESSED_ASSEMBLY"
    )
    if suppressed:
        st.warning(
            "This assembly is **SUPPRESSED_ASSEMBLY** "
            "-- QC metrics may be absent or unreliable."
        )
        st.markdown("**QC status:** SUPPRESSED_ASSEMBLY")

    qc_sql = (
        "SELECT g.genome_size, g.num_contigs, g.N50, g.GC_percent, "
        "g.completeness, g.contamination, g.qc_status, g.qc_notes, "
        "g.outlier_flags, "
        "c.qc_class, c.qc_reason, "
        "c.genome_size_outlier, c.gc_outlier, c.contig_outlier, "
        "c.n50_outlier, c.fragmentation_flag, "
        "c.low_completeness_flag, c.high_contamination_flag "
        "FROM genome_qc g "
        "LEFT JOIN genome_qc_classification c "
        "ON g.sample_id = c.sample_id "
        "WHERE g.sample_id = ?"
    )
    data = q(qc_sql, params=[sid])

    if data.empty:
        fallback_sql = (
            "SELECT qc_class, qc_reason, genome_size, num_contigs, "
            "N50, GC_percent, completeness, contamination "
            "FROM genome_qc_classification WHERE sample_id = ?"
        )
        data = q(fallback_sql, params=[sid])
        if data.empty:
            if not suppressed:
                st.info("No genome QC data available for this sample.")
            return

    r = data.iloc[0]

    st.subheader("Assembly Metrics")
    c1, c2, c3 = st.columns(3)
    c1.metric("Genome size (bp)", _fmt(r.get("genome_size"), 0))
    c1.metric("Num contigs", _fmt(r.get("num_contigs"), 0))
    c2.metric("N50", _fmt(r.get("N50"), 0))
    c2.metric("GC %", _fmt(r.get("GC_percent"), 2))
    c3.metric("Completeness %", _fmt(r.get("completeness"), 2))
    c3.metric("Contamination %", _fmt(r.get("contamination"), 2))

    st.subheader("QC Classification")
    qc_class = r.get("qc_class")
    qc_reason = r.get("qc_reason")
    if qc_class and not pd.isna(qc_class):
        st.markdown(f"**QC class:** {qc_class}")
    else:
        st.markdown("**QC class:** —")
    if qc_reason and not pd.isna(qc_reason):
        st.markdown(f"**Reason:** {qc_reason}")

    flag_cols = [
        "genome_size_outlier", "gc_outlier", "contig_outlier",
        "n50_outlier", "fragmentation_flag",
        "low_completeness_flag", "high_contamination_flag",
    ]
    flags = []
    for fc in flag_cols:
        val = r.get(fc)
        if val and not pd.isna(val) and str(val).lower() not in (
            "", "false", "0", "no",
        ):
            flags.append(fc.replace("_", " ").title())
    if flags:
        st.markdown("**Flags:** " + ", ".join(flags))

    notes = r.get("qc_notes")
    oflags = r.get("outlier_flags")
    if notes and not pd.isna(notes):
        st.caption(f"QC notes: {notes}")
    if oflags and not pd.isna(oflags):
        st.caption(f"Outlier flags: {oflags}")

def _tab_typing(q, sid):
    typ_sql = (
        "SELECT typing_scheme, typing_value, confidence, pmid "
        "FROM isolate_typing WHERE sample_id = ? "
        "ORDER BY typing_scheme"
    )
    data = q(typ_sql, params=[sid])
    if data.empty:
        st.info("No typing data available for this sample.")
        return
    st.subheader("Isolate Typing")
    st.dataframe(data, hide_index=True, use_container_width=True)


def _tab_phenotypes(q, sid):
    phe_sql = (
        "SELECT trait, value, unit, host_species, host_cultivar "
        "FROM phenotypes WHERE sample_id = ? "
        "ORDER BY trait"
    )
    data = q(phe_sql, params=[sid])
    if data.empty:
        st.info("No phenotype data available for this sample.")
        return
    st.subheader("Phenotypes")
    st.dataframe(data, hide_index=True, use_container_width=True)


def _tab_literature(q, sid):
    lit_sql = (
        "SELECT field, candidate_value, confidence, pmid, doi, "
        "paper_title, match_method "
        "FROM literature_metadata_candidates WHERE sample_id = ? "
        "ORDER BY field, confidence DESC"
    )
    data = q(lit_sql, params=[sid])
    if data.empty:
        st.info("No literature-derived metadata for this sample.")
        return
    st.subheader("Literature Metadata Candidates")
    st.dataframe(data, hide_index=True, use_container_width=True)