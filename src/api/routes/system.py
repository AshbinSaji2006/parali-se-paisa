from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.api.dependencies import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
def health(session: Session = Depends(get_db)):
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected", "api_version": "v1",
            "provenance_policy": "synthetic fixtures explicitly labelled; live sources unverified"}
