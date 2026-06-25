"""
Dashboard ICFES Saber Pro – Puntajes Interuniversitarios 2016–2023
===================================================================
Página comparativa: permite seleccionar entre 2 y 4 universidades y
compararlas en las competencias principales de Saber Pro mediante
barras agrupadas, radar, tabla ejecutiva y ranking automático.
Construye y mantiene su propio cache, independiente del resto de
páginas del dashboard.

Cache en disco:
  - Primera ejecución: une todas las tablas anuales vía JDBC y persiste
    el DataFrame en Cache/SaberPro_Interuniversitario_cache.parquet
  - Ejecuciones siguientes: levanta el cache sin arrancar Spark
  - Forzar re-lectura:   python Pages/Saber_Pro_Interuniversitario.py --rebuild
"""

import itertools
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table, Input, Output, callback
from dash.dash_table.Format import Format, Scheme
import dash

# Motor de reportes (vive en desarrolloInterfaz/Services).
sys.path.append(str(Path(__file__).resolve().parents[1]))
import Services.report_engine as RE

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# REGISTRO DE PÁGINA
# ─────────────────────────────────────────────────────────────
if __name__ != "__main__":
    dash.register_page(__name__, path="/saberpro-interuniversitario",
                       name="Saber Pro - Puntajes Interuniversitarios")

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN POSTGRES + JDBC
# ─────────────────────────────────────────────────────────────
PG_HOST     = "localhost"
PG_PORT     = 5432
PG_DATABASE = "TrabajoGrado"
PG_USER     = "postgres"
PG_PASSWORD = "postgres"
PG_SCHEMA   = "public"

YEARS = list(range(2016, 2024))

DASHBOARD_DIR    = Path(__file__).resolve().parents[1]
JDBC_DRIVER_PATH = DASHBOARD_DIR / "JDBC_Driver" / "postgresql-42.7.10.jar"
if not JDBC_DRIVER_PATH.exists():
    JDBC_DRIVER_PATH = DASHBOARD_DIR.parent / "JDBC_Driver" / "postgresql-42.7.10.jar"

JDBC_NUM_PARTITIONS = 4

CACHE_DIR  = DASHBOARD_DIR / "Cache"
CACHE_FILE = CACHE_DIR / "SaberPro_Interuniversitario_cache.parquet"

# Columnas objetivo: solo lo necesario para la comparación interuniversitaria.
COLS_READ = [
    "inst_nombre_institucion",
    "estu_prgm_academico",
    "gruporeferencia",
    "estu_prgm_departamento",
    "mod_razona_cuantitat_punt_norm",
    "mod_lectura_critica_punt_norm",
    "mod_competen_ciudada_punt_norm",
    "mod_ingles_punt_norm",
    "punt_global_norm",
    "punt_global_calc_norm",
]

# Competencias a comparar (mismas etiquetas que el resto del dashboard,
# tomadas de los pares SB11↔SBPro ya definidos para Saber Pro).
COMPETENCIAS = [
    ("mod_razona_cuantitat_punt_norm", "Competencia lógico-cuantitativa"),
    ("mod_lectura_critica_punt_norm",  "Competencia lectora-comunicativa"),
    ("mod_competen_ciudada_punt_norm", "Competencia ciudadana-cívica"),
    ("mod_ingles_punt_norm",           "Competencia en Inglés"),
    ("punt_global_norm",               "Puntaje Global"),
    ("punt_global_calc_norm",          "Puntaje global calculado"),
]
COMP_COLS   = [c for c, _ in COMPETENCIAS]
COMP_LABELS = [l for _, l in COMPETENCIAS]

MIN_UNIV = 2
MAX_UNIV = 4

# ─────────────────────────────────────────────────────────────
# PALETA Y ESTILO (idéntica al resto del dashboard)
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
# LECTURA DESDE POSTGRES VÍA JDBC (PySpark)
# ─────────────────────────────────────────────────────────────

def read_year_via_jdbc(year: int) -> pd.DataFrame | None:
    """Lee una tabla anual. Devuelve None si la tabla no existe o falla."""
    from pyspark.sql import SparkSession

    if not JDBC_DRIVER_PATH.exists():
        raise FileNotFoundError(f"Driver JDBC no encontrado en {JDBC_DRIVER_PATH}")

    spark = (
        SparkSession.builder
        .appName(f"SaberPro_Interuniversitario_Read_{year}")
        .config("spark.jars", str(JDBC_DRIVER_PATH))
        .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
        .config("spark.driver.memory", "4g")
        .config("spark.executor.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    try:
        jdbc_url = f"jdbc:postgresql://{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
        table    = f"{PG_SCHEMA}.saberpro_{year}"
        sdf = (
            spark.read.format("jdbc")
            .option("url", jdbc_url).option("dbtable", table)
            .option("user", PG_USER).option("password", PG_PASSWORD)
            .option("driver", "org.postgresql.Driver")
            .option("fetchsize", 10_000)
            .option("numPartitions", JDBC_NUM_PARTITIONS)
            .load()
        )
        avail = set(sdf.columns)
        selected = [c for c in COLS_READ if c in avail]
        if not selected:
            print(f"    ⚠️  saberpro_{year}: sin columnas objetivo.")
            return None
        df = sdf.select(*selected).toPandas()
        for missing in set(COLS_READ) - set(df.columns):
            df[missing] = None
        df["anio"] = year
        return df
    except Exception as e:
        print(f"    ⚠️  No se pudo leer saberpro_{year}: {e}")
        return None
    finally:
        spark.stop()

def build_cache() -> pd.DataFrame:
    print("=" * 60)
    print("  Construyendo cache Saber Pro Interuniversitario (2016–2023)…")
    print("=" * 60)
    t0 = time.time()

    frames = []
    for y in YEARS:
        print(f"  [{y}] Leyendo saberpro_{y}…")
        df_y = read_year_via_jdbc(y)
        if df_y is not None and len(df_y):
            print(f"         {len(df_y):,} filas")
            frames.append(df_y)

    if not frames:
        raise RuntimeError("No se pudo leer ninguna tabla anual de Saber Pro.")

    df = pd.concat(frames, ignore_index=True)
    print(f"  TOTAL consolidado: {len(df):,} filas · {len(df.columns)} columnas")

    for c in [*COMP_COLS]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].where(df[c].isna(), df[c].astype(str))
    for c in df.select_dtypes(include="float64").columns:
        df[c] = df[c].astype("float32")

    CACHE_DIR.mkdir(exist_ok=True)
    df.to_parquet(CACHE_FILE, index=False, compression="snappy")

    print(f"  ✅ Cache listo en {time.time()-t0:.1f}s → {CACHE_FILE}")
    print("=" * 60)
    _restore_signals()
    return df

def _restore_signals():
    """PySpark hijacks SIGINT/SIGTERM; restores defaults so Flask funcione."""
    import signal
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
    except Exception:
        pass

def load_or_build(force=False) -> pd.DataFrame:
    if not force and CACHE_FILE.exists():
        print(f"  Cargando cache interuniversitario desde {CACHE_FILE}…", end=" ", flush=True)
        t0 = time.time()
        try:
            df = pd.read_parquet(CACHE_FILE)
            print(f"OK ({time.time()-t0:.1f}s) · {len(df):,} filas")
            return df
        except Exception as e:
            print(f"ERROR al leer cache: {e} — intentando reconstruir…")
    try:
        return build_cache()
    except Exception as e:
        print(f"  ❌ No se pudo construir el cache: {e}")
        print("  ⚠️  El dashboard cargará sin datos. Verifica la conexión a Postgres.")
        return pd.DataFrame(columns=COLS_READ + ["anio"])

# ─────────────────────────────────────────────────────────────
# HELPERS DE UI (mismo estilo/estructura usado en el resto del dashboard)
# ─────────────────────────────────────────────────────────────

def empty_fig(msg="Sin datos para los filtros seleccionados"):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False,
                       font=dict(color=TEXT_MUTED, size=13),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_layout(**LAYOUT_BASE,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig

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
        "borderLeft": f"3px solid {ACCENT1}", "paddingLeft": "10px"})

def kpi_box(label, value, color=ACCENT1):
    return html.Div([
        html.Div(label, style={"color": TEXT_MUTED, "fontSize": "10px",
                               "letterSpacing": "1.5px",
                               "textTransform": "uppercase"}),
        html.Div(value, style={"color": color, "fontSize": "20px",
                               "fontWeight": "700", "marginTop": "4px"}),
    ], style={"background": BG, "border": f"1px solid {BORDER}",
              "borderRadius": "8px", "padding": "14px 18px",
              "textAlign": "center", "flex": "1", "minWidth": "200px",
              "fontFamily": "'IBM Plex Mono', monospace"})

def sublabel(text):
    return html.Div(text, style={"color": TEXT_MUTED,
                                 "fontSize": "11px", "marginBottom": "8px"})

def row(*children, gap="16px"):
    return html.Div(list(children), style={"display": "flex",
                                           "flexWrap": "wrap", "gap": gap})

def col(children, flex="1", min_width="280px"):
    return html.Div(children, style={"flex": flex, "minWidth": min_width})

def graph(gid, height="300px"):
    return dcc.Graph(id=gid, config={"displayModeBar": False},
                     style={"height": height})

DROPDOWN_STYLE = {
    "background": BG, "color": TEXT_MAIN,
    "border": f"1px solid {BORDER}", "borderRadius": "6px",
    "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "12px",
}

def dd(ddid, label, options, value=None, multi=False, placeholder="Todos"):
    return html.Div([
        html.Div(label, style={"color": TEXT_MUTED, "fontSize": "10px",
                               "letterSpacing": "1.5px", "marginBottom": "4px",
                               "textTransform": "uppercase"}),
        dcc.Dropdown(
            id=ddid, options=options, value=value, multi=multi,
            placeholder=placeholder, clearable=True,
            style={"color": "#000", "fontSize": "12px"}),
    ], style={"flex": "1", "minWidth": "220px"})

TABLE_STYLE = {
    "style_table": {"overflowX": "auto", "overflowY": "auto",
                    "maxHeight": "420px", "border": f"1px solid {BORDER}",
                    "borderRadius": "8px"},
    "style_header": {"backgroundColor": "#0D1117", "color": ACCENT1,
                     "fontFamily": "'IBM Plex Mono', monospace",
                     "fontSize": "11px", "letterSpacing": "1.5px",
                     "textTransform": "uppercase",
                     "border": f"1px solid {BORDER}", "padding": "10px 14px"},
    "style_cell": {"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                   "fontFamily": "'IBM Plex Mono', monospace",
                   "fontSize": "12px", "border": f"1px solid {BORDER}",
                   "padding": "8px 14px", "textAlign": "left",
                   "whiteSpace": "normal", "height": "auto"},
}
ZEBRA = [{"if": {"row_index": "odd"}, "backgroundColor": "#0D1117"}]

def _radar_placeholder(msg):
    return html.Div(msg, style={"color": TEXT_MUTED, "fontSize": "13px",
                                "textAlign": "center", "padding": "40px"})

# ─────────────────────────────────────────────────────────────
# CARGA INICIAL Y CONSTRUCCIÓN DE OPCIONES
# ─────────────────────────────────────────────────────────────
_DF = load_or_build(force="--rebuild" in sys.argv)


def _clean_inst_name(s):
    """Normaliza nombres de instituciones con comillas de escape CSV duplicadas,
    p. ej. '\"\"\"ESCUELA ... \"\"\"\"JULIO GARAVITO\"\"\"\"-BOGOTÁ D.C.\"\"\"'
    → 'ESCUELA ... JULIO GARAVITO-BOGOTÁ D.C.'."""
    s = str(s)
    while '""' in s:                      # colapsa secuencias de comillas a una
        s = s.replace('""', '"')
    s = s.strip().strip('"').strip()      # quita comillas envolventes
    s = s.replace('"', ' ')               # comillas internas restantes → espacio
    s = " ".join(s.split())               # colapsa espacios
    return s.replace(" -", "-")           # une "NOMBRE -CIUDAD" → "NOMBRE-CIUDAD"


# Limpieza única tras cargar el cache: deja nombres legibles en dropdowns,
# agrupaciones, tablas, rankings y en el payload del Generador de Reportes.
if "inst_nombre_institucion" in _DF.columns:
    _DF["inst_nombre_institucion"] = (
        _DF["inst_nombre_institucion"].astype(str).map(_clean_inst_name))


def _opt_list(series, sort=True):
    vals = pd.Series(series).dropna().astype(str).str.strip()
    vals = vals[vals != ""].unique().tolist()
    if sort: vals = sorted(vals)
    return [{"label": v, "value": v} for v in vals]

DEPTO_OPTS = _opt_list(_DF.get("estu_prgm_departamento", pd.Series(dtype=str)))
GRUPO_OPTS = _opt_list(_DF.get("gruporeferencia", pd.Series(dtype=str)))
PRGM_OPTS  = _opt_list(_DF.get("estu_prgm_academico", pd.Series(dtype=str)))
UNIV_OPTS  = _opt_list(_DF.get("inst_nombre_institucion", pd.Series(dtype=str)))

def _filtered_base(depto, grupo, prgm):
    d = _DF
    if depto:
        d = d[d["estu_prgm_departamento"].isin(depto)]
    if grupo:
        d = d[d["gruporeferencia"].isin(grupo)]
    if prgm:
        d = d[d["estu_prgm_academico"].isin(prgm)]
    return d

# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────

def _filter_bar():
    return card([
        section_title("Filtros"),
        row(
            dd("interuniv-f-depto", "Departamento", DEPTO_OPTS, value=[], multi=True),
            dd("interuniv-f-grupo", "Grupo de referencia", GRUPO_OPTS, value=[], multi=True),
            dd("interuniv-f-prgm",  "Programa académico", PRGM_OPTS, value=[], multi=True),
        ),
        row(
            dd("interuniv-f-univ",
               f"Universidades a comparar ({MIN_UNIV}-{MAX_UNIV})",
               UNIV_OPTS, value=[], multi=True,
               placeholder="Selecciona entre 2 y 4 universidades"),
        ),
        html.Div(id="interuniv-warning", style={
            "color": ACCENT3, "fontSize": "11px", "fontWeight": "700",
            "marginTop": "10px"}),
    ])

def _rank_table(table_id):
    return dash_table.DataTable(
        id=table_id,
        columns=[
            {"name": "Posición",   "id": "Posición"},
            {"name": "Universidad", "id": "Universidad"},
            {"name": "Puntaje",     "id": "Puntaje", "type": "numeric",
             "format": Format(precision=2, scheme=Scheme.fixed)},
        ],
        data=[],
        sort_action="native",
        page_size=10,
        style_data_conditional=ZEBRA,
        **TABLE_STYLE,
    )

layout = html.Div(style={
    "background": BG, "minHeight": "100vh",
    "fontFamily": "'IBM Plex Mono', monospace",
    "color": TEXT_MAIN, "padding": "24px 32px",
}, children=[

    # Header
    html.Div([
        html.Div([
            html.Div("ICFES · SABER PRO · 2016–2023 · INTERUNIVERSITARIO",
                     style={"color": ACCENT1, "fontSize": "11px",
                            "letterSpacing": "4px"}),
            html.H1("Saber Pro - Puntajes Interuniversitarios", style={
                "margin": "4px 0 0 0", "fontSize": "26px",
                "fontWeight": "700", "color": TEXT_MAIN}),
            html.Div(f"Fuente: jdbc:postgresql://{PG_HOST}:{PG_PORT}/"
                     f"{PG_DATABASE} · saberpro_2016..2023",
                     style={"color": TEXT_MUTED, "fontSize": "10px",
                            "letterSpacing": "1px", "marginTop": "6px"}),
        ]),
    ], style={"marginBottom": "20px", "paddingBottom": "20px",
              "borderBottom": f"1px solid {BORDER}"}),

    # KPIs superiores
    card([
        section_title("Indicadores clave"),
        row(
            html.Div(id="interuniv-kpi-best-global", style={"flex": "1", "minWidth": "200px"}),
            html.Div(id="interuniv-kpi-best-calc",   style={"flex": "1", "minWidth": "200px"}),
            html.Div(id="interuniv-kpi-diff",        style={"flex": "1", "minWidth": "200px"}),
            html.Div(id="interuniv-kpi-count",       style={"flex": "1", "minWidth": "200px"}),
        ),
    ]),

    _filter_bar(),

    # Sección 1: Comparación general
    card([
        section_title("1 · Comparación general"),
        sublabel("Puntaje promedio normalizado (0-1) por universidad y competencia."),
        graph("interuniv-fig-bar", "420px"),
    ]),

    # Sección 2: Radar
    card([
        section_title("2 · Comparación por competencias (Radar)"),
        sublabel("Un radar independiente por cada pareja de universidades seleccionadas "
                 "(escala normalizada 0-1, igual para todos)."),
        html.Div(id="interuniv-radar-container"),
    ]),

    # Sección 3: Tabla comparativa ejecutiva
    card([
        section_title("3 · Tabla comparativa ejecutiva"),
        sublabel("Orden por columna, exportación a CSV, resaltado de valores máximos (verde) y mínimos (naranja)."),
        dash_table.DataTable(
            id="interuniv-table-exec",
            columns=[{"name": "Universidad", "id": "Universidad"}],
            data=[],
            sort_action="native",
            export_format="csv",
            export_headers="display",
            style_data_conditional=ZEBRA,
            **TABLE_STYLE,
        ),
    ]),

    # Sección 4: Ranking automático
    card([
        section_title("4 · Ranking automático"),
        sublabel("Clasificación descendente de universidades (según filtros activos) por Puntaje Global y Puntaje Global Calculado."),
        row(
            col([sublabel("Por Puntaje Global"),  _rank_table("interuniv-table-rank-global")]),
            col([sublabel("Por Puntaje Global Calculado"), _rank_table("interuniv-table-rank-calc")]),
        ),
    ]),

    # Footer
    html.Div("ICFES Saber Pro · Puntajes Interuniversitarios 2016–2023",
             style={"textAlign": "center", "color": TEXT_MUTED,
                    "fontSize": "10px", "letterSpacing": "2px",
                    "paddingTop": "20px",
                    "borderTop": f"1px solid {BORDER}"}),
])

# ─────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────

@callback(
    Output("interuniv-f-prgm", "options"),
    Output("interuniv-f-prgm", "value"),
    Input("interuniv-f-grupo", "value"),
    Input("interuniv-f-prgm", "value"),
)
def _update_prgm_options(grupo, prgm_value):
    base = _DF
    if grupo:
        base = base[base["gruporeferencia"].isin(grupo)]
    opts = _opt_list(base["estu_prgm_academico"])
    valid = {o["value"] for o in opts}
    new_value = [v for v in (prgm_value or []) if v in valid]
    return opts, new_value


@callback(
    Output("interuniv-f-univ", "options"),
    Output("interuniv-f-univ", "value"),
    Output("interuniv-warning", "children"),
    Input("interuniv-f-depto", "value"),
    Input("interuniv-f-grupo", "value"),
    Input("interuniv-f-prgm", "value"),
    Input("interuniv-f-univ", "value"),
)
def _update_univ_options(depto, grupo, prgm, univ_value):
    base = _filtered_base(depto, grupo, prgm)
    opts = _opt_list(base["inst_nombre_institucion"])
    valid = {o["value"] for o in opts}
    selected = [v for v in (univ_value or []) if v in valid]

    warning = ""
    if len(selected) > MAX_UNIV:
        warning = (f"⚠ Máximo {MAX_UNIV} universidades para comparar. "
                   f"Se conservaron las primeras {MAX_UNIV} seleccionadas.")
        selected = selected[:MAX_UNIV]

    return opts, selected, warning


@callback(
    Output("interuniv-fig-bar", "figure"),
    Output("interuniv-radar-container", "children"),
    Output("interuniv-table-exec", "data"),
    Output("interuniv-table-exec", "columns"),
    Output("interuniv-table-exec", "style_data_conditional"),
    Output("interuniv-table-rank-global", "data"),
    Output("interuniv-table-rank-calc", "data"),
    Output("interuniv-kpi-best-global", "children"),
    Output("interuniv-kpi-best-calc", "children"),
    Output("interuniv-kpi-diff", "children"),
    Output("interuniv-kpi-count", "children"),
    Output("report-store-interuniv", "data"),
    Input("interuniv-f-depto", "value"),
    Input("interuniv-f-grupo", "value"),
    Input("interuniv-f-prgm", "value"),
    Input("interuniv-f-univ", "value"),
)
def _update_all(depto, grupo, prgm, univ):
    d = _filtered_base(depto, grupo, prgm)
    selected = (univ or [])[:MAX_UNIV]

    # KPIs 1 y 2 y rankings: dependen solo de los filtros activos
    # (departamento / grupo / programa), no de la selección de universidades.
    if len(d):
        agg_all = (d.groupby("inst_nombre_institucion")[["punt_global_norm", "punt_global_calc_norm"]]
                   .mean()).dropna(how="all")
    else:
        agg_all = pd.DataFrame(columns=["punt_global_norm", "punt_global_calc_norm"])

    if len(agg_all):
        bg_uni, bg_val = agg_all["punt_global_norm"].idxmax(), agg_all["punt_global_norm"].max()
        bc_uni, bc_val = agg_all["punt_global_calc_norm"].idxmax(), agg_all["punt_global_calc_norm"].max()
        v_best_global = f"{bg_uni} · {bg_val:.2f}"
        v_best_calc   = f"{bc_uni} · {bc_val:.2f}"
        kpi_best_global = kpi_box("Mejor Universidad (Global)", v_best_global, ACCENT2)
        kpi_best_calc   = kpi_box("Mejor Universidad (Global Calculado)", v_best_calc, ACCENT4)

        rank_g = agg_all["punt_global_norm"].sort_values(ascending=False).head(20)
        rank_c = agg_all["punt_global_calc_norm"].sort_values(ascending=False).head(20)
        rank_global_data = [{"Posición": i + 1, "Universidad": u, "Puntaje": round(float(v), 2)}
                            for i, (u, v) in enumerate(rank_g.items())]
        rank_calc_data = [{"Posición": i + 1, "Universidad": u, "Puntaje": round(float(v), 2)}
                          for i, (u, v) in enumerate(rank_c.items())]
    else:
        v_best_global = v_best_calc = "—"
        kpi_best_global = kpi_box("Mejor Universidad (Global)", "—")
        kpi_best_calc   = kpi_box("Mejor Universidad (Global Calculado)", "—")
        rank_global_data, rank_calc_data = [], []

    v_count = str(len(selected))
    kpi_count = kpi_box("Universidades Comparadas", v_count, ACCENT1)

    # Filtros activos (legibles) y items base disponibles para el reporte.
    rep_filters = {
        "Departamento": depto or "Todos",
        "Grupo de referencia": grupo or "Todos",
        "Programa": prgm or "Todos",
        "Universidades seleccionadas": list(selected),
    }

    def _rank_table(label, data):
        return RE.table(label, ["Posición", "Universidad", "Puntaje"],
                        [[r["Posición"], r["Universidad"], r["Puntaje"]] for r in data])

    def _base_items():
        items = {
            "kpi_best_global": RE.kpi("Mejor Universidad (Global)", v_best_global),
            "kpi_best_calc":   RE.kpi("Mejor Universidad (Global Calculado)", v_best_calc),
            "kpi_count":       RE.kpi("Universidades Comparadas", v_count),
        }
        if rank_global_data:
            items["table_rank_global"] = _rank_table("Ranking de Universidades (Global)", rank_global_data)
        if rank_calc_data:
            items["table_rank_calc"] = _rank_table("Ranking de Universidades (Global Calculado)", rank_calc_data)
        return items

    if len(selected) < MIN_UNIV:
        msg = empty_fig(f"Selecciona entre {MIN_UNIV} y {MAX_UNIV} universidades para comparar")
        radar_children = _radar_placeholder(
            f"Selecciona entre {MIN_UNIV} y {MAX_UNIV} universidades para comparar")
        kpi_diff = kpi_box("Diferencia Máxima", "—", ACCENT3)
        rep_payload = RE.publish_payload("interuniv", rep_filters, _base_items())
        return (msg, radar_children, [], [{"name": "Universidad", "id": "Universidad"}], ZEBRA,
                rank_global_data, rank_calc_data,
                kpi_best_global, kpi_best_calc, kpi_diff, kpi_count, rep_payload)

    dsel = d[d["inst_nombre_institucion"].isin(selected)]
    mat = (dsel.groupby("inst_nombre_institucion")[COMP_COLS].mean()).reindex(selected)

    if mat.dropna(how="all").empty:
        msg = empty_fig("Sin datos para las universidades/filtros seleccionados")
        radar_children = _radar_placeholder("Sin datos para las universidades/filtros seleccionados")
        kpi_diff = kpi_box("Diferencia Máxima", "—", ACCENT3)
        rep_payload = RE.publish_payload("interuniv", rep_filters, _base_items())
        return (msg, radar_children, [], [{"name": "Universidad", "id": "Universidad"}], ZEBRA,
                rank_global_data, rank_calc_data,
                kpi_best_global, kpi_best_calc, kpi_diff, kpi_count, rep_payload)

    global_vals = mat["punt_global_norm"].dropna()
    if len(global_vals):
        diff_val = float(global_vals.max() - global_vals.min())
        v_diff = f"{diff_val:.2f}"
        kpi_diff = kpi_box("Diferencia Máxima", v_diff, ACCENT3)
    else:
        v_diff = "—"
        kpi_diff = kpi_box("Diferencia Máxima", "—", ACCENT3)

    # ── Sección 1: gráfico de barras agrupadas ──
    fig_bar = go.Figure()
    universidades = mat.index.tolist()
    for i, (c, label) in enumerate(COMPETENCIAS):
        fig_bar.add_trace(go.Bar(
            name=label, x=universidades, y=mat[c].round(2).tolist(),
            marker=dict(color=PALETTE[i % len(PALETTE)]),
            hovertemplate="%{x}<br>" + label + ": %{y:.2f}<extra></extra>",
        ))
    fig_bar.update_layout(**LAYOUT_BASE, barmode="group",
        xaxis=dict(gridcolor="rgba(0,0,0,0)", tickangle=-10),
        yaxis=dict(title="Puntaje promedio normalizado (0-1)", gridcolor=BORDER, zerolinecolor=BORDER),
        legend=dict(font=dict(size=10, color=TEXT_MUTED), bgcolor="rgba(0,0,0,0)",
                   orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))

    # ── Sección 2: un radar independiente por cada pareja de universidades ──
    # Se generan todas las combinaciones de 2 universidades (C(n,2)).  Todos los
    # radares se construyen con EXACTAMENTE el mismo layout (misma escala 0-1,
    # misma altura, mismas fuentes/etiquetas/leyenda) y se disponen en una
    # grilla CSS de columnas fijas: a diferencia de un flex con flex:1 —que
    # estira las celdas de una fila incompleta— cada celda de la grilla mide lo
    # mismo aunque la última fila quede a medias, garantizando radares idénticos
    # sin importar cuántos haya.
    radar_cards = []
    radar_pair_figs, radar_pair_caps = [], []
    for uniA, uniB in itertools.combinations(universidades, 2):
        fig_pair = go.Figure()
        for i, uni in enumerate((uniA, uniB)):
            vals = mat.loc[uni, COMP_COLS].tolist()
            fig_pair.add_trace(go.Scatterpolar(
                r=vals + vals[:1], theta=COMP_LABELS + COMP_LABELS[:1],
                fill="toself", name=str(uni),
                line=dict(color=PALETTE[i % len(PALETTE)])))
        fig_pair.update_layout(**LAYOUT_BASE,
            polar=dict(bgcolor="rgba(0,0,0,0)",
                       radialaxis=dict(visible=True, range=[0, 1],
                                       gridcolor=BORDER, color=TEXT_MUTED,
                                       tickfont=dict(size=10)),
                       angularaxis=dict(color=TEXT_MUTED, gridcolor=BORDER,
                                        tickfont=dict(size=11))),
            showlegend=True,
            legend=dict(font=dict(size=11, color=TEXT_MUTED), bgcolor="rgba(0,0,0,0)",
                        orientation="h", yanchor="bottom", y=-0.18,
                        xanchor="center", x=0.5))
        radar_pair_figs.append(fig_pair)
        radar_pair_caps.append(f"{uniA}  vs  {uniB}")
        radar_cards.append(card([
            html.Div(f"{uniA}  vs  {uniB}", style={
                "color": ACCENT1, "fontFamily": "'IBM Plex Mono', monospace",
                "fontSize": "13px", "fontWeight": "700", "textAlign": "center",
                "marginBottom": "10px"}),
            dcc.Graph(figure=fig_pair, config={"displayModeBar": False},
                      style={"height": "480px"}),
        ], extra_style={"marginBottom": "0"}))

    # 2 columnas para usar el ancho disponible manteniendo radares grandes;
    # 1 sola columna cuando hay un único radar (2 universidades).
    n_cols = 1 if len(radar_cards) <= 1 else 2
    radar_children = html.Div(radar_cards, style={
        "display": "grid",
        "gridTemplateColumns": f"repeat({n_cols}, minmax(0, 1fr))",
        "gap": "16px"})

    # ── Sección 3: tabla comparativa ejecutiva ──
    rename = dict(zip(COMP_COLS, COMP_LABELS))
    df_table = (mat.reset_index()
                .rename(columns={"inst_nombre_institucion": "Universidad", **rename}))
    df_table = df_table[["Universidad", *COMP_LABELS]]
    for c in COMP_LABELS:
        df_table[c] = df_table[c].round(2)

    columns_def = [{"name": "Universidad", "id": "Universidad"}] + [
        {"name": c, "id": c, "type": "numeric",
         "format": Format(precision=2, scheme=Scheme.fixed)} for c in COMP_LABELS]

    style_cond = list(ZEBRA)
    for c in COMP_LABELS:
        vals_c = df_table[c].dropna()
        if not len(vals_c):
            continue
        col_max, col_min = float(vals_c.max()), float(vals_c.min())
        style_cond.append({"if": {"filter_query": f"{{{c}}} = {col_max}", "column_id": c},
                           "backgroundColor": "rgba(63,185,80,0.25)",
                           "color": ACCENT2, "fontWeight": "700"})
        if col_max != col_min:
            style_cond.append({"if": {"filter_query": f"{{{c}}} = {col_min}", "column_id": c},
                               "backgroundColor": "rgba(247,129,102,0.25)",
                               "color": ACCENT3, "fontWeight": "700"})

    table_data = df_table.to_dict("records")

    # ── Payload completo para el Generador de Reportes ──
    rep_items = _base_items()
    rep_items["kpi_diff"] = RE.kpi("Diferencia Máxima", v_diff)
    rep_items["fig_bar"] = RE.figure("Gráfico de Barras por Competencia", fig_bar)
    if radar_pair_figs:
        rep_items["fig_radar"] = RE.figure_multi(
            "Radares Comparativos por Pareja", radar_pair_figs, radar_pair_caps)
    exec_cols = ["Universidad", *COMP_LABELS]
    rep_items["table_exec"] = RE.table(
        "Tabla Comparativa Ejecutiva", exec_cols,
        [[row.get(c) for c in exec_cols] for row in table_data])
    rep_payload = RE.publish_payload("interuniv", rep_filters, rep_items)

    return (fig_bar, radar_children, table_data, columns_def, style_cond,
            rank_global_data, rank_calc_data,
            kpi_best_global, kpi_best_calc, kpi_diff, kpi_count, rep_payload)


if __name__ == "__main__":
    load_or_build(force="--rebuild" in sys.argv)
