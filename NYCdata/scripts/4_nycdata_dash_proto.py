'''
FLUXO LINEAR DO SCRIPT:

# ========================================================================================================
Configuração de Dados ➡️ Inicialização do Framework ➡️ Definição de Layout ➡️ Lógica Reativa (Callbacks).
# ========================================================================================================

'''

import os
import json
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.express as px
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# ==============================================================================
# 1. VARIÁVEIS DE AMBIENTE E CONFIGURAÇÃO DE CONEXÃO COM O BANCO DE DADOS
# ==============================================================================

dotenv_path = os.path.join("NYCdata", ".env")
load_dotenv(dotenv_path=dotenv_path)

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS") 
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

# ==============================================================================
# 2. FUNÇÕES DE CONSULTA & CARREGAMENTO DE ATIVOS GEOFÍSICOS
# ==============================================================================

# Carregamento global do GeoJSON para evitar leitura de disco a cada callback
geojson_path = os.path.join("NYCdata", "data", "geojson", "nyc_borough.geojson")
with open(geojson_path, "r", encoding="utf-8") as f:
    nyc_geojson = json.load(f)


def build_temporal_query(metric, granularity, borough_filter):
    """
    Gera a query SQL para a série temporal com base na métrica,
    granularidade (Anual/Mensal) e filtro de distrito selecionados.
    """
    if metric == "FATALITIES":
        metric_sql = "SUM(total_persons_killed) as volume"
    elif metric == "INVOLVED":
        metric_sql = """
            SUM(pedestrians_injured + pedestrians_killed + 
                cyclists_injured + cyclists_killed + 
                motorists_injured + motorists_killed) as volume
        """
    else:  # ACCIDENTS (Padrão)
        metric_sql = "COUNT(*) as volume"

    # ✅ CORREÇÃO: Alinhamento com a coluna canônica 'crash_timestamp' da Camada Silver
    if granularity == "MONTHLY":
        date_field = "DATE_TRUNC('month', crash_timestamp) as periodo"
        group_by_field = "DATE_TRUNC('month', crash_timestamp)"
    else:
        date_field = "crash_year as periodo"
        group_by_field = "crash_year"

    where_clauses = []
    params = {}
    
    if borough_filter != "ALL":
        where_clauses.append("borough = :borough")
        params["borough"] = borough_filter

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    query = f"""
        SELECT 
            {date_field},
            {metric_sql}
        FROM nycdata_vehicle_collisions_cleaned
        {where_sql}
        GROUP BY {group_by_field}
        ORDER BY periodo ASC;
    """
    return text(query), params


def build_spatial_query(metric):
    """
    Gera a query SQL para o mapa coroplético, agrupando o volume
    da métrica selecionada estritamente por distrito (borough).
    """
    if metric == "FATALITIES":
        metric_sql = "SUM(total_persons_killed) as volume"
    elif metric == "INVOLVED":
        metric_sql = """
            SUM(pedestrians_injured + pedestrians_killed + 
                cyclists_injured + cyclists_killed + 
                motorists_injured + motorists_killed) as volume
        """
    else:
        metric_sql = "COUNT(*) as volume"

    query = f"""
        SELECT 
            borough,
            {metric_sql}
        FROM nycdata_vehicle_collisions_cleaned
        WHERE borough IS NOT NULL 
          AND borough NOT IN ('UNSPECIFIED', 'UNKNOWN')
        GROUP BY borough;
    """
    return text(query)

# ==============================================================================
# 3. INICIALIZAÇÃO DO APP DASH E ARQUITETURA DO LAYOUT (PALETA ESCURA)
# ==============================================================================

# Inclusão da fonte 'Inter' através dos estilos externos do Google Fonts
app = dash.Dash(
    __name__, 
    external_stylesheets=[
        'https://codepen.io/chriddyp/pen/bWLwgP.css',
        'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap'
    ]
)
app.title = "🇺🇸 NYC Collisions Analytics - Portfólio sênior"

# Definição centralizada da paleta de cores para estilos inline
THEME_COLORS = {
    "background_main": "#041C32",
    "background_card": "#04293A",
    "border_accent": "#064663",
    "text_highlight": "#ECB365",
    "text_light": "#FFFFFF"
}

app.layout = html.Div(
    style={
        "backgroundColor": THEME_COLORS["background_main"], 
        "color": THEME_COLORS["text_light"],
        "padding": "30px", 
        "minHeight": "100vh",
        "fontFamily": "'Inter', sans-serif"
    }, 
    children=[
        
        # Cabeçalho Principal
        html.H1(
            "Historical Evolution and Severity of Accidents in NYC", 
            style={"textAlign": "center", "marginBottom": "5px", "fontWeight": "700", "color": THEME_COLORS["text_highlight"]}
        ),
        html.P(
            "Integrated geospatial and temporal analyses of accidents in New York.",
            style={"textAlign": "center", "color": "#8ea1b4", "marginBottom": "40px", "fontWeight": "400"}
        ),
        
        # Painel de Controle Superior (Filtros e Seletores Dinâmicos)
        html.Div(
            style={
                "backgroundColor": THEME_COLORS["background_card"],
                "padding": "20px",
                "borderRadius": "8px",
                "border": f"1px solid {THEME_COLORS['border_accent']}",
                "marginBottom": "25px",
                "fontFamily": "'Inter', sans-serif"
            },
            className="row",
            children=[
                # Seletor 1: Distrito (Dropdown)
                html.Div(className="four columns", children=[
                    html.Label("Boroughs:", style={"fontWeight": "600", "marginBottom": "8px", "color": THEME_COLORS["text_light"]}),
                    dcc.Dropdown(
                        id="dropdown-borough",
                        options=[
                            {"label": "All Boroughs", "value": "ALL"},
                            {"label": "Manhattan", "value": "MANHATTAN"},
                            {"label": "Brooklyn", "value": "BROOKLYN"},
                            {"label": "Queens", "value": "QUEENS"},
                            {"label": "Bronx", "value": "BRONX"},
                            {"label": "Staten Island", "value": "STATEN ISLAND"}
                        ],
                        value="ALL",
                        clearable=False,
                        style={"color": "#000000", "fontWeight": "500"}  
                    )
                ]),
                
                # Seletor 2: Foco da Análise (Dropdown antigo Métrica Principal)
                html.Div(className="four columns", children=[
                    html.Label("Indicators:", style={"fontWeight": "600", "marginBottom": "8px", "color": THEME_COLORS["text_light"]}),
                    dcc.Dropdown(
                        id="dropdown-metric",
                        options=[
                            {"label": "Total Accidents", "value": "ACCIDENTS"},
                            {"label": "Fatalities", "value": "FATALITIES"},
                            {"label": "Involved Persons (Injured/Killed)", "value": "INVOLVED"}
                        ],
                        value="ACCIDENTS",
                        clearable=False,
                        style={"color": "#000000", "fontWeight": "500"}
                    )
                ]),
                
                # Seletor 3: Agrupamento Temporal (Dropdown antigo Granularidade)
                html.Div(className="four columns", children=[
                    html.Label("Time Scale:", style={"fontWeight": "600", "marginBottom": "8px", "color": THEME_COLORS["text_light"]}),
                    dcc.Dropdown(
                        id="dropdown-granularity",
                        options=[
                            {"label": "Annual View (Consolidated)", "value": "YEARLY"},
                            {"label": "Monthly View (Seasonality)", "value": "MONTHLY"}
                        ],
                        value="YEARLY",
                        clearable=False,
                        style={"color": "#000000", "fontWeight": "500"}
                    )
                ])
            ]
        ),
        
        # Primeiro Bloco Visual: Mapa e Série Temporal lado a lado
        html.Div(className="row", children=[
            html.Div(className="six columns", children=[
                html.Div(
                    style={
                        "backgroundColor": THEME_COLORS["background_card"],
                        "padding": "15px", "borderRadius": "8px",
                        "border": f"1px solid {THEME_COLORS['border_accent']}"
                    },
                    children=[dcc.Graph(id="graph-map-choropleth")]
                )
            ]),
            html.Div(className="six columns", children=[
                html.Div(
                    style={
                        "backgroundColor": THEME_COLORS["background_card"],
                        "padding": "15px", "borderRadius": "8px",
                        "border": f"1px solid {THEME_COLORS['border_accent']}"
                    },
                    children=[dcc.Graph(id="graph-temporal-evolution")]
                )
            ])
        ]),
        
        html.Br(),
        
        # Segundo Bloco Visual: Fatores Contribuintes
        html.Div(className="row", children=[
            html.Div(className="twelve columns", children=[
                html.Div(
                    style={
                        "backgroundColor": THEME_COLORS["background_card"],
                        "padding": "15px", "borderRadius": "8px",
                        "border": f"1px solid {THEME_COLORS['border_accent']}"
                    },
                    children=[dcc.Graph(id="graph-contributing-factors")]
                )
            ])
        ])
    ]
)

# ==============================================================================
# 4. LÓGICA REATIVA DE CALLBACK (CROSS-FILTERING UNIFICADO)
# ==============================================================================

# Dicionário de Coordenadas de Câmera do Mapbox para Enquadramento Dinâmico
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
     Input("dropdown-granularity", "value")] 
)
def update_dashboard(selected_borough, selected_metric, selected_granularity):
    print(f"🔄 Executando State Cross-Filtering: {selected_borough} | {selected_metric} | {selected_granularity}")
    
    # Dicionário de mapeamento para alternância dinâmica de legendas e eixos
    METRIC_LABELS = {
        "ACCIDENTS": "Total Collisions",
        "FATALITIES": "Total Fatalities",
        "INVOLVED": "People Injured/Killed"
    }

    # 1. PROCESSAMENTO DA CAMADA DE DADOS VIA PUSHDOWN QUERIES
    query_temporal, params_temporal = build_temporal_query(selected_metric, selected_granularity, selected_borough)
    query_spatial = build_spatial_query(selected_metric)
    
    if selected_borough != "ALL":
        where_clause_factors = "WHERE borough = :borough"
    else:
        where_clause_factors = "WHERE 1=1"

    query_fatores = f"""
        SELECT 
            contributing_factor_vehicle_1 as fator,
            COUNT(*) as volume
        FROM nycdata_vehicle_collisions_cleaned
        {where_clause_factors}
        AND contributing_factor_vehicle_1 IS NOT NULL 
        AND contributing_factor_vehicle_1 NOT IN ('UNSPECIFIED', 'UNKNOWN')
        GROUP BY contributing_factor_vehicle_1
        ORDER BY volume DESC
        LIMIT 10;
    """

    with engine.connect() as conn:
        df_temporal = pd.read_sql_query(query_temporal, conn, params=params_temporal)
        df_spatial = pd.read_sql_query(query_spatial, conn, params={"borough": selected_borough})
        df_fatores = pd.read_sql_query(text(query_fatores), conn, params={"borough": selected_borough})

    # 2. CONSTRUÇÃO DO MAPA COROPLÉTICO COM AJUSTE DE CÂMERA E DESTAQUE VISUAL
    df_spatial["borough_map"] = df_spatial["borough"].str.title()
    
    # Regra de Destaque Condicional: Esmaece os bairros não selecionados
    if selected_borough != "ALL":
        df_spatial["color_volume"] = df_spatial.apply(
            lambda row: row["volume"] if row["borough"] == selected_borough else 0, axis=1
        )
    else:
        df_spatial["color_volume"] = df_spatial["volume"]
    
    # Extração das configurações de posicionamento de câmera mapeadas
    camera = BOROUGH_CAMERA.get(selected_borough, BOROUGH_CAMERA["ALL"])
    
    fig_map = px.choropleth_mapbox(
        df_spatial,
        geojson=nyc_geojson,
        locations="borough_map",
        featureidkey="properties.boroname",  
        color="color_volume",  
        color_continuous_scale=[[0, "#05354c"], [1, THEME_COLORS["text_highlight"]]],
        mapbox_style="carto-darkmatter",
        center=camera["center"],  
        zoom=camera["zoom"],      
        labels={"color_volume": METRIC_LABELS[selected_metric], "borough_map": "Borough"},  # ✅ Dinâmico
        title=f"Spatial Distribution by Borough ({METRIC_LABELS[selected_metric]})"         # ✅ Dinâmico
    )
    fig_map.update_layout(
        template="plotly_dark",
        margin={"r":0,"t":40,"l":0,"b":10},
        paper_bgcolor=THEME_COLORS["background_card"],
        plot_bgcolor=THEME_COLORS["background_card"]
    )
    # Adiciona uma borda sutil para delimitar os polígonos esmaecidos no fundo escuro
    fig_map.update_traces(marker_line_width=1, marker_line_color=THEME_COLORS["border_accent"])

    # 3. CONSTRUÇÃO DA SÉRIE TEMPORAL DINÂMICA
    fig_temporal = px.line(
        df_temporal, 
        x="periodo", 
        y="volume",
        labels={"periodo": "Timeline", "volume": METRIC_LABELS[selected_metric]},             # ✅ Dinâmico
        title=f"Time Evolution ({selected_granularity.title() if selected_granularity else ''})", # ✅ Deixa o título elegante (Yearly/Monthly)
        markers=(selected_granularity == "YEARLY")
    )
    fig_temporal.update_traces(line_color=THEME_COLORS["text_highlight"])
    fig_temporal.update_layout(
        template="plotly_dark",
        paper_bgcolor=THEME_COLORS["background_card"],
        plot_bgcolor=THEME_COLORS["background_card"],
        font=dict(family="'Inter', sans-serif")
    )

    # 4. CONSTRUÇÃO DOS FATORES CONTRIBUINTES
    fig_fatores = px.bar(
        df_fatores,
        x="volume",
        y="fator",
        orientation="h",
        labels={"volume": METRIC_LABELS[selected_metric], "fator": "Causal Factor"},  # ✅ Dinâmico
        title=f"Top 10 Contributing Factors in {selected_borough}",
        color="volume",
        color_continuous_scale=[[0, THEME_COLORS["border_accent"]], [1, THEME_COLORS["text_highlight"]]]
    )
    fig_fatores.update_layout(
        template="plotly_dark",
        yaxis={'categoryorder':'total ascending'},
        paper_bgcolor=THEME_COLORS["background_card"],
        plot_bgcolor=THEME_COLORS["background_card"],
        font=dict(family="'Inter', sans-serif")
    )

    return fig_map, fig_temporal, fig_fatores

# ==============================================================================
# 5. INICIALIZAÇÃO DO SERVIDOR LOCAL
# ==============================================================================

if __name__ == "__main__":
    app.run(debug=True, port=8050)