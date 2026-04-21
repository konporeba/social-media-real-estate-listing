from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Browser Worker")


class ExtractRequest(BaseModel):
    url: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/extract")
async def extract(req: ExtractRequest):
    # Stub — full Playwright implementation in Gate 7
    return {
        "url": req.url,
        "title": None,
        "price": None,
        "area": None,
        "rooms": None,
        "floor": None,
        "description": None,
        "features": [],
        "category": None,
        "image_url": None,
        "image_bytes": None,
    }
