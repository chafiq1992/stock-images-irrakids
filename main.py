from fastapi import FastAPI, Request
from utils import handle_variant_update

app = FastAPI()

@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        payload = await request.json()
        handle_variant_update(payload)
        return {"status": "ok"}
    except Exception as e:
        print(f"⚠️ Webhook error: {e}")
        return {"status": "error", "message": str(e)}
