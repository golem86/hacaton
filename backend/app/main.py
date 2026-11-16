from fastapi import FastAPI

app = FastAPI(title="Integrity Dashboard API")

@app.get("/")
def hello():
    return {"message": "Integrity Dashboard працює"}