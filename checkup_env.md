# PLAYBOOK INTEGRADO DE AUDITORIA E VERIFICAÇÃO: ECOSSISTEMA GEODEV (NYCdata)

Este documento é um guia para testar e validar o funcionamento (*Production Readiness*) de todos os componentes do projeto **GeoDev**. Viabiliza a validação de infraestrutura local, a integridade do pipeline de dados e as travas de concorrência para suportar a carga de **200 usuários ativos**.

---

## 1. INFRAESTRUTURA DE BANCO DE DADOS (DOCKER & POSTGIS)

**Objetivo:** Verificar se o contêiner do banco está ativo, isolando conexões com segurança, e se as tabelas contêm as estruturas de índices corretas para evitar *deadlocks*.

### Passos de Execução:

1. No terminal do PowerShell, valide o estado do contêiner:
```powershell
docker ps

```

* **Critério de Aceite:** O contêiner `nyc_crashes_gis_db` deve constar com status `Up` e mapeando a porta corporativa `5432:5432`.


2. Abra o DBeaver e execute o script de batimento volumétrico das três camadas:
```sql
SELECT 
    (SELECT COUNT(*) FROM public.nycdata_vehicle_collisions_raw) AS total_bronze,
    (SELECT COUNT(*) FROM public.nycdata_vehicle_collisions_cleaned) AS total_silver,
    (SELECT COUNT(*) FROM public.nycdata_vehicles_collisions_gold_fact_contributing_factors) AS total_gold;

```


* **Critério de Aceite:** 
  * A diferença entre camadas Bronze e Silver deve refletir exatamente as linhas isoladas pela Dead Letter Queue (DLQ).
  * A camada Gold deve exibir uma volumetria compactada (entorno de dezenas de milhares de registros), provando a eficiência do *Query Pushdown*. 


1. Verifique a presença e validade dos índices estruturais de produção:
```sql
-- Auditoria de Índices da Camada Silver
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'nycdata_vehicle_collisions_cleaned';

-- Auditoria de Índices da Camada Gold (Materialized View)
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'nycdata_vehicles_collisions_gold_fact_contributing_factors';

```


* **Critério de Aceite:** 
  * A Silver deve retornar os índices `idx_nyc_cleaned_spatial_gist` (PostGIS), `idx_nyc_cleaned_timestamp` e `idx_nyc_cleaned_year_month`.
  * A Gold deve listar obrigatoriamente o índice composto **`idx_gold_factors_unique_composite` (UNIQUE)**, viabilizando o `REFRESH CONCURRENTLY`.


---

## 2. AUDITORIA DE DADOS, DELTAS E LINHAGEM

**Objetivo:** Verificar o comportamento dos lotes incrementais que entram pela Bronze e rastrear a transformação até a limpeza da Silver.

### Passos de Execução:

1. No DBeaver, analise o perfil de carregamento por lotes baseado no carimbo físico da API:
```sql
SELECT 
    bronze_inserted_at AS timestamp_ingestao,
    bronze_inserted_at::date AS data_ingestao,
    COUNT(*) AS volume_registros_ingeridos,
    MIN(crash_date) AS acidente_mais_antigo_do_lote,
    MAX(crash_date) AS acidente_mais_recente_do_lote
FROM public.nycdata_vehicle_collisions_raw
GROUP BY bronze_inserted_at
ORDER BY bronze_inserted_at DESC
LIMIT 5;

```


* **Critério de Aceite:** 
  * O primeiro registro deve exibir a carga histórica massiva (~2.2M) e as linhas subsequentes devem demonstrar os blocos incrementais (deltas) menores injetados pelas rodadas seguintes.


2. Inspecione a qualidade dos registros e a existência de campos nulos:
```sql
SELECT collision_id, borough, crash_date, bronze_inserted_at, vehicle_type_code1
FROM public.nycdata_vehicle_collisions_raw
ORDER BY bronze_inserted_at DESC
LIMIT 10;

```

3. Validação do sincronismo temporal entre a ingestão e o processamento:
```sql
SELECT 
    b.bronze_inserted_at AS timestamp_bronze,
    s.silver_processed_at AS timestamp_silver,
    COUNT(*) AS total_lote_comum
FROM public.nycdata_vehicle_collisions_raw b
JOIN public.nycdata_vehicle_collisions_cleaned s ON b.collision_id = s.collision_id
GROUP BY b.bronze_inserted_at, s.silver_processed_at
ORDER BY b.bronze_inserted_at DESC
LIMIT 5;

```

* **Critério de Aceite:** 
  * Os timestamps de Bronze e Silver para o mesmo lote devem possuir uma janela de diferença de poucos minutos (tempo de processamento em memória do Python).

---

## 3. PIPELINE DE TRANSFORMACÃO & ORQUESTRACÃO DVC

**Objetivo:** Confirmar que a DAG do DVC orquestra as etapas sem reprocessamento redundante, agindo estritamente sobre dados novos.

### Passos de Execução:

1. No terminal do PowerShell, garanta o posicionamento do repositório e o ambiente ativo:

```powershell
cd c:\Users\HP\Documents\Projetos\GeoDev
venv\Scripts\activate

```


2. Consulte o mapeamento de dependências do pipeline:

```powershell
dvc status

```


* **Critério de Aceite:** 
  * O DVC deve retornar apenas a flag `always changed` sob o estágio `ingest_bronze`. 
  * Os estágios subsequentes de transformação não devem constar como modificados se os dados analíticos de tracking não mudaram.


3. Execute a verificação forçada de ponta a ponta:

```powershell
dvc repro
```


* **Critério de Aceite (O Teste Delta):** 
  * Em execuções consecutivas, o script da Silver (`2_nycdata_silver.py`) deve executar em poucos segundos.
  * Ele deve ler o estado persistido e indicar o processamento de **0 novas linhas** se a API não trouxer novos registros, em vez de re-escrever a base histórica inteira.
  * Valide o resultado inspecionando o arquivo `NYCdata/metadata/silver_status.json`.

---

## 4. AUTOMACÃO E AGENDAMENTO (WINDOWS TASK SCHEDULER)

**Objetivo:** Garantir a autonomia operacional do pipeline assíncrono e eliminar falhas ocultas.

### Passos de Execução:

1. Sem sair do PowerShell, audite as propriedades de execução do agendamento:

```powershell
Get-ScheduledTask -TaskName "*GeoDev*" | Get-ScheduledTaskInfo

```


* **Critério de Aceite:** 
  * O parâmetro `LastTaskResult` deve retornar obrigatoriamente **`0`** (sucesso absoluto).
  * O campo `NextRunTime` deve exibir o próximo gatilho programado de forma coerente.


2. Validação estrutural na interface do sistema:
* Execute `Windows + R`, digite `taskschd.msc` e abra a Biblioteca do Agendador de Tarefas.
* Localize a tarefa `GeoDev_NYCData_Pipeline_Orchestrated`.



> ### 🚨 O PULO DO GATO: VALIDACÃO DE DIRETÓRIO DE INÍCIO
> > 
> Na aba **Ações** da sua tarefa agendada, clique em **Editar**. O campo **Iniciar em (opcional)** não pode ficar vazio sob risco de quebrar os caminhos relativos do Python. Ele deve conter obrigatoriamente o caminho completo da raiz do projeto:
> `C:\Users\HP\Documents\Projetos\GeoDev`

---

## 5. SERVIDOR WSGI DE PRODUÇÃO (WAITRESS)

**Objetivo:** Validar que o dashboard Dash/Flask foi ejetado do modo single-thread de desenvolvimento e está respondendo sob uma arquitetura multi-threaded corporativa.

### Passos de Execução:

1. Inicialize a aplicação a partir da raiz na branch de melhorias:
```powershell
python NYCdata/scripts/3_nycdata_gold_dash.py

```


* **Critério de Aceite:** O console deve omitir os avisos de ambiente instável do Flask e printar o log corporativo estruturado:
`🚀 Iniciando servidor corporativo Waitress na porta 8050 com 8 threads ativas...`


2. Com o processo de pé, abra o navegador e acesse: `http://localhost:8050`. O Dashboard deve renderizar os componentes geográficos em sua totalidade.

---

## 6. MECANISMO DE CACHE DE CALLBACKS (FLASK-CACHING)

**Objetivo:** Certificar que consultas pesadas a cruzamentos espacio-temporais idênticos fiquem retidas em memória secundária, eliminando requisições redundantes no banco.

### Passos de Execução:

1. Navegue pelo dashboard aberto no browser e mude aleatoriamente os filtros de distritos (`borough`), anos e trimestres para forçar o primeiro cálculo analítico.
2. Abra o seu gerenciador de arquivos e inspecione o seguinte diretório:
`NYCdata/cache/`
* **Critério de Aceite:** O sistema deve popular a pasta com arquivos serializados de hashes binários (representando as consultas memoizadas).


3. Retorne ao dashboard e clique em um filtro previamente selecionado.
* **Critério de Aceite:** A transição gráfica deve ser instantânea, e nenhuma nova query SQL deve ser disparada nos logs do contêiner do Postgres.


---

## 7. POOL DE CONEXÕES & HIGIENIZAÇÃO DE LOGS ESTRUTURADOS

**Objetivo:** Blindar o banco contra exaustão de sockets TCP via pooling do SQLAlchemy e garantir a legibilidade total dos relatórios de qualidade sem corrupção de caracteres.

### Passos de Execução:

1. Enquanto interage com o dashboard simulando requisições simultâneas, execute no DBeaver o monitor de conexões do catálogo do sistema:
```sql
SELECT count(*), state 
FROM pg_stat_activity 
WHERE datname = 'nyc_crashes_gis_db'
GROUP BY state;

```

* **Critério de Aceite:** O número total de conexões ativas e em ociosidade (`idle`) deve estacionar estavelmente dentro do teto delimitado pelas propriedades `pool_size=20` e `max_overflow=30`, nunca estourando o limite do contêiner.


2. No terminal do PowerShell, extraia os registros consolidados da esteira forçando o encode universal:
```powershell
Get-Content NYCdata/metadata/pipeline.log -Tail 50 -Encoding utf8

```

* **Critério de Aceite:** As tags estruturadas (`[INFO]`, `[WARNING]`) devem estar perfeitamente alinhadas, com os relatórios de auditoria do Pydantic (registros válidos vs rejeitados na DLQ) visíveis e livres de caracteres corrompidos (*Mojibake*).