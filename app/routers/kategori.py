"""Kategori endpoints."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import Kategori, User
from app.schemas.kategori import KategoriCreate, KategoriOut, KategoriUpdate

router = APIRouter(prefix="/kategori", tags=["kategori"])


@router.get("", response_model=List[KategoriOut])
def list_kategori(
    only_active: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Kategori).order_by(Kategori.weight.desc(), Kategori.nama.asc())
    if only_active:
        q = q.filter(Kategori.is_active.is_(True))
    return q.all()


@router.post("", response_model=KategoriOut, status_code=status.HTTP_201_CREATED)
def create_kategori(
    payload: KategoriCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if db.query(Kategori).filter(Kategori.nama.ilike(payload.nama)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Nama kategori sudah ada")
    k = Kategori(**payload.model_dump(), is_default=False)
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


@router.put("/{kategori_id}", response_model=KategoriOut)
def update_kategori(
    kategori_id: int,
    payload: KategoriUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    k = db.query(Kategori).filter(Kategori.id == kategori_id).first()
    if not k:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kategori tidak ditemukan")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(k, field, value)
    db.commit()
    db.refresh(k)
    return k


@router.delete("/{kategori_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kategori(
    kategori_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    k = db.query(Kategori).filter(Kategori.id == kategori_id).first()
    if not k:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kategori tidak ditemukan")
    if k.is_default:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Kategori default '{k.nama}' tidak boleh dihapus",
        )
    db.delete(k)
    db.commit()
    return None
