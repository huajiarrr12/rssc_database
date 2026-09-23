"""Phylogeny page — species trees with cluster navigation and metadata coloring.

Data files (bundled with the app, read-only):
    phylogeny/trees/Species{A,B,C}.treefile      Newick core-genome trees
    phylogeny/clusters/Species{A,B,C}_clusters.tsv  sample_id -> cluster assignment

Metadata for tip coloring is read from the resolved_metadata view.
"""
import copy
from io import StringIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from Bio import Phylo
from Bio.Phylo.BaseTree import Tree

PHYLO_DIR = Path(__file__).resolve().parent.parent / "phylogeny"

SPECIES_CONFIG = {
    "SpeciesA — R. pseudosolanacearum": {
        "tree": PHYLO_DIR / "trees" / "SpeciesA.treefile",
        "clusters": PHYLO_DIR / "clusters" / "SpeciesA_clusters.tsv",
    },
    "SpeciesB — R. solanacearum": {
        "tree": PHYLO_DIR / "trees" / "SpeciesB.treefile",
        "clusters": PHYLO_DIR / "clusters" / "SpeciesB_clusters.tsv",
    },
    "SpeciesC — R. syzygii": {
        "tree": PHYLO_DIR / "trees" / "SpeciesC.treefile",
        "clusters": PHYLO_DIR / "clusters" / "SpeciesC_clusters.tsv",
    },
}

METADATA_FIELDS = [
    "phylotype", "sequevar", "host", "country", "collection_year", "qc_class",
]
CONTINUOUS_FIELDS = {"collection_year"}
MISSING_COLOR = "#bdbdbd"

LABEL_STYLES = ["strain (sample_id)", "strain", "sample_id"]


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_newick(species_label):
    path = SPECIES_CONFIG[species_label]["tree"]
    if not path.exists():
        return None
    return path.read_text()


@st.cache_data(show_spinner=False)
def _load_clusters(species_label):
    path = SPECIES_CONFIG[species_label]["clusters"]
    if not path.exists():
        return pd.DataFrame(columns=["sample_id", "cluster"])
    return pd.read_csv(path, sep="\t")


def _parse_tree(newick_text):
    tree = Phylo.read(StringIO(newick_text), "newick")
    # strip IQ-TREE internal support labels ("100/100") — never displayed
    for clade in tree.get_nonterminals():
        clade.name = None
        clade.confidence = None
    return tree


def _load_metadata(q):
    """resolved_metadata: one row per sample, curated fields win."""
    return q(
        "SELECT sample_id, strain, phylotype, sequevar, host, country, "
        "collection_year, qc_class FROM resolved_metadata"
    )


# ---------------------------------------------------------------------------
# Coloring
# ---------------------------------------------------------------------------
def _build_color_map(values, field):
    """Return (color_by_sample, legend_info).

    legend_info is ("categorical", {value: color}) or
    ("continuous", norm, cmap) for a colorbar.
    """
    if field in CONTINUOUS_FIELDS:
        numeric = pd.to_numeric(values, errors="coerce")
        valid = numeric.dropna()
        if valid.empty:
            return ({i: MISSING_COLOR for i in values.index}, None)
        norm = plt.Normalize(float(valid.min()), float(valid.max()))
        cmap = matplotlib.colormaps["viridis"]
        colors = {
            i: (MISSING_COLOR if pd.isna(v) else mcolors.to_hex(cmap(norm(v))))
            for i, v in numeric.items()
        }
        return colors, ("continuous", norm, cmap)

    cats = sorted({str(v) for v in values if pd.notna(v) and str(v) != ""})
    if len(cats) <= 20:
        cmap = matplotlib.colormaps["tab20"]
        palette = {c: mcolors.to_hex(cmap(i % 20)) for i, c in enumerate(cats)}
    else:
        cmap = matplotlib.colormaps["hsv"]
        palette = {
            c: mcolors.to_hex(cmap(i / max(len(cats), 1)))
            for i, c in enumerate(cats)
        }
    colors = {
        i: (palette.get(str(v), MISSING_COLOR) if pd.notna(v) else MISSING_COLOR)
        for i, v in values.items()
    }
    return colors, ("categorical", palette)


def _add_legend(fig, legend_info, field):
    if legend_info is None:
        return
    kind = legend_info[0]
    if kind == "continuous":
        _, norm, cmap = legend_info
        sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
        cbar = fig.colorbar(sm, ax=fig.axes[0], fraction=0.03, pad=0.02)
        cbar.set_label(field)
    else:
        _, palette = legend_info
        handles = [
            mpatches.Patch(color=c, label=str(v)) for v, c in palette.items()
        ]
        if MISSING_COLOR not in palette.values():
            handles.append(mpatches.Patch(color=MISSING_COLOR, label="missing"))
        n = len(handles)
        ncol = 1 if n <= 15 else 2 if n <= 30 else 3
        fig.axes[0].legend(
            handles=handles,
            loc="center left",
            bbox_to_anchor=(1.0, 0.5),
            fontsize=8,
            frameon=False,
            ncol=ncol,
            title=field,
            title_fontsize=9,
        )


# ---------------------------------------------------------------------------
# Tree geometry
# ---------------------------------------------------------------------------
def _circular_coords(tree):
    """Return (theta, radius) dicts keyed by clade for an equal-angle layout."""
    depths = tree.depths()  # clade -> cumulative branch length from root
    tips = tree.get_terminals()
    n = len(tips)
    theta = {}
    for i, tip in enumerate(tips):
        theta[tip] = 2.0 * np.pi * i / n
    for clade in tree.get_nonterminals(order="postorder"):
        kids = clade.clades
        theta[clade] = float(np.mean([theta[k] for k in kids]))
    return theta, depths, tips


def _polar(r, t):
    return r * np.cos(t), r * np.sin(t)


def _draw_circular(tree, tip_colors, tip_labels, show_labels, field, legend_info):
    theta, radius, tips = _circular_coords(tree)
    max_r = max(radius.values()) or 1.0
    label_r = max_r * 1.03

    fig, ax = plt.subplots(figsize=(11, 11))
    ax.set_aspect("equal")
    ax.axis("off")

    # branches: radial segment to each child + arc across children
    for clade in tree.get_nonterminals(order="preorder"):
        r_c = radius[clade]
        kids = clade.clades
        for kid in kids:
            t_k = theta[kid]
            x0, y0 = _polar(r_c, t_k)
            x1, y1 = _polar(radius[kid], t_k)
            ax.plot([x0, x1], [y0, y1], color="#555555", lw=0.6, zorder=1)
        if len(kids) > 1:
            ts = [theta[k] for k in kids]
            arc_ts = np.linspace(min(ts), max(ts), 60)
            xs, ys = _polar(r_c, arc_ts)
            ax.plot(xs, ys, color="#555555", lw=0.6, zorder=1)

    # tips
    for tip in tips:
        x, y = _polar(radius[tip], theta[tip])
        ax.scatter(
            [x], [y],
            s=14 if show_labels else 9,
            color=tip_colors.get(tip.name, MISSING_COLOR),
            zorder=3, linewidths=0,
        )

    if show_labels:
        for tip in tips:
            t = theta[tip]
            x, y = _polar(label_r, t)
            deg = np.degrees(t) % 360
            if 90 < deg < 270:
                rot, ha = deg + 180, "right"
            else:
                rot, ha = deg, "left"
            ax.text(
                x, y, tip_labels.get(tip.name, tip.name),
                rotation=rot, rotation_mode="anchor",
                ha=ha, va="center", fontsize=4, color="#222222",
            )

    pad = max_r * (1.35 if show_labels else 1.12)
    ax.set_xlim(-pad, pad)
    ax.set_ylim(-pad, pad)
    _add_legend(fig, legend_info, field)
    fig.tight_layout()
    return fig


def _draw_rectangular(tree, tip_colors, tip_labels, show_labels, field, legend_info):
    n_tips = tree.count_terminals()
    height = min(60.0, max(4.0, 0.28 * n_tips))
    fig, ax = plt.subplots(figsize=(9, height))

    def label_func(clade):
        return tip_labels.get(clade.name, clade.name or "")

    def color_func(label):
        return tip_colors.get(label, "black")

    Phylo.draw(
        tree,
        axes=ax,
        do_show=False,
        show_confidence=False,
        label_func=label_func if show_labels else lambda c: "",
        label_colors=color_func,
    )
    ax.set_xlabel("substitutions per site", fontsize=9)
    ax.set_yticks([])
    ax.set_ylabel("")
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    _add_legend(fig, legend_info, field)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Cluster subtree extraction
# ---------------------------------------------------------------------------
def _extract_cluster_subtree(tree, member_ids):
    """Root a copy of the tree on a non-member tip, take the member MRCA,
    then prune non-member tips. Returns (subtree, n_pruned_intruders)."""
    t = copy.deepcopy(tree)
    tip_map = {x.name: x for x in t.get_terminals()}
    members = [n for n in member_ids if n in tip_map]
    outsiders = [n for n in tip_map if n not in set(member_ids)]
    if outsiders:
        t.root_with_outgroup(tip_map[outsiders[0]])
        tip_map = {x.name: x for x in t.get_terminals()}
    member_clades = [tip_map[n] for n in members]
    if len(member_clades) == 1:
        sub = Tree(root=copy.deepcopy(member_clades[0]))
        return sub, 0
    mrca = t.common_ancestor(member_clades)
    sub = Tree(root=copy.deepcopy(mrca))
    member_set = set(member_ids)
    n_pruned = 0
    for tip in [x for x in sub.get_terminals() if x.name not in member_set]:
        if sub.prune(tip):
            n_pruned += 1
    for clade in sub.get_nonterminals():
        clade.name = None
        clade.confidence = None
    return sub, n_pruned


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
def _make_tip_labels(sample_ids, meta_by_id, style):
    labels = {}
    for sid in sample_ids:
        row = meta_by_id.get(sid)
        strain = None
        if row is not None:
            strain = row.get("strain")
            if strain is not None and (pd.isna(strain) or str(strain) == ""):
                strain = None
        if style == "sample_id":
            labels[sid] = sid
        elif style == "strain":
            labels[sid] = str(strain) if strain else sid
        else:
            labels[sid] = f"{strain} ({sid})" if strain else sid
    return labels


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def render(q, scalar):
    st.title("Phylogeny")

    if not PHYLO_DIR.exists():
        st.error(f"Phylogeny data directory not found: {PHYLO_DIR}")
        return

    species_label = st.selectbox("Species", list(SPECIES_CONFIG.keys()))
    newick = _load_newick(species_label)
    clusters = _load_clusters(species_label)
    if newick is None or clusters.empty:
        st.error("Tree or cluster file missing for this species.")
        return

    tree = _parse_tree(newick)
    meta = _load_metadata(q)
    meta_by_id = meta.set_index("sample_id").to_dict("index") if not meta.empty else {}

    color_field = st.selectbox("Color tips by", METADATA_FIELDS)

    tab_overview, tab_cluster = st.tabs(
        ["Overview (all strains)", "Cluster view"]
    )

    # ---------------- Overview: full tree, circular ----------------
    with tab_overview:
        all_ids = [t.name for t in tree.get_terminals()]
        st.write(f"**{len(all_ids)}** strains in the full tree")
        st.caption(
            "Circular layout for overall structure only — use the "
            "Cluster view tab to inspect individual clusters with labels."
        )
        show_labels = st.checkbox(
            "Show tip labels", value=False, key="ov_show_labels"
        )
        values = pd.Series(
            {sid: (meta_by_id.get(sid) or {}).get(color_field) for sid in all_ids}
        )
        colors, legend_info = _build_color_map(values, color_field)
        labels = _make_tip_labels(all_ids, meta_by_id, "strain (sample_id)")
        with st.spinner("Drawing tree…"):
            fig = _draw_circular(
                tree, colors, labels, show_labels, color_field, legend_info
            )
            st.pyplot(fig, use_container_width=False)
            plt.close(fig)

    # ---------------- Cluster view: subtree, rectangular ----------------
    with tab_cluster:
        cluster_ids = sorted(clusters["cluster"].dropna().unique())
        sel_cluster = st.selectbox("Cluster", cluster_ids)
        members = clusters.loc[clusters["cluster"] == sel_cluster, "sample_id"].tolist()
        st.write(f"**{len(members)}** strains in **{sel_cluster}**")

        c1, c2 = st.columns(2)
        label_style = c1.radio("Tip label", LABEL_STYLES, horizontal=True)
        show_labels_c = c2.checkbox(
            "Show tip labels", value=True, key="cl_show_labels"
        )

        subtree, n_pruned = _extract_cluster_subtree(tree, set(members))
        if n_pruned:
            st.warning(
                f"{sel_cluster} is not monophyletic in this tree: "
                f"{n_pruned} non-cluster tip(s) were pruned. The plot shows "
                f"the induced subtree (relationships among cluster members only)."
            )

        values = pd.Series(
            {sid: (meta_by_id.get(sid) or {}).get(color_field) for sid in members}
        )
        colors, legend_info = _build_color_map(values, color_field)
        labels = _make_tip_labels(members, meta_by_id, label_style)
        # Bio.Phylo label_colors keys on the *displayed* label
        colors_by_label = {labels[sid]: colors[sid] for sid in members}

        if subtree.count_terminals() < 2:
            st.info("Cluster has fewer than 2 tips in the tree — nothing to draw.")
        else:
            with st.spinner("Drawing subtree…"):
                fig = _draw_rectangular(
                    subtree, colors_by_label, labels, show_labels_c,
                    color_field, legend_info,
                )
                st.pyplot(fig, use_container_width=False)
                plt.close(fig)

        st.divider()
        # downloads
        table = clusters.loc[clusters["cluster"] == sel_cluster, ["sample_id", "cluster"]].copy()
        if not meta.empty:
            table = table.merge(
                meta[
                    ["sample_id", "strain", "phylotype", "sequevar", "host",
                     "country", "collection_year", "qc_class"]
                ],
                on="sample_id", how="left",
            )
        d1, d2 = st.columns(2)
        d1.download_button(
            "Download strain list (CSV)",
            table.to_csv(index=False),
            f"{sel_cluster}_strains.csv",
            "text/csv",
        )
        nwk_buf = StringIO()
        Phylo.write(subtree, nwk_buf, "newick")
        d2.download_button(
            "Download subtree (Newick)",
            nwk_buf.getvalue(),
            f"{sel_cluster}_subtree.nwk",
            "text/plain",
        )
