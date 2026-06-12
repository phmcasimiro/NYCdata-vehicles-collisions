# RELATÓRIO DE AVALIAÇÃO ARQUITETURAL E DE ENGENHARIA DE SOFTWARE

**Autor:** Desenvolvedor Sênior (Google)  
**Projeto:** GeoDev - NYC Open Data Vehicles Collisions  
**Status do Sistema:** Análise de Prontidão para Produção (Production Readiness)  
**Cenário de Escopo:** Disponibilização de Dashboard para ~200 usuários simultâneos/ativos.  

---

## 1. INTRODUÇÃO E VISÃO GERAL
Este documento apresenta uma revisão crítica da arquitetura e das práticas de Engenharia de Software adotadas no projeto **GeoDev**. O ecossistema é avaliado sob a ótica de escalabilidade, resiliência, segurança, performance e capacidade de suportar uma carga de **200 usuários ativos**.

O projeto demonstra excelente maturidade no desenho do pipeline de dados, utilizando conceitos modernos da Engenharia de Dados (Arquitetura Medallion, PostGIS, DVC). Contudo, a transição para um ambiente produtivo com múltiplos usuários exige ajustes significativos na camada de aplicação, no gerenciamento de conexões com o banco de dados e no servidor de aplicação.

---

## 2. PONTOS DE EXCELÊNCIA (PONTOS FORTES)

O projeto se destaca por implementar padrões que garantem a integridade dos dados e otimizam a computação no lado do servidor:

*   **Query Pushdown via Materialized Views:** Em vez de realizar agregações pesadas em memória no servidor Python (usando Pandas), o projeto transfere o processamento para as Materialized Views do PostgreSQL (`pg_cron`). Isso reduz a volumetria de 2.2 milhões de linhas para menos de 1.000 registros antes de trafegar na rede.
*   **Contratos de Dados Rígidos (Pydantic):** A aplicação do crivo de validação estrutural desacoplado impede que dados sujos da API atinjam a camada analítica limpa, garantindo a consistência das métricas exibidas aos tomadores de decisão.
*   **Padrão Dead Letter Queue (DLQ):** O isolamento de registros inválidos em uma tabela física de rejeições (`nycdata_vehicle_collisions_rejections`) garante a resiliência do pipeline e permite depuração assíncrona.
*   **Idempotência nativa via Upsert:** O uso de tabelas de Staging temporárias combinadas com a instrução `ON CONFLICT` blinda o ecossistema contra duplicação de dados sob múltiplas execuções.
*   **Engine Fallback Resiliente:** O tratamento de exceções no parsing de arquivos (chaveando entre PyArrow e motor C) demonstra excelente preocupação com a robustez e continuidade operacional do ETL.
*   **Indexação Espaço-Temporal Avançada:** O uso de índices estruturais `B-Tree` em colunas de alta filtragem analítica e índices espaciais `GiST` no PostGIS garante respostas rápidas a consultas geográficas.

---

## 3. PONTOS DE MELHORIA (GARGALOS PARA 200 USUÁRIOS)

Para suportar 200 usuários simultâneos com estabilidade, identificamos os seguintes pontos críticos de melhoria:

1.  **Servidor de Aplicação de Desenvolvimento (Flask Dev Server):** O dashboard é iniciado via `app.run(debug=True)`. O servidor nativo do Flask é *monothreaded* e não foi projetado para produção. Com múltiplos acessos simultâneos, ele sofrerá travamentos por fila de requisições bloqueadas.
2.  **Exaustão do Pool de Conexões do Banco de Dados:** A criação padrão de conexões sem limites explícitos no SQLAlchemy pode estourar o limite máximo de conexões do contêiner PostgreSQL (`max_connections` por padrão é 100), provocando erros de `Too many clients` para os usuários.
3.  **Ausência de Caching de Callbacks (Custo Redundante no Banco):** Usuários frequentemente filtrarão os mesmos anos, distritos e trimestres. A falta de um mecanismo de cache faz com que o PostgreSQL processe queries redundantes de forma repetida.
4.  **Risco de Deadlocks no Refresh de Materialized Views:** A view de Fatores Contribuintes (`nycdata_vehicles_collisions_gold_fact_contributing_factors`) não possui índice único definido. Sem ele, a diretiva `REFRESH MATERIALIZED VIEW CONCURRENTLY` falhará, exigindo locks exclusivos que congelam as leituras do dashboard.
5.  **Logs em Texto Simples (`print`):** O pipeline e a aplicação usam `print()` para saída de console. Em produção, isso dificulta a centralização de logs e a criação de alertas estruturados de monitoramento de integridade.

---

## 4. DETALHAMENTO DA IMPLEMENTAÇÃO DAS MELHORIAS

Abaixo, apresentamos os planos de ação e códigos sugeridos para sanar cada um dos pontos de melhoria elencados:

### Melhoria 1: Migração para Servidor WSGI de Produção (Waitress / Gunicorn)
No ambiente Windows da máquina do usuário, utilizaremos o **Waitress** como servidor WSGI (Web Server Gateway Interface), que gerencia requisições de forma concorrente e multi-threaded de forma estável.

**Como implementar:**
1. Instale o pacote `waitress`:
   ```bash
   pip install waitress
   ```
2. Modifique o ponto de entrada de execução do arquivo [3_nycdata_gold_dash.py](file:///c:/Users/HP/Documents/Projetos/GeoDev/NYCdata/scripts/3_nycdata_gold_dash.py):

```python
# No final de 3_nycdata_gold_dash.py
if __name__ == "__main__":
    # app.run(debug=True, port=8050) <- Remover do ambiente produtivo
    from waitress import serve
    print("🚀 Iniciando servidor corporativo Waitress na porta 8050 com 8 threads ativas...")
    serve(app.server, host="0.0.0.0", port=8050, threads=8)
```

---

### Melhoria 2: Otimização do Connection Pool do SQLAlchemy
Ajustar as propriedades de pooling do SQLAlchemy para gerenciar conexões persistentes e reutilizáveis, evitando criar e destruir sockets TCP a cada callback.

**Como implementar:**
Modifique a inicialização da engine de banco em [3_nycdata_gold_dash.py](file:///c:/Users/HP/Documents/Projetos/GeoDev/NYCdata/scripts/3_nycdata_gold_dash.py):

```python
# Configuração otimizada para até 200 usuários concorrentes
engine = create_engine(
    DATABASE_URL,
    pool_size=20,          # Mantém até 20 conexões ativas persistentes por worker
    max_overflow=30,       # Permite até 30 conexões adicionais sob pico de carga
    pool_timeout=30,       # Tempo de espera limite para obter conexão (segundos)
    pool_recycle=1800      # Recicla conexões a cada 30 minutos para evitar stales
)
```

---

### Melhoria 3: Implementação de Cache de Callbacks (Flask-Caching)
Adicionar cache em memória ou em arquivos no servidor de dashboard para armazenar o resultado das consultas SQL e processamentos gráficos baseados nos filtros selecionados pelo usuário.

**Como implementar:**
1. Instale o pacote `Flask-Caching`:
   ```bash
   pip install Flask-Caching
   ```
2. Configure o cache no script [3_nycdata_gold_dash.py](file:///c:/Users/HP/Documents/Projetos/GeoDev/NYCdata/scripts/3_nycdata_gold_dash.py):

```python
from flask_caching import Cache

# Inicializa o cache utilizando o sistema de arquivos local (ou Redis em produção cloud)
cache = Cache(app.server, config={
    'CACHE_TYPE': 'FileSystemCache',
    'CACHE_DIR': 'NYCdata/cache',
    'CACHE_DEFAULT_TIMEOUT': 300 # Cache válido por 5 minutos (300s)
})

# Decore a função principal de atualização com o cache memoizado
@app.callback(
    [Output("graph-map-choropleth", "figure"),
     Output("graph-temporal-evolution", "figure"),
     Output("graph-contributing-factors", "figure")],
    [Input("dropdown-borough", "value"),
     Input("dropdown-metric", "value"),  
     Input("dropdown-year", "value"),
     Input("dropdown-quarter", "value")] 
)
@cache.memoize() # 👈 Evita queries duplicadas no banco para as mesmas combinações de filtros
def update_dashboard(selected_borough, selected_metric, selected_year, selected_quarter):
    # Lógica interna do callback preservada...
```

---

### Melhoria 4: Ajuste do Índice Único para Refresh Concorrente
Para que a instrução `REFRESH MATERIALIZED VIEW CONCURRENTLY` funcione na view de fatores contribuintes sem travar as leituras dos usuários, é mandatória a criação de uma constraint ou índice único no PostgreSQL.

**Como implementar:**
Execute as seguintes instruções SQL no banco de dados (também documentadas e atualizadas no arquivo [querys.txt](file:///c:/Users/HP/Documents/Projetos/GeoDev/NYCdata/querys.txt)):

```sql
-- Remove o índice não-único antigo
DROP INDEX IF EXISTS idx_gold_factors_borough;

-- Cria um índice composto ÚNICO para satisfazer o requisito do REFRESH CONCURRENTLY
CREATE UNIQUE INDEX idx_gold_factors_unique_composite 
ON public.nycdata_vehicles_collisions_gold_fact_contributing_factors (borough, contributing_factor);
```
** Resultado da Implementação**
```sql
-- public.nycdata_vehicles_collisions_gold_fact_contributing_factors fonte

CREATE MATERIALIZED VIEW public.nycdata_vehicles_collisions_gold_fact_contributing_factors
TABLESPACE pg_default
AS SELECT COALESCE(NULLIF(unified_factors.borough::text, ''::text), 'UNKNOWN'::text) AS borough,
    EXTRACT(year FROM unified_factors.crash_timestamp)::integer AS year,
    EXTRACT(month FROM unified_factors.crash_timestamp)::integer AS month,
    unified_factors.contributing_factor,
    count(*) AS total_collisions
   FROM ( SELECT nycdata_vehicle_collisions_cleaned.borough,
            nycdata_vehicle_collisions_cleaned.crash_timestamp,
            nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_1 AS contributing_factor
           FROM nycdata_vehicle_collisions_cleaned
          WHERE nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_1 IS NOT NULL
        UNION ALL
         SELECT nycdata_vehicle_collisions_cleaned.borough,
            nycdata_vehicle_collisions_cleaned.crash_timestamp,
            nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_2
           FROM nycdata_vehicle_collisions_cleaned
          WHERE nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_2 IS NOT NULL
        UNION ALL
         SELECT nycdata_vehicle_collisions_cleaned.borough,
            nycdata_vehicle_collisions_cleaned.crash_timestamp,
            nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_3
           FROM nycdata_vehicle_collisions_cleaned
          WHERE nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_3 IS NOT NULL
        UNION ALL
         SELECT nycdata_vehicle_collisions_cleaned.borough,
            nycdata_vehicle_collisions_cleaned.crash_timestamp,
            nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_4
           FROM nycdata_vehicle_collisions_cleaned
          WHERE nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_4 IS NOT NULL
        UNION ALL
         SELECT nycdata_vehicle_collisions_cleaned.borough,
            nycdata_vehicle_collisions_cleaned.crash_timestamp,
            nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_5
           FROM nycdata_vehicle_collisions_cleaned
          WHERE nycdata_vehicle_collisions_cleaned.contributing_factor_vehicle_5 IS NOT NULL) unified_factors
  WHERE unified_factors.contributing_factor <> ALL (ARRAY[''::text, 'UNSPECIFIED'::text, 'UNKNOWN'::text, 'Unspecified'::text])
  GROUP BY unified_factors.borough, (EXTRACT(year FROM unified_factors.crash_timestamp)), (EXTRACT(month FROM unified_factors.crash_timestamp)), unified_factors.contributing_factor
WITH DATA;

-- View indexes:
CREATE INDEX idx_gold_factors_categorical ON public.nycdata_vehicles_collisions_gold_fact_contributing_factors USING btree (contributing_factor);
CREATE UNIQUE INDEX idx_gold_factors_unique_composite ON public.nycdata_vehicles_collisions_gold_fact_contributing_factors USING btree (year, month, borough, contributing_factor);
```
---

### Melhoria 5: Implementação de Logging Estruturado
Substituir os comandos `print` por logs estruturados usando o módulo padrão `logging` do Python, permitindo auditorias e rastreamento de erros facilitados.

**Como implementar:**
Configure o logging no topo de todos os scripts principais:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("NYCdata/metadata/pipeline.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("GeoDevApp")

# Exemplo de uso:
# logger.info("Conexão estabelecida com sucesso!")
# logger.error("Falha ao consultar view materializada: %s", str(e))
```
