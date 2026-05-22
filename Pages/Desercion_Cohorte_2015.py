"""
Dashboard ICFES – Deserción por Cohorte Saber 11
=================================================
Muestra:
  - Total de estudiantes que presentaron Saber 11 (cohorte)
  - Año de la cohorte (extraído de la columna 'Periodo')
  - Número de desertores de esa cohorte
  - Número de estudiantes que continuaron a Saber Pro
  - Tasa de deserción (%)
    - Tasa de transición educativa (%)
  - Histograma de desertores por estrato
    - Distribución de desertores por naturaleza de colegio
    - Distribución de desertores por zona del colegio
    - Top 10 departamentos con más deserción

Cache en disco:
  - Primera ejecución: procesa los CSVs y guarda en Cache/
  - Siguientes:        carga la caché en segundos
  - CSV modificado:    detecta cambio y reprocesa automáticamente

Para forzar reprocesamiento:
    python pages/Desercion_Cohorte.py --rebuild
"""

import sys
import pickle
import hashlib
import time
from pathlib import Path
import warnings

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc
import dash

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# REGISTRO DE PÁGINA
# ─────────────────────────────────────────────────────────────
dash.register_page(__name__, path="/desercion2015", name="Deserción · Cohorte 2015")

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN  –  ajusta estas rutas
# ─────────────────────────────────────────────────────────────
BASE_PROYECT_DIR = Path(__file__).resolve().parents[2]

CSV_SABER11   = BASE_PROYECT_DIR / "Datasets" / "Data_ICFES" / "Saber_11" / "Unificados" / "Limpios" / "Saber_11_2015_filtrado.csv"
CSV_DESERTORES = BASE_PROYECT_DIR / "Datasets" / "Data_ICFES" / "ICFES_Unificado" / "desercion" / "desertores_detalle.csv"

CACHE_DIR  = Path("Cache")
CACHE_FILE = CACHE_DIR / "Desercion_Cohorte_2015_cache.pkl"

# ─────────────────────────────────────────────────────────────
# PALETA Y ESTILO  (igual al resto de dashboards)
# ─────────────────────────────────────────────────────────────
BG         = "#0D1117"
CARD_BG    = "#161B22"
ACCENT1    = "#58A6FF"
ACCENT2    = "#3FB950"
ACCENT3    = "#F78166"
ACCENT4    = "#D2A8FF"
ACCENT5    = "#FFA657"
TEXT_MAIN  = "#E6EDF3"
TEXT_MUTED = "#8B949E"
BORDER     = "#30363D"

PALETTE = [ACCENT1, ACCENT2, ACCENT3, ACCENT4, ACCENT5,
           "#79C0FF", "#56D364", "#FF7B72", "#BC8CFF", "#FFA657"]

LAYOUT_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor ="rgba(0,0,0,0)",
    font=dict(family="'IBM Plex Mono', monospace", color=TEXT_MAIN, size=12),
    margin=dict(t=40, b=40, l=40, r=40),
)

# ─────────────────────────────────────────────────────────────
# FUNCIONES DE FIGURA
# ─────────────────────────────────────────────────────────────

def bar_v_fig(index, values, colors=None, color=ACCENT2, xlab="", ylab=""):
    marker = dict(
        color=colors if colors else color,
        line=dict(color="rgba(0,0,0,0)"),
    )
    fig = go.Figure(go.Bar(
        x=[str(l) for l in index], y=values,
        marker=marker,
        hovertemplate="%{x}<br>%{y:,}<extra></extra>",
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        xaxis=dict(gridcolor="rgba(0,0,0,0)", title=xlab),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, title=ylab),
    )
    return fig


def gauge_fig(value, title=""):
    """Medidor circular para la tasa de deserción."""
    color = ACCENT2 if value < 20 else (ACCENT5 if value < 40 else ACCENT3)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": "%", "font": {"color": color, "size": 36,
                                         "family": "'IBM Plex Mono', monospace"}},
        gauge={
            "axis": {
                "range": [0, 100],
                "tickcolor": TEXT_MUTED,
                "tickfont": {"color": TEXT_MUTED, "size": 10},
            },
            "bar": {"color": color, "thickness": 0.3},
            "bgcolor": "rgba(0,0,0,0)",
            "bordercolor": BORDER,
            "steps": [
                {"range": [0,  20], "color": "#162414"},
                {"range": [20, 40], "color": "#1E1A0F"},
                {"range": [40, 100], "color": "#1E0F0F"},
            ],
            "threshold": {
                "line": {"color": ACCENT3, "width": 2},
                "thickness": 0.75,
                "value": value,
            },
        },
        title={"text": title, "font": {"color": TEXT_MUTED, "size": 12,
                                        "family": "'IBM Plex Mono', monospace"}},
    ))
    layout_gauge = {k: v for k, v in LAYOUT_BASE.items() if k != "margin"}
    fig.update_layout(**layout_gauge, margin=dict(t=60, b=20, l=40, r=40))
    return fig


def donut_continuacion(continuaron, desertaron):
    """Torta que muestra continuaron vs desertaron."""
    fig = go.Figure(go.Pie(
        labels=["Continuaron a Saber Pro", "Desertaron"],
        values=[continuaron, desertaron],
        hole=0.55,
        marker=dict(
            colors=[ACCENT2, ACCENT3],
            line=dict(color=BG, width=3),
        ),
        textfont=dict(size=11),
        hovertemplate="%{label}<br>%{value:,} estudiantes<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        showlegend=True,
        legend=dict(font=dict(size=11, color=TEXT_MUTED),
                    bgcolor="rgba(0,0,0,0)", bordercolor=BORDER, borderwidth=1),
    )
    return fig


def pie_counts_fig(index, values, title=""):
    fig = go.Figure(go.Pie(
        labels=[str(v) for v in index],
        values=values,
        hole=0.45,
        marker=dict(colors=PALETTE, line=dict(color=BG, width=2)),
        textfont=dict(size=11),
        hovertemplate="%{label}<br>%{value:,} estudiantes<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        title=dict(text=title, font=dict(size=12, color=TEXT_MUTED)),
        showlegend=True,
        legend=dict(font=dict(size=11, color=TEXT_MUTED),
                    bgcolor="rgba(0,0,0,0)", bordercolor=BORDER, borderwidth=1),
    )
    return fig


def normalize_col(col_name: str) -> str:
    return "".join(ch for ch in str(col_name).lower() if ch.isalnum())


def find_first_column(df: pd.DataFrame, candidates):
    col_map = {normalize_col(c): c for c in df.columns}
    for candidate in candidates:
        found = col_map.get(normalize_col(candidate))
        if found:
            return found
    return None

# ─────────────────────────────────────────────────────────────
# FINGERPRINT
# ─────────────────────────────────────────────────────────────

def csv_fingerprint(path: Path) -> str:
    s = path.stat()
    return hashlib.md5(f"{s.st_size}-{s.st_mtime}".encode()).hexdigest()

def combined_fingerprint() -> str:
    parts = []
    for p in [CSV_SABER11, CSV_DESERTORES]:
        if p.exists():
            parts.append(csv_fingerprint(p))
    return hashlib.md5("|".join(parts).encode()).hexdigest()

# ─────────────────────────────────────────────────────────────
# PROCESAMIENTO
# ─────────────────────────────────────────────────────────────

def build_cache() -> dict:
    print("=" * 55)
    print("  Procesando CSVs de deserción…")
    print("=" * 55)
    t0 = time.time()

    # ── 1. Leer Saber 11 ────────────────────────────────────
    print("  [1/5] Leyendo CSV Saber 11…")
    df11 = pd.read_csv(CSV_SABER11, sep=";", decimal=".", low_memory=False, encoding="utf-8-sig")
    total_cohorte = len(df11)
    print(f"        {total_cohorte:,} estudiantes en la cohorte.")

    # Año de la cohorte: primeros 4 dígitos del primer valor de 'Periodo'
    periodo_val = str(df11["periodo"].dropna().iloc[0])
    anno_cohorte = int(periodo_val[:4])
    print(f"        Año de la cohorte: {anno_cohorte}")

    # ── 2. Leer desertores ──────────────────────────────────
    print("  [2/6] Leyendo CSV de desertores…")
    df_des = pd.read_csv(CSV_DESERTORES, sep=";", decimal=".", low_memory=False, encoding="utf-8-sig")
    total_desertores = len(df_des)
    print(f"        {total_desertores:,} desertores encontrados.")

    # ── 3. Cálculos ─────────────────────────────────────────
    print("  [3/6] Calculando métricas…")
    continuaron     = total_cohorte - total_desertores
    tasa_desercion  = round((total_desertores / total_cohorte) * 100, 2) if total_cohorte > 0 else 0.0
    tasa_transicion = round((continuaron / total_cohorte) * 100, 2) if total_cohorte > 0 else 0.0

    # Desertores por estrato
    col_estrato = find_first_column(df_des, ["fami_estratovivienda"])

    if col_estrato and col_estrato in df_des.columns:
        estrato_vc = df_des[col_estrato].fillna("No reporta").value_counts().sort_index()
        estrato_idx = list(estrato_vc.index)
        estrato_val = list(estrato_vc.values)
    else:
        print("        ⚠️  No se encontró columna de estrato en el archivo de desertores.")
        estrato_idx = []
        estrato_val = []

    # Distribución por naturaleza y zona del colegio (desertores)
    col_naturaleza = find_first_column(df_des, ["cole_naturaleza"])
    col_area = find_first_column(df_des, ["cole_area_ubicacion"])
    col_depto = find_first_column(df_des, ["estu_depto_presentacion"])

    naturaleza_idx, naturaleza_val = [], []
    area_idx, area_val = [], []
    depto_idx, depto_val = [], []

    if col_naturaleza:
        nat_vc = df_des[col_naturaleza].fillna("No reporta").value_counts()
        naturaleza_idx, naturaleza_val = list(nat_vc.index), list(nat_vc.values)
    else:
        print("        ⚠️  No se encontró columna 'cole_naturaleza' en desertores.")

    if col_area:
        area_vc = df_des[col_area].fillna("No reporta").value_counts()
        area_idx, area_val = list(area_vc.index), list(area_vc.values)
    else:
        print("        ⚠️  No se encontró columna 'cole_area_ubicacion' en desertores.")

    if col_depto:
        dept_vc = df_des[col_depto].fillna("No reporta").value_counts().head(10)
        depto_idx, depto_val = list(dept_vc.index), list(dept_vc.values)
    else:
        print("        ⚠️  No se encontró columna 'estu_depto_presentacion' en desertores.")

    # ── 4. Figuras ──────────────────────────────────────────
    print("  [4/6] Generando figuras…")
    figs = {}

    figs["gauge"] = gauge_fig(tasa_desercion, "Tasa de deserción")
    figs["donut"] = donut_continuacion(continuaron, total_desertores)

    if estrato_idx:
        # Colores degradados por estrato (1=rojo, 6=azul)
        n = len(estrato_idx)
        estrato_colors = [
            f"hsl({int(10 + 200 * i / max(n - 1, 1))}, 70%, 55%)"
            for i in range(n)
        ]
        figs["estrato"] = bar_v_fig(
            estrato_idx, estrato_val,
            colors=estrato_colors,
            xlab="Estrato", ylab="Desertores",
        )
    else:
        figs["estrato"] = None

    figs["naturaleza"] = pie_counts_fig(
        naturaleza_idx, naturaleza_val, "Naturaleza del colegio (desertores)"
    ) if naturaleza_idx else None

    figs["area"] = pie_counts_fig(
        area_idx, area_val, "Zona del colegio (desertores)"
    ) if area_idx else None

    figs["depto_top10"] = bar_v_fig(
        depto_idx, depto_val,
        color=ACCENT5,
        xlab="Departamento", ylab="Desertores",
    ) if depto_idx else None

    # ── 5. Guardar caché ────────────────────────────────────
    print("  [5/6] Empaquetando resultados…")
    payload = {
        "fingerprint":      combined_fingerprint(),
        "anno_cohorte":     anno_cohorte,
        "total_cohorte":    total_cohorte,
        "total_desertores": total_desertores,
        "continuaron":      continuaron,
        "tasa_desercion":   tasa_desercion,
        "tasa_transicion":  tasa_transicion,
        "figs":             figs,
        "tiene_estrato":    col_estrato is not None,
        "tiene_naturaleza": col_naturaleza is not None,
        "tiene_area":       col_area is not None,
        "tiene_depto":      col_depto is not None,
    }

    print("  [6/6] Guardando caché…")
    CACHE_DIR.mkdir(exist_ok=True)
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"  ✅ Listo en {time.time()-t0:.1f}s  →  caché en {CACHE_FILE}")
    print("=" * 55)
    return payload


REQUIRED_KEYS = {
    "fingerprint", "anno_cohorte", "total_cohorte", "total_desertores",
    "continuaron", "tasa_desercion", "tasa_transicion",
    "figs", "tiene_estrato", "tiene_naturaleza", "tiene_area",
    "tiene_depto",
}

def load_or_build(force=False) -> dict:
    if not force and CACHE_FILE.exists():
        print(f"  Cargando caché Deserción desde {CACHE_FILE}…", end=" ", flush=True)
        t0 = time.time()
        with open(CACHE_FILE, "rb") as f:
            payload = pickle.load(f)
        print(f"OK ({time.time()-t0:.1f}s)")
        return payload
    return build_cache()

# ─────────────────────────────────────────────────────────────
# COMPONENTES DE UI
# ─────────────────────────────────────────────────────────────

def card(children, extra_style=None):
    style = {"background": CARD_BG, "border": f"1px solid {BORDER}",
             "borderRadius": "12px", "padding": "20px", "marginBottom": "20px"}
    if extra_style: style.update(extra_style)
    return html.Div(children, style=style)

def section_title(text):
    return html.H3(text, style={
        "color": ACCENT1, "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "13px", "letterSpacing": "2px", "textTransform": "uppercase",
        "marginBottom": "16px", "marginTop": "0",
        "borderLeft": f"3px solid {ACCENT1}", "paddingLeft": "10px",
    })

def kpi_box(label, value, color=ACCENT1, subtitle=None):
    children = [
        html.Div(label, style={"color": TEXT_MUTED, "fontSize": "10px",
                               "letterSpacing": "1.5px", "textTransform": "uppercase"}),
        html.Div(value, style={"color": color, "fontSize": "28px",
                               "fontWeight": "700", "marginTop": "6px",
                               "letterSpacing": "-0.5px"}),
    ]
    if subtitle:
        children.append(
            html.Div(subtitle, style={"color": TEXT_MUTED, "fontSize": "10px", "marginTop": "4px"})
        )
    return html.Div(children, style={
        "background": BG, "border": f"1px solid {BORDER}", "borderRadius": "8px",
        "padding": "18px 22px", "textAlign": "center", "flex": "1",
        "minWidth": "160px", "fontFamily": "'IBM Plex Mono', monospace",
    })

def graph(fig, height="300px"):
    return dcc.Graph(figure=fig, config={"displayModeBar": False},
                     style={"height": height})

def row(*children, gap="16px"):
    return html.Div(list(children),
                    style={"display": "flex", "flexWrap": "wrap", "gap": gap})

def col(children, flex="1", min_width="280px"):
    return html.Div(children, style={"flex": flex, "minWidth": min_width})

# ─────────────────────────────────────────────────────────────
# BUILD LAYOUT
# ─────────────────────────────────────────────────────────────

def build_layout(data: dict):
    figs            = data["figs"]
    anno            = data["anno_cohorte"]
    total_cohorte   = data["total_cohorte"]
    total_des       = data["total_desertores"]
    continuaron     = data["continuaron"]
    tasa            = data["tasa_desercion"]
    tasa_trans      = data["tasa_transicion"]
    tiene_estrato   = data["tiene_estrato"]
    tiene_naturaleza = data["tiene_naturaleza"]
    tiene_area      = data["tiene_area"]
    tiene_depto     = data["tiene_depto"]

    # Color de la tasa según severidad
    tasa_color = ACCENT2 if tasa < 20 else (ACCENT5 if tasa < 40 else ACCENT3)

    return html.Div(style={
        "background": BG, "minHeight": "100vh",
        "fontFamily": "'IBM Plex Mono', monospace",
        "color": TEXT_MAIN, "padding": "24px 32px",
    }, children=[

        # ── Header ──────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div(f"ICFES · COHORTE {anno}", style={
                    "color": ACCENT1, "fontSize": "11px", "letterSpacing": "4px"}),
                html.H1("Deserción Estudiantil", style={
                    "margin": "4px 0 0 0", "fontSize": "28px", "fontWeight": "700",
                    "color": TEXT_MAIN, "letterSpacing": "-0.5px"}),
            ]),
            html.Div([
                html.Div("AÑO DE COHORTE", style={
                    "color": TEXT_MUTED, "fontSize": "10px", "letterSpacing": "2px"}),
                html.Div(str(anno), style={
                    "color": ACCENT4, "fontSize": "42px", "fontWeight": "700",
                    "letterSpacing": "-1px"}),
            ], style={"textAlign": "right"}),
        ], style={
            "display": "flex", "justifyContent": "space-between", "alignItems": "flex-end",
            "marginBottom": "28px", "paddingBottom": "20px",
            "borderBottom": f"1px solid {BORDER}",
        }),

        # ── KPIs principales ────────────────────────────────
        card([
            section_title("Resumen de la cohorte"),
            row(
                kpi_box("Presentaron Saber 11", f"{total_cohorte:,}", ACCENT1,
                        f"Cohorte {anno}"),
                kpi_box("Desertaron", f"{total_des:,}", ACCENT3,
                        "No llegaron a Saber Pro"),
                kpi_box("Continuaron", f"{continuaron:,}", ACCENT2,
                        "Llegaron a Saber Pro"),
                kpi_box("Tasa de deserción", f"{tasa:.2f}%", tasa_color,
                        "Desertores / Total cohorte"),
                kpi_box("Tasa de transición", f"{tasa_trans:.2f}%", ACCENT2,
                        "Continuaron / Total cohorte"),
            ),
        ]),

        # ── Gauge + Donut ───────────────────────────────────
        card([
            section_title("Visualización de la deserción"),
            row(
                col([
                    html.Div("Tasa de deserción", style={
                        "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px"}),
                    graph(figs["gauge"], "320px"),
                ]),
                col([
                    html.Div("Distribución: continuaron vs desertaron", style={
                        "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px"}),
                    graph(figs["donut"], "320px"),
                ]),
            ),
        ]),

        # ── Desertores por estrato ──────────────────────────
        card([
            section_title("Desertores por estrato socioeconómico"),
            *(
                [graph(figs["estrato"], "340px")]
                if tiene_estrato and figs.get("estrato")
                else [html.Div(
                    "⚠️  No se encontró columna de estrato en el archivo de desertores.",
                    style={"color": ACCENT5, "fontFamily": "'IBM Plex Mono', monospace",
                           "fontSize": "13px", "padding": "20px 0"},
                )]
            ),
        ]),

        card([
            section_title("Perfil de desertores por tipo y zona de colegio"),
            row(
                col([
                    html.Div("Naturaleza del colegio", style={
                        "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px"}),
                    graph(figs["naturaleza"], "340px") if tiene_naturaleza and figs.get("naturaleza") else html.Div(
                        "⚠️  No se encontró la columna 'cole_naturaleza' en el archivo de desertores.",
                        style={"color": ACCENT5, "fontFamily": "'IBM Plex Mono', monospace",
                               "fontSize": "13px", "padding": "20px 0"},
                    ),
                ]),
                col([
                    html.Div("Zona del colegio", style={
                        "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px"}),
                    graph(figs["area"], "340px") if tiene_area and figs.get("area") else html.Div(
                        "⚠️  No se encontró la columna 'cole_area_ubicacion' en el archivo de desertores.",
                        style={"color": ACCENT5, "fontFamily": "'IBM Plex Mono', monospace",
                               "fontSize": "13px", "padding": "20px 0"},
                    ),
                ]),
            ),
        ]),

        card([
            section_title("Top 10 departamentos con mayor deserción"),
            *(
                [graph(figs["depto_top10"], "360px")]
                if tiene_depto and figs.get("depto_top10")
                else [html.Div(
                    "⚠️  No se encontró la columna 'estu_depto_presentacion' en el archivo de desertores.",
                    style={"color": ACCENT5, "fontFamily": "'IBM Plex Mono', monospace",
                           "fontSize": "13px", "padding": "20px 0"},
                )]
            ),
        ]),

        # ── Nota metodológica ───────────────────────────────
        card([
            section_title("Nota metodológica"),
            html.Div([
                html.Div([
                    html.Span("Total cohorte  ", style={"color": TEXT_MUTED}),
                    html.Span("→  número de filas en el CSV de Saber 11 de la cohorte seleccionada.",
                              style={"color": TEXT_MAIN}),
                ], style={"marginBottom": "8px"}),
                html.Div([
                    html.Span("Desertores  ", style={"color": TEXT_MUTED}),
                    html.Span("→  número de filas en el CSV de desertores.",
                              style={"color": TEXT_MAIN}),
                ], style={"marginBottom": "8px"}),
                html.Div([
                    html.Span("Continuaron  ", style={"color": TEXT_MUTED}),
                    html.Span("→  Total cohorte − Desertores.",
                              style={"color": TEXT_MAIN}),
                ], style={"marginBottom": "8px"}),
                html.Div([
                    html.Span("Tasa de deserción  ", style={"color": TEXT_MUTED}),
                    html.Span("→  (Desertores / Total cohorte) × 100.",
                              style={"color": TEXT_MAIN}),
                ], style={"marginBottom": "8px"}),
                html.Div([
                    html.Span("Tasa de transición educativa  ", style={"color": TEXT_MUTED}),
                    html.Span("→  (Continuaron / Total cohorte) × 100.",
                              style={"color": TEXT_MAIN}),
                ]),
            ], style={
                "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "12px",
                "lineHeight": "1.8", "color": TEXT_MAIN,
            }),
        ], extra_style={"borderColor": ACCENT4 + "44"}),

        # ── Footer ──────────────────────────────────────────
        html.Div(f"ICFES · Análisis de deserción · Cohorte {anno}",
                 style={"textAlign": "center", "color": TEXT_MUTED, "fontSize": "10px",
                        "letterSpacing": "2px", "paddingTop": "20px",
                        "borderTop": f"1px solid {BORDER}"}),
    ])

# ─────────────────────────────────────────────────────────────
# CARGA Y EXPOSICIÓN DEL LAYOUT
# ─────────────────────────────────────────────────────────────
_data  = load_or_build(force="--rebuild" in sys.argv)
layout = build_layout(_data)