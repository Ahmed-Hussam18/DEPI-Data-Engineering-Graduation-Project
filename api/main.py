import os
from contextlib import closing

import psycopg2
from fastapi import FastAPI, HTTPException
from psycopg2.extras import RealDictCursor

app = FastAPI(
    title="Egypt Economic Intelligence Platform",
    description="API for Egyptian economic data and indicators.",
    version="0.1.0",
)


def fetch_all(query: str, params=None):
    """Execute a read-only query and return its rows as dictionaries."""
    try:
        with closing(
            psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "eco"),
                user=os.getenv("DB_USER", "reader"),
                password=os.getenv("DB_PASSWORD"),
            )
        ) as connection:
            connection.set_session(readonly=True)

            with connection.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    except psycopg2.Error as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/prices/latest")
def get_latest_prices():
    return fetch_all(
        """
        SELECT *
        FROM serving.v_latest_prices
        ORDER BY product_id, source
        """
    )


@app.get("/products/{product_id}/history")
def get_product_history(product_id: str):
    return fetch_all(
        """
        SELECT *
        FROM serving.v_product_history
        WHERE product_id = %s
        ORDER BY price_date, source
        """,
        (product_id,),
    )


@app.get("/index")
def get_index():
    return fetch_all(
        """
        SELECT *
        FROM serving.v_basket_index
        ORDER BY index_date
        """
    )


@app.get("/pipeline/status")
def get_pipeline_status():
    return fetch_all(
        """
        SELECT *
        FROM serving.v_pipeline_status
        ORDER BY source
        """
    )
