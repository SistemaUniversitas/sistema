"""
Dashboard ICFES Saber Pro – Puntajes unificado 2016–2023
========================================================
Página dedicada a los puntajes por módulo y a los niveles de
desempeño por módulo (2016→2023). Construye y mantiene su propio
cache, independiente del de la vista socioeconómica.

Cache en disco:
  - Primera ejecución: une todas las tablas anuales vía JDBC y persiste
    el DataFrame en Cache/SaberPro_Puntajes_cache.parquet
  - Ejecuciones siguientes: levanta el cache sin arrancar Spark
  - Forzar re-lectura:   python Pages/Saber_Pro_Puntajes.py --rebuild
"""

import sys
import time
import warnings
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, callback
import dash

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# REGISTRO DE PÁGINA
# ─────────────────────────────────────────────────────────────
dash.register_page(__name__, path="/saberpro-puntajes",
                   name="Saber Pro · Puntajes unificado")

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

CACHE_DIR          = DASHBOARD_DIR / "Cache"
CACHE_FILE         = CACHE_DIR / "SaberPro_Puntajes_cache.parquet"
CACHE_FILE_PAREADO = CACHE_DIR / "SaberPro_Puntajes_Pareado_cache.parquet"

# Columnas objetivo: solo lo necesario para esta página.
COLS_READ = [
    "periodo",
    "estu_genero",
    "estu_depto_reside", "estu_mcpio_reside",
    "fami_estratovivienda",
    "inst_nombre_institucion",
    "gruporeferencia",
    "estu_pagomatriculabeca", "estu_pagomatriculacredito",
    "estu_pagomatriculapadres", "estu_pagomatriculapropio",
    "mod_razona_cuantitat_punt", "mod_lectura_critica_punt",
    "mod_competen_ciudada_punt", "mod_ingles_punt", "mod_comuni_escrita_punt",
    "mod_razona_cuantitat_desem", "mod_lectura_critica_desem",
    "mod_competen_ciudada_desem", "mod_ingles_desem", "mod_comuni_escrita_desem",
    "punt_global",
]

PUNTAJES_NUM = [
    "mod_razona_cuantitat_punt", "mod_lectura_critica_punt",
    "mod_competen_ciudada_punt", "mod_ingles_punt", "mod_comuni_escrita_punt",
    "punt_global",
]

# ─── Configuración del pareado SB11 ↔ SB Pro ─────────────────
LLAVES_TABLE = "llaves"
LLAVES_COLS  = ["estu_consecutivo_sbpro", "estu_consecutivo_sb11"]

SB11_YEARS = list(range(2015, 2025))

SB11_COLS_READ = [
    "estu_consecutivo",
    "punt_matematicas",          "punt_matematicas_norm",
    "punt_lectura_critica",      "punt_lectura_critica_norm",
    "punt_sociales_ciudadanas",  "punt_sociales_ciudadanas_norm",
    "punt_ingles",               "punt_ingles_norm",
    "punt_global",               "punt_global_norm",
    "desemp_ingles",
]

SBPRO_PAREADO_COLS = [
    "estu_consecutivo",
    "periodo", "estu_genero", "fami_estratovivienda",
    "estu_depto_reside", "estu_mcpio_reside",
    "inst_nombre_institucion",
    "gruporeferencia",
    "estu_pagomatriculabeca", "estu_pagomatriculacredito",
    "estu_pagomatriculapadres", "estu_pagomatriculapropio",
    "mod_razona_cuantitat_punt", "mod_razona_cuantitat_punt_norm",
    "mod_lectura_critica_punt",  "mod_lectura_critica_punt_norm",
    "mod_competen_ciudada_punt", "mod_competen_ciudada_punt_norm",
    "mod_ingles_punt",           "mod_ingles_punt_norm",
    "punt_global",               "punt_global_norm",
    "mod_ingles_desem",
]

# Cada par: (col SB Pro normalizada, col SB11 normalizada (renombrada con sufijo _sb11),
#            label corto, label largo)
MODULE_PAIRS = [
    ("mod_razona_cuantitat_punt_norm", "punt_matematicas_norm_sb11",
     "Mate / Razona cuant.", "Matemáticas (SB11) ↔ Razonamiento cuantitativo (SB Pro)"),
    ("mod_lectura_critica_punt_norm",  "punt_lectura_critica_norm_sb11",
     "Lectura crítica",      "Lectura crítica (SB11) ↔ Lectura crítica (SB Pro)"),
    ("mod_competen_ciudada_punt_norm", "punt_sociales_ciudadanas_norm_sb11",
     "Sociales / Ciudadanas","Sociales y ciudadanas (SB11) ↔ Competencias ciudadanas (SB Pro)"),
    ("mod_ingles_punt_norm",           "punt_ingles_norm_sb11",
     "Inglés",               "Inglés (SB11) ↔ Inglés (SB Pro)"),
    ("punt_global_norm",               "punt_global_norm_sb11",
     "Puntaje global",       "Puntaje global (SB11) ↔ Puntaje global (SB Pro)"),
]

# Niveles de desempeño en inglés (en su orden ordinal nativo)
ENG_LEVELS_SB11  = ["A-", "A1", "A2", "B1", "B+"]
ENG_LEVELS_SBPRO = ["-A1", "A1", "A2", "B1", "B2"]

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
    from pyspark.sql import SparkSession

    if not JDBC_DRIVER_PATH.exists():
        raise FileNotFoundError(f"Driver JDBC no encontrado en {JDBC_DRIVER_PATH}")

    spark = (
        SparkSession.builder
        .appName(f"SaberPro_Puntajes_Read_{year}")
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
    print("  Construyendo cache de puntajes Saber Pro (2016–2023)…")
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

    for p in PUNTAJES_NUM:
        if p in df.columns:
            df[p] = pd.to_numeric(df[p], errors="coerce")

    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].where(df[c].isna(), df[c].astype(str))
    for c in df.select_dtypes(include="float64").columns:
        df[c] = df[c].astype("float32")

    CACHE_DIR.mkdir(exist_ok=True)
    df.to_parquet(CACHE_FILE, index=False, compression="snappy")

    print(f"  ✅ Cache puntajes listo en {time.time()-t0:.1f}s → {CACHE_FILE}")
    print("=" * 60)
    _restore_signals()
    return df

def _restore_signals():
    import signal
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
    except Exception:
        pass

def load_or_build(force=False) -> pd.DataFrame:
    if not force and CACHE_FILE.exists():
        print(f"  Cargando cache puntajes desde {CACHE_FILE}…", end=" ", flush=True)
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
        print(f"  ❌ No se pudo construir el cache de puntajes: {e}")
        print("  ⚠️  La página cargará sin datos. Verifica la conexión a Postgres.")
        return pd.DataFrame(columns=COLS_READ + ["anio"])

_DF = load_or_build(force="--rebuild" in sys.argv)

# ─────────────────────────────────────────────────────────────
# CACHE PAREADO SB11 ↔ SB PRO (vía tabla `llaves`)
# ─────────────────────────────────────────────────────────────

def _spark_session(name: str):
    from pyspark.sql import SparkSession
    if not JDBC_DRIVER_PATH.exists():
        raise FileNotFoundError(f"Driver JDBC no encontrado en {JDBC_DRIVER_PATH}")
    spark = (SparkSession.builder
        .appName(name)
        .config("spark.jars", str(JDBC_DRIVER_PATH))
        .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
        .config("spark.driver.memory", "4g")
        .config("spark.executor.memory", "4g")
        .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    return spark

def _read_table_spark(spark, table: str, cols: list):
    """Devuelve un Spark DataFrame con solo las columnas pedidas que existan,
    castadas a STRING. La conversión a numérico se hace en pandas después del
    join — esto evita errores de cast sobre cadenas vacías al hacer union
    entre años con tipos heterogéneos en Postgres."""
    from pyspark.sql.functions import col as scol
    jdbc_url = f"jdbc:postgresql://{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    sdf = (spark.read.format("jdbc")
        .option("url", jdbc_url)
        .option("dbtable", f"{PG_SCHEMA}.{table}")
        .option("user", PG_USER).option("password", PG_PASSWORD)
        .option("driver", "org.postgresql.Driver")
        .option("fetchsize", 10_000)
        .option("numPartitions", JDBC_NUM_PARTITIONS)
        .load())
    avail = set(sdf.columns)
    selected = [c for c in cols if c in avail]
    if not selected:
        return None
    return sdf.select(*[scol(c).cast("string").alias(c) for c in selected])

def build_pareado_cache() -> pd.DataFrame:
    print("=" * 60)
    print("  Construyendo cache pareado SB11 ↔ SB Pro vía `llaves`…")
    print("  (union + join hechos en Spark — solo el resultado final pasa a pandas)")
    print("=" * 60)
    t0 = time.time()

    spark = _spark_session("SaberPro_Puntajes_Pareado")
    try:
        from pyspark.sql.functions import lit

        print("  Leyendo tabla llaves…")
        sdf_llaves = _read_table_spark(spark, LLAVES_TABLE, LLAVES_COLS)
        if sdf_llaves is None:
            raise RuntimeError("Tabla llaves no disponible o sin columnas esperadas.")
        n_llaves = sdf_llaves.count()
        print(f"    {n_llaves:,} llaves")

        # SB11: union de todos los años en Spark
        sb11_sdfs = []
        for y in SB11_YEARS:
            print(f"  [SB11 {y}] referenciando saber11_{y}…")
            try:
                sdf = _read_table_spark(spark, f"saber11_{y}", SB11_COLS_READ)
                if sdf is not None:
                    sb11_sdfs.append(sdf)
            except Exception as e:
                print(f"    ⚠️  saber11_{y}: {e}")
        if not sb11_sdfs:
            raise RuntimeError("No se pudo leer ninguna tabla anual de Saber 11.")
        sdf_sb11 = sb11_sdfs[0]
        for s in sb11_sdfs[1:]:
            sdf_sb11 = sdf_sb11.unionByName(s, allowMissingColumns=True)

        # SB Pro: union de todos los años en Spark, agregando 'anio'
        sbpro_sdfs = []
        for y in YEARS:
            print(f"  [SB Pro {y}] referenciando saberpro_{y}…")
            try:
                sdf = _read_table_spark(spark, f"saberpro_{y}", SBPRO_PAREADO_COLS)
                if sdf is not None:
                    sbpro_sdfs.append(sdf.withColumn("anio", lit(y)))
            except Exception as e:
                print(f"    ⚠️  saberpro_{y}: {e}")
        if not sbpro_sdfs:
            raise RuntimeError("No se pudo leer ninguna tabla anual de Saber Pro.")
        sdf_sbpro = sbpro_sdfs[0]
        for s in sbpro_sdfs[1:]:
            sdf_sbpro = sdf_sbpro.unionByName(s, allowMissingColumns=True)

        # Renombrar columnas SB11 con sufijo `_sb11` (tipos ya son STRING)
        for c in list(sdf_sb11.columns):
            new = "estu_consecutivo_sb11" if c == "estu_consecutivo" else f"{c}_sb11"
            sdf_sb11 = sdf_sb11.withColumnRenamed(c, new)

        # Inner join sbpro ⋈ llaves ⋈ sb11 dentro de Spark
        print("  Joining SB Pro ⋈ llaves ⋈ SB11 en Spark…")
        joined = sdf_sbpro.join(
            sdf_llaves,
            sdf_sbpro["estu_consecutivo"] == sdf_llaves["estu_consecutivo_sbpro"],
            "inner")
        joined = joined.join(sdf_sb11, on="estu_consecutivo_sb11", how="inner")
        joined = joined.drop("estu_consecutivo",
                             "estu_consecutivo_sbpro",
                             "estu_consecutivo_sb11")

        # Solo el resultado final pasa a pandas (~cientos de miles de filas)
        print("  Materializando resultado a pandas…")
        df = joined.toPandas()
        print(f"  Pares finales SB11 ↔ SB Pro: {len(df):,}")
    finally:
        spark.stop()

    # Tipos
    num_cols = [c for c in df.columns if c.endswith("_norm") or c.endswith("_punt")
                or c == "punt_global" or c.startswith("punt_")]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].where(df[c].isna(), df[c].astype(str))
    for c in df.select_dtypes(include="float64").columns:
        df[c] = df[c].astype("float32")

    CACHE_DIR.mkdir(exist_ok=True)
    df.to_parquet(CACHE_FILE_PAREADO, index=False, compression="snappy")
    print(f"  ✅ Cache pareado listo en {time.time()-t0:.1f}s → {CACHE_FILE_PAREADO}")
    print("=" * 60)
    _restore_signals()
    return df

def load_or_build_pareado(force=False) -> pd.DataFrame:
    if not force and CACHE_FILE_PAREADO.exists():
        print(f"  Cargando cache pareado desde {CACHE_FILE_PAREADO}…",
              end=" ", flush=True)
        t0 = time.time()
        try:
            df = pd.read_parquet(CACHE_FILE_PAREADO)
            print(f"OK ({time.time()-t0:.1f}s) · {len(df):,} pares")
            return df
        except Exception as e:
            print(f"ERROR al leer cache pareado: {e} — intentando reconstruir…")
    try:
        return build_pareado_cache()
    except Exception as e:
        print(f"  ❌ No se pudo construir el cache pareado: {e}")
        print("  ⚠️  La sección de relación SB11↔SB Pro cargará vacía.")
        return pd.DataFrame()

_DF_PAREADO = load_or_build_pareado(force="--rebuild" in sys.argv)

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

def bar_v_fig(index, values, color=ACCENT2, xlab="", ylab=""):
    if not len(values): return empty_fig()
    fig = go.Figure(go.Bar(
        x=[str(l) for l in index], y=list(values),
        marker=dict(color=color),
        hovertemplate="%{x}<br>%{y:,}<extra></extra>",
    ))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(gridcolor="rgba(0,0,0,0)", title=xlab),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, title=ylab))
    return fig

# ── Pareado SB11 ↔ SB Pro ──

def _spearman(x, y):
    # Equivalente a Pearson sobre los rangos; evita la dependencia de scipy.
    return float(x.rank().corr(y.rank(), method="pearson"))

def density_scatter_fig(x, y, xlab="SB 11", ylab="SB Pro"):
    x = pd.to_numeric(pd.Series(x), errors="coerce")
    y = pd.to_numeric(pd.Series(y), errors="coerce")
    mask = x.notna() & y.notna()
    x = x[mask]; y = y[mask]
    if len(x) < 2: return empty_fig("Datos insuficientes")
    r   = float(x.corr(y, method="pearson"))
    rho = _spearman(x, y)
    n   = int(len(x))
    fig = go.Figure(go.Histogram2d(
        x=x, y=y, nbinsx=50, nbinsy=50,
        colorscale=[[0, BG], [0.2, ACCENT1], [1, ACCENT4]],
        hovertemplate=(f"{xlab}: %{{x}}<br>{ylab}: %{{y}}"
                       "<br>n=%{z}<extra></extra>"),
        showscale=False,
    ))
    lo = float(min(x.min(), y.min()))
    hi = float(max(x.max(), y.max()))
    fig.add_trace(go.Scatter(
        x=[lo, hi], y=[lo, hi], mode="lines",
        line=dict(color=TEXT_MUTED, dash="dash", width=1),
        hoverinfo="skip", showlegend=False))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(title=xlab, gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(title=ylab, gridcolor=BORDER, zerolinecolor=BORDER),
        annotations=[dict(
            xref="paper", yref="paper", x=0.02, y=0.98, showarrow=False,
            text=f"n={n:,}<br>r={r:.3f}<br>ρ={rho:.3f}",
            font=dict(color=TEXT_MAIN, size=10,
                      family="'IBM Plex Mono', monospace"),
            align="left", bgcolor="rgba(13,17,23,0.75)",
            bordercolor=BORDER, borderwidth=1)])
    return fig

def quintile_matrix_fig(x_sb11, y_sbpro):
    x = pd.to_numeric(pd.Series(x_sb11), errors="coerce")
    y = pd.to_numeric(pd.Series(y_sbpro), errors="coerce")
    mask = x.notna() & y.notna()
    x = x[mask]; y = y[mask]
    if len(x) < 5: return empty_fig("Datos insuficientes")
    try:
        qx = pd.qcut(x, 5, labels=["Q1","Q2","Q3","Q4","Q5"], duplicates="drop")
        qy = pd.qcut(y, 5, labels=["Q1","Q2","Q3","Q4","Q5"], duplicates="drop")
    except Exception:
        return empty_fig("No se pudieron calcular quintiles")
    ct = pd.crosstab(qx, qy, normalize="index") * 100
    fig = go.Figure(go.Heatmap(
        z=ct.values, x=list(ct.columns), y=list(ct.index),
        colorscale=[[0, BG], [0.5, ACCENT1], [1, ACCENT4]],
        text=[[f"{v:.0f}%" for v in row] for row in ct.values],
        texttemplate="%{text}", textfont=dict(size=10, color=TEXT_MAIN),
        hovertemplate=("Quintil SB11=%{y}<br>Quintil SB Pro=%{x}"
                       "<br>%{z:.1f}%<extra></extra>"),
        showscale=False,
    ))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(title="Quintil SB Pro"),
        yaxis=dict(title="Quintil SB 11", autorange="reversed"))
    return fig

def delta_hist_fig(x_sb11, y_sbpro, xlab="Δ (SB Pro − SB 11)"):
    x = pd.to_numeric(pd.Series(x_sb11), errors="coerce")
    y = pd.to_numeric(pd.Series(y_sbpro), errors="coerce")
    mask = x.notna() & y.notna()
    if mask.sum() == 0: return empty_fig()
    delta = (y[mask].values - x[mask].values)
    mean = float(pd.Series(delta).mean())
    fig = go.Figure(go.Histogram(
        x=delta, nbinsx=50,
        marker=dict(color=ACCENT3, line=dict(color=BG, width=0.5)),
        hovertemplate="Δ=%{x}<br>n=%{y:,}<extra></extra>",
    ))
    fig.add_vline(x=0, line=dict(color=TEXT_MUTED, dash="dash", width=1))
    fig.add_vline(x=mean, line=dict(color=ACCENT2, width=1.5))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(title=xlab, gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(title="Frecuencia", gridcolor=BORDER),
        annotations=[dict(
            xref="paper", yref="paper", x=0.98, y=0.98, showarrow=False,
            text=f"μ={mean:+.3f}",
            font=dict(color=ACCENT2, size=10,
                      family="'IBM Plex Mono', monospace"),
            align="right", bgcolor="rgba(13,17,23,0.75)",
            bordercolor=BORDER, borderwidth=1)])
    return fig

def trend_paired_fig(df, sb11_col, sbpro_col,
                     xlab="Año cohorte SB Pro", ylab="Puntaje normalizado"):
    if ("anio" not in df.columns
            or sb11_col not in df.columns or sbpro_col not in df.columns):
        return empty_fig("Columnas faltantes")
    d = df[["anio", sb11_col, sbpro_col]].copy()
    d["anio"]    = pd.to_numeric(d["anio"],    errors="coerce")
    d[sb11_col]  = pd.to_numeric(d[sb11_col],  errors="coerce")
    d[sbpro_col] = pd.to_numeric(d[sbpro_col], errors="coerce")
    d = d.dropna(subset=["anio"])
    if d.empty: return empty_fig()
    g = (d.groupby("anio")
           .agg(sb11=(sb11_col, "mean"), sbpro=(sbpro_col, "mean"))
           .sort_index())
    if g.empty or g.dropna(how="all").empty: return empty_fig()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=g.index, y=g["sb11"], mode="lines+markers", name="SB 11",
        line=dict(color=ACCENT1, width=2), marker=dict(size=6),
        hovertemplate="Año=%{x}<br>SB 11=%{y:.3f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=g.index, y=g["sbpro"], mode="lines+markers", name="SB Pro",
        line=dict(color=ACCENT3, width=2), marker=dict(size=6),
        hovertemplate="Año=%{x}<br>SB Pro=%{y:.3f}<extra></extra>"))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(title=xlab, gridcolor=BORDER, zerolinecolor=BORDER, dtick=1),
        yaxis=dict(title=ylab, gridcolor=BORDER, zerolinecolor=BORDER,
                   nticks=12, tickformat=".2f"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(color=TEXT_MAIN, size=10),
                    bgcolor="rgba(0,0,0,0)"))
    return fig

def english_transition_fig(df):
    if "desemp_ingles_sb11" not in df.columns or "mod_ingles_desem" not in df.columns:
        return empty_fig("Columnas de desempeño en inglés no disponibles")
    s11 = df["desemp_ingles_sb11"].astype(str).str.strip()
    spr = df["mod_ingles_desem"].astype(str).str.strip()
    s11 = s11.where(s11.isin(ENG_LEVELS_SB11))
    spr = spr.where(spr.isin(ENG_LEVELS_SBPRO))
    sub = pd.concat([s11.rename("sb11"), spr.rename("sbpro")], axis=1).dropna()
    if len(sub) == 0: return empty_fig("Sin pares válidos en desempeño en inglés")
    sub["sb11"]  = pd.Categorical(sub["sb11"],  categories=ENG_LEVELS_SB11,  ordered=True)
    sub["sbpro"] = pd.Categorical(sub["sbpro"], categories=ENG_LEVELS_SBPRO, ordered=True)
    ct = pd.crosstab(sub["sb11"], sub["sbpro"], normalize="index") * 100
    ct = ct.reindex(index=ENG_LEVELS_SB11, columns=ENG_LEVELS_SBPRO, fill_value=0)
    fig = go.Figure(go.Heatmap(
        z=ct.values, x=ENG_LEVELS_SBPRO, y=ENG_LEVELS_SB11,
        colorscale=[[0, BG], [0.5, ACCENT1], [1, ACCENT4]],
        text=[[f"{v:.0f}%" for v in row] for row in ct.values],
        texttemplate="%{text}", textfont=dict(size=12, color=TEXT_MAIN),
        hovertemplate=("Nivel SB11=%{y}<br>Nivel SB Pro=%{x}"
                       "<br>%{z:.1f}%<extra></extra>"),
        colorbar=dict(tickfont=dict(color=TEXT_MUTED),
                      bgcolor="rgba(0,0,0,0)"),
    ))
    fig.update_layout(**LAYOUT_BASE,
        xaxis=dict(title="Nivel desempeño SB Pro"),
        yaxis=dict(title="Nivel desempeño SB 11", autorange="reversed"))
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
# OPCIONES DE FILTRO
# ─────────────────────────────────────────────────────────────

def _opt_list(series, sort=True):
    vals = pd.Series(series).dropna().astype(str).str.strip()
    vals = vals[vals != ""].unique().tolist()
    if sort: vals = sorted(vals)
    return [{"label": v, "value": v} for v in vals]

USB_TOKEN = "san buenaventura"

def _is_usb(series: pd.Series) -> pd.Series:
    return series.astype(str).str.contains(USB_TOKEN, case=False, na=False)

def _usb_sede(name: str) -> str:
    s = str(name).strip()
    if not s or USB_TOKEN not in s.lower():
        return ""
    return s.rsplit("-", 1)[1].strip().upper() if "-" in s else "SIN SEDE"

def _usb_sede_opts(df: pd.DataFrame):
    if "inst_nombre_institucion" not in df.columns:
        return []
    s = df.loc[_is_usb(df["inst_nombre_institucion"]), "inst_nombre_institucion"]
    sedes = sorted({_usb_sede(n) for n in s.dropna() if _usb_sede(n)})
    return [{"label": v, "value": v} for v in sedes]

PAGO_COLS = [
    ("Beca",    "estu_pagomatriculabeca"),
    ("Crédito", "estu_pagomatriculacredito"),
    ("Padres",  "estu_pagomatriculapadres"),
    ("Propio",  "estu_pagomatriculapropio"),
]
PAGO_OPTS = [{"label": lab, "value": col} for lab, col in PAGO_COLS]

_TRUTHY = {"1", "1.0", "true", "t", "yes", "y", "si", "sí", "s"}

def _is_truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(_TRUTHY)

YEAR_OPTS    = ([{"label": str(y), "value": int(y)}
                 for y in sorted(_DF["anio"].dropna().unique())]
                if "anio" in _DF.columns else [])
PERIODO_OPTS  = _opt_list(_DF.get("periodo", pd.Series(dtype=str)))
GENERO_OPTS   = _opt_list(_DF.get("estu_genero", pd.Series(dtype=str)))
ESTRATO_OPTS  = _opt_list(_DF.get("fami_estratovivienda", pd.Series(dtype=str)))
DEPTO_OPTS    = _opt_list(_DF.get("estu_depto_reside", pd.Series(dtype=str)))
USB_SEDE_OPTS = _usb_sede_opts(_DF)
GRUPO_OPTS    = _opt_list(_DF.get("gruporeferencia", pd.Series(dtype=str)))

# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────

def _filter_bar():
    return card([
        section_title("Filtros"),
        row(
            dd("punt-f-year",    "Año",          YEAR_OPTS,    value=None),
            dd("punt-f-periodo", "Periodo",      PERIODO_OPTS, value=None),
            dd("punt-f-genero",  "Género",       GENERO_OPTS,  value=None),
            dd("punt-f-estrato", "Estrato",      ESTRATO_OPTS, value=None),
            dd("punt-f-depto",   "Departamento", DEPTO_OPTS,   value=None),
            dd("punt-f-mcpio",   "Municipio",    [],           value=None),
        ),
        row(
            html.Div([
                html.Div("Solo Universidad de San Buenaventura",
                         style={"color": TEXT_MUTED, "fontSize": "10px",
                                "letterSpacing": "1.5px", "marginBottom": "4px",
                                "textTransform": "uppercase"}),
                dcc.Checklist(
                    id="punt-f-usb",
                    options=[{"label": " Activar filtro USB", "value": "on"}],
                    value=[],
                    style={"color": TEXT_MAIN, "fontSize": "12px"},
                    inputStyle={"marginRight": "6px"}),
            ], style={"flex": "1", "minWidth": "240px"}),
            dd("punt-f-sede", "Sede USB", USB_SEDE_OPTS, value=None),
            dd("punt-f-grupo", "Grupo de referencia", GRUPO_OPTS, value=None),
            dd("punt-f-pago",  "Pago de matrícula",   PAGO_OPTS,  value=None),
        ),
        html.Div(id="punt-filter-summary",
                 style={"color": TEXT_MUTED, "fontSize": "11px",
                        "marginTop": "12px",
                        "fontFamily": "'IBM Plex Mono', monospace"}),
    ])

layout = html.Div(style={
    "background": BG, "minHeight": "100vh",
    "fontFamily": "'IBM Plex Mono', monospace",
    "color": TEXT_MAIN, "padding": "24px 32px",
}, children=[

    html.Div([
        html.Div([
            html.Div("ICFES · SABER PRO · PUNTAJES · 2016–2023",
                     style={"color": ACCENT1, "fontSize": "11px",
                            "letterSpacing": "4px"}),
            html.H1("Puntajes y nivel de desempeño por módulo", style={
                "margin": "4px 0 0 0", "fontSize": "28px",
                "fontWeight": "700", "color": TEXT_MAIN}),
            html.Div(f"Fuente: jdbc:postgresql://{PG_HOST}:{PG_PORT}/"
                     f"{PG_DATABASE} · saberpro_2016..2023",
                     style={"color": TEXT_MUTED, "fontSize": "10px",
                            "letterSpacing": "1px", "marginTop": "6px"}),
        ]),
        html.Div([
            html.Div("TOTAL REGISTROS", style={"color": TEXT_MUTED,
                     "fontSize": "10px", "letterSpacing": "2px"}),
            html.Div(id="punt-kpi-total",
                     style={"color": ACCENT2, "fontSize": "36px",
                            "fontWeight": "700"}),
        ], style={"textAlign": "right"}),
    ], style={"display": "flex", "justifyContent": "space-between",
              "alignItems": "flex-end", "marginBottom": "28px",
              "paddingBottom": "20px",
              "borderBottom": f"1px solid {BORDER}"}),

    _filter_bar(),

    card([
        section_title("Puntajes por módulo"),
        row(
            col([sublabel("Razonamiento cuantitativo"),
                 graph("punt-fig-punt-razona", "260px")]),
            col([sublabel("Lectura crítica"),
                 graph("punt-fig-punt-lectura", "260px")]),
            col([sublabel("Competencias ciudadanas"),
                 graph("punt-fig-punt-ciud", "260px")]),
        ),
        row(
            col([sublabel("Inglés"),
                 graph("punt-fig-punt-ingles", "260px")]),
            col([sublabel("Comunicación escrita"),
                 graph("punt-fig-punt-escrita", "260px")]),
            col([sublabel("Puntaje global"),
                 graph("punt-fig-punt-global", "260px")]),
        ),
    ]),

    card([
        section_title("Nivel de desempeño por módulo"),
        row(
            col([sublabel("Razonamiento cuantitativo"),
                 graph("punt-fig-desem-razona", "280px")]),
            col([sublabel("Lectura crítica"),
                 graph("punt-fig-desem-lectura", "280px")]),
            col([sublabel("Competencias ciudadanas"),
                 graph("punt-fig-desem-ciud", "280px")]),
        ),
        row(
            col([sublabel("Inglés"),
                 graph("punt-fig-desem-ingles", "280px")]),
            col([sublabel("Comunicación escrita"),
                 graph("punt-fig-desem-escrita", "280px")]),
        ),
    ]),

    # ── Relación de puntajes SB 11 ↔ SB Pro ──
    card([
        section_title("Relación de puntajes Saber 11 ↔ Saber Pro"),
        html.Div(id="punt-pareado-summary",
                 style={"color": TEXT_MUTED, "fontSize": "11px",
                        "marginBottom": "16px",
                        "fontFamily": "'IBM Plex Mono', monospace"}),

        sublabel("Resumen de correlaciones por módulo (sobre puntajes normalizados)"),
        html.Div(id="punt-pareado-corr-table", style={"marginBottom": "20px"}),

        sublabel("Tendencia por cohorte (media de puntaje normalizado, SB 11 vs SB Pro)"),
        row(
            col([sublabel("Mate / Razona cuant."),
                 graph("punt-fig-pareado-trend-mate", "260px")]),
            col([sublabel("Lectura crítica"),
                 graph("punt-fig-pareado-trend-lect", "260px")]),
            col([sublabel("Sociales / Ciudadanas"),
                 graph("punt-fig-pareado-trend-ciud", "260px")]),
        ),
        row(
            col([sublabel("Inglés"),
                 graph("punt-fig-pareado-trend-ing", "260px")]),
            col([sublabel("Puntaje global"),
                 graph("punt-fig-pareado-trend-glo", "260px")]),
        ),

        sublabel("Distribución del Δ (SB Pro − SB 11) sobre puntaje normalizado"),
        row(
            col([sublabel("Mate / Razona cuant."),
                 graph("punt-fig-pareado-delta-mate", "260px")]),
            col([sublabel("Lectura crítica"),
                 graph("punt-fig-pareado-delta-lect", "260px")]),
            col([sublabel("Sociales / Ciudadanas"),
                 graph("punt-fig-pareado-delta-ciud", "260px")]),
        ),
        row(
            col([sublabel("Inglés"),
                 graph("punt-fig-pareado-delta-ing", "260px")]),
            col([sublabel("Puntaje global"),
                 graph("punt-fig-pareado-delta-glo", "260px")]),
        ),
    ]),

    card([
        section_title("Detalle pareado por módulo"),

        sublabel("Scatter pareado por módulo (densidad, puntaje normalizado)"),
        row(
            col([sublabel("Mate / Razona cuant."),
                 graph("punt-fig-pareado-scatter-mate", "280px")]),
            col([sublabel("Lectura crítica"),
                 graph("punt-fig-pareado-scatter-lect", "280px")]),
            col([sublabel("Sociales / Ciudadanas"),
                 graph("punt-fig-pareado-scatter-ciud", "280px")]),
        ),
        row(
            col([sublabel("Inglés"),
                 graph("punt-fig-pareado-scatter-ing", "280px")]),
            col([sublabel("Puntaje global"),
                 graph("punt-fig-pareado-scatter-glo", "280px")]),
        ),

        sublabel("Matriz de transición por quintiles (% por fila — fila = quintil SB 11)"),
        row(
            col([sublabel("Mate / Razona cuant."),
                 graph("punt-fig-pareado-quint-mate", "280px")]),
            col([sublabel("Lectura crítica"),
                 graph("punt-fig-pareado-quint-lect", "280px")]),
            col([sublabel("Sociales / Ciudadanas"),
                 graph("punt-fig-pareado-quint-ciud", "280px")]),
        ),
        row(
            col([sublabel("Inglés"),
                 graph("punt-fig-pareado-quint-ing", "280px")]),
            col([sublabel("Puntaje global"),
                 graph("punt-fig-pareado-quint-glo", "280px")]),
        ),

        card([sublabel("Transición de nivel de desempeño en inglés "
                       "(SB 11 → SB Pro, % por fila — escalas nativas)"),
              graph("punt-fig-pareado-eng-desem", "420px")]),
    ]),

    html.Div("ICFES Saber Pro · Puntajes 2016–2023",
             style={"textAlign": "center", "color": TEXT_MUTED,
                    "fontSize": "10px", "letterSpacing": "2px",
                    "paddingTop": "20px",
                    "borderTop": f"1px solid {BORDER}"}),
])

# ─────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────

@callback(
    Output("punt-f-mcpio", "options"),
    Output("punt-f-mcpio", "value"),
    Input("punt-f-depto", "value"),
    Input("punt-f-mcpio", "value"),
)
def _update_mcpio_options(depto, mcpio):
    base = _DF
    if depto and "estu_depto_reside" in base.columns:
        base = base[base["estu_depto_reside"].astype(str).str.strip() == depto]
    opts = _opt_list(base.get("estu_mcpio_reside", pd.Series(dtype=str)))
    vals = {o["value"] for o in opts}
    return opts, (mcpio if mcpio in vals else None)


def _apply_filters(df, anio, periodo, genero, estrato, depto, mcpio,
                   usb_only=False, sede=None, grupo=None, pago=None):
    d = df
    if anio is not None and "anio" in d.columns:
        d = d[d["anio"] == anio]
    if periodo and "periodo" in d.columns:
        d = d[d["periodo"].astype(str) == str(periodo)]
    if genero and "estu_genero" in d.columns:
        d = d[d["estu_genero"].astype(str) == str(genero)]
    if estrato and "fami_estratovivienda" in d.columns:
        d = d[d["fami_estratovivienda"].astype(str) == str(estrato)]
    if depto and "estu_depto_reside" in d.columns:
        d = d[d["estu_depto_reside"].astype(str).str.strip() == depto]
    if mcpio and "estu_mcpio_reside" in d.columns:
        d = d[d["estu_mcpio_reside"].astype(str).str.strip() == mcpio]
    if (usb_only or sede) and "inst_nombre_institucion" in d.columns:
        d = d[_is_usb(d["inst_nombre_institucion"])]
        if sede:
            d = d[d["inst_nombre_institucion"].apply(_usb_sede) == sede]
    if grupo and "gruporeferencia" in d.columns:
        d = d[d["gruporeferencia"].astype(str).str.strip() == grupo]
    if pago and pago in d.columns:
        d = d[_is_truthy(d[pago])]
    return d


_FIG_OUTPUTS = [
    "punt-fig-punt-razona", "punt-fig-punt-lectura", "punt-fig-punt-ciud",
    "punt-fig-punt-ingles", "punt-fig-punt-escrita", "punt-fig-punt-global",
    "punt-fig-desem-razona", "punt-fig-desem-lectura", "punt-fig-desem-ciud",
    "punt-fig-desem-ingles", "punt-fig-desem-escrita",
]


@callback(
    *[Output(fid, "figure") for fid in _FIG_OUTPUTS],
    Output("punt-kpi-total", "children"),
    Output("punt-filter-summary", "children"),
    Input("punt-f-year",    "value"),
    Input("punt-f-periodo", "value"),
    Input("punt-f-genero",  "value"),
    Input("punt-f-estrato", "value"),
    Input("punt-f-depto",   "value"),
    Input("punt-f-mcpio",   "value"),
    Input("punt-f-usb",     "value"),
    Input("punt-f-sede",    "value"),
    Input("punt-f-grupo",   "value"),
    Input("punt-f-pago",    "value"),
)
def update_puntajes(anio, periodo, genero, estrato, depto, mcpio,
                    usb_value, sede, grupo, pago):
    usb_only = bool(usb_value) and "on" in usb_value
    d = _apply_filters(_DF, anio, periodo, genero, estrato, depto, mcpio,
                       usb_only=usb_only, sede=sede, grupo=grupo, pago=pago)
    total = len(d)

    activos = []
    if anio is not None: activos.append(f"año={anio}")
    if periodo:          activos.append(f"periodo={periodo}")
    if genero:           activos.append(f"género={genero}")
    if estrato:          activos.append(f"estrato={estrato}")
    if depto:            activos.append(f"depto={depto}")
    if mcpio:            activos.append(f"mcpio={mcpio}")
    if usb_only:         activos.append("USB=on")
    if sede:             activos.append(f"sede={sede}")
    if grupo:            activos.append(f"grupo={grupo}")
    if pago:
        pago_lab = next((l for l, c in PAGO_COLS if c == pago), pago)
        activos.append(f"pago={pago_lab}")
    resumen = ("Filtros: " + " · ".join(activos)) if activos \
              else "Sin filtros activos · mostrando todo 2016–2023"

    if total == 0:
        empties = [empty_fig()] * len(_FIG_OUTPUTS)
        return (*empties, "0", resumen + " · sin registros")

    fig_p_raz = hist_fig(d.get("mod_razona_cuantitat_punt"),
                         xlab="Puntaje", color=ACCENT1)
    fig_p_lec = hist_fig(d.get("mod_lectura_critica_punt"),
                         xlab="Puntaje", color=ACCENT2)
    fig_p_ciu = hist_fig(d.get("mod_competen_ciudada_punt"),
                         xlab="Puntaje", color=ACCENT3)
    fig_p_ing = hist_fig(d.get("mod_ingles_punt"),
                         xlab="Puntaje", color=ACCENT4)
    fig_p_esc = hist_fig(d.get("mod_comuni_escrita_punt"),
                         xlab="Puntaje", color=ACCENT5)
    fig_p_glo = hist_fig(d.get("punt_global"),
                         xlab="Puntaje global", color=ACCENT1)

    def desem(col_name, color):
        if col_name not in d.columns: return empty_fig()
        s = d[col_name].dropna().astype(str).str.strip()
        s = s[s != ""].value_counts().sort_index()
        return bar_v_fig(s.index, s.values, color=color,
                         xlab="Nivel", ylab="Cantidad")
    fig_d_raz = desem("mod_razona_cuantitat_desem", ACCENT1)
    fig_d_lec = desem("mod_lectura_critica_desem",  ACCENT2)
    fig_d_ciu = desem("mod_competen_ciudada_desem", ACCENT3)
    fig_d_ing = desem("mod_ingles_desem",           ACCENT4)
    fig_d_esc = desem("mod_comuni_escrita_desem",   ACCENT5)

    figs = [
        fig_p_raz, fig_p_lec, fig_p_ciu,
        fig_p_ing, fig_p_esc, fig_p_glo,
        fig_d_raz, fig_d_lec, fig_d_ciu, fig_d_ing, fig_d_esc,
    ]
    return (*figs, f"{total:,}", resumen + f" · {total:,} registros")


# ─────────────────────────────────────────────────────────────
# CALLBACK SECCIÓN PAREADA SB 11 ↔ SB PRO
# ─────────────────────────────────────────────────────────────

_PAREADO_FIG_OUTPUTS = [
    # scatter
    "punt-fig-pareado-scatter-mate", "punt-fig-pareado-scatter-lect",
    "punt-fig-pareado-scatter-ciud", "punt-fig-pareado-scatter-ing",
    "punt-fig-pareado-scatter-glo",
    # quintiles
    "punt-fig-pareado-quint-mate", "punt-fig-pareado-quint-lect",
    "punt-fig-pareado-quint-ciud", "punt-fig-pareado-quint-ing",
    "punt-fig-pareado-quint-glo",
    # delta
    "punt-fig-pareado-delta-mate", "punt-fig-pareado-delta-lect",
    "punt-fig-pareado-delta-ciud", "punt-fig-pareado-delta-ing",
    "punt-fig-pareado-delta-glo",
    # tendencia por cohorte
    "punt-fig-pareado-trend-mate", "punt-fig-pareado-trend-lect",
    "punt-fig-pareado-trend-ciud", "punt-fig-pareado-trend-ing",
    "punt-fig-pareado-trend-glo",
    # english desempeño
    "punt-fig-pareado-eng-desem",
]


def _corr_table(df):
    rows = [html.Tr([
        html.Th("Módulo",   style={"textAlign": "left",  "padding": "6px 12px",
                                   "color": ACCENT1, "fontSize": "10px",
                                   "letterSpacing": "1.5px",
                                   "borderBottom": f"1px solid {BORDER}"}),
        html.Th("n pares",  style={"textAlign": "right", "padding": "6px 12px",
                                   "color": ACCENT1, "fontSize": "10px",
                                   "letterSpacing": "1.5px",
                                   "borderBottom": f"1px solid {BORDER}"}),
        html.Th("Pearson r",style={"textAlign": "right", "padding": "6px 12px",
                                   "color": ACCENT1, "fontSize": "10px",
                                   "letterSpacing": "1.5px",
                                   "borderBottom": f"1px solid {BORDER}"}),
        html.Th("Spearman ρ",style={"textAlign": "right", "padding": "6px 12px",
                                    "color": ACCENT1, "fontSize": "10px",
                                    "letterSpacing": "1.5px",
                                    "borderBottom": f"1px solid {BORDER}"}),
    ])]
    for sbpro_col, sb11_col, label_short, _ in MODULE_PAIRS:
        if sbpro_col in df.columns and sb11_col in df.columns:
            x = pd.to_numeric(df[sb11_col],  errors="coerce")
            y = pd.to_numeric(df[sbpro_col], errors="coerce")
            mask = x.notna() & y.notna()
            n = int(mask.sum())
            if n >= 2:
                r   = float(x[mask].corr(y[mask], method="pearson"))
                rho = _spearman(x[mask], y[mask])
                r_s, rho_s = f"{r:.3f}", f"{rho:.3f}"
            else:
                r_s, rho_s = "—", "—"
        else:
            n = 0; r_s = "—"; rho_s = "—"
        cell = {"padding": "6px 12px", "fontSize": "12px",
                "color": TEXT_MAIN,
                "borderBottom": f"1px solid {BORDER}"}
        rows.append(html.Tr([
            html.Td(label_short, style={**cell, "textAlign": "left"}),
            html.Td(f"{n:,}",    style={**cell, "textAlign": "right",
                                        "color": TEXT_MUTED}),
            html.Td(r_s,         style={**cell, "textAlign": "right",
                                        "color": ACCENT2, "fontWeight": "700"}),
            html.Td(rho_s,       style={**cell, "textAlign": "right",
                                        "color": ACCENT4, "fontWeight": "700"}),
        ]))
    return html.Table(rows, style={
        "borderCollapse": "collapse", "width": "100%",
        "fontFamily": "'IBM Plex Mono', monospace",
        "background": BG, "border": f"1px solid {BORDER}",
        "borderRadius": "8px", "overflow": "hidden"})


@callback(
    *[Output(fid, "figure") for fid in _PAREADO_FIG_OUTPUTS],
    Output("punt-pareado-summary",    "children"),
    Output("punt-pareado-corr-table", "children"),
    Input("punt-f-year",    "value"),
    Input("punt-f-periodo", "value"),
    Input("punt-f-genero",  "value"),
    Input("punt-f-estrato", "value"),
    Input("punt-f-depto",   "value"),
    Input("punt-f-mcpio",   "value"),
    Input("punt-f-usb",     "value"),
    Input("punt-f-sede",    "value"),
    Input("punt-f-grupo",   "value"),
    Input("punt-f-pago",    "value"),
)
def update_pareado(anio, periodo, genero, estrato, depto, mcpio,
                   usb_value, sede, grupo, pago):
    if _DF_PAREADO.empty:
        empties = [empty_fig("Cache pareado no disponible")] * len(_PAREADO_FIG_OUTPUTS)
        msg = "Cache pareado no construido · revisa conexión a Postgres y la tabla `llaves`."
        return (*empties, msg, html.Div("Sin datos.", style={"color": TEXT_MUTED}))

    usb_only = bool(usb_value) and "on" in usb_value
    d = _apply_filters(_DF_PAREADO, anio, periodo, genero, estrato, depto, mcpio,
                       usb_only=usb_only, sede=sede, grupo=grupo, pago=pago)
    n_pairs = len(d)
    summary = (f"Pares emparejados (filtros aplicados sobre lado SB Pro): "
               f"{n_pairs:,} · total disponible: {len(_DF_PAREADO):,}")

    if n_pairs == 0:
        empties = [empty_fig()] * len(_PAREADO_FIG_OUTPUTS)
        return (*empties, summary + " · sin registros", _corr_table(d))

    scatters, quints, deltas, trends = [], [], [], []
    for sbpro_col, sb11_col, label_short, label_long in MODULE_PAIRS:
        if sbpro_col in d.columns and sb11_col in d.columns:
            scatters.append(density_scatter_fig(
                d[sb11_col], d[sbpro_col],
                xlab=f"{label_short} · SB 11 (norm)",
                ylab=f"{label_short} · SB Pro (norm)"))
            quints.append(quintile_matrix_fig(d[sb11_col], d[sbpro_col]))
            deltas.append(delta_hist_fig(d[sb11_col], d[sbpro_col]))
            trends.append(trend_paired_fig(d, sb11_col, sbpro_col))
        else:
            missing = empty_fig(f"Columnas faltantes: {sb11_col} / {sbpro_col}")
            scatters.append(missing); quints.append(missing)
            deltas.append(missing);   trends.append(missing)

    eng_fig = english_transition_fig(d)

    return (*scatters, *quints, *deltas, *trends, eng_fig,
            summary, _corr_table(d))
