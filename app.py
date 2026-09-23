#!/usr/bin/env python3
"""RSSC Strain Database Explorer v3."""
import sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = (PROJECT_ROOT / "db" / "strain_db_v3.sqlite").resolve()

st.set_page_config(
    page_title="RSSC Strain Database",
    page_icon="\U0001f9a0",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def _db_uri():
    p = Path(DB_PATH)
    if not p.exists():
        st.error(f"Database not found: {DB_PATH}")
        st.stop()
    return f"file:{p.resolve()}?mode=ro"


@st.cache_data(ttl=300)
def q(sql, params=None):
    conn = sqlite3.connect(_db_uri(), uri=True)
    try:
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    return df


def scalar(sql):
    return q(sql).iloc[0, 0]


def get_write_conn():
    """Return a read-write connection for curation tables."""
    p = Path(DB_PATH)
    if not p.exists():
        st.error(f"Database not found: {DB_PATH}")
        st.stop()
    conn = sqlite3.connect(str(p.resolve()), timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


PAGES = [
    "Overview", "Strain Browser", "Genome QC",
    "Metadata", "Typing", "Phylogeny", "Phenotypes",
    "BioProjects", "Literature",
    "Manual Curation", "Export Data",
]
st.sidebar.title("\U0001f9a0 RSSC Database v3")
page = st.sidebar.radio("Navigate", PAGES)
st.sidebar.divider()
st.sidebar.caption(f"Database: `{DB_PATH}`")
st.sidebar.caption(f"Samples: {scalar('SELECT COUNT(*) FROM samples')}")

from views import overview, strain_browser, genome_qc
from views import metadata, typing, phylogeny, phenotypes
from views import bioprojects, literature
from views import manual_curation, export_data

_map = {
    "Overview": overview, "Strain Browser": strain_browser,
    "Genome QC": genome_qc, "Metadata": metadata,
    "Typing": typing, "Phylogeny": phylogeny, "Phenotypes": phenotypes,
    "BioProjects": bioprojects, "Literature": literature,
    "Manual Curation": manual_curation, "Export Data": export_data,
}

if page in ("Manual Curation", "Phenotypes"):
    _map[page].render(q, scalar, get_write_conn)
else:
    _map[page].render(q, scalar)
