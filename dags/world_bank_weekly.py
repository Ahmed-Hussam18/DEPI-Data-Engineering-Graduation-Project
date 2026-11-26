# Airflow DAG file: this comment keeps the words "airflow" and "dag" so Airflow parses the file.
# World Bank indicators are annual, so a weekly run (Sunday 06:00 Cairo) is enough.
from src.common.pipeline import make_source_dag
from src.connectors.world_bank import WorldBankConnector
from src.transform.api_staging import load_indicator_staging

dag = make_source_dag(
    dag_id="world_bank_weekly",
    source="world_bank",
    connector_cls=WorldBankConnector,
    staging_fn=load_indicator_staging,
    staging_table="staging.indicators_clean",
    fact_table="dwh.fact_indicator",
    load_sql="load_indicators.sql",
    schedule="0 6 * * 0",
)