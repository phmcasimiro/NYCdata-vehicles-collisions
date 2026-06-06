'''
# NYCdata/scripts/schemas.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime

# ==============================================================================
# 1. CONTRATO DE DADOS (DATA CONTRACT) - CAMADA SILVER
# ==============================================================================

class CollisionSilverSchema(BaseModel):
    """
    Schema do Pydantic para validação de tipos, integridade matemática e 
    sanitização automatizada de strings em tempo de execução para a Camada Silver.
    """
    # Chaves Primárias e Atributos Temporais
    collision_id: int = Field(..., description="Chave primária obrigatória do acidente.")
    crash_timestamp: datetime = Field(..., description="Carimbo de tempo unificado indexado em UTC.")
    crash_year: int = Field(..., ge=2012, description="Ano limite mínimo baseado no histórico do projeto.")
    crash_month: int = Field(..., ge=1, le=12)
    crash_day_of_week: int = Field(..., ge=0, le=6)
    time_bucket: str
    
    # Dados Geográficos e de Localização
    borough: str
    zip_code: str
    latitude: Optional[float] = Field(None)
    longitude: Optional[float] = Field(None)
    location_text: str
    
    # Logradouros e Vias
    on_street_name: str
    off_street_name: str
    cross_street_name: str
    
    # Estatísticas de Vítimas (Garantia de não-negatividade)
    total_persons_injured: int = Field(0, ge=0)
    total_persons_killed: int = Field(0, ge=0)
    pedestrians_injured: int = Field(0, ge=0)
    pedestrians_killed: int = Field(0, ge=0)
    cyclists_injured: int = Field(0, ge=0)
    cyclists_killed: int = Field(0, ge=0)
    motorists_injured: int = Field(0, ge=0)
    motorists_killed: int = Field(0, ge=0)
    
    # Fatores Contribuintes
    contributing_factor_vehicle_1: str
    contributing_factor_vehicle_2: str
    contributing_factor_vehicle_3: str
    contributing_factor_vehicle_4: str
    contributing_factor_vehicle_5: str
    
    # Tipologias de Veículos
    vehicle_type_code_1: str
    vehicle_type_code_2: str
    vehicle_type_code_3: str
    vehicle_type_code_4: str
    vehicle_type_code_5: str
    
    # Linhagem de Auditoria e Controle
    silver_processed_at: datetime
    pipeline_version: str

    # --------------------------------------------------------------------------
    # VALIDHADORES NATIVOS - SANITIZAÇÃO TEXTUAL AGRESSIVA
    # --------------------------------------------------------------------------
    @field_validator(
        "borough", "zip_code", "location_text", "time_bucket",
        "on_street_name", "off_street_name", "cross_street_name",
        "contributing_factor_vehicle_1", "contributing_factor_vehicle_2",
        "contributing_factor_vehicle_3", "contributing_factor_vehicle_4",
        "contributing_factor_vehicle_5",
        "vehicle_type_code_1", "vehicle_type_code_2", "vehicle_type_code_3",
        "vehicle_type_code_4", "vehicle_type_code_5",
        mode="before"
    )
    @classmethod
    def sanitize_categorical_strings(cls, value: any, info) -> str:
        """
        Intercepta os dados de texto e trata de forma cirúrgica os nulos,
        strings em branco e as anomalias textuais geradas pelo casting ('NONE', 'NAN').
        """
        if value is None or pd.isna(value):
            return "UNKNOWN" if info.field_name in ["borough", "on_street_name", "off_street_name", "cross_street_name", "location_text", "zip_code"] else "UNSPECIFIED"
        
        # Limpa espaços nas pontas e força para Letras Maiúsculas
        clean_str = str(value).strip().upper()
        
        # Alvo do nosso troubleshooting: Captura as strings fantasmas geradas por falha de parse
        if clean_str in ["", "NAN", "NONE", "NULL"]:
            # Separa os literais padrão por contexto analítico (UNKNOWN para locais, UNSPECIFIED para fatores/veículos)
            if info.field_name in ["borough", "on_street_name", "off_street_name", "cross_street_name", "location_text", "zip_code"]:
                return "UNKNOWN"
            else:
                return "UNSPECIFIED"
                
        return clean_str

# É preciso importar o pandas dentro do escopo ou no topo do arquivo para o pd.isna funcionar
import pandas as pd


# ==============================================================================
# 2. MAPEAMENTO OFICIAL DE LINHAGEM (MANTIDO INTACTO)
# ==============================================================================
MAP_BRONZE_TO_SILVER = {
    "crash_date": "raw_crash_date",
    "crash_time": "raw_crash_time",
    "borough": "borough",
    "zip_code": "zip_code",
    "latitude": "raw_latitude",
    "longitude": "raw_longitude",
    "location": "location_text",
    "on_street_name": "on_street_name",
    "off_street_name": "off_street_name",
    "cross_street_name": "cross_street_name",
    "number_of_persons_injured": "total_persons_injured",
    "number_of_persons_killed": "total_persons_killed",
    "number_of_pedestrians_injured": "pedestrians_injured",
    "number_of_pedestrians_killed": "pedestrians_killed",
    "number_of_cyclist_injured": "cyclists_injured",
    "number_of_cyclist_killed": "cyclists_killed",
    "number_of_motorist_injured": "motorists_injured",
    "number_of_motorist_killed": "motorists_killed",
    "contributing_factor_vehicle_1": "contributing_factor_vehicle_1",
    "contributing_factor_vehicle_2": "contributing_factor_vehicle_2",
    "contributing_factor_vehicle_3": "contributing_factor_vehicle_3",
    "contributing_factor_vehicle_4": "contributing_factor_vehicle_4",
    "contributing_factor_vehicle_5": "contributing_factor_vehicle_5",
    "collision_id": "collision_id",
    "vehicle_type_code1": "vehicle_type_code_1",
    "vehicle_type_code2": "vehicle_type_code_2",
    "vehicle_type_code_3": "vehicle_type_code_3",
    "vehicle_type_code_4": "vehicle_type_code_4",
    "vehicle_type_code_5": "vehicle_type_code_5"
}
'''
# ------------------------------------------------------------------------------

# NYCdata/scripts/schemas.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import pandas as pd

# ==============================================================================
# 1. CONTRATO DE DADOS (DATA CONTRACT) - CAMADA SILVER
# ==============================================================================

class CollisionSilverSchema(BaseModel):
    """
    Schema do Pydantic para validação de tipos, integridade matemática e 
    sanitização automatizada de strings em tempo de execução para a Camada Silver.
    """
    # Chaves Primárias e Atributos Temporais (ESTRITOS E OBRIGATÓRIOS)
    collision_id: int = Field(..., description="Chave primária obrigatória do acidente.")
    crash_timestamp: datetime = Field(..., description="Carimbo de tempo unificado indexado em UTC.")
    crash_year: int = Field(..., ge=2012, description="Ano limite mínimo baseado no histórico do projeto.")
    crash_month: int = Field(..., ge=1, le=12)
    crash_day_of_week: int = Field(..., ge=0, le=6)
    time_bucket: str
    
    # Dados Geográficos e de Localização
    borough: str
    zip_code: str
    latitude: Optional[float] = Field(None)
    longitude: Optional[float] = Field(None)
    location_text: str
    
    # Logradouros e Vias
    on_street_name: str
    off_street_name: str
    cross_street_name: str
    
    # Métricas de Severidade e Vítimas
    total_persons_injured: int = Field(..., ge=0)
    total_persons_killed: int = Field(..., ge=0)
    pedestrians_injured: int = Field(..., ge=0)
    pedestrians_killed: int = Field(..., ge=0)
    cyclists_injured: int = Field(..., ge=0)
    cyclists_killed: int = Field(..., ge=0)
    motorists_injured: int = Field(..., ge=0)
    motorists_killed: int = Field(..., ge=0)
    
    # Fatores Contribuintes (Mapeamento Completo das 5 Colunas de Veículos)
    contributing_factor_vehicle_1: Optional[str] = Field(None)
    contributing_factor_vehicle_2: Optional[str] = Field(None)
    contributing_factor_vehicle_3: Optional[str] = Field(None)
    contributing_factor_vehicle_4: Optional[str] = Field(None)
    contributing_factor_vehicle_5: Optional[str] = Field(None)
    
    # Tipologia dos Veículos Envolvidos
    vehicle_type_code_1: Optional[str] = Field(None)
    vehicle_type_code_2: Optional[str] = Field(None)
    vehicle_type_code_3: Optional[str] = Field(None)
    vehicle_type_code_4: Optional[str] = Field(None)
    vehicle_type_code_5: Optional[str] = Field(None)

    # 💥 VALIDADOR DEFENSIVO E ESTRITO PARA IMPEDIR TIMESTAMPS NULOS (NaN / NaT)
    @field_validator('crash_timestamp', mode='before')
    @classmethod
    def reject_null_timestamps(cls, v):
        if v is None or pd.isna(v) or str(v).strip().lower() in ['nat', 'nan', 'null', '']:
            raise ValueError("O campo 'crash_timestamp' é obrigatório para a consistência analítica e não pode ser nulo.")
        return v

    # 🏙️ VALIDADOR PARA INFRAESTRUTURA URBANA E LOCALIZAÇÃO -> Mapeia para 'UNKNOWN'
    @field_validator('borough', 'zip_code', 'location_text', 'on_street_name', 'off_street_name', 'cross_street_name', mode='before')
    @classmethod
    def sanitize_infrastructure_strings(cls, v) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "UNKNOWN"
        cleaned = str(v).strip().upper()
        return cleaned if cleaned not in ["", "NAN", "NONE", "NULL"] else "UNKNOWN"

    # 🚗 VALIDADOR PARA OMNICHANNEL DE VEÍCULOS E FATORES -> Mapeia para 'UNSPECIFIED'
    @field_validator(
        'contributing_factor_vehicle_1', 'contributing_factor_vehicle_2', 'contributing_factor_vehicle_3', 
        'contributing_factor_vehicle_4', 'contributing_factor_vehicle_5', 'vehicle_type_code_1', 
        'vehicle_type_code_2', 'vehicle_type_code_3', 'vehicle_type_code_4', 'vehicle_type_code_5',
        mode='before'
    )
    @classmethod
    def sanitize_vehicle_strings(cls, v) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "UNSPECIFIED"
        cleaned = str(v).strip().upper()
        return cleaned if cleaned not in ["", "NAN", "NONE", "NULL"] else "UNSPECIFIED"

# ==============================================================================
# 2. DICIONÁRIO DE MAPEAMENTO CANÔNICO (BRONZE -> SILVER)
# ==============================================================================
MAP_BRONZE_TO_SILVER = {
    "crash_date": "raw_crash_date",
    "crash_time": "raw_crash_time",
    "borough": "borough",
    "zip_code": "zip_code",
    "latitude": "raw_latitude",
    "longitude": "raw_longitude",
    "location": "location_text",
    "on_street_name": "on_street_name",
    "off_street_name": "off_street_name",
    "cross_street_name": "cross_street_name",
    "number_of_persons_injured": "total_persons_injured",
    "number_of_persons_killed": "total_persons_killed",
    "number_of_pedestrians_injured": "pedestrians_injured",
    "number_of_pedestrians_killed": "pedestrians_killed",
    "number_of_cyclist_injured": "cyclists_injured",
    "number_of_cyclist_killed": "cyclists_killed",
    "number_of_motorist_injured": "motorists_injured",
    "number_of_motorist_killed": "motorists_killed",
    "contributing_factor_vehicle_1": "contributing_factor_vehicle_1",
    "contributing_factor_vehicle_2": "contributing_factor_vehicle_2",
    "contributing_factor_vehicle_3": "contributing_factor_vehicle_3",
    "contributing_factor_vehicle_4": "contributing_factor_vehicle_4",
    "contributing_factor_vehicle_5": "contributing_factor_vehicle_5",
    "collision_id": "collision_id",
    "vehicle_type_code1": "vehicle_type_code_1",
    "vehicle_type_code2": "vehicle_type_code_2",
    "vehicle_type_code_3": "vehicle_type_code_3",
    "vehicle_type_code_4": "vehicle_type_code_4",
    "vehicle_type_code_5": "vehicle_type_code_5"
}