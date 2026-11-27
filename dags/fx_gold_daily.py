# Airflow DAG file: this comment keeps the words "airflow" and "dag" so Airflow parses the file.
from src.common.pipeline import make_source_dag
from src.connectors.fx_gold import FxGoldConnector
from src.transform.api_staging import load_fx_gold_staging

dag = make_source_dag(
    dag_id="fx_gold_daily",
    source="fx_gold",
    connector_cls=FxGoldConnector,
    staging_fn=load_fx_gold_staging,
    staging_table="staging.fx_gold_clean",
    fact_table="dwh.fact_gold_fx",
    load_sql="load_fx_gold.sql",
)