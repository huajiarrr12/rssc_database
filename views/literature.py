"""Literature page."""
import streamlit as st
import pandas as pd


def render(q, scalar):
    st.title("Literature")
    tab1, tab2 = st.tabs(["Publications", "Manual Literature Review"])
    with tab1:
        pubs = q("""SELECT bioproject_accession, paper_title,
            pmid, doi, relation_type, relation_confidence,
            publication_year, journal, confidence
            FROM publications ORDER BY bioproject_accession""")
        search = st.text_input("Search publications", key="pub_search")
        if search:
            mask = pubs.apply(lambda r: search.lower() in str(r).lower(), axis=1)
            pubs = pubs[mask]
        st.write(f"**{len(pubs)}** publications")
        st.dataframe(pubs, hide_index=True, use_container_width=True)
    with tab2:
        mlr = q("""SELECT bioproject_accession, review_priority,
            manual_review_status, n_samples, best_candidate_title,
            best_candidate_pmid, best_candidate_doi,
            metadata_candidate_count, typing_candidate_count,
            phenotype_candidate_count, manual_notes
            FROM manual_literature_review
            ORDER BY priority_rank""")
        search2 = st.text_input("Search reviews", key="mlr_search")
        if search2:
            mask = mlr.apply(lambda r: search2.lower() in str(r).lower(), axis=1)
            mlr = mlr[mask]
        st.write(f"**{len(mlr)}** BioProjects in review")
        st.dataframe(mlr, hide_index=True, use_container_width=True)

