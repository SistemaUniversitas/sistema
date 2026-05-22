"""
Dashboard ICFES – Deserción Académica por Cohorte (Genérico 2010–2018)
=======================================================================
Fuente: PostgreSQL (mismo esquema que Saber_Pro_Puntajes.py)
  - saber11_{año} : datos Saber 11 por cohorte (2010–2018)
  - llaves        : pares estu_consecutivo_sb11 ↔ estu_consecutivo_sbpro
                    (estudiantes que llegaron a Saber Pro 2015–2023)

Lógica:
  - Total cohorte  = filas en saber11_{año}
  - Continuaron    = estudiantes con llave coincidente en `llaves`
                     (estu_consecutivo aparece en llaves.estu_consecutivo_sb11)
  - Desertores     = Total − Continuaron (sin llave → no llegaron a Saber Pro)
  - Tasa deserción = (Desertores / Total) × 100

Cache en disco (Cache/):
  - desercion_generica_meta.pkl         → KPIs por año {año: {...}}
  - desercion_generica_desertores.parquet → filas de desertores con anio_cohorte

Para forzar reprocesamiento:
    python Pages/Desercion_Generica.py --rebuild
"""

import sys
import pickle
import time
from pathlib import Path
import warnings

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, callback
import dash

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# REGISTRO DE PÁGINA
# ─────────────────────────────────────────────────────────────
dash.register_page(__name__, path="/desercion", name="Deserción · Por Cohorte")

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN POSTGRES
# ─────────────────────────────────────────────────────────────
PG_HOST     = "localhost"
PG_PORT     = 5432
PG_DATABASE = "TrabajoGrado"
PG_USER     = "postgres"
PG_PASSWORD = "postgres"
PG_SCHEMA   = "public"

# Cohortes Saber 11 analizadas (se comparan con SB Pro 2015–2023 vía llaves)
SB11_YEARS = list(range(2010, 2019))  # 2010 a 2018

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR     = DASHBOARD_DIR / "Cache"
CACHE_META    = CACHE_DIR / "desercion_generica_meta.pkl"
CACHE_DES     = CACHE_DIR / "desercion_generica_desertores.parquet"

# Columnas del saber11 necesarias para los gráficos de desertores
SB11_DES_COLS = [
    "estu_consecutivo",
    "fami_estratovivienda",
    "cole_naturaleza",
    "cole_area_ubicacion",
    "estu_depto_presentacion",
]

# ─────────────────────────────────────────────────────────────
# PALETA Y ESTILO
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
# HELPERS DE FIGURAS
# ─────────────────────────────────────────────────────────────

def empty_fig(msg="Sin datos para los filtros seleccionados"):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False,
                       font=dict(color=TEXT_MUTED, size=13),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_layout(**LAYOUT_BASE,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def bar_v_fig(index, values, colors=None, color=ACCENT2, xlab="", ylab=""):
    if not len(values):
        return empty_fig()
    fig = go.Figure(go.Bar(
        x=[str(l) for l in index], y=list(values),
        marker=dict(
            color=colors if colors else color,
            line=dict(color="rgba(0,0,0,0)"),
        ),
        hovertemplate="%{x}<br>%{y:,}<extra></extra>",
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        xaxis=dict(gridcolor="rgba(0,0,0,0)", title=xlab),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, title=ylab),
    )
    return fig


def gauge_fig(value, title=""):
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


def donut_fig(continuaron, desertaron):
    fig = go.Figure(go.Pie(
        labels=["Continuaron a Saber Pro", "Desertaron"],
        values=[continuaron, desertaron],
        hole=0.55,
        marker=dict(colors=[ACCENT2, ACCENT3], line=dict(color=BG, width=3)),
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


def pie_fig(index, values):
    if not len(index):
        return empty_fig()
    fig = go.Figure(go.Pie(
        labels=[str(v) for v in index],
        values=list(values),
        hole=0.45,
        marker=dict(colors=PALETTE, line=dict(color=BG, width=2)),
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

# ─────────────────────────────────────────────────────────────
# POSTGRES HELPERS
# ─────────────────────────────────────────────────────────────

def pg_connect():
    import psycopg2
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = %s",
        (PG_SCHEMA, table),
    )
    return cur.fetchone() is not None


def _table_columns(cur, table: str) -> set:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (PG_SCHEMA, table),
    )
    return {row[0] for row in cur.fetchall()}

# ─────────────────────────────────────────────────────────────
# CONSTRUCCIÓN DE CACHÉ
# ─────────────────────────────────────────────────────────────

def build_cache() -> tuple:
    print("=" * 65)
    print("  Construyendo caché de deserción genérica (2010–2018)…")
    print("  Fuente: Postgres · saber11_XXXX × llaves")
    print("=" * 65)
    t0 = time.time()

    conn = pg_connect()
    cur  = conn.cursor()

    meta       = {}   # {year: {total, continuaron, desertores, tasa_desercion, tasa_transicion}}
    des_frames = []   # DataFrames de detalle de desertores por año

    for year in SB11_YEARS:
        table = f"saber11_{year}"
        print(f"  [{year}] Verificando {table}…", end=" ")

        if not _table_exists(cur, table):
            print("no existe, omitiendo.")
            continue

        avail = _table_columns(cur, table)

        if "estu_consecutivo" not in avail:
            print("sin columna estu_consecutivo, omitiendo.")
            continue

        print(f"OK ({len(avail)} columnas)")

        # ── 1. Total de la cohorte ──────────────────────────────
        cur.execute(f"SELECT COUNT(*) FROM {PG_SCHEMA}.{table}")
        total = cur.fetchone()[0]

        # ── 2. Continuaron: tienen llave en la tabla llaves ─────
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {PG_SCHEMA}.{table} s
            INNER JOIN {PG_SCHEMA}.llaves l
                ON s.estu_consecutivo::text = l.estu_consecutivo_sb11::text
            """
        )
        continuaron = cur.fetchone()[0]
        desertores  = total - continuaron
        tasa_d      = round((desertores / total) * 100, 2) if total > 0 else 0.0
        tasa_t      = round((continuaron / total) * 100, 2) if total > 0 else 0.0

        meta[year] = {
            "total":           total,
            "continuaron":     continuaron,
            "desertores":      desertores,
            "tasa_desercion":  tasa_d,
            "tasa_transicion": tasa_t,
        }
        print(f"         total={total:,}  continuaron={continuaron:,}  "
              f"desertores={desertores:,}  tasa={tasa_d:.1f}%")

        # ── 3. Detalle de desertores (anti-join con llaves) ─────
        detail_cols = [c for c in SB11_DES_COLS if c in avail and c != "estu_consecutivo"]
        if detail_cols:
            sel = ", ".join(f"s.{c}" for c in detail_cols)
            cur.execute(
                f"""
                SELECT {sel}
                FROM {PG_SCHEMA}.{table} s
                LEFT JOIN {PG_SCHEMA}.llaves l
                    ON s.estu_consecutivo::text = l.estu_consecutivo_sb11::text
                WHERE l.estu_consecutivo_sb11 IS NULL
                """
            )
            rows = cur.fetchall()
            if rows:
                df_y = pd.DataFrame(rows, columns=detail_cols)
                df_y["anio_cohorte"] = year
                des_frames.append(df_y)
                print(f"         detalle desertores: {len(df_y):,} filas")

    cur.close()
    conn.close()

    # ── 4. Consolidar y persistir ───────────────────────────────
    df_des = pd.concat(des_frames, ignore_index=True) if des_frames else pd.DataFrame()

    CACHE_DIR.mkdir(exist_ok=True)
    with open(CACHE_META, "wb") as f:
        pickle.dump(meta, f, protocol=pickle.HIGHEST_PROTOCOL)

    if not df_des.empty:
        for c in df_des.select_dtypes(include="object").columns:
            df_des[c] = df_des[c].astype(str)
        df_des.to_parquet(CACHE_DES, index=False, compression="snappy")

    print(f"\n  ✅ Caché lista en {time.time()-t0:.1f}s")
    print(f"     Cohortes procesadas : {sorted(meta.keys())}")
    print(f"     Filas de desertores : {len(df_des):,}")
    print("=" * 65)
    return meta, df_des


def load_or_build(force=False) -> tuple:
    if not force and CACHE_META.exists() and CACHE_DES.exists():
        print("  Cargando caché deserción genérica…", end=" ", flush=True)
        t0 = time.time()
        try:
            with open(CACHE_META, "rb") as f:
                meta = pickle.load(f)
            df_des = pd.read_parquet(CACHE_DES)
            print(f"OK ({time.time()-t0:.1f}s) · cohortes={sorted(meta.keys())} "
                  f"· desertores={len(df_des):,}")
            return meta, df_des
        except Exception as e:
            print(f"ERROR: {e} — reconstruyendo…")
    try:
        return build_cache()
    except Exception as e:
        print(f"  ❌ No se pudo construir el caché: {e}")
        print("  ⚠️  La página cargará sin datos. Verifica la conexión a Postgres.")
        return {}, pd.DataFrame()


_META, _DF_DES = load_or_build(force="--rebuild" in sys.argv)

# ─────────────────────────────────────────────────────────────
# GRÁFICOS DE RESUMEN (estáticos — todas las cohortes)
# ─────────────────────────────────────────────────────────────

def _overview_figs():
    if not _META:
        return empty_fig("Sin datos"), empty_fig("Sin datos")

    years      = sorted(_META.keys())
    tasas      = [_META[y]["tasa_desercion"] for y in years]
    continuaron = [_META[y]["continuaron"]   for y in years]
    desertores  = [_META[y]["desertores"]    for y in years]

    # Tasa de deserción por cohorte (colores verde→rojo)
    colors_tasa = [
        f"hsl({int(120 - 120 * t / 100)}, 70%, 55%)" for t in tasas
    ]
    fig_tasa = go.Figure(go.Bar(
        x=[str(y) for y in years], y=tasas,
        marker=dict(color=colors_tasa, line=dict(color="rgba(0,0,0,0)")),
        text=[f"{t:.1f}%" for t in tasas],
        textposition="outside",
        textfont=dict(size=10, color=TEXT_MUTED),
        hovertemplate="Cohorte %{x}<br>Tasa: %{y:.2f}%<extra></extra>",
    ))
    fig_tasa.update_layout(
        **LAYOUT_BASE,
        xaxis=dict(title="Cohorte (año Saber 11)", gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="Tasa de deserción (%)", gridcolor=BORDER,
                   zerolinecolor=BORDER, range=[0, max(tasas) * 1.15 if tasas else 100]),
    )

    # Composición: continuaron vs desertaron (barras apiladas)
    fig_comp = go.Figure()
    fig_comp.add_trace(go.Bar(
        name="Continuaron a Saber Pro",
        x=[str(y) for y in years], y=continuaron,
        marker=dict(color=ACCENT2),
        hovertemplate="Cohorte %{x}<br>Continuaron: %{y:,}<extra></extra>",
    ))
    fig_comp.add_trace(go.Bar(
        name="Desertaron",
        x=[str(y) for y in years], y=desertores,
        marker=dict(color=ACCENT3),
        hovertemplate="Cohorte %{x}<br>Desertaron: %{y:,}<extra></extra>",
    ))
    fig_comp.update_layout(
        **LAYOUT_BASE,
        barmode="stack",
        xaxis=dict(title="Cohorte (año Saber 11)", gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="Estudiantes", gridcolor=BORDER, zerolinecolor=BORDER),
        legend=dict(
            font=dict(color=TEXT_MAIN, size=10),
            bgcolor="rgba(0,0,0,0)",
            orientation="h", yanchor="bottom", y=1.02, x=0,
        ),
    )
    return fig_tasa, fig_comp


_FIG_TASA_OV, _FIG_COMP_OV = _overview_figs()

# ─────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────

def card(children, extra_style=None):
    style = {
        "background": CARD_BG, "border": f"1px solid {BORDER}",
        "borderRadius": "12px", "padding": "20px", "marginBottom": "20px",
    }
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
            html.Div(subtitle, style={"color": TEXT_MUTED, "fontSize": "10px",
                                     "marginTop": "4px"})
        )
    return html.Div(children, style={
        "background": BG, "border": f"1px solid {BORDER}", "borderRadius": "8px",
        "padding": "18px 22px", "textAlign": "center", "flex": "1",
        "minWidth": "160px", "fontFamily": "'IBM Plex Mono', monospace",
    })


def g(gid, height="300px"):
    return dcc.Graph(id=gid, config={"displayModeBar": False},
                     style={"height": height})


def row(*children, gap="16px"):
    return html.Div(list(children),
                    style={"display": "flex", "flexWrap": "wrap", "gap": gap})


def col(children, flex="1", min_width="280px"):
    return html.Div(children, style={"flex": flex, "minWidth": min_width})

# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────

YEAR_OPTS     = [{"label": str(y), "value": y} for y in sorted(_META.keys())]
_DEFAULT_YEAR = sorted(_META.keys())[0] if _META else None

layout = html.Div(style={
    "background": BG, "minHeight": "100vh",
    "fontFamily": "'IBM Plex Mono', monospace",
    "color": TEXT_MAIN, "padding": "24px 32px",
}, children=[

    # ── Header ──────────────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("ICFES · DESERCIÓN ACADÉMICA · COHORTES 2010–2018", style={
                "color": ACCENT1, "fontSize": "11px", "letterSpacing": "4px"}),
            html.H1("Deserción Estudiantil por Cohorte", style={
                "margin": "4px 0 0 0", "fontSize": "28px", "fontWeight": "700",
                "color": TEXT_MAIN, "letterSpacing": "-0.5px"}),
            html.Div(
                f"Fuente: jdbc:postgresql://{PG_HOST}:{PG_PORT}/{PG_DATABASE} "
                "· saber11_2010..2018 × llaves",
                style={"color": TEXT_MUTED, "fontSize": "10px",
                       "letterSpacing": "1px", "marginTop": "6px"},
            ),
        ]),
        html.Div([
            html.Div("COHORTES ANALIZADAS", style={
                "color": TEXT_MUTED, "fontSize": "10px", "letterSpacing": "2px"}),
            html.Div(str(len(_META)), style={
                "color": ACCENT4, "fontSize": "42px", "fontWeight": "700",
                "letterSpacing": "-1px"}),
        ], style={"textAlign": "right"}),
    ], style={
        "display": "flex", "justifyContent": "space-between", "alignItems": "flex-end",
        "marginBottom": "28px", "paddingBottom": "20px",
        "borderBottom": f"1px solid {BORDER}",
    }),

    # ── Resumen general (todas las cohortes) ────────────────────
    card([
        section_title("Resumen general · todas las cohortes"),
        row(
            col([
                html.Div("Tasa de deserción por cohorte",
                         style={"color": TEXT_MUTED, "fontSize": "11px",
                                "marginBottom": "8px"}),
                dcc.Graph(figure=_FIG_TASA_OV, config={"displayModeBar": False},
                          style={"height": "300px"}),
            ]),
            col([
                html.Div("Composición: continuaron vs desertaron",
                         style={"color": TEXT_MUTED, "fontSize": "11px",
                                "marginBottom": "8px"}),
                dcc.Graph(figure=_FIG_COMP_OV, config={"displayModeBar": False},
                          style={"height": "300px"}),
            ]),
        ),
    ]),

    # ── Filtro + KPIs dinámicos ──────────────────────────────────
    card([
        section_title("Análisis por cohorte"),
        html.Div([
            html.Div("Seleccionar cohorte (año Saber 11)",
                     style={"color": TEXT_MUTED, "fontSize": "10px",
                            "letterSpacing": "1.5px", "marginBottom": "8px",
                            "textTransform": "uppercase"}),
            dcc.Dropdown(
                id="des-f-cohorte",
                options=YEAR_OPTS,
                value=_DEFAULT_YEAR,
                clearable=False,
                style={"color": "#000", "fontSize": "13px", "maxWidth": "220px"},
            ),
        ], style={"marginBottom": "20px"}),
        html.Div(id="des-kpi-row"),
    ]),

    # ── Gauge + Donut ────────────────────────────────────────────
    card([
        section_title("Visualización de la deserción"),
        row(
            col([
                html.Div("Tasa de deserción", style={
                    "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px"}),
                g("des-fig-gauge", "320px"),
            ]),
            col([
                html.Div("Distribución: continuaron vs desertaron", style={
                    "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px"}),
                g("des-fig-donut", "320px"),
            ]),
        ),
    ]),

    # ── Desertores por estrato ───────────────────────────────────
    card([
        section_title("Desertores por estrato socioeconómico"),
        g("des-fig-estrato", "340px"),
    ]),

    # ── Naturaleza + zona ────────────────────────────────────────
    card([
        section_title("Perfil de desertores por tipo y zona de colegio"),
        row(
            col([
                html.Div("Naturaleza del colegio", style={
                    "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px"}),
                g("des-fig-naturaleza", "340px"),
            ]),
            col([
                html.Div("Zona del colegio", style={
                    "color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "8px"}),
                g("des-fig-area", "340px"),
            ]),
        ),
    ]),

    # ── Top 10 departamentos ─────────────────────────────────────
    card([
        section_title("Top 10 departamentos con mayor deserción"),
        g("des-fig-depto", "360px"),
    ]),

    # ── Nota metodológica ────────────────────────────────────────
    card([
        section_title("Nota metodológica"),
        html.Div([
            html.Div([
                html.Span("Total cohorte  ", style={"color": TEXT_MUTED}),
                html.Span("→  número de filas en saber11_{año} para el cohorte seleccionado.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Continuaron  ", style={"color": TEXT_MUTED}),
                html.Span("→  estudiantes con coincidencia en llaves.estu_consecutivo_sb11 "
                          "(llegaron a Saber Pro 2015–2023).",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Desertores  ", style={"color": TEXT_MUTED}),
                html.Span("→  Total cohorte − Continuaron (sin llave → no llegaron a Saber Pro).",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Tasa de deserción  ", style={"color": TEXT_MUTED}),
                html.Span("→  (Desertores / Total cohorte) × 100.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Saber 11  ", style={"color": TEXT_MUTED}),
                html.Span("→  cohortes 2010–2018 · tablas saber11_{año} en Postgres.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Saber Pro  ", style={"color": TEXT_MUTED}),
                html.Span("→  resultados 2015–2023 · cruzados vía tabla pública llaves.",
                          style={"color": TEXT_MAIN}),
            ]),
        ], style={
            "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "12px",
            "lineHeight": "1.8", "color": TEXT_MAIN,
        }),
    ], extra_style={"borderColor": ACCENT4 + "44"}),

    # ── Footer ───────────────────────────────────────────────────
    html.Div("ICFES · Análisis de deserción · Cohortes 2010–2018",
             style={"textAlign": "center", "color": TEXT_MUTED, "fontSize": "10px",
                    "letterSpacing": "2px", "paddingTop": "20px",
                    "borderTop": f"1px solid {BORDER}"}),
])

# ─────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────

@callback(
    Output("des-kpi-row",        "children"),
    Output("des-fig-gauge",      "figure"),
    Output("des-fig-donut",      "figure"),
    Output("des-fig-estrato",    "figure"),
    Output("des-fig-naturaleza", "figure"),
    Output("des-fig-area",       "figure"),
    Output("des-fig-depto",      "figure"),
    Input("des-f-cohorte",       "value"),
)
def update_cohorte(year):
    _no_data = (
        html.Div("Sin cohorte seleccionada.",
                 style={"color": TEXT_MUTED,
                        "fontFamily": "'IBM Plex Mono', monospace"}),
        empty_fig(), empty_fig(),
        empty_fig(), empty_fig(), empty_fig(), empty_fig(),
    )

    if year is None or year not in _META:
        return _no_data

    m           = _META[year]
    total       = m["total"]
    continuaron = m["continuaron"]
    desertores  = m["desertores"]
    tasa_d      = m["tasa_desercion"]
    tasa_t      = m["tasa_transicion"]
    tasa_color  = ACCENT2 if tasa_d < 20 else (ACCENT5 if tasa_d < 40 else ACCENT3)

    kpis = row(
        kpi_box("Presentaron Saber 11", f"{total:,}",       ACCENT1, f"Cohorte {year}"),
        kpi_box("Desertaron",           f"{desertores:,}",  ACCENT3, "Sin llave en Saber Pro"),
        kpi_box("Continuaron",          f"{continuaron:,}", ACCENT2, "Con llave en Saber Pro"),
        kpi_box("Tasa de deserción",    f"{tasa_d:.2f}%",   tasa_color, "Desertores / Total cohorte"),
        kpi_box("Tasa de transición",   f"{tasa_t:.2f}%",   ACCENT2,    "Continuaron / Total cohorte"),
    )

    fig_gauge = gauge_fig(tasa_d, "Tasa de deserción")
    fig_donut = donut_fig(continuaron, desertores)

    if _DF_DES.empty or "anio_cohorte" not in _DF_DES.columns:
        return kpis, fig_gauge, fig_donut, empty_fig(), empty_fig(), empty_fig(), empty_fig()

    d = _DF_DES[_DF_DES["anio_cohorte"] == year]

    # Estrato socioeconómico
    if "fami_estratovivienda" in d.columns:
        vc = d["fami_estratovivienda"].fillna("No reporta").value_counts().sort_index()
        n  = len(vc)
        colors = [f"hsl({int(10 + 200 * i / max(n - 1, 1))}, 70%, 55%)" for i in range(n)]
        fig_estrato = bar_v_fig(list(vc.index), list(vc.values),
                                colors=colors, xlab="Estrato", ylab="Desertores")
    else:
        fig_estrato = empty_fig("Columna 'fami_estratovivienda' no disponible en esta cohorte")

    # Naturaleza del colegio
    if "cole_naturaleza" in d.columns:
        vc = d["cole_naturaleza"].fillna("No reporta").value_counts()
        fig_naturaleza = pie_fig(list(vc.index), list(vc.values))
    else:
        fig_naturaleza = empty_fig("Columna 'cole_naturaleza' no disponible en esta cohorte")

    # Zona / área del colegio
    if "cole_area_ubicacion" in d.columns:
        vc = d["cole_area_ubicacion"].fillna("No reporta").value_counts()
        fig_area = pie_fig(list(vc.index), list(vc.values))
    else:
        fig_area = empty_fig("Columna 'cole_area_ubicacion' no disponible en esta cohorte")

    # Top 10 departamentos
    if "estu_depto_presentacion" in d.columns:
        vc = d["estu_depto_presentacion"].fillna("No reporta").value_counts().head(10)
        fig_depto = bar_v_fig(list(vc.index), list(vc.values),
                              color=ACCENT5, xlab="Departamento", ylab="Desertores")
    else:
        fig_depto = empty_fig("Columna 'estu_depto_presentacion' no disponible en esta cohorte")

    return kpis, fig_gauge, fig_donut, fig_estrato, fig_naturaleza, fig_area, fig_depto
