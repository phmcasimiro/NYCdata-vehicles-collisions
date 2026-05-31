### Post 1 - Projeto NYC Data Vehicles Collisions - Introdução e Visão Geral do Projeto

Em meio aos compromissos familiares, ao (não tão) novo trabalho e à Pós-Graduação da PCDF/IBMEC, venho tentanto não perder contato com a prática profissional que mais gosto (DADOS). Dessa forma, escolhi um dataset público desafiador que estivesse na interseção das minhas formações profissionais (Segurança Pública, TI/Dados e Geo) para construir um projeto de portfólio que fosse mais próximo dos desafios reais de um profissional de TI/Dados.

Nesse contexto escolhi o NYC Motor Vehicle Collisions, uma base de dados pública da prefeitura de Nova York com mais de 2,26 milhões de acidentes de trânsito e que é atualizada diariamente. O objetivo inicial deste projeto é construir um pipeline de dados ponta a ponta (Bronze ➡️ Silver ➡️ Gold), integrando práticas de Arquitetura de Soluções, Engenharia de Software, Engenharia de Dados e Visualização de Dados.

A Arquitetura de Soluções foi implementada neste projeto por meio de decisões/ecolhas, entre elas: a arquitetura de medalhões (Bronze, Silver, Gold); a escolha do banco **PostgreSQL + PostGIS** para lidar com dados espaciais; o design transacional da **Dead Letter Queue (DLQ)** para isolar registros corrompidos; e, principalmente, na escolha arquitetural de criar um **Manifesto em JSON (`silver_status.json`)** para servir de ponte de estado entre o banco relacional e o DVC.

A Engenharia de Software foi efetivada neste projeto por meio do **Git Workflow** (criação de *feature branches*, commits semânticos, abertura de Pull Requests e merge na `main`); a modularização do código isolando o contrato de dados e dicionários em um arquivo separado (`schemas.py`); o gerenciamento de ambiente via `requirements.txt` e isolamento de credenciais sensíveis via `.env`; além do tratamento defensivo de exceções e mecanismos de resiliência (*fallback* de engines e loops controlados com *try/except*).

A Engenharia de Dados foi executada neste projeto na construção dos pipelines de ingestão incremental com paginação via SODA API na camada Bronze/Raw, na aplicação do **Batch Chunking (100k linhas)** na camada Silver/Cleaned para evitar estouro de memória, nas transformações e higienizações textuais profundas (TRIM/UPPERCASE), na aplicação de filtros geográficos (*Bounding Box de NYC*), a tradução de coordenadas para o formato **OGC WKT (`POINT`)** e operações de *Upsert Atômico* (`ON CONFLICT DO UPDATE`) com criação de índices `B-Tree` e espaciais `GiST`.

A camada Gold/Aggregated e a Visualização de Dados são etapas ainda em planejamento e construção, mas o projeto está caminhando conforme o tempo e os compromissos permitem.

Repositório: 

#DataEngineering #MLOps #Python #Pydantic #PostgreSQL #PostGIS #DataScience #DataVersionControl #Backend

---
### Post 2 - Projeto NYC Data Vehicles Collisions - Arquitetura de Solução e Engenharia de Software

No post anterior fiz uma introdução falando sobre o dataset NYC Motor Vehicle Collisions e sobre o projeto que estou desenvolvendo. Neste post a proposta é detalhar as escolhas de **Arquitetura de Soluções** e **Engenharia de Software**.

Partindo da ideia de que Arquitetura não é sobre ferramentas, mas sobre decisões que garantam resiliência, governança e escala, adotei as soluções abaixo:

### Arquitetura de Soluções: O Design do Ecossistema

- **PostgreSQL + PostGIS:** Sendo a Geografia uma das minhas fundações profissionais, os dados espaciais são sempre um ponto de atenção. O banco de dados foi escolhido porque nos permite ir além do armazenamento de latitude/longitude como mero texto, mas converte as coordenadas para o formato nativo OGC WKT (`POINT`) e cria índices espaciais `GiST`, permitindo consultas geográficas complexas em milissegundos.
- **Dead Letter Queue (DLQ):** Em um pipelines reais, profissionais não deletam dados ruins e não permitem que quebrem a carga. Considerando isso, preocupei-me em desenhar uma DLQ transacional diretamente no banco para que os dados limpos não sejam inseridos na tabela principal (silver/cleaned), enquanto os registros problemáticos detectadas são desviados para uma tabela de rejeições, preservando o payload bruto para auditoria.
- **A Ponte JSON ➡️ DVC:** O Data Version Control (DVC) é incrível para versionar arquivos, mas ele não "olha" para dentro de bancos de dados relacionais. A solução arquitetural foi criar um **Manifesto de Estado (`silver_status.json`)**. Ao final de cada carga, o script exporta os metadados técnicos e volumetrias. O DVC rastreia esse JSON e amarra o estado do banco ao histórico do Git via *lockfiles* matemáticos (`dvc.lock`).

### Engenharia de Software em Soluções de Dados

- **Modularização e Contratos:** Isolei a governança de mapeamento de colunas e validações de contrato do Pydantic em um arquivo independente (`schemas.py`) a fim de limpar o script principal e garantir reuso. O gerenciamento de ambiente é feito com `requirements.txt` e o isolamento de credenciais via `.env`.
- **Git Workflow** Para manter a disciplina, mesmo não trabalhando em equipe mantenho a rotina de PR e Merge para não perder a prática. O desenvolvimento na branch `feature/silver-governance-mlops` seguiu o fluxo: criação de ramificações isoladas, commits semânticos detalhados, abertura de Pull Requests e Code Review próprio antes do merge definitivo na `main`.
- **Programação Defensiva e Resiliência:** Para proteger o pipeline contra falhas de I/O e quebra de delimitadores na fonte de dados pública, implementei um mecanismo de *Fallback de Engines*, ou seja, o script tenta ler os dados via PyArrow (visando ganho de performance), contudo, se encontrar uma linha malformada com aspas truncadas, o bloco `except` captura a falha e aciona o motor padrão em `C` com regras de descarte pontual. O pipeline melhorou sua perfomance quanto aos travamentos (*deadlocks*).

### Engenharia de Dados: Manipulação, Escala e Otimização Volumétrica

- **Processamento Vetorizado em Lote (*Batch Chunking Engine*):** Manipular um DataFrame de 2,26 milhões de linhas na memória RAM de uma só vez provocaria um estouro de memória (*Out of Memory*). Neste pronto escolhemos dividir a Camada Silver em blocos de 100.000 registros por iteração, garantindo a estabilidade contínua da CPU local e permitindo que a validação do Pydantic de forma escalável e performática.

- **Engenharia Espaço-Temporal:** Com relação à temporalidade, as colunas primitivas de data e hora foram unificadas em um carimbo de tempo único (timestamp) de Nova York (`America/New_York`) para tratar as ambiguidades do horário de verão. O vetor resultante foi transformado para o padrão universal UTC (`crash_timestamp`) e os atributos derivados para o BI (ano, mês, dia da semana e faixas horárias) foram então extraídos.

- Para tratamento da espacialidade, foi aplicada uma máscara booleana estrita (*NYC Bounding Box*) que neutraliza 11% das geolocalizações ruins ou zeradas e as força como `NULL`. O objetivo é não poluir o mapa, mas preservar a descrição das ruas. Em seguida, as coordenadas válidas foram traduzidas dinamicamente em strings **OGC WKT (`POINT`)**.

- **Persistência Idempotente, Upsert Atômico e Indexação:** A gravação física da base higienizada no banco de dados utiliza uma tabela temporária de staging (com lotes de 20.000 linhas) conectada a uma query de **Upsert Atômico** (`ON CONFLICT (collision_id) DO UPDATE`). Essa estratégia garante a idempotência do pipeline, ou seja, se o script rodar duas vezes, ele atualiza as métricas sem duplicar chaves primárias. Por fim, o banco constrói índices estruturais `B-Tree` para filtros cronológicos e índices espaciais `GiST` para a geometria do PostGIS, preparando a base para responder queries complexas em milissegundos.

### O Próximo Passo: Prototipagem Visual Ágil

Com as soluções de ingestão e armazenamento implementadas chegamos a um ponto de escolha. Antes de fechar a modelagem das tabelas agregadas da Camada Gold, optei pela  Prototipagem Orientada ao Valor.

No próximo post, vou detalhar como estou estruturando uma exploração de visualização de dados utilizando a biblioteca **Dash/Plotly** diretamente sobre a tabela completa da Silver. O objetivo? Descobrir visualmente os gráficos, o grão exato e os filtros que o negócio precisa antes de gastar poder consolidando os Data Marts definitivos.

Como o prazo não é uma preocupação neste projeto particular, meu objetivo é exercitar e aprofundar meu domínio sobre construções de soluções de TI/Dados.

Repositório: 

#DataEngineering #SoftwareEngineering #SolutionsArchitecture #PostGIS #PostgreSQL #Pydantic #MLOps #Python #Git




















---