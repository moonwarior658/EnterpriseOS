from fastapi import FastAPI

app = FastAPI(
    title="EnterpriseOS API",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "eos-api",
        "version": "0.1.0",
    }
