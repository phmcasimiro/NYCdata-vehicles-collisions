@echo off
:: 1. Navega ate a pasta raiz do projeto GeoDev
cd /d "C:\Users\HP\Documents\Projetos\GeoDev"

:: 2. Ativa o ambiente virtual do Python (venv)
call venv\Scripts\activate

:: 3. Executa o script de ingestao Bronze
python NYCdata/scripts/1_nycdata_etl.py

:: 4. Desativa o venv ao encerrar
deactivate