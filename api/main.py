from fastapi import FastAPI

app = FastAPI(
    title="Egypt Economic Intelligence Platform",
    description="API for Egyptian economic data and indicators.",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/prices/latest")
def get_latest_prices():
    return []


@app.get("/products/{product_id}/history")
def get_product_history(product_id: int):
    return []


@app.get("/index")
def get_index():
    return []


@app.get("/pipeline/status")
def get_pipeline_status():
    return []