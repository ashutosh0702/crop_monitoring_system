from fastapi import FastAPI
from src.modules.auth import router as auth_router
from src.modules.farms import router as farms_router

app = FastAPI(title="Crop Monitoring System API")

# Register Modules
app.include_router(auth_router.router)
app.include_router(farms_router.router)

@app.get("/")
def root():
    return {"message": "System is Online. Use /docs for Swagger UI"}