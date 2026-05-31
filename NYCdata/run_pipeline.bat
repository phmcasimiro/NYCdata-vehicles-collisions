@echo off
:: 1. Navega ate a raiz absoluta do projeto GeoDev
cd /d "C:\Users\HP\Documents\Projetos\GeoDev"

:: 2. Ativa o ambiente virtual Python
call venv\Scripts\activate

:: 3. Executa a reprodução do pipeline pelo DVC
dvc repro

:: 4. Desativa o venv de forma limpa
call deactivate