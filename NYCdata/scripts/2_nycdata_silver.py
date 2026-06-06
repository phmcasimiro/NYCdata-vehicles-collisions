# NYCdata/scripts/2_nycdata_silver.py
import os
import sys
import urllib.parse
import json
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import pandas as pd
from schemas import MAP_BRONZE_TO_SILVER, CollisionSilverSchema

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
df_silver["zip_code"] = df_silver["zip_code"].astype(str).str.strip()
df_silver["zip_code"] = df_silver["zip_code"].replace({"nan": "UNKNOWN", "": "UNKNOWN"})

print("✅ Fase 1 concluída com sucesso absoluto!")

# ==============================================================================
# FASE 2: ENGENHARIA DE ATRIBUTOS TEMPORAIS E FUSOS (Feature Engineering)
# ==============================================================================

print("\n📅 Iniciando a Fase 2: Unificação de Data/Hora e Padronização de Fusos...")

# 1. Combinar Data e Hora brutas em uma única string tratada
df_silver["timestamp_concat"] = (
    df_silver["raw_crash_date"].astype(str).str.slice(0, 10) + " " + df_silver["raw_crash_time"].astype(str).str.strip()
)

print("🌍 Aplicando a conversão de Timezone para UTC universal...")
df_datetime = pd.to_datetime(df_silver["timestamp_concat"], errors="coerce")

# Atribuímos o fuso horário original de Nova York (tz_localize) e convertemos para UTC (tz_convert)
df_silver["crash_timestamp"] = df_datetime.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")

print("✂️ Extraindo colunas analíticas derivadas para o Dashboard...")
df_silver["crash_year"] = df_silver["crash_timestamp"].dt.year
df_silver["crash_month"] = df_silver["crash_timestamp"].dt.month
df_silver["crash_day_of_week"] = df_silver["crash_timestamp"].dt.dayofweek 

# Classificação de Faixa Horária (Time Bucket) com base na hora local de NY
hora_local = df_datetime.dt.hour
df_silver["time_bucket"] = pd.cut(
    hora_local,
    bins=[-1, 5, 11, 17, 23],
    labels=["Overnight", "Morning", "Afternoon", "Evening"],
    include_lowest=True
).astype(str).replace({"nan": "UNKNOWN"})

# Removemos a coluna temporária de concatenação
df_silver = df_silver.drop(columns=["timestamp_concat"])

print("✅ Fase 2 concluída! Atributos temporais gerados com sucesso.")

# ==============================================================================
# FASES 3, 4, 5 & GOVERNANÇA: CONTRATO DE DADOS E VALIDAÇÃO ESTRITA (Pydantic + DLQ)
# ==============================================================================

print("\n🛡️ Iniciando a validação em lote do Contrato de Dados (Pydantic + Chunking + Bounding Box)...")

# 1. Alinhamento inicial de coordenadas geográficas
df_silver["latitude"] = pd.to_numeric(df_silver["raw_latitude"], errors="coerce")
df_silver["longitude"] = pd.to_numeric(df_silver["raw_longitude"], errors="coerce")

# 2. Configuração de fatiamento para controle de memória (Chunking)
CHUNK_SIZE = 100000
total_linhas = len(df_silver)
validated_records = []
rejections_list = []  # Inicializa o buffer da Dead Letter Queue
errors_count = 0

# Limites Oficiais da Bounding Box de NYC
LON_MIN, LON_MAX = -74.259, -73.700
LAT_MIN, LAT_MAX = 40.477, 40.917

print(f"🧪 Submetendo {total_linhas:,} registros ao crivo do CollisionSilverSchema em blocos de {CHUNK_SIZE:,}...")

for i in range(0, total_linhas, CHUNK_SIZE):
    # Extrai o pedaço isolado de linhas para processamento
    df_chunk = df_silver.iloc[i : i + CHUNK_SIZE].copy()
    
    # Aplica a regra de qualidade espacial da Bounding Box a nível de bloco (Alta Performance)
    valid_coords_mask = (
        (df_chunk["longitude"] >= LON_MIN) & (df_chunk["longitude"] <= LON_MAX) &
        (df_chunk["latitude"] >= LAT_MIN) & (df_chunk["latitude"] <= LAT_MAX)
    )
    df_chunk.loc[~valid_coords_mask, ["latitude", "longitude"]] = None
    
    # Converte apenas o bloco atual para dicionários
    chunk_records = df_chunk.to_dict(orient="records")
    
    for record in chunk_records:
        try:
            # Passa os dados pelo Pydantic (Aplica as regras higienizadas do schemas.py)
            validated_obj = CollisionSilverSchema(**record)
            val_dict = validated_obj.model_dump()
            
            # Reconstrói dinamicamente a string WKT exigida pelo PostGIS na Fase 6
            if val_dict.get("longitude") is not None and val_dict.get("latitude") is not None:
                val_dict["geom_wkt"] = f"POINT({val_dict['longitude']} {val_dict['latitude']})"
            else:
                val_dict["geom_wkt"] = None
                
            validated_records.append(val_dict)
        except Exception as e:
            errors_count += 1
            if errors_count <= 5:
                print(f"⚠️ Registro rejeitado pelo contrato: ID {record.get('collision_id')} - Erro: {e}")
            
            # Captura e preserva a linhagem da falha sem quebrar o laço (DLQ)
            rejections_list.append({
                "collision_id": record.get("collision_id"),
                "rejection_reason": str(e),
                "rejected_at": pd.Timestamp.now(tz="UTC"),
                "pipeline_version": "v2.0.0",
                "raw_payload": str(record)  # Serializa o dicionário problemático como string TEXT
            })

print(f"📊 Relatório de Auditoria de Qualidade Pydantic:")
print(f"   ✅ Registros em conformidade total com o contrato: {len(validated_records):,}")
print(f"   ❌ Registros corrompidos/enviados para a DLQ: {errors_count:,}")

# 3. Reconstrói o DataFrame principal e injeta de forma vetorizada os metadados de auditoria
df_silver = pd.DataFrame(validated_records)
if not df_silver.empty:
    df_silver["silver_processed_at"] = pd.Timestamp.now(tz="UTC")
    df_silver["pipeline_version"] = "v2.0.0"

df_rejections = pd.DataFrame(rejections_list)  # Criação do DataFrame de erros

# 4. Deduplicação Fina Analítica por Chave Primária
print("🆔 Executando a deduplicação analítica fina por 'collision_id'...")
if not df_silver.empty:
    df_silver = df_silver.sort_values(by=["collision_id", "crash_timestamp"], ascending=[True, False])
    df_silver = df_silver.drop_duplicates(subset=["collision_id"], keep="first")

print("✅ Governança, higienização profunda e volumetria espacial validadas com sucesso!")

# ==============================================================================
# FASE 6: CARREGAMENTO FÍSICO E CONVERSÃO POSTGIS (Load, Upsert & Indexing)
# ==============================================================================

print("\n🚀 Iniciando a Fase 6: Gravação, Gravação da DLQ e Conversão Espacial no Postgres...")

# 1. DDL Completa da Tabela Definitiva Limpa (Silver)
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
    geom GEOMETRY(Point, 4326) 
);
"""

# 2. DDL da Tabela da Dead Letter Queue (DLQ / Rejeições)
create_dlq_table_query = """
CREATE TABLE IF NOT EXISTS nycdata_vehicle_collisions_rejections (
    id SERIAL PRIMARY KEY,
    collision_id BIGINT,
    rejection_reason TEXT,
    rejected_at TIMESTAMP WITH TIME ZONE,
    pipeline_version VARCHAR(20),
    raw_payload TEXT
);
"""

with engine.begin() as conn:
    print("🏗️ Garantindo a existência das estruturas das tabelas definitiva e DLQ...")
    conn.execute(text(create_table_query))
    conn.execute(text(create_dlq_table_query))

# 3. Gravação Física dos Dados Rejeitados na DLQ (Se houver rejeições)
if not df_rejections.empty:
    print(f"📉 Despejando {len(df_rejections):,} registros corrompidos na tabela de DLQ...")
    df_rejections.to_sql(
        name="nycdata_vehicle_collisions_rejections",
        con=engine,
        if_exists="append",  # Acumula o histórico de erros de múltiplas cargas
        index=False,
        chunksize=10000
    )
else:
    print("🎉 Excelente: Nenhum registro foi rejeitado nesta carga.")

# 4. Carga Volátil na Camada de Staging
if not df_silver.empty:
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

    # 5. Definição do Upsert Atômico Completo
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

print("\n🏆 [SUCESSO ABSOLUTO] A Camada Silver e a DLQ foram completamente consolidadas e indexadas!")

# ==============================================================================
# ESTÁGIO DE AUDITORIA: MANIFESTO DE ESTADO PARA O DVC (PONTE DE GOVERNANÇA)
# ==============================================================================

print("\n📝 Gerando o Manifesto de Estado da Camada Silver para o DVC...")

metadata_dir = "NYCdata/metadata"
os.makedirs(metadata_dir, exist_ok=True)

manifesto_silver = {
    "layer": "silver",
    "pipeline_version": "v2.0.0",
    "timestamp_execution": pd.Timestamp.now(tz="UTC").isoformat(),
    "metrics": {
        "total_records_processed": int(total_linhas),
        "total_records_approved": int(len(df_silver)),
        "total_records_rejected_dlq": int(errors_count)
    }
}

manifesto_path = os.path.join(metadata_dir, "silver_status.json")
with open(manifesto_path, "w", encoding="utf-8") as f:
    json.dump(manifesto_silver, f, indent=4, ensure_ascii=False)

print(f"💾 Manifesto de estado guardado com sucesso em: {manifesto_path}")