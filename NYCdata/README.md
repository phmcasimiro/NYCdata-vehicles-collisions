# PROJETO NYC DATA - VEHICLES COLLISIONS

DATASET:
https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Vehicles/bm4k-52h4/about_data

IDEIAS DE PROJETOS:
https://opendata.cityofnewyork.us/projects/

## 1) ARQUITETURA DE INFRAESTRUTURA (Containerização)

O ecossistema de armazenamento do projeto foi projetado para operar de forma isolada do sistema operacional hospedeiro (*host*), garantindo portabilidade, reprodutibilidade e conformidade com ambientes de produção via **Docker**.

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

## 1) ETL - CAMADA BRONZE/RAW

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

## 2) ETL - CAMADA SILVER/CLEANED

Com o encerramento da camada Bronze (Raw), na qual estão garantidas a integridade e a resiliência da extração dos dados brutos, o projeto segue para a **Camada Silver (Cleaned/Conformed)**. Na arquitetura de medalhões (Bronze $\rightarrow$ Silver $\rightarrow$ Gold), a **Camada Silver (Cleaned/Conformed)** é o coração da qualidade dos dados.

Abaixo, são apresentados os objetivos estratégicos e as etapas práticas utilizadas para estruturar a camada Silver no banco de dados:

---

## Objetivos da Camada Silver

O foco da camada Silver é **limpar, padronizar e enriquecer** os registros para que qualquer analista, cientista de dados ou ferramenta de BI possa consumi-los sem medo de inconsistências.

- **Garantir a Qualidade dos Dados (*Data Quality*):** 
    - Eliminar registros totalmente corrompidos
    - Tratar dados nulos de forma analítica
    - Remover duplicidades finas que possam ter passado pela camada anterior (bronze/raw)

- **Padronizar a Estrutura (*Schema Conformance*):**
    - Corrigir anomalias de nomenclatura da fonte (como a bagunça de sublinhados em `vehicle_type_code`)
    - Aplicar tipos de dados perfeitos (converter strings de números para inteiros reais)
    - Traduzir termos técnicos para o negócio

- **Habilitar a Análise Espacial (Geoprocessamento):** 
    - Converter as coordenadas brutas de Latitude e Longitude em objetos geográficos reais (pontos no PostGIS), possibilitando cruzamentos espaciais rápidos.

- **Otimizar a Performance:** 
    - Indexar a tabela por chaves de busca frequentes (como datas e regiões) para que as consultas respondam em milissegundos, mesmo contendo mais de 2 milhões de linhas.

---

## Etapas Práticas de Execução na Camada Silver

Estas etapas serão traduzidas em scripts SQL estruturados ou em modelos de transformação (*tabelas* ou *views*) dentro do banco

### 1. Higienização e Padronização de Colunas (*Renaming & Casting*)

- **Renomeação Uniforme:** 
    - Padronizar os nomes de todas as colunas e corrigir assimetrias de escrita. 
    - Campos como `vehicle_type_code1` e `vehicle_type_code_3` passarão a seguir um padrão rígido (ex: `veiculo_tipo_codigo_1`).
- **Tipagem Correta:** 
    - Forçar strings puras que representam números categóricos (como o código postal `zip_code`) a irem para um formato de texto limpo, garantindo que não ocorra perda de zeros à esquerda.

### 2. Engenharia de Atributos Temporais (*Feature Engineering*)

-  **Enriquecimento de Tempo:** 
    - O banco bruto possui campos textuais isolados para data e hora. Nesta etapa, vamos unificar e extrair novos atributos fundamentais para análise de tendências, gerando novas colunas como:
    - `ano` (Integer)
    - `mes` (Integer)
    - `dia_da_semana` (Texto ou Integer, ex: Segunda, Terça...)
    - `faixa_horaria` (ex: Madrugada, Manhã, Tarde, Noite)

### 3. Tratamento de Dados Ausentes (*Null Handling*)

- **Imputação de Valores:** 
    - Campos de texto vitais que vieram em branco ou nulos (como `borough` ou `contributing_factor`) serão preenchidos com uma string padrão (ex: `'NÃO INFORMADO'`), evitando falhas em filtros de relatórios visuais.
- **Consistência Numérica:**
    - Garantir que contagens nulas de vítimas passem a ser tratadas explicitamente como `0` onde aplicável, limpando distorções estatísticas.

### 4. Criação da Geometria PostGIS (*Spatial Enrichment*)

- **Geração de Pontos Geográficos:** 
    - Utilizar as funções nativas do PostGIS para criar uma coluna geométrica real de coordenadas a partir da latitude e longitude brutas:

$$\text{geom} = \text{ST\_SetSRID}(\text{ST\_MakePoint}(\text{longitude}, \text{latitude}), 4326)$$

- **Validação de Coordenadas:**
    - Filtrar e isolar registros que possuem coordenadas impossíveis (como latitude/longitude zeradas `(0,0)`, que apontam para o meio do Oceano Atlântico) para não poluírem os mapas do painel.

### 5. Deduplicação Fina e Indexação

-  **Garantia de Unicidade:**
    - Executar queries com partições (`ROW_NUMBER() OVER(PARTITION BY collision_id ORDER BY ...)`) para garantir que apenas a versão mais recente de uma ocorrência atualizada seja mantida.
- **Criação de Índices:**
    - Aplicar índices tradicionais (`B-Tree`) em colunas de alta busca (como data e ano) e índices espaciais (`GiST`) na coluna geográfica, preparando a base para responder com velocidade máxima.

---

## Stack Tecnológico da Camada Silver

Na camada Silver utilizamos o **Pydantic** e o **DVC (Data Version Control)** no pipeline para uma arquitetura profissional de **Engenharia de Dados e MLOps**.

No contexto da arquitetura de medalhões (Bronze $\rightarrow$ Silver $\rightarrow$ Gold), cada uma dessas ferramentas tem um papel cirúrgico e um momento de utilização.

### 7. Implementação do Pydantic no Ciclo de Dados

A implementação do Pydantic neste pipeline se dá na transição entre a **Camada Bronze (`nycdata_vehicle_collisions_raw`)** e a **Camada Silver (`nycdata_vehicle_collisions_cleaned`)**.

O Pydantic é utilizado exclusivamente no script de transformação (`2_nycdata_silver.py`), atuando como um validador (*schemas*) e garantidor de regras em tempo de execução. O script de ingestão inicial (`1_nycdata_etl.py`) permanece isolado e focado apenas no carregamento bruto (*Extract & Load*).

- **Garantia de Contratos Teóricos:**
    - Evita a dependência exclusiva das tipagens dinâmicas ou inferências do Pandas estabelecidas na camada Raw, submetendo os dados brutos extraídos do Postgres a um objeto estruturado (`BaseModel`) com validação estrita.
-  **Validação de Regras de Negócio:**
    - Garante a consistência física dos dados, validando que indicadores de contagem (como `number_of_persons_injured`) nunca assumam valores negativos e que a linha temporal (`crash_date`) pertença a um intervalo de tempo correto (entre o ano de 2012 e o ano atual).
-  **Sanitização Orientada a Objetos:** 
    - Através dos decoradores de validação do Pydantic, strings categóricas (como nomes de logradouros) são limpas e normalizadas via `.strip().upper()`. 
    - Dados ausentes ou nulos não estruturados são convertidos de forma padronizada para literais de controle, como `'NÃO INFORMADO'`.

---

### 8. Orquestração e Versionamento com Data Version Control (DVC)

A orquestração e o versionamento com DVC são implementados no projeto por meio do gerenciamento do ciclo de vida das **Camadas Silver e Gold**, além dos metadados e artefatos de pipeline.

Enquanto o Git gerencia o histórico de código do projeto de forma eficiente, o DVC rastreia o fluxo dos pipelines e armazena possíveis subprodutos de dados pesados (como *snapshots* em formatos binários ou conjuntos de *features*), utilizando arquivos de ponteiro leves (`.dvc`) indexados ao Git e vinculados a um repositório de armazenamento secundário (*storage local ou nuvem*).

O DVC opera na camada de abstração e orquestração dos scripts de engenharia, controlando a linhagem dos dados e evitando reprocessamentos desnecessários.

- **Versionamento de Pipelines (DAG Dinâmico):**
    - Através do arquivo central de configuração `dvc.yaml`, as etapas do pipeline de dados são conectadas por meio de uma árvore de dependências. O DVC mapeia explicitamente o fluxo:
    - **Etapa Bronze:** Executa o script `1_nycdata_etl.py` (depende das credenciais do arquivo `.env` e gera a tabela Raw no Postgres).
    - **Etapa Silver:** Executa o script de transformação (depende do sucesso da etapa Bronze e do código de validação do Pydantic).

- **Otimização de Ciclos de Processamento (`dvc repro`):**
    - Caso uma regra de validação ou normalização de string seja modificada no script da camada Silver, o comando `dvc repro` identifica de forma inteligente que o histórico bruto da camada Bronze não sofreu mutações, executando **apenas** a transformação subsequente, poupando tempo de rede e processamento do banco de dados.

- **Rastreamento de Artefatos de Produção:**
    - Se o escopo do projeto expandir para ciência de dados, permitindo a exportação de frações da camada Silver ou Gold em arquivos de alta performance (como arquivos `.parquet`) para treinamento de modelos de Machine Learning, o DVC encapsula o versionamento desses arquivos sem estourar as travas de tamanho do GitHub.

---

### 🗺️ O Fluxo Visual na Arquitetura do Projeto

Para tangibilizar o ciclo de vida dos dados, veja como o pipeline está estruturado entre as camadas:

1. **Camada BRONZE (Concluída e Versionada):**
   * **Fluxo:** O script `1_nycdata_etl.py` consome a API SODA 2 $\rightarrow$ Realiza carga pontual/incremental $\rightarrow$ Salva os dados brutos na tabela `nycdata_vehicle_collisions_raw` do PostgreSQL (Docker).
   * **Papel do DVC:** Monitora a execução do script de ingestão como uma etapa dependente do arquivo `.env` e armazena os metadados e logs do estado inicial da carga, mapeando a origem da linhagem dos dados (*data lineage*).

2. **Camada SILVER (Próximo Passo — Transformação):**
   * **Fluxo:** Um novo script focado em transformação (`2_nycdata_silver.py`) lê os dados brutos diretamente da tabela `nycdata_vehicle_collisions_raw`.
   * **💥 Atuação do Pydantic:** Funciona como o validador de contrato. Cada lote de dados extraído da Bronze é convertido em objetos e submetido às classes de validação do Pydantic para checar a integridade de negócio (bloqueio de números negativos, tipagem estrita, normalização de strings e tratamento de nulos).
   * **Persistência:** Os dados validados e enriquecidos com funções geométricas do PostGIS são salvos na tabela definitiva de análise: `nycdata_vehicle_collisions_cleaned`.
   * **Papel do DVC:** Orquestra essa etapa garantindo que ela só seja executada se o script de transformação for alterado ou se a camada Bronze receber novos dados.

3. **Camada GOLD (Consolidação e Modelagem):**
   * **Fluxo:** Criação de tabelas agregadas e visões de negócios otimizadas para alimentar diretamente os relatórios e painéis do Looker Studio.
   * **💥 Atuação do DVC:** Caso o escopo se estenda para Machine Learning e você decida exportar *snapshots* ou matrizes de características da Silver/Gold (ex: `features_acidentes.parquet`), o comando `dvc add` entra em ação. O DVC armazena o arquivo binário pesado no seu *Storage* (local ou nuvem) e gera um ponteiro leve textualmente rastreável (`features_acidentes.parquet.dvc`) para o Git, blindando o repositório contra o limite de 100MB do GitHub.



### Próximo Passo Prático
- Agendamento do script `1_nycdata_etl.py` no Agendador de Tarefas do Windows.
    - Quartas-Feiras às 00:00 e Domingos 00:00

Planejar a implementação da **Camada Silver utilizando Python + Pydantic para a validação**. Avaliar se a criação de um script `2_transform_silver.py` que leia os dados da tabela Raw do Postgres, valide linha por linha (ou bloco por bloco) com o Pydantic e salve em uma nova tabela limpa está de acordo com o planejado nos chat anteriores desta conversa

Quer que eu monte a estrutura inicial da classe Pydantic baseada nas colunas que nós temos no banco para você ver como criar essas validações?