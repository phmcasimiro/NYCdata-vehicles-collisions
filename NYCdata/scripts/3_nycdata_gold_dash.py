import os
import json
import sys
import urllib.parse
import logging
import dash
from dash import dcc, html, Input, Output
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from flask_caching import Cache

# ==============================================================================
# 0. CONFIGURAÇÃO DE LOGGING ESTRUTURADO
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("NYCdata/metadata/pipeline.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("GeoDevApp")

# ==============================================================================
# 1. CONFIGURAÇÕES DE CONEXÃO COM O BANCO DE DADOS
# ==============================================================================
dotenv_path = os.path.join("NYCdata", ".env")
load_dotenv(dotenv_path=dotenv_path)

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS") 
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")

if not all([DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
    logger.error("❌ Erro Crítico: Variáveis de ambiente de conexão não encontradas no .env")
    sys.exit(1)

senha_tratada = urllib.parse.quote_plus(DB_PASS)
DATABASE_URL = f"postgresql://{DB_USER}:{senha_tratada}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Otimização do Pool de Conexões do SQLAlchemy para Produção
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    pool_recycle=1800
)

# Carregamento do GeoJSON canônico para o mapa
geojson_path = os.path.join("NYCdata", "data", "geojson", "nyc_borough.geojson")
with open(geojson_path, "r", encoding="utf-8") as f:
    nyc_geojson = json.load(f)

# ==============================================================================
# 2. CONFIGURAÇÃO VISUAL E LAYOUT DO APP (ESTILO ORIGINAL ESCURO PRESERVADO)
# ==============================================================================
# Descobre dinamicamente onde o script está e aponta para a pasta assets um nível acima
# garantindo que as imagens e recursos estáticos sejam carregados corretamente, independentemente do ambiente de execução
script_dir = os.path.dirname(os.path.abspath(__file__))
assets_dir = os.path.join(script_dir, "..", "assets")

app = dash.Dash(
    __name__, 
    assets_folder=assets_dir, # 👈 Linha mágica: diz ao Dash onde encontrar a pasta real
    external_stylesheets=[
        'https://codepen.io/chriddyp/pen/bWLwgP.css',
        'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap'
    ]
)
app.title = "🇺🇸 NYC Collisions Analytics - Camada Gold"

# Habilita CORS nativo de forma segura (restrito a localhost e file://)
@app.server.after_request
def after_request(response):
    from flask import request
    origin = request.headers.get('Origin')
    if origin and (origin.startswith('http://localhost') or origin.startswith('http://127.0.0.1') or origin == 'null'):
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')
    return response



# Configuração do Cache de Callbacks (Flask-Caching)
cache = Cache(app.server, config={
    'CACHE_TYPE': 'FileSystemCache',
    'CACHE_DIR': 'NYCdata/cache',
    'CACHE_DEFAULT_TIMEOUT': 300 # Cache de 5 minutos
})

THEME_COLORS = {
    "background_main": "#041C32",
    "background_card": "#04293A",
    "border_accent": "#064663",
    "text_highlight": "#ECB365",
    "text_light": "#FFFFFF",
    "trend_line": "#EF4444"
}

# Geração de listas dinâmicas para os novos dropdowns baseados no banco
with engine.connect() as conn:
    years_avail = pd.read_sql_query("SELECT DISTINCT year FROM public.nycdata_vehicles_collisions_gold_fact_temporal ORDER BY year DESC;", conn)["year"].tolist()

app.layout = html.Div(
    style={
        "backgroundColor": THEME_COLORS["background_main"], "color": THEME_COLORS["text_light"],
        "padding": "30px", "minHeight": "100vh", "fontFamily": "'Inter', sans-serif"
    }, 
    children=[
        
        # ==============================================================================
        # CABEÇALHO PRINCIPAL REFATORADO (LOGO FIXA À ESQUERDA & TÍTULOS CENTRALIZADOS)
        # ==============================================================================
        html.Div(
            style={
                "position": "relative",         # Permite que a logo seja fixada de forma absoluta dentro dele
                "display": "flex", 
                "alignItems": "center", 
                "justifyContent": "center",     # Centraliza o bloco de texto perfeitamente na tela
                "marginBottom": "40px",
                "minHeight": "85px",            # Garante área vertical confortável para a logo maior
                "padding": "0 5px"
            },
            children=[
                # 🌐 LINK EXTERNO ENVOLVENDO A LOGO
                html.A(
                    href="https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95/about_data",
                    target="_blank",            # 🎯 Abre o dataset original em uma nova aba do navegador
                    style={
                        "position": "absolute", # Mantém a flutuação à esquerda
                        "left": "5px",          # Alinhamento com a borda dos cards
                        "cursor": "pointer",    # Transforma o mouse em "mãozinha" indicando clique
                        "display": "inline-block"
                    },
                    children=[
                        html.Img(
                            src="/assets/nyc_opendata.png", 
                            style={
                                "height": "35px", 
                                "width": "auto",
                                "display": "block"
                            }
                        )
                    ]
                ),
                
                # Bloco de Texto do Título (Centralizado na página e com fontes expandidas)
                html.Div(
                    style={
                        "textAlign": "center",  # Centralização horizontal dos textos
                        "width": "100%",        # Ocupa toda a largura para garantir centro real da tela
                        "paddingLeft": "160px", # Margem de segurança para o título não colidir com a logo
                        "paddingRight": "160px" # Preenchimento idêntico na direita para manter o equilíbrio simétrico
                    },
                    children=[
                        html.H1(
                            "Historical Evolution and Severity of Accidents in NYC", 
                            style={
                                "margin": "0", 
                                "fontWeight": "700", 
                                "color": THEME_COLORS["text_highlight"],
                                "fontSize": "50px"  # Fonte expandida para máxima legibilidade e destaque
                            }
                        ),
                        html.P(
                            "Integrated geospatial and temporal analyses of accidents in New York - General Panorama.", 
                            style={
                                "margin": "8px 0 0 0", 
                                "color": "#8ea1b4", 
                                "fontSize": "25px"  # Subtítulo aumentado para acompanhar a nova proporção macro
                            }
                        ),
                    ]
                )
            ]
        ),

        # Painel de Filtros Superior Estratégico
        html.Div(
            style={
                "backgroundColor": THEME_COLORS["background_card"], "padding": "20px", "borderRadius": "8px",
                "border": f"1px solid {THEME_COLORS['border_accent']}", "marginBottom": "25px"
            },
            className="row",
            children=[
                # Filtro 1: Região
                html.Div(style={"width": "22%", "display": "inline-block", "marginRight": "3%"}, children=[
                    html.Label("Boroughs:", style={"fontWeight": "600", "marginBottom": "8px"}),
                    dcc.Dropdown(
                        id="dropdown-borough",
                        options=[{"label": "All Boroughs", "value": "ALL"}] + [{"label": b, "value": b} for b in ["MANHATTAN", "BROOKLYN", "QUEENS", "BRONX", "STATEN ISLAND"]],
                        value="ALL", clearable=False, style={"color": "#000000"}  
                    )
                ]),
                
                # Filtro 2: Indicadores Canônicos Refatorados
                html.Div(style={"width": "22%", "display": "inline-block", "marginRight": "3%"}, children=[
                    html.Label("Indicators:", style={"fontWeight": "600", "marginBottom": "8px"}),
                    dcc.Dropdown(
                        id="dropdown-metric",
                        options=[
                            {"label": "Total Collisions", "value": "ACCIDENTS"},
                            {"label": "Persons Injured", "value": "INJURED"},
                            {"label": "Persons Killed", "value": "FATALITIES"},
                            {"label": "Total Victims (Injured & Killed)", "value": "INVOLVED"}
                        ],
                        value="ACCIDENTS", clearable=False, style={"color": "#000000"}
                    )
                ]),
                
                # Filtro 3: Seletor de Ano
                html.Div(style={"width": "22%", "display": "inline-block", "marginRight": "3%"}, children=[
                    html.Label("Filter by Year:", style={"fontWeight": "600", "marginBottom": "8px"}),
                    dcc.Dropdown(
                        id="dropdown-year",
                        options=[{"label": "All Years", "value": "ALL"}] + [{"label": str(y), "value": int(y)} for y in years_avail],
                        value="ALL", clearable=False, style={"color": "#000000"}
                    )
                ]),

                # Filtro 4: Novo Seletor de Trimestre (Visão de Gestão de Políticas Públicas)
                html.Div(style={"width": "22%", "display": "inline-block"}, children=[
                    html.Label("Filter by Quarter:", style={"fontWeight": "600", "marginBottom": "8px"}),
                    dcc.Dropdown(
                        id="dropdown-quarter",
                        options=[
                            {"label": "All Quarters", "value": "ALL"},
                            {"label": "1st Quarter (Jan - Mar)", "value": 1},
                            {"label": "2nd Quarter (Apr - Jun)", "value": 2},
                            {"label": "3rd Quarter (Jul - Sep)", "value": 3},
                            {"label": "4th Quarter (Oct - Dec)", "value": 4}
                        ],
                        value="ALL", clearable=False, style={"color": "#000000"}
                    )
                ])
            ]
        ),
        
        # Grid Visual Central
        html.Div(className="row", children=[
            html.Div(className="six columns", children=[
                html.Div(style={"backgroundColor": THEME_COLORS["background_card"], "padding": "15px", "borderRadius": "8px", "border": f"1px solid {THEME_COLORS['border_accent']}"},
                         children=[dcc.Graph(id="graph-map-choropleth")])
            ]),
            html.Div(className="six columns", children=[
                html.Div(style={"backgroundColor": THEME_COLORS["background_card"], "padding": "15px", "borderRadius": "8px", "border": f"1px solid {THEME_COLORS['border_accent']}"},
                         children=[dcc.Graph(id="graph-temporal-evolution")])
            ])
        ]),
        
        html.Br(),
        
        # Grid Visual Inferior (Fatores)
        html.Div(className="row", children=[
            html.Div(className="twelve columns", children=[
                html.Div(style={"backgroundColor": THEME_COLORS["background_card"], "padding": "15px", "borderRadius": "8px", "border": f"1px solid {THEME_COLORS['border_accent']}"},
                         children=[dcc.Graph(id="graph-contributing-factors")])
            ])
        ])
    ]
)

# ==============================================================================
# 3. LÓGICA REATIVA DE REFRESH E MONTAGEM DOS GRÁFICOS (CALLBACK)
# ==============================================================================
BOROUGH_CAMERA = {
    "ALL": {"center": {"lat": 40.7128, "lon": -74.0060}, "zoom": 9.2},
    "MANHATTAN": {"center": {"lat": 40.7750, "lon": -73.9660}, "zoom": 10.0},
    "BROOKLYN": {"center": {"lat": 40.6450, "lon": -73.9450}, "zoom": 10.0},
    "QUEENS": {"center": {"lat": 40.7000, "lon": -73.8300}, "zoom": 9.5},
    "BRONX": {"center": {"lat": 40.8500, "lon": -73.8700}, "zoom": 10.0},
    "STATEN ISLAND": {"center": {"lat": 40.5750, "lon": -74.1400}, "zoom": 10.0}
}

@app.callback(
    [Output("graph-map-choropleth", "figure"),
     Output("graph-temporal-evolution", "figure"),
     Output("graph-contributing-factors", "figure")],
    [Input("dropdown-borough", "value"),
     Input("dropdown-metric", "value"),  
     Input("dropdown-year", "value"),
     Input("dropdown-quarter", "value")] 
)
@cache.memoize()
def update_dashboard(selected_borough, selected_metric, selected_year, selected_quarter):
    logger.info(
        "Filtros acionados no dashboard: Borough=%s, Metric=%s, Year=%s, Quarter=%s",
        selected_borough, selected_metric, selected_year, selected_quarter
    )
    
    METRIC_LABELS = {
        "ACCIDENTS": "Total Collisions", "INJURED": "Persons Injured",
        "FATALITIES": "Persons Killed", "INVOLVED": "Total Victims"
    }
    
    field_mapping = {
        "ACCIDENTS": "total_collisions", "INJURED": "total_injured",
        "FATALITIES": "total_fatalities", "INVOLVED": "people_involved"
    }
    gold_field = field_mapping[selected_metric]

    # --- 1. PREPARAÇÃO SEGURA DOS PARÂMETROS DE INJEÇÃO (SQLALCHMEY) ---
    params = {}
    if selected_borough != "ALL":
        params["borough"] = selected_borough
    if selected_year != "ALL":
        params["year"] = int(selected_year)
    if selected_quarter != "ALL":
        params["quarter"] = int(selected_quarter)

    # --- 2. DESACOPLAMENTO DAS CLÁUSULAS WHERE POR TIPO DE ESTRUTURA GOLD ---
    
    # Filtros para a View Temporal (Baseada nativamente em period_date)
    where_clauses_temp = []
    if selected_borough != "ALL":
        where_clauses_temp.append("borough = :borough")
    if selected_year != "ALL":
        where_clauses_temp.append("year = :year")
    if selected_quarter != "ALL":
        # Extração nativa do trimestre usando a função do Postgres
        where_clauses_temp.append("EXTRACT(QUARTER FROM period_date) = :quarter")
    where_temp_sql = f"WHERE {' AND '.join(where_clauses_temp)}" if where_clauses_temp else ""

    # Filtros para a View de Distribuição Espacial (Mapa)
    where_clauses_spatial = [c for c in where_clauses_temp if "borough" not in c]
    where_clauses_spatial.append("borough NOT IN ('UNKNOWN', 'UNSPECIFIED')")
    where_spatial_sql = f"WHERE {' AND '.join(where_clauses_spatial)}"

    # Filtros para a View de Fatores Contribuintes (Contém year e month numéricos)
    where_clauses_factors = []
    if selected_borough != "ALL":
        where_clauses_factors.append("borough = :borough")
    if selected_year != "ALL":
        where_clauses_factors.append("year = :year")
    if selected_quarter != "ALL":
        # Fórmula matemática para cruzar o trimestre com os meses físicos indexados
        where_clauses_factors.append("month BETWEEN (:quarter * 3 - 2) AND (:quarter * 3)")
    where_factors_sql = f"WHERE {' AND '.join(where_clauses_factors)}" if where_clauses_factors else ""

    # --- 3. MONTAGEM E DISPARO DAS CONSULTAS ---
    query_temporal = f"""
        SELECT period_date as periodo, SUM({gold_field}) as volume
        FROM public.nycdata_vehicles_collisions_gold_fact_temporal
        {where_temp_sql}
        GROUP BY period_date ORDER BY period_date ASC;
    """

    query_spatial = f"""
        SELECT borough, SUM({gold_field}) as volume
        FROM public.nycdata_vehicles_collisions_gold_fact_temporal
        {where_spatial_sql} GROUP BY borough;
    """

    query_fatores = f"""
        SELECT contributing_factor as fator, SUM(total_collisions) as volume
        FROM public.nycdata_vehicles_collisions_gold_fact_contributing_factors
        {where_factors_sql} 
        GROUP BY contributing_factor ORDER BY volume DESC LIMIT 10;
    """

    with engine.connect() as conn:
        df_temporal = pd.read_sql_query(text(query_temporal), conn, params=params)
        df_spatial = pd.read_sql_query(text(query_spatial), conn, params=params)
        df_fatores = pd.read_sql_query(text(query_fatores), conn, params=params)

    # --- 4. MONTAGEM DO MAPA COROPLÉTICO ---
    df_spatial["borough_map"] = df_spatial["borough"].str.title()
    if selected_borough != "ALL":
        df_spatial["color_volume"] = df_spatial.apply(lambda r: r["volume"] if r["borough"] == selected_borough else 0, axis=1)
    else:
        df_spatial["color_volume"] = df_spatial["volume"]
        
    camera = BOROUGH_CAMERA.get(selected_borough, BOROUGH_CAMERA["ALL"])
    
    fig_map = px.choropleth_mapbox(
        df_spatial, geojson=nyc_geojson, locations="borough_map", featureidkey="properties.boroname",
        color="color_volume", color_continuous_scale=[[0, "#05354c"], [1, THEME_COLORS["text_highlight"]]],
        mapbox_style="carto-darkmatter", center=camera["center"], zoom=camera["zoom"],
        labels={"color_volume": METRIC_LABELS[selected_metric], "borough_map": "Borough"},
        title=f"Geospatial Density — {METRIC_LABELS[selected_metric]}"
    )
    fig_map.update_layout(template="plotly_dark", margin={"r":0,"t":40,"l":0,"b":10}, paper_bgcolor=THEME_COLORS["background_card"], plot_bgcolor=THEME_COLORS["background_card"])
    fig_map.update_traces(marker_line_width=1, marker_line_color=THEME_COLORS["border_accent"])

    # --- 5. SÉRIE TEMPORAL COM DUPLA LINHA (VOLATILIDADE VS TENDÊNCIA MACRO) ---
    df_temporal["periodo"] = pd.to_datetime(df_temporal["periodo"])
    
    # Média Móvel de 12 meses (MMA) sobre a série agregada
    df_temporal["trend_12m"] = df_temporal["volume"].rolling(window=12, min_periods=1).mean()

    fig_temporal = go.Figure()
    # Linha 1: Volatilidade Mensal Real
    fig_temporal.add_trace(go.Scatter(
        x=df_temporal["periodo"], y=df_temporal["volume"], mode="lines+markers",
        name="Monthly Volatility", line=dict(color=THEME_COLORS["text_highlight"], width=2)
    ))
    # Linha 2: Tendência de Longo Prazo (Média Móvel)
    fig_temporal.add_trace(go.Scatter(
        x=df_temporal["periodo"], y=df_temporal["trend_12m"], mode="lines",
        name="12-Month Trend Line", line=dict(color=THEME_COLORS["trend_line"], width=2.5, dash="dash")
    ))
    
    fig_temporal.update_layout(
        template="plotly_dark", title=f"Temporal Analysis — {METRIC_LABELS[selected_metric]}",
        xaxis_title="Timeline", yaxis_title="Volume",
        paper_bgcolor=THEME_COLORS["background_card"], plot_bgcolor=THEME_COLORS["background_card"],
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(family="'Inter', sans-serif")
    )

    # --- 6. GRÁFICO DOS TOP 10 FATORES (MÚLTIPLOS VEÍCULOS COMPLETO) ---
    fig_fatores = px.bar(
        df_fatores, x="volume", y="fator", orientation="h",
        labels={"volume": "Occurrences", "fator": "Causal Factor"},
        title=f"Top 10 Valid Causes ({selected_borough})",
        color="volume", color_continuous_scale=[[0, THEME_COLORS["border_accent"]], [1, THEME_COLORS["text_highlight"]]]
    )
    fig_fatores.update_layout(template="plotly_dark", yaxis={'categoryorder':'total ascending'}, paper_bgcolor=THEME_COLORS["background_card"], plot_bgcolor=THEME_COLORS["background_card"], font=dict(family="'Inter', sans-serif"))

    return fig_map, fig_temporal, fig_fatores


# ==============================================================================
# 4. ENDPOINT DE API DE TELEMETRIA DO PIPELINE (PARA A LANDING PAGE)
# ==============================================================================
from flask import jsonify

@app.server.route("/api/status")
def get_pipeline_status():
    # Caminhos físicos dos manifestos de status
    bronze_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "metadata", "bronze_status.json")
    silver_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "metadata", "silver_status.json")

    # Valores padrão de fallback estático (baseados no histórico inicial do projeto)
    last_ingest_date = "N/A"
    last_ingest_qty = 0
    total_approved = 2259956
    total_rejected_dlq = 8959
    watermark_crash_date = "N/A"

    # 1. Tentar ler bronze_status.json para obter carimbo de data e quantidade da última carga incremental
    if os.path.exists(bronze_path):
        try:
            with open(bronze_path, "r", encoding="utf-8") as f:
                bronze_data = json.load(f)
                last_ingest_date = bronze_data.get("updated_at", "N/A")
                last_ingest_qty = bronze_data.get("records_ingested", 0)
                watermark_crash_date = bronze_data.get("watermark_crash_date", "N/A")
        except Exception as e:
            logger.warning(f"Erro ao ler bronze_status.json para API: {e}")

    # 2. Tentar ler silver_status.json para fallback local das métricas
    if os.path.exists(silver_path):
        try:
            with open(silver_path, "r", encoding="utf-8") as f:
                silver_data = json.load(f)
                metrics = silver_data.get("metrics", {})
                total_approved = metrics.get("total_records_approved", total_approved)
                total_rejected_dlq = metrics.get("total_records_rejected_dlq", total_rejected_dlq)
        except Exception as e:
            logger.warning(f"Erro ao ler silver_status.json para API: {e}")

    # 3. Consulta ao PostgreSQL para contagens dinâmicas e precisas em tempo real
    try:
        with engine.connect() as conn:
            # Contagem de validados (Silver)
            query_approved = "SELECT COUNT(*) FROM public.nycdata_vehicle_collisions_cleaned;"
            db_approved = conn.execute(text(query_approved)).scalar()
            if db_approved is not None:
                total_approved = db_approved

            # Contagem de rejeitados (DLQ)
            query_rejections = "SELECT COUNT(*) FROM public.nycdata_vehicle_collisions_rejections;"
            db_rejections = conn.execute(text(query_rejections)).scalar()
            if db_rejections is not None:
                total_rejected_dlq = db_rejections
    except Exception as e:
        logger.warning(f"Erro ao consultar contagens dinâmicas no PostgreSQL: {e}")

    # 4. Estrutura a resposta final
    data = {
        "last_ingest_date": last_ingest_date,
        "last_ingest_qty": last_ingest_qty,
        "total_approved": total_approved,
        "total_rejected_dlq": total_rejected_dlq,
        "watermark_crash_date": watermark_crash_date
    }

    response = jsonify(data)
    return response


if __name__ == "__main__":
    from waitress import serve
    logger.info("🚀 Iniciando servidor corporativo Waitress na porta 8050 com 8 threads ativas...")
    serve(app.server, host="0.0.0.0", port=8050, threads=8)