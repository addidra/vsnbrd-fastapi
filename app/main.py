from fastapi import FastAPI, Query, Response
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import requests
import os

load_dotenv()

TELE_FILE_URL = os.getenv("TELE_FILE_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origin=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": TELE_FILE_URL}

@app.get('/getImage')
def getImage(file_path: str = Query(...)):
    try:
        url = f'{TELE_FILE_URL}{file_path}'
        response = requests.get(url)
        return Response(content=response.content, media_type='image/png')
    except Exception as e:
        return e