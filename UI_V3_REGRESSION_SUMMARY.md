# Streamlit v3 UI Regression Summary

Generated: 2026-09-04

## Database path used

Before: `db/strain_db_v2.sqlite` (working-directory relative)
After: `rssc_database/db/strain_db_v3.sqlite` (absolute from `Path(__file__).resolve()`)

## Smoke test result

| Page | Status | Notes |
|---|---|---|
| Overview | PASS | 1602 samples, 1595 FASTA, 1595 QC, 7 suppressed, 206 BioProjects |
| Strain Browser | PASS | old and new samples resolve; FASTA + annotation status displayed |
| Genome QC | PASS | 1595 real QC rows; 7 suppressed reported separately |
| Metadata | PASS | 1602 rows; new467 values present; missing values remain NULL |
| Typing | PASS | `isolate_typing` readable; no schema errors |
| Phenotypes | PASS | 76 historical source phenotype rows visible |
| BioProjects | PASS | 206 rows; sample counts use `sample_bioprojects`; PRJNA1227534 = 57 distinct samples |
| Literature | PASS | `publications` and `manual_literature_review` readable |
| Manual Curation | PASS | all widgets render; no test records written |
| Export Data | PASS | uses v3 default database; no exceptions |

## Results

- App load exceptions: 0
- Per-page exceptions: 0
- SQL/schema errors: 0
- Streamlit local URL: http://localhost:8505
- New467 searches: SAMEA10977830, SAMN61027274, SAMN62149727: all found
- Old1135 searches: SAMD00034391, SAMD00250057, SAMN44820517: all found
- v3 SHA256 before browsing: `d4a2f627a2a84ece5eb675940b9cca7c792c02388e33b3a77cfccb6f454338a9`
- v3 SHA256 after browsing: `d4a2f627a2a84ece5eb675940b9cca7c792c02388e33b3a77cfccb6f454338a9`
- v3 no data changes from smoke testing: TRUE

## Warnings

- Streamlit 1.62 emits deprecation warnings for `use_container_width`; this does not affect v3 functionality.
- `export_data.py` still resolves `phylogeny_input/sample_name_map.tsv` relative to the server working directory. It is not a database issue and was not modified in this round.
