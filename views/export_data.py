"""Export Data page."""
import streamlit as st
import pandas as pd
from pathlib import Path as _Path


def render(q, scalar):
    st.title("Export Data")
    st.caption("All exports are generated in-memory. Nothing is written back.")

    base = q(
        "SELECT rm.*, sfm.fasta_path "
        "FROM resolved_metadata rm "
        "LEFT JOIN sample_fasta_map sfm ON rm.sample_id = sfm.sample_id")

    st.sidebar.subheader("Export Filters")
    qc_vals = sorted(base["qc_class"].dropna().unique())
    qc_sel = st.sidebar.multiselect("QC class", qc_vals,
                                    default=qc_vals, key="exp_qc")
    has_fasta = st.sidebar.checkbox("Has FASTA only", key="exp_fasta")
    bp_filter = st.sidebar.text_input("BioProject filter", key="exp_bp")
    org_vals = sorted(base["organism_name"].dropna().unique())
    org_sel = st.sidebar.multiselect("Organism", org_vals, key="exp_org")
    phylo_vals = sorted(base["phylotype"].dropna().unique())
    phylo_sel = st.sidebar.multiselect("Phylotype", phylo_vals, key="exp_phy")
    host_vals = sorted(base["host"].dropna().unique())
    host_sel = st.sidebar.multiselect("Host", host_vals, key="exp_host")

    filt = base.copy()
    filt = filt[filt["qc_class"].isin(qc_sel) | filt["qc_class"].isna()]
    if has_fasta:
        filt = filt[filt["fasta_path"].notna() & (filt["fasta_path"] != "")]
    if bp_filter:
        filt = filt[filt["bioproject_accession"].str.contains(
            bp_filter, case=False, na=False)]
    if org_sel:
        filt = filt[filt["organism_name"].isin(org_sel)]
    if phylo_sel:
        filt = filt[filt["phylotype"].isin(phylo_sel)]
    if host_sel:
        filt = filt[filt["host"].isin(host_sel)]

    st.write(f"**Selected samples = {len(filt)}**")
    _export_resolved(filt)
    _export_phylogeny(filt)
    _export_pangenome(filt)
    _export_gwas(filt, q)
    _export_phenotypes(q)


def _export_resolved(filt):
    st.subheader("resolved_metadata.csv")
    st.caption("All samples with resolved fields. Includes SUPPRESSED.")
    cols = [c for c in filt.columns if c != "fasta_path"]
    df = filt[cols]
    st.write(f"{len(df)} rows")
    with st.expander("Preview"):
        st.dataframe(df.head(10), hide_index=True, use_container_width=True)
    st.download_button("Download resolved_metadata.csv",
                       df.to_csv(index=False),
                       "resolved_metadata.csv", "text/csv")


def _export_phylogeny(filt):
    st.subheader("phylogeny_metadata.tsv")
    st.caption("Samples with FASTA for phylogenetic analysis / iTOL.")
    df = filt[filt["fasta_path"].notna() & (filt["fasta_path"] != "")]
    cols = ["sample_id", "strain", "biosample_accession",
            "organism_name", "bioproject_accession",
            "preferred_assembly", "host", "country", "region",
            "collection_year", "phylotype", "sequevar",
            "qc_class", "fasta_path"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols]
    st.write(f"{len(out)} rows")
    with st.expander("Preview"):
        st.dataframe(out.head(10), hide_index=True, use_container_width=True)
    tsv = out.to_csv(index=False, sep="\t")
    st.download_button("Download phylogeny_metadata.tsv", tsv,
                       "phylogeny_metadata.tsv", "text/tab-separated-values")


def _export_pangenome(filt):
    st.subheader("pangenome_sample_manifest.tsv")
    st.caption("Manifest for pangenome analysis.")
    df = filt[filt["fasta_path"].notna() & (filt["fasta_path"] != "")]
    pan = df[["sample_id", "strain", "preferred_assembly",
              "qc_class", "fasta_path"]].copy()
    map_path = _Path("phylogeny_input/sample_name_map.tsv")
    if map_path.exists():
        try:
            nm = pd.read_csv(map_path, sep="\t")
            if "sample_id" in nm.columns:
                for c in ["canonical_gff3", "canonical_faa", "canonical_ffn"]:
                    if c in nm.columns:
                        pan = pan.merge(nm[["sample_id", c]],
                                        on="sample_id", how="left")
        except Exception:
            pass
    for c in ["canonical_gff3", "canonical_faa", "canonical_ffn"]:
        if c not in pan.columns:
            pan[c] = ""
    st.write(f"{len(pan)} rows")
    with st.expander("Preview"):
        st.dataframe(pan.head(10), hide_index=True, use_container_width=True)
    tsv = pan.to_csv(index=False, sep="\t")
    st.download_button("Download pangenome_sample_manifest.tsv", tsv,
                       "pangenome_sample_manifest.tsv", "text/tab-separated-values")


def _export_gwas(filt, q):
    st.subheader("GWAS_sample_metadata.tsv")
    st.caption("Resolved metadata for GWAS. Phenotype columns not included.")
    pheno_sids = set(
        q("SELECT DISTINCT sample_id FROM phenotypes")["sample_id"])
    cols = ["sample_id", "strain", "organism_name", "host", "cultivar",
            "country", "region", "collection_year",
            "phylotype", "sequevar", "qc_class"]
    cols = [c for c in cols if c in filt.columns]
    df = filt[cols].copy()
    df["has_phenotype"] = df["sample_id"].isin(pheno_sids)
    st.write(f"{len(df)} rows")
    with st.expander("Preview"):
        st.dataframe(df.head(10), hide_index=True, use_container_width=True)
    tsv = df.to_csv(index=False, sep="\t")
    st.download_button("Download GWAS_sample_metadata.tsv", tsv,
                       "GWAS_sample_metadata.tsv", "text/tab-separated-values")


def _export_phenotypes(q):
    st.subheader("reviewed_phenotypes_long.tsv")
    st.caption("Reviewed manual phenotypes in long format.")
    df = q(
        "SELECT mp.sample_id, s.strain, mp.trait AS trait_name, mp.value, mp.unit, "
        "mp.host_species, mp.host_cultivar, mp.n_inoculated, mp.n_responded, "
        "mp.temperature, mp.dpi, mp.experiment, mp.condition, "
        "mp.notes, mp.source_type, mp.source_paper AS paper_title, "
        "mp.source_doi AS doi, mp.source_pmid AS pmid, mp.source_table, "
        "mp.source_file, mp.source_url, mp.review_status "
        "FROM manual_phenotypes mp "
        "JOIN samples s ON mp.sample_id = s.sample_id "
        "WHERE mp.review_status = 'REVIEWED' "
        "ORDER BY mp.trait, mp.host_species, mp.sample_id")
    if df.empty:
        st.info("No reviewed manual phenotypes yet.")
        return
    df["value_numeric"] = pd.to_numeric(df["value"], errors="coerce")
    df["value_text"] = df["value"]
    df = df[[
        "sample_id", "strain", "trait_name", "value_numeric", "value_text", "unit",
        "host_species", "host_cultivar", "n_inoculated", "n_responded",
        "temperature", "dpi", "experiment", "condition", "notes",
        "source_type", "paper_title", "doi", "pmid", "source_table",
        "source_file", "source_url", "review_status",
    ]]
    st.write(f"{len(df)} rows")
    with st.expander("Preview"):
        st.dataframe(df.head(10), hide_index=True, use_container_width=True)
    tsv = df.to_csv(index=False, sep="\t")
    st.download_button("Download reviewed_phenotypes_long.tsv", tsv,
                       "reviewed_phenotypes_long.tsv",
                       "text/tab-separated-values")
