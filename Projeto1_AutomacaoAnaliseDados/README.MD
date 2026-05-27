# Projeto 1: Automação e Análise de Dados com Python

> **Objetivo:** Automatizar a coleta, análise e geração de relatórios de dados de vendas, eliminando o trabalho manual diário do analista e entregando um documento executivo formatado para a diretoria.

---

## Situação Problema

Em muitas empresas, um analista realiza diariamente o seguinte fluxo manual:
1. Acessa o sistema de vendas (Google Drive).
2. Baixa a planilha de vendas do dia.
3. Abre o Excel, realiza cálculos e monta um relatório.
4. Envia o relatório por e-mail para a diretoria.

Este projeto **automatiza 100% desse fluxo** usando Python e Quarto.

---

## Arquitetura do Projeto

O projeto é composto por **dois arquivos complementares** com responsabilidades separadas — uma prática fundamental na Engenharia de Software conhecida como **Separação de Responsabilidades**.

```
Projeto1_AutomacaoAnaliseDados/
│
├── ingestion.py          ← O ROBÔ: coleta e orquestra o processo
├── develop.ipynb         ← O LABORATÓRIO: exploração e análise de dados
├── sells_report.qmd      ← O MOTOR: geração do relatório executivo
│
├── .env                  ← Variáveis de ambiente (não subir no GitHub!)
├── .env.example          ← Template de variáveis para novos desenvolvedores
└── requirements.txt      ← Dependências do projeto
```

---

## Descrição dos Arquivos Principais

### `ingestion.py` — O Robô (Robotic Process Automation - RPA)

**Responsabilidade:** Automação de interface (RPA) e orquestração do pipeline completo.

Este script é o **ponto de entrada** do sistema. Quando executado, ele realiza todo o fluxo de forma autônoma:

| Etapa | Função | O que faz |
|:---:|:---|:---|
| 1 | `abrir_navegador_e_acessar()` | Abre o Microsoft Edge e acessa o link do Google Drive. |
| 2 | `baixar_planilha()` | Navega na interface do Drive e realiza o download da planilha de vendas. |
| 3 | `gerar_relatorio()` | Chama o software **Quarto** para processar o `sells_report.qmd` e gerar o HTML. |
| 4 | `limpar_arquivos_temporarios()` | Deleta a planilha `.xlsx` da pasta Downloads após o uso. |

**Boas práticas implementadas:**
- **Logging profissional:** Todas as ações são registradas com data e hora.
- **Variáveis de ambiente:** Links e nomes de arquivos lidos de um `.env`.
- **Caminhos dinâmicos:** Usa `pathlib` para funcionar em qualquer computador.
- **Tratamento de erros:** Erros são capturados e registrados sem "explodir" o programa.
- **Modularização:** Cada etapa é uma função com uma única responsabilidade.

---

### `develop.ipynb` — Arquivo do Analista construído com Jupyter Notebook

**Responsabilidade:** Exploração de dados, prototipagem e documentação técnica.

Este notebook foi desenvolvido como **ambiente de desenvolvimento e adaptação** do projeto.

Com este notebook o analista pode rodar o relatório todos dos dias e adaptar quando necessário, sem alterar o código do robô que foi desenvolvido para um ambiente de produção.

| Seção | Conteúdo |
|:---|:---|
| **Situação Problema** | Descrição do desafio de negócio e proposta de solução. |
| **Automação (RPA)** | Protótipo do código `pyautogui` com descoberta de coordenadas de mouse. |
| **Análise Descritiva** | Cálculos de Faturamento, Ticket Médio, Moda, Mediana e Desvio Padrão. |
| **Visualização** | Construção do Boxplot + Histograma interativo com Plotly. |
| **Cheat Sheet** | Guia de referência rápida do `pyautogui` para novos desenvolvedores. |

> **Dica:** Use o `develop.ipynb` para entender cada etapa individualmente. O `ingestion.py` é a versão "produtiva" final deste notebook.

---

## Como Executar o Projeto

### Pré-requisitos
- Python 3.12+
- [Quarto](https://quarto.org/docs/get-started/) instalado no computador.
- Microsoft Edge instalado.

### 1. Clonar o repositório e criar o ambiente virtual

```bash
git clone https://github.com/phmcasimiro/GeoDev.git
cd GeoDev

python -m venv venv
venv\scripts\activate
```

### 2. Instalar as dependências

```bash
pip install -r Projeto1_AutomacaoAnaliseDados/requirements.txt
```

### 3. Configurar as variáveis de ambiente

Copie o arquivo de exemplo e preencha com os seus dados:

```bash
# Copie o .env.example para .env
copy Projeto1_AutomacaoAnaliseDados\.env.example Projeto1_AutomacaoAnaliseDados\.env
```

Edite o arquivo `.env` criado:

```env
DRIVE_LINK=https://drive.google.com/drive/folders/seu_link_aqui
NOME_ARQUIVO_VENDAS=Vendas - Dez.xlsx
```

### 4. Executar o robô

```bash
python Projeto1_AutomacaoAnaliseDados\ingestion.py
```

O processo completo será executado automaticamente. Ao final, um arquivo `sells_report.html` será gerado na pasta do projeto.

---

## Observações Importantes

> **Coordenadas do Mouse:** O script `ingestion.py` usa coordenadas fixas `(x, y)` para cliques no Google Drive. Essas coordenadas foram calibradas para uma resolução específica de tela. **Se você mudar de monitor ou redimensionar a janela, será necessário recalibrar.** Use o trecho abaixo para descobrir as coordenadas corretas:
> ```python
> import pyautogui, time
> time.sleep(5)
> print(pyautogui.position())
> ```

---

## Autor

**Pedro Henrique** | Ciência de Dados & Automação  
Repositório: [github.com/phmcasimiro/GeoDev](https://github.com/phmcasimiro/GeoDev)
