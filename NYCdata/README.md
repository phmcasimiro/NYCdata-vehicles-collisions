# PROJETO NYC DATA - VEHICLES COLLISIONS

DATASET:
https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Vehicles/bm4k-52h4/about_data

IDEIAS DE PROJETOS:
https://opendata.cityofnewyork.us/projects/

## 1) ARQUITETURA DE INFRAESTRUTURA (Containerização)

A arquitetura de armazenamento do projeto foi projetada para operar de forma isolada do sistema operacional hospedeiro (*host*), garantindo portabilidade, reprodutibilidade e conformidade com ambientes de produção via **Docker**.

### 1. A Imagem Base: Postgres + PostGIS
Em vez de compilar dependências geográficas manualmente no PostgreSQL padrão, a infraestrutura adota a imagem oficial postgis/postgis, que já vem pré-configurada com as principais bibliotecas geoespaciais do mercado (GEOS, PROJ e GDAL). Essa abordagem estende o motor SQL tradicional de forma nativa e autônoma, habilitando o suporte a tipos geográficos complexos — como POINT, POLYGON e LINESTRING — além de permitir o uso de indexação espacial avançada e consultas de proximidade de alta performance.

### 2. Isolamento de Rede e Redirecionamento de Portas (*Port Mapping*)
O banco de dados executa em uma camada de rede isolada criada nativamente pelo Docker, expondo seus serviços para a máquina local por meio do mapeamento da porta interna do PostgreSQL (5432) para a máquina hospedeira. Esse direcionamento controlado permite que ferramentas locais de gerenciamento de dados, como o DBeaver, e os scripts do pipeline rodando no ambiente virtual (venv) conectem-se perfeitamente ao banco apontando para o endereço localhost:5432.

### 3. Persistência de Dados via Docker Volumes (Garantia Antiperda)
Por padrão, os contêineres Docker são temporários: se o banco de dados for desligado, destruído ou atualizado, todas as tabelas guardadas dentro dele são apagadas. Para proteger o nosso histórico de 2,26 milhões de acidentes, utilizamos uma estratégia de **Volumes Nomeados** (*Named Volumes*). 

- **Montagem de Volume (`Data Volume`):** O diretório interno do Postgres onde as tabelas, índices e logs de transações são gravados fisicamente (`/var/lib/postgresql/data`) é montado e espelhado em um volume gerenciado pelo Docker na máquina local. Isso significa que uma "ponte" é criada para espelhar a pasta interna de arquivos do banco de dados diretamente em uma pasta segura e permanente no disco rígido do seu computador real.

- **Segurança de Estado:** Caso o contêiner seja parado (`docker stop`), reiniciado ou atualizado para uma versão mais recente do banco, o estado dos dados permanece intacto e persistido no disco local, permitindo que o pipeline incremental retome a carga sem perdas. Em resumo, os dados estão salvos fisicamente no seu computador e o pipeline incremental sempre continuará de onde parou, sem perda de informação.

### 4. Blueprint da Infraestrutura (`docker-compose.yml`)

Toda a infraestrutura (banco de dados e mapeamento) é configurada de forma centralizada e automatizada através de um único arquivo de comando. Na prática, é um "manual de instruções digital" que permite automatizar a configuração de senhas e criação de conexões. O arquivo .yml diz ao computador exatamente o que ele precisa preparar e evita instalações manuais de cada programa. Com isso, o ambiente inteiro entra no ar em segundos, garantindo agilidade e eliminando qualquer risco de erro humano na instalação.

Em resumo, a orquestração declarativa dessa infraestrutura é controlada de forma centralizada, isto é, um modelo arquitetural (.yml) que reflete a configuração do ambiente:

```yaml
version: '3.8'

services:
  database_spatial:
    image: postgis/postgis:16-3.4-alpine # Imagem leve baseada em Alpine Linux
    container_name: geodev_postgres_spatial
    restart: always # Política de resiliência: reinicia o banco se o container cair
    environment:
      POSTGRES_USER: ${DB_USER}       # Injetado dinamicamente via arquivo .env
      POSTGRES_PASSWORD: ${DB_PASS}   # Injetado dinamicamente via arquivo .env
      POSTGRES_DB: ${DB_NAME}         # Injetado dinamicamente via arquivo .env
    ports:
      - "5432:5432" # Expõe a porta do Postgres para o ambiente local
    volumes:
      - geodev_spatial_data:/var/lib/postgresql/data # Garante a persistência física

volumes:
  geodev_spatial_data: # Declaração do volume nomeado gerenciado pelo Docker
```
### RESUMO ESQUEMÁTICO DA ARQUITETURA DE INFRAESTRUTURA (Containerização)
```markdown
├── ARQUITETURA DE INFRAESTRUTURA (Containerização)
│   ├── Imagem Base (Postgres + PostGIS)
│   │   ├── Uso da imagem oficial 'postgis/postgis:16-3.4-alpine' para leveza e estabilidade
│   │   ├── Pré-configuração nativa de bibliotecas geoespaciais críticas (GEOS, PROJ e GDAL)
│   │   └── Suporte autônomo a tipos complexos (POINT, POLYGON, LINESTRING) e índices espaciais
│   │
│   ├── Isolamento de Rede & Port Mapping
│   │   ├── Execução do banco em uma camada de rede isolada criada nativamente pelo Docker
│   │   ├── Mapeamento de portas controlado ("5432:5432") direcionado à máquina hospedeira
│   │   └── Permissão de conexões externas seguras via Localhost (DBeaver, Scripts e venv)
│   │
│   ├── Persistência de Dados (Docker Volumes)
│   │   ├── Mitigação da natureza efêmera de containers através de Named Volumes
│   │   ├── Criação de ponte lógica (bind) espelhando a pasta '/var/lib/postgresql/data' no host
│   │   └── Garantia de segurança de estado para manutenção de cargas incrementais pós-reboot
│   │
│   └── Orquestração Declarativa (Blueprint .yml)
│       ├── Centralização do deploy e eliminação de riscos de erro humano via manual digital
│       ├── Injeção dinâmica de credenciais sensíveis via integração de variáveis (${DB_USER})
│       └── Aplicação de política de resiliência e alta disponibilidade ('restart: always')
```

## 2) ETL - CAMADA BRONZE/RAW

## Funcionamento do Pipeline de Ingestão (`1_nycdata_etl.py`)

O script foi desenvolvido seguindo práticas de Engenharia de Dados corporativa, atuando como um pipeline de carga híbrida (Histórica e Incremental) estruturado sob três pilares: **Idempotência**, **Resiliência** e **Consistência de Tipagem**.

### 1. Inicialização Segura e Gerenciamento de Credenciais
- **Variáveis de Ambiente:** O pipeline utiliza a biblioteca `python-dotenv` para isolar credenciais sensíveis (`DB_USER`, `DB_PASS`, etc.) em um arquivo `.env` local.
- **Tratamento de Strings de Conexão:** Aplica o método `quote_plus` da biblioteca `urllib.parse` para realizar o *URL Encoding* da senha do banco de dados, protegendo o driver de conexão contra quebras provocadas por caracteres especiais (como `@`, `:` ou `/`).

### 2. Análise de Estado e Idempotência (Ponto de Partida)
- O script realiza uma fase de *Discovery* antes de iniciar a extração, executando uma contagem ativa (`COUNT(*)`) na tabela definitiva do PostgreSQL (`nycdata_vehicle_collisions_raw`).
- **Se o banco estiver vazio:** O pipeline inicia do zero (`Offset: 0`), executando de forma automatizada a carga histórica total.
- **Se o banco já contiver dados:** Ele calcula o exato ponto de interrupção e retoma o processamento de forma incremental direto daquele registro. Isso garante que o script possa ser interrompido e reiniciado a qualquer momento sem duplicar dados ou gerar lacunas.

### 3. Extração Resiliente em Lotes (SODA API)
- A extração consome o endpoint oficial da prefeitura de Nova York no formato CSV em blocos controlados de **50.000 registros** por requisição, otimizando o consumo de memória RAM do ambiente.
- A URL de busca é paginada dinamicamente utilizando as cláusulas `$limit`, `$offset` e `$order=collision_id` do protocolo Socrata (SODA 2), garantindo ordenação estrita.

### 4. Mecanismo de Tolerância a Falhas de Rede e Fallback de Engine
Para garantir a continuidade em ambientes produtivos sujeitos a instabilidades, a função de extração implementa uma estratégia dupla de resiliência:
- **Retry com Exponential Backoff:** Em caso de erro na requisição, o script tenta ler o bloco novamente até 3 vezes, aguardando um tempo progressivo (5s, 10s e 15s) para permitir a recuperação da API.
- **Fallback Estratégico de Parse:** Na primeira tentativa, utiliza o motor `pyarrow` devido à alta performance. Caso a linha contenha caracteres corrompidos, aspas truncadas ou quebras de texto inválidas que gerem um erro de *parse*, o script chaveia automaticamente para o motor nativo em `C` utilizando a propriedade `on_bad_lines='skip'`, descartando apenas as linhas corrompidas e salvando o restante do lote.

### 5. Tipagem Estrita e Blindagem de Dados
- **Tratamento de Nulos:** Colunas categóricas (como `zip_code` e nomes de ruas) e de contagem de vítimas são mapeadas explicitamente no dicionário `dtype_mapeamento` para evitar inferências conflitantes do Pandas entre blocos distintos.
- **Uniformização de Timestamps:** A coluna `crash_date` passa obrigatoriamente por um tratamento via `pd.to_datetime(errors='coerce')` antes de ser inserida no banco de dados, garantindo que o PostgreSQL a receba como um tipo de dado temporal puro, e não como texto plano.

### 6. Carga em Duas Camadas (Staging e Upsert Atômico)
- A cada iteração bem-sucedida, o DataFrame limpo é injetado em uma tabela temporária de transição (`stg_nyc_collisions_tmp`) utilizando a propriedade `if_exists="replace"`.
- Em seguida, uma query SQL consolida os dados na tabela final através de uma operação de **Upsert**:
  ```sql
  INSERT INTO "nycdata_vehicle_collisions_raw" 
  SELECT * FROM "stg_nyc_collisions_tmp"
  ON CONFLICT (collision_id) DO NOTHING;
  ```

---

## Histórico de Troubleshooting e Evolução da Arquitetura

Durante o desenvolvimento e a execução da carga de dados (> 2 milhões de registros), o pipeline foi submetido a cenários reais de inconsistência da fonte de dados (Open Data). Abaixo estão documentados os problemas identificados, os logs gerados e as soluções de engenharia implementadas para atingir a estabilidade atual.

### 1. Incompatibilidade de Tipos entre Blocos (Zip Code)
- **Problema:** Inicialmente o Pandas inferiu que a coluna `zip_code` era numérica (`double precision`) com base nos primeiros blocos. No entanto, o Bloco #5 continha códigos postais com caracteres alfanuméricos ou formatações textuais da prefeitura, gerando uma colisão de tipos no Postgres.

- **Log do Erro:**
  ```text
  psycopg2.errors.DatatypeMismatch: column "zip_code" is of type double precision but expression is of type text
  HINT: You will need to rewrite or cast the expression.
    ```

- **Solução de Engenharia:** Criação do dicionário estrito `dtype_mapeamento` passando `"zip_code": str`. Como códigos postais são identificadores categóricos espaciais, foram fixados como texto para preservar zeros à esquerda e evitar quebras de esquema.

### 2. Valores Nulos em Colunas Inteiras (Contagem de Vítimas)

- **Problema:** Inicialmente os campos de contagem de feridos/mortos foram tipados como inteiro não nulos. No Bloco #28, o pipeline encontrou registros onde os campos de contagem de feridos/mortos estavam totalmente vazios (`NA`). O motor do Pandas tentou converter esses valores ausentes para inteiros rígidos, o que é matematicamente impossível no ecossistema padrão, estourando a memória do parser.
- **Log do Erro:**
```text
ValueError: cannot convert NA to integer: Error while type casting for column 'number_of_persons_injured'
```
- **Solução de Engenharia:** Mapeamento preventivo de todas as 8 colunas de estatísticas de vítimas (`injured`/`killed`) como `float` na leitura do CSV. O tipo flutuante aceita valores nulos (`NaN`/`NA`) nativamente. A conversão final para o formato numérico adequado ocorre de forma transparente na inserção dentro do banco.

### 3. Quebra de Delimitadores e Aspas Malformadas no CSV (Bloco #36)

- **Problema:** O trator de alta performance `pyarrow` encontrou uma linha corrompida no Bloco #36, onde um operador inseriu aspas truncadas ou quebras de linha manuais nos campos de texto plano (ex: nome de ruas). Por ser extremamente rígido com o esquema, o `pyarrow` abortou o lote completo de 50.000 linhas.

- **Log do Erro:**
```text
pyarrow.lib.ArrowInvalid: CSV parse error: Expected 29 columns, got 24: (40.81969, -73.90161)","EAST 160 STREET"...
pandas.errors.ParserError: CSV parse error: Expected 29 columns, got 24...
```

- **Solução de Engenharia:** Implementação de um **Fallback Estratégico de Engine**. O script tenta ler o bloco usando `pyarrow` pelo ganho de velocidade. Se houver falha de *parse*, o bloco `except` captura o erro e aciona o motor padrão em `C` configurado com `on_bad_lines='skip'`. O pipeline ganha imunidade, descartando a linha defeituosa e salvando o restante do lote.

### 4. Efeito Colateral de Tipagem no Fallback (Crash Date)

- **Problema:** Ao ativar o motor em `C` para pular as linhas ruins do Bloco #36, esse parser alternativo leu a coluna de datas (`crash_date`) como texto cru (`TEXT`), enquanto os blocos anteriores processados pelo `pyarrow` haviam criado a coluna definitiva como `TIMESTAMP`. O Postgres barrou o *Upsert* devido ao conflito estrutural.

- **Log do Erro:**
```text
psycopg2.errors.DatatypeMismatch: column "crash_date" is of type timestamp without time zone but expression is of type text
```

- **Solução de Engenharia:** Blindagem absoluta da camada de transformação. Logo após a leitura de qualquer bloco (seja por PyArrow ou C), o script executa explicitamente:

```python
df_bloco["crash_date"] = pd.to_datetime(
    df_bloco["crash_date"], errors="coerce"
)
```
- Essa solução uniformizou os objetos de data na memória do Python antes que eles toquem a tabela de staging, garantindo compatibilidade com o banco de dados.

---

### Resumo da Solução

Devido a ao ciclo de melhorias exposto acima, o pipeline tornou-se **idempotente** e **tolerante a falhas**. Por isso o script foi capaz de retomar execuções interrompidas exatamente do bloco onde parou, tratando dinamicamente sujeiras no meio de milhões de linhas e concluindo a carga massiva histórica de **2.263.787 registros** com sucesso absoluto.

---

## Granularidade, Consistência Histórica e Alinhamento de Volumes

Ao analisar o volume total de dados persistidos localmente em comparação com os indicadores macro exibidos na interface visual do portal *NYC Open Data*, uma validação de consistência foi executada para garantir que o pipeline não sofresse com perda de pacotes ou truncamento de registros.

### 1. Divergência de Registros Nominal vs. Real (Crashes vs. Vehicles)
A página de apresentação do portal de Nova York aponta um volume de mais de **4.54 milhões de linhas**, enquanto a tabela local definitiva (`nycdata_vehicle_collisions_raw`) estabilizou em **2.263.787 registros**. 

Essa diferença não representa perda de dados, mas uma distinção fundamental de **granularidade (o "grão" da tabela)** entre os *datasets* relacionais da prefeitura de NYC:

- **Tabela de Acidentes (`h9gi-nx95`):** É o *dataset* consumido neste pipeline. Cada linha representa **um acidente único** (um boletim de ocorrência), indexado de forma exclusiva pela chave `collision_id`. Se uma colisão envolveu múltiplos veículos, ela ainda assim constará como apenas uma linha nesta tabela.

- **Tabela de Veículos (Contador de 4.54M):** Cada linha representa **um veículo individual** envolvido em uma ocorrência. Se um único acidente envolveu 3 veículos, essa tabela registrará 3 linhas vinculadas ao mesmo ID de colisão.

Dado que a taxa média de veículos envolvidos por acidente em perímetros urbanos adensa-se em aproximadamente 2 por ocorrência, a validação matemática confirma a integridade total do histórico capturado:

$$\text{2.263.787 acidentes} \times \approx 2\text{ veículos/acidente} = \mathbf{4.54\text{ milhões de registros}}$$

### 2. Validação Estatística e Inconsistências de Origem (*Schema Anomalies*)
Para fins de auditoria, foi executada uma query analítica diretamente no banco de dados local para extrair a média horizontal de veículos mapeados por ocorrência. Durante essa validação, identificou-se uma anomalia de nomenclatura (*naming convention*) no próprio esquema de dados da API SODA 2 de Nova York:

```sql
-- Query de Auditoria de Granularidade no DBeaver
SELECT 
    AVG(
        CASE WHEN vehicle_type_code1 IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN vehicle_type_code2 IS NOT NULL THEN 1 ELSE 0 END +
        CASE WHEN vehicle_type_code_3 IS NOT NULL THEN 1 ELSE 0 END + -- Inconsistência na API (_)
        CASE WHEN vehicle_type_code_4 IS NOT NULL THEN 1 ELSE 0 END + -- Inconsistência na API (_)
        CASE WHEN vehicle_type_code_5 IS NOT NULL THEN 1 ELSE 0 END   -- Inconsistência na API (_)
    ) as media_veiculos_por_acidente
FROM nycdata_vehicle_collisions_raw;

```

- **Nota de Engenharia:** Enquanto os dois primeiros veículos utilizam o padrão `vehicle_type_code1` e `vehicle_type_code2`, os veículos subsequentes foram nomeados na origem com um caractere sublinhado (`vehicle_type_code_3`, `_4` e `_5`). O script tratou essa anomalia de forma transparente ao espelhar o esquema de metadados dinamicamente.

### 3. Justificativa para Pequenos Descartes (*Data Quality Rules*)

Uma margem residual de registros inferiores a 1% pode apresentar variações devido às seguintes travas de qualidade de dados (*Data Quality Guards*) ativas no código:

1. **Remoção de Registros sem Identificador:** Linhas históricas corrompidas na origem que não possuíam o campo `collision_id` preenchido ou válido foram descartadas via `dropna(subset=['collision_id'])` para preservar a integridade referencial e impedir a falha da restrição `UNIQUE` do PostgreSQL.

2. **Tratamento de Linhas Malformadas (`on_bad_lines='skip'`):** Linhas que continham quebras manuais de texto ou aspas truncadas inseridas por falha humana na digitação dos boletins de ocorrência foram ignoradas pelo motor de *fallback* em `C` do Pandas, garantindo a continuidade e a automação do pipeline sem travamentos (*deadlocks*).

### RESUMO ESQUEMÁTICO CAMADA BRONZE/RAW
```markdown
├── ETL - CAMADA BRONZE/RAW (Ingestão e Resiliência)
│   ├── Funcionamento do Pipeline (1_nycdata_etl.py)
│   │   ├── Inicialização Segura & Credenciais
│   │   │   ├── Isolamento de parâmetros sensíveis via biblioteca 'python-dotenv'
│   │   │   └── URL Encoding de senhas via 'urllib.parse.quote_plus' contra caracteres especiais
│   │   │
│   │   ├── Análise de Estado & Idempotência
│   │   │   ├── Fase de Discovery ativa executando 'COUNT(*)' na tabela definitiva
│   │   │   └── Carga híbrida: offset zero para histórico ou cálculo de retomada incremental
│   │   │
│   │   ├── Extração Resiliente em Lotes
│   │   │   ├── Consumo do endpoint SODA API via blocos de 50.000 linhas salvando memória RAM
│   │   │   └── Paginação dinâmica ordenada de forma estrita via '$limit', '$offset' e '$order'
│   │   │
│   │   ├── Tolerância a Falhas & Fallback de Engine
│   │   │   ├── Mecanismo de Retry com Exponential Backoff (3 tentativas espaçadas: 5s, 10s, 15s)
│   │   │   └── Chaveamento de parser: motor 'pyarrow' (velocidade) ou 'C' com 'on_bad_lines=skip'
│   │   │
│   │   ├── Tipagem Estrita & Blindagem
│   │   │   ├── Mapeamento explícito via 'dtype_mapeamento' contra inferências conflitantes
│   │   │   └── Uniformização temporal forçada de datas usando 'pd.to_datetime(errors="coerce")'
│   │   │
│   │   └── Carga Atômica em Duas Camadas
│   │       ├── Injeção volátil do bloco limpo em tabela temporária ('stg_nyc_collisions_tmp')
│   │       └── Operação de Upsert definitivo via query 'INSERT INTO ... ON CONFLICT DO NOTHING'
│   │
│   ├── Histórico de Troubleshooting (Evolução da Arquitetura)
│   │   ├── 01. Incompatibilidade de Tipos entre Blocos (Zip Code)
│   │   │   ├── Sintoma: Erro 'psycopg2.errors.DatatypeMismatch' (conflito double vs text)
│   │   │   └── Solução: Fixado mapeamento de códigos postais como string para manter zeros à esquerda
│   │   │
│   │   ├── 02. Valores Nulos em Colunas Inteiras (Estatísticas de Vítimas)
│   │   │   ├── Sintoma: Erro 'ValueError: cannot convert NA to integer' em campos vazios
│   │   │   └── Solução: Leitura tipada como float (aceita NaN) e conversão nativa pelo Postgres
│   │   │
│   │   ├── 03. Quebra de Delimitadores e Aspas Malformadas (Bloco #36)
│   │   │   ├── Sintoma: Abortamento do lote por falha do parser rígido ('ArrowInvalid / ParserError')
│   │   │   └── Solução: Implementação do bloco try/except ativando o Fallback Estratégico de Engine
│   │   │
│   │   └── 04. Efeito Colateral de Tipagem no Fallback (Crash Date)
│   │       ├── Sintoma: Conflito de esquema causado pelo motor C que interpretou data como text
│   │       └── Solução: Inclusão de 'pd.to_datetime' pós-leitura imediata de qualquer motor
│   │
│   └── Auditoria de Granularidade & Consistência do Volume
│       ├── Validação de Volume Nominal vs. Real
│       │   ├── Alinhamento do grão da tabela: 2.26M de acidentes únicos ('collision_id')
│       │   └── Prova matemática: 2.26M acidentes × ~2 veículos por ocorrência = ~4.54M de registros
│       │
│       ├── Identificação de Anomalias de Esquema na Fonte
│       │   ├── Descoberta de desvio de padrão na API (veículos 1 e 2 sem '_', de 3 a 5 com '_')
│       │   └── Tratamento transparente via espelhamento e mapeamento dinâmico de metadados
│       │
│       └── Regras de Descarte (Data Quality Guards)
│           ├── Eliminação de registros sem chave: 'dropna(subset=["collision_id"])'
│           └── Supressão de ruídos de digitação manual de agentes via pulo de linhas corrompidas
```

## 2) ETL - CAMADA SILVER/CLEANED

Na etapa anterior, Bronze (Raw), foram garantidas a integridade e a resiliência da extração dos dados brutos, nesta nova etapa o projeto segue para a **Camada Silver (Cleaned/Conformed)**. Na arquitetura de medalhões a **Camada Silver (Cleaned/Conformed)** está relacionada a processos que garantam a qualidade dos dados.

```markdown
├── PIPELINE DE TRANSFORMAÇÃO E ARQUITETURA DA CAMADA SILVER
│   ├── 1. Higienização e Padronização de Colunas (Renaming & Casting)
│   │   ├── Padronização estrita de todas as 29 colunas originais para snake_case em inglês via 'schemas.py'
│   │   ├── Neutralização de assimetrias da API de NYC (ex: vehicle_type_code_1 ao 5 padronizados com '_')
│   │   └── Tipagem estrita de identificadores categóricos como TEXT/str (ex: zip_code mantendo 5 dígitos)
│   │
│   ├── 2. Engenharia de Atributos Temporais & Fusos (Feature Engineering)
│   │   ├── Unificação de 'raw_crash_date' e 'raw_crash_time' em um eixo temporal único
│   │   ├── Conversão de fuso horário local de Nova York (EST/EDT) para padrão UTC universal ('crash_timestamp')
│   │   └── Extração em memória de colunas derivadas para BI ('crash_year', 'crash_month', 'crash_day_of_week', 'time_bucket')
│   │
│   ├── 3. Tratamento em Lote de Dados Ausentes (Null Handling)
│   │   ├── Varredura estrutural forçando colunas numéricas de vítimas decimais para INTEGER rígido (NaN -> 0)
│   │   ├── Imputação de nulos em fatores contribuintes e tipos de veículos para o literal 'UNSPECIFIED'
│   │   └── Normalização de dados de infraestrutura urbana (Borough & Streets) mapeando nulos para 'UNKNOWN'
│   │
│   ├── 4. Criação da Geometria PostGIS & Bounding Box (Spatial Enrichment)
│   │   ├── Construção de strings no formato padrão da OGC WKT: 'POINT(longitude latitude)'
│   │   ├── Filtro via máscara booleana isolando 11% de telemetria corrompida ou zerada (0,0) fora dos limites de NYC
│   │   └── Conversão transacional no banco gerando bytes binários espaciais na coluna nativa 'geom' (SRID 4326)
│   │
│   ├── 5. Metadados de Auditoria, Linhagem & Higienização Textual (Data Governance)
│   │   ├── Injeção em tempo de execução das colunas de controle e rastreabilidade 'silver_processed_at' e 'pipeline_version'
│   │   └── Processamento em lote aplicando tratamento textual agressivo (UPPERCASE + TRIM em categorias de texto)
│   │
│   └── 6. Carga Física, Deduplicação e Indexação de Alta Performance
│       ├── Janelamento atômico cronológico eliminando duplicidades finas de chaves primárias ('collision_id')
│       ├── Carga volátil em tabela de staging ('stg_nyc_cleaned_tmp') com chunks otimizados de 20.000 linhas
│       ├── Operação de Upsert definitivo ('INSERT ... ON CONFLICT DO UPDATE') garantindo idempotência absoluta
│       └── Otimização de queries indexando eixos estruturais: B-Tree (timestamps) e GiST espacial (coluna 'geom')
```

## Etapas Práticas de Execução na Camada Silver

Diferente da camada Bronze (focada puramente em ingestão isolada), a camada Silver foi projetada sob uma arquitetura de transformação híbrida e performática através do script `2_nycdata_silver.py`. O pipeline combina o poder de processamento em memória e vetorização do Python (Pandas) com a robustez transacional e geoespacial nativa do PostgreSQL e PostGIS.

Abaixo estão documentadas as 6 fases fundamentais executadas pelo pipeline para garantir a qualidade analítica global dos dados:

### 1. Higienização e Padronização de Colunas (*Renaming & Casting*)

- **Renomeação Uniforme:**
    - Padronização das 29 colunas originais da API para o formato `snake_case` em inglês.
    - Correção de assimetrias dos headers nas fonte de dados (ex: `vehicle_type_code1` e `vehicle_type_code_3`). Esta correção foi implementada por meio do arquivo de metadados `schemas.py` (`MAP_BRONZE_TO_SILVER`).
- **Tipagem Estrita e Auditoria de String:**
    - Identificadores categóricos (ex: `zip_code`) são forçados estritamente para o tipo texto (`str`). 
    - Auditoria de metadados no banco de dados para validação da ingestão inicial, ou seja, que os registros da coluna `zip_code` possuem comprimento exato de 5 dígitos dos códigos postais de Nova York, eliminando riscos de truncamento ou perda de zeros à esquerda.

### 2. Engenharia de Atributos Temporais e Padronização de Fusos (*Feature Engineering & Timezone*)

- **Padronização de Datas, Horários e Fusos (Timezone Standardization):**
    - O script captura tanto a data nativa em formato textual e quanto a hora isolada da camada Bronze/Raw e as unifica em uma linha temporal única. 
    - O pipeline localiza o registro, com o fuso horário original do acidente (*America/New_York*), trata anomalias de Horário de Verão (EDT/EST), e converte o resultado final para o padrão universal **UTC** (`TIMESTAMP WITH TIME ZONE`), salvando-o na coluna definitiva `crash_timestamp`.
- **Extração de Atributos Analíticos Avançados:**
    - Visando otimizar a performance de renderização do dashboard final e evitar cálculos custosos em tempo de execução no BI, o script extrai componentes temporais diretamente do vetor em memória, gerando as colunas: `crash_year`, `crash_month`, `crash_day_of_week` (indexado de 0 a 6) e `time_bucket` (classificação categórica dos períodos do dia: *Overnight*, *Morning*, *Afternoon*, *Evening*).

### 3. Tratamento de Dados Ausentes e Padronização em Lote (*Null Handling & Bulk Transformation*)

- **Consistência Numérica de Vítimas:**
    - Na camada Bronze, os indicadores de vítimas (como `total_persons_injured` e `total_persons_killed`) precisaram ser ingeridos como ponto flutuante (`double precision`) para aceitar valores nulos da API. Na camada Silver, o script executa uma transformação em lote (*bulk transformation*), mapeando as 8 colunas de estatísticas de acidentes, substituindo nulos por `0` e convertendo os tipos de dados para inteiros rígidos (`INTEGER`).
- **Normalização Categórica contra Fragmentação:**
    - As 10 colunas associadas a fatores contribuintes e tipologias de veículos são processadas em lote na memória. O script aplica regras de limpeza em espaços vazios ocultos enviados pela API (`.str.strip()`), forçando letras maiúsculas (`.str.upper()`) e convertendo campos ausentes estruturais para o literal internacional padrão `'UNSPECIFIED'`.
    - Dados de infraestrutura urbana (`borough` e nomes de ruas) seguem o mesmo tratamento, convertendo nulos e strings em branco para o literal de controle espacial `'UNKNOWN'`.

### 4. Criação da Geometria PostGIS e Filtros Espaciais (*Spatial Enrichment & Bounding Box*)

- **Geração de Geometria Nativa de Escala:**
    - O pipeline transforma as coordenadas de latitude e longitude brutas em strings no formato padrão da OGC chamado WKT (*Well-Known Text*), construindo a estrutura `POINT(longitude latitude)` na ordem correta exigida por sistemas de informação geográfica.
    - Ao persistir os dados no banco, o motor do PostGIS consome essa string através da função transacional `ST_GeomFromText`, convertendo-a em um objeto geográfico binário de alta performance indexado sob o sistema de coordenadas global WGS 84 (`SRID 4326`):

$$\text{geom} = \text{ST\_GeomFromText}(\text{geom\_wkt}, 4326)$$

- **Validação por Caixa Delimitadora (Bounding Box):**
    - O script atua como um guarda de qualidade de dados geoespaciais, aplicando uma máscara booleana baseada nos limites geográficos reais dos cinco distritos de New York City (Longitude entre `-74.259` e `-73.700`; Latitude entre `40.477` e `40.917`).
    - A auditoria do pipeline identificou com precisão cirúrgica que **11% dos registros (248.425 ocorrências)** continham falhas críticas de telemetria ou coordenadas zeradas `(0,0)` enviadas pela prefeitura. O script isolou essas anomalias de forma segura, convertendo-as para `NULL` no campo geométrico para proteger os mapas do dashboard, enquanto preserva o histórico textual do acidente.

### 5. Metadados de Auditoria e Linhagem (*Data Lineage & Governance*)

- **Governança e Rastreabilidade de Carga:**
    - Para estabelecer um rastreamento rigoroso de auditoria, o pipeline injeta duas colunas de controle técnico em tempo de execução para cada linha gravada na tabela limpa:
    - `silver_processed_at`: Carimbo de data e hora com fuso horário registrando o momento exato em que a linha foi consolidada pelo pipeline Python.
    - `pipeline_version`: Tag de controle de versão do código (ex: `v2.0.0`), permitindo identificar imediatamente quais regras de negócio foram aplicadas àquele registro em caso de atualizações de esquema no futuro.

### 6. Carregamento Atômico, Deduplicação e Indexação Avançada

- **Janelamento e Unicidade Absoluta:**
    - Antes de tocar o disco do banco de dados definitivo, os registros passam por uma ordenação cronológica encadeada (`collision_id` + `crash_timestamp`) e uma remoção de duplicidades baseada na chave única do boletim de ocorrência (`collision_id`), emulando um janelamento SQL analítico (`ROW_NUMBER() OVER`). Isso blinda o pipeline, permitindo que a tabela final estabeleça uma `PRIMARY KEY` rígida inviolável.
- **Transação por Staging e Upsert Atômico:**
    - Visando mitigar o risco de corrupção ou travamento da base de dados ativa em produção, o script adota uma estratégia de carga em duas fases. O DataFrame higienizado é despejado inicialmente em uma tabela volátil de transição (`stg_nyc_cleaned_tmp`) via blocos otimizados de memória (*chunks* de 20.000 linhas). Em seguida, uma transação atômica do SQLAlchemy executa uma query de `INSERT ... ON CONFLICT DO UPDATE` (*Upsert*), garantindo consistência total e idempotência absoluta ao pipeline.
- **Otimização Estrutural por Índices:**
    - Para responder consultas analíticas e espaciais complexas em frações de milissegundos, o banco consolida índices tradicionais `B-Tree` em colunas de alta filtragem temporal (`crash_timestamp`, `crash_year`, `crash_month`) e cria um índice geoespacial avançado **`GiST` (Generalized Search Tree)** diretamente sobre a coluna binária `geom`, preparando a infraestrutura para cruzamentos de proximidade geográfica em altíssima velocidade.

---

## Stack Tecnológico da Camada Silver

```markdown
├── OBJETIVOS DE GOVERNANÇA E MLOps NA CAMADA SILVER (*Caminho 1*)
│   ├── Data Contract & Schema Enforcement (Pydantic)
│   │   ├── Validar tipos de dados em tempo de execução via 'BaseModel' estrito
│   │   ├── Aplicar regras de negócio numéricas (ex: 'total_persons_injured' >= 0)
│   │   ├── Validar limites temporais coerentes (ex: 'crash_year' entre 2012 e o ano atual)
│   │   └── Injetar sanitização orientada a objetos ( decorators para UPPERCASE + TRIM)
│   │
│   ├── Pipeline Lineage & Orchestration (DVC)
│   │   ├── Construir DAG dinâmico de dependências ligando scripts e dados via 'dvc.yaml'
│   │   ├── Isolar gatilhos de execução ('dvc repro' executa apenas estágios alterados)
│   │   └── Garantir reprodutibilidade total do pipeline fim a fim (Bronze → Silver)
│   │
│   ├── Relational State Tracking (Ponteiros no DVC)
│   │   ├── Gerar manifestos leves de metadados/checksums (.json) das tabelas Docker/Postgres
│   │   └── Rastrear arquivos de controle no Git para indexar o estado exato do banco de dados
│   │
│   └── Artefact Versioning (MLOps Readiness)
│       ├── Preparar o versionamento de snapshots pesados extraídos (ex: .parquet)
│       └── Blindar o GitHub contra arquivos grandes usando storage local/nuvem gerenciado pelo DVC
```

```markdown
├── ETAPAS PRÁTICAS DE IMPLEMENTAÇÃO (Pydantic & DVC)
│   ├── 1. Isolamento de Contratos de Dados (schemas.py)
│   │   ├── Importar 'BaseModel', 'Field' e 'field_validator' da biblioteca Pydantic
│   │   └── Criar a classe 'CollisionSilverSchema' com mapeamento internacional (EUA/Canadá)
│   │
│   ├── 2. Acoplamento de Validação no Pipeline (2_nycdata_silver.py)
│   │   ├── Converter registros do DataFrame para dicionários Python na memória
│   │   ├── Passar os dados pelo crivo do schema Pydantic interceptando falhas (try/except)
│   │   └── Exportar um log de qualidade contendo registros aprovados vs. rejeitados
│   │
│   ├── 3. Criação do Manifesto de Estado do Banco de Dados
│   │   ├── Injetar uma função de geração de checksum/contagem ao fim do processamento
│   │   └── Salvar um arquivo estático de controle ('silver_status.json') na pasta de metadados
│   │
│   ├── 4. Inicialização e Mapeamento do DVC
│   │   ├── Executar o comando 'dvc init' na raiz do repositório GeoDev
│   │   └── Configurar o storage remoto local para armazenar os artefatos do pipeline
│   │
│   ├── 5. Construção da DAG do Pipeline (dvc.yaml)
│   │   ├── Declarar estágio 'ingest_bronze' (deps: script 1, env; outs: raw_status.json)
│   │   └── Declarar estágio 'transform_silver' (deps: script 2, schemas, raw_status; outs: silver_status.json)
│   │
│   └── 6. Homologação e Otimização do Fluxo ('dvc repro')
│       ├── Executar 'dvc repro' na console para compilar e salvar a árvore de execução
│       └── Validar o cache do DVC alterando regras no Pydantic sem reprocessar a carga Bronze
```

Na camada Silver, integramos o **Pydantic** e o **DVC (Data Version Control)** ao pipeline para consolidar uma arquitetura profissional alinhada às melhores práticas de **Engenharia de Dados e MLOps**. No contexto da arquitetura de medalhões (Bronze $\rightarrow$ Silver $\rightarrow$ Gold), cada uma dessas ferramentas desempenha um papel cirúrgico e possui um momento exato de acoplamento.

### 7. Implementação do Pydantic no Ciclo de Dados

A camada de validação e garantia de contratos do Pydantic atua estritamente na transição entre a **Camada Bronze (`nycdata_vehicle_collisions_raw`)** e a **Camada Silver (`nycdata_vehicle_collisions_cleaned`)**.

O Pydantic é utilizado exclusivamente de forma desacoplada no script de transformação (`2_nycdata_silver.py`), operando como um validador de esquemas (*Data Contract*) e garantidor de regras de consistência em tempo de execução. O script de ingestão inicial (`1_nycdata_etl.py`) permanece isolado e focado apenas na carga bruta (*Extract & Load*).

- **Garantia de Contratos de Dados (*Data Contract Enforcement*):**
    - Evita a dependência exclusiva de tipagens dinâmicas ou inferências do Pandas estabelecidas na camada Raw. O pipeline submete as linhas extraídas do Postgres a um objeto estruturado estrito (`BaseModel`), blindando os estágios seguintes contra mutações ou quebras de esquema na fonte.
- **Validação de Regras de Negócio e Sanidade:**
    - Garante a consistência lógica e física dos dados em nível de linha, auditando e forçando restrições matemáticas (ex: validando que colunas analíticas como `total_persons_injured` nunca assumam valores negativos) e restrições cronológicas (ex: assegurando que o campo `crash_timestamp` pertença a um intervalo coerente entre o ano de 2012 e o ano atual).
- **Sanitização Orientada a Objetos:**
    - Utiliza validadores de campo nativos (*field validators*) para higienizar dados textuais de forma padronizada. Strings categóricas passam por normalização de caixa e remoção de espaçamentos ocultos (`.strip().upper()`). 
    - Valores nulos ou vazios estruturais são interceptados e convertidos de forma limpa para literais padronizados de mercado internacional, como `'UNSPECIFIED'` e `'UNKNOWN'`.
- **Processamento Otimizado em Lote (*Batch Chunking Engine*):**
    - Para mitigar picos de consumo de memória RAM ao manipular volumes massivos, o ecossistema processa o DataFrame em blocos fracionados de 100.000 linhas por iteração, convertendo e aplicando as regras contratuais com máxima eficiência computacional.
- **Resiliência e Observabilidade via Tabela de Erros (*Dead Letter Queue - DLQ*):**
    - Em vez de tolerar falhas fatais que abortariam o pipeline ou aceitar dados corrompidos na base limpa, o bloco de controle captura anomalias estruturais na origem (ex: registros com datas impossíveis que geram `NaN` no parse). 
    - Esses registros rejeitados são desviados em tempo real para uma estrutura de DLQ física no Postgres (`nycdata_vehicle_collisions_rejections`), armazenando o carimbo de tempo da falha, a descrição do erro apontada pelo Pydantic e o payload bruto original em formato JSON/String para fins de auditoria posterior.

### 8. Orquestração e Versionamento com Data Version Control (DVC)

A orquestração de dependências e o versionamento do ciclo de vida das **Camadas Bronze, Silver e Gold** são gerenciados de forma centralizada pelo DVC, controlando a linhagem dos metadados e dos artefatos do pipeline.

Como as tabelas do projeto residem dentro de um banco de dados relacional que o Git não pode rastrear por padrão, o pipeline adota uma estratégia avançada de rastreamento de estado: os scripts de engenharia exportam arquivos leves de manifesto contendo metadados técnicos e contagens de linhas (`silver_status.json`) ao final de cada execução bem-sucedida. O DVC rastreia esses ponteiros de estado indexados ao Git e vinculados a um repositório de armazenamento secundário (*storage local de backup*), garantindo a governança do ambiente.

- **Versionamento de Pipelines (DAG Dinâmico):**
    - Através do arquivo central de configuração `dvc.yaml`, as etapas do ecossistema de dados são conectadas por meio de uma árvore de dependências explícita. O DVC mapeia e controla o fluxo operacional:
        - **Etapa Bronze:** Executa o script `1_nycdata_etl.py` (depende das credenciais do arquivo `.env` e gera a tabela Raw no Postgres).
        - **Etapa Silver:** Executa o script `2_nycdata_silver.py` (depende do sucesso da Etapa Bronze, do código de validação do Pydantic em `schemas.py` e consolida a tabela espacial limpa, gravando as rejeições na DLQ).
- **Otimização de Ciclos de Processamento (*Pipeline Caching* com `dvc repro`):**
    - Estabelece idempotência inteligente ao ciclo de desenvolvimento. Caso uma regra de validação ou normalização de string seja modificada no script ou nas classes do Pydantic na Silver, o comando `dvc repro` identifica de forma cirúrgica se o histórico bruto da Bronze sofreu alterações. Se a origem estiver idêntica, o DVC reaproveita o cache e executa **apenas** a transformação subsequente, poupando tempo de processamento de rede e I/O do banco de dados.
- **Rastreamento Rígido de Estado com Lockfiles (`dvc.lock`):**
    - A integridade do pipeline fim a fim é imobilizada através do arquivo de trava matemática `dvc.lock`. Ele armazena os hashes md5 exatos de cada dependência e saída gerada pelo pipeline. Qualquer alteração não documentada nos scripts ou nos manifestos quebra a validação, garantindo reprodutibilidade absoluta do ambiente em pipelines de CI/CD.
- **Isolamento de Artefatos Pesados (*Decoupled Remote Storage*):**
    - Alinhado às boas práticas de MLOps, o repositório é configurado com um armazenamento local secundário (`dvc remote`). Usando o comando `dvc push`, o cache de metadados e manifestos volumosos são sincronizados com o diretório de backup externo, permitindo manter o repositório do GitHub extremamente leve e livre de dados pesados.

---

```markdown
## Histórico de Troubleshooting e Evolução da Arquitetura (Camada Silver)

Durante a transição e higienização dos dados da Camada Bronze para a Silver, o pipeline de transformação enfrentou desafios complexos de escala, consistência de tipos ocultos na API e integridade de regras de negócio. Abaixo estão documentados os problemas identificados na massa de mais de 2,2 milhões de linhas, os respetivos logs de erro e as soluções de arquitetura aplicadas para garantir conformidade total.

### 1. As Strings de Conversão ("NONE" / "NAN")
- **Problema:** Durante a higienização textual, a conversão nativa de nulos do Pandas (`.astype(str)`) transformou os valores nulos relacionais (`NULL`) vindos do Postgres em strings literais `"NONE"` ou `"NAN"`. Isto burlou os filtros tradicionais de substituição do Pandas, permitindo que registos com dados de localização vazios (como o `collision_id` 24) chegassem à tabela final com campos em branco em vez do padrão corporativo exigido.

- **Sintoma Visual (DBeaver):**
  ```sql
  SELECT collision_id, borough FROM nycdata_vehicle_collisions_cleaned WHERE collision_id = 24;
  -- Resultado: 24 | [Campo Vazio / Espaço em Branco] (Deveria exibir 'UNKNOWN')

```

- **Solução de Engenharia:** Implementação de um validador nativo interceptador no Pydantic (`@field_validator(mode="before")`). 
    - O contrato de dados captura o valor bruto antes de qualquer inferência do Pandas e submete-o a uma varredura estrita. 
    - Se o dado contiver `""`, `"NAN"`, `"NONE"` ou `"NULL"`, o Pydantic força a atribuição automática para os literais controlados `'UNKNOWN'` (infraestrutura) ou `'UNSPECIFIED'` (fatores/veículos).

### 2. Bloqueio do Contrato por NaNs Temporais em Inteiros (Os 4.841 Registos Isolados)

- **Problema:**
    - No dataset original há 4.841 boletins de ocorrência com strings de data ou hora completamente corrompidas. 
    - Ao aplicar a unificação temporal com `pd.to_datetime(errors="coerce")`, o Pandas converteu estes erros em objetos `NaT` (Not a Time).
    - Consequentemente, a extração das colunas derivadas de ano, mês e dia gerou valores de ponto flutuante `NaN`.
    - Como o contrato exige estritamente inteiros puros (`int`), o validador barrou o bloco completo.

- **Log do Erro (Pydantic):**
```text
⚠️ Registro rejeitado pelo contrato: ID 9971 - Erro: 3 validation errors for CollisionSilverSchema
crash_year
  Input should be a finite number [type=finite_number, input_value=nan, input_type=float]
crash_month
  Input should be a finite number [type=finite_number, input_value=nan, input_type=float]

```
- **Solução de Engenharia:** 
    - Isolamento via bloco `try/except` dentro do motor de loops. 
    - Registos que não possuem eixos temporais válidos perdem a capacidade de indexação (`B-Tree`) e utilidade analítica em painéis de BI.
    - Em vez de crashar o pipeline, o script isolou estas linhas, mantendo a integridade da carga dos 2.259.948 registos saudáveis (preparando o terreno para o desvio para uma Dead Letter Queue).

### 3. Gargalo de Memória RAM e Desaparecimento da Coluna Espacial (`geom_wkt`)

- **Problema:**
    - A conversão volumétrica total do DataFrame para dicionários Python via `df_silver.to_dict(orient="records")` gerou um pico massivo de consumo de memória RAM, ameaçando a estabilidade do sistema. 
    - Além disso, ao reconstruir o DataFrame pós-validação, a coluna temporária `geom_wkt` foi eliminada, pois não pertencia aos campos nativos do esquema Pydantic, quebrando a Fase 6 de injeção no PostGIS.

- **Log do Erro:**
```text
pandas.errors.DatabaseError: Execution failed on sql 'INSERT INTO ...' 
KeyError: 'geom_wkt' / Out of Memory Event

```

- **Solução de Engenharia:** 
    - Refatoração do pipeline para a estratégia de **Batch Chunking**.
    - O DataFrame é fatiado em blocos controlados de 100.000 linhas por iteração.
    - Dentro de cada bloco, a máscara booleana da Bounding Box de NYC isola telemetrias de GPS absurdas e reconstrói dinamicamente a string OGC WKT (`POINT(lon lat)`) em tempo de execução no loop do Pydantic, otimizando a memória e preservando o contrato do PostGIS.

---

## Granularidade, Consistência Histórica e Alinhamento de Volumes

Para validar a eficácia do contrato de dados e auditoria da Camada Silver, foi executado um batimento volumétrico estrito entre as entradas extraídas da camada de dados brutos (Bronze) e as saídas consolidadas no banco de dados espacial definitivo.

### 1. Auditoria de Fluxo de Ingestão e Taxa de Conformidade

O pipeline iniciou a leitura com uma volumetria bruta de **2.264.789 registos** residentes na Camada Bronze. Após passar pelo motor de governança do Pydantic e filtros de consistência, o volume final distribuído fixou-se nos seguintes indicadores fundamentais:

* **Massa Aprovada na Silver (`nycdata_vehicle_collisions_cleaned`):** **2.259.948 registos únicos** perfeitamente limpos, indexados temporariamente e enriquecidos com coordenadas PostGIS válidas.
* **Massa Rejeitada por Inconsistência Temporal:** **4.841 registos corrompidos na origem** (ausência de data/hora válidas).

$$\text{2.259.948 (Aprovados)} + \text{4.841 (Rejeitados)} = \mathbf{2.264.789\text{ Registos Totais de Entrada (100%)}}$$

### 2. Validação da Máscara Espacial da Bounding Box

Durante a Fase 4, a auditoria espacial expôs um dado de telemetria pública alarmante: **11% dos registos (248.425 acidentes)** continham coordenadas de GPS zeradas `(0,0)` ou localizadas fora do perímetro do Estado de Nova Iorque.

O pipeline protegeu o ecossistema analítico forçando estas coordenadas espúrias para `NULL` no campo geométrico, garantindo que ferramentas de mapa (como o DBeaver Spatial ou dashboards de BI) renderizem o perímetro de Manhattan e bairros vizinhos sem distorções no globo, preservando intactos os dados textuais das ruas do acidente.

---

### RESUMO ESQUEMÁTICO CAMADA SILVER/CLEANED

```markdown
├── TRANSFORMAÇÃO & GOVERNANÇA - CAMADA SILVER/CLEANED
│   ├── Funcionamento do Pipeline (2_nycdata_silver.py)
│   │   ├── Engenharia de Atributos Temporais Estritos
│   │   │   ├── Unificação de vetores primitivos de data/hora no objeto unificado 'crash_timestamp'
│   │   │   ├── Alinhamento de fusos: conversão de America/New_York (com horário de verão) para UTC
│   │   │   └── Desmembramento analítico pré-calculado em memória para BI (year, month, day_of_week, time_bucket)
│   │   │
│   │   ├── Governança e Contrato de Dados (Pydantic)
│   │   │   ├── Interpolação do DataFrame em lotes otimizados (Chunks de 100.000 linhas)
│   │   │   ├── Validação de tipos estrita via BaseModel impedindo mutações de esquema ocultas
│   │   │   └── Restrição de integridade matemática barrando indicadores de vítimas negativos (ge=0)
│   │   │
│   │   ├── Sanitização Orientada a Objetos (Field Validators)
│   │   │   ├── Varredura robusta mapeando e limpando espaços em branco invisíveis (TRIM de strings)
│   │   │   ├── Uniformização categórica transformando inputs em letras maiúsculas (UPPERCASE)
│   │   │   └── Captura e tradução automática de strings fantasmas ('NONE', 'NAN') para 'UNKNOWN' ou 'UNSPECIFIED'
│   │   │
│   │   ├── Enriquecimento e Qualidade Espacial (PostGIS)
│   │   │   ├── Proteção geoespacial via Bounding Box ativa isolando 11% de GPS corrompido na prefeitura
│   │   │   └── Construção dinâmica de strings padrão WKT: 'POINT(longitude latitude)'
│   │   │
│   │   └── Persistência Idempotente e Escala
│   │       ├── Janelamento cronológico para eliminação de duplicidades finas por 'collision_id'
│   │       ├── Carga volátil de staging intermediária via blocos otimizados de 20.000 registos
│   │       ├── Operação de Upsert definitivo via comando 'ON CONFLICT DO UPDATE' para atomicidade
│   │       └── Indexação de infraestrutura: Estruturas B-Tree (tempo) e índices espaciais GiST (geometria)
│   │
│   └── Histórico de Troubleshooting (Evolução da Arquitetura)
│       ├── 01. O Fantasma das Strings de Conversão ("NONE" / "NAN")
│       │   ├── Sintoma: Registros em branco no DBeaver (ID 24) devido a falha de escape do Pandas
│       │   └── Solução: Ativação do decorator '@field_validator(mode="before")' convertendo anomalias textuais
│       │
│       ├── 02. Bloqueio por NaNs Temporais em Inteiros (4.841 Rejeitados)
│       │   ├── Sintoma: Erro 'finite_number' do Pydantic causado por datas corrompidas que viraram NaT/NaN
│       │   └── Solução: Isolamento analítico por bloco try/except sem interrupção do pipeline de produção
│       │
│       └── 03. Gargalo de Memória RAM e Sumiço da Coluna 'geom_wkt'
│           ├── Sintoma: Erro 'KeyError: geom_wkt' e lentidão extrema no loop de processamento
│           └── Solução: Introdução do Batch Chunking acoplado à reconstrução em lote de coordenadas WKT

```
---
### 9. Orquestração Automatizada e Automação (Infrastructure as Code - IaC)

Substituindo a automação tradicional baseada em scripts isolados, neste projeto optou-se por uma abordagem de **Orquestração por Grafo (DAG)** utilizando o DVC em simbiose com o Agendador de Tarefas do Windows. O provisionamento e gerenciamento desse agendamento são realizados inteiramente via terminal PowerShell (modo elevado), aplicando conceitos de *Infrastructure as Code* (IaC) para garantir reprodutibilidade absoluta do ambiente operacional.

#### Script de Inicialização Encapsulado (`run_pipeline.bat`)

Para garantir o isolamento das dependências e evitar falhas de contexto relativas ao diretório de execução do sistema, as ações do pipeline foram encapsuladas em um script de lote (`.bat`) localizado em `NYCdata/run_pipeline.bat`:

```batch
@echo off
:: 1. Navega até a raiz absoluta do projeto GeoDev
cd /d "C:\Users\HP\Documents\Projetos\GeoDev"

:: 2. Ativa o ambiente virtual Python
call venv\Scripts\activate

:: 3. Dispara a verificação e execução inteligente via DVC
dvc repro

:: 4. Encerra o ambiente de forma limpa
call deactivate

```

#### Provisionamento Modular da Tarefa via PowerShell

O agendamento foi estruturado de forma modular no PowerShell, separando a **Ação** (o que executar), o **Gatilho** (quando executar) e as **Configurações de Resiliência** (condições de contorno do sistema) antes do registro definitivo.

Para provisionar ou replicar essa infraestrutura em qualquer ambiente Windows, executa-se o seguinte bloco de comandos sob privilégios de Administrador:

```powershell
# 1. Define a Ação apontando para o script de inicialização do ecossistema
$action = New-ScheduledTaskAction -Execute "C:\Users\HP\Documents\Projetos\GeoDev\NYCdata\run_pipeline.bat"

# 2. Define o Gatilho Cronológico para execução diária pontualmente às 13:00
$trigger = New-ScheduledTaskTrigger -Daily -At "13:00"

# 3. Define Políticas de Resiliência Energética (Garante execução contínua mesmo em modo bateria)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

# 4. Consolida e registra a tarefa no núcleo do Sistema Operacional
Register-ScheduledTask `
    -TaskName "GeoDev_NYCData_Pipeline_Orchestrated" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Orquestração ponta a ponta das camadas Bronze e Silver do ecossistema NYC Data via DVC DAG"

```

#### 🛡️ Governança de Infraestrutura e Políticas de Resiliência

- **Imunidade à Interrupção de Energia (`-AllowStartIfOnBatteries`):** Por padrão, o Windows suspende automações caso o hardware seja desconectado da tomada. No ecossistema de dados, essa restrição é desativada para mitigar o risco de *table locks* ou transações corrompidas no PostgreSQL/PostGIS no meio de um processo de *Upsert Atômico*.
- **Desacoplamento Inteligente:** O Agendador do Windows não precisa saber quais scripts Python existem ou onde o banco está localizado. Ele apenas acorda o DVC. O DVC, através do arquivo `dvc.yaml`, decide de forma autônoma quais camadas precisam de reprocessamento com base na variação dos hashes de dados ou regras de negócio.

#### Monitoramento e Observabilidade

A auditoria e verificação do pipeline podem ser realizadas via terminal sem dependência da interface gráfica (GUI):

- **Disparo Manual (Sob Demanda/Teste de Carga):**
```powershell
Start-ScheduledTask -TaskName "GeoDev_NYCData_Pipeline_Orchestrated"

```

- **Coleta de Indicadores de Sucesso (Auditoria):**
```powershell
Get-ScheduledTask -TaskName "GeoDev_NYCData_Pipeline_Orchestrated" | Get-ScheduledTaskInfo

```

**Indicadores Críticos de Sucesso:**
- **`LastTaskResult = 0`:** Código universal do sistema operacional que valida que o pipeline encerrou sua execução com sucesso.
- **`NextRunTime`:** Confirma o alinhamento do relógio do sistema com a próxima janela de ingestão incremental de dados da API.

















### Próximo Passo Prático
- Agendamento do script `1_nycdata_etl.py` no Agendador de Tarefas do Windows.
    - Quartas-Feiras às 00:00 e Domingos 00:00

Planejar a implementação da **Camada Silver utilizando Python + Pydantic para a validação**. Avaliar se a criação de um script `2_transform_silver.py` que leia os dados da tabela Raw do Postgres, valide linha por linha (ou bloco por bloco) com o Pydantic e salve em uma nova tabela limpa está de acordo com o planejado nos chat anteriores desta conversa

Quer que eu monte a estrutura inicial da classe Pydantic baseada nas colunas que nós temos no banco para você ver como criar essas validações?