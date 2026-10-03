from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.email import AllowedDomain
from app.schemas.email import AllowedDomainCreate, AllowedDomainUpdate, AllowedDomainOut
from app.models.user import User
from app.routers.auth import require_admin

router = APIRouter(tags=["domains"])


@router.get("", response_model=List[AllowedDomainOut])
def list_domains(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return db.query(AllowedDomain).order_by(AllowedDomain.domain).all()


@router.post("", response_model=AllowedDomainOut, status_code=status.HTTP_201_CREATED)
def create_domain(payload: AllowedDomainCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    domain_lower = payload.domain  # normalised + validated by the schema
    existing = db.query(AllowedDomain).filter(AllowedDomain.domain == domain_lower).first()
    if existing:
        raise HTTPException(status_code=409, detail="Domain already exists")
    obj = AllowedDomain(domain=domain_lower, notes=payload.notes)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/{domain_id}", response_model=AllowedDomainOut)
def update_domain(domain_id: int, payload: AllowedDomainUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    obj = db.query(AllowedDomain).filter(AllowedDomain.id == domain_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Domain not found")
    if payload.is_active is not None:
        obj.is_active = payload.is_active
    if payload.notes is not None:
        obj.notes = payload.notes
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_domain(domain_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    obj = db.query(AllowedDomain).filter(AllowedDomain.id == domain_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Domain not found")
    db.delete(obj)
    db.commit()
