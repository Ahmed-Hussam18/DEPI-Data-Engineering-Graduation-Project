# Airflow DAG file: this comment keeps the words "airflow" and "dag" so Airflow parses the file.
# The CBE publishes urban CPI monthly, so a monthly run (1st of each month at 06:00 Cairo) is enough.
from src.common.pipeline import make_source_dag
from src.connectors.official_file import OfficialFileConnector
from src.transform.official_staging import load_official_file_staging

dag = make_source_dag(
    dag_id="official_file_monthly",
    source="official_file",
    connector_cls=OfficialFileConnector,
    staging_fn=load_official_file_staging,
    staging_table="staging.indicators_clean",
    fact_table="dwh.fact_indicator",
    load_sql="load_indicators.sql",
    schedule="0 6 1 * *",
)