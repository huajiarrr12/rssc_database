-- ============================================================================
-- Ralstonia Strain Genomics Database Schema
-- ============================================================================
-- Designed for plant bacterial wilt research
-- Supports: Ralstonia solanacearum species complex (RSSC) comparative genomics
-- Pipeline: Bakta/PGAP → Panaroo → FastANI → IQ-TREE → PhiSpy/VIBRANT →
--           CRISPRCasTyper → MacSyFinder/TXSScan → CheckM2/QUAST
-- ============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================================
-- 1. CORE: Strain metadata
-- ============================================================================

CREATE TABLE IF NOT EXISTS strains (
    strain_id       TEXT PRIMARY KEY,           -- Lab internal ID (e.g., "RS001")
    strain_name     TEXT NOT NULL UNIQUE,        -- Public name (e.g., "GMI1000")
    species         TEXT,                        -- R. solanacearum / R. pseudosolanacearum / R. syzygii
    phylotype       TEXT CHECK(phylotype IN ('I','IIA','IIB','III','IV')),
    sequovar        INTEGER,                     -- Sequovar number
    biovar          INTEGER,                     -- Biovar (1-5)
    host_plant      TEXT,                        -- Isolation host (e.g., "Solanum lycopersicum")
    host_common     TEXT,                        -- Common name (e.g., "tomato")
    isolation_source TEXT,                       -- Tissue/environment (e.g., "root", "stem", "rhizosphere soil")
    geographic_origin TEXT,                      -- Province/State + detail
    country         TEXT,                        -- ISO 3166-1 alpha-3
    latitude        REAL,
    longitude       REAL,
    collection_date TEXT,                        -- ISO 8601 (YYYY-MM-DD or YYYY)
    collector       TEXT,
    is_reference    BOOLEAN DEFAULT FALSE,       -- TRUE for RSSC reference genomes
    is_type_strain  BOOLEAN DEFAULT FALSE,       -- TRUE for type strains
    notes           TEXT,
    date_added      TEXT DEFAULT (datetime('now')),
    last_updated    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_strains_phylotype ON strains(phylotype);
CREATE INDEX idx_strains_species ON strains(species);
CREATE INDEX idx_strains_host ON strains(host_plant);
CREATE INDEX idx_strains_country ON strains(country);

-- ============================================================================
-- 2. ASSEMBLY: Genome assembly information
-- ============================================================================

CREATE TABLE IF NOT EXISTS assemblies (
    assembly_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    assembly_version TEXT NOT NULL DEFAULT 'v1',
    ncbi_accession  TEXT,                        -- GCF_/GCA_ accession
    genbank_accession TEXT,                      -- Individual sequence accessions
    assembly_level  TEXT CHECK(assembly_level IN ('complete','chromosome','scaffold','contig')),
    sequencing_tech TEXT,                        -- e.g., "Illumina NovaSeq", "PacBio HiFi"
    assembly_method TEXT,                        -- e.g., "SPAdes 3.15", "Flye 2.9"
    genome_size_bp  INTEGER,
    num_contigs     INTEGER,
    n50             INTEGER,
    l50             INTEGER,
    gc_content      REAL,                        -- Percentage (0-100)
    num_chromosomes INTEGER,                     -- For complete genomes (typically 2 for RSSC)
    num_plasmids    INTEGER,
    is_current      BOOLEAN DEFAULT TRUE,        -- Mark latest assembly version
    fasta_path      TEXT,                        -- Local filesystem path to assembly FASTA
    date_added      TEXT DEFAULT (datetime('now')),
    UNIQUE(strain_id, assembly_version)
);

CREATE INDEX idx_assemblies_strain ON assemblies(strain_id);
CREATE INDEX idx_assemblies_accession ON assemblies(ncbi_accession);

-- ============================================================================
-- 3. QUALITY: CheckM2 + QUAST metrics
-- ============================================================================

CREATE TABLE IF NOT EXISTS quality_metrics (
    qc_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    assembly_id     INTEGER REFERENCES assemblies(assembly_id) ON DELETE CASCADE,
    -- CheckM2 metrics
    completeness    REAL,                        -- Percentage
    contamination   REAL,                        -- Percentage
    checkm2_model   TEXT,                        -- "gradient_boost" or "neural_network"
    checkm2_version TEXT,
    -- QUAST metrics
    total_length    INTEGER,
    num_contigs_quast INTEGER,                   -- QUAST may count differently
    largest_contig  INTEGER,
    n50_quast       INTEGER,
    n75             INTEGER,
    l50_quast       INTEGER,
    num_n_per_100kb REAL,
    quast_version   TEXT,
    -- Quality verdict
    passes_qc       BOOLEAN GENERATED ALWAYS AS (
                        completeness >= 95.0 AND contamination <= 5.0
                    ) STORED,
    date_added      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_qc_strain ON quality_metrics(strain_id);
CREATE INDEX idx_qc_passes ON quality_metrics(passes_qc);

-- ============================================================================
-- 4. ANNOTATION: Gene-level annotation (Bakta / PGAP)
-- ============================================================================

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    assembly_id     INTEGER REFERENCES assemblies(assembly_id) ON DELETE CASCADE,
    annotation_tool TEXT NOT NULL CHECK(annotation_tool IN ('bakta','pgap')),
    tool_version    TEXT,
    total_genes     INTEGER,
    total_cds       INTEGER,
    total_trna      INTEGER,
    total_rrna      INTEGER,
    total_tmrna     INTEGER,
    total_ncrna     INTEGER,
    total_crispr_arrays INTEGER,
    hypothetical_proteins INTEGER,
    pseudogenes     INTEGER,
    gff_path        TEXT,                        -- Path to GFF3 file
    gbk_path        TEXT,                        -- Path to GenBank file
    faa_path        TEXT,                        -- Path to protein FASTA
    ffn_path        TEXT,                        -- Path to nucleotide FASTA
    date_added      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_annotations_strain ON annotations(strain_id);

-- Individual gene records (for linking to pan-genome)
CREATE TABLE IF NOT EXISTS genes (
    gene_id         TEXT PRIMARY KEY,            -- Bakta/PGAP locus_tag
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    annotation_id   INTEGER REFERENCES annotations(annotation_id) ON DELETE CASCADE,
    contig          TEXT NOT NULL,
    start_pos       INTEGER NOT NULL,
    end_pos         INTEGER NOT NULL,
    strand          TEXT CHECK(strand IN ('+','-')),
    gene_type       TEXT,                        -- CDS, tRNA, rRNA, etc.
    gene_name       TEXT,                        -- Short gene name if assigned
    product         TEXT,                        -- Functional description
    ec_number       TEXT,
    cog_category    TEXT,
    kegg_ko         TEXT,
    pfam_domains    TEXT,                        -- Comma-separated Pfam IDs
    interpro_ids    TEXT,
    go_terms        TEXT,                        -- Comma-separated GO IDs
    eggnog_og       TEXT,                        -- eggNOG orthologous group
    protein_length  INTEGER                      -- Amino acid length for CDS
);

CREATE INDEX idx_genes_strain ON genes(strain_id);
CREATE INDEX idx_genes_name ON genes(gene_name);
CREATE INDEX idx_genes_product ON genes(product);
CREATE INDEX idx_genes_kegg ON genes(kegg_ko);
CREATE INDEX idx_genes_cog ON genes(cog_category);

-- ============================================================================
-- 5. PAN-GENOME: Panaroo results
-- ============================================================================

CREATE TABLE IF NOT EXISTS pangenome_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    panaroo_version TEXT,
    panaroo_mode    TEXT CHECK(panaroo_mode IN ('strict','moderate','sensitive')),
    core_threshold  REAL DEFAULT 0.99,           -- Fraction of strains for core gene
    num_strains     INTEGER,
    total_genes     INTEGER,                     -- Total gene clusters
    core_genes      INTEGER,
    soft_core_genes INTEGER,                     -- 95-99% of strains
    shell_genes     INTEGER,                     -- 15-95% of strains
    cloud_genes     INTEGER,                     -- <15% of strains
    run_date        TEXT DEFAULT (datetime('now')),
    parameters      TEXT                         -- JSON string of all parameters
);

CREATE TABLE IF NOT EXISTS pangenome_genes (
    gene_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES pangenome_runs(run_id) ON DELETE CASCADE,
    cluster_name    TEXT NOT NULL,               -- Panaroo cluster ID (e.g., "group_0001")
    annotation      TEXT,                        -- Consensus annotation
    gene_category   TEXT CHECK(gene_category IN ('core','soft_core','shell','cloud','unique')),
    num_strains     INTEGER,                     -- Number of strains with this gene
    avg_identity    REAL,                        -- Average nucleotide identity within cluster
    avg_length      REAL                         -- Average gene length in cluster
);

CREATE INDEX idx_pangenes_category ON pangenome_genes(gene_category);
CREATE INDEX idx_pangenes_run ON pangenome_genes(run_id);

-- Junction table: which strains have which pan-genome genes
CREATE TABLE IF NOT EXISTS strain_pangenes (
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    gene_id         INTEGER NOT NULL REFERENCES pangenome_genes(gene_id) ON DELETE CASCADE,
    locus_tag       TEXT,                        -- The specific gene ID in this strain
    copy_number     INTEGER DEFAULT 1,           -- Paralogs
    PRIMARY KEY (strain_id, gene_id)
);

CREATE INDEX idx_strain_pangenes_strain ON strain_pangenes(strain_id);
CREATE INDEX idx_strain_pangenes_gene ON strain_pangenes(gene_id);

-- ============================================================================
-- 6. ANI: Average Nucleotide Identity (FastANI)
-- ============================================================================

CREATE TABLE IF NOT EXISTS ani_results (
    ani_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    strain_id_1     TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    strain_id_2     TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    ani_value       REAL NOT NULL,               -- ANI percentage (e.g., 98.5)
    aligned_fraction REAL,                       -- Fraction of genome aligned (AF)
    orthologous_matches INTEGER,                 -- Number of bidirectional fragment mappings
    total_fragments INTEGER,                     -- Total fragments in query
    tool            TEXT DEFAULT 'FastANI',
    tool_version    TEXT,
    run_date        TEXT DEFAULT (datetime('now')),
    UNIQUE(strain_id_1, strain_id_2)
);

-- Note: ANI is directional. Store both A→B and B→A.
CREATE INDEX idx_ani_strain1 ON ani_results(strain_id_1);
CREATE INDEX idx_ani_strain2 ON ani_results(strain_id_2);
CREATE INDEX idx_ani_value ON ani_results(ani_value);

-- ============================================================================
-- 7. PHYLOGENY: Tree information
-- ============================================================================

CREATE TABLE IF NOT EXISTS phylogenies (
    phylo_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tree_name       TEXT NOT NULL,               -- e.g., "core_gene_ml_tree"
    tree_type       TEXT CHECK(tree_type IN ('core_gene','whole_genome','single_gene','snp')),
    method          TEXT,                        -- "ML", "NJ", "Bayesian"
    tool            TEXT DEFAULT 'IQ-TREE',
    tool_version    TEXT,
    substitution_model TEXT,                     -- e.g., "GTR+F+I+G4"
    bootstrap_method TEXT,                       -- "ultrafast", "standard"
    bootstrap_replicates INTEGER,
    alignment_length INTEGER,                    -- Number of sites in alignment
    num_taxa        INTEGER,
    newick          TEXT NOT NULL,               -- Full newick tree string
    run_date        TEXT DEFAULT (datetime('now')),
    parameters      TEXT                         -- JSON string of additional parameters
);

-- Per-node bootstrap values (optional, for detailed queries)
CREATE TABLE IF NOT EXISTS phylogeny_supports (
    support_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    phylo_id        INTEGER NOT NULL REFERENCES phylogenies(phylo_id) ON DELETE CASCADE,
    node_label      TEXT,
    bootstrap_value REAL,
    sh_alrt         REAL                         -- SH-aLRT support value
);

-- ============================================================================
-- 8. T3E: Type III Effectors (Rip proteins)
-- ============================================================================

CREATE TABLE IF NOT EXISTS t3_effectors (
    effector_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    effector_name   TEXT NOT NULL UNIQUE,         -- Ralsto T3E naming: RipA, RipB, etc.
    effector_family TEXT,                         -- Family grouping
    description     TEXT,
    reference_strain TEXT,                        -- Strain where first characterized
    reference_gene  TEXT,                         -- Original locus_tag
    is_hypothetical BOOLEAN DEFAULT FALSE,        -- Hypothetical Rip
    reference_pmid  TEXT                          -- Key publication PMID
);

CREATE TABLE IF NOT EXISTS strain_effectors (
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    effector_id     INTEGER NOT NULL REFERENCES t3_effectors(effector_id) ON DELETE CASCADE,
    locus_tag       TEXT,                        -- Gene ID in this strain
    percent_identity REAL,                       -- To reference sequence
    percent_coverage REAL,                       -- Query coverage
    is_truncated    BOOLEAN DEFAULT FALSE,        -- Pseudogene / truncated copy
    is_split        BOOLEAN DEFAULT FALSE,        -- Split across contigs
    prediction_method TEXT,                       -- e.g., "tBLASTn", "HMMer"
    e_value         REAL,
    notes           TEXT,
    PRIMARY KEY (strain_id, effector_id)
);

CREATE INDEX idx_strain_effectors_strain ON strain_effectors(strain_id);
CREATE INDEX idx_strain_effectors_effector ON strain_effectors(effector_id);

-- ============================================================================
-- 9. PROPHAGES
-- ============================================================================

CREATE TABLE IF NOT EXISTS prophages (
    prophage_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    prediction_tool TEXT CHECK(prediction_tool IN ('PhiSpy','VIBRANT','both')),
    tool_version    TEXT,
    contig          TEXT NOT NULL,
    start_pos       INTEGER NOT NULL,
    end_pos         INTEGER NOT NULL,
    length_bp       INTEGER GENERATED ALWAYS AS (end_pos - start_pos) STORED,
    num_genes       INTEGER,
    phage_genes     INTEGER,                     -- Number of phage-related genes
    bacterial_genes INTEGER,                     -- Number of bacterial genes in region
    integrase_family TEXT,                       -- e.g., "tyrosine", "serine"
    att_site_l      TEXT,                        -- Left attachment site sequence
    att_site_r      TEXT,                        -- Right attachment site sequence
    completeness    TEXT CHECK(completeness IN ('intact','questionable','incomplete')),
    gc_content      REAL,
    closest_phage   TEXT,                        -- Best BLAST hit to known phage
    phispy_score    REAL,                        -- PhiSpy confidence score
    vibrant_quality TEXT                          -- VIBRANT quality category
);

CREATE INDEX idx_prophages_strain ON prophages(strain_id);
CREATE INDEX idx_prophages_completeness ON prophages(completeness);

-- ============================================================================
-- 10. CRISPR-Cas SYSTEMS
-- ============================================================================

CREATE TABLE IF NOT EXISTS crispr_cas (
    crispr_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    tool            TEXT DEFAULT 'CRISPRCasTyper',
    tool_version    TEXT,
    contig          TEXT NOT NULL,
    start_pos       INTEGER,
    end_pos         INTEGER,
    cas_type        TEXT,                        -- e.g., "I-E", "I-F", "II-A"
    cas_subtype     TEXT,
    num_spacers     INTEGER,
    repeat_sequence TEXT,                        -- Consensus repeat
    repeat_length   INTEGER,
    spacer_avg_length REAL,
    has_cas_genes   BOOLEAN DEFAULT TRUE,        -- Orphan arrays lack cas genes
    cas_genes       TEXT,                        -- Comma-separated cas gene names
    evidence_level  TEXT                         -- CRISPRCasTyper evidence level
);

CREATE INDEX idx_crispr_strain ON crispr_cas(strain_id);
CREATE INDEX idx_crispr_type ON crispr_cas(cas_type);

-- ============================================================================
-- 11. ICEs and GENOMIC ISLANDS
-- ============================================================================

CREATE TABLE IF NOT EXISTS mobile_elements (
    element_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    element_type    TEXT CHECK(element_type IN ('ICE','IME','genomic_island','transposon','IS_element')),
    prediction_tool TEXT,
    tool_version    TEXT,
    contig          TEXT NOT NULL,
    start_pos       INTEGER NOT NULL,
    end_pos         INTEGER NOT NULL,
    length_bp       INTEGER GENERATED ALWAYS AS (end_pos - start_pos) STORED,
    num_genes       INTEGER,
    integrase_type  TEXT,
    conjugation_module BOOLEAN,                  -- Has T4SS for self-transfer
    cargo_genes     TEXT,                        -- Notable cargo genes (comma-separated)
    gc_deviation    REAL,                        -- GC% difference from genome average
    closest_known   TEXT,                        -- Best match to known element
    confidence      TEXT                         -- Prediction confidence level
);

CREATE INDEX idx_mge_strain ON mobile_elements(strain_id);
CREATE INDEX idx_mge_type ON mobile_elements(element_type);

-- ============================================================================
-- 12. SECRETION SYSTEMS (MacSyFinder / TXSScan)
-- ============================================================================

CREATE TABLE IF NOT EXISTS secretion_systems (
    ss_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    strain_id       TEXT NOT NULL REFERENCES strains(strain_id) ON DELETE CASCADE,
    system_type     TEXT NOT NULL,               -- T1SS, T2SS, T3SS, T4SS, T5SS, T6SS
    system_subtype  TEXT,                        -- e.g., T3SS_hrp, T6SS-i, T6SS-ii
    prediction_tool TEXT DEFAULT 'MacSyFinder',
    tool_version    TEXT,
    model_name      TEXT,                        -- TXSScan model used
    contig          TEXT,
    start_pos       INTEGER,
    end_pos         INTEGER,
    num_mandatory   INTEGER,                     -- Mandatory genes found
    num_accessory   INTEGER,                     -- Accessory genes found
    num_forbidden   INTEGER,                     -- Forbidden genes found (should be 0)
    total_genes     INTEGER,
    score           REAL,                        -- MacSyFinder score
    decision        TEXT CHECK(decision IN ('positive','ambiguous','negative')),
    genes_detail    TEXT                          -- JSON: [{gene, hit_id, e_value, coverage}]
);

CREATE INDEX idx_ss_strain ON secretion_systems(strain_id);
CREATE INDEX idx_ss_type ON secretion_systems(system_type);

-- ============================================================================
-- 13. USEFUL VIEWS
-- ============================================================================

-- Summary view: one row per strain with key metrics
CREATE VIEW IF NOT EXISTS strain_summary AS
SELECT
    s.strain_id,
    s.strain_name,
    s.species,
    s.phylotype,
    s.host_plant,
    s.country,
    s.is_reference,
    a.ncbi_accession,
    a.genome_size_bp,
    a.gc_content,
    a.num_contigs,
    a.n50,
    a.assembly_level,
    q.completeness,
    q.contamination,
    q.passes_qc,
    an.annotation_tool,
    an.total_cds,
    (SELECT COUNT(*) FROM strain_effectors se WHERE se.strain_id = s.strain_id) as num_effectors,
    (SELECT COUNT(*) FROM prophages p WHERE p.strain_id = s.strain_id) as num_prophages,
    (SELECT COUNT(*) FROM crispr_cas c WHERE c.strain_id = s.strain_id) as num_crispr_arrays,
    (SELECT COUNT(*) FROM mobile_elements m WHERE m.strain_id = s.strain_id) as num_mobile_elements,
    (SELECT COUNT(*) FROM secretion_systems ss
     WHERE ss.strain_id = s.strain_id AND ss.decision = 'positive') as num_secretion_systems
FROM strains s
LEFT JOIN assemblies a ON s.strain_id = a.strain_id AND a.is_current = TRUE
LEFT JOIN quality_metrics q ON s.strain_id = q.strain_id
LEFT JOIN annotations an ON s.strain_id = an.strain_id;

-- T3E presence/absence matrix (pivot-style, long format)
CREATE VIEW IF NOT EXISTS t3e_matrix AS
SELECT
    s.strain_id,
    s.strain_name,
    s.phylotype,
    e.effector_name,
    CASE
        WHEN se.strain_id IS NOT NULL AND se.is_truncated = FALSE THEN 'intact'
        WHEN se.strain_id IS NOT NULL AND se.is_truncated = TRUE THEN 'truncated'
        ELSE 'absent'
    END as status,
    se.percent_identity
FROM strains s
CROSS JOIN t3_effectors e
LEFT JOIN strain_effectors se ON s.strain_id = se.strain_id AND e.effector_id = se.effector_id
ORDER BY s.phylotype, s.strain_name, e.effector_name;

-- Pan-genome category counts per strain
CREATE VIEW IF NOT EXISTS pangenome_summary AS
SELECT
    s.strain_id,
    s.strain_name,
    s.phylotype,
    pr.panaroo_mode,
    SUM(CASE WHEN pg.gene_category = 'core' THEN 1 ELSE 0 END) as core,
    SUM(CASE WHEN pg.gene_category = 'soft_core' THEN 1 ELSE 0 END) as soft_core,
    SUM(CASE WHEN pg.gene_category = 'shell' THEN 1 ELSE 0 END) as shell,
    SUM(CASE WHEN pg.gene_category IN ('cloud','unique') THEN 1 ELSE 0 END) as cloud_unique,
    COUNT(sp.gene_id) as total
FROM strains s
JOIN strain_pangenes sp ON s.strain_id = sp.strain_id
JOIN pangenome_genes pg ON sp.gene_id = pg.gene_id
JOIN pangenome_runs pr ON pg.run_id = pr.run_id
GROUP BY s.strain_id, s.strain_name, s.phylotype, pr.panaroo_mode;

-- Mobile element burden per strain
CREATE VIEW IF NOT EXISTS mobile_element_summary AS
SELECT
    s.strain_id,
    s.strain_name,
    s.phylotype,
    COALESCE(pp.num_prophages, 0) as prophages,
    COALESCE(cc.num_crispr, 0) as crispr_arrays,
    COALESCE(me.num_ices, 0) as ices,
    COALESCE(me2.num_islands, 0) as genomic_islands,
    COALESCE(pp.total_prophage_bp, 0) as total_prophage_bp,
    CASE WHEN a.genome_size_bp > 0
         THEN ROUND(COALESCE(pp.total_prophage_bp, 0) * 100.0 / a.genome_size_bp, 2)
         ELSE NULL
    END as prophage_pct_genome
FROM strains s
LEFT JOIN assemblies a ON s.strain_id = a.strain_id AND a.is_current = TRUE
LEFT JOIN (
    SELECT strain_id, COUNT(*) as num_prophages, SUM(length_bp) as total_prophage_bp
    FROM prophages GROUP BY strain_id
) pp ON s.strain_id = pp.strain_id
LEFT JOIN (
    SELECT strain_id, COUNT(*) as num_crispr
    FROM crispr_cas GROUP BY strain_id
) cc ON s.strain_id = cc.strain_id
LEFT JOIN (
    SELECT strain_id, COUNT(*) as num_ices
    FROM mobile_elements WHERE element_type = 'ICE' GROUP BY strain_id
) me ON s.strain_id = me.strain_id
LEFT JOIN (
    SELECT strain_id, COUNT(*) as num_islands
    FROM mobile_elements WHERE element_type = 'genomic_island' GROUP BY strain_id
) me2 ON s.strain_id = me2.strain_id;

-- Secretion system repertoire per strain
CREATE VIEW IF NOT EXISTS secretion_system_summary AS
SELECT
    s.strain_id,
    s.strain_name,
    s.phylotype,
    ss.system_type,
    COUNT(*) as num_copies,
    GROUP_CONCAT(ss.system_subtype, ', ') as subtypes
FROM strains s
JOIN secretion_systems ss ON s.strain_id = ss.strain_id
WHERE ss.decision = 'positive'
GROUP BY s.strain_id, s.strain_name, s.phylotype, ss.system_type
ORDER BY s.strain_name, ss.system_type;