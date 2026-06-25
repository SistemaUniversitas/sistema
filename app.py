import os

from dash import Dash, html, dcc, page_container, callback, Input, Output, State, no_update
import dash
from flask import session

import Services.auth as auth
from Services.report_engine import STORE_IDS

app = Dash(__name__, use_pages=True, suppress_callback_exceptions=True)
# Clave para la sesión de Flask (login por roles).
#   • Si se define TG_SECRET_KEY (recomendado en producción / multi-worker) se usa
#     esa clave estable → las sesiones persisten entre reinicios.
#   • Si NO se define, se genera una clave ALEATORIA en cada arranque → al correr
#     el dash todas las sesiones anteriores quedan inválidas y se exige login.
app.server.secret_key = os.environ.get("TG_SECRET_KEY") or os.urandom(24)

app.index_string = """<!DOCTYPE html>
<html>
<head>
    {%metas%}<title>{%title%}</title>{%favicon%}{%css%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #0D1117; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0D1117; }
        ::-webkit-scrollbar-thumb { background: #30363D; border-radius: 3px; }

        /* ── Overlay de carga global ── */
        @keyframes icfes-spin  { to { transform: rotate(360deg); } }
        @keyframes icfes-fade  { from { opacity: 0; } to { opacity: 1; } }
        @keyframes icfes-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }

        .icfes-loading-overlay {
            position: fixed; inset: 0;
            width: 100vw; height: 100vh;
            display: flex; align-items: center; justify-content: center;
            background: rgba(1, 4, 9, 0.74);
            backdrop-filter: blur(2px);
            -webkit-backdrop-filter: blur(2px);
            z-index: 9999;
            animation: icfes-fade 0.18s ease-out;
        }
        .icfes-loading-card {
            display: flex; flex-direction: column; align-items: center; gap: 18px;
            padding: 34px 46px;
            background: #161B22;
            border: 1px solid #30363D;
            border-radius: 14px;
            box-shadow: 0 12px 48px rgba(0, 0, 0, 0.6);
            font-family: 'IBM Plex Mono', monospace;
        }
        .icfes-spinner {
            width: 54px; height: 54px;
            border: 4px solid rgba(232, 115, 12, 0.18);
            border-top-color: #E8730C;
            border-radius: 50%;
            animation: icfes-spin 0.8s linear infinite;
        }
        .icfes-loading-title {
            color: #E6EDF3; font-size: 14px; font-weight: 700;
            letter-spacing: 1.5px; text-transform: uppercase;
            animation: icfes-pulse 1.4s ease-in-out infinite;
        }
        .icfes-loading-sub {
            color: #8B949E; font-size: 11px; letter-spacing: 1px;
        }
    </style>
</head>
<body>{%app_entry%}{%config%}{%scripts%}{%renderer%}</body>
</html>"""

BG = "#0D1117"

# Páginas ocultas de la navbar (versiones antiguas por año + Deserción Cohorte 2015).
_HIDDEN = {"/2007", "/2015", "/2024", "/saberpro2006", "/saberpro2015",
           "/saberpro2023", "/saberpro2023-db", "/desercion2015"}


# ─────────────────────────────────────────────────────────────────────────────
# Vista de Login (overlay a pantalla completa)
# ─────────────────────────────────────────────────────────────────────────────
def _login_overlay():
    return html.Div(className="lg-overlay", children=[
        dcc.Location(id="login-redirect", refresh=True),
        html.Div(className="lg-wrap", children=[
            html.Div(className="lg-card", children=[
                html.Img(src="/assets/USB_Logo.svg.png", className="lg-logo"),
                html.H1("Sistema de Analítica Académica", className="lg-title"),
                html.Div("Universidad de San Buenaventura · Medellín", className="lg-sub"),
                html.Div(className="lg-field", children=[
                    html.Label("Correo", className="lg-label"),
                    dcc.Input(id="login-user", type="email", className="lg-input",
                              placeholder="correo@usb.com", autoComplete="username"),
                ]),
                html.Div(className="lg-field", children=[
                    html.Label("Contraseña", className="lg-label"),
                    dcc.Input(id="login-pass", type="password", className="lg-input",
                              placeholder="••••••••", autoComplete="current-password",
                              n_submit=0),
                ]),
                html.Button("Ingresar", id="login-submit", n_clicks=0, className="lg-btn"),
                html.Div(id="login-msg", className="lg-msg"),
                html.Div("Análisis Saber 11 – Saber Pro", className="lg-foot"),
            ]),
        ]),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# Navbar
# ─────────────────────────────────────────────────────────────────────────────
def _nav_pages():
    reg = {p["path"]: p["name"] for p in dash.page_registry.values()}
    ordered = [(auth.HOME_PATH, "Inicio"), (auth.LANDING_PATH, "Vista Ejecutiva")]
    seen = {auth.HOME_PATH, auth.LANDING_PATH}
    for path, name in reg.items():
        if path in _HIDDEN or path in seen:
            continue
        ordered.append((path, name))
        seen.add(path)
    return ordered


def _build_navbar(active_path, user_name):
    links = []
    for path, name in _nav_pages():
        cls = "nv-link nv-link-active" if path == active_path else "nv-link"
        if path == auth.LANDING_PATH:
            cls += " nv-link-exec"
        links.append(dcc.Link(name, href=path, className=cls))
    return html.Div(className="nv-bar", children=[
        dcc.Link(className="nv-brand", href=auth.HOME_PATH, children=[
            html.Img(src="/assets/logo-usb-medellin.png", className="nv-logo"),
        ]),
        html.Div(links, className="nv-links"),
        html.Div(className="nv-right", children=[
            html.Span(f"● {user_name or 'Usuario'}", className="nv-user"),
            html.Button("Cerrar sesión", id="nav-logout", n_clicks=0, className="nv-logout"),
        ]),
    ])


app.layout = html.Div(style={"background": BG, "minHeight": "100vh"}, children=[

    dcc.Location(id="url", refresh=False),
    dcc.Location(id="redirect", refresh=True),          # redirección forzada (consultor)
    dcc.Location(id="logout-redirect", refresh=True),

    html.Div(id="navbar-container"),

    dcc.Loading(
        id="global-loading",
        custom_spinner=html.Div(
            html.Div([
                html.Div(className="icfes-spinner"),
                html.Div("Procesando información", className="icfes-loading-title"),
                html.Div("Cargando y actualizando diagramas…",
                         className="icfes-loading-sub"),
            ], className="icfes-loading-card"),
            className="icfes-loading-overlay",
        ),
        overlay_style={"visibility": "visible"},
        delay_show=120,
        delay_hide=200,
        children=page_container,
    ),

    # Overlay de login (cubre todo cuando no hay sesión).
    html.Div(id="auth-overlay"),

    # Stores globales del Generador de Reportes (uno por página fuente).
    *[dcc.Store(id=store_id, storage_type="session") for store_id, _ in STORE_IDS],
])


# ─────────────────────────────────────────────────────────────────────────────
# Control de acceso por roles: login overlay + navbar + redirección
# ─────────────────────────────────────────────────────────────────────────────
@callback(
    Output("auth-overlay", "children"),
    Output("navbar-container", "children"),
    Output("redirect", "pathname"),
    Input("url", "pathname"),
)
def _gate(path):
    path = path or auth.HOME_PATH
    role = session.get("role")

    # No autenticado → mostrar el login overlay (cubre cualquier ruta).
    if not role:
        return _login_overlay(), None, no_update

    # Consultor → solo la Landing ejecutiva (redirección forzada si intenta otra).
    if role == "consultor":
        if path != auth.LANDING_PATH:
            return None, None, auth.LANDING_PATH
        return None, None, no_update

    # Admin → acceso total. Navbar oculta en Inicio / Landing.
    navbar = (None if path in auth.NO_NAVBAR_PATHS
              else _build_navbar(path, session.get("name")))
    return None, navbar, no_update


# ─────────────────────────────────────────────────────────────────────────────
# Login: valida contra la BD, guarda sesión y recarga hacia la ruta del rol
# ─────────────────────────────────────────────────────────────────────────────
@callback(
    Output("login-redirect", "href"),
    Output("login-msg", "children"),
    Input("login-submit", "n_clicks"),
    Input("login-pass", "n_submit"),
    State("login-user", "value"),
    State("login-pass", "value"),
    prevent_initial_call=True,
)
def _do_login(n_click, n_submit, correo, pw):
    if not (n_click or n_submit):
        return no_update, no_update
    u = auth.check_credentials(correo, pw)
    if not u:
        return no_update, "Correo o contraseña incorrectos."
    session["role"] = u["role"]
    session["name"] = u["name"]
    session["correo"] = u["correo"]
    return auth.landing_for(u["role"]), ""


@callback(
    Output("logout-redirect", "href"),
    Input("nav-logout", "n_clicks"),
    prevent_initial_call=True,
)
def _logout(n):
    if n:
        session.clear()
        return auth.HOME_PATH
    return no_update


print("Páginas registradas:", list(dash.page_registry.keys()))

if __name__ == "__main__":
    app.run(debug=False, port=8050)
