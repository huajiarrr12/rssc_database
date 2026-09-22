"""Genome QC page."""
import streamlit as st
import pandas as pd


def render(q, scalar):
    st.title("Genome QC")
    suppressed = scalar("SELECT COUNT(*) FROM genome_qc WHERE qc_status='SUPPRESSED_ASSEMBLY'")
    st.caption(f"Suppressed / no genome = {suppressed}")
    df = q("""SELECT sample_id,
        biosample_accession, strain, preferred_assembly,
        genome_size, num_contigs, N50, GC_percent,
        completeness, contamination, qc_class, qc_reason
        FROM genome_qc_classification""")
    st.sidebar.subheader("QC Filters")
    classes = df["qc_class"].dropna().unique().tolist()
    sel_class = st.sidebar.multiselect("QC Class", classes, default=classes)
    df = df[df["qc_class"].isin(sel_class)]
    cmin, cmax = st.sidebar.slider("Completeness", 0.0, 100.0, (0.0, 100.0))
    df = df[(df["completeness"] >= cmin) & (df["completeness"] <= cmax)]
    tmin, tmax = st.sidebar.slider("Contamination", 0.0, 100.0, (0.0, 100.0))
    df = df[(df["contamination"] >= tmin) & (df["contamination"] <= tmax)]
    n50_max = float(df["N50"].max()) if not df.empty else 1e7
    n50r = st.sidebar.slider("N50", 0.0, n50_max, (0.0, n50_max))
    df = df[(df["N50"] >= n50r[0]) & (df["N50"] <= n50r[1])]
    st.write(f"**{len(df)}** samples after filtering")
    st.dataframe(df, hide_index=True, use_container_width=True, height=600)
    csv = df.to_csv(index=False)
    st.download_button("Download CSV", csv, "genome_qc_filtered.csv", "text/csv")

