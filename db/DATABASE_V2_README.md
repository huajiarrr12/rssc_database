# RSSC Strain Database v2

Rebuilt 2026-08-31. Manual curation layer added 2026-09-01.

## Primary Key

`sample_id` = BioSample accession (e.g. SAMN22612246).
One row per biological sample. NOT strain name, NOT assembly accession.

## Table Categories

### SOURCE TABLES (rebuilt from output/ TSVs)

Populated by `init_db_v2.py`. Safe to re-import (drops and recreates).

| Table | Rows | Key |
|-------|------|-----|
| samples | 1135 | PK: sample_id |
| sample_metadata | 1135 | PK/FK: sample_id |
| genome_qc | 1135 | PK/FK: sample_id |
| genome_qc_classification | 1128 | PK/FK: sample_id |
| literature_metadata_candidates | 281 | FK: sample_id |
| isolate_typing | 57 | FK: sample_id |
| phenotypes | 76 | FK: sample_id |
| bioprojects | 191 | PK: bioproject_accession |
| publications | 245 | FK: bioproject_accession |
| manual_literature_review | 191 | FK: bioproject_accession |
| sample_fasta_map | 1128 | PK/FK: sample_id |
| genome_rescue_candidates | 6 | PK/FK: sample_id |
| genome_rescue_read_audit | 6 | FK: sample_id |
| genome_rescue_read_plan | 6 | FK: sample_id |

### CURATION TABLES (preserved across rebuilds)

Human-curated data. **Never dropped** by default rebuild.

| Table | Purpose |
|-------|---------|
| manual_metadata | Manual curation records (field/value per sample) |
| manual_curation_audit | Audit trail for all manual changes |
| manual_phenotypes | Manual phenotype observations (long format) |

### RESOLVED VIEWS (derived, read-only)

| View | Purpose |
|------|---------|
| resolved_metadata | One row per sample, manual REVIEWED > database |
| resolved_metadata_conflicts | Samples with conflicting REVIEWED values |

## Resolved Metadata Priority

For each field in `resolved_metadata`:

1. `manual_metadata` with `review_status = 'REVIEWED'` (highest priority)
2. `sample_metadata` current database value (fallback)

NOT included automatically:
- `literature_metadata_candidates` (must be manually reviewed first)
- `isolate_typing` candidates (must be manually reviewed first)
- `manual_metadata` with `IN_PROGRESS` or `REJECTED` status

If multiple distinct REVIEWED values exist for the same sample+field,
the resolved value is NULL and the conflict appears in
`resolved_metadata_conflicts`.

## Rebuild Safety

Default rebuild (`python init_db_v2.py`):
- Drops and recreates all SOURCE tables
- **Preserves** manual_metadata and manual_curation_audit

Full rebuild (`python init_db_v2.py --rebuild-all`):
- Drops ALL tables including curation data
- **WARNING**: Destroys manually curated data

Verify only: `python init_db_v2.py --verify-only`

## Backup

Before any rebuild, back up the curation tables:

```bash
cp db/strain_db_v2.sqlite db/archive/strain_db_v2_$(date +%Y%m%d_%H%M%S).sqlite
```

Existing archives are in `db/archive/`.

## Streamlit Pages

| Page | Module | Read/Write |
|------|--------|------------|
| Overview | views/overview.py | Read |
| Strain Browser | views/strain_browser.py | Read |
| Genome QC | views/genome_qc.py | Read |
| Metadata | views/metadata.py | Read |
| Typing | views/typing.py | Read |
| Phenotypes | views/phenotypes.py | Read |
| BioProjects | views/bioprojects.py | Read |
| Literature | views/literature.py | Read |
| Manual Curation | views/manual_curation.py | Read + Write (manual_metadata only) |
| Export Data | views/export_data.py | Read |

## NOT in this database (kept as files)

- ANI pairwise results (rssc_database/ani_pairs.tsv)
- LIN codes (in old strain_db.sqlite)
- Pangenome data (in old strain_db.sqlite, covers 350 strains)
- Bakta annotations (in old strain_db.sqlite)
- sourmash signatures (rssc_database/sourmash_out/)
