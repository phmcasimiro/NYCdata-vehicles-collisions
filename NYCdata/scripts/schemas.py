# NYCdata/scripts/schemas.py

# Mapeamento Oficial de Linhagem: Bronze (Raw API) -> Camada Silver (Cleaned)
# Mantendo o padrão snake_case internacionalizado para portfólio estrangeiro
MAP_BRONZE_TO_SILVER = {
    # Temporal Metadata (Serão unificadas na engenharia de atributos)
    "crash_date": "raw_crash_date",
    "crash_time": "raw_crash_time",
    
    # Geographic & Categorical Metadata
    "borough": "borough",
    "zip_code": "zip_code",
    "latitude": "raw_latitude",
    "longitude": "raw_longitude",
    "location": "location_text",
    
    # Street & Infrastructure Data
    "on_street_name": "on_street_name",
    "off_street_name": "off_street_name",
    "cross_street_name": "cross_street_name",
    
    # Victim Statistics (Ainda double precision, serão castadas para INTEGER)
    "number_of_persons_injured": "total_persons_injured",
    "number_of_persons_killed": "total_persons_killed",
    "number_of_pedestrians_injured": "pedestrians_injured",
    "number_of_pedestrians_killed": "pedestrians_killed",
    "number_of_cyclist_injured": "cyclists_injured",
    "number_of_cyclist_killed": "cyclists_killed",
    "number_of_motorist_injured": "motorists_injured",
    "number_of_motorist_killed": "motorists_killed",
    
    # Contributing Factors
    "contributing_factor_vehicle_1": "contributing_factor_vehicle_1",
    "contributing_factor_vehicle_2": "contributing_factor_vehicle_2",
    "contributing_factor_vehicle_3": "contributing_factor_vehicle_3",
    "contributing_factor_vehicle_4": "contributing_factor_vehicle_4",
    "contributing_factor_vehicle_5": "contributing_factor_vehicle_5",
    
    # Primary Key
    "collision_id": "collision_id",
    
    # Vehicle Types (Neutralizando as quebras de padrão de sublinhados da API)
    "vehicle_type_code1": "vehicle_type_code_1",
    "vehicle_type_code2": "vehicle_type_code_2",
    "vehicle_type_code_3": "vehicle_type_code_3",
    "vehicle_type_code_4": "vehicle_type_code_4",
    "vehicle_type_code_5": "vehicle_type_code_5"
}