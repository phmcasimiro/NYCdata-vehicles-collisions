import os
import time
from datetime import datetime
import logging
import json
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus, urlencode

# Configuração de Logging Estruturado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("NYCdata/metadata/pipeline.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("GeoDevETL")

# Carrega as variáveis contidas no arquivo .env para a memória
load_dotenv()

# --- Configurações de Ambiente Seguras ---
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
TABELA_DESTINO = "nycdata_vehicle_collisions_raw"
TABELA_STAGING = "stg_nyc_collisions_tmp"

# URL Base da API SODA 2 que retorna dados formatados em CSV
API_URL_BASE = "https://data.cityofnewyork.us/resource/h9gi-nx95.csv"

# Validação preventiva do arquivo .env
if not all([DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
    raise ValueError("❌ Erro crítico: Variáveis de ambiente de banco de dados não foram carregadas do arquivo .env")

# --- Proteção de Caracteres Especiais na Senha ---
SENHA_TRATADA = quote_plus(DB_PASS)
DATABASE_URL = f"postgresql://{DB_USER}:{SENHA_TRATADA}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

# Mapeamento estrito para evitar inferências erradas ou quebras por valores nulos (NA)
dtype_mapeamento = {
    "zip_code": str,
    "off_street_name": str,
    "on_street_name": str,
    "cross_street_name": str,
    "borough": str,
    "number_of_persons_injured": float,
    "number_of_persons_killed": float,
    "number_of_pedestrians_injured": float,
    "number_of_pedestrians_killed": float,
    "number_of_cyclist_injured": float,
    "number_of_cyclist_killed": float,
    "number_of_motorist_injured": float,
    "number_of_motorist_killed": float
}


def migrar_schema_bronze(engine_banco, nome_tabela):
    """Adiciona a coluna de auditoria temporal bronze_inserted_at se ainda não existir (idempotente)."""
    with engine_banco.connect() as conexao:
        # Verifica se a tabela existe antes de tentar alterar
        query_tabela_existe = f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = '{nome_tabela}'
            );
        """
        tabela_existe = conexao.execute(text(query_tabela_existe)).scalar()

        if tabela_existe:
            logger.info("🔧 Verificando coluna de auditoria 'bronze_inserted_at'...")
            conexao.execute(text(f"""
                ALTER TABLE "{nome_tabela}" 
                ADD COLUMN IF NOT EXISTS bronze_inserted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
            """))
            conexao.commit()
            logger.info("✅ Coluna 'bronze_inserted_at' garantida na tabela Bronze.")
        else:
            logger.info("ℹ️ Tabela ainda não existe. A coluna será criada junto com a estrutura na primeira carga.")


def criar_constraints_se_nao_existirem(engine_banco, nome_tabela, df_modelo):
    """Garante que a tabela exista com o schema completo e possua a constraint de UNIQUE no collision_id."""
    with engine_banco.connect() as conexao:
        query_tabela_existe = f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = '{nome_tabela}'
            );
        """
        tabela_existe = conexao.execute(text(query_tabela_existe)).scalar()
        
        if not tabela_existe:
            logger.info(f"🛠️ Tabela '{nome_tabela}' não encontrada. Criando estrutura baseada no schema da API...")
            df_modelo.head(0).to_sql(
                name=nome_tabela,
                con=engine_banco,
                if_exists="append",
                index=False
            )
            conexao.commit()
            # Adiciona a coluna de auditoria imediatamente após a criação da tabela
            conexao.execute(text(f"""
                ALTER TABLE "{nome_tabela}" 
                ADD COLUMN IF NOT EXISTS bronze_inserted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
            """))
            conexao.commit()

        query_verificar_constraint = f"""
            SELECT COUNT(*) 
            FROM pg_indexes 
            WHERE tablename = '{nome_tabela}' AND indexname = '{nome_tabela}_collision_id_key';
        """
        existe_idx = conexao.execute(text(query_verificar_constraint)).scalar()
        
        if existe_idx == 0:
            logger.info(f"🛠️ Aplicando restrição UNIQUE na coluna 'collision_id' da tabela '{nome_tabela}'...")
            try:
                conexao.execute(text(f'ALTER TABLE "{nome_tabela}" ADD CONSTRAINT "{nome_tabela}_collision_id_key" UNIQUE (collision_id);'))
                conexao.commit()
            except Exception as e:
                logger.warning(f"⚠️ Nota ao aplicar a constraint: {e}")


def obter_watermark_bronze(engine_banco, nome_tabela):
    """Consulta o banco para descobrir a data do acidente mais recente já ingerido (Watermark Dinâmico)."""
    try:
        query = f'SELECT MAX(crash_date) FROM "{nome_tabela}";'
        with engine_banco.connect() as conexao:
            resultado = conexao.execute(text(query)).scalar()
            if resultado is not None:
                # Converte para string ISO formatada para a API SODA
                if isinstance(resultado, str):
                    return resultado
                return resultado.strftime("%Y-%m-%dT%H:%M:%S")
            return None
    except Exception:
        return None


def extrair_bloco_com_retry(url, bloco_num, max_retries=3):
    """Executa a leitura do bloco aplicando resiliência de rede e fallback estratégico de engine de parse."""
    retry_count = 0
    while retry_count < max_retries:
        try:
            if retry_count == 0:
                df = pd.read_csv(url, engine="pyarrow", dtype=dtype_mapeamento)
            else:
                logger.info("🔄 Aplicando estratégia de Fallback: Usando motor padrão com descarte de linhas malformadas...")
                df = pd.read_csv(url, engine="c", dtype=dtype_mapeamento, on_bad_lines="skip")
            return df
        except Exception as e:
            retry_count += 1
            wait_time = retry_count * 5  
            logger.warning(f"⚠️ Falha observada no Bloco #{bloco_num} (Tentativa {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                logger.info(f"⏳ Aguardando {wait_time} segundos para tentar novamente...")
                time.sleep(wait_time)
            else:
                raise RuntimeError(f"❌ Erro crítico: O bloco #{bloco_num} falhou persistentemente.")


def consolidar_dados_upsert(engine_banco, tabela_stg, tabela_final):
    """Executa o merge atômico (Upsert) dos dados dentro do banco, descartando registros repetidos."""
    query_upsert = f"""
        INSERT INTO "{tabela_final}" (
            {', '.join(f'"{c}"' for c in _get_staging_columns(engine_banco, tabela_stg))}
        )
        SELECT *, NOW() AS bronze_inserted_at FROM "{tabela_stg}"
        ON CONFLICT (collision_id) 
        DO NOTHING; 
    """
    with engine_banco.connect() as conexao:
        conexao.execute(text(query_upsert))
        conexao.commit()


def _get_staging_columns(engine_banco, tabela_stg):
    """Retorna a lista de colunas da staging + bronze_inserted_at para o UPSERT."""
    with engine_banco.connect() as conexao:
        result = conexao.execute(text(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = '{tabela_stg}' ORDER BY ordinal_position;
        """))
        stg_cols = [row[0] for row in result]
    stg_cols.append("bronze_inserted_at")
    return stg_cols


def executar_pipeline(nome_tabela, engine_banco):
    """Orquestrador completo de extração, resiliência e carga do pipeline com Watermarking Dinâmico."""
    limite_bloco = 50000  
    total_processado = 0
    primeira_rodada = True
    
    # =====================================================================
    # WATERMARK DINÂMICO: Consulta o MAX(crash_date) existente no Postgres
    # =====================================================================
    watermark = obter_watermark_bronze(engine_banco, nome_tabela)
    
    if watermark is not None:
        logger.info(f"🔍 Watermark encontrado: {watermark}. Ativando modo DELTA — apenas dados posteriores serão coletados.")
    else:
        logger.info("🆕 Nenhum watermark detectado (tabela vazia ou inexistente). Ativando CARGA COMPLETA do histórico...")
    
    bloco_num = 1
    offset_atual = 0

    while True:
        # Monta a URL com $where dinâmico (URL-encoded) quando há watermark
        query_params = {
            "$limit": limite_bloco,
            "$offset": offset_atual,
            "$order": "collision_id"
        }
        if watermark is not None:
            query_params["$where"] = f"crash_date > '{watermark}'"
        
        url_pagina = f"{API_URL_BASE}?{urlencode(query_params)}"

        logger.info(f"⌛ Processando Bloco #{bloco_num} (Offset: {offset_atual}, Modo: {'DELTA' if watermark else 'FULL'})...")
        
        df_bloco = extrair_bloco_com_retry(url_pagina, bloco_num)

        if df_bloco.empty:
            if bloco_num == 1:
                logger.info("🏁 Nenhum dado novo disponível na API desde o último watermark. Pipeline encerrado com sucesso.")
            else:
                logger.info("🏁 Sincronização concluída com sucesso! Todos os dados disponíveis foram processados.")
            break
 
        # Limpeza e tipagem explícita do ID para evitar incompatibilidades
        if 'collision_id' in df_bloco.columns:
            df_bloco['collision_id'] = pd.to_numeric(df_bloco['collision_id'], errors='coerce')
            df_bloco = df_bloco.dropna(subset=['collision_id'])
            df_bloco['collision_id'] = df_bloco['collision_id'].astype('int64')
 
        # --- O PULO DO GATO DE TIPAGEM DE DATA ---
        # Força explicitamente a conversão para Datetime independente do motor de parse do CSV
        if 'crash_date' in df_bloco.columns:
            df_bloco['crash_date'] = pd.to_datetime(df_bloco['crash_date'], errors='coerce')
 
        if primeira_rodada:
            criar_constraints_se_nao_existirem(engine_banco, nome_tabela, df_bloco)
            primeira_rodada = False
 
        linhas_bloco = len(df_bloco)
        total_processado += linhas_bloco
 
        # Carga na tabela de Staging temporária (SEM a coluna bronze_inserted_at)
        df_bloco.to_sql(
            name=TABELA_STAGING,
            con=engine_banco,
            if_exists="replace",
            index=False,
            chunksize=10000
        )
        
        consolidar_dados_upsert(engine_banco, TABELA_STAGING, nome_tabela)
        logger.info(f"✅ Bloco #{bloco_num} consolidado com sucesso no Postgres (+{linhas_bloco} linhas / Total acumulado nesta execução: {total_processado}).")
 
        # Avança os ponteiros da paginação
        bloco_num += 1
        offset_atual += limite_bloco
        
        time.sleep(1.5)

    return total_processado


if __name__ == "__main__":
    start_time = time.time()

    # Executa a migração de schema (idempotente) antes de qualquer operação
    migrar_schema_bronze(engine, TABELA_DESTINO)

    # Dispara a orquestração do pipeline
    total_ingested = executar_pipeline(TABELA_DESTINO, engine)

    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{TABELA_STAGING}";'))
            conn.commit()
    except Exception:
        pass

    duracao = (time.time() - start_time) / 60
    logger.info(f"⏱️ Tempo total de processamento do job: {duracao:.2f} minutos.")

    # ==============================================================================
    # GENERATION OF THE BRONZE MANIFEST FOR DVC ORCHESTRATION
    # ==============================================================================

    # Obtém o watermark atualizado após a carga para registrar no manifesto
    watermark_final = obter_watermark_bronze(engine, TABELA_DESTINO)

    # Estrutura o dicionário de metadados do estado atual da carga
    bronze_manifest = {
        "status": "success",
        "updated_at": datetime.now(tz=__import__('datetime').timezone.utc).isoformat(),
        "pipeline_version": "v3.0.0",
        "records_ingested": total_ingested,
        "watermark_crash_date": watermark_final
    }

    # Define o caminho físico correto baseado na estrutura real do seu projeto
    metadata_dir = os.path.join("NYCdata", "metadata")
    os.makedirs(metadata_dir, exist_ok=True)  # Garante a criação da pasta caso não exista
    manifest_path = os.path.join(metadata_dir, "bronze_status.json")

    # Escreve o arquivo JSON de forma limpa no disco
    with open(manifest_path, "w") as f:
        json.dump(bronze_manifest, f, indent=4)

    logger.info("📝 Manifesto 'bronze_status.json' gerado com sucesso para o DVC!")