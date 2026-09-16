from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from .. import crud
from ..database import get_db
from ..models import MasterData, User
from ..auth import get_current_user
import uuid

router = APIRouter(prefix="/master", tags=["Master Data"])

@router.get("/buyers")
def get_buyers(db: Session = Depends(get_db)):
    """Get all active buyers"""
    buyers = db.query(MasterData).filter(
        MasterData.category == "BUYER",
        MasterData.status == "ACTIVE"
    ).all()
    return [{
        "id": b.id,
        "name": b.name,
        "gst_no": b.gst_no,
        "contact_person": b.contact_person,
        "contact_no": b.contact_no,
        "email": b.email,
        "address": b.address,
        "payment_term": b.payment_term,
        "status": b.status
    } for b in buyers]

@router.get("/suppliers")
def get_suppliers(db: Session = Depends(get_db)):
    """Get all active suppliers"""
    suppliers = db.query(MasterData).filter(
        MasterData.category == "SUPPLIER",
        MasterData.status == "ACTIVE"
    ).all()
    return [{
        "id": s.id,
        "name": s.name,
        "gst_no": s.gst_no,
        "contact_person": s.contact_person,
        "contact_no": s.contact_no,
        "email": s.email,
        "address": s.address,
        "payment_term": s.payment_term,
        "status": s.status
    } for s in suppliers]

@router.get("/all")
def get_all_parties(db: Session = Depends(get_db)):
    """Get all active parties (buyers and suppliers)"""
    parties = db.query(MasterData).filter(MasterData.status == "ACTIVE").all()
    return [{
        "id": p.id,
        "category": p.category,
        "name": p.name,
        "gst_no": p.gst_no,
        "contact_person": p.contact_person,
        "contact_no": p.contact_no,
        "email": p.email,
        "address": p.address,
        "payment_term": p.payment_term,
        "status": p.status
    } for p in parties]

@router.get("/{id}")
def get_party(id: str, db: Session = Depends(get_db)):
    """Get a single party by ID"""
    party = db.query(MasterData).filter(MasterData.id == id).first()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    return {
        "id": party.id,
        "category": party.category,
        "name": party.name,
        "gst_no": party.gst_no,
        "contact_person": party.contact_person,
        "contact_no": party.contact_no,
        "email": party.email,
        "address": party.address,
        "payment_term": party.payment_term,
        "status": party.status
    }

@router.post("/buyers")
def add_buyer(data: Dict, db: Session = Depends(get_db)):
    """Add a new buyer"""
    from ..crud import add_master_entity
    try:
        # Check if name already exists
        existing = db.query(MasterData).filter(
            MasterData.name == data['name'],
            MasterData.category == "BUYER"
        ).first()
        if existing:
            return {"success": False, "message": "Buyer with this name already exists"}
        
        data['category'] = 'BUYER'
        result = add_master_entity(db, data)
        return {"success": True, "message": "Buyer added successfully", "id": result.id, "name": result.name}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/suppliers")
def add_supplier(data: Dict, db: Session = Depends(get_db)):
    """Add a new supplier"""
    from ..crud import add_master_entity
    try:
        # Check if name already exists
        existing = db.query(MasterData).filter(
            MasterData.name == data['name'],
            MasterData.category == "SUPPLIER"
        ).first()
        if existing:
            return {"success": False, "message": "Supplier with this name already exists"}
        
        data['category'] = 'SUPPLIER'
        result = add_master_entity(db, data)
        return {"success": True, "message": "Supplier added successfully", "id": result.id, "name": result.name}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.put("/{id}")
def update_party(id: str, data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Update a party (Admin only)"""
    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can edit party information")
    
    party = db.query(MasterData).filter(MasterData.id == id).first()
    if not party:
        return {"success": False, "message": "Party not found"}
    
    try:
        # Update fields
        if 'name' in data and data['name']:
            # Check if new name conflicts with existing
            existing = db.query(MasterData).filter(
                MasterData.name == data['name'],
                MasterData.id != id,
                MasterData.category == party.category
            ).first()
            if existing:
                return {"success": False, "message": "A party with this name already exists"}
            party.name = data['name']
        
        if 'gst_no' in data:
            party.gst_no = data['gst_no']
        if 'address' in data:
            party.address = data['address']
        if 'contact_person' in data:
            party.contact_person = data['contact_person']
        if 'contact_no' in data:
            party.contact_no = data['contact_no']
        if 'email' in data:
            party.email = data['email']
        if 'payment_term' in data:
            party.payment_term = data['payment_term']
        if 'status' in data:
            party.status = data['status']
        
        db.commit()
        db.refresh(party)
        return {"success": True, "message": "Party updated successfully", "party": {
            "id": party.id,
            "category": party.category,
            "name": party.name,
            "gst_no": party.gst_no,
            "contact_person": party.contact_person,
            "contact_no": party.contact_no,
            "email": party.email,
            "address": party.address,
            "payment_term": party.payment_term,
            "status": party.status
        }}
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

@router.delete("/{id}")
def delete_party(id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Soft delete a party (Admin only)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete parties")
    
    party = db.query(MasterData).filter(MasterData.id == id).first()
    if not party:
        return {"success": False, "message": "Party not found"}
    
    party.status = "INACTIVE"
    db.commit()
    return {"success": True, "message": "Party deleted successfully"}
