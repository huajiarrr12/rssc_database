"""Regression coverage for multi-host manual phenotype persistence."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from db.migrate_manual_phenotypes_v3 import migrate_manual_phenotypes
from views.phenotypes import _build_multi_host_records, _save_records_transaction


OLD_MANUAL_PHENOTYPES_SCHEMA = """
CREATE TABLE manual_phenotypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT NOT NULL REFERENCES samples(sample_id),
    trait TEXT NOT NULL,
    value TEXT,
    unit TEXT,
    host_species TEXT,
    host_cultivar TEXT,
    temperature TEXT,
    dpi TEXT,
    experiment TEXT,
    condition TEXT,
    bioproject_accession TEXT,
    source_type TEXT,
    source_paper TEXT,
    source_doi TEXT,
    source_pmid TEXT,
    source_table TEXT,
    source_file TEXT,
    source_url TEXT,
    evidence TEXT,
    notes TEXT,
    review_status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class MultiHostManualPhenotypeTest(unittest.TestCase):
    def test_five_hosts_expand_to_five_long_format_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "manual_phenotypes_test.sqlite"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("CREATE TABLE samples (sample_id TEXT PRIMARY KEY)")
                conn.executescript(OLD_MANUAL_PHENOTYPES_SCHEMA)
                conn.execute("INSERT INTO samples(sample_id) VALUES ('TEST')")
                self.assertEqual(
                    migrate_manual_phenotypes(conn),
                    ["n_inoculated", "n_responded"],
                )

                shared = {
                    "trait": "pathogenic_status",
                    "experiment": "host_range_pathogenicity_assay",
                    "temperature": "28",
                    "dpi": "30",
                    "condition": "soil_soak; root_wounding",
                    "number_of_repeats": "2",
                    "inoculation_method": "soil soak",
                    "inoculum_concentration": "5x10^9 CFU per plant",
                    "source_type": "paper",
                    "source_paper": "Test host range paper",
                    "source_doi": "10.0000/test",
                    "source_pmid": None,
                    "source_table": "Table 1",
                    "source_figure": None,
                    "source_file": "test.pdf",
                    "source_url": None,
                    "evidence": None,
                    "supplementary_notes": (
                        "Pathogenicity was defined as >50% wilted plants."
                    ),
                    "review_status": "IN_PROGRESS",
                }
                panel = pd.DataFrame([
                    ["Tomato", "L390", 30, None, 1, None, "binary", None, None],
                    ["Potato", "Desiree", 30, None, 1, None, "binary", None, None],
                    ["Melon", "Amish", 30, None, 0, None, "binary", None, None],
                    ["Banana", "Cavendish 902", 8, None, 0, None, "binary", None,
                     "Only 8 plants were used."],
                    ["Anthurium", "Fire", 4, None, 0, None, "binary", None, None],
                ], columns=[
                    "host_species", "host_cultivar", "n_inoculated", "n_responded",
                    "value_numeric", "value_text", "unit",
                    "host_specific_condition", "host_specific_notes",
                ])
                records, errors = _build_multi_host_records(
                    "TEST", "TEST", "PRJTEST", shared, panel)
                self.assertEqual(errors, [])
                self.assertEqual(len(records), 5)

                result = _save_records_transaction(conn, records)
                self.assertEqual(result, {
                    "attempted": 5,
                    "inserted": 5,
                    "updated": 0,
                    "verified": 5,
                })
                actual = conn.execute(
                    "SELECT host_species, host_cultivar, n_inoculated, "
                    "n_responded, value, unit, notes "
                    "FROM manual_phenotypes ORDER BY id"
                ).fetchall()
                self.assertEqual(len(actual), 5)
                self.assertEqual(
                    [(row[0], row[2], row[4]) for row in actual],
                    [
                        ("Tomato", 30, "1"),
                        ("Potato", 30, "1"),
                        ("Melon", 30, "0"),
                        ("Banana", 8, "0"),
                        ("Anthurium", 4, "0"),
                    ],
                )
                self.assertTrue(all(row[3] is None for row in actual))
                self.assertIn("Host-specific notes: Only 8 plants were used.", actual[3][6])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
