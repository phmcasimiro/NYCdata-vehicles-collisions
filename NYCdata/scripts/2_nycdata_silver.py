# NYCdata/scripts/2_nycdata_silver.py
import os
import sys
import time
import urllib.parse
import json
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import pandas as pd
from schemas import MAP_BRONZE_TO_SILVER, CollisionSilverSchema

# Configuração de Logging Estruturado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("NYCdata/metadata/pipeline.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("GeoDevSilver")

# 1. Carrega as variáveis de ambiente
load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

if not all([DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
    logger.error("❌ Erro: Variáveis de ambiente de conexão não encontradas no .env")
    sys.exit(1)

# Realiza o URL Encoding da senha para blindar caracteres especiais
senha_encriptada = urllib.parse.quote_plus(DB_PASS)
DATABASE_URL = f"postgresql://{DB_USER}:{senha_encriptada}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Cria a engine de conexão com o banco de dados Postgres (Docker)
engine = create_engine(DATABASE_URL)

# Caminho do manifesto de estado da Silver
METADATA_DIR = "NYCdata/metadata"
SILVER_STATUS_PATH = os.path.join(METADATA_DIR, "silver_status.json")

logger.info("⚡ Conexão com o banco de dados configurada com sucesso!")
logger.info(f"📋 Mapeamento de colunas carregado de 'schemas.py'. Total de colunas: {len(MAP_BRONZE_TO_SILVER)}")


# ==============================================================================
# FUNÇÕES DE WATERMARKING E DEDUPLICAÇÃO
# ==============================================================================

def obter_watermark_silver():
    """Lê o token temporal da última execução bem-sucedida da Silver a partir do manifesto JSON."""
    if not os.path.exists(SILVER_STATUS_PATH):
        logger.info("ℹ️ Manifesto silver_status.json não encontrado. Será executada uma carga completa inicial.")
        return None

    try:
        with open(SILVER_STATUS_PATH, "r", encoding="utf-8") as f:
            status_data = json.load(f)
        
        token = status_data.get("last_bronze_watermark")
        if token:
            logger.info(f"🔍 Watermark Silver encontrado: {token}")
            return token
        else:
            logger.info("ℹ️ Campo 'last_bronze_watermark' ausente no manifesto. Será executada uma carga completa.")
            return None
    except Exception as e:
        logger.warning(f"⚠️ Erro ao ler silver_status.json: {e}. Será executada uma carga completa.")
        return None


def deduplicar_dlq_se_necessario(engine_banco):
    """Executa a deduplicação cirúrgica da DLQ uma única vez, protegida por flag no manifesto."""
    # Verifica se a deduplicação já foi realizada
    if os.path.exists(SILVER_STATUS_PATH):
        try:
            with open(SILVER_STATUS_PATH, "r", encoding="utf-8") as f:
                status_data = json.load(f)
            if status_data.get("dlq_deduplicated") is True:
                logger.info("✅ DLQ já deduplicada anteriormente. Pulando etapa.")
                return
        except Exception:
            pass  # Se não conseguir ler, executa a deduplicação por segurança

    logger.info("🧹 Iniciando deduplicação da DLQ (execução única)...")

    try:
        with engine_banco.connect() as conexao:
            # Conta registros antes
            count_antes = conexao.execute(
                text("SELECT COUNT(*) FROM nycdata_vehicle_collisions_rejections;")
            ).scalar() or 0

            if count_antes == 0:
                logger.info("ℹ️ DLQ vazia. Nada a deduplicar.")
                _registrar_flag_dlq_deduplicada()
                return

            # Deduplicação: mantém apenas o registro mais recente por collision_id
            conexao.execute(text("""
                DELETE FROM nycdata_vehicle_collisions_rejections
                WHERE id NOT IN (
                    SELECT DISTINCT ON (collision_id) id
                    FROM nycdata_vehicle_collisions_rejections
                    ORDER BY collision_id, rejected_at DESC
                );
            """))
            conexao.commit()

            # Conta registros depois
            count_depois = conexao.execute(
                text("SELECT COUNT(*) FROM nycdata_vehicle_collisions_rejections;")
            ).scalar() or 0

            removidos = count_antes - count_depois
            logger.info(f"🧹 Deduplicação da DLQ concluída: {removidos:,} registros duplicados removidos ({count_antes:,} → {count_depois:,}).")

    except Exception as e:
        logger.error(f"❌ Erro durante a deduplicação da DLQ: {e}")
        raise

    # Registra a flag para nunca mais repetir
    _registrar_flag_dlq_deduplicada()


def _registrar_flag_dlq_deduplicada():
    """Registra no silver_status.json que a deduplicação foi realizada."""
    status_data = {}
    if os.path.exists(SILVER_STATUS_PATH):
        try:
            with open(SILVER_STATUS_PATH, "r", encoding="utf-8") as f:
                status_data = json.load(f)
        except Exception:
            pass
    
    status_data["dlq_deduplicated"] = True
    
    os.makedirs(METADATA_DIR, exist_ok=True)
    with open(SILVER_STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=4, ensure_ascii=False)
    
    logger.info("📝 Flag 'dlq_deduplicated' registrada no silver_status.json.")


# ==============================================================================
# FASE 0: DEDUPLICAÇÃO DA DLQ (MIGRAÇÃO ÚNICA)
# ==============================================================================

deduplicar_dlq_se_necessario(engine)

# ==============================================================================
# FASE 1: LEITURA INCREMENTAL DA BRONZE (Watermarking Dinâmico)
# ==============================================================================

start_time = time.time()

logger.info("📖 Iniciando a leitura dos dados da Camada Bronze...")

# Obtém o token de watermark da Silver
watermark_token = obter_watermark_silver()

# Monta a query de leitura DELTA ou COMPLETA
if watermark_token is not None:
    query_bronze = text("""
        SELECT * FROM nycdata_vehicle_collisions_raw 
        WHERE bronze_inserted_at > :last_token
        ORDER BY collision_id;
    """)
    logger.info(f"📖 Leitura incremental: buscando registros com bronze_inserted_at > '{watermark_token}'")
    df_raw = pd.read_sql_query(query_bronze, con=engine, params={"last_token": watermark_token})
else:
    query_bronze = "SELECT * FROM nycdata_vehicle_collisions_raw ORDER BY collision_id;"
    logger.info("📖 Leitura completa da Bronze (carga inicial)...")
    df_raw = pd.read_sql_query(query_bronze, con=engine)

logger.info(f"📊 Total de registros lidos da Bronze: {len(df_raw):,}")

# ==============================================================================
# ENCERRAMENTO GRACIOSO: DELTA VAZIO
# ==============================================================================

if len(df_raw) == 0:
    duracao = (time.time() - start_time)
    logger.info(f"🏁 Nenhum dado novo para processar. Pipeline Silver encerrado graciosamente em {duracao:.1f} segundos.")
    
    # Obtém o watermark atual da Bronze para manter no manifesto
    with engine.connect() as conn:
        max_inserted_at = conn.execute(
            text("SELECT MAX(bronze_inserted_at) FROM nycdata_vehicle_collisions_raw;")
        ).scalar()
    
    # Grava manifesto mesmo com delta vazio para manter consistência DVC
    manifesto_silver = {
        "layer": "silver",
        "pipeline_version": "v3.0.0",
        "timestamp_execution": pd.Timestamp.now(tz="UTC").isoformat(),
        "last_bronze_watermark": max_inserted_at.isoformat() if max_inserted_at else watermark_token,
        "dlq_deduplicated": True,
        "metrics": {
            "total_records_processed": 0,
            "total_records_approved": 0,
            "total_records_rejected_dlq": 0
        }
    }
    os.makedirs(METADATA_DIR, exist_ok=True)
    with open(SILVER_STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(manifesto_silver, f, indent=4, ensure_ascii=False)
    
    logger.info(f"💾 Manifesto de estado (delta vazio) guardado em: {SILVER_STATUS_PATH}")
    sys.exit(0)

# ==============================================================================
# FASE 2: HIGIENIZAÇÃO DE ESQUEMA (Renaming & Casting)
# ==============================================================================

logger.info("🔄 Aplicando a renomeação uniforme para o padrão internacional (EUA/Canadá)...")
# Executa a renomeação das colunas usando o mapeamento importado do 'schemas.py'
df_silver = df_raw.rename(columns=MAP_BRONZE_TO_SILVER)

logger.info("🧪 Executando a tipagem estrita (Casting) e tratamento preliminar...")

# 1. Garantia do Código Postal (zip_code): Forçando tipo string limpa e tratando nulos
df_silver["zip_code"] = df_silver["zip_code"].astype(str).str.strip()
df_silver["zip_code"] = df_silver["zip_code"].replace({"nan": "UNKNOWN", "": "UNKNOWN"})

logger.info("✅ Fase de renomeação e casting concluída com sucesso!")

# ==============================================================================
# FASE 3: ENGENHARIA DE ATRIBUTOS TEMPORAIS E FUSOS (Feature Engineering)
# ==============================================================================

logger.info("📅 Iniciando a Fase 3: Unificação de Data/Hora e Padronização de Fusos...")

# 1. Combinar Data e Hora brutas em uma única string tratada
df_silver["timestamp_concat"] = (
    df_silver["raw_crash_date"].astype(str).str.slice(0, 10) + " " + df_silver["raw_crash_time"].astype(str).str.strip()
)

logger.info("🌍 Aplicando a conversão de Timezone para UTC universal...")
df_datetime = pd.to_datetime(df_silver["timestamp_concat"], errors="coerce")

# Atribuímos o fuso horário original de Nova York (tz_localize) e convertemos para UTC (tz_convert)
df_silver["crash_timestamp"] = df_datetime.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")

logger.info("✂️ Extraindo colunas analíticas derivadas para o Dashboard...")
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

logger.info("✅ Fase 3 concluída! Atributos temporais gerados com sucesso.")

# ==============================================================================
# FASES 4 & 5: CONTRATO DE DADOS E VALIDAÇÃO ESTRITA (Pydantic + DLQ)
# ==============================================================================

logger.info("🛡️ Iniciando a validação em lote do Contrato de Dados (Pydantic + Chunking + Bounding Box)...")

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

logger.info(f"🧪 Submetendo {total_linhas:,} registros ao crivo do CollisionSilverSchema em blocos de {CHUNK_SIZE:,}...")

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
                logger.warning(f"⚠️ Registro rejeitado pelo contrato: ID {record.get('collision_id')} - Erro: {e}")
            
            # Captura e preserva a linhagem da falha sem quebrar o laço (DLQ)
            rejections_list.append({
                "collision_id": record.get("collision_id"),
                "rejection_reason": str(e),
                "rejected_at": pd.Timestamp.now(tz="UTC"),
                "pipeline_version": "v3.0.0",
                "raw_payload": str(record)  # Serializa o dicionário problemático como string TEXT
            })

logger.info("📊 Relatório de Auditoria de Qualidade Pydantic:")
logger.info(f"   ✅ Registros em conformidade total com o contrato: {len(validated_records):,}")
logger.info(f"   ❌ Registros corrompidos/enviados para a DLQ: {errors_count:,}")

# 3. Reconstrói o DataFrame principal e injeta de forma vetorizada os metadados de auditoria
df_silver = pd.DataFrame(validated_records)
if not df_silver.empty:
    df_silver["silver_processed_at"] = pd.Timestamp.now(tz="UTC")
    df_silver["pipeline_version"] = "v3.0.0"

df_rejections = pd.DataFrame(rejections_list)  # Criação do DataFrame de erros

# 4. Deduplicação Fina Analítica por Chave Primária
logger.info("🆔 Executando a deduplicação analítica fina por 'collision_id'...")
if not df_silver.empty:
    df_silver = df_silver.sort_values(by=["collision_id", "crash_timestamp"], ascending=[True, False])
    df_silver = df_silver.drop_duplicates(subset=["collision_id"], keep="first")

logger.info("✅ Governança, higienização profunda e volumetria espacial validadas com sucesso!")

# ==============================================================================
# FASE 6: CARREGAMENTO FÍSICO E CONVERSÃO POSTGIS (Load, Upsert & Indexing)
# ==============================================================================

logger.info("🚀 Iniciando a Fase 6: Gravação, Gravação da DLQ e Conversão Espacial no Postgres...")

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
    collision_id BIGINT UNIQUE,
    rejection_reason TEXT,
    rejected_at TIMESTAMP WITH TIME ZONE,
    pipeline_version VARCHAR(20),
    raw_payload TEXT
);
"""

with engine.begin() as conn:
    logger.info("🏗️ Garantindo a existência das estruturas das tabelas definitiva e DLQ...")
    conn.execute(text(create_table_query))
    conn.execute(text(create_dlq_table_query))

# ==============================================================================
# 3. GRAVAÇÃO FÍSICA DOS DADOS REJEITADOS NA DLQ (UPSERT IDEMPOTENTE)
# ==============================================================================
if not df_rejections.empty:
    logger.info(f"📉 Despejando {len(df_rejections):,} registros corrompidos na DLQ via Upsert de segurança...")
    
    # Remove duplicatas internas do próprio lote em memória para otimizar o I/O
    df_rejections = df_rejections.drop_duplicates(subset=["collision_id"], keep="first")
    
    NOM_STAGING_DLQ = "stg_nyc_rejections_tmp"
    
    # 1. Desagregando o lote em uma tabela volátil de staging
    df_rejections.to_sql(
        name=NOM_STAGING_DLQ,
        con=engine,
        if_exists="replace",
        index=False,
        chunksize=10000
    )
    
    # 2. Executa o merge atômico: se o ID já foi rejeitado no passado, ignora (DO NOTHING)
    upsert_dlq_query = f"""
    INSERT INTO nycdata_vehicle_collisions_rejections (
        collision_id, rejection_reason, rejected_at, pipeline_version, raw_payload
    )
    SELECT 
        collision_id, rejection_reason, rejected_at, pipeline_version, raw_payload
    FROM {NOM_STAGING_DLQ}
    ON CONFLICT (collision_id) DO NOTHING;
    """
    
    with engine.begin() as conn:
        conn.execute(text(upsert_dlq_query))
        conn.execute(text(f"DROP TABLE IF EXISTS {NOM_STAGING_DLQ};"))
        
    logger.info("✅ Gravação idempotente na DLQ concluída com sucesso absoluto!")
else:
    logger.info("🎉 Excelente: Nenhum registro foi rejeitado nesta carga.")

# 4. Carga Volátil na Camada de Staging
if not df_silver.empty:
    cols_to_drop = ["raw_crash_date", "raw_crash_time", "raw_latitude", "raw_longitude"]
    df_staging = df_silver.drop(columns=cols_to_drop, errors="ignore")

    logger.info("⏳ Despejando dados higienizados na tabela de Staging...")
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
        logger.info("🔄 Executando Upsert Atômico e traduzindo geometrias para o PostGIS...")
        conn.execute(text(upsert_query))
        
        logger.info("⚡ Construindo índices estruturais B-Tree e índices espaciais GiST...")
        for idx_q in index_queries:
            conn.execute(text(idx_q))
            
        logger.info("🧹 Limpando resquícios da camada de Staging...")
        conn.execute(text("DROP TABLE IF EXISTS stg_nyc_cleaned_tmp;"))

logger.info("🏆 [SUCESSO ABSOLUTO] A Camada Silver e a DLQ foram completamente consolidadas e indexadas!")

# ==============================================================================
# ESTÁGIO DE AUDITORIA: MANIFESTO DE ESTADO PARA O DVC (PONTE DE GOVERNANÇA)
# ==============================================================================

logger.info("📝 Gerando o Manifesto de Estado da Camada Silver para o DVC...")

# Obtém o watermark atualizado: MAX(bronze_inserted_at) da tabela Bronze
with engine.connect() as conn:
    max_bronze_inserted_at = conn.execute(
        text("SELECT MAX(bronze_inserted_at) FROM nycdata_vehicle_collisions_raw;")
    ).scalar()

os.makedirs(METADATA_DIR, exist_ok=True)

manifesto_silver = {
    "layer": "silver",
    "pipeline_version": "v3.0.0",
    "timestamp_execution": pd.Timestamp.now(tz="UTC").isoformat(),
    "last_bronze_watermark": max_bronze_inserted_at.isoformat() if max_bronze_inserted_at else None,
    "dlq_deduplicated": True,
    "metrics": {
        "total_records_processed": int(total_linhas),
        "total_records_approved": int(len(df_silver)),
        "total_records_rejected_dlq": int(errors_count)
    }
}

with open(SILVER_STATUS_PATH, "w", encoding="utf-8") as f:
    json.dump(manifesto_silver, f, indent=4, ensure_ascii=False)

duracao = (time.time() - start_time)
logger.info(f"💾 Manifesto de estado guardado com sucesso em: {SILVER_STATUS_PATH}")
logger.info(f"⏱️ Tempo total de processamento da Silver: {duracao:.1f} segundos.")