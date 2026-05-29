
# ==============================================================================
# REPOSITÓRIO DE ARQUITETURA DE DADOS - HISTÓRICO DE EVOLUÇÃO DO PIPELINE
# ==============================================================================
# # SCRIPT ANTIGO PARA REFERÊNCIA HISTÓRICA (ANTES DA REFATORAÇÃO)
#
# ⚠️ STATUS: RETIRADO DE PRODUÇÃO / DEPRECATED
#
# MOTIVOS DA SUBSTITUIÇÃO (ANÁLISE DE DIAGNÓSTICO TÉCNICO):
# 1. Explosão de Memória (Falta de Chunking): Tentava processar os 2,26 milhões 
#    de registros simultaneamente na memória RAM, gerando alto risco de OOM 
#    (Out of Memory) em servidores de produção.
# 2. Gargalo Crítico de CPU (.apply + lambda): A criação da coluna 'geom_wkt' 
#    usando df.apply(axis=1) forçava o Pandas a iterar linha por linha de forma
#    síncrona no Python, anulando a vetorização nativa do C/C++ e tornando o 
#    pipeline extremamente lento.
# 3. Vulnerabilidade a Strings Fantasmas: O método antigo de casting (.astype(str)) 
#    convertia valores nulos físicos (None) para a string literal "NONE" ou "NAN". 
#    Isso burlava o filtro de substituição do Pandas (.replace), fazendo com que 
#    registros sem informações (como o Registro ID 24) chegassem vazios ao banco.
# ==============================================================================

# NYCdata/scripts/2_nycdata_silver.py
import os
import sys
import urllib.parse
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from schemas import MAP_BRONZE_TO_SILVER, CollisionSilverSchema

# Importando o mapeamento limpo a partir do arquivo de schemas isolado
from schemas import MAP_BRONZE_TO_SILVER

# 1. Carrega as variáveis de ambiente
load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

if not all([DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
    print("❌ Erro: Variáveis de ambiente de conexão não encontradas no .env")
    sys.exit(1)

# Realiza o URL Encoding da senha para blindar caracteres especiais
senha_encriptada = urllib.parse.quote_plus(DB_PASS)
DATABASE_URL = f"postgresql://{DB_USER}:{senha_encriptada}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Cria a engine de conexão com o banco de dados Postgres (Docker)
engine = create_engine(DATABASE_URL)

print("⚡ Conexão com o banco de dados configurada com sucesso!")
print(f"📋 Mapeamento de colunas carregado de 'schemas.py'. Total de colunas: {len(MAP_BRONZE_TO_SILVER)}")

# ==============================================================================
# FASE 1: LEITURA DA BRONZE E HIGIENIZAÇÃO DE ESQUEMA (Renaming & Casting)
# ==============================================================================

print("\n📖 Iniciando a leitura dos dados da Camada Bronze...")

# Query para extrair os dados brutos da Bronze
query_bronze = "SELECT * FROM nycdata_vehicle_collisions_raw;"

# Lê a tabela inteira do Postgres para a memória do Python usando Pandas
df_raw = pd.read_sql_query(query_bronze, con=engine)
print(f"✅ Dados carregados com sucesso! Total de registros lidos: {len(df_raw):,}")

print("\n🔄 Aplicando a renomeação uniforme para o padrão internacional (EUA/Canadá)...")
# Executa a renomeação das colunas usando o mapeamento importado do 'schemas.py'
df_silver = df_raw.rename(columns=MAP_BRONZE_TO_SILVER)

print("🧪 Executando a tipagem estrita (Casting) e tratamento preliminar...")

# 1. Garantia do Código Postal (zip_code): Forçando tipo string limpa e tratando nulos
# Como descobrimos que o tamanho padrão é estável, removemos espaços e convertemos para string pura.
df_silver["zip_code"] = df_silver["zip_code"].astype(str).str.strip()

# O Pandas converte valores nulos (None) para a string 'nan' ao forçar o tipo .astype(str).
# Vamos normalizar isso substituindo 'nan' ou strings vazias pelo nosso literal padrão de mercado 'UNKNOWN'
df_silver["zip_code"] = df_silver["zip_code"].replace({"nan": "UNKNOWN", "": "UNKNOWN"})

print("✅ Fase 1 concluída com sucesso absoluto!")
print(f"📋 Colunas atuais no DataFrame Silver:\n{list(df_silver.columns)}")

# ==============================================================================
# FASE 2: ENGENHARIA DE ATRIBUTOS TEMPORAIS E FUSOS (Feature Engineering)
# ==============================================================================

print("\n📅 Iniciando a Fase 2: Unificação de Data/Hora e Padronização de Fusos...")

# 1. Combinar Data e Hora brutas em uma única string tratada
# Como 'raw_crash_date' pode vir com a parte de hora zerada (ex: 2020-01-01 00:00:00), 
# extraímos apenas os primeiros 10 caracteres (AAAA-MM-DD) e juntamos com a string de hora.
df_silver["timestamp_concat"] = (
    df_silver["raw_crash_date"].astype(str).str.slice(0, 10) + " " + df_silver["raw_crash_time"].astype(str).str.strip()
)

print("🌍 Aplicando a conversão de Timezone para UTC universal...")
# Convertemos para datetime. O parâmetro 'errors="coerce"' garante que horas malformadas virem NaT (nulos)
df_datetime = pd.to_datetime(df_silver["timestamp_concat"], errors="coerce")

# Atribuímos o fuso horário original de Nova York (tz_localize) e convertemos para UTC (tz_convert)
df_silver["crash_timestamp"] = df_datetime.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")

print("✂️ Extraindo colunas analíticas derivadas para o Dashboard...")
# Extração de componentes de tempo diretamente do vetor UTC
df_silver["crash_year"] = df_silver["crash_timestamp"].dt.year
df_silver["crash_month"] = df_silver["crash_timestamp"].dt.month
df_silver["crash_day_of_week"] = df_silver["crash_timestamp"].dt.dayofweek # Retorna de 0 (Segunda) a 6 (Domingo)

# Criando a classificação de Faixa Horária (Time Bucket) com base na hora UTC ajustada ou local
# Para o analista de BI, é melhor classificar com base na hora em que o acidente aconteceu em NY.
# Por isso, extraímos a hora local de NY para a regra de negócio:
hora_local = df_datetime.dt.hour

df_silver["time_bucket"] = pd.cut(
    hora_local,
    bins=[-1, 5, 11, 17, 23],
    labels=["Overnight", "Morning", "Afternoon", "Evening"],
    include_lowest=True
).astype(str).replace({"nan": "UNKNOWN"})

# Removemos a coluna temporária de concatenação para manter o DataFrame limpo
df_silver = df_silver.drop(columns=["timestamp_concat"])

print("✅ Fase 2 concluída! Atributos temporais gerados com sucesso.")
print(f"📊 Amostragem das novas colunas temporais:\n{df_silver[['crash_timestamp', 'crash_year', 'crash_month', 'crash_day_of_week', 'time_bucket']].head(3)}")

# ==============================================================================
# FASE 3: TRATAMENTO DE DADOS AUSENTES E CONSISTÊNCIA NUMÉRICA (Null Handling)
# ==============================================================================

print("\n🧹 Iniciando a Fase 3: Tratamento de Nulos e Padronização Textual em Lote...")

# --- GRUPO 1: Estatísticas de Vítimas (8 colunas) ---
# Identificamos estas colunas na auditoria do schema como 'double precision' (float) devido aos NaNs.
# Vamos substituir NaNs por 0 e convertê-las para INTEGER puro.
columns_victims = [
    "total_persons_injured", "total_persons_killed",
    "pedestrians_injured", "pedestrians_killed",
    "cyclists_injured", "cyclists_killed",
    "motorists_injured", "motorists_killed"
]

print("🔢 Tratando e convertendo colunas numéricas de vítimas para INTEGER...")
for col in columns_victims:
    if col in df_silver.columns:
        # Substitui nulos por 0 e força o tipo int64 do Pandas (será mapeado para INTEGER no Postgres)
        df_silver[col] = df_silver[col].fillna(0).astype('int64')

# --- GRUPO 2: Fatores Contribuintes e Tipos de Veículos (10 colunas) ---
# Vamos aplicar Caixa Alta (UPPERCASE), remover espaços (STRIP) e tratar nulos como 'UNSPECIFIED'
columns_categorical = [
    "contributing_factor_vehicle_1", "contributing_factor_vehicle_2",
    "contributing_factor_vehicle_3", "contributing_factor_vehicle_4",
    "contributing_factor_vehicle_5",
    "vehicle_type_code_1", "vehicle_type_code_2",
    "vehicle_type_code_3", "vehicle_type_code_4", "vehicle_type_code_5"
]

print("🔤 Aplicando UPPERCASE + TRIM e tratando nulos nas colunas categóricas...")
for col in columns_categorical:
    if col in df_silver.columns:
        # Garante o tipo string, aplica o strip para remover espaços invisíveis e joga para caixa alta
        df_silver[col] = df_silver[col].astype(str).str.strip().str.upper()
        # O Pandas converte nulos para 'NAN' ao forçar string. Substituímos pelo literal internacional
        df_silver[col] = df_silver[col].replace({"NAN": "UNSPECIFIED", "": "UNSPECIFIED"})

# --- GRUPO 3: Infraestrutura e Localização (Borough & Streets) ---
# Mesma regra de padronização textual, mas usando o literal 'UNKNOWN' para consistência analítica
columns_location = ["borough", "on_street_name", "off_street_name", "cross_street_name", "location_text"]

print("📍 Normalizando nomes de ruas e bairros (Borough / Streets)...")
for col in columns_location:
    if col in df_silver.columns:
        df_silver[col] = df_silver[col].astype(str).str.strip().str.upper()
        df_silver[col] = df_silver[col].replace({"NAN": "UNKNOWN", "": "UNKNOWN"})

print("✅ Fase 3 concluída! Dados ausentes tratados e integridade numérica restabelecida.")

# ==============================================================================
# FASE 4: CRIAÇÃO DA GEOMETRIA POSTGIS E FILTROS ESPACIAIS (Spatial Enrichment)
# ==============================================================================

print("\n🌍 Iniciando a Fase 4: Enriquecimento Espacial e Validação de Coordenadas...")

# 1. Copia as coordenadas brutas e garante a tipagem numérica (float)
df_silver["latitude"] = pd.to_numeric(df_silver["raw_latitude"], errors="coerce")
df_silver["longitude"] = pd.to_numeric(df_silver["raw_longitude"], errors="coerce")

# 2. Definindo os limites da Bounding Box oficial de New York City (NYC)
LON_MIN, LON_MAX = -74.259, -73.700
LAT_MIN, LAT_MAX = 40.477, 40.917

# Criamos uma máscara booleana para identificar coordenadas válidas dentro de NYC
valid_coords_mask = (
    (df_silver["longitude"] >= LON_MIN) & (df_silver["longitude"] <= LON_MAX) &
    (df_silver["latitude"] >= LAT_MIN) & (df_silver["latitude"] <= LAT_MAX)
)

print("🔍 Auditando telemetria de GPS e aplicando filtros de Bounding Box...")
# Contabilização para os logs do pipeline
total_linhas = len(df_silver)
total_validas = valid_coords_mask.sum()
total_invalidas = total_linhas - total_validas

print(f"   📍 Coordenadas geoespaciais válidas (Dentro de NYC): {total_validas:,} ({total_validas/total_linhas:.1%})")
print(f"   ⚠️ Coordenadas inválidas/zeradas (Fora de NYC ou Null): {total_invalidas:,} ({total_invalidas/total_linhas:.1%})")

# 3. Tratamento de anomalias espaciais
# Em vez de dropar as linhas (o que faria perder o histórico do acidente), mantemos o registro,
# mas limpamos as coordenadas inválidas para NULL (None) para não quebrar o PostGIS.
df_silver.loc[~valid_coords_mask, ["latitude", "longitude"]] = None

# 4. Preparação para o PostGIS
# O PostGIS cria geometrias de alta performance a partir de strings no formato WKT (Well-Known Text).
# Um ponto geométrico é representado estritamente por: 'POINT(longitude latitude)'
# Nota técnica crítica: Longitude vem SEMPRE primeiro na sintaxe WKT do Open Geospatial Consortium (OGC).
print("🧩 Construindo strings textuais no padrão WKT (Well-Known Text) para o PostGIS...")

df_silver["geom_wkt"] = df_silver.apply(
    lambda row: f"POINT({row['longitude']} {row['latitude']})" 
    if pd.notnull(row["longitude"]) and pd.notnull(row["latitude"]) 
    else None, 
    axis=1
)

print("✅ Fase 4 concluída! Camada de dados preparada para indexação geoespacial.")

# ==============================================================================
# FASE 5: METADADOS DE AUDITORIA E DEDUPLICAÇÃO FINA (Data Lineage & Deduplication)
# ==============================================================================

print("\n🛡️ Iniciando a Fase 5: Injeção de Metadados de Auditoria e Deduplicação...")

# 1. Injeção de Metadados de Linhagem (Lineage)
# Registramos o momento exato em que a linha está a ser consolidada na Silver
df_silver["silver_processed_at"] = pd.Timestamp.now(tz="UTC")
df_silver["pipeline_version"] = "v2.0.0"

print("🆔 Executando a deduplicação estrita baseada na Chave de Colisão (collision_id)...")
# Contabilização antes da limpeza
linhas_antes = len(df_silver)

# Passo de engenharia: Removemos IDs nulos que possam quebrar a chave primária
df_silver = df_silver.dropna(subset=["collision_id"])

# Aplicamos a ordenação pelo timestamp do acidente para garantir que se houver registros repetidos,
# o mais recente no tempo seja o priorizado, emulando um particionamento ROW_NUMBER() do SQL.
df_silver = df_silver.sort_values(by=["collision_id", "crash_timestamp"], ascending=[True, False])

# Mantemos apenas o primeiro registro encontrado para cada ID único
df_silver = df_silver.drop_duplicates(subset=["collision_id"], keep="first")

linhas_depois = len(df_silver)
duplicados_removidos = linhas_antes - linhas_depois

print(f"   📊 Registros processados originalmente: {linhas_antes:,}")
print(f"   🧹 Duplicidades finas eliminadas: {duplicados_removidos:,}")
print(f"   🥇 Base Silver consolidada na memória: {linhas_depois:,} registros únicos.")

print("✅ Fase 5 concluída! O contrato de dados está sanitizado e pronto para o carregamento físico.")


# ==============================================================================
# FASE 6: CARREGAMENTO FÍSICO E CONVERSÃO POSTGIS (Load, Upsert & Indexing)
# ==============================================================================

print("\n🚀 Iniciando a Fase 6: Gravação e Conversão Espacial no Postgres...")

# 1. Definição da Estrutura da Tabela Definitiva Espacial (Silver)
create_table_query = """
CREATE TABLE IF NOT EXISTS nycdata_vehicle_collisions_cleaned (
    collision_id BIGINT PRIMARY KEY,
    crash_timestamp TIMESTAMP WITH TIME ZONE,
    crash_year INT,
    crash_month INT,
    crash_day_of_week INT,
    time_bucket VARCHAR(20),
    borough VARCHAR(50),
    zip_code VARCHAR(20),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    location_text TEXT,
    on_street_name TEXT,
    off_street_name TEXT,
    cross_street_name TEXT,
    total_persons_injured INT,
    total_persons_killed INT,
    pedestrians_injured INT,
    pedestrians_killed INT,
    cyclists_injured INT,
    cyclists_killed INT,
    motorists_injured INT,
    motorists_killed INT,
    contributing_factor_vehicle_1 TEXT,
    contributing_factor_vehicle_2 TEXT,
    contributing_factor_vehicle_3 TEXT,
    contributing_factor_vehicle_4 TEXT,
    contributing_factor_vehicle_5 TEXT,
    vehicle_type_code_1 TEXT,
    vehicle_type_code_2 TEXT,
    vehicle_type_code_3 TEXT,
    vehicle_type_code_4 TEXT,
    vehicle_type_code_5 TEXT,
    silver_processed_at TIMESTAMP WITH TIME ZONE,
    pipeline_version VARCHAR(20),
    geom GEOMETRY(Point, 4326) -- Tipo geométrico nativo do PostGIS
);
"""

with engine.begin() as conn:
    print("🏗️ Garantindo a existência da estrutura da tabela definitiva espacial...")
    conn.execute(text(create_table_query))

# 2. Carga Volátil na Camada de Staging
cols_to_drop = ["raw_crash_date", "raw_crash_time", "raw_latitude", "raw_longitude"]
df_staging = df_silver.drop(columns=cols_to_drop, errors="ignore")

print("⏳ Despejando dados higienizados na tabela de Staging...")
df_staging.to_sql(
    name="stg_nyc_cleaned_tmp",
    con=engine,
    if_exists="replace",
    index=False,
    chunksize=20000
)

# 3. Definição da Query de Upsert com Conversão Espacial (WKT para Geometria)
upsert_query = """
INSERT INTO nycdata_vehicle_collisions_cleaned (
    collision_id, crash_timestamp, crash_year, crash_month, crash_day_of_week, time_bucket,
    borough, zip_code, latitude, longitude, location_text, on_street_name, off_street_name, cross_street_name,
    total_persons_injured, total_persons_killed, pedestrians_injured, pedestrians_killed,
    cyclists_injured, cyclists_killed, motorists_injured, motorists_killed,
    contributing_factor_vehicle_1, contributing_factor_vehicle_2, contributing_factor_vehicle_3, contributing_factor_vehicle_4, contributing_factor_vehicle_5,
    vehicle_type_code_1, vehicle_type_code_2, vehicle_type_code_3, vehicle_type_code_4, vehicle_type_code_5,
    silver_processed_at, pipeline_version, geom
)
SELECT 
    collision_id, crash_timestamp, crash_year, crash_month, crash_day_of_week, time_bucket,
    borough, zip_code, latitude, longitude, location_text, on_street_name, off_street_name, cross_street_name,
    total_persons_injured, total_persons_killed, pedestrians_injured, pedestrians_killed,
    cyclists_injured, cyclists_killed, motorists_injured, motorists_killed,
    contributing_factor_vehicle_1, contributing_factor_vehicle_2, contributing_factor_vehicle_3, contributing_factor_vehicle_4, contributing_factor_vehicle_5,
    vehicle_type_code_1, vehicle_type_code_2, vehicle_type_code_3, vehicle_type_code_4, vehicle_type_code_5,
    silver_processed_at, pipeline_version,
    CASE 
        WHEN geom_wkt IS NOT NULL THEN ST_GeomFromText(geom_wkt, 4326)
        ELSE NULL 
    END AS geom
FROM stg_nyc_cleaned_tmp
ON CONFLICT (collision_id) DO UPDATE SET
    crash_timestamp = EXCLUDED.crash_timestamp,
    time_bucket = EXCLUDED.time_bucket,
    total_persons_injured = EXCLUDED.total_persons_injured,
    total_persons_killed = EXCLUDED.total_persons_killed,
    silver_processed_at = EXCLUDED.silver_processed_at,
    geom = EXCLUDED.geom;
"""

# 4. Definição das Queries de Otimização (Índices B-Tree e GiST)
index_queries = [
    "CREATE INDEX IF NOT EXISTS idx_nyc_cleaned_timestamp ON nycdata_vehicle_collisions_cleaned(crash_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_nyc_cleaned_year_month ON nycdata_vehicle_collisions_cleaned(crash_year, crash_month);",
    "CREATE INDEX IF NOT EXISTS idx_nyc_cleaned_spatial_gist ON nycdata_vehicle_collisions_cleaned USING GIST(geom);"
]

with engine.begin() as conn:
    print("🔄 Executando Upsert Atômico e traduzindo geometrias para o PostGIS...")
    conn.execute(text(upsert_query))
    
    print("⚡ Construindo índices estruturais B-Tree e índices espaciais GiST...")
    for idx_q in index_queries:
        conn.execute(text(idx_q))
        
    print("🧹 Limpando resquícios da camada de Staging...")
    conn.execute(text("DROP TABLE IF EXISTS stg_nyc_cleaned_tmp;"))

print("\n🏆 [SUCESSO ABSOLUTO] A Camada Silver foi completamente consolidada e indexada no PostGIS!")