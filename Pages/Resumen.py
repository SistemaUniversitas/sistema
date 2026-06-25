"""
Pages/Resumen.py — Landing Ejecutiva (Vista Ejecutiva / Dashboard Principal)
============================================================================

Resumen ejecutivo y condensado del sistema: consolida ~8 gráficos clave de CADA
módulo (Interuniversitario, Puntajes, Socioeconómico, No profesionalización y
RNA), agrupados por página, más KPIs globales.  Incluye exportación a PDF y
cierre de sesión.

Es la página que ve el usuario "consultor"; el admin accede con "Vista Ejecutiva".
El cómputo de los gráficos es perezoso (al cargar) y se cachea, para no penalizar
el arranque de la app.  Las figuras se pre-binan (histogramas → barras,
densidades → heatmaps) para que sean ligeras en el navegador y en el PDF.
"""

import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import dash
from dash import html, dcc, callback, Input, Output, no_update
from flask import session
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pyarrow.parquet as pq

sys.path.append(str(Path(__file__).resolve().parents[1]))
import Services.report_engine as RE  # noqa: E402

if __name__ != "__main__":
    dash.register_page(__name__, path="/resumen-ejecutivo", name="Vista Ejecutiva")

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "Cache"
DATOS6 = ROOT / "Datos6"
LOGO_BANNER = "/assets/logo-usb-medellin.png"

BG = "#0D1117"; MUTED = "#8B949E"; TEXT = "#E6EDF3"; GRID = "#22272E"
PALETTE = ["#E8730C", "#58A6FF", "#3FB950", "#F78166", "#BC8CFF",
           "#FFB000", "#ED7D31", "#79C0FF"]


def _clean_inst_name(s):
    s = str(s)
    while '""' in s:
        s = s.replace('""', '"')
    s = s.strip().strip('"').strip().replace('"', ' ')
    return " ".join(s.split()).replace(" -", "-")


# ─────────────────────────────────────────────────────────────
# Helpers de figuras (tema oscuro, ligeras / pre-binadas)
# ─────────────────────────────────────────────────────────────
def _lay(title, h=270, **kw):
    lay = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=BG,
               font=dict(color=MUTED, family="IBM Plex Mono", size=9),
               margin=dict(l=48, r=16, t=34, b=36), height=h,
               title=dict(text=title, font=dict(color=TEXT, size=11.5), x=0.02))
    lay.update(kw)
    return lay


def _barh(cats, vals, title, color, fmt="{:,.0f}"):
    cats, vals = list(cats), list(vals)
    fig = go.Figure(go.Bar(y=cats[::-1], x=vals[::-1], orientation="h",
                           marker_color=color,
                           text=[fmt.format(v) for v in vals[::-1]], textposition="auto",
                           textfont=dict(size=8)))
    fig.update_layout(**_lay(title), xaxis=dict(gridcolor=GRID),
                      yaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(size=8)),
                      uniformtext=dict(minsize=7, mode="hide"))
    return fig


def _barv(cats, vals, title, color, fmt="{:,.0f}", angle=-18):
    fig = go.Figure(go.Bar(x=list(cats), y=list(vals), marker_color=color,
                           text=[fmt.format(v) for v in vals], textposition="outside",
                           textfont=dict(size=8)))
    fig.update_layout(**_lay(title), xaxis=dict(gridcolor="rgba(0,0,0,0)", tickangle=angle,
                                                tickfont=dict(size=8)),
                      yaxis=dict(gridcolor=GRID), uniformtext=dict(minsize=7, mode="hide"))
    return fig


def _pie(labels, vals, title):
    fig = go.Figure(go.Pie(labels=list(labels), values=list(vals), hole=0.42,
                           marker=dict(colors=PALETTE), textinfo="label+percent",
                           textfont=dict(size=9), sort=True))
    fig.update_layout(**_lay(title), showlegend=False)
    return fig


def _histbar(series, title, color, xlab="", nb=40):
    a = pd.to_numeric(pd.Series(series), errors="coerce").dropna().to_numpy()
    if a.size == 0:
        return go.Figure().update_layout(**_lay(title))
    counts, edges = np.histogram(a, bins=nb)
    centers = (edges[:-1] + edges[1:]) / 2
    fig = go.Figure(go.Bar(x=centers.tolist(), y=counts.tolist(),
                           width=float(edges[1] - edges[0]), marker_color=color))
    fig.update_layout(**_lay(title), xaxis=dict(title=xlab, gridcolor=GRID),
                      yaxis=dict(title="Frecuencia", gridcolor=GRID))
    return fig


def _line(x, y, title, color, ylab=""):
    fig = go.Figure(go.Scatter(x=list(x), y=list(y), mode="lines+markers",
                               line=dict(color=color, width=2.5), marker=dict(size=6, color=color)))
    fig.update_layout(**_lay(title), xaxis=dict(gridcolor=GRID, dtick=1),
                      yaxis=dict(title=ylab, gridcolor=GRID))
    return fig


def _density(x, y, title, xlab, ylab, nb=45):
    x = pd.to_numeric(pd.Series(x), errors="coerce")
    y = pd.to_numeric(pd.Series(y), errors="coerce")
    m = x.notna() & y.notna()
    x, y = x[m].to_numpy(), y[m].to_numpy()
    if x.size == 0:
        return go.Figure().update_layout(**_lay(title))
    H, xe, ye = np.histogram2d(x, y, bins=nb)
    fig = go.Figure(go.Heatmap(z=H.T.tolist(),
                               x=((xe[:-1] + xe[1:]) / 2).tolist(),
                               y=((ye[:-1] + ye[1:]) / 2).tolist(),
                               colorscale=[[0, BG], [0.25, PALETTE[1]], [1, PALETTE[0]]],
                               showscale=False))
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                             line=dict(color=MUTED, dash="dash", width=1), hoverinfo="skip"))
    fig.update_layout(**_lay(title), xaxis=dict(title=xlab, gridcolor=GRID, range=[0, 1]),
                      yaxis=dict(title=ylab, gridcolor=GRID, range=[0, 1]))
    return fig


def _vc(series, top=None, sort_index=False):
    s = pd.Series(series).dropna().astype(str).str.strip()
    s = s[s != ""]
    v = s.value_counts()
    if sort_index:
        v = v.sort_index()
    if top:
        v = v.head(top)
    return v


# ─────────────────────────────────────────────────────────────
# Constructores por módulo (cada uno devuelve ~8 figuras)
# ─────────────────────────────────────────────────────────────
def _mod_interuniv(kpis):
    df = pq.read_table(str(CACHE_DIR / "SaberPro_Interuniversitario_cache.parquet"), columns=[
        "inst_nombre_institucion", "estu_prgm_academico", "estu_prgm_departamento",
        "gruporeferencia", "mod_razona_cuantitat_punt_norm", "mod_lectura_critica_punt_norm",
        "mod_competen_ciudada_punt_norm", "mod_ingles_punt_norm",
        "punt_global_norm", "punt_global_calc_norm", "anio"]).to_pandas()
    df["inst"] = df["inst_nombre_institucion"].astype(str).map(_clean_inst_name)
    g = pd.to_numeric(df["punt_global_norm"], errors="coerce")
    gc = pd.to_numeric(df["punt_global_calc_norm"], errors="coerce")
    figs = []
    top = df.assign(g=g).groupby("inst")["g"].mean().dropna().sort_values(ascending=False).head(10)
    kpis["universidades"] = f"{df['inst'].nunique():,}"
    kpis["programas"] = f"{df['estu_prgm_academico'].nunique():,}" if "estu_prgm_academico" in df else "—"
    kpis["mejor"] = str(top.index[0]); kpis["mejor_val"] = f"{top.iloc[0]:.3f}"
    figs.append(("Top 10 universidades · Puntaje Global",
                 _barh([t[:40] for t in top.index], top.values.round(3),
                       "Top 10 universidades · Puntaje Global", PALETTE[0], "{:.3f}"),
                 "Universidades con mayor puntaje global promedio."))
    figs.append(("Distribución del Puntaje Global",
                 _histbar(g, "Distribución del Puntaje Global", PALETTE[1], "Global (norm)"),
                 "Distribución del puntaje global normalizado."))
    comp = [("Lóg-Cuant", "mod_razona_cuantitat_punt_norm"), ("Lectora", "mod_lectura_critica_punt_norm"),
            ("Ciudadana", "mod_competen_ciudada_punt_norm"), ("Inglés", "mod_ingles_punt_norm"),
            ("Global", "punt_global_norm")]
    means = [round(float(pd.to_numeric(df[c], errors="coerce").mean()), 3) for _, c in comp]
    figs.append(("Promedio por competencia",
                 _barv([l for l, _ in comp], means, "Promedio por competencia", PALETTE[2], "{:.3f}", angle=0),
                 "Puntaje promedio normalizado por competencia."))
    topc = df.assign(gc=gc).groupby("inst")["gc"].mean().dropna().sort_values(ascending=False).head(10)
    figs.append(("Top 10 universidades · Global Calculado",
                 _barh([t[:40] for t in topc.index], topc.values.round(3),
                       "Top 10 universidades · Global Calculado", PALETTE[3], "{:.3f}"),
                 "Por puntaje global calculado."))
    yr = df.assign(g=g, a=pd.to_numeric(df["anio"], errors="coerce")).dropna(subset=["a"]).groupby("a")["g"].mean()
    figs.append(("Puntaje Global por año",
                 _line([int(x) for x in yr.index], yr.values.round(3), "Puntaje Global por año", PALETTE[4], "Global"),
                 "Evolución del puntaje global promedio."))
    topd = df.assign(g=g, d=df["estu_prgm_departamento"].astype(str)).groupby("d")["g"].mean().dropna().sort_values(ascending=False).head(10)
    figs.append(("Top 10 departamentos · Puntaje Global",
                 _barh([t[:34] for t in topd.index], topd.values.round(3),
                       "Top 10 departamentos · Puntaje Global", PALETTE[5], "{:.3f}"),
                 "Departamentos del programa con mayor global."))
    topgr = df.assign(g=g, gr=df["gruporeferencia"].astype(str)).groupby("gr")["g"].mean().dropna().sort_values(ascending=False).head(10)
    figs.append(("Top 10 grupos de referencia · Global",
                 _barh([t[:34] for t in topgr.index], topgr.values.round(3),
                       "Top 10 grupos de referencia · Global", PALETTE[6], "{:.3f}"),
                 "Grupos de referencia con mayor global."))
    figs.append(("Distribución del Global Calculado",
                 _histbar(gc, "Distribución del Global Calculado", PALETTE[7], "Global calc (norm)"),
                 "Distribución del puntaje global calculado."))
    return {"id": "interuniv", "title": "Saber Pro · Interuniversitario", "figs": figs}


def _mod_puntajes():
    df = pq.read_table(str(CACHE_DIR / "SaberPro_Puntajes_cache.parquet"), columns=[
        "mod_razona_cuantitat_punt", "mod_lectura_critica_punt", "mod_competen_ciudada_punt",
        "mod_ingles_punt", "mod_comuni_escrita_punt", "mod_ingles_desem", "punt_global", "anio"]).to_pandas()
    figs = []
    for label, col, col_color in [
        ("Razonamiento cuantitativo", "mod_razona_cuantitat_punt", PALETTE[1]),
        ("Lectura crítica", "mod_lectura_critica_punt", PALETTE[2]),
        ("Competencias ciudadanas", "mod_competen_ciudada_punt", PALETTE[3]),
        ("Inglés", "mod_ingles_punt", PALETTE[4]),
        ("Comunicación escrita", "mod_comuni_escrita_punt", PALETTE[5]),
        ("Puntaje global", "punt_global", PALETTE[0])]:
        figs.append((f"Distribución · {label}",
                     _histbar(df[col], f"Distribución · {label}", col_color, "Puntaje"),
                     f"Distribución de puntajes de {label}."))
    yr = df.assign(g=pd.to_numeric(df["punt_global"], errors="coerce"),
                   a=pd.to_numeric(df["anio"], errors="coerce")).dropna(subset=["a"]).groupby("a")["g"].mean()
    figs.append(("Puntaje global promedio por año",
                 _line([int(x) for x in yr.index], yr.values.round(1), "Puntaje global promedio por año", PALETTE[6], "Puntaje"),
                 "Evolución del puntaje global por año."))
    nv = _vc(df["mod_ingles_desem"], sort_index=True)
    figs.append(("Nivel de desempeño en Inglés",
                 _barv(nv.index, nv.values, "Nivel de desempeño en Inglés", PALETTE[7], angle=0),
                 "Distribución de niveles de desempeño en inglés."))
    return {"id": "puntajes", "title": "Saber Pro · Puntajes", "figs": figs}


def _mod_socio(kpis):
    df = pq.read_table(str(CACHE_DIR / "SaberPro_Socioeconomico_cache.parquet"), columns=[
        "estu_genero", "fami_estratovivienda", "edad", "fami_educacionmadre",
        "estu_nse_individual", "inst_nombre_institucion", "estu_prgm_academico",
        "estu_areareside", "fami_tieneinternet", "estu_nucleo_pregrado"]).to_pandas()
    kpis.setdefault("registros", f"{len(df):,}")
    figs = []
    gv = _vc(df["estu_genero"])
    figs.append(("Distribución por género", _pie(gv.index, gv.values, "Distribución por género"),
                 "Participación por género."))
    ev = _vc(df["fami_estratovivienda"], sort_index=True)
    figs.append(("Distribución por estrato", _barv(ev.index, ev.values, "Distribución por estrato", PALETTE[0], angle=0),
                 "Estrato socioeconómico de la vivienda."))
    figs.append(("Distribución por edad", _histbar(df["edad"], "Distribución por edad", PALETTE[1], "Edad", nb=35),
                 "Edad de los evaluados."))
    em = _vc(df["fami_educacionmadre"], top=12)
    figs.append(("Educación de la madre", _barh([t[:34] for t in em.index], em.values, "Educación de la madre", PALETTE[2]),
                 "Nivel educativo de la madre."))
    nse = _vc(df["estu_nse_individual"], sort_index=True)
    figs.append(("Nivel socioeconómico (NSE)", _barv(nse.index, nse.values, "Nivel socioeconómico (NSE)", PALETTE[3], angle=0),
                 "Nivel socioeconómico individual."))
    inst = _vc(df["inst_nombre_institucion"].astype(str).map(_clean_inst_name), top=10)
    figs.append(("Top 10 instituciones", _barh([t[:38] for t in inst.index], inst.values, "Top 10 instituciones", PALETTE[4]),
                 "Instituciones con más estudiantes."))
    prg = _vc(df["estu_prgm_academico"], top=10)
    figs.append(("Top 10 programas", _barh([t[:38] for t in prg.index], prg.values, "Top 10 programas", PALETTE[5]),
                 "Programas con más estudiantes."))
    nuc = _vc(df["estu_nucleo_pregrado"], top=10)
    figs.append(("Top 10 núcleos de pregrado", _barh([t[:38] for t in nuc.index], nuc.values, "Top 10 núcleos de pregrado", PALETTE[6]),
                 "Núcleos básicos de conocimiento más frecuentes."))
    return {"id": "socio", "title": "Saber Pro · Socioeconómico", "figs": figs}


def _mod_desercion(kpis):
    figs = []
    try:
        meta = pickle.load(open(CACHE_DIR / "desercion_generica_meta.pkl", "rb"))
        years = sorted(int(y) for y in meta)
        tasas = [round(float(meta[y]["tasa_transicion"]), 1) for y in years]
        nocoin = [round(100 - t, 1) for t in tasas]
        tot = sum(meta[y]["total"] for y in years); cont = sum(meta[y]["continuaron"] for y in years)
        kpis["tasa"] = f"{(cont / tot * 100):.1f}%" if tot else "—"
        figs.append(("Tasa de profesionalización por cohorte",
                     _line(years, tasas, "Tasa de profesionalización por cohorte", PALETTE[2], "%"),
                     "Coincidencia SB 11 a SB Pro por cohorte."))
        figs.append(("Tasa de no coincidencia por cohorte",
                     _line(years, nocoin, "Tasa de no coincidencia por cohorte", PALETTE[3], "%"),
                     "No profesionalización por cohorte."))
        delta = [round(nocoin[i] - nocoin[i - 1], 1) for i in range(1, len(nocoin))]
        figs.append(("Variación interanual (no coincidencia)",
                     _barv(years[1:], delta, "Variación interanual (no coincidencia)", PALETTE[5], "{:+.1f}", angle=0),
                     "Cambio de la tasa de no coincidencia respecto a la cohorte previa."))
    except Exception:
        pass
    try:
        d = pq.read_table(str(CACHE_DIR / "desercion_generica_desertores.parquet"), columns=[
            "fami_estratovivienda", "cole_naturaleza", "cole_area_ubicacion",
            "estu_depto_presentacion", "anio_cohorte"]).to_pandas()
        ev = _vc(d["fami_estratovivienda"], sort_index=True)
        figs.append(("No coincidentes por estrato", _barv(ev.index, ev.values, "No coincidentes por estrato", PALETTE[0], angle=0),
                     "Estrato de quienes no coinciden."))
        nv = _vc(d["cole_naturaleza"])
        figs.append(("Naturaleza del colegio", _pie(nv.index, nv.values, "Naturaleza del colegio"),
                     "Colegio público / privado."))
        av = _vc(d["cole_area_ubicacion"])
        figs.append(("Zona del colegio", _pie(av.index, av.values, "Zona del colegio"),
                     "Zona urbana / rural del colegio."))
        dv = _vc(d["estu_depto_presentacion"], top=10)
        figs.append(("Top 10 departamentos · no coincidentes", _barh([t[:30] for t in dv.index], dv.values, "Top 10 departamentos · no coincidentes", PALETTE[6]),
                     "Departamentos con más no coincidentes."))
        cv = _vc(d["anio_cohorte"], sort_index=True)
        figs.append(("No coincidentes por cohorte", _barv([str(int(float(x))) for x in cv.index], cv.values, "No coincidentes por cohorte", PALETTE[7], angle=0),
                     "Cantidad de no coincidentes por cohorte."))
    except Exception:
        pass
    return {"id": "desercion", "title": "No profesionalización", "figs": figs}


def _mod_rna():
    figs = []
    f1 = {}
    try:
        met = json.load(open(DATOS6 / "metricas.json", encoding="utf-8"))
        f1 = dict(met.get("forma1", []))
    except Exception:
        pass
    mods = [("Razonamiento", "razona_cuantitat", "mod_razona_cuantitat_punt_norm_sbpro"),
            ("Lectura crítica", "lectura_critica", "mod_lectura_critica_punt_norm_sbpro"),
            ("Ciudadanas", "competen_ciudada", "mod_competen_ciudada_punt_norm_sbpro"),
            ("Inglés", "ingles", "mod_ingles_punt_norm_sbpro")]
    if f1:
        labels = [m[0] for m in mods]
        mae = [round(f1.get(m[2], {}).get("mae", 0), 4) for m in mods]
        rmse = [round(f1.get(m[2], {}).get("rmse", 0), 4) for m in mods]
        r2 = [round(f1.get(m[2], {}).get("r2", 0), 3) for m in mods]
        figs.append(("MAE por módulo", _barv(labels, mae, "MAE por módulo (menor es mejor)", PALETTE[0], "{:.4f}", angle=0),
                     "Error absoluto medio del modelo por módulo."))
        figs.append(("RMSE por módulo", _barv(labels, rmse, "RMSE por módulo", PALETTE[3], "{:.4f}", angle=0),
                     "Raíz del error cuadrático medio."))
        figs.append(("R² por módulo", _barv(labels, r2, "R² por módulo (mayor es mejor)", PALETTE[2], "{:.3f}", angle=0),
                     "Coeficiente de determinación del modelo."))
    try:
        cols = [f"{m[1]}_real" for m in mods] + [f"{m[1]}_pred" for m in mods]
        df = pq.read_table(str(DATOS6 / "predicciones.parquet"), columns=cols).to_pandas()
        for label, base, _ in mods:
            figs.append((f"Real vs Predicho · {label}",
                         _density(df[f"{base}_real"], df[f"{base}_pred"],
                                  f"Real vs Predicho · {label}", "Real (norm)", "Predicho (norm)"),
                         "Calibración del modelo (línea = predicción perfecta)."))
    except Exception:
        pass
    return {"id": "rna", "title": "RNA · Predicción Saber Pro", "figs": figs}


# ─────────────────────────────────────────────────────────────
# Cómputo perezoso (una vez) y cacheado
# ─────────────────────────────────────────────────────────────
_DATA = None


def _get_data():
    global _DATA
    if _DATA is not None:
        return _DATA
    kpis = {"años": "2010–2024"}
    modules = []
    for fn in (lambda: _mod_interuniv(kpis), _mod_puntajes,
               lambda: _mod_socio(kpis), lambda: _mod_desercion(kpis), _mod_rna):
        try:
            m = fn()
            if m["figs"]:
                modules.append(m)
        except Exception:
            pass
    try:
        socio = CACHE_DIR / "SaberPro_Socioeconomico_cache.parquet"
        kpis.setdefault("registros", f"{pq.read_metadata(str(socio)).num_rows:,}")
    except Exception:
        kpis.setdefault("registros", "—")
    _DATA = {"kpis": kpis, "modules": modules}
    return _DATA


# ─────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────
def _stat(val, lbl):
    return html.Div([html.Div(val, className="ld-stat-val"),
                     html.Div(lbl, className="ld-stat-lbl")], className="ld-stat")


def _chart(label, fig, desc):
    return html.Div(className="ld-prev-card", children=[
        dcc.Graph(figure=fig, config={"displayModeBar": False},
                  style={"height": f"{fig.layout.height}px"}),
        html.Div(desc, className="ld-prev-tag"),
    ])


layout = html.Div(className="ld-root", children=[
    dcc.Location(id="rs-logout-redirect", refresh=True),
    dcc.Interval(id="rs-trigger", interval=120, max_intervals=1, n_intervals=0),
    dcc.Download(id="rs-pdf-download"),

    html.Div(className="ld-hero ld-fade", children=[
        html.Div(className="ld-hero-inner", children=[
            html.Div(html.Img(src=LOGO_BANNER), className="ld-logo-chip"),
            html.Span("Vista Ejecutiva · Resumen General", className="ld-kicker"),
            html.H1(className="ld-hero-title", children=["Dashboard ", html.Span("Ejecutivo", className="hl")]),
            html.P("Resumen consolidado de los gráficos e indicadores más relevantes de cada "
                   "módulo del análisis Saber 11 – Saber Pro.", className="ld-hero-desc"),
            html.Div(className="ld-cta-row", children=[
                # Navegación de regreso — solo para admin (la llena un callback).
                html.Div(id="rs-admin-nav", style={"display": "contents"}),
                html.Button("📄  Exportar Resumen a PDF", id="rs-pdf-btn", n_clicks=0,
                            className="ld-btn ld-btn-primary"),
                html.Button("Cerrar sesión", id="rs-logout", n_clicks=0, className="ld-btn ld-btn-ghost"),
            ]),
            dcc.Loading(type="circle", color=PALETTE[0],
                        children=html.Div(id="rs-pdf-status", style={
                            "marginTop": "12px", "fontSize": "11px", "color": MUTED})),
        ]),
    ]),

    dcc.Loading(type="default", color=PALETTE[0],
                children=html.Div(id="rs-content", style={"minHeight": "200px"})),

    html.Div(className="ld-foot", children=[
        "Universidad de San Buenaventura · Seccional Medellín · "
        "Sistema de Analítica Académica · Resumen Ejecutivo",
    ]),
])


# ─────────────────────────────────────────────────────────────
# Render perezoso del contenido (KPIs + gráficos por módulo)
# ─────────────────────────────────────────────────────────────
@callback(Output("rs-content", "children"), Input("rs-trigger", "n_intervals"))
def _render(_n):
    data = _get_data()
    k = data["kpis"]
    blocks = [
        html.Div(className="ld-section", children=[
            html.Div([html.H2("Indicadores clave", className="ld-sec-title")], className="ld-sec-head"),
            html.Div(className="ld-stats", children=[
                _stat(k.get("registros", "—"), "Registros analizados"),
                _stat(k.get("universidades", "—"), "Universidades"),
                _stat(k.get("programas", "—"), "Programas académicos"),
                _stat(k.get("tasa", "—"), "Profesionalización"),
                _stat(k.get("años", "—"), "Años analizados"),
            ]),
        ]),
    ]
    for mod in data["modules"]:
        blocks.append(html.Div(className="ld-section", children=[
            html.Div([html.H2(mod["title"], className="ld-sec-title"),
                      html.Span(f'{len(mod["figs"])} gráficos', className="ld-sec-sub")],
                     className="ld-sec-head"),
            html.Div(className="ld-prev-grid",
                     children=[_chart(lbl, fig, desc) for lbl, fig, desc in mod["figs"]]),
        ]))
    return html.Div(blocks)


# ─────────────────────────────────────────────────────────────
# Navegación de regreso — SOLO para admin (el consultor no navega)
# ─────────────────────────────────────────────────────────────
@callback(Output("rs-admin-nav", "children"), Input("rs-trigger", "n_intervals"))
def _admin_nav(_n):
    if session.get("role") != "admin":
        return None
    return html.Span(style={"display": "contents"}, children=[
        dcc.Link("← Volver al Inicio", href="/", className="ld-btn ld-btn-ghost"),
        dcc.Link("Ver módulos", href="/saberpro-interuniversitario",
                 className="ld-btn ld-btn-ghost"),
    ])


# ─────────────────────────────────────────────────────────────
# Cerrar sesión
# ─────────────────────────────────────────────────────────────
@callback(Output("rs-logout-redirect", "href"), Input("rs-logout", "n_clicks"),
          prevent_initial_call=True)
def _logout(n):
    if n:
        session.clear()
        return "/"
    return no_update


# ─────────────────────────────────────────────────────────────
# Exportar a PDF (todos los gráficos agrupados por módulo)
# ─────────────────────────────────────────────────────────────
@callback(Output("rs-pdf-download", "data"), Output("rs-pdf-status", "children"),
          Input("rs-pdf-btn", "n_clicks"), prevent_initial_call=True)
def _export(n):
    if not n:
        return no_update, no_update
    data = _get_data()
    k = data["kpis"]
    payloads = {"resumen": RE.publish_payload("resumen",
        {"Alcance": "Consolidado del sistema", "Años": k.get("años", "—")}, {
            "kpi_registros":     RE.kpi("Registros analizados", k.get("registros", "—")),
            "kpi_universidades": RE.kpi("Universidades", k.get("universidades", "—")),
            "kpi_programas":     RE.kpi("Programas académicos", k.get("programas", "—")),
            "kpi_tasa":          RE.kpi("Tasa de profesionalización", k.get("tasa", "—")),
            "kpi_mejor":         RE.kpi("Mejor universidad (Global)",
                                        f"{k.get('mejor', '—')} · {k.get('mejor_val', '')}"),
        })}
    ordered = ["resumen::kpi_registros", "resumen::kpi_universidades",
               "resumen::kpi_programas", "resumen::kpi_tasa", "resumen::kpi_mejor"]
    for mod in data["modules"]:
        sid = f"rmod_{mod['id']}"
        items = {}
        for i, (label, fig, desc) in enumerate(mod["figs"]):
            iid = f"fig{i}"
            items[iid] = RE.figure(label, fig, desc=desc)
            ordered.append(f"{sid}::{iid}")
        payloads[sid] = RE.publish_payload(sid, {}, items, title=mod["title"])

    config = {"title": "Resumen Ejecutivo · Saber 11 – Saber Pro",
              "subtitle": "Vista consolidada del sistema", "user": "",
              "date_str": datetime.now().strftime("%d/%m/%Y")}
    try:
        pdf = RE.build_report_pdf(config, payloads, ordered)
    except Exception as e:  # pragma: no cover
        return no_update, f"✗ Error al generar el PDF: {type(e).__name__}: {e}"
    fname = "Resumen_Ejecutivo_USB_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".pdf"
    return dcc.send_bytes(lambda b: b.write(pdf), fname), "✓ PDF generado. Descarga iniciada."
