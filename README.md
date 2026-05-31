# NYCdata Vehicles Collisions Pipeline

# Pipeline de Dados: Colisões de Veículos de Nova York (NYC)

Este projeto consiste no desenvolvimento de um pipeline de dados para o processamento, armazenamento e visualização do conjunto de dados público *NYC Motor Vehicle Collisions*, que contabiliza mais de 2,26 milhões de registros de acidentes de trânsito. O sistema adota a arquitetura de medalhões (divida em camadas Bronze, Silver e Gold) para estruturar o fluxo da informação a partir da coleta bruta até a disponibilidade analítica.

## Estágio Atual de Desenvolvimento

### 1. Camada Bronze (Ingestão)
* Realização da coleta incremental de dados brutos diretamente da API SODA (*Socrata Open Data API*).
* Utilização de mecanismos de paginação para a transferência dos dados da origem para o armazenamento local.

### 2. Camada Silver (Higienização e Governança)
* Validação estrutural e de tipagem dos dados por meio de contratos de esquema implementados com a biblioteca Pydantic.
* Processamento dos dados em blocos (*chunks*) de 100.000 registros para controle do consumo de memória RAM.
* Isolamento de registros que violam as regras de validação em uma estrutura de desvio (*Dead Letter Queue* - DLQ) para fins de auditoria.
* Filtragem geográfica de coordenadas via caixa delimitadora (*bounding box*) dos limites espaciais da cidade de Nova York.
* Conversão de dados de latitude e longitude para o formato geométrico padrão *Well-Known Text* (WKT `POINT`).
* Persistência dos dados processados em banco de dados PostgreSQL com extensão espacial PostGIS, estruturados com índices GiST (espaciais) e B-Tree (temporais).

### 3. Orquestração e Automação
* Mapeamento de dependências e execução das etapas do pipeline estruturados em um Grafo Acíclico Direcionado (DAG) controlado via ferramenta *Data Version Control* (DVC).
* Automação de execução configurada para disparos diários às 13:00 h por meio do Agendador de Tarefas do sistema operacional Windows, que invoca um script de lote (`.bat`) encarregado de ativar o ambiente virtual Python e acionar o DVC.

### 4. Camada Gold e Visualização (Em Construção)
* Desenvolvimento de protótipo de interface gráfica para visualização de dados por meio da biblioteca Dash.
* Definição da granularidade e dos agrupamentos para consolidação das tabelas agregadas finais (*Data Marts*).

## ÁRVORE DE DIRETÓRIOS E ARQUIVOS

```
GeoDev/
├── .dvc/
├── .dvcignore
├── .gitignore
├── dvc.lock
├── dvc.yaml
├── NYCdata/
│   ├── .env
│   ├── data/
│   │   └── bronze_raw/
│   ├── docker-compose.yml
│   ├── metadata/
│   │   ├── .gitignore
│   │   └── silver_status.json
│   ├── NYCdata_MotorVehicleCollisions.ipynb
│   ├── pipeline_nyc.bat
│   ├── README.md
│   ├── run_pipeline.bat
│   └── scripts/
│       ├── 1_nycdata_etl.py
│       ├── 2_nycdata_silver.py
│       ├── 2_nycdata_silver_v1.py
│       ├── __pycache__/
│       └── schemas.py
├── posts.md
├── README.md
├── requirements.txt
└── venv/
```
