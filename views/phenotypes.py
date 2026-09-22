"""Phenotypes page - source, manual entry, and reviewed records."""
import datetime
import sqlite3

import pandas as pd
import streamlit as st


SOURCE_TYPES = ["paper", "supplement", "manual_review", "database_correction", "other"]
REVIEW_STATUSES = ["IN_PROGRESS", "REVIEWED", "REJECTED"]
HOST_PANEL_COLUMNS = [
    "host_species",
    "host_cultivar",
    "n_inoculated",
    "n_responded",
    "value_numeric",
    "value_text",
    "unit",
    "host_specific_condition",
    "host_specific_notes",
]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _optional_text(value):
    if value is None or pd.isna(value):
        return None
    value = str(value).strip()
    return value or None


def _optional_count(value, label, row_number, errors):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"Host row {row_number}: {label} must be a whole number.")
        return None
    if number < 0 or not number.is_integer():
        errors.append(f"Host row {row_number}: {label} must be a non-negative whole number.")
        return None
    return int(number)


def _format_numeric(value):
    value = float(value)
    return str(int(value)) if value.is_integer() else format(value, "g")


def _compose_condition(shared_condition, inoculation_method,
                       inoculum_concentration, host_condition):
    parts = []
    if shared_condition:
        parts.append(shared_condition)
    if inoculation_method:
        parts.append(f"Inoculation method: {inoculation_method}")
    if inoculum_concentration:
        parts.append(f"Inoculum concentration: {inoculum_concentration}")
    if host_condition:
        parts.append(f"Host-specific condition: {host_condition}")
    return "\n".join(parts) or None


def _compose_notes(supplementary_notes, number_of_repeats,
                   source_figure, host_notes):
    parts = []
    if supplementary_notes:
        parts.append(f"Supplementary notes: {supplementary_notes}")
    if number_of_repeats:
        parts.append(f"Number of repeats: {number_of_repeats}")
    if source_figure:
        parts.append(f"Source figure: {source_figure}")
    if host_notes:
        parts.append(f"Host-specific notes: {host_notes}")
    return "\n\n".join(parts) or None


def _record_key(record):
    return (
        record["sample_id"],
        record["trait"],
        record["host_species"],
        record["host_cultivar"],
        record["temperature"],
        record["dpi"],
        record["experiment"],
        record["condition"],
        record["source_doi"],
        record["source_table"],
    )


def _upsert_phenotype(conn, record):
    """Insert one long-format record or update its matching provenance context."""
    key_fields = (
        "sample_id", "trait", "host_species", "host_cultivar",
        "temperature", "dpi", "experiment", "condition",
        "source_doi", "source_table",
    )
    where = " AND ".join(f"{field} IS ?" for field in key_fields)
    existing = conn.execute(
        f"SELECT id FROM manual_phenotypes WHERE {where} "
        "ORDER BY updated_at DESC, id DESC LIMIT 1",
        _record_key(record),
    ).fetchone()

    fields = (
        "sample_id", "trait", "value", "unit", "host_species", "host_cultivar",
        "temperature", "dpi", "experiment", "condition",
        "bioproject_accession", "source_type", "source_paper", "source_doi",
        "source_pmid", "source_table", "source_file", "source_url", "evidence",
        "notes", "n_inoculated", "n_responded", "review_status",
    )
    values = tuple(record[field] for field in fields)
    now = _now()
    if existing:
        updates = ", ".join(f"{field}=?" for field in fields if field != "sample_id")
        update_fields = tuple(field for field in fields if field != "sample_id")
        conn.execute(
            f"UPDATE manual_phenotypes SET {updates}, updated_at=? WHERE id=?",
            tuple(record[field] for field in update_fields) + (now, existing[0]),
        )
        return "updated", existing[0]

    placeholders = ",".join("?" for _ in fields)
    cur = conn.execute(
        "INSERT INTO manual_phenotypes "
        f"({','.join(fields)},created_at,updated_at) "
        f"VALUES ({placeholders},?,?)",
        values + (now, now),
    )
    return "inserted", cur.lastrowid


def _save_records_transaction(conn, records):
    """Persist all pending records atomically and verify after commit."""
    if not records:
        raise ValueError("No phenotype records were supplied.")

    actions = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        for record in records:
            action, row_id = _upsert_phenotype(conn, record)
            actions.append((action, row_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    row_ids = [row_id for _, row_id in actions]
    placeholders = ",".join("?" for _ in row_ids)
    verified = conn.execute(
        f"SELECT COUNT(*) FROM manual_phenotypes WHERE id IN ({placeholders})",
        row_ids,
    ).fetchone()[0]
    return {
        "attempted": len(records),
        "inserted": sum(action == "inserted" for action, _ in actions),
        "updated": sum(action == "updated" for action, _ in actions),
        "verified": verified,
    }


def _blank_host_panel():
    return pd.DataFrame(
        [{column: None for column in HOST_PANEL_COLUMNS}],
        columns=HOST_PANEL_COLUMNS,
    )


def _normalise_panel(panel):
    panel = panel.copy()
    for column in HOST_PANEL_COLUMNS:
        if column not in panel.columns:
            panel[column] = None
    return panel[HOST_PANEL_COLUMNS]


def _shared_experiment_fields(prefix, default_trait=""):
    st.subheader("Shared Experiment Information")
    c1, c2 = st.columns(2)
    trait = c1.text_input("Trait name", value=default_trait, key=f"{prefix}_trait")
    experiment = c2.text_input("Experiment", key=f"{prefix}_experiment")
    temperature = c1.text_input("Temperature", key=f"{prefix}_temperature")
    dpi = c2.text_input("DPI", key=f"{prefix}_dpi")
    condition = c1.text_area("Condition", key=f"{prefix}_condition", height=68)
    number_of_repeats = c2.text_input("Number of repeats", key=f"{prefix}_repeats")
    inoculation_method = c1.text_input(
        "Inoculation method", key=f"{prefix}_inoculation_method")
    inoculum_concentration = c2.text_input(
        "Inoculum concentration", key=f"{prefix}_inoculum_concentration")

    st.divider()
    st.subheader("Source and Review")
    source_type = st.selectbox("Source type", SOURCE_TYPES, key=f"{prefix}_source_type")
    c1, c2 = st.columns(2)
    source_paper = c1.text_input("Paper title", key=f"{prefix}_source_paper")
    source_doi = c2.text_input("DOI", key=f"{prefix}_source_doi")
    source_pmid = c1.text_input("PMID", key=f"{prefix}_source_pmid")
    source_table = c2.text_input("Source table", key=f"{prefix}_source_table")
    source_figure = c1.text_input("Source figure", key=f"{prefix}_source_figure")
    source_file = c2.text_input("Source file", key=f"{prefix}_source_file")
    source_url = c1.text_input("Source URL", key=f"{prefix}_source_url")
    evidence = c2.text_area("Evidence", key=f"{prefix}_evidence", height=68)
    supplementary_notes = st.text_area(
        "Supplementary notes", key=f"{prefix}_supplementary_notes", height=110)
    review_status = st.selectbox(
        "Review status", REVIEW_STATUSES, key=f"{prefix}_review_status")

    return {
        "trait": _optional_text(trait),
        "experiment": _optional_text(experiment),
        "temperature": _optional_text(temperature),
        "dpi": _optional_text(dpi),
        "condition": _optional_text(condition),
        "number_of_repeats": _optional_text(number_of_repeats),
        "inoculation_method": _optional_text(inoculation_method),
        "inoculum_concentration": _optional_text(inoculum_concentration),
        "source_type": _optional_text(source_type),
        "source_paper": _optional_text(source_paper),
        "source_doi": _optional_text(source_doi),
        "source_pmid": _optional_text(source_pmid),
        "source_table": _optional_text(source_table),
        "source_figure": _optional_text(source_figure),
        "source_file": _optional_text(source_file),
        "source_url": _optional_text(source_url),
        "evidence": _optional_text(evidence),
        "supplementary_notes": _optional_text(supplementary_notes),
        "review_status": review_status,
    }


def _build_multi_host_records(sample_id, strain, bioproject_accession,
                              shared, panel):
    errors = []
    if not shared["trait"]:
        errors.append("Trait name is required.")

    records = []
    seen_contexts = set()
    for index, row in _normalise_panel(panel).iterrows():
        row_number = index + 1
        host_species = _optional_text(row["host_species"])
        if not host_species:
            continue
        host_cultivar = _optional_text(row["host_cultivar"])
        host_condition = _optional_text(row["host_specific_condition"])
        host_notes = _optional_text(row["host_specific_notes"])
        value_numeric = row["value_numeric"]
        value_text = _optional_text(row["value_text"])
        has_numeric = not (
            value_numeric is None or pd.isna(value_numeric)
            or str(value_numeric).strip() == ""
        )
        if has_numeric and value_text:
            errors.append(
                f"Host row {row_number}: use either value_numeric or value_text, not both.")
            continue
        if has_numeric:
            try:
                value = _format_numeric(value_numeric)
            except (TypeError, ValueError):
                errors.append(f"Host row {row_number}: value_numeric must be numeric.")
                continue
        else:
            value = value_text

        n_inoculated = _optional_count(
            row["n_inoculated"], "n_inoculated", row_number, errors)
        n_responded = _optional_count(
            row["n_responded"], "n_responded", row_number, errors)
        if (n_inoculated is not None and n_responded is not None
                and n_responded > n_inoculated):
            errors.append(
                f"Host row {row_number}: n_responded cannot exceed n_inoculated.")

        condition = _compose_condition(
            shared["condition"], shared["inoculation_method"],
            shared["inoculum_concentration"], host_condition)
        context = (host_species, host_cultivar, condition)
        if context in seen_contexts:
            errors.append(
                f"Host row {row_number}: duplicate host/cultivar/condition context.")
        seen_contexts.add(context)

        records.append({
            "sample_id": sample_id,
            "strain": strain,
            "trait": shared["trait"],
            "value": value,
            "unit": _optional_text(row["unit"]),
            "host_species": host_species,
            "host_cultivar": host_cultivar,
            "temperature": shared["temperature"],
            "dpi": shared["dpi"],
            "experiment": shared["experiment"],
            "condition": condition,
            "bioproject_accession": bioproject_accession,
            "source_type": shared["source_type"],
            "source_paper": shared["source_paper"],
            "source_doi": shared["source_doi"],
            "source_pmid": shared["source_pmid"],
            "source_table": shared["source_table"],
            "source_file": shared["source_file"],
            "source_url": shared["source_url"],
            "evidence": shared["evidence"],
            "notes": _compose_notes(
                shared["supplementary_notes"], shared["number_of_repeats"],
                shared["source_figure"], host_notes),
            "n_inoculated": n_inoculated,
            "n_responded": n_responded,
            "review_status": shared["review_status"],
        })

    if not records:
        errors.append("Add at least one host row with host_species.")
    return records, errors


def _split_stored_condition(value):
    """Recover editable shared and host-specific fields from generated text."""
    result = {
        "condition": [],
        "inoculation_method": None,
        "inoculum_concentration": None,
        "host_specific_condition": None,
    }
    for line in (_optional_text(value) or "").splitlines():
        if line.startswith("Inoculation method: "):
            result["inoculation_method"] = line.removeprefix("Inoculation method: ")
        elif line.startswith("Inoculum concentration: "):
            result["inoculum_concentration"] = line.removeprefix(
                "Inoculum concentration: ")
        elif line.startswith("Host-specific condition: "):
            result["host_specific_condition"] = line.removeprefix(
                "Host-specific condition: ")
        else:
            result["condition"].append(line)
    result["condition"] = "\n".join(result["condition"]) or None
    return result


def _split_stored_notes(value):
    result = {
        "supplementary_notes": None,
        "number_of_repeats": None,
        "source_figure": None,
        "host_specific_notes": None,
    }
    for block in (_optional_text(value) or "").split("\n\n"):
        if block.startswith("Supplementary notes: "):
            result["supplementary_notes"] = block.removeprefix(
                "Supplementary notes: ")
        elif block.startswith("Number of repeats: "):
            result["number_of_repeats"] = block.removeprefix("Number of repeats: ")
        elif block.startswith("Source figure: "):
            result["source_figure"] = block.removeprefix("Source figure: ")
        elif block.startswith("Host-specific notes: "):
            result["host_specific_notes"] = block.removeprefix(
                "Host-specific notes: ")
        elif block:
            result["host_specific_notes"] = block
    return result


def _panel_value_fields(value):
    value = _optional_text(value)
    if value is None:
        return None, None
    try:
        return float(value), None
    except ValueError:
        return None, value


def _load_in_progress_experiment(q, selected):
    """Load an existing multi-host IN_PROGRESS group into editable widget state."""
    rows = q(
        "SELECT id, trait, value, unit, host_species, host_cultivar, "
        "n_inoculated, n_responded, temperature, dpi, experiment, condition, "
        "source_type, source_paper, source_doi, source_pmid, source_table, "
        "source_file, source_url, evidence, notes "
        "FROM manual_phenotypes WHERE sample_id=? AND review_status='IN_PROGRESS' "
        "ORDER BY updated_at DESC, id DESC",
        [selected["sample_id"]],
    )
    if rows.empty:
        return

    labels = [
        f"{row.id} | {_optional_text(row.trait) or 'no trait'} | "
        f"{_optional_text(row.host_species) or 'no host'} | "
        f"{_optional_text(row.experiment) or 'no experiment'}"
        for row in rows.itertuples(index=False)
    ]
    selected_label = st.selectbox(
        "Load saved IN_PROGRESS record", labels, key="multi_load_in_progress")
    if not st.button("Load IN_PROGRESS experiment", key="multi_load_button"):
        return

    anchor_id = int(selected_label.split(" | ", maxsplit=1)[0])
    anchor = rows[rows["id"] == anchor_id].iloc[0]
    group = q(
        "SELECT trait, value, unit, host_species, host_cultivar, "
        "n_inoculated, n_responded, temperature, dpi, experiment, condition, "
        "source_type, source_paper, source_doi, source_pmid, source_table, "
        "source_file, source_url, evidence, notes "
        "FROM manual_phenotypes "
        "WHERE sample_id=? AND review_status='IN_PROGRESS' "
        "AND trait IS ? AND temperature IS ? AND dpi IS ? AND experiment IS ? "
        "AND source_doi IS ? AND source_table IS ? "
        "ORDER BY id",
        [
            selected["sample_id"], anchor["trait"], anchor["temperature"],
            anchor["dpi"], anchor["experiment"], anchor["source_doi"],
            anchor["source_table"],
        ],
    )
    first = group.iloc[0]
    first_condition = _split_stored_condition(first["condition"])
    first_notes = _split_stored_notes(first["notes"])

    def set_text_state(key, value):
        st.session_state[key] = _optional_text(value) or ""

    set_text_state("multi_trait", first["trait"])
    set_text_state("multi_experiment", first["experiment"])
    set_text_state("multi_temperature", first["temperature"])
    set_text_state("multi_dpi", first["dpi"])
    set_text_state("multi_condition", first_condition["condition"])
    set_text_state("multi_repeats", first_notes["number_of_repeats"])
    set_text_state("multi_inoculation_method", first_condition["inoculation_method"])
    set_text_state(
        "multi_inoculum_concentration", first_condition["inoculum_concentration"])
    set_text_state("multi_source_paper", first["source_paper"])
    set_text_state("multi_source_doi", first["source_doi"])
    set_text_state("multi_source_pmid", first["source_pmid"])
    set_text_state("multi_source_table", first["source_table"])
    set_text_state("multi_source_figure", first_notes["source_figure"])
    set_text_state("multi_source_file", first["source_file"])
    set_text_state("multi_source_url", first["source_url"])
    set_text_state("multi_evidence", first["evidence"])
    set_text_state("multi_supplementary_notes", first_notes["supplementary_notes"])
    source_type = _optional_text(first["source_type"])
    st.session_state["multi_source_type"] = (
        source_type if source_type in SOURCE_TYPES else "other")
    st.session_state["multi_review_status"] = "IN_PROGRESS"

    panel_rows = []
    for _, row in group.iterrows():
        parsed_condition = _split_stored_condition(row["condition"])
        parsed_notes = _split_stored_notes(row["notes"])
        value_numeric, value_text = _panel_value_fields(row["value"])
        panel_rows.append({
            "host_species": row["host_species"],
            "host_cultivar": row["host_cultivar"],
            "n_inoculated": row["n_inoculated"],
            "n_responded": row["n_responded"],
            "value_numeric": value_numeric,
            "value_text": value_text,
            "unit": row["unit"],
            "host_specific_condition": parsed_condition["host_specific_condition"],
            "host_specific_notes": parsed_notes["host_specific_notes"],
        })
    st.session_state["multi_host_panel_data"] = _normalise_panel(
        pd.DataFrame(panel_rows))
    st.session_state.pop("multi_host_panel_editor", None)
    st.session_state.pop("multi_pending_records", None)
    st.success(f"Loaded {len(panel_rows)} IN_PROGRESS host records.")


def _render_pending_records(records, pending_key, q, get_write_conn):
    if not records:
        return
    preview = pd.DataFrame([{
        "sample_id": record["sample_id"],
        "strain": record["strain"],
        "trait": record["trait"],
        "host_species": record["host_species"],
        "host_cultivar": record["host_cultivar"],
        "n_inoculated": record["n_inoculated"],
        "n_responded": record["n_responded"],
        "value": record["value"],
        "unit": record["unit"],
        "review_status": record["review_status"],
    } for record in records])
    st.write(f"**{len(records)} phenotype records will be created or updated.**")
    st.dataframe(preview, hide_index=True, use_container_width=True)

    if st.button("Confirm Save", type="primary", key=f"{pending_key}_confirm"):
        conn = get_write_conn()
        try:
            result = _save_records_transaction(conn, records)
        except (sqlite3.Error, ValueError) as exc:
            st.error(f"Save failed; transaction rolled back: {exc}")
            return
        finally:
            conn.close()
        q.clear()
        del st.session_state[pending_key]
        st.success(
            "Save verified: "
            f"Attempted {result['attempted']}; "
            f"Inserted {result['inserted']}; "
            f"Updated {result['updated']}; "
            f"Verified persisted {result['verified']}."
        )


def _sample_selector(q, prefix):
    term = st.text_input(
        "Search sample", key=f"{prefix}_search",
        placeholder="sample_id, strain, BioProject")
    if not term:
        st.info("Enter a search term.")
        return None
    pat = f"%{term}%"
    hits = q(
        "SELECT sample_id, strain, bioproject_accession FROM samples "
        "WHERE sample_id LIKE ? OR strain LIKE ? OR bioproject_accession LIKE ? "
        "ORDER BY sample_id",
        [pat, pat, pat],
    )
    if hits.empty:
        st.warning("No matches")
        return None
    sample_id = st.selectbox(
        "Select sample", hits["sample_id"].tolist(), key=f"{prefix}_sample_id")
    selected = hits[hits["sample_id"] == sample_id].iloc[0]
    identity = q(
        "SELECT s.sample_id, s.strain, s.organism_name, s.bioproject_accession, "
        "gc.qc_class FROM samples s "
        "LEFT JOIN genome_qc_classification gc ON s.sample_id=gc.sample_id "
        "WHERE s.sample_id=?",
        [sample_id],
    )
    if not identity.empty:
        row = identity.iloc[0]
        qc_class = row["qc_class"] if pd.notna(row["qc_class"]) else "-"
        st.markdown(f"**{row['strain']}** | {row['bioproject_accession']} | QC: {qc_class}")
    return {
        "sample_id": sample_id,
        "strain": _optional_text(selected["strain"]) or sample_id,
        "bioproject_accession": _optional_text(selected["bioproject_accession"]),
    }


def _show_sample_phenotypes(q, sample_id):
    st.subheader("Source Phenotypes")
    source = q(
        "SELECT trait, value, unit, experiment, condition, confidence "
        "FROM phenotypes WHERE sample_id=? ORDER BY trait",
        [sample_id],
    )
    if source.empty:
        st.info("No source phenotypes")
    else:
        st.dataframe(source, hide_index=True, use_container_width=True)

    st.subheader("Manual Phenotypes")
    manual = q(
        "SELECT id, trait, value, unit, host_species, host_cultivar, "
        "n_inoculated, n_responded, temperature, dpi, experiment, "
        "review_status, source_doi, notes, updated_at "
        "FROM manual_phenotypes WHERE sample_id=? ORDER BY trait, host_species",
        [sample_id],
    )
    if manual.empty:
        st.info("No manual phenotypes")
    else:
        st.dataframe(manual, hide_index=True, use_container_width=True)


def render(q, scalar, get_write_conn):
    st.title("Phenotypes")
    tab1, tab2, tab3 = st.tabs([
        "Source Phenotypes", "Manual Phenotype Entry", "Reviewed Phenotypes"])
    with tab1:
        _tab_source(q)
    with tab2:
        _tab_manual_entry(q, get_write_conn)
    with tab3:
        _tab_reviewed(q)


def _tab_source(q):
    df = q(
        "SELECT sample_id, strain, trait, value, unit, "
        "host_species, host_cultivar, experiment, condition, "
        "bioproject_accession, pmid, doi, paper_title, "
        "sheet_or_table, confidence, needs_manual_review "
        "FROM phenotypes ORDER BY trait, sample_id")
    if df.empty:
        st.info("No source phenotype data")
        return
    c1, c2, c3 = st.columns(3)
    traits = sorted(df["trait"].dropna().unique())
    sel_trait = c1.multiselect("Trait", traits, default=traits, key="sp_trait")
    bps = sorted(df["bioproject_accession"].dropna().unique())
    sel_bp = c2.multiselect("BioProject", bps, default=bps, key="sp_bp")
    hosts_raw = df["host_species"].dropna().unique().tolist()
    has_null_host = df["host_species"].isna().any()
    if hosts_raw:
        sel_host = c3.multiselect("Host", sorted(hosts_raw), default=hosts_raw, key="sp_host")
        mask_host = df["host_species"].isin(sel_host)
        if has_null_host:
            mask_host = mask_host | df["host_species"].isna()
    else:
        mask_host = pd.Series(True, index=df.index)
    search = st.text_input("Search sample_id or strain", key="sp_search")
    filtered = df[
        df["trait"].isin(sel_trait)
        & df["bioproject_accession"].isin(sel_bp)
        & mask_host
    ]
    if search:
        filtered = filtered[
            filtered["sample_id"].str.contains(search, case=False, na=False)
            | filtered["strain"].str.contains(search, case=False, na=False)
        ]
    st.write(f"**{len(filtered)}** records")
    st.dataframe(filtered, hide_index=True, use_container_width=True)
    st.download_button(
        "Download CSV", filtered.to_csv(index=False), "phenotypes_source.csv",
        "text/csv", key="sp_dl")


def _tab_manual_entry(q, get_write_conn):
    mode = st.radio(
        "Entry mode",
        ["Single host", "Multi-host experiment", "BioProject Batch"],
        horizontal=True,
        key="pe_mode",
    )
    if mode == "Single host":
        _single_phenotype(q, get_write_conn)
    elif mode == "Multi-host experiment":
        _multi_host_phenotype(q, get_write_conn)
    else:
        _batch_phenotype(q, get_write_conn)


def _single_phenotype(q, get_write_conn):
    selected = _sample_selector(q, "single")
    if not selected:
        return
    _show_sample_phenotypes(q, selected["sample_id"])
    st.divider()
    st.subheader("Add Manual Phenotype")
    shared = _shared_experiment_fields("single")
    c1, c2, c3 = st.columns(3)
    host_species = c1.text_input("Host species", key="single_host_species")
    host_cultivar = c2.text_input("Host cultivar", key="single_host_cultivar")
    value = c3.text_input("Value", key="single_value")
    c1, c2, c3 = st.columns(3)
    unit = c1.text_input("Unit", key="single_unit")
    n_inoculated = c2.number_input(
        "N inoculated", min_value=0, step=1, value=None, key="single_n_inoculated")
    n_responded = c3.number_input(
        "N responded", min_value=0, step=1, value=None, key="single_n_responded")
    c1, c2 = st.columns(2)
    host_condition = c1.text_input(
        "Host-specific condition", key="single_host_condition")
    host_notes = c2.text_area(
        "Host-specific notes", key="single_host_notes", height=68)

    if st.button("Preview", key="single_preview"):
        panel = pd.DataFrame([{
            "host_species": host_species,
            "host_cultivar": host_cultivar,
            "n_inoculated": n_inoculated,
            "n_responded": n_responded,
            "value_numeric": None,
            "value_text": value,
            "unit": unit,
            "host_specific_condition": host_condition,
            "host_specific_notes": host_notes,
        }])
        records, errors = _build_multi_host_records(
            selected["sample_id"], selected["strain"],
            selected["bioproject_accession"], shared, panel)
        if errors:
            for error in errors:
                st.error(error)
        else:
            st.session_state["single_pending_records"] = records

    pending = st.session_state.get("single_pending_records")
    if pending:
        _render_pending_records(pending, "single_pending_records", q, get_write_conn)


def _host_panel_editor():
    panel_key = "multi_host_panel_data"
    editor_key = "multi_host_panel_editor"
    template_key = "multi_host_panel_template"
    if panel_key not in st.session_state:
        st.session_state[panel_key] = _blank_host_panel()

    controls = st.columns(3)
    if controls[0].button("Save host panel template", key="mh_template_save"):
        st.session_state[template_key] = _normalise_panel(
            st.session_state[panel_key]).copy()
        st.success("Host panel template saved for this session.")
    if controls[1].button(
            "Load host panel template",
            key="mh_template_load",
            disabled=template_key not in st.session_state):
        st.session_state[panel_key] = st.session_state[template_key].copy()
        st.session_state.pop(editor_key, None)
    if controls[2].button("Reset host panel", key="mh_panel_reset"):
        st.session_state[panel_key] = _blank_host_panel()
        st.session_state.pop(editor_key, None)

    column_config = {
        "host_species": st.column_config.TextColumn("Host species", required=True),
        "host_cultivar": st.column_config.TextColumn("Host cultivar"),
        "n_inoculated": st.column_config.NumberColumn(
            "N inoculated", min_value=0, step=1, format="%.0f"),
        "n_responded": st.column_config.NumberColumn(
            "N responded", min_value=0, step=1, format="%.0f"),
        "value_numeric": st.column_config.NumberColumn("Value numeric"),
        "value_text": st.column_config.TextColumn("Value text"),
        "unit": st.column_config.TextColumn("Unit"),
        "host_specific_condition": st.column_config.TextColumn("Host-specific condition"),
        "host_specific_notes": st.column_config.TextColumn("Host-specific notes"),
    }
    edited = st.data_editor(
        _normalise_panel(st.session_state[panel_key]),
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        column_config=column_config,
        key=editor_key,
    )
    st.session_state[panel_key] = _normalise_panel(edited)
    return edited


def _multi_host_phenotype(q, get_write_conn):
    selected = _sample_selector(q, "multi")
    if not selected:
        return
    _show_sample_phenotypes(q, selected["sample_id"])
    _load_in_progress_experiment(q, selected)
    st.divider()
    shared = _shared_experiment_fields("multi")
    st.divider()
    st.subheader("Host panel")
    st.caption(
        "One row is one host context. Leave n_responded blank when a binary "
        "status was reported without an exact response count.")
    panel = _host_panel_editor()

    if st.button("Preview", key="multi_preview"):
        records, errors = _build_multi_host_records(
            selected["sample_id"], selected["strain"],
            selected["bioproject_accession"], shared, panel)
        if errors:
            for error in errors:
                st.error(error)
        else:
            st.session_state["multi_pending_records"] = records

    pending = st.session_state.get("multi_pending_records")
    if pending:
        _render_pending_records(pending, "multi_pending_records", q, get_write_conn)


def _batch_phenotype(q, get_write_conn):
    st.subheader("Provenance and Experiment Conditions")
    c1, c2 = st.columns(2)
    trait = c1.text_input(
        "Trait", key="bp_trait", placeholder="e.g. percent_plants_with_symptoms")
    unit = c2.text_input("Unit", key="bp_unit")
    host_species = c1.text_input("Host species", key="bp_hsp")
    host_cultivar = c2.text_input("Host cultivar", key="bp_hcv")
    temperature = c1.text_input("Temperature", key="bp_temp")
    dpi = c2.text_input("DPI", key="bp_dpi")
    experiment = c1.text_input("Experiment", key="bp_exp")
    condition = c2.text_input("Condition", key="bp_cond")
    st.divider()
    source_type = st.selectbox("Source type", SOURCE_TYPES, key="bp_stype")
    c1, c2 = st.columns(2)
    source_paper = c1.text_input("Paper title", key="bp_paper")
    source_doi = c2.text_input("DOI", key="bp_doi")
    source_pmid = c1.text_input("PMID", key="bp_pmid")
    source_table = c2.text_input("Source table", key="bp_stable")
    source_file = c1.text_input("Source file", key="bp_sfile")
    source_url = c2.text_input("Source URL", key="bp_surl")
    notes = st.text_area("Supplementary notes", key="bp_notes", height=68)
    review_status = st.selectbox("Review status", REVIEW_STATUSES, key="bp_rs")

    bps = q(
        "SELECT DISTINCT bioproject_accession FROM samples "
        "WHERE bioproject_accession IS NOT NULL ORDER BY bioproject_accession")
    bioproject = st.selectbox(
        "BioProject", bps["bioproject_accession"].tolist(), key="bp_sel")
    if not bioproject or not trait:
        st.info("Select a BioProject and enter a trait name above.")
        return

    samples = q(
        "SELECT sample_id, strain FROM samples WHERE bioproject_accession=? "
        "ORDER BY sample_id",
        [bioproject],
    )
    if samples.empty:
        st.warning("No samples")
        return
    manual = q(
        "SELECT sample_id, value FROM manual_phenotypes "
        "WHERE bioproject_accession=? AND trait=? AND review_status!='REJECTED' "
        "ORDER BY updated_at DESC",
        [bioproject, trait],
    )
    manual_values = {}
    for _, row in manual.iterrows():
        manual_values.setdefault(row["sample_id"], row["value"])
    samples["existing_value"] = samples["sample_id"].map(manual_values).fillna("")

    source = q(
        "SELECT sample_id, value FROM phenotypes "
        "WHERE bioproject_accession=? AND trait=?",
        [bioproject, trait],
    )
    source_values = {}
    for _, row in source.iterrows():
        source_values.setdefault(row["sample_id"], []).append(str(row["value"]))
    samples["source_value"] = samples["sample_id"].apply(
        lambda sample_id: "; ".join(source_values.get(sample_id, [])))
    samples["manual_value"] = samples["existing_value"]
    original = samples.copy()
    edited = st.data_editor(
        samples[["sample_id", "strain", "source_value", "existing_value", "manual_value"]],
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "sample_id": st.column_config.TextColumn("sample_id", disabled=True),
            "strain": st.column_config.TextColumn("strain", disabled=True),
            "source_value": st.column_config.TextColumn("source_value", disabled=True),
            "existing_value": st.column_config.TextColumn(
                "existing_manual", disabled=True),
            "manual_value": st.column_config.TextColumn("new_value"),
        },
        key="bp_editor",
        height=500,
    )

    changes = []
    for index in range(len(edited)):
        old_value = _optional_text(original.iloc[index]["manual_value"])
        new_value = _optional_text(edited.iloc[index]["manual_value"])
        if new_value and new_value != old_value:
            changes.append({
                "sample_id": edited.iloc[index]["sample_id"],
                "strain": edited.iloc[index]["strain"],
                "value": new_value,
            })
    if not changes:
        st.info("Fill values in the new_value column, then preview.")
        return

    if st.button("Preview changes", key="bp_preview"):
        records = []
        for change in changes:
            records.append({
                "sample_id": change["sample_id"],
                "strain": change["strain"],
                "trait": _optional_text(trait),
                "value": change["value"],
                "unit": _optional_text(unit),
                "host_species": _optional_text(host_species),
                "host_cultivar": _optional_text(host_cultivar),
                "temperature": _optional_text(temperature),
                "dpi": _optional_text(dpi),
                "experiment": _optional_text(experiment),
                "condition": _optional_text(condition),
                "bioproject_accession": bioproject,
                "source_type": _optional_text(source_type),
                "source_paper": _optional_text(source_paper),
                "source_doi": _optional_text(source_doi),
                "source_pmid": _optional_text(source_pmid),
                "source_table": _optional_text(source_table),
                "source_file": _optional_text(source_file),
                "source_url": _optional_text(source_url),
                "evidence": None,
                "notes": _optional_text(notes),
                "n_inoculated": None,
                "n_responded": None,
                "review_status": review_status,
            })
        st.session_state["batch_pending_records"] = records

    pending = st.session_state.get("batch_pending_records")
    if pending:
        _render_pending_records(pending, "batch_pending_records", q, get_write_conn)


def _tab_reviewed(q):
    df = q(
        "SELECT mp.sample_id, s.strain, mp.trait, mp.value, mp.unit, "
        "mp.host_species, mp.host_cultivar, mp.n_inoculated, mp.n_responded, "
        "mp.temperature, mp.dpi, mp.experiment, mp.condition, "
        "mp.bioproject_accession, mp.source_type, mp.source_paper, "
        "mp.source_doi, mp.source_pmid, mp.source_table, mp.source_file, "
        "mp.source_url, mp.notes, mp.updated_at "
        "FROM manual_phenotypes mp JOIN samples s ON mp.sample_id=s.sample_id "
        "WHERE mp.review_status='REVIEWED' ORDER BY mp.trait, mp.host_species, mp.sample_id")
    if df.empty:
        st.info("No reviewed manual phenotypes yet")
        return
    c1, c2, c3 = st.columns(3)
    traits = sorted(df["trait"].dropna().unique())
    hosts = sorted(df["host_species"].dropna().unique())
    cultivars = sorted(df["host_cultivar"].dropna().unique())
    selected_traits = c1.multiselect(
        "Trait", traits, default=traits, key="rv_trait")
    selected_hosts = c2.multiselect(
        "Host species", hosts, default=hosts, key="rv_host")
    selected_cultivars = c3.multiselect(
        "Host cultivar", cultivars, default=cultivars, key="rv_cultivar")
    search = st.text_input("Search sample", key="rv_search")
    filtered = df[
        df["trait"].isin(selected_traits)
        & (df["host_species"].isin(selected_hosts) | df["host_species"].isna())
        & (df["host_cultivar"].isin(selected_cultivars) | df["host_cultivar"].isna())
    ]
    if search:
        filtered = filtered[
            filtered["sample_id"].str.contains(search, case=False, na=False)
            | filtered["strain"].str.contains(search, case=False, na=False)
        ]
    st.write(f"**{len(filtered)}** reviewed records")
    st.dataframe(filtered, hide_index=True, use_container_width=True)
    with st.expander("Notes / Supplementary notes"):
        st.dataframe(
            filtered[[
                "sample_id", "strain", "trait", "host_species",
                "host_cultivar", "notes",
            ]],
            hide_index=True,
            use_container_width=True,
        )
    st.download_button(
        "Download CSV", filtered.to_csv(index=False), "reviewed_phenotypes.csv",
        "text/csv", key="rv_dl")
