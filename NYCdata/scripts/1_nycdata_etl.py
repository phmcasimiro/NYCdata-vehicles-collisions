import os
import time
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

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
            print(f"🛠️ Tabela '{nome_tabela}' não encontrada. Criando estrutura baseada no schema da API...")
            df_modelo.head(0).to_sql(
                name=nome_tabela,
                con=engine_banco,
                if_exists="append",
                index=False
            )
            conexao.commit()

        query_verificar_constraint = f"""
            SELECT COUNT(*) 
            FROM pg_indexes 
            WHERE tablename = '{nome_tabela}' AND indexname = '{nome_tabela}_collision_id_key';
        """
        existe_idx = conexao.execute(text(query_verificar_constraint)).scalar()
        
        if existe_idx == 0:
            print(f"🛠️ Aplicando restrição UNIQUE na coluna 'collision_id' da tabela '{nome_tabela}'...")
            try:
                conexao.execute(text(f'ALTER TABLE "{nome_tabela}" ADD CONSTRAINT "{nome_tabela}_collision_id_key" UNIQUE (collision_id);'))
                conexao.commit()
            except Exception as e:
                print(f"⚠️ Nota ao aplicar a constraint: {e}")


def obter_ponto_de_partida(engine_banco, nome_tabela):
    """Verifica a quantidade de registros atuais na tabela destino para definir o offset incremental."""
    try:
        query = f'SELECT COUNT(*) FROM "{nome_tabela}";'
        with engine_banco.connect() as conexao:
            total_linhas = conexao.execute(text(query)).scalar()
            return total_linhas if total_linhas else 0
    except Exception:
        return 0


def extrair_bloco_com_retry(url, bloco_num, max_retries=3):
    """Executa a leitura do bloco aplicando resiliência de rede e fallback estratégico de engine de parse."""
    retry_count = 0
    while retry_count < max_retries:
        try:
            if retry_count == 0:
                df = pd.read_csv(url, engine="pyarrow", dtype=dtype_mapeamento)
            else:
                print(f"🔄 Aplicando estratégia de Fallback: Usando motor padrão com descarte de linhas malformadas...")
                df = pd.read_csv(url, engine="c", dtype=dtype_mapeamento, on_bad_lines="skip")
            return df
        except Exception as e:
            retry_count += 1
            wait_time = retry_count * 5  
            print(f"⚠️ Falha observada no Bloco #{bloco_num} (Tentativa {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                print(f"⏳ Aguardando {wait_time} segundos para tentar novamente...")
                time.sleep(wait_time)
            else:
                raise RuntimeError(f"❌ Erro crítico: O bloco #{bloco_num} falhou persistentemente.")


def consolidar_dados_upsert(engine_banco, tabela_stg, tabela_final):
    """Executa o merge atômico (Upsert) dos dados dentro do banco, descartando registros repetidos."""
    query_upsert = f"""
        INSERT INTO "{tabela_final}" 
        SELECT * FROM "{tabela_stg}"
        ON CONFLICT (collision_id) 
        DO NOTHING; 
    """
    with engine_banco.connect() as conexao:
        conexao.execute(text(query_upsert))
        conexao.commit()


def executar_pipeline(nome_tabela, engine_banco):
    """Orquestrador completo de extração, resiliência e carga do pipeline."""
    limite_bloco = 50000  
    total_processado = 0
    primeira_rodada = True
    
    offset_atual = obter_ponto_de_partida(engine_banco, nome_tabela)
    bloco_num = (offset_atual // limite_bloco) + 1
    
    if offset_atual > 0:
        print(f"🔄 Carga retomada de forma incremental. Registro atual de partida: {offset_atual} (Bloco #{bloco_num}).")
    else:
        print("🆕 Tabela vazia ou inexistente detectada. Iniciando processamento completo do histórico...")

    while True:
        url_pagina = f"{API_URL_BASE}?$limit={limite_bloco}&$offset={offset_atual}&$order=collision_id"

        print(f"\n⌛ Processando Bloco #{bloco_num} (Offset de busca: {offset_atual})...")
        
        df_bloco = extrair_bloco_com_retry(url_pagina, bloco_num)

        if df_bloco.empty:
            print(f"\n🏁 Sincronização concluída com sucesso! Todos os dados disponíveis foram processados.")
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

        # Carga na tabela de Staging temporária
        df_bloco.to_sql(
            name=TABELA_STAGING,
            con=engine_banco,
            if_exists="replace",
            index=False,
            chunksize=10000
        )
        
        consolidar_dados_upsert(engine_banco, TABELA_STAGING, nome_tabela)
        print(f"✅ Bloco #{bloco_num} consolidado com sucesso no Postgres (+{linhas_bloco} linhas / Total acumulado de novas linhas processadas nesta execução: {total_processado}).")

        # Avança os ponteiros da paginação
        bloco_num += 1
        offset_atual += limite_bloco
        
        time.sleep(1.5)


if __name__ == "__main__":
    start_time = time.time()

    # Dispara a orquestração do pipeline
    executar_pipeline(TABELA_DESTINO, engine)

    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{TABELA_STAGING}";'))
            conn.commit()
    except Exception:
        pass

    duracao = (time.time() - start_time) / 60
    print(f"\n⏱️ Tempo total de processamento do job: {duracao:.2f} minutos.")