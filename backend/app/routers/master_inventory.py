from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from sqlalchemy.orm.attributes import flag_modified
from ..database import get_db
from ..crud import generate_rm_id
from ..models import MasterInventory
from ..auth import get_current_user
from ..models import User
import uuid

router = APIRouter(prefix="/master/inventory", tags=["Master Inventory"])

@router.get("/")
def get_inventory(db: Session = Depends(get_db)):
    """Get all inventory items with live stock from inventory_snapshot"""
    from ..models import InventorySnapshot
    from collections import defaultdict
    from decimal import Decimal
    
    items = db.query(MasterInventory).filter(
        MasterInventory.status == "ACTIVE",
    ).all()
    
    # Aggregate snapshot stock per item_no
    snapshots = db.query(InventorySnapshot).all()
    stock_by_item = defaultdict(lambda: {
        'total': Decimal('0'),
        'by_size': defaultdict(lambda: Decimal('0'))
    })
    for s in snapshots:
        if not s.item_no:
            continue
        current = Decimal(str(s.current_stock or 0))
        stock_by_item[s.item_no]['total'] += current
        size = s.garment_size or 'ALL'
        stock_by_item[s.item_no]['by_size'][size] += current
    
    result = []
    for i in items:
        info = stock_by_item.get(i.item_no, {'total': Decimal('0'), 'by_size': {}})
        # Build size-wise breakdown string for tooltip
        size_breakdown_parts = []
        by_size = info.get('by_size', {})
        if by_size:
            for sz in sorted(by_size.keys(), key=lambda x: str(x)):
                qty = float(by_size[sz] or 0)
                if qty != 0:
                    size_breakdown_parts.append(f"{sz}: {qty:.2f}")
        size_breakdown = ", ".join(size_breakdown_parts) if size_breakdown_parts else ""
        
        result.append({
            "id": i.item_no,
            "category": i.category,
            "name": i.item_name,
            "color": i.extra_data.get('color', '') if i.extra_data else '',
            "size": i.extra_data.get('size', '') if i.extra_data else '',
            "rate": i.standard_rate,
            "supplier": i.preferred_supplier,
            "stock": float(info['total']),
            "stock_by_size": size_breakdown,
            "uom": i.uom,
            "location": i.location
        })
    return result

@router.post("/")
def add_inventory_item(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Add a new inventory item"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can add inventory items")
    
    # Auto-generate RM ID
    auto_id = generate_rm_id(db)
    data["id"] = auto_id
    try:
        # Check if item_no already exists
        existing = db.query(MasterInventory).filter(
            MasterInventory.item_no == data['id']
        ).first()
        if existing:
            return {"success": False, "message": f"Item ID {data['id']} already exists"}
        
        item = MasterInventory(
            item_no=data['id'],
            item_name=data['name'],
            category=data.get('category', 'RM'),
            uom=data.get('uom', 'PCS'),
            standard_rate=data.get('rate', 0),
            preferred_supplier=data.get('supplier', ''),
            status="ACTIVE",
            version=1,
            extra_data={
                'color': data.get('color', ''),
                'size': data.get('size', ''),
                'location': data.get('location', '')
            }
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return {"success": True, "message": "Item added successfully", "id": item.item_no}
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

@router.put("/{item_no}")
def update_inventory_item(item_no: str, data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Update an inventory item"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can update inventory items")
    
    item = db.query(MasterInventory).filter(MasterInventory.item_no == item_no).first()
    if not item:
        return {"success": False, "message": "Item not found"}
    
    try:
        if 'name' in data:
            item.item_name = data['name']
        if 'category' in data:
            item.category = data['category']
        if 'uom' in data:
            item.uom = data['uom']
        if 'rate' in data:
            item.standard_rate = data['rate']
        if 'supplier' in data:
            item.preferred_supplier = data['supplier']
        if 'status' in data:
            item.status = data['status']
        if 'location' in data:
            item.location = data['location']
        if 'color' in data or 'size' in data:
            extra = item.extra_data or {}
            if 'color' in data:
                extra['color'] = data['color']
            if 'size' in data:
                extra['size'] = data['size']
            item.extra_data = extra
            # Force SQLAlchemy to detect the change
            flag_modified(item, 'extra_data')
        
        db.commit()
        db.refresh(item)
        return {"success": True, "message": "Item updated successfully"}
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

@router.delete("/{item_no}")
def delete_inventory_item(item_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Soft delete an inventory item"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete inventory items")
    
    item = db.query(MasterInventory).filter(MasterInventory.item_no == item_no).first()
    if not item:
        return {"success": False, "message": "Item not found"}
    
    item.status = "INACTIVE"
    db.commit()
    return {"success": True, "message": "Item deleted successfully"}

# Also handle without trailing slash
@router.get("")
def get_inventory_no_slash(db: Session = Depends(get_db)):
    """Get all inventory items (without trailing slash)"""
    return get_inventory(db)
