"""BioProjects page."""
import streamlit as st
import pandas as pd


def render(q, scalar):
    st.title("BioProjects")
    bps = q("""SELECT bp.bioproject_accession,
        COUNT(DISTINCT sb.sample_id) AS n_samples,
        bp.n_unique_strains, bp.bioproject_title, bp.pmid, bp.doi,
        bp.literature_status
        FROM bioprojects bp
        LEFT JOIN sample_bioprojects sb
          ON sb.bioproject_accession = bp.bioproject_accession
        GROUP BY bp.bioproject_accession
        ORDER BY n_samples DESC""")
    st.write(f"**{len(bps)}** BioProjects")
    st.dataframe(bps, hide_index=True, use_container_width=True, height=400)
    st.divider()
    bp_id = st.selectbox("Select BioProject", bps["bioproject_accession"].tolist())
    if not bp_id: return
    st.subheader(f"BioProject: {bp_id}")
    info = q("SELECT * FROM bioprojects WHERE bioproject_accession = ?", [bp_id])
    if not info.empty:
        r = info.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Samples", r["n_samples"])
        c2.metric("Unique Strains", r["n_unique_strains"])
        c3.metric("Literature Status", r["literature_status"] or "N/A")
    samps = q("""SELECT s.sample_id, s.strain, s.organism_name
        FROM sample_bioprojects sb JOIN samples s ON s.sample_id=sb.sample_id
        WHERE sb.bioproject_accession = ? ORDER BY s.sample_id""", [bp_id])
    st.write(f"**Samples** ({len(samps)}):")
    st.dataframe(samps, hide_index=True)
    pubs = q("""SELECT paper_title, pmid, doi, relation_type, confidence
        FROM publications WHERE bioproject_accession = ?""", [bp_id])
    if not pubs.empty:
        st.write(f"**Publications** ({len(pubs)}):")
        st.dataframe(pubs, hide_index=True)
    mlr = q("""SELECT review_priority, manual_review_status,
        best_candidate_title, metadata_candidate_count,
        typing_candidate_count, phenotype_candidate_count
        FROM manual_literature_review
        WHERE bioproject_accession = ?""", [bp_id])
    if not mlr.empty:
        st.write("**Manual Literature Review**:")
        st.dataframe(mlr, hide_index=True)

