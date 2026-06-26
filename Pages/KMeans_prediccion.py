"""
Dashboard ICFES · K-Means · Predicción Saber Pro a partir de Saber 11
====================================================================
Página dedicada a visualizar los resultados de la predicción ALTERNATIVA por
K-Means (cluster-then-predict) entrenada en kmeans.py. NO reentrena ni predice
en vivo: lee los artefactos ya generados en la carpeta ArtefactosKMeans/.

Sobre el método (resumen de kmeans.py):
  Los estudiantes se agrupan por su vector de entrada Saber 11 (las mismas
  features que la RNA). Cada clúster "responde" de dos formas:
    - 'media'     : devuelve la media de los 4 módulos Saber Pro de su train.
    - 'reglineal' : ajusta una regresión lineal local multi-salida por clúster.
  El número de clústeres K se elige con el conjunto de validación (minimiza
  MAE_val), no con el codo. El global predicho aún no se calcula, por lo que
  esta página trabaja con los 4 módulos (sin el puntaje global).

Lee de la carpeta ArtefactosKMeans/ (relativa al dashboard):
  - predicciones_kmeans.parquet  (real vs predicho por módulo, columnas
                                   'forma' y 'metodo')
  - metricas_kmeans.json         (MAE/RMSE/R² por módulo, forma y método en
                                   test, y el barrido de selección de K)

Filtros: forma (1/2), método (media/reglineal), módulo, split (test por
defecto), institución. Visualiza: real vs predicho con elipse bivariada de
probabilidad (nivel de confianza interactivo) y outliers 3σ marcados,
distribución, residuales con bandas ±1σ/±2σ/±3σ, selección de K (MAE_val vs K),
comparación media vs reg. lineal y comparación Forma 1 vs Forma 2 (MAE/MSE).

Todos los gráficos, KPIs y la tabla se publican al Generador de Reportes
(store 'report-store-kmeans') para poder exportarlos a PDF.
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import chi2
from dash import html, dcc, dash_table, Input, Output, callback
import dash

# Motor de reportes (vive en Services).
sys.path.append(str(Path(__file__).resolve().parents[1]))
import Services.report_engine as RE

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# REGISTRO DE PÁGINA
# ─────────────────────────────────────────────────────────────
dash.register_page(__name__, path="/kmeans-prediccion",
                   name="K-Means · Predicción Saber Pro")

# ─────────────────────────────────────────────────────────────
# RUTAS A LOS ARTEFACTOS DE K-MEANS
# ─────────────────────────────────────────────────────────────
DASHBOARD_DIR = Path(__file__).resolve().parents[1]
KMEANS_DIR = DASHBOARD_DIR / "ArtefactosKMeans"
if not KMEANS_DIR.exists():
    KMEANS_DIR = DASHBOARD_DIR.parent / "ArtefactosKMeans"

ARCHIVO_PRED = KMEANS_DIR / "predicciones_kmeans.parquet"
ARCHIVO_MET  = KMEANS_DIR / "metricas_kmeans.json"

COL_INST = "inst_nombre_institucion_sbpro"

# Módulos: id interno (en parquet) -> etiqueta legible. K-Means NO predice el
# puntaje global (camino explícito pendiente), por eso aquí solo van los 4.
MODULOS = [
    ("razona_cuantitat", "Razonamiento Cuantitativo"),
    ("lectura_critica",  "Lectura Crítica"),
    ("competen_ciudada", "Competencias Ciudadanas"),
    ("ingles",           "Inglés"),
]
MODULO_LABEL = dict(MODULOS)

# Las claves "largas" del metricas_kmeans.json, en el mismo orden que MODULOS.
MET_KEYS = [
    "mod_razona_cuantitat_punt_norm_sbpro",
    "mod_lectura_critica_punt_norm_sbpro",
    "mod_competen_ciudada_punt_norm_sbpro",
    "mod_ingles_punt_norm_sbpro",
]

METODOS = [
    ("media",     "Media por clúster"),
    ("reglineal", "Regresión lineal local"),
]
METODO_LABEL = dict(METODOS)

MAX_PUNTOS_SCATTER = 6000   # muestreo para el scatter (rendimiento)

# Niveles de confianza disponibles para la elipse bivariada (χ² con 2 g.l.)
NIVELES_CONFIANZA = {"90%": 0.90, "95%": 0.95, "99%": 0.99}

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

LAYOUT_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor ="rgba(0,0,0,0)",
    font=dict(family="'IBM Plex Mono', monospace", color=TEXT_MAIN, size=12),
    margin=dict(t=40, b=40, l=50, r=30),
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

def col(children, flex="1", min_width="220px"):
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

def _alert(msg, color=ACCENT5):
    return html.Div(msg, style={
        "color": color, "padding": "20px",
        "fontFamily": "'IBM Plex Mono', monospace", "fontSize": "13px",
    })

# ─────────────────────────────────────────────────────────────
# CARGA DE ARTEFACTOS (cache en memoria del proceso)
# ─────────────────────────────────────────────────────────────
_cache = {"pred": None, "met": None, "error": None, "instituciones": []}


def _cargar():
    """Carga predicciones/métricas de K-Means una sola vez."""
    if _cache["pred"] is not None or _cache["error"] is not None:
        return
    try:
        if not ARCHIVO_PRED.exists():
            _cache["error"] = (f"No se encontró {ARCHIVO_PRED}. "
                               f"Ejecuta primero kmeans.py.")
            return
        pred = pd.read_parquet(ARCHIVO_PRED)

        met = {}
        if ARCHIVO_MET.exists():
            met = json.loads(ARCHIVO_MET.read_text(encoding="utf-8"))

        instituciones = []
        if COL_INST in pred.columns:
            vc = pred[COL_INST].dropna().astype(str).value_counts()
            # Cap a las 400 instituciones con más registros (dropdown manejable)
            instituciones = list(vc.head(400).index)

        _cache.update({"pred": pred, "met": met, "instituciones": instituciones})
    except Exception as e:
        _cache["error"] = str(e)


def _filtrar(forma, metodo, split, institucion):
    """Devuelve el subconjunto de predicciones según los filtros."""
    df = _cache["pred"]
    sub = df[(df["forma"] == forma) & (df["metodo"] == metodo)]
    if split and split != "todos":
        sub = sub[sub["split"] == split]
    if institucion and institucion != "__TODAS__" and COL_INST in sub.columns:
        sub = sub[sub[COL_INST].astype(str) == institucion]
    return sub


# ─────────────────────────────────────────────────────────────
# ANÁLISIS 3σ Y ELIPSE BIVARIADA DE PROBABILIDAD
# ─────────────────────────────────────────────────────────────
def _sigma_stats(err: np.ndarray):
    """Media, desviación estándar muestral y máscara de outliers |e − μ| > 3σ."""
    mu  = float(np.mean(err))
    sig = float(np.std(err, ddof=1))
    outlier_mask = np.abs(err - mu) > 3 * sig
    return mu, sig, outlier_mask


def _sigma_bands(mu: float, sig: float):
    """Límites de las bandas ±1σ, ±2σ, ±3σ."""
    return {
        1: (mu - sig,     mu + sig),
        2: (mu - 2 * sig, mu + 2 * sig),
        3: (mu - 3 * sig, mu + 3 * sig),
    }


def _calcular_elipse(rx: np.ndarray, py: np.ndarray, nivel: float = 0.95):
    """
    Puntos (x, y) de la elipse de probabilidad bivariada al nivel indicado para
    el par (real, predicho). La elipse se deriva de los autovectores de la matriz
    de covarianza 2×2; el umbral es la distancia de Mahalanobis² = χ²(nivel, df=2).
    Retorna (ex, ey, mu, cov) o (None, None, None, None) si no es calculable.
    """
    if len(rx) < 4:
        return None, None, None, None
    try:
        puntos = np.column_stack([rx, py])
        mu_biv = puntos.mean(axis=0)
        cov    = np.cov(puntos.T)
        vals, vecs = np.linalg.eigh(cov)   # autovalores ascendentes, autovectores ortonormales

        c2 = chi2.ppf(nivel, df=2)
        t  = np.linspace(0, 2 * np.pi, 360)
        eje_a = np.sqrt(max(c2 * vals[1], 0))   # semieje mayor (autovalor mayor)
        eje_b = np.sqrt(max(c2 * vals[0], 0))   # semieje menor (autovalor menor)
        elipse_local = np.column_stack([eje_a * np.cos(t), eje_b * np.sin(t)])

        # Rotar al sistema original (autovector mayor primero) y trasladar al centroide
        R = np.column_stack([vecs[:, 1], vecs[:, 0]])
        elipse_global = elipse_local @ R.T + mu_biv
        return elipse_global[:, 0], elipse_global[:, 1], mu_biv, cov
    except Exception as e:
        print(f"  ⚠  Error calculando elipse bivariada: {e}")
        return None, None, None, None


def _mahalanobis_mask(rx: np.ndarray, py: np.ndarray, nivel: float):
    """Máscara booleana: True si el punto está FUERA de la elipse
    (distancia de Mahalanobis² > umbral χ²(nivel, df=2))."""
    if len(rx) < 4:
        return np.zeros(len(rx), dtype=bool)
    try:
        puntos  = np.column_stack([rx, py])
        mu_biv  = puntos.mean(axis=0)
        cov     = np.cov(puntos.T)
        cov_inv = np.linalg.inv(cov)
        diffs   = puntos - mu_biv
        d2      = np.einsum("ij,jk,ik->i", diffs, cov_inv, diffs)
        return d2 > chi2.ppf(nivel, df=2)
    except Exception:
        return np.zeros(len(rx), dtype=bool)


# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────
_cargar()

if _cache["error"]:
    layout = html.Div(style={
        "background": BG, "minHeight": "100vh",
        "fontFamily": "'IBM Plex Mono', monospace",
        "color": TEXT_MAIN, "padding": "24px 32px",
    }, children=[
        card([
            section_title("K-Means · Predicción Saber Pro"),
            _alert(f"⚠  {_cache['error']}", color=ACCENT3),
            sublabel("Esta página lee ArtefactosKMeans/predicciones_kmeans.parquet "
                     "y ArtefactosKMeans/metricas_kmeans.json."),
        ]),
    ])
else:
    inst_opts = ([{"label": "▸ TODAS las instituciones", "value": "__TODAS__"}] +
                 [{"label": i, "value": i} for i in _cache["instituciones"]])

    layout = html.Div(style={
        "background": BG, "minHeight": "100vh",
        "fontFamily": "'IBM Plex Mono', monospace",
        "color": TEXT_MAIN, "padding": "24px 32px",
    }, children=[

        # ── Header ──
        html.Div([
            html.Div("ICFES · K-MEANS · PREDICCIÓN SABER PRO",
                     style={"color": ACCENT1, "fontSize": "11px",
                            "letterSpacing": "4px"}),
            html.H1("Predicción alternativa por K-Means", style={
                "margin": "4px 0 0 0", "fontSize": "28px",
                "fontWeight": "700", "color": TEXT_MAIN,
            }),
            html.Div("Cluster-then-predict (cuantización vectorial) · "
                     "Saber 11 → Saber Pro · valores normalizados [0,1]",
                     style={"color": TEXT_MUTED, "fontSize": "10px",
                            "letterSpacing": "1px", "marginTop": "6px"}),
        ], style={"marginBottom": "28px", "paddingBottom": "20px",
                  "borderBottom": f"1px solid {BORDER}"}),

        # ── Controles ──
        card([
            section_title("Controles"),
            row(
                col([
                    _dd_label("Forma (entrada del modelo)"),
                    dcc.Dropdown(
                        id="km-forma",
                        options=[
                            {"label": "Forma 1 · solo puntajes", "value": 1},
                            {"label": "Forma 2 · puntajes + socioeconómicas", "value": 2},
                        ],
                        value=2, clearable=False,
                        style={"color": "#000", "fontSize": "12px"},
                    ),
                ], min_width="240px"),
                col([
                    _dd_label("Método del clúster"),
                    dcc.Dropdown(
                        id="km-metodo",
                        options=[{"label": lbl, "value": mid} for mid, lbl in METODOS],
                        value="reglineal", clearable=False,
                        style={"color": "#000", "fontSize": "12px"},
                    ),
                ], min_width="240px"),
                col([
                    _dd_label("Módulo Saber Pro"),
                    dcc.Dropdown(
                        id="km-modulo",
                        options=[{"label": lbl, "value": mid} for mid, lbl in MODULOS],
                        value="razona_cuantitat", clearable=False,
                        style={"color": "#000", "fontSize": "12px"},
                    ),
                ], min_width="240px"),
                col([
                    _dd_label("Conjunto"),
                    dcc.Dropdown(
                        id="km-split",
                        options=[
                            {"label": "Test (cohorte de validación final)", "value": "test"},
                            {"label": "Validación", "value": "val"},
                            {"label": "Entrenamiento", "value": "train"},
                            {"label": "Todos", "value": "todos"},
                        ],
                        value="test", clearable=False,
                        style={"color": "#000", "fontSize": "12px"},
                    ),
                ], min_width="220px"),
                col([
                    _dd_label("Institución"),
                    dcc.Dropdown(
                        id="km-inst",
                        options=inst_opts, value="__TODAS__",
                        clearable=False, optionHeight=44,
                        style={"color": "#000", "fontSize": "12px"},
                    ),
                ], min_width="280px"),
            ),
        ]),

        # ── KPIs ──
        html.Div(id="km-kpis", style={"marginBottom": "20px"}),

        # ── Real vs Predicho + Distribución ──
        row(
            col(card([
                section_title("Real vs Predicho · Elipse bivariada"),
                sublabel(
                    "Cada punto es un estudiante · diagonal = predicción perfecta · "
                    "elipse = región que contiene el % seleccionado bajo normalidad bivariada · "
                    "◆ fuera de la elipse · ○ outlier 3σ residual · ✕ ambos."
                ),
                html.Div([
                    _dd_label("Nivel de confianza de la elipse"),
                    dcc.RadioItems(
                        id="km-nivel-elipse",
                        options=[{"label": k, "value": k} for k in NIVELES_CONFIANZA],
                        value="95%", inline=True,
                        inputStyle={"marginRight": "4px"},
                        labelStyle={"marginRight": "18px", "cursor": "pointer",
                                    "color": TEXT_MAIN, "fontSize": "12px",
                                    "fontFamily": "'IBM Plex Mono', monospace"},
                    ),
                ], style={"marginBottom": "12px"}),
                dcc.Graph(id="km-scatter", config={"displayModeBar": False}),
            ]), min_width="380px"),
            col(card([
                section_title("Distribución · real vs predicho"),
                sublabel("Comparación de las distribuciones de puntaje del módulo."),
                dcc.Graph(id="km-dist", config={"displayModeBar": False}),
            ]), min_width="380px"),
        ),

        # ── Residuales ──
        card([
            section_title("Distribución de residuales (real − predicho)"),
            sublabel("Centrada en 0 y estrecha = buen ajuste · bandas: "
                     "verde ±1σ, naranja ±2σ, rojo ±3σ · fuera de ±3σ = outlier."),
            dcc.Graph(id="km-resid", config={"displayModeBar": False}),
        ]),

        # ── Selección de K + comparación de métodos ──
        row(
            col(card([
                section_title("Selección de K · MAE de validación"),
                sublabel("Barrido de K (criterio: MAE de validación con el predictor "
                         "'media') · ◆ = K elegido. Test se evalúa una sola vez."),
                dcc.Graph(id="km-barrido", config={"displayModeBar": False}),
            ]), min_width="380px"),
            col(card([
                section_title("Media vs Reg. lineal · MAE por módulo (test)"),
                sublabel("Compara las dos respuestas por clúster para la forma activa."),
                dcc.Graph(id="km-metodos", config={"displayModeBar": False}),
            ]), min_width="380px"),
        ),

        # ── Comparación de formas (desde metricas_kmeans.json) ──
        card([
            section_title("Comparación Forma 1 vs Forma 2 · MAE por módulo (test)"),
            sublabel("La diferencia cuantifica el aporte del contexto socioeconómico "
                     "(para el método seleccionado)."),
            dcc.Graph(id="km-formas", config={"displayModeBar": False}),
        ]),

        card([
            section_title("Comparación Forma 1 vs Forma 2 · MSE por módulo (test)"),
            sublabel("La diferencia cuantifica el aporte del contexto socioeconómico "
                     "(para el método seleccionado)."),
            dcc.Graph(id="km-formas-mse", config={"displayModeBar": False}),
        ]),

        # ── Tabla de métricas ──
        card([
            section_title("Métricas por módulo (test)"),
            html.Div(id="km-tabla"),
        ]),
    ])


# ─────────────────────────────────────────────────────────────
# CONSTRUCCIÓN DE FIGURAS (funciones puras reutilizables)
# ─────────────────────────────────────────────────────────────
def _construir_scatter(real, pred, modulo, nivel_str):
    """Scatter Real vs Predicho con elipse bivariada y outliers marcados."""
    nivel      = NIVELES_CONFIANZA.get(nivel_str, 0.95)
    modulo_lbl = MODULO_LABEL.get(modulo, modulo)

    err = real - pred
    _, _, sig_mask = _sigma_stats(err)            # outliers 3σ en residual
    mah_mask       = _mahalanobis_mask(real, pred, nivel)  # fuera de la elipse

    normal_m = ~sig_mask & ~mah_mask
    only_sig =  sig_mask & ~mah_mask
    only_mah = ~sig_mask &  mah_mask
    both_out =  sig_mask &  mah_mask

    fig = go.Figure()

    if normal_m.any():
        fig.add_trace(go.Scattergl(
            x=real[normal_m], y=pred[normal_m], mode="markers",
            marker=dict(size=4, color=ACCENT1, opacity=0.30),
            name="Estudiantes",
            hovertemplate="Real: %{x:.3f}<br>Predicho: %{y:.3f}<extra></extra>",
        ))
    if only_mah.any():
        fig.add_trace(go.Scattergl(
            x=real[only_mah], y=pred[only_mah], mode="markers",
            marker=dict(size=5, color=ACCENT4, opacity=0.55, symbol="diamond"),
            name=f"Fuera de la elipse ({nivel_str})",
            hovertemplate="Real: %{x:.3f}<br>Predicho: %{y:.3f}<br>Outlier bivariado<extra></extra>",
        ))
    if only_sig.any():
        fig.add_trace(go.Scattergl(
            x=real[only_sig], y=pred[only_sig], mode="markers",
            marker=dict(size=6, color=ACCENT5, opacity=0.75,
                        symbol="circle-open", line=dict(width=1.5, color=ACCENT5)),
            name="Outlier 3σ (residual)",
            hovertemplate="Real: %{x:.3f}<br>Predicho: %{y:.3f}<br>Outlier 3σ<extra></extra>",
        ))
    if both_out.any():
        fig.add_trace(go.Scattergl(
            x=real[both_out], y=pred[both_out], mode="markers",
            marker=dict(size=7, color=ACCENT3, opacity=0.85,
                        symbol="x", line=dict(width=1.5, color=ACCENT3)),
            name="Outlier 3σ + bivariado",
            hovertemplate="Real: %{x:.3f}<br>Predicho: %{y:.3f}<br>3σ + bivariado<extra></extra>",
        ))

    ex, ey, mu_biv, _ = _calcular_elipse(real, pred, nivel)
    if ex is not None:
        fig.add_trace(go.Scatter(
            x=ex, y=ey, mode="lines",
            line=dict(color=ACCENT2, width=2, dash="dot"),
            name=f"Elipse {nivel_str}", hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=[mu_biv[0]], y=[mu_biv[1]], mode="markers",
            marker=dict(size=8, color=ACCENT2, symbol="cross"),
            name="Centroide", hoverinfo="skip",
        ))

    fig.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1], mode="lines",
        line=dict(color=ACCENT3, width=1.5, dash="dash"),
        name="Predicción perfecta", hoverinfo="skip",
    ))
    fig.update_layout(
        **LAYOUT_BASE, height=380,
        xaxis=dict(title=f"{modulo_lbl} · Real (normalizado)", range=[0, 1],
                   gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(title="Predicho (normalizado)", range=[0, 1],
                   gridcolor=BORDER, zerolinecolor=BORDER),
        legend=dict(orientation="h", y=1.10, x=0, font=dict(size=10)),
    )
    return fig


def _construir_residuales(err):
    """Histograma de residuales con bandas y líneas ±1σ/±2σ/±3σ y μ."""
    mu_err, sig_err, _ = _sigma_stats(err)
    bands = _sigma_bands(mu_err, sig_err)

    resid = go.Figure(go.Histogram(
        x=err, nbinsx=60, marker_color=ACCENT4, opacity=0.80,
        hovertemplate="Residual: %{x:.3f}<br>Casos: %{y}<extra></extra>",
    ))

    x_min, x_max = float(np.min(err)) - 0.01, float(np.max(err)) + 0.01
    shapes = []
    for (bx0, bx1), bcolor, bop in [
        (bands[1], ACCENT2, 0.06), (bands[2], ACCENT5, 0.05), (bands[3], ACCENT3, 0.05)
    ]:
        shapes.append(dict(type="rect", xref="x", yref="paper",
                           x0=bx0, x1=bx1, y0=0, y1=1,
                           fillcolor=bcolor, opacity=bop,
                           line=dict(width=0), layer="below"))

    vlines = [
        (bands[1][0], ACCENT2, "dot",     "−1σ"), (bands[1][1], ACCENT2, "dot",     "+1σ"),
        (bands[2][0], ACCENT5, "dashdot", "−2σ"), (bands[2][1], ACCENT5, "dashdot", "+2σ"),
        (bands[3][0], ACCENT3, "dash",    "−3σ"), (bands[3][1], ACCENT3, "dash",    "+3σ"),
        (mu_err,      ACCENT1, "solid", f"μ={mu_err:+.4f}"),
        (0.0,         TEXT_MUTED, "dot", "0"),
    ]
    annotations = []
    for vx, vc, vd, vlbl in vlines:
        if x_min <= vx <= x_max:
            shapes.append(dict(type="line", xref="x", yref="paper",
                               x0=vx, x1=vx, y0=0, y1=1,
                               line=dict(color=vc, width=1.2, dash=vd)))
            annotations.append(dict(x=vx, y=1.0, xref="x", yref="paper",
                                    text=vlbl, showarrow=False, yanchor="bottom",
                                    font=dict(size=9, color=vc),
                                    bgcolor="rgba(13,17,23,0.7)"))

    resid.update_layout(
        **LAYOUT_BASE, height=320,
        xaxis=dict(title="Residual (real − predicho)", gridcolor=BORDER,
                   zerolinecolor=BORDER),
        yaxis=dict(title="Frecuencia", gridcolor=BORDER),
        showlegend=False, shapes=shapes, annotations=annotations,
    )
    return resid


def _vacia(height=360):
    return go.Figure().update_layout(**LAYOUT_BASE, height=height)


# ─────────────────────────────────────────────────────────────
# FIGURAS QUE LEEN DEL metricas_kmeans.json  (baratas, sin caché)
# ─────────────────────────────────────────────────────────────
def _met_modulo(metodo, forma, metric_key):
    """Devuelve la lista de valores por módulo (orden MODULOS) para
    metodo/forma desde metricas_kmeans.json. metric_key ∈ {mae, mse, rmse, r2}.
    'mse' se deriva de rmse**2 (el JSON guarda rmse, no mse)."""
    met = _cache["met"] or {}
    forma_d = (((met.get("metricas") or {}).get(metodo) or {})
               .get(f"forma{forma}") or {})
    valores = []
    for mk in MET_KEYS:
        stats = forma_d.get(mk, {})
        if metric_key == "mse":
            v = stats.get("rmse")
            valores.append(v ** 2 if v is not None else np.nan)
        else:
            valores.append(stats.get(metric_key, np.nan))
    return valores


def _fmt_metric(v):
    return f"{v:.3f}" if not (v is None or np.isnan(v)) else "N/D"


def _grafico_barrido(forma):
    """Curva MAE_val vs K del barrido de selección; marca el K elegido."""
    met = _cache["met"] or {}
    sel = (((met.get("seleccion_k") or {}).get(f"forma{forma}")) or {})
    barrido = sel.get("barrido") or []
    k_elegido = sel.get("k_elegido")
    if not barrido:
        return _vacia(380)

    ks   = [d["k"] for d in barrido]
    maes = [d["mae_val"] for d in barrido]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ks, y=maes, mode="lines+markers", name="MAE validación",
        line=dict(color=ACCENT1, width=2),
        marker=dict(size=8, color=ACCENT1),
        hovertemplate="K=%{x}<br>MAE_val=%{y:.4f}<extra></extra>",
    ))
    if k_elegido is not None:
        mae_sel = next((d["mae_val"] for d in barrido if d["k"] == k_elegido), None)
        if mae_sel is not None:
            fig.add_trace(go.Scatter(
                x=[k_elegido], y=[mae_sel], mode="markers",
                marker=dict(size=15, color=ACCENT2, symbol="diamond",
                            line=dict(width=1.5, color=TEXT_MAIN)),
                name=f"K elegido = {k_elegido}",
                hovertemplate=f"K elegido = {k_elegido}<br>MAE_val=%{{y:.4f}}<extra></extra>",
            ))
    fig.update_layout(
        **LAYOUT_BASE, height=380,
        xaxis=dict(title="K (número de clústeres)", type="log",
                   gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(title="MAE de validación", gridcolor=BORDER),
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=10)),
    )
    return fig


def _grafico_metodos(forma):
    """Barras agrupadas: MAE por módulo (test), media vs reglineal, para forma."""
    labels = [lbl for _, lbl in MODULOS]
    val_media = _met_modulo("media", forma, "mae")
    val_regl  = _met_modulo("reglineal", forma, "mae")

    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=val_media, name="Media por clúster",
                         marker_color=ACCENT1,
                         text=[_fmt_metric(v) for v in val_media], textposition="outside"))
    fig.add_trace(go.Bar(x=labels, y=val_regl, name="Reg. lineal local",
                         marker_color=ACCENT2,
                         text=[_fmt_metric(v) for v in val_regl], textposition="outside"))
    fig.update_layout(
        **LAYOUT_BASE, height=380, barmode="group",
        xaxis=dict(gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="MAE (test)", gridcolor=BORDER),
        legend=dict(orientation="h", y=1.1, x=0),
    )
    return fig


def _grafico_formas(metodo, metric_key, titulo_y):
    """Barras agrupadas: métrica por módulo (test), Forma 1 vs Forma 2, para metodo."""
    labels = [lbl for _, lbl in MODULOS]
    val_f1 = _met_modulo(metodo, 1, metric_key)
    val_f2 = _met_modulo(metodo, 2, metric_key)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=val_f1, name="Forma 1 · puntajes",
                         marker_color=ACCENT1,
                         text=[_fmt_metric(v) for v in val_f1], textposition="outside"))
    fig.add_trace(go.Bar(x=labels, y=val_f2, name="Forma 2 · + socioec.",
                         marker_color=ACCENT2,
                         text=[_fmt_metric(v) for v in val_f2], textposition="outside"))
    fig.update_layout(
        **LAYOUT_BASE, height=380, barmode="group",
        xaxis=dict(gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title=titulo_y, gridcolor=BORDER),
        legend=dict(orientation="h", y=1.1, x=0),
    )
    return fig


# ─────────────────────────────────────────────────────────────
# CALLBACK PRINCIPAL
# ─────────────────────────────────────────────────────────────
@callback(
    Output("km-kpis",    "children"),
    Output("km-scatter", "figure"),
    Output("km-dist",    "figure"),
    Output("km-resid",   "figure"),
    Output("km-tabla",   "children"),
    Output("report-store-kmeans", "data"),
    Input("km-forma",  "value"),
    Input("km-metodo", "value"),
    Input("km-modulo", "value"),
    Input("km-split",  "value"),
    Input("km-inst",   "value"),
    Input("km-nivel-elipse", "value"),
)
def actualizar(forma, metodo, modulo, split, institucion, nivel_str):
    sub = _filtrar(forma, metodo, split, institucion)
    col_real, col_pred = f"{modulo}_real", f"{modulo}_pred"
    nivel_str = nivel_str or "95%"

    if len(sub) == 0 or col_real not in sub.columns or col_pred not in sub.columns:
        vacio = _vacia()
        msg = _alert("⚠  No hay datos para esta combinación de filtros.")
        return msg, vacio, vacio, vacio, msg, RE.publish_payload("kmeans", {}, {})

    mask = sub[col_real].notna() & sub[col_pred].notna()
    sub_valid = sub[mask]
    if len(sub_valid) == 0:
        vacio = _vacia()
        msg = _alert("⚠  No hay datos válidos para esta combinación de filtros.")
        return msg, vacio, vacio, vacio, msg, RE.publish_payload("kmeans", {}, {})

    real = sub_valid[col_real].to_numpy(dtype="float64")
    pred = sub_valid[col_pred].to_numpy(dtype="float64")
    err  = real - pred

    mae  = float(np.mean(np.abs(err)))
    mse  = float(np.mean(err ** 2))
    rmse = float(np.sqrt(mse))
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((real - real.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    sesgo = float(np.mean(err))

    _, _, out_full = _sigma_stats(err)
    n_out   = int(out_full.sum())
    pct_out = n_out / len(err) * 100

    k_clusters = "—"
    if "k_clusters" in sub_valid.columns and len(sub_valid):
        try:
            k_clusters = f"{int(sub_valid['k_clusters'].iloc[0])}"
        except Exception:
            pass

    # ── KPIs ──
    kpis = row(
        kpi_box("Estudiantes", f"{len(sub_valid):,}", ACCENT1),
        kpi_box("K (clústeres)", k_clusters, ACCENT4),
        kpi_box("MAE", f"{mae:.4f}", ACCENT2),
        kpi_box("MSE", f"{mse:.4f}", ACCENT5),
        kpi_box("RMSE", f"{rmse:.4f}", ACCENT5),
        kpi_box("R²", f"{r2:.4f}", ACCENT4),
        kpi_box("Sesgo medio", f"{sesgo:+.4f}", ACCENT3),
        kpi_box("Outliers 3σ", f"{n_out:,} ({pct_out:.1f}%)", ACCENT3),
    )

    # ── Scatter real vs predicho (muestreado) ──
    if len(sub_valid) > MAX_PUNTOS_SCATTER:
        idx = np.random.default_rng(42).choice(len(sub_valid), MAX_PUNTOS_SCATTER, replace=False)
        rx, py = real[idx], pred[idx]
    else:
        rx, py = real, pred
    scatter = _construir_scatter(rx, py, modulo, nivel_str)

    # ── Distribución real vs predicho ──
    dist = go.Figure()
    dist.add_trace(go.Histogram(x=real, nbinsx=40, name="Real",
                                marker_color=ACCENT1, opacity=0.6))
    dist.add_trace(go.Histogram(x=pred, nbinsx=40, name="Predicho",
                                marker_color=ACCENT5, opacity=0.6))
    dist.update_layout(
        **LAYOUT_BASE, height=380, barmode="overlay",
        xaxis=dict(title=f"{MODULO_LABEL[modulo]} (normalizado)",
                   range=[0, 1], gridcolor=BORDER),
        yaxis=dict(title="Frecuencia", gridcolor=BORDER),
        legend=dict(orientation="h", y=1.08, x=0),
    )

    # ── Residuales con bandas σ ──
    resid = _construir_residuales(err)

    # ── Tabla de métricas por módulo (sobre el subconjunto actual) ──
    filas = []
    for mid, lbl in MODULOS:
        cr, cp = f"{mid}_real", f"{mid}_pred"
        if cr not in sub.columns or cp not in sub.columns:
            continue
        m_valid = sub[cr].notna() & sub[cp].notna()
        r_arr = sub.loc[m_valid, cr].to_numpy("float64")
        p_arr = sub.loc[m_valid, cp].to_numpy("float64")
        if len(r_arr) == 0:
            continue
        e = r_arr - p_arr
        filas.append({
            "Módulo": lbl,
            "MAE": round(float(np.mean(np.abs(e))), 4),
            "MSE": round(float(np.mean(e ** 2)), 4),
            "RMSE": round(float(np.sqrt(np.mean(e ** 2))), 4),
            "Sesgo": round(float(np.mean(e)), 4),
        })
    tabla = dash_table.DataTable(
        data=filas,
        columns=[{"name": c, "id": c} for c in ["Módulo", "MAE", "MSE", "RMSE", "Sesgo"]],
        style_table={"overflowX": "auto", "border": f"1px solid {BORDER}",
                     "borderRadius": "8px"},
        style_header={"backgroundColor": BG, "color": ACCENT1,
                      "fontFamily": "'IBM Plex Mono', monospace",
                      "fontSize": "11px", "letterSpacing": "1.5px",
                      "textTransform": "uppercase",
                      "border": f"1px solid {BORDER}", "padding": "10px 14px"},
        style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                    "fontFamily": "'IBM Plex Mono', monospace",
                    "fontSize": "12px", "border": f"1px solid {BORDER}",
                    "padding": "8px 14px", "textAlign": "center"},
        style_data_conditional=[{"if": {"row_index": "odd"},
                                 "backgroundColor": BG}],
    )

    # ── Payload para el Generador de Reportes ──
    rep_filters = {
        "Forma": forma, "Método": METODO_LABEL.get(metodo, metodo),
        "Módulo": MODULO_LABEL.get(modulo, modulo),
        "Split": split, "Institución": institucion,
        "Nivel elipse": nivel_str,
    }
    rep_items = {
        "kpi_n":      RE.kpi("Estudiantes", f"{len(sub_valid):,}"),
        "kpi_k":      RE.kpi("K (clústeres)", k_clusters),
        "kpi_mae":    RE.kpi("MAE", f"{mae:.4f}"),
        "kpi_mse":    RE.kpi("MSE", f"{mse:.4f}"),
        "kpi_rmse":   RE.kpi("RMSE", f"{rmse:.4f}"),
        "kpi_r2":     RE.kpi("R²", f"{r2:.4f}"),
        "kpi_sesgo":  RE.kpi("Sesgo medio", f"{sesgo:+.4f}"),
        "kpi_out3s":  RE.kpi("Outliers 3σ", f"{n_out:,} ({pct_out:.1f}%)"),
        "fig_scatter": RE.figure("Real vs Predicho · Elipse bivariada", scatter),
        "fig_dist":    RE.figure("Distribución real vs predicho", dist),
        "fig_resid":   RE.figure("Distribución de residuales", resid),
    }
    # Figuras derivadas del JSON (baratas): barrido, métodos, formas.
    try:
        rep_items["fig_barrido"] = RE.figure(
            f"Selección de K · MAE de validación (Forma {forma})", _grafico_barrido(forma))
        rep_items["fig_metodos"] = RE.figure(
            f"Media vs Reg. lineal · MAE por módulo (Forma {forma})", _grafico_metodos(forma))
        rep_items["fig_formas"] = RE.figure(
            "Comparación Forma 1 vs Forma 2 · MAE por módulo (test)",
            _grafico_formas(metodo, "mae", "MAE (test)"))
        rep_items["fig_formas_mse"] = RE.figure(
            "Comparación Forma 1 vs Forma 2 · MSE por módulo (test)",
            _grafico_formas(metodo, "mse", "MSE (test)"))
    except Exception:
        pass
    if filas:
        _cols = ["Módulo", "MAE", "RMSE", "Sesgo"]
        rep_items["table_metrics"] = RE.table(
            "Métricas por módulo", _cols, [[f[c] for c in _cols] for f in filas])
    rep_payload = RE.publish_payload("kmeans", rep_filters, rep_items)

    return kpis, scatter, dist, resid, tabla, rep_payload


# ─────────────────────────────────────────────────────────────
# CALLBACKS DE FIGURAS DERIVADAS DEL JSON
# ─────────────────────────────────────────────────────────────
@callback(
    Output("km-barrido", "figure"),
    Output("km-metodos", "figure"),
    Input("km-forma", "value"),
)
def actualizar_seleccion_k(forma):
    return _grafico_barrido(forma), _grafico_metodos(forma)


@callback(
    Output("km-formas", "figure"),
    Output("km-formas-mse", "figure"),
    Input("km-metodo", "value"),
)
def comparar_formas(metodo):
    return (_grafico_formas(metodo, "mae", "MAE (test)"),
            _grafico_formas(metodo, "mse", "MSE (test)"))
