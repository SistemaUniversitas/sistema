"""
Dashboard ICFES Saber Pro – Socioeconómico unificado 2014–2023
===============================================================
Vista socioeconómica unificada con todos los años (2014→2023)
cargados desde PostgreSQL (tablas saberpro_YYYY). Filtros
interactivos: año, periodo, género, estrato, departamento y
municipio (residencia).

Cache en disco:
  - Primera ejecución: une todas las tablas anuales vía JDBC y persiste
    el DataFrame consolidado en Cache/SaberPro_Socioeconomico_cache.parquet
  - Ejecuciones siguientes: levanta el cache sin arrancar Spark
  - Forzar re-lectura:   python Pages/Saber_Pro_Socioeconomico.py --rebuild
"""

import sys
import pickle
import time
import unicodedata
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import html, dcc, dash_table, Input, Output, State, callback
import dash

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# REGISTRO DE PÁGINA
# ─────────────────────────────────────────────────────────────
dash.register_page(__name__, path="/saberpro-socioeconomico",
                   name="Saber Pro · Socioeconómico unificado")

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN POSTGRES + JDBC
# ─────────────────────────────────────────────────────────────
PG_HOST     = "localhost"
PG_PORT     = 5432
PG_DATABASE = "TrabajoGrado"
PG_USER     = "postgres"
PG_PASSWORD = "postgres"
PG_SCHEMA   = "public"

YEARS = list(range(2014, 2024))  # 2014..2023

DASHBOARD_DIR    = Path(__file__).resolve().parents[1]
JDBC_DRIVER_PATH = DASHBOARD_DIR / "JDBC_Driver" / "postgresql-42.7.10.jar"
if not JDBC_DRIVER_PATH.exists():
    JDBC_DRIVER_PATH = DASHBOARD_DIR.parent / "JDBC_Driver" / "postgresql-42.7.10.jar"

JDBC_NUM_PARTITIONS = 4

CACHE_DIR  = DASHBOARD_DIR / "Cache"
CACHE_FILE = CACHE_DIR / "SaberPro_Socioeconomico_cache.parquet"

# Columnas objetivo (snake_case, como las deja el ETL)
COLS_READ = [
    "periodo", "estu_genero", "estu_fechanacimiento", "estu_nacionalidad",
    "estu_depto_reside", "estu_mcpio_reside", "estu_areareside",
    "estu_depto_presentacion", "estu_mcpio_presentacion",
    "estu_semestrecursa", "estu_horassemanatrabaja",
    "fami_educacionpadre", "fami_educacionmadre",
    "fami_ocupacionpadre", "fami_ocupacionmadre",
    "fami_estratovivienda", "fami_tieneinternet", "fami_tienecomputador",
    "estu_inse_individual", "estu_nse_individual",
    "inst_nombre_institucion", "inst_caracter_academico", "inst_origen",
    "estu_prgm_academico", "estu_nucleo_pregrado",
    "estu_nivel_prgm_academico", "estu_metodo_prgm",
    "estu_prgm_departamento", "gruporeferencia",
    "estu_pagomatriculabeca", "estu_pagomatriculacredito",
    "estu_pagomatriculapadres", "estu_pagomatriculapropio",
]

PAGO_COLS = {
    "estu_pagomatriculabeca":    "Beca",
    "estu_pagomatriculacredito": "Crédito",
    "estu_pagomatriculapadres":  "Padres",
    "estu_pagomatriculapropio":  "Recursos propios",
}

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
PIE_LAYOUT = dict(
    **LAYOUT_BASE,
    showlegend=True,
    legend=dict(font=dict(size=10, color=TEXT_MUTED),
                bgcolor="rgba(0,0,0,0)", bordercolor=BORDER, borderwidth=1),
)

# ─────────────────────────────────────────────────────────────
# COORDENADAS (para mapas con hilos y bubbles)
# ─────────────────────────────────────────────────────────────
MCPIO_COORDS = {
    "BOGOTÁ": (4.711, -74.0721), "BOGOTA": (4.711, -74.0721),
    "BOGOTÁ D.C.": (4.711, -74.0721), "BOGOTA D.C.": (4.711, -74.0721),
    "MEDELLÍN": (6.2442, -75.5812), "MEDELLIN": (6.2442, -75.5812),
    "CALI": (3.4516, -76.5319), "BARRANQUILLA": (10.9685, -74.7813),
    "CARTAGENA": (10.3910, -75.4794), "BUCARAMANGA": (7.1193, -73.1227),
    "PEREIRA": (4.8133, -75.6961), "MANIZALES": (5.0703, -75.5138),
    "IBAGUÉ": (4.4389, -75.2322), "IBAGUE": (4.4389, -75.2322),
    "CÚCUTA": (7.8939, -72.5078), "CUCUTA": (7.8939, -72.5078),
    "VILLAVICENCIO": (4.1420, -73.6266), "PASTO": (1.2136, -77.2811),
    "ARMENIA": (4.5339, -75.6811), "NEIVA": (2.9273, -75.2820),
    "MONTERÍA": (8.7575, -75.8851), "MONTERIA": (8.7575, -75.8851),
    "SANTA MARTA": (11.2408, -74.1990), "POPAYÁN": (2.4448, -76.6147),
    "POPAYAN": (2.4448, -76.6147), "VALLEDUPAR": (10.4631, -73.2532),
    "SINCELEJO": (9.3047, -75.3978), "FLORENCIA": (1.6144, -75.6062),
    "TUNJA": (5.5353, -73.3678), "QUIBDÓ": (5.6919, -76.6583),
    "QUIBDO": (5.6919, -76.6583), "RIOHACHA": (11.5444, -72.9072),
    "YOPAL": (5.3378, -72.3956), "LETICIA": (-4.2153, -69.9406),
    "SAN ANDRÉS": (12.5847, -81.7006), "SAN ANDRES": (12.5847, -81.7006),
    "BELLO": (6.3367, -75.5570), "SOACHA": (4.5793, -74.2179),
    "ITAGÜÍ": (6.1845, -75.5990), "ITAGUI": (6.1845, -75.5990),
    "ENVIGADO": (6.1752, -75.5838), "SOLEDAD": (10.9162, -74.7671),
    "BUENAVENTURA": (3.8801, -77.0311), "PALMIRA": (3.5394, -76.3035),
    "FLORIDABLANCA": (7.0649, -73.0893), "GIRARDOT": (4.3033, -74.8027),
    "SOGAMOSO": (5.7193, -72.9267), "DUITAMA": (5.8279, -73.0267),
    "CHÍA": (4.8629, -74.0592), "CHIA": (4.8629, -74.0592),
    "ZIPAQUIRÁ": (5.0231, -74.0059), "ZIPAQUIRA": (5.0231, -74.0059),
    "FUSAGASUGÁ": (4.3433, -74.3648), "FUSAGASUGA": (4.3433, -74.3648),
    "BUGA": (3.9008, -76.2986), "TULÚA": (4.0847, -76.2005),
    "TULUA": (4.0847, -76.2005), "SAHAGÚN": (8.9516, -75.4440),
    "MOCOA": (1.1519, -76.6478), "ARAUCA": (7.0847, -70.7591),
    "PUERTO CARREÑO": (6.1891, -67.4856), "INIRIDA": (3.8653, -67.9239),
    "SAN JOSÉ DEL GUAVIARE": (2.5709, -72.6417),
    "MITÚ": (1.2478, -70.2344), "MITU": (1.2478, -70.2344),
}

DEPT_COORDS = {
    "AMAZONAS": (-1.0, -71.5), "ANTIOQUIA": (6.85, -75.7),
    "ARAUCA": (6.55, -71.0), "ATLÁNTICO": (10.7, -74.9),
    "ATLANTICO": (10.7, -74.9), "BOGOTÁ": (4.65, -74.1),
    "BOGOTA": (4.65, -74.1), "BOGOTÁ D.C.": (4.65, -74.1),
    "BOGOTA D.C.": (4.65, -74.1), "BOLÍVAR": (8.7, -74.5),
    "BOLIVAR": (8.7, -74.5), "BOYACÁ": (5.55, -72.95),
    "BOYACA": (5.55, -72.95), "CALDAS": (5.3, -75.3),
    "CAQUETÁ": (0.85, -73.9), "CAQUETA": (0.85, -73.9),
    "CASANARE": (5.35, -71.7), "CAUCA": (2.45, -76.8),
    "CESAR": (9.3, -73.65), "CHOCÓ": (5.7, -76.65),
    "CHOCO": (5.7, -76.65), "CÓRDOBA": (8.35, -75.85),
    "CORDOBA": (8.35, -75.85), "CUNDINAMARCA": (5.05, -74.1),
    "GUAINÍA": (2.55, -68.5), "GUAINIA": (2.55, -68.5),
    "GUAVIARE": (2.1, -72.5), "HUILA": (2.55, -75.55),
    "LA GUAJIRA": (11.45, -72.5), "MAGDALENA": (10.35, -74.25),
    "META": (3.45, -73.0), "NARIÑO": (1.55, -77.8),
    "NARINO": (1.55, -77.8), "NORTE DE SANTANDER": (7.9, -72.9),
    "PUTUMAYO": (0.4, -76.5), "QUINDÍO": (4.45, -75.7),
    "QUINDIO": (4.45, -75.7), "RISARALDA": (5.3, -75.95),
    "SAN ANDRÉS Y PROVIDENCIA": (12.55, -81.7),
    "SAN ANDRES Y PROVIDENCIA": (12.55, -81.7),
    "SAN ANDRES": (12.55, -81.7), "SANTANDER": (6.65, -73.1),
    "SUCRE": (9.15, -75.1), "TOLIMA": (4.1, -75.2),
    "VALLE DEL CAUCA": (3.9, -76.45), "VALLE": (3.9, -76.45),
    "VAUPÉS": (0.85, -70.6), "VAUPES": (0.85, -70.6),
    "VICHADA": (4.7, -69.5),
}

def _norm_key(s: str) -> str:
    if s is None: return ""
    s = str(s).upper().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

MCPIO_COORDS_NORM = {_norm_key(k): v for k, v in MCPIO_COORDS.items()}
DEPT_COORDS_NORM  = {_norm_key(k): v for k, v in DEPT_COORDS.items()}

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
        .appName(f"SaberPro_Unificado_Read_{year}")
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
    print("  Construyendo cache unificado Saber Pro (2014–2023)…")
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

    # Tipos
    for p in ["estu_inse_individual", "estu_horassemanatrabaja"]:
        if p in df.columns:
            df[p] = pd.to_numeric(df[p], errors="coerce")
    for c in [*PAGO_COLS.keys(), "fami_tieneinternet", "fami_tienecomputador"]:
        if c in df.columns and df[c].dtype != bool:
            df[c] = df[c].astype(str).str.lower().isin(
                ["true", "t", "1", "si", "s"])

    # Edad
    def to_age(s, ref):
        try:
            n = pd.to_datetime(s, dayfirst=True, errors="coerce")
            if pd.isna(n): return None
            return ref - n.year - ((6, 30) < (n.month, n.day))
        except Exception:
            return None
    df["edad"] = [to_age(s, y) for s, y
                  in zip(df["estu_fechanacimiento"], df["anio"])]

    # Homogenizar tipos: object → string, float64 → float32
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
        print(f"  Cargando cache unificado desde {CACHE_FILE}…", end=" ", flush=True)
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
        return pd.DataFrame(columns=COLS_READ + ["anio", "edad"])

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

def pie_fig(values, labels):
    if not len(values): return empty_fig()
    fig = go.Figure(go.Pie(
        labels=list(labels), values=list(values), hole=0.45,
        marker=dict(colors=PALETTE, line=dict(color=BG, width=2)),
        textfont=dict(size=11),
        hovertemplate="%{label}<br>%{value:,}<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(**PIE_LAYOUT)
    return fig

def bar_h_fig(index, values, color=ACCENT1):
    if not len(values): return empty_fig()
    fig = go.Figure(go.Bar(
        x=list(values), y=[str(l) for l in index], orientation="h",
        marker=dict(color=color),
        hovertemplate="%{y}<br>%{x:,}<extra></extra>",
    ))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor="rgba(0,0,0,0)"))
    return fig

def bar_v_fig(index, values, color=ACCENT2, xlab="", ylab="",
              tickangle=0, bargap=None):
    if not len(values): return empty_fig()
    fig = go.Figure(go.Bar(
        x=[str(l) for l in index], y=list(values),
        marker=dict(color=color),
        hovertemplate="%{x}<br>%{y:,}<extra></extra>",
    ))
    extra = dict(bargap=bargap) if bargap is not None else {}
    fig.update_layout(**LAYOUT_BASE, **extra,
        xaxis=dict(gridcolor="rgba(0,0,0,0)", title=xlab, tickangle=tickangle),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, title=ylab))
    return fig

def hist_fig(series, xlab="Valor", color=ACCENT1, nbins=40):
    s = pd.Series(series).dropna()
    if not len(s): return empty_fig()
    fig = go.Figure(go.Histogram(
        x=s, nbinsx=nbins, marker=dict(color=color, line=dict(color=BG, width=0.5)),
        hovertemplate="%{x}<br>%{y:,}<extra></extra>",
    ))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(title=xlab, gridcolor=BORDER),
        yaxis=dict(title="Frecuencia", gridcolor=BORDER))
    return fig

def hist_inse_fig(series, nbins=40):
    """Histograma del INSE individual con 4 trazas coloreadas por nivel
    socioeconómico y leyenda interactiva horizontal debajo del gráfico."""
    s = pd.Series(series).dropna()
    if not len(s): return empty_fig()

    INSE_RANGES = [
        (0,    41.1,  ACCENT3, "Nivel Socioeconómico Bajo (INSE 0 – 41.1)"),
        (41.1, 51.2,  ACCENT5, "Nivel Socioeconómico Medio-bajo (INSE 41.1 – 51.2)"),
        (51.2, 64.1,  ACCENT1, "Nivel Socioeconómico Medio-alto (INSE 51.2 – 64.1)"),
        (64.1, 100.1, ACCENT2, "Nivel Socioeconómico Alto (INSE 64.1 – 100)"),
    ]

    # Calcular bins uniformes para todo el rango, de modo que las 4 trazas
    # se alineen y formen un histograma continuo de apariencia coherente.
    s_min = max(0.0,   float(s.min()))
    s_max = min(100.0, float(s.max()))
    bin_size = (s_max - s_min) / nbins
    xbins_common = dict(start=s_min, end=s_max + bin_size * 0.001, size=bin_size)

    fig = go.Figure()
    for lo, hi, color, label in INSE_RANGES:
        sub = s[(s >= lo) & (s < hi)]
        fig.add_trace(go.Histogram(
            x=sub,
            xbins=xbins_common,
            autobinx=False,
            name=label,
            marker=dict(color=color, line=dict(color=BG, width=0.5)),
            hovertemplate=f"{label}<br>Frecuencia: %{{y:,}}<extra></extra>",
        ))

    # Excluir 'margin' de LAYOUT_BASE para evitar argumento duplicado
    _base = {k: v for k, v in LAYOUT_BASE.items() if k != "margin"}
    fig.update_layout(
        **_base,
        barmode="stack",
        xaxis=dict(title="INSE", gridcolor=BORDER, range=[s_min - 1, s_max + 1]),
        yaxis=dict(title="Frecuencia", gridcolor=BORDER, zerolinecolor=BORDER),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.22,
            xanchor="center",
            x=0.5,
            font=dict(size=10, color=TEXT_MUTED),
            bgcolor="rgba(0,0,0,0)",
            bordercolor=BORDER,
            borderwidth=1,
            traceorder="normal",
            itemclick="toggle",
            itemdoubleclick="toggleothers",
        ),
        margin=dict(t=40, b=120, l=40, r=40),
    )
    return fig

# ── Choropleth (Colombia) ──

_GEOJSON_CACHE = {"data": None, "tried": False}
def _get_colombia_geojson():
    if _GEOJSON_CACHE["tried"]:
        return _GEOJSON_CACHE["data"]
    _GEOJSON_CACHE["tried"] = True
    try:
        import urllib.request, json
        url = ("https://raw.githubusercontent.com/angelnmara/geojson/master/"
               "colombiaDepartamentos.json")
        with urllib.request.urlopen(url, timeout=15) as r:
            _GEOJSON_CACHE["data"] = json.loads(r.read().decode())
    except Exception as e:
        print(f"  ⚠️  GeoJSON Colombia no disponible: {e}")
    return _GEOJSON_CACHE["data"]

def choropleth_colombia(dept_counts: dict, title=None):
    if not dept_counts: return empty_fig()
    geojson = _get_colombia_geojson()
    df_map = pd.DataFrame(list(dept_counts.items()),
                          columns=["departamento", "conteo"])

    if geojson:
        geo_names = [f["properties"].get("NOMBRE_DPT", "")
                     for f in geojson["features"]]
        geo_norm  = {_norm_key(n): n for n in geo_names}
        df_map["geo_key"]    = df_map["departamento"].apply(_norm_key)
        df_map["nombre_geo"] = df_map["geo_key"].map(geo_norm)
        df_map = df_map.dropna(subset=["nombre_geo"])
        if df_map.empty: return empty_fig()
        fig = px.choropleth(
            df_map, geojson=geojson, locations="nombre_geo",
            featureidkey="properties.NOMBRE_DPT", color="conteo",
            color_continuous_scale=[[0, "#0D1117"], [0.2, ACCENT1], [1, ACCENT4]],
            hover_name="departamento",
            hover_data={"conteo": True, "nombre_geo": False})
        fig.update_geos(fitbounds="locations", visible=False)
    else:
        df_s = df_map.sort_values("conteo").tail(33)
        fig = go.Figure(go.Bar(
            x=df_s["conteo"].tolist(), y=df_s["departamento"].tolist(),
            orientation="h", marker=dict(color=ACCENT1)))

    fig.update_layout(**LAYOUT_BASE,
        coloraxis_colorbar=dict(tickfont=dict(color=TEXT_MUTED),
                                bgcolor="rgba(0,0,0,0)",
                                title=dict(text="Estudiantes",
                                           font=dict(color=TEXT_MUTED, size=10))),
        geo=dict(bgcolor="rgba(0,0,0,0)"))
    return fig

def scatter_mcpio(mcpio_counts: dict):
    if not mcpio_counts: return empty_fig()
    rows = []
    for m, n in mcpio_counts.items():
        c = MCPIO_COORDS_NORM.get(_norm_key(m))
        if c: rows.append({"municipio": m, "conteo": int(n),
                           "lat": c[0], "lon": c[1]})
    if not rows: return empty_fig("No hay municipios con coordenadas")
    df_m = pd.DataFrame(rows)
    fig = px.scatter_geo(df_m, lat="lat", lon="lon",
        size="conteo", color="conteo", hover_name="municipio",
        color_continuous_scale=[[0, ACCENT2], [1, ACCENT1]], size_max=45)
    fig.update_geos(scope="south america",
        center=dict(lat=4.5, lon=-74.0), projection_scale=3.5,
        bgcolor="rgba(0,0,0,0)",
        showland=True,  landcolor="#1C2128",
        showocean=True, oceancolor="#0D1117",
        showcountries=True, countrycolor=BORDER,
        showcoastlines=True, coastlinecolor=BORDER)
    fig.update_layout(**LAYOUT_BASE,
        coloraxis_colorbar=dict(tickfont=dict(color=TEXT_MUTED),
                                bgcolor="rgba(0,0,0,0)",
                                title=dict(text="Estudiantes",
                                           font=dict(color=TEXT_MUTED, size=10))))
    return fig

# ── Heatmap co-ocurrencia de tipos de pago ──

def pago_cooccurrence(df):
    cols = [c for c in PAGO_COLS if c in df.columns]
    if not cols: return empty_fig()
    bools = df[cols].astype(bool).values
    n = len(cols)
    m = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(n):
            m[i, j] = int(np.sum(bools[:, i] & bools[:, j]))
    labels = [PAGO_COLS[c] for c in cols]
    fig = go.Figure(go.Heatmap(
        z=m, x=labels, y=labels,
        colorscale=[[0, "#0D1117"], [0.5, ACCENT1], [1, ACCENT4]],
        hovertemplate="%{y} ∩ %{x}<br>%{z:,} estudiantes<extra></extra>",
        showscale=True,
        colorbar=dict(tickfont=dict(color=TEXT_MUTED),
                      bgcolor="rgba(0,0,0,0)"),
    ))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(tickangle=0), yaxis=dict(autorange="reversed"))
    return fig

# ── Estratos × tipo de pago ──

def estrato_vs_pago(df):
    cols = [c for c in PAGO_COLS if c in df.columns]
    if not cols or "fami_estratovivienda" not in df.columns:
        return empty_fig()
    sub = df[["fami_estratovivienda", *cols]].copy()
    sub["fami_estratovivienda"] = sub["fami_estratovivienda"].astype(str)
    grouped = (sub.groupby("fami_estratovivienda")[cols]
               .apply(lambda g: g.astype(bool).sum())
               .reset_index())
    grouped = grouped.sort_values("fami_estratovivienda")
    if grouped.empty: return empty_fig()

    fig = go.Figure()
    for i, c in enumerate(cols):
        fig.add_trace(go.Bar(
            name=PAGO_COLS[c],
            x=grouped["fami_estratovivienda"].tolist(),
            y=grouped[c].tolist(),
            marker=dict(color=PALETTE[i % len(PALETTE)]),
            hovertemplate=("%{x}<br>" + PAGO_COLS[c] +
                           "<br>%{y:,}<extra></extra>"),
        ))
    fig.update_layout(**LAYOUT_BASE, barmode="stack",
        xaxis=dict(title="Estrato", gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="Estudiantes", gridcolor=BORDER),
        legend=dict(font=dict(size=10, color=TEXT_MUTED),
                    bgcolor="rgba(0,0,0,0)"))
    return fig

# ─────────────────────────────────────────────────────────────
# UI HELPERS
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
        "borderLeft": f"3px solid {ACCENT1}", "paddingLeft": "10px"})

def kpi_box(label, value, color=ACCENT1):
    return html.Div([
        html.Div(label, style={"color": TEXT_MUTED, "fontSize": "10px",
                               "letterSpacing": "1.5px",
                               "textTransform": "uppercase"}),
        html.Div(value, style={"color": color, "fontSize": "22px",
                               "fontWeight": "700", "marginTop": "4px"}),
    ], style={"background": BG, "border": f"1px solid {BORDER}",
              "borderRadius": "8px", "padding": "14px 18px",
              "textAlign": "center", "flex": "1", "minWidth": "100px",
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
    ], style={"flex": "1", "minWidth": "150px"})

# ─────────────────────────────────────────────────────────────
# CARGA INICIAL Y CONSTRUCCIÓN DE OPCIONES
# ─────────────────────────────────────────────────────────────
_DF = load_or_build(force="--rebuild" in sys.argv)

def _opt_list(series, sort=True):
    vals = pd.Series(series).dropna().astype(str).str.strip()
    vals = vals[vals != ""].unique().tolist()
    if sort: vals = sorted(vals)
    return [{"label": v, "value": v} for v in vals]

YEAR_OPTS    = [{"label": str(y), "value": y}
                for y in sorted(_DF["anio"].dropna().unique())]
PERIODO_OPTS = _opt_list(_DF.get("periodo", pd.Series(dtype=str)))
GENERO_OPTS  = _opt_list(_DF.get("estu_genero", pd.Series(dtype=str)))
ESTRATO_OPTS = _opt_list(_DF.get("fami_estratovivienda", pd.Series(dtype=str)))
DEPTO_OPTS   = _opt_list(_DF.get("estu_depto_reside", pd.Series(dtype=str)))

# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────

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
    "style_data_conditional": [
        {"if": {"row_index": "odd"}, "backgroundColor": "#0D1117"},
        {"if": {"column_id": "Conteo"}, "color": ACCENT2,
         "fontWeight": "700", "textAlign": "right"}],
}

def _filter_bar():
    return card([
        section_title("Filtros"),
        row(
            dd("unif-f-year",    "Año",          YEAR_OPTS,    value=None),
            dd("unif-f-periodo", "Periodo",      PERIODO_OPTS, value=None),
            dd("unif-f-genero",  "Género",       GENERO_OPTS,  value=None),
            dd("unif-f-estrato", "Estrato",      ESTRATO_OPTS, value=None),
            dd("unif-f-depto",   "Departamento", DEPTO_OPTS,   value=None),
            dd("unif-f-mcpio",   "Municipio",    [],           value=None),
        ),
        html.Div(id="unif-filter-summary",
                 style={"color": TEXT_MUTED, "fontSize": "11px",
                        "marginTop": "12px",
                        "fontFamily": "'IBM Plex Mono', monospace"}),
    ])

layout = html.Div(style={
    "background": BG, "minHeight": "100vh",
    "fontFamily": "'IBM Plex Mono', monospace",
    "color": TEXT_MAIN, "padding": "24px 32px",
}, children=[

    # Header
    html.Div([
        html.Div([
            html.Div("ICFES · SABER PRO · 2014–2023 · UNIFICADO",
                     style={"color": ACCENT1, "fontSize": "11px",
                            "letterSpacing": "4px"}),
            html.H1("Dashboard interactivo", style={
                "margin": "4px 0 0 0", "fontSize": "28px",
                "fontWeight": "700", "color": TEXT_MAIN}),
            html.Div(f"Fuente: jdbc:postgresql://{PG_HOST}:{PG_PORT}/"
                     f"{PG_DATABASE} · saberpro_2014..2023",
                     style={"color": TEXT_MUTED, "fontSize": "10px",
                            "letterSpacing": "1px", "marginTop": "6px"}),
        ]),
        html.Div([
            html.Div("TOTAL REGISTROS", style={"color": TEXT_MUTED,
                     "fontSize": "10px", "letterSpacing": "2px"}),
            html.Div(id="unif-kpi-total",
                     style={"color": ACCENT2, "fontSize": "36px",
                            "fontWeight": "700"}),
        ], style={"textAlign": "right"}),
    ], style={"display": "flex", "justifyContent": "space-between",
              "alignItems": "flex-end", "marginBottom": "28px",
              "paddingBottom": "20px",
              "borderBottom": f"1px solid {BORDER}"}),

    _filter_bar(),

    # ── 1. Identificación y periodo ──
    card([
        section_title("Identificación y periodo"),
        row(
            html.Div(
                col(card([sublabel("Periodo"),
                          graph("unif-fig-periodo", "260px")])),
                id="unif-container-periodo",
                style={"display": "none", "flex": "1", "minWidth": "280px"},
            ),
            col(card([sublabel("Género"),
                      graph("unif-fig-genero",  "260px")])),
            col(card([sublabel("Nacionalidad (colombianos vs extranjeros)"),
                      graph("unif-fig-nac-resumen", "260px")])),
        ),
        card([sublabel(f"Distribución de edad (calculada al año de la prueba)"),
              graph("unif-fig-edad", "320px")]),
        card([
            sublabel("Nacionalidad de los estudiantes"),
            html.Div([
                html.Div(id="unif-kpi-colombianos",
                         style={"flex": "1", "minWidth": "180px"}),
                html.Div(id="unif-kpi-extranjeros",
                         style={"flex": "1", "minWidth": "180px"}),
            ], style={"display": "flex", "gap": "12px", "marginBottom": "20px"}),
            sublabel("Top 25 nacionalidades extranjeras"),
            graph("unif-fig-extranjeros", "800px"),
        ]),
    ]),

    # ── 2. Ubicación (top 10) ──
    card([
        section_title("Ubicación del estudiante · Top 10"),
        row(
            col([sublabel("Top 10 departamentos de residencia"),
                 graph("unif-fig-top10-depto-reside", "460px")]),
            col([sublabel("Top 10 municipios de residencia"),
                 graph("unif-fig-top10-mcpio-reside", "460px")]),
        ),
        row(
            col([sublabel("Top 10 departamentos de presentación"),
                 graph("unif-fig-top10-depto-present", "460px")]),
            col([sublabel("Top 10 municipios de presentación"),
                 graph("unif-fig-top10-mcpio-present", "460px")]),
        ),
    ]),

    # ── 2.b Ubicación (completa) ──
    card([
        section_title("Ubicación del estudiante · Todos los departamentos y municipios"),
        row(
            col([sublabel("Departamento de residencia"),
                 graph("unif-fig-mapa-depto-reside", "900px")]),
            col([sublabel("Municipio de residencia (top)"),
                 graph("unif-fig-mapa-mcpio-reside", "500px")]),
        ),
        row(
            col([sublabel("Departamento de presentación"),
                 graph("unif-fig-mapa-depto-present", "900px")]),
            col([sublabel("Municipio de presentación (top)"),
                 graph("unif-fig-mapa-mcpio-present", "500px")]),
        ),
        card([sublabel("Área de residencia"),
              graph("unif-fig-area-reside", "280px")]),
    ]),

    # ── 3. Contexto académico ──
    card([
        section_title("Contexto académico del estudiante"),
        row(
            col([sublabel("Semestre cursando"),
                 graph("unif-fig-semestre", "320px")]),
        ),
    ]),

    # ── 4. Contexto familiar ──
    card([
        section_title("Contexto familiar"),
        row(
            col([sublabel("Educación del padre"),
                 graph("unif-fig-edu-padre", "360px")]),
            col([sublabel("Educación de la madre"),
                 graph("unif-fig-edu-madre", "360px")]),
        ),
        row(
            col([sublabel("Ocupación del padre"),
                 graph("unif-fig-ocu-padre", "360px")]),
            col([sublabel("Ocupación de la madre"),
                 graph("unif-fig-ocu-madre", "360px")]),
        ),
        row(
            col([sublabel("Estrato de vivienda"),
                 graph("unif-fig-estrato", "420px")]),
            col([sublabel("Tiene internet"),
                 graph("unif-fig-internet", "300px")]),
            col([sublabel("Tiene computador"),
                 graph("unif-fig-computador", "300px")]),
        ),
    ]),

    # ── 5. Índices socioeconómicos ──
    card([
        section_title("Índices socioeconómicos"),
        row(
            col([sublabel("INSE individual (histograma)"),
                 graph("unif-fig-inse", "430px")]),
            col([sublabel("NSE individual (niveles)"),
                 graph("unif-fig-nse", "320px")]),
        ),
    ]),

    # ── 6. Institución y programa ──
    card([
        section_title("Institución y programa"),
        row(
            col([sublabel("Carácter académico de la IES"),
                 graph("unif-fig-caracter", "320px")]),
            col([sublabel("Tipo de institución (pública / privada / especial)"),
                 graph("unif-fig-origen-tipo", "320px")]),
            col([sublabel("Origen (valores detallados)"),
                 graph("unif-fig-origen", "320px")]),
            col([sublabel("Nivel del programa"),
                 graph("unif-fig-nivel-prgm", "320px")]),
        ),
        row(
            col([sublabel("Método del programa"),
                 graph("unif-fig-metodo", "300px")]),
            col([sublabel("Grupo de referencia (top 20)"),
                 graph("unif-fig-grupo-ref", "650px")]),
        ),
        card([sublabel("Departamento donde se ofrece el programa"),
              graph("unif-fig-mapa-prgm-depto", "900px")]),
        card([sublabel("Top 30 instituciones"),
              graph("unif-fig-top-inst", "560px")]),
        card([sublabel("Top 30 programas académicos"),
              graph("unif-fig-top-prgm", "560px")]),
        card([sublabel("Top 25 núcleos de pregrado"),
              graph("unif-fig-nucleo", "520px")]),
    ]),

    # ── 7. Financiación de matrícula ──
    card([
        section_title("Financiación de matrícula"),
        row(
            col([sublabel("Cantidad de estudiantes por tipo de pago"),
                 graph("unif-fig-pago-totales", "300px")]),
            col([
                html.Div([
                    sublabel("Co-ocurrencia entre tipos de pago"),
                    html.Button(
                        "?",
                        id="unif-btn-ayuda-heatmap",
                        n_clicks=0,
                        title="¿Cómo leer este gráfico?",
                        style={
                            "marginLeft": "8px",
                            "width": "22px", "height": "22px",
                            "borderRadius": "50%",
                            "border": f"1px solid {ACCENT1}",
                            "background": "transparent",
                            "color": ACCENT1,
                            "cursor": "pointer",
                            "fontFamily": "'IBM Plex Mono', monospace",
                            "fontSize": "12px",
                            "lineHeight": "20px",
                            "padding": "0",
                        },
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
                graph("unif-fig-pago-heatmap", "300px"),
            ]),
        ),
        card([sublabel("Estrato × tipo de pago (apilado)"),
              graph("unif-fig-estrato-pago", "360px")]),
    ]),

    # ── Modal de ayuda: heatmap de co-ocurrencia ──
    html.Div(
        id="unif-modal-ayuda-heatmap",
        children=html.Div([
            html.Div([
                html.H3("¿Cómo leer este gráfico?", style={
                    "color": ACCENT1, "margin": "0",
                    "fontFamily": "'IBM Plex Mono', monospace",
                    "fontSize": "14px", "letterSpacing": "2px",
                    "textTransform": "uppercase"}),
                html.Button("×", id="unif-btn-cerrar-ayuda-heatmap",
                            n_clicks=0, style={
                    "background": "transparent", "border": "none",
                    "color": TEXT_MAIN, "fontSize": "22px",
                    "cursor": "pointer", "lineHeight": "1", "padding": "0"}),
            ], style={"display": "flex", "justifyContent": "space-between",
                      "alignItems": "center", "marginBottom": "14px",
                      "borderBottom": f"1px solid {BORDER}",
                      "paddingBottom": "10px"}),

            html.P("Este cuadro muestra cómo se combinan las distintas "
                   "formas de pagar la matrícula entre los estudiantes. "
                   "Cada estudiante puede usar más de una a la vez "
                   "(por ejemplo, beca y aporte de los padres).",
                   style={"color": TEXT_MAIN, "marginBottom": "12px"}),

            html.H4("¿Qué representa cada casilla?", style={
                "color": ACCENT2, "fontSize": "12px",
                "letterSpacing": "1.5px", "textTransform": "uppercase",
                "marginBottom": "8px", "marginTop": "16px"}),
            html.Ul([
                html.Li([html.B("Casillas de la diagonal "),
                         "(donde se cruza una opción consigo misma): "
                         "es el total de estudiantes que usan esa forma "
                         "de pago, ya sea combinandola o no combinandola con otra."]),
                html.Li([html.B("Casillas fuera de la diagonal: "),
                         "cuántos estudiantes usan al mismo tiempo las "
                         "dos formas de pago que se cruzan. Por ejemplo, "
                         "“Beca” con “Crédito” muestra los estudiantes "
                         "que tienen las dos."]),
                html.Li([html.B("Color: "),
                         "cuanto más intenso (azul fuerte o violeta), "
                         "más estudiantes hay en esa combinación. "
                         "Los tonos oscuros indican pocos casos."]),
            ], style={"color": TEXT_MAIN, "paddingLeft": "20px",
                      "marginBottom": "12px", "lineHeight": "1.6"}),

            html.H4("Cosas importantes a tener en cuenta", style={
                "color": ACCENT2, "fontSize": "12px",
                "letterSpacing": "1.5px", "textTransform": "uppercase",
                "marginBottom": "8px", "marginTop": "16px"}),
            html.Ul([
                html.Li("El cuadro es simétrico: la parte de arriba y la "
                        "de abajo de la diagonal dicen lo mismo. Basta "
                        "con mirar la mitad."),                
                html.Li("Que dos formas de pago aparezcan juntas no "
                        "significa que una sea la causa de la otra. "
                        "Solo indica que conviven en los mismos estudiantes."),
                html.Li("Los números cambian según los filtros aplicados "
                        "(año, estrato, departamento, etc.). Al filtrar, "
                        "el cuadro se actualiza con ese grupo."),
            ], style={"color": TEXT_MAIN, "paddingLeft": "20px",
                      "lineHeight": "1.6"}),

            html.Div("Pasa el cursor sobre cualquier casilla para ver "
                    "el número exacto de estudiantes en esa combinación.",
                    style={"color": TEXT_MUTED, "fontSize": "11px",
                           "marginTop": "16px", "fontStyle": "italic"}),
        ], style={
            "background": CARD_BG,
            "border": f"1px solid {BORDER}",
            "borderRadius": "12px",
            "padding": "24px",
            "maxWidth": "640px",
            "width": "90%",
            "maxHeight": "85vh",
            "overflowY": "auto",
            "color": TEXT_MAIN,
            "fontFamily": "'IBM Plex Mono', monospace",
            "fontSize": "12px",
        }),
        style={
            "display": "none",
            "position": "fixed",
            "top": "0", "left": "0",
            "width": "100vw", "height": "100vh",
            "background": "rgba(0, 0, 0, 0.65)",
            "zIndex": "1000",
            "justifyContent": "center",
            "alignItems": "center",
        },
    ),

    # Footer
    html.Div("ICFES Saber Pro · Dashboard unificado 2014–2023",
             style={"textAlign": "center", "color": TEXT_MUTED,
                    "fontSize": "10px", "letterSpacing": "2px",
                    "paddingTop": "20px",
                    "borderTop": f"1px solid {BORDER}"}),
])

# ─────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────

@callback(
    Output("unif-f-mcpio", "options"),
    Output("unif-f-mcpio", "value"),
    Input("unif-f-depto", "value"),
    Input("unif-f-mcpio", "value"),
)
def _update_mcpio_options(depto, mcpio):
    base = _DF
    if depto:
        base = base[base["estu_depto_reside"].astype(str).str.strip() == depto]
    opts = _opt_list(base["estu_mcpio_reside"])
    vals = {o["value"] for o in opts}
    return opts, (mcpio if mcpio in vals else None)


@callback(
    Output("unif-container-periodo", "style"),
    Input("unif-f-year", "value"),
)
def _toggle_periodo(anio):
    base = {"flex": "1", "minWidth": "280px"}
    if anio is None:
        return {**base, "display": "none"}
    return {**base, "display": "block"}


@callback(
    Output("unif-modal-ayuda-heatmap", "style"),
    Input("unif-btn-ayuda-heatmap", "n_clicks"),
    Input("unif-btn-cerrar-ayuda-heatmap", "n_clicks"),
)
def _toggle_ayuda_heatmap(n_open, n_close):
    base = {
        "position": "fixed", "top": "0", "left": "0",
        "width": "100vw", "height": "100vh",
        "background": "rgba(0, 0, 0, 0.65)",
        "zIndex": "1000",
        "justifyContent": "center", "alignItems": "center",
    }
    ctx = dash.callback_context
    if not ctx.triggered:
        return {**base, "display": "none"}
    trig = ctx.triggered[0]["prop_id"].split(".")[0]
    if trig == "unif-btn-ayuda-heatmap":
        return {**base, "display": "flex"}
    return {**base, "display": "none"}


def _apply_filters(df, anio, periodo, genero, estrato, depto, mcpio):
    d = df
    if anio is not None:
        d = d[d["anio"] == anio]
    if periodo:
        d = d[d["periodo"].astype(str) == str(periodo)]
    if genero:
        d = d[d["estu_genero"].astype(str) == str(genero)]
    if estrato:
        d = d[d["fami_estratovivienda"].astype(str) == str(estrato)]
    if depto:
        d = d[d["estu_depto_reside"].astype(str).str.strip() == depto]
    if mcpio:
        d = d[d["estu_mcpio_reside"].astype(str).str.strip() == mcpio]
    return d


# Lista de todos los outputs en el orden en que se regresan en update_all
_FIG_OUTPUTS = [
    # identificación
    "unif-fig-periodo", "unif-fig-genero", "unif-fig-nac-resumen",
    "unif-fig-edad", "unif-fig-extranjeros",
    # ubicación top 10
    "unif-fig-top10-depto-reside", "unif-fig-top10-mcpio-reside",
    "unif-fig-top10-depto-present", "unif-fig-top10-mcpio-present",
    # ubicación completa
    "unif-fig-mapa-depto-reside", "unif-fig-mapa-mcpio-reside",
    "unif-fig-mapa-depto-present", "unif-fig-mapa-mcpio-present",
    "unif-fig-area-reside",
    # académico
    "unif-fig-semestre",
    # familiar
    "unif-fig-edu-padre", "unif-fig-edu-madre",
    "unif-fig-ocu-padre", "unif-fig-ocu-madre",
    "unif-fig-estrato", "unif-fig-internet", "unif-fig-computador",
    # socioeconómico
    "unif-fig-inse", "unif-fig-nse",
    # institución
    "unif-fig-caracter", "unif-fig-origen-tipo", "unif-fig-origen", "unif-fig-nivel-prgm",
    "unif-fig-metodo", "unif-fig-grupo-ref",
    "unif-fig-mapa-prgm-depto",
    "unif-fig-top-inst", "unif-fig-top-prgm", "unif-fig-nucleo",
    # pago
    "unif-fig-pago-totales", "unif-fig-pago-heatmap", "unif-fig-estrato-pago",
]


@callback(
    *[Output(fid, "figure") for fid in _FIG_OUTPUTS],
    Output("unif-kpi-total", "children"),
    Output("unif-filter-summary", "children"),
    Output("unif-kpi-colombianos", "children"),
    Output("unif-kpi-extranjeros", "children"),
    Input("unif-f-year",    "value"),
    Input("unif-f-periodo", "value"),
    Input("unif-f-genero",  "value"),
    Input("unif-f-estrato", "value"),
    Input("unif-f-depto",   "value"),
    Input("unif-f-mcpio",   "value"),
)
def update_all(anio, periodo, genero, estrato, depto, mcpio):
    d = _apply_filters(_DF, anio, periodo, genero, estrato, depto, mcpio)
    total = len(d)

    # Resumen de filtros activos
    activos = []
    if anio is not None: activos.append(f"año={anio}")
    if periodo:          activos.append(f"periodo={periodo}")
    if genero:           activos.append(f"género={genero}")
    if estrato:          activos.append(f"estrato={estrato}")
    if depto:            activos.append(f"depto={depto}")
    if mcpio:            activos.append(f"mcpio={mcpio}")
    resumen = ("Filtros: " + " · ".join(activos)) if activos \
              else "Sin filtros activos · mostrando todo 2014–2023"

    if total == 0:
        empty = empty_fig()
        empties = [empty] * len(_FIG_OUTPUTS)
        return (*empties, "0", resumen + " · sin registros", None, None)

    def vc(col, top=None, sort_index=False):
        if col not in d.columns: return pd.Series(dtype=int)
        s = d[col].dropna().astype(str).str.strip()
        s = s[s != ""]
        v = s.value_counts()
        if sort_index: v = v.sort_index()
        if top is not None: v = v.head(top)
        return v

    # ── identificación ──
    periodo_vc = vc("periodo", sort_index=True)
    genero_vc  = vc("estu_genero")
    nac_raw    = (d["estu_nacionalidad"].fillna("COLOMBIA")
                  .astype(str).str.upper().str.strip())
    col_count  = int((nac_raw == "COLOMBIA").sum())
    ext_count  = int((nac_raw != "COLOMBIA").sum())
    ext_vc     = (nac_raw[nac_raw != "COLOMBIA"]
                  .value_counts().head(25).sort_values())
    edad_vc    = (pd.Series(d["edad"]).dropna().astype(int)
                  .pipe(lambda s: s[(s >= 15) & (s <= 60)])
                  .value_counts().sort_index())

    fig_periodo = pie_fig(periodo_vc.values, periodo_vc.index.astype(str))
    fig_genero  = pie_fig(genero_vc.values,
                          [{"M": "Masculino", "F": "Femenino"}.get(x, str(x))
                           for x in genero_vc.index])
    fig_nac     = pie_fig([col_count, ext_count], ["Colombianos", "Extranjeros"])
    fig_edad    = bar_v_fig(edad_vc.index, edad_vc.values,
                            color=ACCENT4, xlab="Edad", ylab="Cantidad")
    fig_ext     = bar_h_fig(ext_vc.index, ext_vc.values, color=ACCENT5)

    # ── ubicación ──
    depto_r_vc  = vc("estu_depto_reside")
    mcpio_r_vc  = vc("estu_mcpio_reside", top=60)
    depto_p_vc  = vc("estu_depto_presentacion")
    mcpio_p_vc  = vc("estu_mcpio_presentacion", top=60)
    area_vc     = vc("estu_areareside")

    def _top10_bar(value_counts):
        top = value_counts.head(10).sort_values(ascending=True)
        return bar_h_fig(top.index, top.values, color=ACCENT1)

    fig_top10_depto_r = _top10_bar(depto_r_vc)
    fig_top10_mcpio_r = _top10_bar(mcpio_r_vc)
    fig_top10_depto_p = _top10_bar(depto_p_vc)
    fig_top10_mcpio_p = _top10_bar(mcpio_p_vc)

    fig_mapa_depto_r = choropleth_colombia(
        {str(k): int(v) for k, v in depto_r_vc.items()})
    fig_mapa_mcpio_r = scatter_mcpio(
        {str(k): int(v) for k, v in mcpio_r_vc.items()})
    fig_mapa_depto_p = choropleth_colombia(
        {str(k): int(v) for k, v in depto_p_vc.items()})
    fig_mapa_mcpio_p = scatter_mcpio(
        {str(k): int(v) for k, v in mcpio_p_vc.items()})
    fig_area         = pie_fig(area_vc.values, area_vc.index.astype(str))

    # ── académico ──
    sem_vc = vc("estu_semestrecursa", sort_index=True)
    fig_sem = bar_v_fig(sem_vc.index, sem_vc.values,
                        color=ACCENT1, xlab="Semestre", ylab="Cantidad")

    # ── familiar ──
    edu_p_vc = vc("fami_educacionpadre").sort_values(ascending=True)
    edu_m_vc = vc("fami_educacionmadre").sort_values(ascending=True)
    ocu_p_vc = vc("fami_ocupacionpadre").sort_values(ascending=True).tail(20)
    ocu_m_vc = vc("fami_ocupacionmadre").sort_values(ascending=True).tail(20)
    est_vc   = vc("fami_estratovivienda", sort_index=True)
    int_vc   = vc("fami_tieneinternet")
    com_vc   = vc("fami_tienecomputador")

    fig_edu_p = bar_h_fig(edu_p_vc.index, edu_p_vc.values, color=ACCENT2)
    fig_edu_m = bar_h_fig(edu_m_vc.index, edu_m_vc.values, color=ACCENT4)
    fig_ocu_p = bar_h_fig(ocu_p_vc.index, ocu_p_vc.values, color=ACCENT1)
    fig_ocu_m = bar_h_fig(ocu_m_vc.index, ocu_m_vc.values, color=ACCENT3)
    fig_est   = bar_v_fig(est_vc.index, est_vc.values,
                          color=ACCENT2, xlab="Estrato", ylab="Cantidad",
                          bargap=0.08, tickangle=-45)
    fig_est.update_layout(margin=dict(t=40, b=110, l=40, r=40))
    fig_int   = pie_fig(int_vc.values,
                        [{"True": "Sí", "False": "No"}.get(str(x), str(x))
                         for x in int_vc.index])
    fig_com   = pie_fig(com_vc.values,
                        [{"True": "Sí", "False": "No"}.get(str(x), str(x))
                         for x in com_vc.index])

    # ── socioeconómico ──
    fig_inse = hist_inse_fig(d.get("estu_inse_individual"), nbins=40)
    nse_vc   = vc("estu_nse_individual", sort_index=True)
    NSE_LABELS = {
        "1": "1 — Nivel socioeconómico bajo",
        "2": "2 — Nivel socioeconómico medio-bajo",
        "3": "3 — Nivel socioeconómico medio-alto",
        "4": "4 — Nivel socioeconómico alto",
    }
    NSE_COLORS = {
        "1": ACCENT3, "2": ACCENT5, "3": ACCENT1, "4": ACCENT2,
    }
    def _nse_key(raw):
        s = str(raw).strip()
        try:
            return str(int(float(s)))
        except (ValueError, TypeError):
            return s
    if len(nse_vc):
        fig_nse = go.Figure()
        agg = {}
        for k, v in nse_vc.items():
            agg[_nse_key(k)] = agg.get(_nse_key(k), 0) + int(v)
        for key in sorted(agg.keys()):
            v = agg[key]
            label = NSE_LABELS.get(key, f"{key} — Sin descripción")
            color = NSE_COLORS.get(key, ACCENT1)
            fig_nse.add_trace(go.Bar(
                x=[key], y=[int(v)], name=label,
                marker=dict(color=color),
                hovertemplate=f"{label}<br>%{{y:,}}<extra></extra>",
            ))
        fig_nse.update_layout(**LAYOUT_BASE, showlegend=True,
            legend=dict(font=dict(size=10, color=TEXT_MUTED),
                        bgcolor="rgba(0,0,0,0)",
                        bordercolor=BORDER, borderwidth=1),
            xaxis=dict(title="Nivel NSE", gridcolor="rgba(0,0,0,0)"),
            yaxis=dict(title="Cantidad", gridcolor=BORDER,
                       zerolinecolor=BORDER))
    else:
        fig_nse = empty_fig()

    # ── institución ──
    car_vc     = vc("inst_caracter_academico")
    org_vc     = vc("inst_origen")
    nivel_vc   = vc("estu_nivel_prgm_academico")
    metodo_vc  = vc("estu_metodo_prgm")
    grupo_vc   = vc("gruporeferencia", top=20).sort_values(ascending=True)
    depto_pr_vc= vc("estu_prgm_departamento")

    _PRIVADAS = {"NO OFICIAL - FUNDACIÓN", "NO OFICIAL - CORPORACIÓN",
                 "NO OFICIAL - FUNDACION", "NO OFICIAL - CORPORACION"}
    _PUBLICAS = {"OFICIAL DEPARTAMENTAL", "OFICIAL MUNICIPAL", "OFICIAL NACIONAL"}
    _ESPECIAL = {"REGIMEN ESPECIAL"}
    if "inst_origen" in d.columns:
        _orig = d["inst_origen"].astype(str).str.upper().str.strip()
        _tipo = {
            "Pública":          int(_orig.isin(_PUBLICAS).sum()),
            "Privada":          int(_orig.isin(_PRIVADAS).sum()),
            "Régimen especial": int(_orig.isin(_ESPECIAL).sum()),
        }
        _tipo = {k: v for k, v in _tipo.items() if v > 0}
    else:
        _tipo = {}
    fig_org_tipo = pie_fig(list(_tipo.values()), list(_tipo.keys())) \
                   if _tipo else empty_fig()

    car_sorted = car_vc.sort_values(ascending=False)
    org_sorted = org_vc.sort_values(ascending=False)
    fig_car   = bar_v_fig(car_sorted.index, car_sorted.values,
                          color=ACCENT2, xlab="Carácter académico",
                          ylab="Cantidad", bargap=0.08, tickangle=-45)
    fig_car.update_layout(margin=dict(t=40, b=110, l=40, r=40))
    fig_org   = bar_v_fig(org_sorted.index, org_sorted.values,
                          color=ACCENT3, xlab="Origen",
                          ylab="Cantidad", bargap=0.08, tickangle=-45)
    fig_org.update_layout(margin=dict(t=40, b=110, l=40, r=40))
    fig_nivel = pie_fig(nivel_vc.values, nivel_vc.index.astype(str))
    fig_metodo= pie_fig(metodo_vc.values, metodo_vc.index.astype(str))
    fig_grupo = bar_h_fig(grupo_vc.index, grupo_vc.values, color=ACCENT5)
    fig_mapa_pr = choropleth_colombia(
        {str(k): int(v) for k, v in depto_pr_vc.items()})

    inst_vc   = vc("inst_nombre_institucion", top=30).sort_values(ascending=True)
    prgm_vc   = vc("estu_prgm_academico", top=30).sort_values(ascending=True)
    nucleo_vc = vc("estu_nucleo_pregrado", top=25).sort_values(ascending=True)
    fig_inst   = bar_h_fig(inst_vc.index, inst_vc.values, color=ACCENT1)
    fig_prgm   = bar_h_fig(prgm_vc.index, prgm_vc.values, color=ACCENT2)
    fig_nucleo = bar_h_fig(nucleo_vc.index, nucleo_vc.values, color=ACCENT4)

    # ── pago ──
    pago_counts = {}
    for c, lbl in PAGO_COLS.items():
        if c in d.columns:
            pago_counts[lbl] = int(d[c].astype(bool).sum())
    pago_s = pd.Series(pago_counts).sort_values(ascending=True) \
             if pago_counts else pd.Series(dtype=int)
    fig_pago_tot = bar_h_fig(pago_s.index, pago_s.values, color=ACCENT3)
    fig_pago_hm  = pago_cooccurrence(d)
    fig_est_pago = estrato_vs_pago(d)

    figs = [
        fig_periodo, fig_genero, fig_nac, fig_edad, fig_ext,
        fig_top10_depto_r, fig_top10_mcpio_r,
        fig_top10_depto_p, fig_top10_mcpio_p,
        fig_mapa_depto_r, fig_mapa_mcpio_r, fig_mapa_depto_p,
        fig_mapa_mcpio_p, fig_area,
        fig_sem,
        fig_edu_p, fig_edu_m, fig_ocu_p, fig_ocu_m,
        fig_est, fig_int, fig_com,
        fig_inse, fig_nse,
        fig_car, fig_org_tipo, fig_org, fig_nivel, fig_metodo, fig_grupo,
        fig_mapa_pr, fig_inst, fig_prgm, fig_nucleo,
        fig_pago_tot, fig_pago_hm, fig_est_pago,
    ]
    assert len(figs) == len(_FIG_OUTPUTS), (len(figs), len(_FIG_OUTPUTS))
    kpi_col = kpi_box("Estudiantes colombianos", f"{col_count:,}", ACCENT2)
    kpi_ext = kpi_box("Estudiantes extranjeros",  f"{ext_count:,}", ACCENT3)
    return (*figs, f"{total:,}", resumen + f" · {total:,} registros",
            kpi_col, kpi_ext)