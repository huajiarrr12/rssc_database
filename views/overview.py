"""Overview page."""
import streamlit as st


def render(q, scalar):
    st.title("RSSC Strain Database")
    total = scalar("SELECT COUNT(*) FROM samples")
    fasta = scalar("SELECT COUNT(*) FROM sample_fasta_map")
    with_qc = scalar("SELECT COUNT(*) FROM genome_qc_classification")
    suppressed = scalar("SELECT COUNT(*) FROM genome_qc WHERE qc_status = 'SUPPRESSED_ASSEMBLY'")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Samples", total)
    c2.metric("Genome FASTA Available", fasta)
    c3.metric("Genomes with QC", with_qc)
    c4.metric("Suppressed / no FASTA", suppressed)
    st.divider()
    st.subheader("QC Class Distribution")
    qc_dist = q("SELECT qc_class, COUNT(*) as n FROM genome_qc_classification GROUP BY qc_class ORDER BY n DESC")
    st.dataframe(qc_dist, hide_index=True, use_container_width=False)
    st.divider()
    st.subheader("Database Summary")
    bp = scalar("SELECT COUNT(*) FROM bioprojects")
    pub = scalar("SELECT COUNT(*) FROM publications")
    lit = scalar("SELECT COUNT(DISTINCT sample_id) FROM literature_metadata_candidates")
    typ = scalar("SELECT COUNT(DISTINCT sample_id) FROM isolate_typing")
    phe = scalar("SELECT COUNT(DISTINCT sample_id) FROM phenotypes")
    rows = [
        ("BioProjects", bp),
        ("Publications", pub),
        ("Samples with literature metadata", lit),
        ("Samples with typing", typ),
        ("Samples with phenotype", phe),
    ]
    import pandas as pd
    st.dataframe(pd.DataFrame(rows, columns=["Item","Count"]), hide_index=True)

