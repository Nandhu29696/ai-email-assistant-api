"""
Lookups router — static reference data for UI dropdowns.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.email import SentimentOption, PriorityOption, CategoryOption
from app.schemas.email import SentimentOptionOut, PriorityOptionOut, CategoryOptionOut

router = APIRouter()


@router.get("/sentiments", response_model=list[SentimentOptionOut])
def list_sentiments(db: Session = Depends(get_db)):
    return (
        db.query(SentimentOption)
        .order_by(SentimentOption.sort_order)
        .all()
    )


@router.get("/priorities", response_model=list[PriorityOptionOut])
def list_priorities(db: Session = Depends(get_db)):
    return (
        db.query(PriorityOption)
        .order_by(PriorityOption.sort_order)
        .all()
    )


@router.get("/categories", response_model=list[CategoryOptionOut])
def list_categories(db: Session = Depends(get_db)):
    return (
        db.query(CategoryOption)
        .order_by(CategoryOption.sort_order)
        .all()
    )
