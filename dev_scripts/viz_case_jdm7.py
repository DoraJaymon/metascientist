"""Visualize JDm7oIcx4Y discovery subgraph for thesis §6.3.

Layout: X = logical column (not linear year), grouped by discovery stage.
Columns: Foundations → Hub → Gold/Seed zone → Search results
Node color = discovery stage. Node size ~ idc.
Edges = citation (A→B means A references B).
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Node definitions ──────────────────────────────────────────────

nodes = [
    # Gold papers
    ("ResNet",        "Deep Residual\nLearning [2015]",        "gold_zone", "search",   105, "gold"),
    ("Highway",       "Highway\nNetworks [2015]",              "gold_zone", "backward",   2, "gold"),
    ("Identity",      "Identity Mappings\nin Deep ResNets [2016]", "gold_zone", "backward", 17, "gold"),
    ("Decoupled",     "Decoupled Neural\nInterfaces [2016]",   "gold_zone", "search",    5, "gold"),
    ("Ensembles",     "Residual Nets ≈\nEnsembles [2016]",     "gold_zone", "forward",   0, "gold"),
    ("GreedyScale",   "Greedy Layerwise\nCan Scale [2018]",    "gold_zone", "forward",   0, "gold"),
    ("HwyUnrolled",   "Highway & ResNets\nUnrolled [2017]",    "gold_zone", "missing",   0, "gold"),

    # Hub / forward seeds
    ("Backprop86",    "Backpropagation\n[Rumelhart 1986]",     "foundation", "hub",  67, "hub"),
    ("LongTermDeps",  "Learning long-term\ndeps [1994]",       "foundation", "hub",  26, "hub"),
    ("BioPlausible",  "Biologically Plausible\nError-Driven [1996]", "foundation", "seed", 17, "seed"),
    ("LSTM",          "LSTM [1997]",                           "foundation", "hub",  52, "hub"),
    ("GreedyLW07",    "Greedy Layer-Wise\nTraining [2007]",    "hub_zone",  "hub",  52, "hub"),

    # Search hits (bridges)
    ("MAN++",         "MAN++ [2025]",                          "search_zone", "search", 0, "bridge"),
    ("BackpropFree",  "Backprop-Free DL\n[2023]",              "search_zone", "search", 0, "bridge"),
    ("DLSurvey",      "DL in Medical\nImaging Survey [2017]",  "search_zone", "search", 0, "bridge"),
]

edges = [
    # Search hits → hubs/gold (backward: these papers' refs led to discoveries)
    ("MAN++",        "ResNet",      "ref"),
    ("MAN++",        "Backprop86",  "ref"),
    ("MAN++",        "GreedyLW07",  "ref"),
    ("BackpropFree", "ResNet",      "ref"),
    ("BackpropFree", "Highway",     "ref"),
    ("BackpropFree", "Identity",    "ref"),
    ("DLSurvey",     "ResNet",      "ref"),
    ("DLSurvey",     "Identity",    "ref"),

    # Gold internal references
    ("Identity",     "ResNet",      "ref"),
    ("Ensembles",    "ResNet",      "fwd"),
    ("Ensembles",    "LongTermDeps","ref"),

    # Gold → hubs
    ("ResNet",       "LSTM",        "ref"),
    ("ResNet",       "LongTermDeps","ref"),
    ("Decoupled",    "Backprop86",  "ref"),
    ("Decoupled",    "LSTM",        "ref"),

    # Forward discovery paths
    ("GreedyScale",  "GreedyLW07",  "fwd"),
    ("GreedyScale",  "Decoupled",   "fwd"),
    ("GreedyScale",  "ResNet",      "fwd"),

    # Hub connections
    ("GreedyLW07",   "Backprop86",  "ref"),
    ("LSTM",         "LongTermDeps","ref"),
    ("BioPlausible", "Backprop86",  "ref"),
]

# ── Colors ────────────────────────────────────────────────────────

stage_colors = {
    "search":   "#4A90D9",
    "backward": "#E8913A",
    "forward":  "#50B86C",
    "hub":      "#9B7DC9",
    "seed":     "#9B7DC9",
    "missing":  "#BBBBBB",
}

role_markers = {
    "gold":   "s",
    "hub":    "o",
    "seed":   "D",
    "bridge": "^",
}

# ── Column-based layout ──────────────────────────────────────────
# 4 logical columns, left to right:
#   foundation (1986-1997) | hub (2007) | gold_zone (2015-2018) | search_zone (2017-2025)

col_x = {
    "foundation":  1.0,
    "hub_zone":    3.8,
    "gold_zone":   7.0,
    "search_zone": 10.5,
}

# Manual Y positions for each node within its column
pos = {
    # Foundation column (old → left)
    "Backprop86":    (col_x["foundation"], 2.5),
    "LongTermDeps":  (col_x["foundation"], 0.0),
    "BioPlausible":  (col_x["foundation"], -2.5),
    "LSTM":          (col_x["foundation"] + 0.8, -1.2),

    # Hub column
    "GreedyLW07":    (col_x["hub_zone"], 0.0),

    # Gold zone — the main area, spread vertically
    "ResNet":        (col_x["gold_zone"], 3.0),
    "Identity":      (col_x["gold_zone"] + 0.8, 1.5),
    "Highway":       (col_x["gold_zone"] - 0.3, -0.2),
    "Decoupled":     (col_x["gold_zone"], -2.0),
    "Ensembles":     (col_x["gold_zone"] + 0.6, -3.5),
    "GreedyScale":   (col_x["gold_zone"] + 1.5, -1.0),
    "HwyUnrolled":   (col_x["gold_zone"] - 0.3, -5.0),

    # Search zone (recent papers, rightmost)
    "MAN++":         (col_x["search_zone"], 1.8),
    "BackpropFree":  (col_x["search_zone"], 0.5),
    "DLSurvey":      (col_x["search_zone"] - 0.3, -1.5),
}

# ── Figure ────────────────────────────────────────────────────────

fig, ax = plt.subplots(1, 1, figsize=(16, 10))

# ── Background bands ─────────────────────────────────────────────

bands = [
    (-0.2, 2.5, "#9B7DC9", 0.06, "Foundations\n(1986–1997)"),
    (2.7,  5.0, "#9B7DC9", 0.06, "Hub\n(2007)"),
    (5.3,  9.5, "#F5F5F5", 0.5,  "Gold Paper Zone\n(2015–2018)"),
    (9.5, 11.8, "#4A90D9", 0.06, "Search Results\n(2017–2025)"),
]
for x0, x1, color, alpha, label in bands:
    ax.axvspan(x0, x1, alpha=alpha, color=color, zorder=0)
    ax.text((x0 + x1) / 2, -6.3, label, ha="center", va="top",
            fontsize=11, color="#888888", style="italic")

# ── Draw edges ────────────────────────────────────────────────────

edge_rad_counter = {}
for src, dst, etype in edges:
    x0, y0 = pos[src]
    x1, y1 = pos[dst]

    if etype == "fwd":
        color = "#2D8B4E"
        lw = 2.2
        ls = (0, (5, 3))
        alpha = 0.75
        rad = 0.12
    else:
        color = "#AAAAAA"
        lw = 1.0
        ls = "-"
        alpha = 0.35
        count = edge_rad_counter.get(dst, 0)
        edge_rad_counter[dst] = count + 1
        rad = 0.04 + count * 0.035

    ax.annotate("",
        xy=(x1, y1), xytext=(x0, y0),
        arrowprops=dict(
            arrowstyle="-|>",
            color=color, lw=lw, linestyle=ls, alpha=alpha,
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=16, shrinkB=16,
        ),
    )

# ── Draw nodes ────────────────────────────────────────────────────

for nid, label, col, stage, idc, role in nodes:
    x, y = pos[nid]
    color = stage_colors[stage]
    marker = role_markers.get(role, "o")

    size = max(320, 90 * np.sqrt(max(idc, 1)) + 160)
    edge_color = "#222222" if role == "gold" else "#666666"
    edge_width = 2.5 if role == "gold" else 1.2

    ax.scatter(x, y, s=size, c=color, marker=marker,
               edgecolors=edge_color, linewidths=edge_width, zorder=5)

    # Label position: alternate above/below based on y
    if y >= 2:
        va, y_off = "bottom", 0.42
    else:
        va, y_off = "top", -0.42

    # Override for specific nodes
    label_overrides = {
        "LSTM": ("bottom", 0.4),
        "BioPlausible": ("top", -0.4),
        "GreedyScale": ("bottom", 0.42),
        "Highway": ("top", -0.42),
        "HwyUnrolled": ("top", -0.42),
        "Ensembles": ("top", -0.42),
    }
    if nid in label_overrides:
        va, y_off = label_overrides[nid]

    ax.text(x, y + y_off, label, fontsize=10, ha="center", va=va, zorder=6,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                      edgecolor="none", alpha=0.85))

    # idc badge for papers with significant hub value
    if idc >= 15:
        if nid == "Identity":
            badge_x, badge_y = x - 0.45, y + 0.05
            badge_ha = "right"
        elif x < 8:
            badge_x, badge_y = x + 0.35, y
            badge_ha = "left"
        else:
            badge_x, badge_y = x - 0.35, y
            badge_ha = "right"
        ax.text(badge_x, badge_y, f"{idc}", fontsize=9, fontweight="bold",
                ha=badge_ha, va="center", color="white", zorder=7,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="#666666",
                          edgecolor="none", alpha=0.8))

# ── Directional annotations ──────────────────────────────────────

ax.annotate("", xy=(0.3, -7.3), xytext=(5.2, -7.3),
            arrowprops=dict(arrowstyle="<-", color="#E8913A", lw=2.5))
ax.text(2.7, -7.7, "← Backward expansion\n(follow references to older work)",
        ha="center", va="top", fontsize=11, color="#E8913A")

ax.annotate("", xy=(10.5, -7.3), xytext=(5.5, -7.3),
            arrowprops=dict(arrowstyle="->", color="#2D8B4E", lw=2.5))
ax.text(8.0, -7.7, "Forward expansion →\n(find citing papers of seeds)",
        ha="center", va="top", fontsize=11, color="#2D8B4E")

# ── Legend ────────────────────────────────────────────────────────

legend_elements = [
    mpatches.Patch(facecolor=stage_colors["search"], label="Found by search"),
    mpatches.Patch(facecolor=stage_colors["backward"], label="Found by backward expansion"),
    mpatches.Patch(facecolor=stage_colors["forward"], label="Found by forward expansion"),
    mpatches.Patch(facecolor=stage_colors["hub"], label="Hub / seed paper"),
    mpatches.Patch(facecolor=stage_colors["missing"], label="Not found"),
    plt.Line2D([0], [0], marker="s", color="w", markerfacecolor="#999",
               markeredgecolor="black", markersize=11, label="Gold paper ■"),
    plt.Line2D([0], [0], marker="^", color="w", markerfacecolor="#999",
               markeredgecolor="#666", markersize=11, label="Bridge paper ▲"),
    plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#9B7DC9",
               markeredgecolor="#666", markersize=11, label="Hub ● (size ∝ idc)"),
    plt.Line2D([0], [0], color="#AAAAAA", lw=1.2, label="Reference edge"),
    plt.Line2D([0], [0], color="#2D8B4E", lw=2.2, ls="--", label="Forward discovery path"),
]
ax.legend(handles=legend_elements, loc="upper right", fontsize=10,
          framealpha=0.95, ncol=1, borderpad=0.8)

# ── Axes ──────────────────────────────────────────────────────────

ax.set_xlim(-0.5, 13.0)
ax.set_ylim(-9.0, 4.8)
ax.set_xticks([])
ax.set_yticks([])
for spine in ax.spines.values():
    spine.set_visible(False)

## Title removed — caption is in the thesis document

plt.tight_layout()
out = "/home/dell/Desktop/metascientist/metasci_outputs/citeflow/viz_jdm7_discovery.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved to {out}")
plt.close()
