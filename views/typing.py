"""Typing page — candidates + manual + resolved."""
import streamlit as st
import pandas as pd


def render(q, scalar):
    st.title("Isolate Typing")

    tab1, tab2, tab3 = st.tabs([
        "Typing Candidates", "Reviewed Manual Typing", "Resolved Typing"])

    with tab1:
        df = q(
            "SELECT sample_id, strain_paper, typing_scheme, "
            "typing_value, bioproject_accession, confidence, pmid "
            "FROM isolate_typing ORDER BY typing_scheme, typing_value")
        if df.empty:
            st.info("No typing data")
        else:
            schemes = df["typing_scheme"].dropna().unique().tolist()
            sel = st.multiselect("Scheme", schemes, default=schemes)
            search = st.text_input("Search sample", key="typ_search")
            f = df[df["typing_scheme"].isin(sel)]
            if search:
                f = f[f["sample_id"].str.contains(search, case=False, na=False)]
            st.write(f"**{len(f)}** records")
            st.dataframe(f, hide_index=True, use_container_width=True)
            csv = f.to_csv(index=False)
            st.download_button("Download CSV", csv, "typing.csv", "text/csv")
            st.divider()
            st.subheader("By scheme")
            by_s = df.groupby("typing_scheme").size().reset_index(name="n")
            st.dataframe(by_s, hide_index=True)
            st.subheader("By value")
            by_v = df.groupby(["typing_scheme", "typing_value"]).size().reset_index(name="n")
            by_v = by_v.sort_values("n", ascending=False)
            st.dataframe(by_v, hide_index=True)

    with tab2:
        mm = q(
            "SELECT sample_id, field AS typing_scheme, "
            "value AS typing_value, source_doi, source_paper, updated_at "
            "FROM manual_metadata "
            "WHERE field IN ('phylotype','sequevar','sequence_type_ST','lineage') "
            "AND review_status = 'REVIEWED' "
            "ORDER BY field, value")
        if mm.empty:
            st.info("No reviewed manual typing records")
        else:
            st.write(f"**{len(mm)}** reviewed manual typing records")
            st.dataframe(mm, hide_index=True, use_container_width=True)

    with tab3:
        rm = q(
            "SELECT sample_id, strain, phylotype, sequevar, "
            "phylotype_source, sequevar_source "
            "FROM resolved_metadata "
            "WHERE phylotype IS NOT NULL OR sequevar IS NOT NULL "
            "ORDER BY phylotype, sequevar")
        if rm.empty:
            st.info("No resolved typing data yet")
        else:
            phylos = sorted(rm["phylotype"].dropna().unique())
            if phylos:
                pfilt = st.multiselect("Filter phylotype", phylos, key="rt_phylo")
                if pfilt:
                    rm = rm[rm["phylotype"].isin(pfilt)]
            st.write(f"**{len(rm)}** samples with resolved typing")
            st.dataframe(rm, hide_index=True, use_container_width=True)
