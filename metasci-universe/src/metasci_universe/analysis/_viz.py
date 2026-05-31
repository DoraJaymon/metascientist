"""Visualization helpers for analysis artifacts.

Plotly is optional. When it is unavailable, the helpers return lightweight
HTML-writable placeholders so analysis workflows can still save JSON, CSV, and
summary artifacts in minimal environments.
"""

from __future__ import annotations

import json
from typing import Any

import networkx as nx
import pandas as pd

try:  # pragma: no cover - exercised only when plotly is installed
    import plotly.express as px
    import plotly.graph_objects as go
except Exception:  # pragma: no cover - exercised in dependency-light test envs
    px = None
    go = None


class FallbackFigure:
    """Small stand-in object with Plotly's write_html surface."""

    def __init__(self, title: str, payload: dict[str, Any] | None = None):
        self.title = title
        self.payload = payload or {}

    def write_html(self, path: str, include_plotlyjs: str | None = None, full_html: bool = True) -> None:
        body = json.dumps(self.payload, ensure_ascii=False, indent=2, default=_json_default)
        html = f"<html><head><meta charset='utf-8'><title>{self.title}</title></head><body><h1>{self.title}</h1><pre>{body}</pre></body></html>"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)


def bar(rows: list[dict[str, Any]], *, x: str, y: str, title: str, orientation: str = "v") -> Any:
    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_figure(title)
    if px is None:
        return FallbackFigure(title, {"kind": "bar", "x": x, "y": y, "orientation": orientation, "rows": rows})
    fig = px.bar(df, x=x, y=y, title=title, orientation=orientation)
    fig.update_layout(template="plotly_white", margin=dict(l=40, r=20, t=60, b=40))
    return fig


def line(rows: list[dict[str, Any]], *, x: str, y: str, title: str, color: str | None = None) -> Any:
    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_figure(title)
    if px is None:
        return FallbackFigure(title, {"kind": "line", "x": x, "y": y, "color": color, "rows": rows})
    fig = px.line(df, x=x, y=y, color=color, markers=True, title=title)
    fig.update_layout(template="plotly_white", margin=dict(l=40, r=20, t=60, b=40))
    return fig


def dual_axis_line_bar(
    rows: list[dict[str, Any]],
    *,
    x: str,
    bar_y: str,
    line_y: str,
    title: str,
    bar_name: str,
    line_name: str,
) -> Any:
    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_figure(title)
    if go is None:
        return FallbackFigure(
            title,
            {
                "kind": "dual_axis_line_bar",
                "x": x,
                "bar_y": bar_y,
                "line_y": line_y,
                "bar_name": bar_name,
                "line_name": line_name,
                "rows": rows,
            },
        )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df[x],
            y=df[bar_y],
            name=bar_name,
            marker_color="#4f81bd",
            yaxis="y",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df[x],
            y=df[line_y],
            mode="lines+markers",
            name=line_name,
            line=dict(color="#c0504d", width=2),
            marker=dict(size=7),
            yaxis="y2",
        )
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        margin=dict(l=50, r=50, t=60, b=40),
        yaxis=dict(title=bar_name),
        yaxis2=dict(title=line_name, overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def stacked_area(rows: list[dict[str, Any]], *, x: str, y: str, color: str, title: str) -> Any:
    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_figure(title)
    if px is None:
        return FallbackFigure(title, {"kind": "stacked_area", "x": x, "y": y, "color": color, "rows": rows})
    fig = px.area(df, x=x, y=y, color=color, title=title)
    fig.update_layout(template="plotly_white", margin=dict(l=40, r=20, t=60, b=40))
    return fig


def bubble_terms(rows: list[dict[str, Any]], *, term: str, size: str, color: str | None = None, title: str) -> Any:
    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_figure(title)
    if px is None:
        return FallbackFigure(title, {"kind": "bubble_terms", "term": term, "size": size, "color": color, "rows": rows})
    fig = px.scatter(
        df,
        x=term,
        y=size,
        size=size,
        color=color,
        text=term,
        title=title,
        size_max=56,
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(
        template="plotly_white",
        margin=dict(l=40, r=20, t=60, b=80),
        xaxis=dict(showticklabels=False, title=""),
        yaxis=dict(title=size.replace("_", " ").title()),
    )
    return fig


def choropleth(
    rows: list[dict[str, Any]],
    *,
    locations: str,
    color: str,
    title: str,
    animation_frame: str | None = None,
    hover_name: str | None = None,
    colorscale: str = "Viridis",
) -> Any:
    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_figure(title)
    if px is None:
        return FallbackFigure(
            title,
            {
                "kind": "choropleth",
                "locations": locations,
                "color": color,
                "animation_frame": animation_frame,
                "hover_name": hover_name,
                "colorscale": colorscale,
                "rows": rows,
            },
        )
    fig = px.choropleth(
        df,
        locations=locations,
        color=color,
        animation_frame=animation_frame,
        hover_name=hover_name,
        color_continuous_scale=colorscale,
        title=title,
    )
    fig.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=60, b=20))
    return fig


def stacked_bar(
    rows: list[dict[str, Any]],
    *,
    x: str,
    y: str,
    color: str,
    title: str,
    orientation: str = "v",
    color_discrete_map: dict[str, str] | None = None,
) -> Any:
    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_figure(title)
    if px is None:
        return FallbackFigure(
            title,
            {
                "kind": "stacked_bar",
                "x": x,
                "y": y,
                "color": color,
                "orientation": orientation,
                "rows": rows,
            },
        )
    fig = px.bar(
        df,
        x=x,
        y=y,
        color=color,
        title=title,
        orientation=orientation,
        color_discrete_map=color_discrete_map,
    )
    fig.update_layout(
        template="plotly_white",
        barmode="stack",
        margin=dict(l=40, r=20, t=60, b=40),
        legend_title_text="",
    )
    return fig


def ranked_horizontal_bar(
    rows: list[dict[str, Any]],
    *,
    x: str,
    y: str,
    title: str,
    x_title: str,
    top_n: int = 10,
    marker_colors: list[str] | None = None,
    font_size: int = 16,
    height: int = 520,
) -> Any:
    df = pd.DataFrame(list(reversed(rows[:top_n])))
    if df.empty:
        return _empty_figure(title)
    if go is None:
        return FallbackFigure(title, {"kind": "ranked_horizontal_bar", "x": x, "y": y, "rows": rows[:top_n]})
    colors = list(reversed(marker_colors[:top_n])) if marker_colors else "#4db6e2"
    fig = go.Figure(
        go.Bar(
            x=df[x],
            y=df[y],
            orientation="h",
            marker=dict(color=colors),
            text=df[x],
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(size=font_size, color="#111827"),
            hovertemplate="%{y}: %{x}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        height=height,
        margin=dict(l=230, r=35, t=70, b=65),
        font=dict(size=font_size),
        xaxis=dict(title=x_title, titlefont=dict(size=font_size), tickfont=dict(size=font_size - 1)),
        yaxis=dict(title="", tickfont=dict(size=font_size - 1)),
        showlegend=False,
    )
    return fig


def institution_collaboration_network(
    edges: list[dict[str, Any]],
    *,
    title: str,
    node_metadata: dict[str, dict[str, Any]],
    max_edges: int = 100,
    max_nodes: int = 36,
    highlight_top_n: int = 6,
    font_size: int = 15,
) -> Any:
    import math

    graph = nx.Graph()
    for edge in edges[:max_edges]:
        source = edge.get("source")
        target = edge.get("target")
        if not source or not target:
            continue
        graph.add_edge(str(source), str(target), weight=float(edge.get("weight") or 1))
    if not graph.nodes:
        return _empty_figure(title)
    if go is None:
        return FallbackFigure(
            title,
            {
                "kind": "institution_collaboration_network",
                "edges": edges[:max_edges],
                "node_metadata": node_metadata,
                "max_nodes": max_nodes,
            },
        )

    strength_by_node = dict(graph.degree(weight="weight"))
    node_rows: list[tuple[str, float, dict[str, Any]]] = []
    for node in graph.nodes():
        metadata = node_metadata.get(node, {})
        score = float(metadata.get("n_papers") or 0) * 2.0 + strength_by_node.get(node, 0.0) + graph.degree(node) * 0.35
        node_rows.append((node, score, metadata))

    ranked_nodes = sorted(node_rows, key=lambda item: item[1], reverse=True)
    keep_candidates = [node for node, _, metadata in ranked_nodes if metadata]
    keep_candidates.extend(node for node, _, _ in ranked_nodes)
    keep_nodes: set[str] = set()
    for node in keep_candidates:
        keep_nodes.add(node)
        if len(keep_nodes) >= max(1, max_nodes):
            break
    graph = graph.subgraph(keep_nodes).copy()
    graph.remove_nodes_from(list(nx.isolates(graph)))
    if not graph.nodes:
        return _empty_figure(title)

    node_rows = [row for row in ranked_nodes if row[0] in graph.nodes]
    ordered_nodes = _spread_ranked_nodes([node for node, _, _ in node_rows])
    highlighted = {node for node, _, _ in sorted(node_rows, key=lambda item: item[1], reverse=True)[:highlight_top_n]}
    community_palette = ["#E15759", "#4E79A7", "#59A14F", "#F28E2B", "#76B7B2", "#B07AA1", "#EDC948", "#9C755F"]
    community_by_node = _network_communities(graph)
    pos: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(ordered_nodes):
        angle = 2 * math.pi * index / len(ordered_nodes) - math.pi / 2
        rank = next((rank for rank, (ranked_node, _, _) in enumerate(node_rows) if ranked_node == node), index)
        radius_jitter = 0.035 * ((rank % 3) - 1)
        pos[node] = ((1.25 + radius_jitter) * math.cos(angle), (1.25 + radius_jitter) * math.sin(angle))

    def node_color(node: str) -> str:
        return community_palette[community_by_node.get(node, 0) % len(community_palette)]

    max_edge_weight = max((data.get("weight", 1) for _, _, data in graph.edges(data=True)), default=1)
    top_edge_keys = {
        tuple(sorted((source, target)))
        for source, target, _data in sorted(
            graph.edges(data=True),
            key=lambda item: float(item[2].get("weight", 1)),
            reverse=True,
        )[:4]
    }
    sorted_edges = sorted(
        graph.edges(data=True),
        key=lambda item: (
            tuple(sorted((item[0], item[1]))) in top_edge_keys,
            float(item[2].get("weight", 1)),
        ),
    )
    for source, target, data in sorted_edges:
        x0, y0 = pos[source]
        x1, y1 = pos[target]
        weight = float(data.get("weight", 1))
        is_top_edge = tuple(sorted((source, target))) in top_edge_keys
        width = (1.0 + 7.2 * weight / max_edge_weight) if is_top_edge else (0.25 + 3.2 * weight / max_edge_weight)
        alpha = (0.58 + 0.32 * weight / max_edge_weight) if is_top_edge else (0.08 + 0.24 * weight / max_edge_weight)
        fig_line_color = _hex_to_rgba(node_color(source), alpha)
        if "fig" not in locals():
            fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=[x0, 0, x1, None],
                y=[y0, 0, y1, None],
                mode="lines",
                line_shape="spline",
                line=dict(width=width, color=fig_line_color),
                hoverinfo="text",
                hovertext=f"{source} - {target}: {data.get('weight', 1):g}",
                showlegend=False,
            )
        )
    if "fig" not in locals():
        fig = go.Figure()

    label_rows = sorted(node_rows, key=lambda item: item[1], reverse=True)[: min(18, len(node_rows))]
    inline_label_nodes = {node for node, _score, _metadata in label_rows[:14]}
    for is_highlight in (True, False):
        selected = [item for item in node_rows if (item[0] in highlighted) == is_highlight]
        if not selected:
            continue
        fig.add_trace(
            go.Scatter(
                x=[pos[node][0] for node, _, _ in selected],
                y=[pos[node][1] for node, _, _ in selected],
                mode="markers+text",
                text=[_institution_label(node) if node in inline_label_nodes else "" for node, _, _ in selected],
                textposition=[_node_text_position(pos[node]) for node, _, _ in selected],
                textfont=dict(
                    size=max(9, font_size - 3) if is_highlight else max(8, font_size - 5),
                    color="#111827" if is_highlight else "rgba(55,65,81,0.78)",
                ),
                marker=dict(
                    size=[
                        (14 if is_highlight else 5)
                        + min(25, (float(metadata.get("n_papers") or 0) ** 0.72) * 1.75)
                        + min(6, strength_by_node.get(node, 0.0) ** 0.45)
                        for _, _, metadata in selected
                    ],
                    color=[node_color(node) for node, _, _ in selected],
                    opacity=0.9 if is_highlight else 0.78,
                    line=dict(width=2.0 if is_highlight else 0.8, color="#ffffff"),
                ),
                hovertext=[
                    metadata.get("hover")
                    or f"{node}: {metadata.get('n_papers', 0)} papers, {strength_by_node.get(node, 0):g} collaboration strength"
                    for node, _, metadata in selected
                ],
                hoverinfo="text",
                showlegend=False,
            )
        )

    label_annotations = []
    for index, (node, _score, metadata) in enumerate(label_rows):
        label = _institution_label(node)
        full_name = _short_label(node, 30)
        country = metadata.get("country_code") or ""
        label_annotations.append(
            dict(
                x=0.705,
                y=0.96 - index * 0.049,
                xref="paper",
                yref="paper",
                text=f"<b>{label}</b> = {full_name}" + (f" ({country})" if country else ""),
                showarrow=False,
                xanchor="left",
                align="left",
                bgcolor="rgba(255,255,255,0.72)",
                font=dict(size=max(10, font_size - 4), color="#111827"),
            )
        )

    fig.update_layout(
        template="plotly_white",
        height=620,
        margin=dict(l=25, r=25, t=18, b=35),
        font=dict(size=font_size),
        showlegend=False,
        xaxis=dict(visible=False, range=[-1.62, 1.62], domain=[0.0, 0.72]),
        yaxis=dict(visible=False, range=[-1.55, 1.55], scaleanchor="x", scaleratio=1),
        annotations=label_annotations,
    )
    return fig


def institution_country_density_map(
    rows: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    title: str,
    font_size: int = 15,
    top_n: int = 20,
) -> Any:
    focus_rows = list(rows[:top_n])
    if not focus_rows:
        return _empty_figure(title)
    if go is None:
        return FallbackFigure(
            title,
            {
                "kind": "institution_country_density_map",
                "rows": focus_rows,
                "edges": edges,
                "note": "downgraded label-density map",
            },
        )

    try:
        import numpy as np
        from PIL import Image, ImageDraw
        from scipy.ndimage import gaussian_filter
        from wordcloud import WordCloud
    except Exception:
        return FallbackFigure(
            title,
            {
                "kind": "institution_country_density_map",
                "rows": focus_rows,
                "edges": edges,
                "note": "downgraded label-density map",
            },
        )

    ranked = sorted(
        focus_rows,
        key=lambda row: (float(row.get("n_papers") or 0), float(row.get("collaborator_count") or 0)),
        reverse=True,
    )
    weights = {row["name"]: max(1, float(row.get("n_papers") or 1)) for row in ranked}
    wc = WordCloud(
        width=1200,
        height=800,
        background_color="white",
        prefer_horizontal=0.92,
        max_words=len(ranked),
        min_font_size=8,
        max_font_size=78,
        random_state=42,
        collocations=False,
        color_func=lambda *args, **kwargs: "#111827",
    )
    wc.generate_from_frequencies(weights)
    positions = wc.layout_
    xs = [p[2][0] for p in positions]
    ys = [p[2][1] for p in positions]
    if not xs or not ys:
        return _empty_figure(title)

    canvas = Image.new("L", (1200, 800), 0)
    draw = ImageDraw.Draw(canvas)
    for (word, _freq), font_size_wc, (x, y), _orient, _color in positions:
        box = (
            max(0, int(x)),
            max(0, int(y)),
            min(1199, int(x + max(12, font_size_wc * 0.7))),
            min(799, int(y + max(10, font_size_wc * 0.45))),
        )
        draw.ellipse(box, fill=255)
    density = gaussian_filter(np.array(canvas, dtype=float) / 255.0, sigma=42)
    density = density / density.max() if density.max() else density

    fig = go.Figure()
    fig.add_trace(
        go.Heatmap(
            z=density,
            colorscale="YlOrRd",
            showscale=False,
            hoverinfo="skip",
            opacity=0.66,
        )
    )

    palette = ["#111827", "#1f2937", "#374151", "#4b5563"]
    for index, row in enumerate(ranked):
        if index >= 20:
            break
        layout_item = positions[index]
        (word, _count), font_size_wc, (x, y), orientation, color = layout_item
        size = max(7, min(26, int(font_size_wc * (0.82 if index >= 10 else 1.0))))
        label = row["name"]
        if index >= 12 and len(label) > 26:
            label = _short_label(label, 26)
        fig.add_trace(
            go.Scatter(
                x=[x],
                y=[y],
                mode="text",
                text=[label],
                textfont=dict(
                    size=size + (2 if index < 4 else 0),
                    color=palette[min(index, len(palette) - 1)],
                ),
                hovertext=[
                    f"{row['name']}: {row.get('n_papers', 0)} papers, {row.get('collaborator_count', 0)} collaborator links"
                ],
                hoverinfo="text",
                showlegend=False,
            )
        )

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=620,
        margin=dict(l=20, r=20, t=80, b=40),
        font=dict(size=font_size),
        xaxis=dict(visible=False, range=[0, 1200]),
        yaxis=dict(visible=False, range=[0, 800], scaleanchor="x", scaleratio=1),
        annotations=[
            dict(
                text="Downgraded: institution label-density map without institution coordinates.",
                x=0.5,
                y=-0.06,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=font_size - 2, color="#4b5563"),
            )
        ],
    )
    return fig


def chord(
    edges: list[dict[str, Any]],
    *,
    title: str,
    max_edges: int = 120,
    node_order: list[str] | None = None,
    node_metadata: dict[str, dict[str, Any]] | None = None,
) -> Any:
    filtered_edges = [
        edge
        for edge in edges[:max_edges]
        if edge.get("source") and edge.get("target") and float(edge.get("weight") or 0) > 0
    ]
    if not filtered_edges:
        return _empty_figure(title)

    node_weight: dict[str, float] = {}
    for edge in filtered_edges:
        source = str(edge["source"])
        target = str(edge["target"])
        weight = float(edge.get("weight") or 1)
        node_weight[source] = node_weight.get(source, 0.0) + weight
        node_weight[target] = node_weight.get(target, 0.0) + weight

    if node_order:
        nodes = [node for node in node_order if node in node_weight]
        nodes.extend(node for node in sorted(node_weight, key=node_weight.get, reverse=True) if node not in nodes)
    else:
        nodes = sorted(node_weight, key=node_weight.get, reverse=True)

    if len(nodes) < 2:
        return _empty_figure(title)

    if go is None:
        return FallbackFigure(
            title,
            {
                "kind": "chord",
                "nodes": nodes,
                "node_metadata": node_metadata,
                "edges": filtered_edges,
            },
        )

    fig = go.Figure()
    _add_ribbon_chord_traces(
        fig,
        filtered_edges,
        nodes=nodes,
        node_weight=node_weight,
        node_metadata=node_metadata or {},
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        xaxis=dict(visible=False, range=[-1.2, 1.2]),
        yaxis=dict(visible=False, range=[-1.2, 1.2], scaleanchor="x", scaleratio=1),
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


def country_distribution_figure(
    edges: list[dict[str, Any]],
    corresponding_rows: list[dict[str, Any]],
    *,
    title: str,
    max_edges: int = 120,
    node_order: list[str] | None = None,
    node_metadata: dict[str, dict[str, Any]] | None = None,
) -> Any:
    filtered_edges = [
        edge
        for edge in edges[:max_edges]
        if edge.get("source") and edge.get("target") and float(edge.get("weight") or 0) > 0
    ]
    if not filtered_edges and not corresponding_rows:
        return _empty_figure(title)

    if go is None:
        return FallbackFigure(
            title,
            {
                "kind": "country_distribution_figure",
                "edges": filtered_edges,
                "corresponding_rows": corresponding_rows,
                "node_order": node_order,
                "node_metadata": node_metadata,
            },
        )

    node_weight: dict[str, float] = {}
    for edge in filtered_edges:
        source = str(edge["source"])
        target = str(edge["target"])
        weight = float(edge.get("weight") or 1)
        node_weight[source] = node_weight.get(source, 0.0) + weight
        node_weight[target] = node_weight.get(target, 0.0) + weight

    if node_order:
        nodes = [node for node in node_order if node in node_weight]
        nodes.extend(node for node in sorted(node_weight, key=node_weight.get, reverse=True) if node not in nodes)
    else:
        nodes = sorted(node_weight, key=node_weight.get, reverse=True)

    fig = go.Figure()
    node_metadata = node_metadata or {}

    if nodes:
        _add_ribbon_chord_traces(
            fig,
            filtered_edges,
            nodes=nodes,
            node_weight=node_weight,
            node_metadata=node_metadata,
            xaxis="x",
            yaxis="y",
        )

    df = pd.DataFrame(corresponding_rows)
    if not df.empty:
        for publication_type, color in (("MCP", "#f8766d"), ("SCP", "#00bfc4")):
            typed = df[df["publication_type"] == publication_type]
            fig.add_trace(
                go.Bar(
                    x=typed["n_papers"],
                    y=typed["country_name"],
                    orientation="h",
                    name=publication_type,
                    marker_color=color,
                    xaxis="x2",
                    yaxis="y2",
                    hovertemplate="%{y}: %{x} " + publication_type + "<extra></extra>",
                )
            )

    fig.update_layout(
        title=title,
        template="plotly_white",
        barmode="stack",
        margin=dict(l=30, r=30, t=70, b=45),
        legend=dict(x=0.88, y=0.18, bgcolor="rgba(255,255,255,0.75)"),
        xaxis=dict(domain=[0.0, 0.43], visible=False, range=[-1.2, 1.2]),
        yaxis=dict(domain=[0.0, 1.0], visible=False, range=[-1.2, 1.2], scaleanchor="x", scaleratio=1),
        xaxis2=dict(domain=[0.55, 1.0], title="Number of Publications"),
        yaxis2=dict(domain=[0.0, 1.0], automargin=True, title=""),
        annotations=[
            dict(text="A", x=0.0, y=1.05, xref="paper", yref="paper", showarrow=False, font=dict(size=16)),
            dict(text="B", x=0.55, y=1.05, xref="paper", yref="paper", showarrow=False, font=dict(size=16)),
        ],
    )
    return fig


def _add_ribbon_chord_traces(
    fig: Any,
    edges: list[dict[str, Any]],
    *,
    nodes: list[str],
    node_weight: dict[str, float],
    node_metadata: dict[str, dict[str, Any]],
    xaxis: str = "x",
    yaxis: str = "y",
) -> None:
    import math

    palette = [
        "#E15759",
        "#4E79A7",
        "#59A14F",
        "#F28E2B",
        "#76B7B2",
        "#B07AA1",
        "#EDC948",
        "#9C755F",
        "#FF9DA7",
        "#BAB0AC",
        "#86BCB6",
        "#FABFD2",
    ]
    node_colors = {node: palette[index % len(palette)] for index, node in enumerate(nodes)}

    total_weight = sum(node_weight.get(node, 0.0) for node in nodes)
    if total_weight <= 0:
        return

    gap = min(0.055, (2 * math.pi) / max(1, len(nodes)) * 0.22)
    available = (2 * math.pi) - gap * len(nodes)
    angle = -math.pi / 2
    sectors: dict[str, tuple[float, float]] = {}
    for node in nodes:
        span = available * node_weight[node] / total_weight
        sectors[node] = (angle, angle + span)
        angle += span + gap

    incident: dict[str, list[dict[str, Any]]] = {node: [] for node in nodes}
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        if source in incident:
            incident[source].append(edge)
        if target in incident:
            incident[target].append(edge)

    segment: dict[tuple[int, str], tuple[float, float]] = {}
    for node in nodes:
        start, end = sectors[node]
        cursor = start
        sector_span = max(0.0, end - start)
        for edge in sorted(incident[node], key=lambda item: (str(item.get("source")), str(item.get("target")))):
            weight = float(edge.get("weight") or 1)
            span = sector_span * weight / node_weight[node] if node_weight[node] else 0
            segment[(id(edge), node)] = (cursor, cursor + span)
            cursor += span

    for edge in sorted(edges, key=lambda item: float(item.get("weight") or 1)):
        source = str(edge["source"])
        target = str(edge["target"])
        source_span = segment.get((id(edge), source))
        target_span = segment.get((id(edge), target))
        if source_span is None or target_span is None:
            continue
        weight = float(edge.get("weight") or 1)
        x, y = _ribbon_polygon(source_span, target_span)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                xaxis=xaxis,
                yaxis=yaxis,
                mode="lines",
                fill="toself",
                fillcolor=_hex_to_rgba(node_colors[source], 0.28),
                line=dict(color=_hex_to_rgba(node_colors[source], 0.42), width=0.5),
                hoverinfo="text",
                hovertext=f"{source} - {target}: {weight:g}",
                showlegend=False,
            )
        )

    for node in nodes:
        start, end = sectors[node]
        x, y = _annular_sector_polygon(start, end)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                xaxis=xaxis,
                yaxis=yaxis,
                mode="lines",
                fill="toself",
                fillcolor=node_colors[node],
                line=dict(color="#ffffff", width=0.8),
                hoverinfo="text",
                hovertext=node_metadata.get(node, {}).get("hover") or f"{node}: {node_weight[node]:g} collaboration links",
                showlegend=False,
            )
        )

    label_x = []
    label_y = []
    labels = []
    for node in nodes:
        start, end = sectors[node]
        mid = (start + end) / 2
        label_x.append(1.13 * math.cos(mid))
        label_y.append(1.13 * math.sin(mid))
        labels.append(node_metadata.get(node, {}).get("label") or node)
    fig.add_trace(
        go.Scatter(
            x=label_x,
            y=label_y,
            xaxis=xaxis,
            yaxis=yaxis,
            mode="text",
            text=labels,
            textfont=dict(size=16, color="#111827"),
            hoverinfo="skip",
            showlegend=False,
        )
    )


def _annular_sector_polygon(start: float, end: float, *, outer_radius: float = 1.0, inner_radius: float = 0.86) -> tuple[list[float], list[float]]:
    import math

    steps = max(6, int(abs(end - start) / 0.035))
    outer_angles = [start + (end - start) * index / steps for index in range(steps + 1)]
    inner_angles = list(reversed(outer_angles))
    x = [outer_radius * math.cos(angle) for angle in outer_angles]
    y = [outer_radius * math.sin(angle) for angle in outer_angles]
    x.extend(inner_radius * math.cos(angle) for angle in inner_angles)
    y.extend(inner_radius * math.sin(angle) for angle in inner_angles)
    x.append(x[0])
    y.append(y[0])
    return x, y


def _ribbon_polygon(
    source_span: tuple[float, float],
    target_span: tuple[float, float],
    *,
    radius: float = 0.84,
    control_radius: float = 0.12,
) -> tuple[list[float], list[float]]:
    import math

    def point(angle: float, r: float = radius) -> tuple[float, float]:
        return r * math.cos(angle), r * math.sin(angle)

    source_start, source_end = source_span
    target_start, target_end = target_span
    x1, y1 = point(source_start)
    x2, y2 = point(target_end)
    x3, y3 = point(target_start)
    x4, y4 = point(source_end)
    c1_angle = (source_start + target_end) / 2
    c2_angle = (target_start + source_end) / 2
    cx1, cy1 = point(c1_angle, control_radius)
    cx2, cy2 = point(c2_angle, control_radius)

    first = _quadratic_bezier((x1, y1), (cx1, cy1), (x2, y2), steps=24)
    outer = _arc_points(target_end, target_start, radius=radius, steps=6)
    second = _quadratic_bezier((x3, y3), (cx2, cy2), (x4, y4), steps=24)
    inner = _arc_points(source_end, source_start, radius=radius, steps=6)
    points = first + outer[1:] + second[1:] + inner[1:]
    points.append(points[0])
    return [point[0] for point in points], [point[1] for point in points]


def _quadratic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    *,
    steps: int,
) -> list[tuple[float, float]]:
    points = []
    for index in range(steps + 1):
        t = index / steps
        mt = 1 - t
        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
        points.append((x, y))
    return points


def _arc_points(start: float, end: float, *, radius: float, steps: int) -> list[tuple[float, float]]:
    import math

    return [
        (
            radius * math.cos(start + (end - start) * index / steps),
            radius * math.sin(start + (end - start) * index / steps),
        )
        for index in range(steps + 1)
    ]


def _hex_to_rgba(color: str, alpha: float) -> str:
    value = color.lstrip("#")
    if len(value) != 6:
        return color
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"


def _spread_ranked_nodes(nodes: list[str]) -> list[str]:
    if len(nodes) <= 2:
        return nodes
    slots: list[str | None] = [None] * len(nodes)
    step = len(nodes) / max(1, min(len(nodes), 8))
    for rank, node in enumerate(nodes):
        if rank < 8:
            index = round(rank * step) % len(nodes)
        else:
            index = rank
        while slots[index] is not None:
            index = (index + 1) % len(nodes)
        slots[index] = node
    return [node for node in slots if node is not None]


def _network_communities(graph: nx.Graph) -> dict[str, int]:
    try:
        communities = nx.algorithms.community.greedy_modularity_communities(graph, weight="weight")
    except Exception:
        communities = [set(component) for component in nx.connected_components(graph)]
    ordered = sorted(communities, key=lambda group: (-len(group), sorted(group)[0]))
    return {node: index for index, group in enumerate(ordered) for node in group}


def _institution_label(value: str) -> str:
    known = {
        "Centre National de la Recherche Scientifique": "CNRS",
        "Massachusetts Institute of Technology": "MIT",
        "Institute for Advanced Study": "IAS",
        "University of California, Los Angeles": "UCLA",
        "University of California, Berkeley": "UC Berkeley",
        "University of California, San Diego": "UCSD",
        "California Institute of Technology": "Caltech",
        "Courant Institute of Mathematical Sciences": "Courant",
        "Institut de Mathématiques de Jussieu-Paris Rive Gauche": "IMJ-PRG",
        "École Normale Supérieure - PSL": "ENS-PSL",
    }
    if value in known:
        return known[value]
    return _short_label(value, 22)


def _node_text_position(position: tuple[float, float]) -> str:
    x, y = position
    if abs(x) < 0.28:
        return "top center" if y >= 0 else "bottom center"
    if x > 0:
        return "middle right"
    return "middle left"


def _short_label(value: str, max_length: int = 18) -> str:
    if len(value) <= max_length:
        return value
    words = value.replace(",", "").split()
    connector_words = {"of", "and", "for", "the", "de", "del", "di", "la", "le", "des", "du"}
    content_words = [word for word in words if word.lower() not in connector_words]
    if len(content_words) >= 5 and max_length <= 18:
        label = " ".join(word[0] for word in words if word[:1].isalpha()).upper()
        if 2 <= len(label) <= 8:
            return label
    return value[: max_length - 1] + "."


def network(
    edges: list[dict[str, Any]],
    *,
    title: str,
    max_edges: int = 200,
    node_metadata: dict[str, dict[str, Any]] | None = None,
) -> Any:
    graph = nx.Graph()
    for edge in edges[:max_edges]:
        source = edge.get("source")
        target = edge.get("target")
        if not source or not target:
            continue
        graph.add_edge(str(source), str(target), weight=float(edge.get("weight") or 1))

    if not graph.nodes:
        return _empty_figure(title)

    pos = nx.spring_layout(graph, seed=42, weight="weight")
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for source, target in graph.edges():
        x0, y0 = pos[source]
        x1, y1 = pos[target]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    node_x = []
    node_y = []
    labels = []
    sizes = []
    node_metadata = node_metadata or {}
    node_colors = []
    hover_texts = []
    for node in graph.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        labels.append(node)
        metadata = node_metadata.get(str(node), {})
        sizes.append(float(metadata.get("size") or (10 + min(30, graph.degree(node) * 3))))
        node_colors.append(metadata.get("color") if metadata.get("color") is not None else graph.degree(node))
        hover_texts.append(metadata.get("hover") or node)

    if go is None:
        payload = {
            "kind": "network",
            "nodes": labels,
            "node_metadata": node_metadata,
            "edges": [{"source": source, "target": target, "weight": graph[source][target].get("weight", 1)} for source, target in graph.edges()],
        }
        return FallbackFigure(title, payload)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=0.7, color="#9aa4b2"),
            hoverinfo="none",
            name="links",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=labels,
            textposition="top center",
            marker=dict(size=sizes, color=node_colors, colorscale="Viridis", line=dict(width=1, color="#ffffff")),
            hovertext=hover_texts,
            hoverinfo="text",
            name="terms",
        )
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        showlegend=False,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


def wide_matrix(rows: list[dict[str, Any]], *, index: str, columns: str, values: str) -> list[dict[str, Any]]:
    df = pd.DataFrame(rows)
    if df.empty:
        return []
    matrix = df.pivot_table(index=index, columns=columns, values=values, aggfunc="sum", fill_value=0)
    return matrix.reset_index().to_dict(orient="records")


def _empty_figure(title: str) -> Any:
    if go is not None:
        return go.Figure()
    return FallbackFigure(title, {"rows": []})


def _json_default(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)
