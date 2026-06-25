import sys
import warnings
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table, Input, Output, State, callback
import dash

# Motor de reportes (vive en desarrolloInterfaz/Services).
sys.path.append(str(Path(__file__).resolve().parents[1]))
import Services.report_engine as RE

warnings.filterwarnings("ignore")

dash.register_page(__name__, path="/probabilidad-estrato",
                   name="Probabilidad · Estrato")

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN POSTGRES
# ─────────────────────────────────────────────────────────────
PG_HOST     = "localhost"
PG_PORT     = 5432
PG_DATABASE = "TrabajoGrado"
PG_USER     = "postgres"
PG_PASSWORD = "postgres"
PG_SCHEMA   = "public"

YEARS     = list(range(2014, 2024))
YEAR_OPTS = [{"label": str(y), "value": y} for y in YEARS]

# Valores que se agrupan en "No aplica"
_NO_APLICA = {"ninguno", "no sabe", "no aplica"}

# ─────────────────────────────────────────────────────────────
# PALETA Y ESTILO (idéntica a Saber_Pro_Unificado.py)
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
# UI HELPERS
# ─────────────────────────────────────────────────────────────
def card(children, extra_style=None):
    style = {"background": CARD_BG, "border": f"1px solid {BORDER}",
             "borderRadius": "12px", "padding": "20px", "marginBottom": "20px"}
    if extra_style:
        style.update(extra_style)
    return html.Div(children, style=style)

def section_title(text):
    return html.H3(text, style={
        "color": ACCENT1, "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "13px", "letterSpacing": "2px", "textTransform": "uppercase",
        "marginBottom": "16px", "marginTop": "0",
        "borderLeft": f"3px solid {ACCENT1}", "paddingLeft": "10px",
    })

def sublabel(text):
    return html.Div(text, style={
        "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px",
        "fontFamily": "'IBM Plex Mono', monospace",
    })

def row(*children, gap="16px"):
    return html.Div(list(children),
                    style={"display": "flex", "flexWrap": "wrap", "gap": gap})

def col(children, flex="1", min_width="280px"):
    return html.Div(children, style={"flex": flex, "minWidth": min_width})

def _dd_label(text):
    return html.Div(text, style={
        "color": TEXT_MUTED, "fontSize": "10px", "letterSpacing": "1.5px",
        "marginBottom": "4px", "textTransform": "uppercase",
        "fontFamily": "'IBM Plex Mono', monospace",
    })

def kpi_box(label, value, color=ACCENT1):
    return html.Div([
        html.Div(label, style={"color": TEXT_MUTED, "fontSize": "10px",
                               "letterSpacing": "1.5px",
                               "textTransform": "uppercase"}),
        html.Div(value, style={"color": color, "fontSize": "22px",
                               "fontWeight": "700", "marginTop": "4px"}),
    ], style={"background": BG, "border": f"1px solid {BORDER}",
              "borderRadius": "8px", "padding": "14px 18px",
              "textAlign": "center", "flex": "1", "minWidth": "120px",
              "fontFamily": "'IBM Plex Mono', monospace"})

# ─────────────────────────────────────────────────────────────
# CARGA DESDE POSTGRES
# ─────────────────────────────────────────────────────────────
_cache: dict[int, pd.DataFrame] = {}

def _norm_edu(val) -> str:
    """Agrupa Ninguno/No sabe/No Aplica → 'No aplica'."""
    if pd.isna(val):
        return val
    v = str(val).strip().lower()
    return "No aplica" if v in _NO_APLICA else str(val).strip()

def load_year(year: int) -> tuple:
    """Carga fami_educacion* y fami_estratovivienda de saberpro_{year}."""
    if year in _cache:
        return _cache[year], None
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD,
        )
        table = f'"{PG_SCHEMA}"."saberpro_{year}"'
        df = pd.read_sql(
            f"SELECT fami_educacionpadre, fami_educacionmadre, "
            f"fami_estratovivienda FROM {table}",
            conn,
        )
        conn.close()
        df["fami_educacionpadre"] = df["fami_educacionpadre"].apply(_norm_edu)
        df["fami_educacionmadre"] = df["fami_educacionmadre"].apply(_norm_edu)
        _cache[year] = df
        return df, None
    except Exception as e:
        return None, str(e)

def _edu_options(df: pd.DataFrame, col: str) -> list:
    if df is None or col not in df.columns:
        return []
    vals = sorted(df[col].dropna().unique(), key=str)
    return [{"label": str(v), "value": str(v)} for v in vals]

# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────
layout = html.Div(style={
    "background": BG, "minHeight": "100vh",
    "fontFamily": "'IBM Plex Mono', monospace",
    "color": TEXT_MAIN, "padding": "24px 32px",
}, children=[

    # ── Header ──
    html.Div([
        html.Div([
            html.Div("ICFES · SABER PRO · ANÁLISIS PROBABILÍSTICO",
                     style={"color": ACCENT1, "fontSize": "11px",
                            "letterSpacing": "4px"}),
            html.H1("Probabilidad de estrato socioeconómico", style={
                "margin": "4px 0 0 0", "fontSize": "28px",
                "fontWeight": "700", "color": TEXT_MAIN,
            }),
            html.Div("P(Estrato | Educación del padre, Educación de la madre)",
                     style={"color": TEXT_MUTED, "fontSize": "10px",
                            "letterSpacing": "1px", "marginTop": "6px"}),
        ]),
    ], style={"marginBottom": "28px", "paddingBottom": "20px",
              "borderBottom": f"1px solid {BORDER}"}),

    # ── 1. Selección de tabla ──
    card([
        section_title("Fuente de datos · Tabla Postgres"),
        sublabel("Selecciona el año para cargar la tabla saberpro_YYYY"),
        row(
            col([
                _dd_label("Año / Tabla"),
                dcc.Dropdown(
                    id="prob-year",
                    options=YEAR_OPTS,
                    value=None,
                    placeholder="Selecciona un año…",
                    clearable=True,
                    style={"color": "#000", "fontSize": "12px"},
                ),
            ], min_width="200px"),
            col([
                html.Div(id="prob-load-status",
                         style={"color": TEXT_MUTED, "fontSize": "12px",
                                "marginTop": "22px",
                                "fontFamily": "'IBM Plex Mono', monospace"}),
            ]),
        ),
    ]),

    # ── 2. Consulta ──
    card([
        section_title("Consulta · Nivel educativo de los padres"),
        sublabel("Elige el nivel de educación del padre y/o la madre para "
                 "calcular la distribución de estratos del estudiante."),
        row(
            col([
                _dd_label("Educación del padre"),
                dcc.Dropdown(
                    id="prob-padre",
                    options=[],
                    placeholder="Selecciona nivel educativo…",
                    clearable=True,
                    disabled=True,
                    style={"color": "#000", "fontSize": "12px"},
                ),
            ]),
            col([
                _dd_label("Educación de la madre"),
                dcc.Dropdown(
                    id="prob-madre",
                    options=[],
                    placeholder="Selecciona nivel educativo…",
                    clearable=True,
                    disabled=True,
                    style={"color": "#000", "fontSize": "12px"},
                ),
            ]),
        ),
        html.Button(
            "▶  Calcular probabilidad de estrato",
            id="prob-calc-btn",
            disabled=True,
            style={
                "marginTop": "24px", "padding": "11px 28px",
                "backgroundColor": ACCENT1, "color": BG,
                "border": "none", "borderRadius": "8px", "fontSize": "13px",
                "cursor": "pointer", "fontWeight": "700",
                "fontFamily": "'IBM Plex Mono', monospace",
                "letterSpacing": "1px",
            },
        ),
    ]),

    # ── 3. Resultados ──
    html.Div(id="prob-results"),
])

# ─────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────

@callback(
    Output("prob-padre",      "options"),
    Output("prob-madre",      "options"),
    Output("prob-padre",      "disabled"),
    Output("prob-madre",      "disabled"),
    Output("prob-calc-btn",   "disabled"),
    Output("prob-padre",      "value"),
    Output("prob-madre",      "value"),
    Output("prob-load-status","children"),
    Input("prob-year", "value"),
    prevent_initial_call=True,
)
def on_year_selected(year):
    if year is None:
        return [], [], True, True, True, None, None, ""

    df, error = load_year(year)
    if error:
        msg = html.Span(f"❌ Error al conectar con Postgres: {error}",
                        style={"color": ACCENT3})
        return [], [], True, True, True, None, None, msg

    padre_opts = _edu_options(df, "fami_educacionpadre")
    madre_opts = _edu_options(df, "fami_educacionmadre")
    msg = html.Span(
        f"✔  saberpro_{year} cargada · {len(df):,} registros",
        style={"color": ACCENT2},
    )
    return padre_opts, madre_opts, False, False, False, None, None, msg


@callback(
    Output("prob-results", "children"),
    Output("report-store-probestrato", "data"),
    Input("prob-calc-btn", "n_clicks"),
    State("prob-year",  "value"),
    State("prob-padre", "value"),
    State("prob-madre", "value"),
    prevent_initial_call=True,
)
def compute_probabilities(_n, year, padre_val, madre_val):
    _empty = RE.publish_payload("probestrato", {}, {})
    if year is None or year not in _cache:
        return _alert("⚠  Selecciona primero un año para cargar los datos."), _empty

    if not padre_val and not madre_val:
        return _alert("⚠  Selecciona al menos uno de los niveles educativos."), _empty

    df = _cache[year]

    mask = pd.Series([True] * len(df), index=df.index)
    if padre_val:
        mask &= df["fami_educacionpadre"].astype(str) == padre_val
    if madre_val:
        mask &= df["fami_educacionmadre"].astype(str) == madre_val

    estrato_series = df.loc[mask, "fami_estratovivienda"].dropna()
    n_total = len(estrato_series)

    if n_total == 0:
        return _alert("⚠  No se encontraron estudiantes con esa combinación."), _empty

    counts = estrato_series.astype(str).value_counts().sort_index()
    probs  = (counts / n_total * 100).round(2)

    best_estrato = probs.idxmax()
    best_prob    = probs.max()

    result_df = pd.DataFrame({
        "Estrato":           counts.index,
        "Casos":             counts.values,
        "Probabilidad (%)":  probs.values,
    })

    # ── Gráfico ──
    bar_colors = [ACCENT3 if e == best_estrato else ACCENT1
                  for e in result_df["Estrato"]]
    fig = go.Figure(go.Bar(
        x=result_df["Estrato"],
        y=result_df["Probabilidad (%)"],
        marker_color=bar_colors,
        text=[f"{p:.1f}%" for p in result_df["Probabilidad (%)"]],
        textposition="outside",
        textfont=dict(color=TEXT_MAIN, size=11),
        hovertemplate=(
            "<b>Estrato %{x}</b><br>"
            "Probabilidad: %{y:.2f}%<br>"
            "Casos: %{customdata}<extra></extra>"
        ),
        customdata=result_df["Casos"],
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        xaxis=dict(title="Estrato socioeconómico",
                   gridcolor="rgba(0,0,0,0)", zerolinecolor=BORDER),
        yaxis=dict(title="Probabilidad (%)",
                   gridcolor=BORDER, zerolinecolor=BORDER,
                   range=[0, min(100, best_prob * 1.35)]),
        height=380,
        showlegend=False,
    )

    condition_parts = []
    if padre_val:
        condition_parts.append(f"Padre: {padre_val}")
    if madre_val:
        condition_parts.append(f"Madre: {madre_val}")
    condition_text = " | ".join(condition_parts)

    # ── Tabla ──
    TABLE_STYLE = {
        "style_table": {
            "overflowX": "auto", "border": f"1px solid {BORDER}",
            "borderRadius": "8px",
        },
        "style_header": {
            "backgroundColor": BG, "color": ACCENT1,
            "fontFamily": "'IBM Plex Mono', monospace",
            "fontSize": "11px", "letterSpacing": "1.5px",
            "textTransform": "uppercase",
            "border": f"1px solid {BORDER}", "padding": "10px 14px",
        },
        "style_cell": {
            "backgroundColor": CARD_BG, "color": TEXT_MAIN,
            "fontFamily": "'IBM Plex Mono', monospace",
            "fontSize": "12px", "border": f"1px solid {BORDER}",
            "padding": "8px 14px", "textAlign": "center",
        },
        "style_data_conditional": [
            {"if": {"row_index": "odd"}, "backgroundColor": BG},
            {"if": {"filter_query": f'{{Estrato}} = "{best_estrato}"'},
             "color": ACCENT5, "fontWeight": "700"},
        ],
    }

    # ── Payload para el Generador de Reportes ──
    rep_filters = {
        "Año": str(year),
        "Educación del padre": padre_val or "No especificado",
        "Educación de la madre": madre_val or "No especificado",
        "Registros analizados": f"{n_total:,}",
    }
    rep_items = {
        "kpi_best": RE.kpi("Estrato más probable", f"Estrato {best_estrato}"),
        "kpi_prob": RE.kpi("Probabilidad máxima", f"{best_prob:.1f}%"),
        "kpi_n":    RE.kpi("Registros analizados", f"{n_total:,}"),
        "fig_prob": RE.figure("Probabilidad por estrato", fig),
        "table_prob": RE.table(
            "Tabla de probabilidades", ["Estrato", "Casos", "Probabilidad (%)"],
            [[r["Estrato"], r["Casos"], r["Probabilidad (%)"]]
             for r in result_df.to_dict("records")]),
    }
    rep_payload = RE.publish_payload("probestrato", rep_filters, rep_items)

    results_div = html.Div([
        # Condición analizada
        card([
            section_title("Condición analizada"),
            html.Div(style={"display": "flex", "gap": "32px",
                            "flexWrap": "wrap", "marginTop": "8px"},
                     children=[
                html.Div([
                    html.Span("Año: ", style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    html.Span(str(year),
                              style={"fontWeight": "700", "color": ACCENT4}),
                ]),
                html.Div([
                    html.Span("Padre: ", style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    html.Span(padre_val or "No especificado",
                              style={"fontWeight": "700", "color": TEXT_MAIN}),
                ]),
                html.Div([
                    html.Span("Madre: ", style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    html.Span(madre_val or "No especificado",
                              style={"fontWeight": "700", "color": TEXT_MAIN}),
                ]),
                html.Div([
                    html.Span("Registros: ",
                              style={"color": TEXT_MUTED, "fontSize": "12px"}),
                    html.Span(f"{n_total:,}",
                              style={"fontWeight": "700", "color": ACCENT2}),
                ]),
            ]),
        ]),

        # KPI: estrato más probable
        card([
            html.Div(style={"textAlign": "center", "padding": "8px 0"}, children=[
                html.Div("ESTRATO MÁS PROBABLE",
                         style={"color": TEXT_MUTED, "fontSize": "10px",
                                "letterSpacing": "2px"}),
                html.Div(f"Estrato {best_estrato}",
                         style={"color": ACCENT5, "fontSize": "40px",
                                "fontWeight": "700", "margin": "8px 0 4px"}),
                html.Div(f"{best_prob:.1f}% de probabilidad",
                         style={"color": ACCENT5, "fontSize": "16px",
                                "fontWeight": "600"}),
            ]),
        ], extra_style={"borderLeft": f"4px solid {ACCENT5}"}),

        # Gráfico
        card([
            section_title("Distribución de probabilidad por estrato"),
            sublabel(f"P(Estrato | {condition_text})"),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ]),

        # Tabla detallada
        card([
            section_title("Tabla detallada"),
            dash_table.DataTable(
                data=result_df.to_dict("records"),
                columns=[
                    {"name": "Estrato",          "id": "Estrato"},
                    {"name": "Casos",            "id": "Casos"},
                    {"name": "Probabilidad (%)", "id": "Probabilidad (%)"},
                ],
                **TABLE_STYLE,
            ),
        ]),
    ])
    return results_div, rep_payload


def _alert(msg: str):
    return html.Div(msg, style={
        "color": ACCENT5, "padding": "20px",
        "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "13px",
    })
