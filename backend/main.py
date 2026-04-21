from fastapi import FastAPI

app = FastAPI(title="Social Agent API")


@app.get("/health")
async def health():
    return {"status": "ok"}
