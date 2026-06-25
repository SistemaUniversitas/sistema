"""
Dashboard ICFES – No profesionalización por Cohorte (Genérico 2010–2018)
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
  - Tasa de no profesionalización = ('Desertores' / Total) × 100

Radio de incertidumbre:
  - Estándar: 5 años (10 semestres) entre SB11 y SB Pro
  - Para cada cohorte se cruzan las tablas saberpro_{2015..2023} vía llaves
    para obtener en qué periodo presentaron SB Pro los que sí continuaron
  - Se muestra la distribución por año real y la desviación en semestres
    (negativa = antes del estándar, positiva = después del estándar)

Cache en disco (Cache/):
  - desercion_generica_meta.pkl         → KPIs + periodo_dist por año {año: {...}}
  - desercion_generica_desertores.parquet → filas de desertores con anio_cohorte

Para forzar reprocesamiento:
    python Pages/Desercion_Generica.py --rebuild
"""

import sys
import pickle
import time
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, callback
import dash

# Motor de reportes (vive en desarrolloInterfaz/Services).
sys.path.append(str(Path(__file__).resolve().parents[1]))
import Services.report_engine as RE

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# REGISTRO DE PÁGINA
# ─────────────────────────────────────────────────────────────
# Solo se registra cuando la app importa el módulo. Al ejecutarlo como script
# (p. ej. `python Pages/Desercion_Generica.py --rebuild`) no hay app instanciada
# y dash.register_page lanzaría PageError, así que se omite en ese caso.
if __name__ != "__main__":
    dash.register_page(__name__, path="/no-profesionalizacion", name="No profesionalización · Por Cohorte")

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
SB11_YEARS        = list(range(2010, 2019))  # 2010 a 2018
SBPRO_YEARS       = list(range(2014, 2024))  # 2014 a 2023
STANDARD_YEARS    = 5                        # tiempo estándar SB11 → SB Pro en años (sin grupo)
STANDARD_SEMESTERS = STANDARD_YEARS * 2     # = 10 semestres

# ── Grupos de referencia Saber Pro y su duración estándar ────────────
# El valor "clave" es EXACTAMENTE el texto almacenado en saberpro_{año}.gruporeferencia
# (mayúsculas, con tildes/ñ). El estándar de tiempo es distinto por grupo.
# (clave_BD, etiqueta_visible, años_estándar)
GRUPO_REF = [
    ("ADMINISTRACIÓN Y AFINES",                "Administración y afines",                4.5),
    ("ARQUITECTURA Y URBANISMO",               "Arquitectura y urbanismo",               5.0),
    ("BELLAS ARTES Y DISEÑO",                  "Bellas artes y diseño",                  4.0),
    ("CIENCIAS AGROPECUARIAS",                 "Ciencias agropecuarias",                 4.5),
    ("CIENCIAS MILITARES Y NAVALES",           "Ciencias militares y navales",           4.0),
    ("CIENCIAS NATURALES Y EXACTAS",           "Ciencias naturales y exactas",           4.5),
    ("CIENCIAS SOCIALES",                      "Ciencias sociales",                      4.0),
    ("COMUNICACIÓN, PERIODISMO Y PUBLICIDAD",  "Comunicación, periodismo y publicidad",  4.0),
    ("CONTADURÍA Y AFINES",                    "Contaduría y afines",                    4.5),
    ("DERECHO",                                "Derecho",                                5.0),
    ("ECONOMÍA",                               "Economía",                               4.5),
    ("EDUCACIÓN",                              "Educación",                              4.0),
    ("ENFERMERÍA",                             "Enfermería",                             4.5),
    ("GRUPO REFERENCIA NACIONAL UNIVERSITARIO","Grupo referencia nacional universitario",4.0),
    ("HUMANIDADES",                            "Humanidades",                            4.0),
    ("INGENIERÍA",                             "Ingeniería",                             5.0),
    ("MEDICINA",                               "Medicina",                               6.0),
    ("PSICOLOGÍA",                             "Psicología",                             5.0),
    ("RECREACIÓN Y DEPORTES",                  "Recreación y deportes",                  4.0),
    ("SALUD",                                  "Salud",                                  4.5),
]
GRUPO_STD   = {k: yrs for k, _lbl, yrs in GRUPO_REF}   # clave_BD → años estándar
GRUPO_LABEL = {k: lbl for k, lbl, _yrs in GRUPO_REF}   # clave_BD → etiqueta visible
SIN_GRUPO   = "(sin grupo)"   # bucket para gruporeferencia NULL/'' (no se muestra en el filtro)

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
# HELPERS DE INCERTIDUMBRE — tiempo entre SB11 y SB Pro
# ─────────────────────────────────────────────────────────────

def _parse_periodo(p, sb11_year: int):
    """Parsea un valor de periodo SB Pro (ej. '20161', '20162', 20161) y devuelve
    (sbpro_year, sbpro_sem, delta_sems) donde delta_sems es el número de semestres
    transcurridos desde el año de SB11 hasta ese periodo SB Pro.
    Devuelve (None, None, None) si el parse falla."""
    try:
        s = str(p).strip().split(".")[0]  # maneja '20161.0' → '20161'
        if len(s) >= 5:
            year = int(s[:4])
            sem  = int(s[4:5])
        elif len(s) == 4:
            year = int(s)
            sem  = 1  # periodo sin semestre → asumir semestre 1
        else:
            return None, None, None
        if year < 2000 or year > 2030 or sem not in (1, 2):
            return None, None, None
        delta_sems = (year - sb11_year) * 2 + (sem - 1)
        return year, sem, delta_sems
    except Exception:
        return None, None, None


def _incert_stats(pairs, std_sems=STANDARD_SEMESTERS):
    """Calcula estadísticas de incertidumbre agregando uno o varios cohortes.
    `pairs` es una lista de (periodo_dist, sb11_year). `std_sems` es el estándar en
    semestres (10 = 5 años, por defecto; varía por grupo de referencia).

    Clasificación (ventana de un año académico que arranca en el estándar):
      - antes:    delta_sems <  std_sems
      - a tiempo: std_sems <= delta_sems <= std_sems + 1  (los 2 semestres del año estándar)
      - después:  delta_sems >  std_sems + 1
    Para std_sems=10 reproduce exactamente la lógica por años previa (a tiempo = año 5)."""
    total = 0
    early_count = 0;  ontime_count = 0;  late_count = 0
    w_dev_sum   = 0.0
    early_dev_sum = 0.0;  late_dev_sum = 0.0

    for periodo_dist, sb11_year in pairs:
        if not periodo_dist:
            continue
        for p, cnt in periodo_dist.items():
            year, sem, delta_sems = _parse_periodo(p, sb11_year)
            if year is None:
                continue
            dev        = delta_sems - std_sems   # desviación en semestres
            total     += cnt
            w_dev_sum += dev * cnt

            if delta_sems < std_sems:
                early_count   += cnt
                early_dev_sum += dev * cnt
            elif delta_sems <= std_sems + 1:
                ontime_count  += cnt
            else:
                late_count    += cnt
                late_dev_sum  += dev * cnt

    if total == 0:
        return None

    avg_dev       = w_dev_sum / total
    early_avg_dev = early_dev_sum / early_count if early_count else 0.0
    late_avg_dev  = late_dev_sum  / late_count  if late_count  else 0.0

    return {
        "total_matched": total,
        "early_count":   early_count,
        "early_pct":     early_count / total * 100,
        "early_avg_dev": early_avg_dev,   # en semestres (negativo)
        "ontime_count":  ontime_count,
        "ontime_pct":    ontime_count / total * 100,
        "late_count":    late_count,
        "late_pct":      late_count / total * 100,
        "late_avg_dev":  late_avg_dev,    # en semestres (positivo)
        "avg_dev":       avg_dev,         # desviación global en semestres
    }


def _fmt_sems(d_sems: float, short=False) -> str:
    """Formatea semestres de desviación como texto legible.
    Redondea primero al semestre entero más cercano para que prefijo y
    desglose sean siempre consistentes (evita '4 sem → 2a 1sem' o '2 sem').
    short=True  → '+3 sem (+1a 1sem)'
    short=False → '1 año y 1 semestre después del estándar'"""
    # Redondear al semestre entero: garantiza years*2 + sems == s_int
    s_int = round(abs(d_sems))   # ej. 4.7 → 5 · 4.3 → 4 · 3.5 → 4
    if s_int == 0:
        return "en el estándar" if short else "en el estándar (≈5 años)"
    years = s_int // 2           # 0, 1, 2, 3 …   (siempre entero)
    sems  = s_int % 2            # siempre 0 ó 1  (nunca puede ser 2)
    sign  = "+" if d_sems > 0 else "−"
    if short:
        parts = []
        if years: parts.append(f"{years}a")
        if sems:  parts.append("1sem")
        return f"{sign}{s_int} sem ({sign}{' '.join(parts) or '1sem'})"
    else:
        parts = []
        if years: parts.append(f"{years} año{'s' if years > 1 else ''}")
        if sems:  parts.append("1 semestre")
        suffix = "después del estándar" if d_sems > 0 else "antes del estándar"
        return f"{' y '.join(parts) or '1 semestre'} {suffix}"


def _fmt_yrs(x):
    """Formatea un nº de años quitando el .0 ('4.0'→'4', '4.5'→'4.5')."""
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _incert_legend_traces():
    """Trazas invisibles para mostrar la leyenda común del esquema de colores
    usado en incert_anos_fig e incert_desviacion_fig."""
    items = [
        (ACCENT5,    "Presentación antes de lo esperado"),
        (ACCENT2,    "Presentación dentro del tiempo esperado"),
        (ACCENT3,    "Presentación luego del tiempo esperado"),
        ("#C23B22",  "Presentación mucho más tarde del tiempo esperado"),
    ]
    return [
        go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=color, symbol="square"),
            name=label, showlegend=True, hoverinfo="skip",
        )
        for color, label in items
    ]


def incert_anos_fig(pairs, std_years=STANDARD_YEARS):
    """Barras por año real de presentación SB Pro.
    Una cohorte → colorea según delta vs su estándar (`std_years`) y marca el esperado.
    Varias cohortes → suma por año calendario (color neutro, sin delta único)."""
    single = len(pairs) == 1

    year_counts: dict = {}
    for periodo_dist, sb11_year in pairs:
        if not periodo_dist:
            continue
        for p, cnt in periodo_dist.items():
            yr, _, _ = _parse_periodo(p, sb11_year)
            if yr is not None:
                year_counts[yr] = year_counts.get(yr, 0) + cnt

    if not year_counts:
        return empty_fig("Sin datos de trayectoria")

    years   = sorted(year_counts.keys())
    counts  = [year_counts[y] for y in years]
    x_idx   = list(range(len(years)))
    expected = None

    if single:
        expected = pairs[0][1] + std_years   # puede ser fraccionario (ej. +4.5)

        def _color(y):
            d = y - expected
            if d < -0.5: return ACCENT5        # antes del estándar: naranja
            if d <= 0.5: return ACCENT2        # en el estándar: verde
            if d <= 2.5: return ACCENT3        # hasta ~2 años tarde: rojo
            return "#C23B22"                   # más tarde: rojo oscuro

        def _xlabel(y):
            d = y - expected
            if abs(d) <= 0.5: return f"{y}<br>✓ estándar"
            return f"{y}<br>{d:+.0f} año{'s' if abs(d) >= 1.5 else ''}"

        colors     = [_color(y)  for y in years]
        x_labels   = [_xlabel(y) for y in years]
        customdata = [f"SB Pro {y} (delta: {y - expected:+.1f} años)" for y in years]
    else:
        colors     = ACCENT1
        x_labels   = [str(y) for y in years]
        customdata = [f"SB Pro {y}" for y in years]

    fig = go.Figure(go.Bar(
        x=x_idx, y=counts,
        marker=dict(color=colors, line=dict(color="rgba(0,0,0,0)")),
        text=[f"{c:,}" for c in counts],
        textposition="outside",
        textfont=dict(size=10, color=TEXT_MUTED),
        customdata=customdata,
        hovertemplate="%{customdata}<br>Estudiantes: %{y:,}<extra></extra>",
        showlegend=False,
    ))

    if single:
        for trace in _incert_legend_traces():
            fig.add_trace(trace)

    # Línea del estándar en su posición (interpolada si es fraccionaria)
    if single and years[0] <= expected <= years[-1]:
        x_exp = 0.0
        for i in range(len(years) - 1):
            if years[i] <= expected <= years[i + 1]:
                span = years[i + 1] - years[i]
                x_exp = i + ((expected - years[i]) / span if span else 0)
                break
        else:
            x_exp = float(len(years) - 1)
        fig.add_vline(x=x_exp, line=dict(color=ACCENT2, dash="dot", width=1.5))

    fig.update_layout(
        **LAYOUT_BASE,
        showlegend=single,
        xaxis=dict(
            title="Año de presentación Saber Pro",
            tickmode="array", tickvals=x_idx, ticktext=x_labels,
            gridcolor="rgba(0,0,0,0)", tickfont=dict(size=10),
        ),
        yaxis=dict(title="Estudiantes coincidentes", gridcolor=BORDER,
                   zerolinecolor=BORDER),
        legend=dict(
            font=dict(color=TEXT_MAIN, size=10),
            bgcolor="rgba(0,0,0,0)",
            orientation="h", yanchor="bottom", y=1.02, x=0,
        ),
    )
    return fig


def incert_desviacion_fig(pairs, std_sems=STANDARD_SEMESTERS, std_years=STANDARD_YEARS):
    """Barras de desviación en semestres respecto al estándar (`std_sems`).
    Negativo = llegaron antes; 0 = exactamente en el estándar; positivo = llegaron después.
    Agrega uno o varios cohortes (la desviación ya está normalizada por cohorte)."""
    sem_counts: dict = {}
    for periodo_dist, sb11_year in pairs:
        if not periodo_dist:
            continue
        for p, cnt in periodo_dist.items():
            _, _, delta_sems = _parse_periodo(p, sb11_year)
            if delta_sems is not None:
                dev = delta_sems - std_sems
                sem_counts[dev] = sem_counts.get(dev, 0) + cnt

    if not sem_counts:
        return empty_fig("Sin datos de trayectoria")

    devs   = sorted(sem_counts.keys())
    counts = [sem_counts[d] for d in devs]

    def _color(d):
        if d < 0:  return ACCENT5
        if d == 0: return ACCENT2
        if d <= 4: return ACCENT3
        return "#C23B22"

    colors = [_color(d) for d in devs]

    def _tick(d):
        if d == 0: return f"0 sem<br>(estándar)"
        s    = abs(d)
        yrs  = int(s // 2)
        srem = int(round(s % 2))
        sign = "+" if d > 0 else "−"
        parts = []
        if yrs:  parts.append(f"{yrs}a")
        if srem: parts.append("1sem")
        return f"{sign}{int(s)} sem<br>({sign}{' '.join(parts) or '½a'})"

    labels = [_tick(d) for d in devs]

    fig = go.Figure(go.Bar(
        x=devs, y=counts,
        marker=dict(color=colors, line=dict(color="rgba(0,0,0,0)")),
        customdata=labels,
        hovertemplate="Desviación: %{customdata}<br>Estudiantes: %{y:,}<extra></extra>",
        showlegend=False,
    ))
    for trace in _incert_legend_traces():
        fig.add_trace(trace)
    fig.add_vline(x=0, line=dict(color=ACCENT2, dash="dot", width=1.5))
    fig.update_layout(
        **LAYOUT_BASE,
        showlegend=True,
        xaxis=dict(
            title=f"Desviación respecto al estándar en semestres  (0 = {_fmt_yrs(std_years)} años)",
            tickmode="array", tickvals=devs, ticktext=labels,
            gridcolor="rgba(0,0,0,0)", tickfont=dict(size=9),
        ),
        yaxis=dict(title="Estudiantes coincidentes", gridcolor=BORDER,
                   zerolinecolor=BORDER),
        legend=dict(
            font=dict(color=TEXT_MAIN, size=10),
            bgcolor="rgba(0,0,0,0)",
            orientation="h", yanchor="bottom", y=1.02, x=0,
        ),
        shapes=[dict(
            type="rect", xref="x", yref="paper",
            x0=-0.5, x1=0.5, y0=0, y1=1,
            fillcolor=ACCENT2, opacity=0.06,
            line=dict(width=0), layer="below",
        )],
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
    print("  Construyendo caché de no profesionalización (2010–2018)…")
    print("  Fuente: Postgres · saber11_XXXX × llaves × saberpro_XXXX")
    print("=" * 65)
    t0 = time.time()

    conn = pg_connect()
    conn.autocommit = True          # cada query es su propia transacción
    cur  = conn.cursor()

    meta       = {}   # {year: {total, continuaron, desertores, tasas, periodo_dist}}
    des_frames = []   # DataFrames de detalle de desertores por año

    # Pre-verificar qué tablas SB Pro tienen estu_consecutivo + periodo
    # y cuáles además tienen 'gruporeferencia' (no todas: p.ej. 2019 no la tiene)
    sbpro_avail = []
    sbpro_grupo = set()
    print("  Verificando tablas SB Pro para incertidumbre…", end=" ")
    for sy in SBPRO_YEARS:
        if _table_exists(cur, f"saberpro_{sy}"):
            cols_sy = _table_columns(cur, f"saberpro_{sy}")
            if "estu_consecutivo" in cols_sy and "periodo" in cols_sy:
                sbpro_avail.append(sy)
                if "gruporeferencia" in cols_sy:
                    sbpro_grupo.add(sy)
    print(f"{sbpro_avail}  (con grupo: {sorted(sbpro_grupo)})")

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
            "periodo_dist":    {},
            "periodo_grupo":   {},
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
            prows = cur.fetchall()
            if prows:
                df_y = pd.DataFrame(prows, columns=detail_cols)
                df_y["anio_cohorte"] = year
                des_frames.append(df_y)
                print(f"         detalle no profesionalizados: {len(df_y):,} filas")

        # ── 4. Distribución por periodo SB Pro (radio de incertidumbre) ──
        #   Para cada tabla saberpro_{sy}, cuenta cuántos estudiantes de
        #   esta cohorte (con llave) presentaron SB Pro en ese año/periodo,
        #   desglosado por gruporeferencia (cuando la columna existe).
        print(f"         [incert] Consultando periodos SB Pro cruzados…", end=" ")
        periodo_grupo: dict = {}   # {grupo: {periodo: count}}
        for sy in sbpro_avail:
            has_grupo  = sy in sbpro_grupo
            grupo_expr = "sp.gruporeferencia::text" if has_grupo else "NULL::text"
            try:
                cur.execute(
                    f"""
                    SELECT sp.periodo::text, {grupo_expr} AS grupo, COUNT(*)
                    FROM {PG_SCHEMA}.{table} s
                    INNER JOIN {PG_SCHEMA}.llaves l
                        ON s.estu_consecutivo::text = l.estu_consecutivo_sb11::text
                    INNER JOIN {PG_SCHEMA}.saberpro_{sy} sp
                        ON l.estu_consecutivo_sbpro::text = sp.estu_consecutivo::text
                    WHERE sp.periodo IS NOT NULL
                    GROUP BY sp.periodo, grupo
                    """
                )
                for prow in cur.fetchall():
                    p_str = str(prow[0])
                    grupo = prow[1]
                    cnt   = int(prow[2])
                    g_key = grupo if grupo not in (None, "") else SIN_GRUPO
                    periodo_grupo.setdefault(g_key, {})
                    periodo_grupo[g_key][p_str] = periodo_grupo[g_key].get(p_str, 0) + cnt
            except Exception as exc:
                print(f"\n         ⚠️  [{year}↔saberpro_{sy}]: {exc}", end=" ")

        # periodo_dist (sin grupo) = suma sobre todos los grupos → idéntico a antes
        periodo_dist: dict = {}
        for g_dist in periodo_grupo.values():
            for p_str, cnt in g_dist.items():
                periodo_dist[p_str] = periodo_dist.get(p_str, 0) + cnt

        meta[year]["periodo_dist"]  = periodo_dist
        meta[year]["periodo_grupo"] = periodo_grupo
        total_match = sum(periodo_dist.values())
        print(f"{total_match:,} pares · {len(periodo_dist)} periodos · "
              f"{len(periodo_grupo)} grupos")

    cur.close()
    conn.close()

    # ── 5. Consolidar y persistir ───────────────────────────────
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
    print(f"     Filas de no profesionalizados : {len(df_des):,}")
    print("=" * 65)
    return meta, df_des


def load_or_build(force=False) -> tuple:
    if not force and CACHE_META.exists() and CACHE_DES.exists():
        print("  Cargando caché no profesionalización…", end=" ", flush=True)
        t0 = time.time()
        try:
            with open(CACHE_META, "rb") as f:
                meta = pickle.load(f)
            # Si la caché no tiene periodo_dist/periodo_grupo (versión anterior), rebuild
            if meta and not all(("periodo_dist" in v and "periodo_grupo" in v)
                                for v in meta.values()):
                print("\n  ⚠️  Caché sin desglose por grupo de referencia. Reprocesando…")
                return build_cache()
            df_des = pd.read_parquet(CACHE_DES)
            print(f"OK ({time.time()-t0:.1f}s) · cohortes={sorted(meta.keys())} "
                  f"· no profesionalizados={len(df_des):,}")
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

def _trendline(years, values):
    """Devuelve los valores de la recta de regresión lineal sobre la serie."""
    if len(years) < 2:
        return None
    xs   = np.array(years, dtype=float)
    coef = np.polyfit(xs, np.array(values, dtype=float), 1)
    return coef[0], (coef[0] * xs + coef[1]).tolist()   # (pendiente pp/año, recta)


def _global_trend():
    """Tendencia global de la tasa de no coincidencia a lo largo de las cohortes."""
    if not _META or len(_META) < 2:
        return None
    years = sorted(_META.keys())
    tasas = [_META[y]["tasa_desercion"] for y in years]
    slope, _ = _trendline(years, tasas)
    return {
        "slope":       slope,                  # puntos porcentuales por año
        "first_year":  years[0],
        "last_year":   years[-1],
        "delta_total": tasas[-1] - tasas[0],
    }


def _overview_figs():
    if not _META:
        return empty_fig("Sin datos"), empty_fig("Sin datos")

    years       = sorted(_META.keys())
    tasas       = [_META[y]["tasa_desercion"] for y in years]   # tasa de no coincidencia
    continuaron = [_META[y]["continuaron"]    for y in years]
    desertores  = [_META[y]["desertores"]     for y in years]

    # ── Gráfico 1: líneas de tasa de no coincidencia / coincidencia + tendencias ──
    tasas_coinc = [100 - t for t in tasas]
    fig_tasa = go.Figure()
    fig_tasa.add_trace(go.Scatter(
        name="No coincidencia",
        x=[str(y) for y in years], y=tasas,
        mode="lines+markers",
        line=dict(color=ACCENT3, width=2.5),
        marker=dict(size=8, color=ACCENT3),
        hovertemplate="Cohorte %{x}<br>No coincidencia: %{y:.2f}%<extra></extra>",
    ))
    tl = _trendline(years, tasas)
    if tl:
        fig_tasa.add_trace(go.Scatter(
            name="Tendencia no coincidencia",
            x=[str(y) for y in years], y=tl[1],
            mode="lines", line=dict(color=ACCENT3, width=1.5, dash="dot"),
            hoverinfo="skip",
        ))
    fig_tasa.add_trace(go.Scatter(
        name="Coincidencia",
        x=[str(y) for y in years], y=tasas_coinc,
        mode="lines+markers",
        line=dict(color=ACCENT2, width=2.5),
        marker=dict(size=8, color=ACCENT2),
        hovertemplate="Cohorte %{x}<br>Coincidencia: %{y:.2f}%<extra></extra>",
    ))
    tl_coinc = _trendline(years, tasas_coinc)
    if tl_coinc:
        fig_tasa.add_trace(go.Scatter(
            name="Tendencia coincidencia",
            x=[str(y) for y in years], y=tl_coinc[1],
            mode="lines", line=dict(color=ACCENT2, width=1.5, dash="dot"),
            hoverinfo="skip",
        ))
    fig_tasa.update_layout(
        **LAYOUT_BASE, showlegend=True,
        xaxis=dict(title="Cohorte (año Saber 11)", gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="Tasa (%)", gridcolor=BORDER,
                   zerolinecolor=BORDER, range=[0, 100]),
        legend=dict(
            font=dict(color=TEXT_MAIN, size=10),
            bgcolor="rgba(0,0,0,0)",
            orientation="h", yanchor="bottom", y=1.02, x=0,
        ),
    )

    # ── Gráfico 2: área apilada al 100% coincidentes vs no coincidentes ──
    fig_comp = go.Figure()
    fig_comp.add_trace(go.Scatter(
        name="Coincidentes",
        x=[str(y) for y in years], y=continuaron,
        mode="lines", stackgroup="one", groupnorm="percent",
        line=dict(width=0.5, color=ACCENT2), fillcolor=ACCENT2,
        hovertemplate="Cohorte %{x}<br>Coincidentes: %{y:.1f}%<extra></extra>",
    ))
    fig_comp.add_trace(go.Scatter(
        name="No coincidentes",
        x=[str(y) for y in years], y=desertores,
        mode="lines", stackgroup="one",
        line=dict(width=0.5, color=ACCENT3), fillcolor=ACCENT3,
        hovertemplate="Cohorte %{x}<br>No coincidentes: %{y:.1f}%<extra></extra>",
    ))
    fig_comp.update_layout(
        **LAYOUT_BASE,
        xaxis=dict(title="Cohorte (año Saber 11)", gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="Proporción (%)", gridcolor=BORDER, zerolinecolor=BORDER,
                   range=[0, 100]),
        legend=dict(
            font=dict(color=TEXT_MAIN, size=10),
            bgcolor="rgba(0,0,0,0)",
            orientation="h", yanchor="bottom", y=1.02, x=0,
        ),
    )
    return fig_tasa, fig_comp


def trend_line_fig(selected_year):
    """Evolución de la tasa de no coincidencia por cohorte, con la cohorte
    seleccionada resaltada y línea de tendencia."""
    if not _META:
        return empty_fig("Sin datos")
    years = sorted(_META.keys())
    tasas       = [_META[y]["tasa_desercion"] for y in years]
    tasas_coinc = [100 - t for t in tasas]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        name="No coincidencia",
        x=[str(y) for y in years], y=tasas,
        mode="lines+markers",
        line=dict(color=ACCENT1, width=2.5),
        marker=dict(size=7, color=ACCENT1),
        hovertemplate="Cohorte %{x}<br>No coincidencia: %{y:.2f}%<extra></extra>",
    ))
    tl = _trendline(years, tasas)
    if tl:
        fig.add_trace(go.Scatter(
            name="Tendencia no coincidencia",
            x=[str(y) for y in years], y=tl[1],
            mode="lines", line=dict(color=ACCENT1, width=1.5, dash="dot"),
            hoverinfo="skip",
        ))
    fig.add_trace(go.Scatter(
        name="Coincidencia",
        x=[str(y) for y in years], y=tasas_coinc,
        mode="lines+markers",
        line=dict(color=ACCENT2, width=2.5),
        marker=dict(size=7, color=ACCENT2),
        hovertemplate="Cohorte %{x}<br>Coincidencia: %{y:.2f}%<extra></extra>",
    ))
    tl_coinc = _trendline(years, tasas_coinc)
    if tl_coinc:
        fig.add_trace(go.Scatter(
            name="Tendencia coincidencia",
            x=[str(y) for y in years], y=tl_coinc[1],
            mode="lines", line=dict(color=ACCENT2, width=1.5, dash="dot"),
            hoverinfo="skip",
        ))
    if selected_year in _META:
        sy_tasa  = _META[selected_year]["tasa_desercion"]
        sy_coinc = 100 - sy_tasa
        fig.add_trace(go.Scatter(
            name="Cohorte seleccionada",
            x=[str(selected_year)], y=[sy_tasa],
            mode="markers+text",
            marker=dict(size=16, color=ACCENT5, line=dict(color=BG, width=2)),
            text=[f"{sy_tasa:.1f}%"], textposition="top center",
            textfont=dict(color=ACCENT5, size=11),
            hovertemplate=f"Cohorte {selected_year}<br>%{{y:.2f}}%<extra></extra>",
            showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            name="Cohorte seleccionada (coincidencia)",
            x=[str(selected_year)], y=[sy_coinc],
            mode="markers+text",
            marker=dict(size=16, color=ACCENT5, line=dict(color=BG, width=2)),
            text=[f"{sy_coinc:.1f}%"], textposition="bottom center",
            textfont=dict(color=ACCENT5, size=11),
            hovertemplate=f"Cohorte {selected_year}<br>%{{y:.2f}}%<extra></extra>",
            showlegend=False,
        ))
    fig.update_layout(
        **LAYOUT_BASE, showlegend=True,
        xaxis=dict(title="Cohorte (año Saber 11)", gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="Tasa (%)", gridcolor=BORDER,
                   zerolinecolor=BORDER, range=[0, 100]),
        legend=dict(
            font=dict(color=TEXT_MAIN, size=10),
            bgcolor="rgba(0,0,0,0)",
            orientation="h", yanchor="bottom", y=1.02, x=0,
        ),
    )
    return fig


def trend_delta_fig(selected_year):
    """Variación interanual de la tasa de no coincidencia (Δ pp vs cohorte previa)."""
    if not _META or len(_META) < 2:
        return empty_fig("Serie insuficiente para variación interanual")
    years = sorted(_META.keys())
    tasas = {y: _META[y]["tasa_desercion"] for y in years}

    dyears = years[1:]
    deltas = [round(tasas[cur] - tasas[prev], 3) for prev, cur in zip(years[:-1], years[1:])]
    # sube = más no coincidencia = peor = rojo · baja = mejor = verde
    colors      = [ACCENT3 if d > 0 else ACCENT2 for d in deltas]
    # contorno para resaltar la cohorte seleccionada
    line_colors = [TEXT_MAIN if y == selected_year else "rgba(0,0,0,0)" for y in dyears]
    # texto del hover pre-formateado a 3 decimales (Plotly ignora %{y:+.3f} con el flag +)
    hover_txt   = [f"{d:+.3f}" for d in deltas]

    fig = go.Figure(go.Bar(
        x=[str(y) for y in dyears], y=deltas,
        marker=dict(color=colors, line=dict(color=line_colors, width=2)),
        text=[f"{d:+.1f}" for d in deltas],
        textposition="outside", textfont=dict(size=10, color=TEXT_MUTED),
        customdata=hover_txt,
        hovertemplate="Cohorte %{x}<br>Δ vs previa: %{customdata} pp<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=BORDER, width=1))
    fig.update_layout(
        **LAYOUT_BASE,
        xaxis=dict(title="Cohorte (año Saber 11)", gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="Δ tasa vs cohorte previa (pp)", gridcolor=BORDER,
                   zerolinecolor=BORDER),
    )
    return fig


_FIG_TASA_OV, _FIG_COMP_OV = _overview_figs()
_TREND                     = _global_trend()

# ─────────────────────────────────────────────────────────────
# AGREGACIÓN "TODAS LAS COHORTES"
# ─────────────────────────────────────────────────────────────
ALL_VALUE = "ALL"   # valor del filtro para "Todas las cohortes"


def _all_totals():
    """Totales agregados de todas las cohortes (para el filtro 'Todas')."""
    if not _META:
        return None
    total = sum(m["total"]       for m in _META.values())
    cont  = sum(m["continuaron"] for m in _META.values())
    des   = sum(m["desertores"]  for m in _META.values())
    return {
        "total":           total,
        "continuaron":     cont,
        "desertores":      des,
        "tasa_transicion": round(cont / total * 100, 2) if total else 0.0,
    }


def _all_pairs():
    """Lista de (periodo_dist, sb11_year) de todas las cohortes."""
    return [(m.get("periodo_dist", {}), y) for y, m in _META.items()]


_ALL_TOTALS = _all_totals()

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


def kpi_box(label, value, color=ACCENT1, subtitle=None, general=False):
    children = []
    if general:
        children.append(
            html.Div("◆ GENERAL · TODAS LAS COHORTES", style={
                "color": ACCENT4, "fontSize": "9px", "letterSpacing": "2px",
                "fontWeight": "700", "marginBottom": "8px"})
        )
    children += [
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
    style = {
        "background": BG, "border": f"1px solid {BORDER}", "borderRadius": "8px",
        "padding": "18px 22px", "textAlign": "center", "flex": "1",
        "minWidth": "160px", "fontFamily": "'IBM Plex Mono', monospace",
    }
    if general:
        style.update({
            "border": f"1px dashed {ACCENT4}",
            "background": "rgba(210, 168, 255, 0.05)",
        })
    return html.Div(children, style=style)


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

YEAR_OPTS     = ([{"label": "Todas las cohortes", "value": ALL_VALUE}]
                 + [{"label": str(y), "value": y} for y in sorted(_META.keys())])
_DEFAULT_YEAR = sorted(_META.keys())[0] if _META else None

# Opciones del filtro de grupo de referencia (value "" = sin grupo → estándar 5 años)
GRUPO_OPTS = ([{"label": f"Sin grupo (estándar {_fmt_yrs(STANDARD_YEARS)} años)", "value": ""}]
              + [{"label": f"{lbl} · {_fmt_yrs(yrs)} años", "value": k}
                 for k, lbl, yrs in GRUPO_REF])

layout = html.Div(style={
    "background": BG, "minHeight": "100vh",
    "fontFamily": "'IBM Plex Mono', monospace",
    "color": TEXT_MAIN, "padding": "24px 32px",
}, children=[

    # ── Header ──────────────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("ICFES · NO PROFESIONALIZACIÓN · COHORTES 2010–2018", style={
                "color": ACCENT1, "fontSize": "11px", "letterSpacing": "4px"}),
            html.H1("No profesionalización por Cohorte", style={
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
            html.Div([
                html.Div("COHORTES ANALIZADAS", style={
                    "color": TEXT_MUTED, "fontSize": "10px", "letterSpacing": "2px"}),
                html.Div(str(len(_META)), style={
                    "color": ACCENT4, "fontSize": "42px", "fontWeight": "700",
                    "letterSpacing": "-1px", "lineHeight": "1"}),
            ], style={"textAlign": "right"}),
            html.Div([
                html.Div("DATOS ANALIZADOS", style={
                    "color": TEXT_MUTED, "fontSize": "10px", "letterSpacing": "2px"}),
                html.Div(id="des-header-count", style={
                    "color": ACCENT1, "fontSize": "42px", "fontWeight": "700",
                    "letterSpacing": "-1px", "lineHeight": "1"}),
                html.Div(id="des-header-scope", style={
                    "color": TEXT_MUTED, "fontSize": "10px", "letterSpacing": "1px",
                    "marginTop": "2px"}),
            ], style={"textAlign": "right"}),
        ], style={"display": "flex", "gap": "40px", "alignItems": "flex-start"}),
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
                html.Div("Tendencia de las tasas de coincidencia y no coincidencia por cohorte",
                         style={"color": TEXT_MUTED, "fontSize": "11px",
                                "marginBottom": "8px"}),
                dcc.Graph(figure=_FIG_TASA_OV, config={"displayModeBar": False},
                          style={"height": "300px"}),
            ]),
            col([
                html.Div("Proporción: coincidentes vs no coincidentes",
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

    # ── Tendencia (línea evolución + variación interanual) ───────
    card([
        section_title("Tendencia de la falta de coincidencia"),
        row(
            col([
                html.Div("Evolución de las tasas de coincidencia y no coincidencia (cohorte resaltada)",
                         style={"color": TEXT_MUTED, "fontSize": "11px",
                                "marginBottom": "8px"}),
                g("des-fig-trend-line", "320px"),
            ]),
            col([
                html.Div("Variación interanual (Δ pp vs cohorte previa)",
                         style={"color": TEXT_MUTED, "fontSize": "11px",
                                "marginBottom": "8px"}),
                g("des-fig-trend-delta", "320px"),
            ]),
        ),
    ]),

    # ── No profesionalizados por estrato ───────────────────────────────────
    card([
        section_title("Falta de coincidencias por estrato socioeconómico"),
        g("des-fig-estrato", "340px"),
    ]),

    # ── Naturaleza + zona ────────────────────────────────────────
    card([
        section_title("Falta de coincidencias por tipo y zona de colegio"),
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
        section_title("Top 10 departamentos con mayor falta de coincidencias"),
        g("des-fig-depto", "360px"),
    ]),

    # ── Radio de incertidumbre ───────────────────────────────────
    card([
        section_title("Radio de incertidumbre — tiempo entre Saber 11 y Saber Pro"),
        html.Div(
            "Mide cuánto tiempo antes o después del estándar llegaron a Saber Pro los "
            "estudiantes con llave coincidente. El tiempo estándar depende del grupo de "
            "referencia: sin grupo seleccionado se usa el estándar general de 5 años.",
            style={"color": TEXT_MUTED, "fontSize": "11px",
                   "lineHeight": "1.7", "marginBottom": "16px"},
        ),
        html.Div([
            html.Div("Grupo de referencia (estándar de tiempo)",
                     style={"color": TEXT_MUTED, "fontSize": "10px",
                            "letterSpacing": "1.5px", "marginBottom": "8px",
                            "textTransform": "uppercase"}),
            dcc.Dropdown(
                id="des-f-grupo",
                options=GRUPO_OPTS,
                value="",
                clearable=False,
                style={"color": "#000", "fontSize": "13px", "maxWidth": "420px"},
            ),
        ], style={"marginBottom": "12px"}),
        html.Div(id="des-incert-std-info",
                 style={"color": TEXT_MUTED, "fontSize": "11px", "marginBottom": "20px"}),
        html.Div(id="des-incert-kpi-row", style={"marginBottom": "20px"}),
        row(
            col([
                html.Div("Año real de presentación Saber Pro (respecto al estándar)",
                         style={"color": TEXT_MUTED, "fontSize": "11px",
                                "marginBottom": "8px"}),
                g("des-fig-incert-anos", "360px"),
            ]),
            col([
                html.Div("Desviación en semestres respecto al estándar (0 = estándar)",
                         style={"color": TEXT_MUTED, "fontSize": "11px",
                                "marginBottom": "8px"}),
                g("des-fig-incert-desv", "360px"),
            ]),
        ),
    ], extra_style={"borderColor": ACCENT1 + "33"}),

    # ── Nota metodológica ────────────────────────────────────────
    card([
        section_title("Nota metodológica"),
        html.Div([
            html.Div([
                html.Span("Nota sobre el concepto  ", style={"color": ACCENT5}),
                html.Span("→  no se mide deserción directamente. Solo se observa si existe o no "
                          "coincidencia de llave entre Saber 11 y Saber Pro; la ausencia de "
                          "coincidencia no confirma deserción (puede ser cambio de identificador, "
                          "presentación fuera del rango 2015–2023, etc.).",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "12px"}),
            html.Div([
                html.Span("Total cohorte  ", style={"color": TEXT_MUTED}),
                html.Span("→  número de filas en saber11_{año} para la cohorte seleccionada.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Coincidentes  ", style={"color": TEXT_MUTED}),
                html.Span("→  estudiantes con coincidencia en llaves.estu_consecutivo_sb11 "
                          "(aparecen en Saber Pro 2015–2023).",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("No coincidentes  ", style={"color": TEXT_MUTED}),
                html.Span("→  Total cohorte − Coincidentes (sin llave coincidente en Saber Pro).",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Tasa de no coincidencia  ", style={"color": TEXT_MUTED}),
                html.Span("→  (No coincidentes / Total cohorte) × 100.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Tasa de transición  ", style={"color": TEXT_MUTED}),
                html.Span("→  (Coincidentes / Total cohorte) × 100  ·  complemento de la anterior.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Tendencia (pp/año)  ", style={"color": TEXT_MUTED}),
                html.Span("→  pendiente de la regresión lineal de la tasa de no coincidencia "
                          "sobre todas las cohortes 2010–2018. Positiva = la no coincidencia crece "
                          "año a año. Indicador global, no depende de la cohorte seleccionada.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Variación interanual (Δ pp)  ", style={"color": TEXT_MUTED}),
                html.Span("→  tasa de no coincidencia de la cohorte menos la de la cohorte previa, "
                          "en puntos porcentuales.",
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
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Estándar de tiempo  ", style={"color": TEXT_MUTED}),
                html.Span("→  5 años (10 semestres) entre el año de SB11 y el año de SB Pro.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Antes del estándar  ", style={"color": TEXT_MUTED}),
                html.Span("→  estudiantes que presentaron SB Pro en menos de 5 años desde su SB11.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Después del estándar  ", style={"color": TEXT_MUTED}),
                html.Span("→  estudiantes que presentaron SB Pro en más de 5 años desde su SB11.",
                          style={"color": TEXT_MAIN}),
            ], style={"marginBottom": "8px"}),
            html.Div([
                html.Span("Desviación (semestres)  ", style={"color": TEXT_MUTED}),
                html.Span("→  delta_sems = (año_SBPro − año_SB11) × 2 + (semestre_SBPro − 1) − 10.",
                          style={"color": TEXT_MAIN}),
            ]),
        ], style={
            "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "12px",
            "lineHeight": "1.8", "color": TEXT_MAIN,
        }),
    ], extra_style={"borderColor": ACCENT4 + "44"}),

    # ── Footer ───────────────────────────────────────────────────
    html.Div("ICFES · Análisis de no profesionalización · Cohortes 2010–2018",
             style={"textAlign": "center", "color": TEXT_MUTED, "fontSize": "10px",
                    "letterSpacing": "2px", "paddingTop": "20px",
                    "borderTop": f"1px solid {BORDER}"}),
])

# ─────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────

@callback(
    Output("des-kpi-row",          "children"),
    Output("des-fig-trend-line",   "figure"),
    Output("des-fig-trend-delta",  "figure"),
    Output("des-fig-estrato",      "figure"),
    Output("des-fig-naturaleza",   "figure"),
    Output("des-fig-area",         "figure"),
    Output("des-fig-depto",        "figure"),
    Output("des-incert-kpi-row",   "children"),
    Output("des-fig-incert-anos",  "figure"),
    Output("des-fig-incert-desv",  "figure"),
    Output("des-incert-std-info",  "children"),
    Output("des-header-count",     "children"),
    Output("des-header-scope",     "children"),
    Output("report-store-desercion", "data"),
    Input("des-f-cohorte",         "value"),
    Input("des-f-grupo",           "value"),
)
def update_cohorte(year, grupo):
    _empty_incert = (
        html.Div("Sin datos de trayectoria.",
                 style={"color": TEXT_MUTED, "fontFamily": "'IBM Plex Mono', monospace"}),
        empty_fig("Sin datos de trayectoria"),
        empty_fig("Sin datos de trayectoria"),
    )
    _no_data = (
        html.Div("Sin cohorte seleccionada.",
                 style={"color": TEXT_MUTED, "fontFamily": "'IBM Plex Mono', monospace"}),
        empty_fig(), empty_fig(),
        empty_fig(), empty_fig(), empty_fig(), empty_fig(),
        *_empty_incert,
        "", "—", "",
        RE.publish_payload("desercion", {}, {}),
    )

    is_all = (year == ALL_VALUE)
    if year is None or (not is_all and year not in _META):
        return _no_data

    # ── Totales según el filtro (cohorte única o todas) ─────────
    if is_all:
        agg          = _ALL_TOTALS
        total        = agg["total"]
        continuaron  = agg["continuaron"]
        desertores   = agg["desertores"]
        tasa_t       = agg["tasa_transicion"]
        total_sub    = "Todas · 2010–2018"
        sel_year     = None                     # sin cohorte resaltada
        header_scope = "Todas · 2010–2018"
    else:
        m            = _META[year]
        total        = m["total"]
        continuaron  = m["continuaron"]
        desertores   = m["desertores"]
        tasa_t       = m["tasa_transicion"]
        total_sub    = f"Cohorte {year}"
        sel_year     = year
        header_scope = f"Cohorte {year}"

    header_count = f"{total:,}"

    # ── Estándar de tiempo según grupo de referencia ────────────
    grupo = grupo or ""                       # "" = sin grupo seleccionado
    if grupo and grupo in GRUPO_STD:
        std_years = GRUPO_STD[grupo]
        grupo_lbl = GRUPO_LABEL.get(grupo, grupo)
    else:
        grupo, std_years, grupo_lbl = "", STANDARD_YEARS, None
    std_sems = int(round(std_years * 2))

    if grupo:
        std_info = html.Span([
            html.Span("Estándar aplicado: ", style={"color": TEXT_MUTED}),
            html.Span(f"{grupo_lbl} → {_fmt_yrs(std_years)} años "
                      f"({std_sems} semestres)", style={"color": ACCENT1}),
        ])
    else:
        std_info = html.Span([
            html.Span("Estándar aplicado: ", style={"color": TEXT_MUTED}),
            html.Span(f"general {_fmt_yrs(STANDARD_YEARS)} años "
                      f"({STANDARD_SEMESTERS} semestres) · sin grupo de referencia",
                      style={"color": ACCENT1}),
        ])

    # KPI de tendencia global (independiente del filtro)
    if _TREND:
        slope = _TREND["slope"]
        if slope > 0.05:
            arrow, tcolor = "↗", ACCENT3      # la no coincidencia crece
        elif slope < -0.05:
            arrow, tcolor = "↘", ACCENT2      # decrece
        else:
            arrow, tcolor = "→", ACCENT5
        trend_val = f"{arrow} {slope:+.2f} pp/año"
        trend_sub = (f"{_TREND['first_year']}→{_TREND['last_year']} · "
                     f"{_TREND['delta_total']:+.1f} pp en total")
    else:
        trend_val, tcolor, trend_sub = "—", TEXT_MUTED, "Serie insuficiente"

    # ── Items base para el Generador de Reportes ──
    rep_filters = {
        "Cohorte": header_scope,
        "Grupo de referencia": grupo_lbl if grupo else "General (5 años)",
    }

    def _rep_kpi_items():
        return {
            "kpi_total":   RE.kpi("Presentaron Saber 11", f"{total:,}"),
            "kpi_nocoinc": RE.kpi("No coincidentes", f"{desertores:,}"),
            "kpi_coinc":   RE.kpi("Coincidentes", f"{continuaron:,}"),
            "kpi_tasa":    RE.kpi("Tasa de profesionalización", f"{tasa_t:.2f}%"),
            "kpi_trend":   RE.kpi("Tendencia", trend_val),
        }

    kpis = html.Div([
        # KPIs del filtro seleccionado
        row(
            kpi_box("Presentaron Saber 11", f"{total:,}",       ACCENT1, total_sub),
            kpi_box("No coincidentes",      f"{desertores:,}",  ACCENT3, "Sin llave en Saber Pro"),
            kpi_box("Coincidentes",         f"{continuaron:,}", ACCENT2, "Con llave en Saber Pro"),
            kpi_box("Tasa de profesionalización",   f"{tasa_t:.2f}%",   ACCENT2, "Coincidentes / Total"),
        ),
        # Indicador general (no depende del filtro)
        html.Div(
            "Indicador general — no depende del filtro seleccionado",
            style={"color": TEXT_MUTED, "fontSize": "10px", "letterSpacing": "1.5px",
                   "textTransform": "uppercase", "marginTop": "20px", "marginBottom": "10px",
                   "paddingTop": "16px", "borderTop": f"1px dashed {BORDER}"},
        ),
        row(
            kpi_box("Tendencia", trend_val, tcolor, trend_sub, general=True),
        ),
    ])

    fig_trend_line  = trend_line_fig(sel_year)
    fig_trend_delta = trend_delta_fig(sel_year)

    if _DF_DES.empty or "anio_cohorte" not in _DF_DES.columns:
        rep_items = _rep_kpi_items()
        rep_items["fig_trend_line"] = RE.figure("Tendencia de no coincidencia por cohorte", fig_trend_line)
        rep_items["fig_trend_delta"] = RE.figure("Variación interanual", fig_trend_delta)
        rep_payload = RE.publish_payload("desercion", rep_filters, rep_items)
        return (kpis, fig_trend_line, fig_trend_delta,
                empty_fig(), empty_fig(), empty_fig(), empty_fig(),
                *_empty_incert, std_info, header_count, header_scope, rep_payload)

    d = _DF_DES if is_all else _DF_DES[_DF_DES["anio_cohorte"] == year]

    # Estrato socioeconómico
    if "fami_estratovivienda" in d.columns:
        estr = d["fami_estratovivienda"].fillna("No reporta").astype(str).str.strip()
        # 'Sin Estrato' se agrupa dentro de 'No reporta'
        estr = estr.mask(estr.str.lower() == "sin estrato", "No reporta")
        vc = estr.value_counts().sort_index()
        n  = len(vc)
        colors = [f"hsl({int(10 + 200 * i / max(n - 1, 1))}, 70%, 55%)" for i in range(n)]
        fig_estrato = bar_v_fig(list(vc.index), list(vc.values),
                                colors=colors, xlab="Estrato", ylab="No coincidentes")
    else:
        fig_estrato = empty_fig("Columna 'fami_estratovivienda' no disponible")

    # Naturaleza del colegio
    if "cole_naturaleza" in d.columns:
        vc = d["cole_naturaleza"].fillna("No reporta").value_counts()
        fig_naturaleza = pie_fig(list(vc.index), list(vc.values))
    else:
        fig_naturaleza = empty_fig("Columna 'cole_naturaleza' no disponible")

    # Zona / área del colegio
    if "cole_area_ubicacion" in d.columns:
        vc = d["cole_area_ubicacion"].fillna("No reporta").value_counts()
        fig_area = pie_fig(list(vc.index), list(vc.values))
    else:
        fig_area = empty_fig("Columna 'cole_area_ubicacion' no disponible")

    # Top 10 departamentos
    if "estu_depto_presentacion" in d.columns:
        vc = d["estu_depto_presentacion"].fillna("No reporta").value_counts().head(10)
        fig_depto = bar_v_fig(list(vc.index), list(vc.values),
                              color=ACCENT5, xlab="Departamento", ylab="No coincidentes")
    else:
        fig_depto = empty_fig("Columna 'estu_depto_presentacion' no disponible")

    # ── Radio de incertidumbre ──────────────────────────────────
    # periodo a usar: por grupo si hay grupo seleccionado, si no el agregado
    def _periodo_of(meta_entry):
        if grupo:
            return meta_entry.get("periodo_grupo", {}).get(grupo, {})
        return meta_entry.get("periodo_dist", {})

    if is_all:
        pairs = [(_periodo_of(mm), yy) for yy, mm in _META.items()]
    else:
        pairs = [(_periodo_of(_META[year]), year)]

    stats = _incert_stats(pairs, std_sems)

    if stats:
        ontime_sub = f"{stats['ontime_pct']:.1f}% · estándar {_fmt_yrs(std_years)} años"
        incert_kpis = row(
            kpi_box(
                f"A tiempo ({_fmt_yrs(std_years)} años)",
                f"{stats['ontime_count']:,}",
                ACCENT2,
                ontime_sub,
            ),
            kpi_box(
                "Antes del estándar",
                f"{stats['early_count']:,}",
                ACCENT5,
                f"{stats['early_pct']:.1f}% · prom. {_fmt_sems(stats['early_avg_dev'], short=True)}",
            ),
            kpi_box(
                "Después del estándar",
                f"{stats['late_count']:,}",
                ACCENT3,
                f"{stats['late_pct']:.1f}% · prom. {_fmt_sems(stats['late_avg_dev'], short=True)}",
            ),
            kpi_box(
                "Desviación promedio global",
                _fmt_sems(stats["avg_dev"]),
                ACCENT4,
                f"{stats['avg_dev']:+.1f} sem respecto al estándar",
            ),
        )
    else:
        incert_kpis = html.Div(
            "Sin datos de trayectoria (periodo_dist vacío o tabla llaves no disponible).",
            style={"color": TEXT_MUTED, "fontFamily": "'IBM Plex Mono', monospace",
                   "fontSize": "12px"},
        )

    fig_incert_anos = incert_anos_fig(pairs, std_years)
    fig_incert_desv = incert_desviacion_fig(pairs, std_sems, std_years)

    rep_items = _rep_kpi_items()
    rep_items["fig_trend_line"]  = RE.figure("Tendencia de no coincidencia por cohorte", fig_trend_line)
    rep_items["fig_trend_delta"] = RE.figure("Variación interanual", fig_trend_delta)
    rep_items["fig_estrato"]     = RE.figure("No coincidentes por estrato", fig_estrato)
    rep_items["fig_naturaleza"]  = RE.figure("Naturaleza del colegio", fig_naturaleza)
    rep_items["fig_area"]        = RE.figure("Zona del colegio", fig_area)
    rep_items["fig_depto"]       = RE.figure("Top 10 departamentos", fig_depto)
    rep_items["fig_incert_anos"] = RE.figure("Radio de incertidumbre · año de presentación", fig_incert_anos)
    rep_items["fig_incert_desv"] = RE.figure("Radio de incertidumbre · desviación", fig_incert_desv)
    rep_payload = RE.publish_payload("desercion", rep_filters, rep_items)

    return (kpis, fig_trend_line, fig_trend_delta,
            fig_estrato, fig_naturaleza, fig_area, fig_depto,
            incert_kpis, fig_incert_anos, fig_incert_desv,
            std_info, header_count, header_scope, rep_payload)
