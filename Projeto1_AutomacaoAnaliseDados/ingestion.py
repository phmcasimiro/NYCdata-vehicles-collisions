"""
PROJETO: AUTOMAÇÃO E ANÁLISE DE DADOS COM PYTHON
------------------------------------------------
Este script realiza o download automatizado de uma base de dados no Google Drive
e aciona a geração de um relatório estatístico por meio do software Quarto.
"""

import os
import time
import logging
import subprocess
from pathlib import Path

import pyautogui
from dotenv import load_dotenv

# CONFIGURAÇÕES DE LOGGINGS (Registros de ações e erros)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# CARREGAR VARIÁVEIS DE AMBIENTE DO ARQUIVO .env
load_dotenv()

# VARIÁVEIS GLOBAIS
DRIVE_LINK = os.getenv("DRIVE_LINK")
NOME_ARQUIVO = os.getenv("NOME_ARQUIVO_VENDAS")
PASTA_DOWNLOADS = Path.home() / "Downloads"
CAMINHO_ARQUIVO = PASTA_DOWNLOADS / NOME_ARQUIVO

# TEMPO PADRÃO ENTRE COMANDOS DO PYAUTOGUI
pyautogui.PAUSE = 1

#-----------------------------------------------#
# FUNÇÃO PARA ABRIR O NAVEGADOR E ACESSAR O LINK
#-----------------------------------------------#
def abrir_navegador_e_acessar(link):
    """Abre o Microsoft Edge e navega até o link especificado."""
    logging.info("Abrindo o navegador Edge...")
    pyautogui.press('win') # PRESSIONAR TECLA 'WIN' PARA ABRIR O MENU INICIAR
    pyautogui.write('edge') # ESCREVER 'EDGE' PARA BUSCAR O NAVEGADOR
    pyautogui.press('enter') # PRESSIONAR 'ENTER' PARA ABRIR O NAVEGADOR
    time.sleep(3) # AGUARDAR O NAVEGADOR ABRIR

    logging.info(f"Acessando o link: {link}") # INFORMAR O LINK QUE SERÁ ACESSADO
    pyautogui.write(link) # ESCREVER O LINK NO NAVEGADOR
    pyautogui.press('enter') # PRESSIONAR 'ENTER' PARA ACESSAR O LINK
    time.sleep(5) # AGUARDAR O SITE CARREGAR

#-----------------------------------------------#
# FUNÇÃO PARA BAIXAR A PLANILHA
#-----------------------------------------------#
def baixar_planilha():
    """Navega na interface do Google Drive para realizar o download."""
    logging.info("Iniciando navegação para download da planilha...")
    
    # CLICLAR 2 VEZES NA PASTA DO DRIVE
    pyautogui.click(x=356, y=385, clicks=2) # CLICAR 2 VEZES EM DETERMINADO LUGAR
    time.sleep(2) # AGUARDAR O CARREGAMENTO DA PASTA
    
    # CLICAR EM 3 PONTOS PARA ABRIR A LISTA DE AÇÕES
    pyautogui.click(x=925, y=382) # CLICAR EM DETERMINADO LUGAR
    time.sleep(2) # AGUARDAR A LISTA DE AÇÕES ABRIR
    
    # CLICAR EM TRANSFERIR/DOWNLOAD
    logging.info("Iniciando o download do arquivo...")
    pyautogui.click(x=967, y=347) # CLICAR EM DETERMINADO LUGAR
    
    # AGUARDAR O DOWNLOAD CONCLUIR (AJUSTÁVEL DEPENDENDO DA INTERNET)
    time.sleep(15)

#-----------------------------------------------#
# FUNÇÃO PARA GERAR O RELATÓRIO
#-----------------------------------------------#
def gerar_relatorio():
    """Chama o Quarto para compilar o relatório .qmd."""
    logging.info("Iniciando a geração do relatório via Quarto...")
    caminho_qmd = Path("Projeto1_AutomacaoAnaliseDados") / "sells_report.qmd"
    
    # EXECUTAR O QUARTO DE FORMA SÍNCRONA
    subprocess.run(["quarto", "render", str(caminho_qmd)], shell=True, check=True)
    logging.info("Relatório gerado com sucesso!")

#----------------------------------------------#
# FUNÇÃO PARA LIMPAR ARQUIVOS TEMPORÁRIOS
#----------------------------------------------#
def limpar_arquivos_temporarios(caminho):
    """Deleta a planilha baixada após o uso."""
    logging.info("Limpando arquivos temporários...")
    if caminho.exists():
        caminho.unlink()
        logging.info("Arquivo da base de dados deletado com segurança.")
    else:
        logging.warning("O arquivo não foi encontrado para deleção.")

#----------------------------------------------#
# FUNÇÃO PRINCIPAL
#----------------------------------------------#
def main():
    """Função principal que orquestra todo o processo de automação."""
    logging.info("=== INICIANDO O PROCESSO DE AUTOMAÇÃO ===")
    
    if not DRIVE_LINK or not NOME_ARQUIVO: # VERIFICAR SE AS VARIÁVEIS DE AMBIENTE FORAM ENCONTRADAS
        logging.error("Variáveis de ambiente DRIVE_LINK ou NOME_ARQUIVO_VENDAS não encontradas no .env")
        return

    try:
        abrir_navegador_e_acessar(DRIVE_LINK) # ABRIR O NAVEGADOR E ACESSAR O LINK
        baixar_planilha() # BAIXAR A PLANILHA
        
        # O QUARTO VAI USAR O CAMINHO_ARQUIVO, ENTÃO ELE DEVE EXISTIR NESTE MOMENTO
        if not CAMINHO_ARQUIVO.exists():
            logging.error(f"O arquivo não foi encontrado em {CAMINHO_ARQUIVO}. Abortando.")
            return

        gerar_relatorio() # GERAR O RELATÓRIO
        limpar_arquivos_temporarios(CAMINHO_ARQUIVO) # LIMPAR OS ARQUIVOS TEMPORÁRIOS
        
        logging.info("=== PROCESSO DE AUTOMAÇÃO FINALIZADO COM SUCESSO ===")
        
    except subprocess.CalledProcessError as e:
        logging.error(f"Erro ao gerar o relatório com Quarto: {e}")
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado durante a automação: {e}")

if __name__ == "__main__":
    main()
