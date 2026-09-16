from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
from ..auth import get_current_user
from ..models import User
from .. import models
from ..models import FGInventory, ActivityLedger, StageTransition

router = APIRouter(prefix="/fg-inventory", tags=["FG Inventory"])

@router.get("/items")
def get_fg_inventory(db: Session = Depends(get_db)):
    """Get all orders in FG_INVENTORY stage"""
    tokens = db.query(crud.WorkflowToken).filter(
        crud.WorkflowToken.current_stage == "FG_INVENTORY",
        crud.WorkflowToken.status == "ACTIVE"
    ).all()
    buyer_order_ids = [t.buyer_order_id for t in tokens]
    if not buyer_order_ids:
        return []
    items = db.query(FGInventory).filter(
        FGInventory.quantity_ready > 0,
        FGInventory.buyer_order_id.in_(buyer_order_ids)
    ).all()
    result = []
    for item in items:
        result.append({
            'fgKey': item.fg_key,
            'orderId': item.buyer_order_id,
            'designName': item.design_name,
            'color': item.color,
            'garmentSize': item.garment_size,
            'quantityProduced': item.quantity_produced,
            'quantityPassed': item.quantity_passed,
            'quantityReady': item.quantity_ready,
            'status': item.status,
            'location': item.location,
            'batchId': item.batch_id,
            'productionDate': item.production_date
        })
    return result

@router.get("/orders")
def get_fg_inventory_orders(db: Session = Depends(get_db)):
    """List buyer orders in FG_INVENTORY stage with per-order FG aggregates"""
    from .. import models
    from decimal import Decimal
    
    tokens = db.query(crud.WorkflowToken).filter(
        crud.WorkflowToken.current_stage == "FG_INVENTORY",
        crud.WorkflowToken.status == "ACTIVE"
    ).all()
    
    if not tokens:
        return []
    
    result = []
    for token in tokens:
        buyer_order_id = token.buyer_order_id
        
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        if not buyer_order:
            continue
        
        # Get latest PASSED inspection per fg_key
        inspections = db.query(models.FGInspectionRecord).filter(
            models.FGInspectionRecord.buyer_order_id == buyer_order_id,
            models.FGInspectionRecord.status == 'PASSED'
        ).order_by(models.FGInspectionRecord.id.desc()).all()
        
        # Latest per fg_key
        latest_by_fg = {}
        for ins in inspections:
            if ins.fg_key not in latest_by_fg:
                latest_by_fg[ins.fg_key] = ins
        
        total_qty = Decimal('0')
        fg_breakdown = []
        for fg_key, ins in latest_by_fg.items():
            passed = Decimal(str(ins.inspected_qty or 0))
            total_qty += passed
            parts = fg_key.split('|')
            design = parts[1] if len(parts) > 1 else ''
            color = parts[2] if len(parts) > 2 else ''
            fg_breakdown.append({
                'fgKey': fg_key,
                'design': design,
                'color': color,
                'qty': float(passed)
            })
        
        # Compute balance qty from FGInventory.quantity_ready per FG
        fg_inv_rows = db.query(models.FGInventory).filter(
            models.FGInventory.buyer_order_id == buyer_order_id
        ).all()
        balance_total = Decimal('0')
        balance_breakdown = []
        for fi in fg_inv_rows:
            ready = Decimal(str(fi.quantity_ready or 0))
            if ready <= 0:
                continue
            balance_total += ready
            balance_breakdown.append({
                'fgKey': fi.fg_key,
                'design': fi.design_name or '',
                'color': fi.color or '',
                'qty': float(ready)
            })
        
        result.append({
            'buyerOrderId': buyer_order_id,
            'buyerName': buyer_order.buyer_name or 'Unknown',
            'buyerOrderNo': buyer_order.buyer_order_no or 'N/A',
            'orderDate': buyer_order.order_date,
            'fgCount': len(latest_by_fg),
            'totalQty': float(total_qty),
            'balancePcs': float(balance_total),
            'fgBreakdown': fg_breakdown,
            'balanceBreakdown': balance_breakdown,
            'currentStage': token.current_stage,
            'currentVersion': token.current_version,
        })
    
    return result

@router.post("/send-back")
def send_back_to_inspection(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Move token backward FG_INVENTORY -> FG_INSPECTION.
    Unwinds FGInventory rows (created by the last FG Inspection PASS) so the
    next PASS does not double-count. Blocked when dispatches exist.
    """
    try:
        buyer_order_id = crud.clean_key_exact(data.get('buyer_order_id', ''))
        if not buyer_order_id:
            return {'success': False, 'message': 'Buyer Order ID required'}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {'success': False, 'message': 'No workflow token found'}
        if token_state['current_stage'] != 'FG_INVENTORY':
            return {'success': False, 'message': f'Cannot send back from stage: {token_state["current_stage"]}'}
        
        dispatch_count = db.query(models.DispatchRecord).filter(
            models.DispatchRecord.buyer_order_id == buyer_order_id
        ).count()
        if dispatch_count > 0:
            return {'success': False, 'message': f'Cannot send back: order has {dispatch_count} dispatch record(s). Once dispatched, the order is locked.'}
        
        if not crud.can_move_backward(db, buyer_order_id):
            return {'success': False, 'message': 'Cannot move backward'}
        
        # Unwind FGInventory rows that PASSED inspection created.
        # Only the LATEST PASSED record per (buyer_order_id, fg_key) counts:
        # prior PASSED rows are never cancelled across cycles, so summing them
        # all double/triple-counts and over-decrements FGInventory.
        passed_all = db.query(models.FGInspectionRecord).filter(
            models.FGInspectionRecord.buyer_order_id == buyer_order_id,
            models.FGInspectionRecord.status == 'PASSED'
        ).order_by(models.FGInspectionRecord.id.desc()).all()

        latest_by_fg = {}
        for rec in passed_all:
            if rec.fg_key not in latest_by_fg:
                latest_by_fg[rec.fg_key] = rec

        reversed_map = {}
        for rec in latest_by_fg.values():
            qty = float(rec.inspected_qty or 0)
            if qty <= 0:
                continue
            reversed_map[rec.fg_key] = qty
        
        total_reversed = 0.0
        for fg_key, rev_qty in reversed_map.items():
            fg_inv = db.query(models.FGInventory).filter(
                models.FGInventory.buyer_order_id == buyer_order_id,
                models.FGInventory.fg_key == fg_key
            ).first()
            if not fg_inv:
                continue
            fg_inv.quantity_produced = max(0.0, float(fg_inv.quantity_produced or 0) - rev_qty)
            fg_inv.quantity_inspected = max(0.0, float(fg_inv.quantity_inspected or 0) - rev_qty)
            fg_inv.quantity_passed = max(0.0, float(fg_inv.quantity_passed or 0) - rev_qty)
            fg_inv.quantity_ready = max(0.0, float(fg_inv.quantity_ready or 0) - rev_qty)
            fg_inv.status = 'INSPECTION_REVERTED'
            fg_inv.last_updated = datetime.utcnow()
            total_reversed += rev_qty
        
        db.commit()
        
        move_result = crud.move_stage(db, buyer_order_id, 'backward', 'system')
        
        return {
            'success': True,
            'message': f'Sent back to FG Inspection. {len(reversed_map)} FG(s) unwound, {total_reversed:.2f} qty removed.',
            'newStage': move_result['new_stage'],
            'newVersion': move_result['new_version'],
            'reversedFGCount': len(reversed_map),
            'totalReversed': total_reversed
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}


# ==============================================================
# RESTORED: dispatch-data + dispatch (bulk) + return
# ==============================================================

@router.get("/dispatch-data/{buyer_order_id}")
def get_dispatch_data(buyer_order_id: str, db: Session = Depends(get_db)):
    """Get FGs of a buyer order in FG_INVENTORY with available qty for dispatch"""
    from .. import models
    from decimal import Decimal
    
    clean_bo_id = crud.clean_key_exact(buyer_order_id)
    
    buyer_order = db.query(models.BuyerOrder).filter(
        models.BuyerOrder.buyer_order_id == clean_bo_id
    ).first()
    if not buyer_order:
        return {'success': False, 'message': 'Buyer order not found'}
    
    fg_items = db.query(models.FGInventory).filter(
        models.FGInventory.buyer_order_id == clean_bo_id
    ).all()
    
    fgs = []
    for item in fg_items:
        ready = float(item.quantity_ready or 0)
        if ready <= 0:
            continue
        fgs.append({
            'fgKey': item.fg_key,
            'design': item.design_name or '',
            'color': item.color or '',
            'fgQty': ready,
        })
    
    return {
        'success': True,
        'buyerOrderId': clean_bo_id,
        'buyerOrderNo': buyer_order.buyer_order_no or 'N/A',
        'buyerName': buyer_order.buyer_name or 'Unknown',
        'fgs': fgs,
        'totalFGs': len(fgs)
    }


@router.post("/dispatch")
def dispatch_fg_bulk(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Dispatch FG from a buyer order.
    Payload: {
      buyer_order_id, invoice_no, challan_no, dispatched_by,
      rows: [{fgKey, fgQty, dispatchQty}]
    }
    """
    from .. import models
    from decimal import Decimal
    import uuid as _uuid
    
    try:
        buyer_order_id = crud.clean_key_exact(data.get('buyer_order_id', ''))
        invoice_no = data.get('invoice_no', '')
        challan_no = data.get('challan_no', '')
        dispatched_by = data.get('dispatched_by', 'admin')
        rows = data.get('rows', [])
        
        if not buyer_order_id:
            return {'success': False, 'message': 'Buyer Order ID required'}
        if not rows:
            return {'success': False, 'message': 'No rows to dispatch'}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state or token_state['current_stage'] != 'FG_INVENTORY':
            return {'success': False, 'message': 'Buyer order is not in FG Inventory stage'}
        
        ledger_version = token_state['current_version']
        
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        buyer_order_no = buyer_order.buyer_order_no if buyer_order else ''
        buyer_name = buyer_order.buyer_name if buyer_order else ''
        
        dispatch_batch_id = f"DISP-{_uuid.uuid4().hex[:6].upper()}"
        total_dispatched = Decimal('0')
        records_created = []
        
        for r in rows:
            fg_key = r.get('fgKey', '')
            dispatch_qty = Decimal(str(r.get('dispatchQty', 0) or 0))
            
            if not fg_key or dispatch_qty <= 0:
                continue
            
            item = db.query(models.FGInventory).filter(
                models.FGInventory.buyer_order_id == buyer_order_id,
                models.FGInventory.fg_key == fg_key
            ).first()
            if not item:
                return {'success': False, 'message': f'FGInventory item not found for {fg_key}'}
            
            available = Decimal(str(item.quantity_ready or 0))
            if dispatch_qty > available + Decimal('0.001'):
                return {'success': False, 'message': f'Dispatch qty {dispatch_qty} exceeds available {available} for {fg_key}'}
            
            db.add(models.DispatchRecord(
                dispatch_id=f"{dispatch_batch_id}-{_uuid.uuid4().hex[:4].upper()}",
                buyer_order_id=buyer_order_id,
                buyer_order_no=buyer_order_no,
                buyer_name=buyer_name,
                invoice_no=invoice_no,
                challan_no=challan_no,
                fg_key=fg_key,
                design_name=item.design_name or '',
                color=item.color or '',
                fg_qty=Decimal(str(r.get('fgQty', 0) or 0)),
                dispatch_qty=dispatch_qty,
                dispatched_by=dispatched_by,
            ))
            
            item.quantity_ready = available - dispatch_qty
            item.status = 'DISPATCHED' if float(item.quantity_ready) <= 0 else 'PARTIAL_DISPATCHED'
            item.last_updated = datetime.utcnow()
            
            total_dispatched += dispatch_qty
            records_created.append({'fgKey': fg_key, 'qty': float(dispatch_qty)})
        
        if not records_created:
            return {'success': False, 'message': 'No valid dispatch rows'}
        
        crud.add_ledger_entry(db, {
            'fg_key': '',
            'buyer_order_id': buyer_order_id,
            'activity_type': 'DISPATCH',
            'status': 'DISPATCHED',
            'buyer_name': buyer_name,
            'buyer_order_no': buyer_order_no,
            'order_date': buyer_order.order_date if buyer_order else None,
            'created_date': datetime.utcnow(),
            'qty': float(total_dispatched),
            'workflow_position': 9,
            'version': ledger_version,
            'extra_data': {
                'dispatchBatchId': dispatch_batch_id,
                'invoiceNo': invoice_no,
                'challanNo': challan_no,
                'rows': records_created,
                'totalDispatched': float(total_dispatched),
                'dispatchedAt': datetime.utcnow().isoformat(),
                'dispatchedBy': dispatched_by,
            }
        })
        
        db.commit()
        
        return {
            'success': True,
            'message': f'Dispatched {len(records_created)} FG line(s). Total qty: {float(total_dispatched)}',
            'dispatchBatchId': dispatch_batch_id,
            'recordsCreated': len(records_created),
            'totalDispatched': float(total_dispatched),
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}


@router.post("/return")
def return_fg_inventory(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Return FG from inventory back to FG_INSPECTION (unwind ready qty, move token)."""
    from .. import models
    
    try:
        fg_key = data.get('fg_key', '')
        buyer_order_id = data.get('buyer_order_id', '')
        quantity = float(data.get('quantity', 0) or 0)
        
        if not fg_key or not buyer_order_id or quantity <= 0:
            return {'success': False, 'message': 'Missing required fields'}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {'success': False, 'message': 'No workflow token found'}
        if token_state['current_stage'] != 'FG_INVENTORY':
            return {'success': False, 'message': f"Cannot return from stage: {token_state['current_stage']}"}
        
        dispatch_count = db.query(models.DispatchRecord).filter(
            models.DispatchRecord.buyer_order_id == buyer_order_id
        ).count()
        if dispatch_count > 0:
            return {'success': False, 'message': f'Cannot return: order has {dispatch_count} dispatch record(s). Once dispatched, the order is locked.'}
        
        if not crud.can_move_backward(db, buyer_order_id):
            return {'success': False, 'message': 'Cannot move backward'}
        
        move_result = crud.move_stage(db, buyer_order_id, 'backward', 'system')
        
        item = db.query(models.FGInventory).filter(
            models.FGInventory.fg_key == fg_key,
            models.FGInventory.buyer_order_id == buyer_order_id
        ).first()
        if not item:
            return {'success': False, 'message': 'FG Inventory item not found'}
        if float(item.quantity_ready or 0) < quantity:
            return {'success': False, 'message': f"Insufficient stock. Available: {item.quantity_ready}"}
        
        item.quantity_ready = float(item.quantity_ready or 0) - quantity
        item.quantity_passed = max(0.0, float(item.quantity_passed or 0) - quantity)
        item.status = 'INSPECTED' if float(item.quantity_ready) <= 0 else 'PARTIAL_INSPECTED'
        item.last_updated = datetime.utcnow()
        db.commit()
        
        return {
            'success': True,
            'message': 'FG Inventory returned. Moved back to FG Inspection.',
            'new_stage': move_result['new_stage'],
            'new_version': move_result['new_version'],
            'remainingStock': float(item.quantity_ready)
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}
