from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
from ..auth import require_role
from ..models import User
from ..models import CostingApproval, ActivityLedger, StageTransition

router = APIRouter(prefix="/approval", tags=["Costing Approval"])

@router.get("/orders")
def get_approval_orders(db: Session = Depends(get_db)):
    """Get all orders in COSTING_APPROVAL stage"""
    # Get all active tokens in COSTING_APPROVAL stage
    tokens = db.query(crud.WorkflowToken).filter(
        crud.WorkflowToken.current_stage == "COSTING_APPROVAL",
        crud.WorkflowToken.status == "ACTIVE"
    ).all()
    
    buyer_order_ids = [t.buyer_order_id for t in tokens]
    
    if not buyer_order_ids:
        return []
    
    result = []
    
    for buyer_order_id in buyer_order_ids:
        # Live BOM rows (latest version per fg_key, COMPLETED only)
        order_entries = crud.get_live_ledger_entries(
            db, activity_type='BOM', buyer_order_id=buyer_order_id,
            latest_version_only=True,
            extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
        )
        if not order_entries:
            continue
        
        existing = db.query(CostingApproval).filter(
            CostingApproval.buyer_order_id == buyer_order_id
        ).first()
        
        fg_keys = list(set(e.fg_key for e in order_entries))
        
        result.append({
            'buyerOrderId': buyer_order_id,
            'buyerName': order_entries[0].buyer_name if order_entries else 'Unknown',
            'buyerOrderNo': order_entries[0].buyer_order_no if order_entries else 'N/A',
            'orderDate': order_entries[0].order_date if order_entries else None,
            'totalFGs': len(fg_keys),
            'fgKeys': fg_keys,
            'status': existing.approval_status if existing else 'PENDING'
        })
    
    return result

@router.get("/order/{order_id}")
def get_approval_order_detail(order_id: str, db: Session = Depends(get_db)):
    """Get detailed approval data for an order - only latest version, deduplicated"""
    from .. import models
    
    # Live BOM rows for this order (latest version per fg_key, COMPLETED only)
    live_bom = crud.get_live_ledger_entries(
        db, activity_type='BOM', buyer_order_id=order_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    
    if not live_bom:
        return {"success": False, "message": "No BOM found for this order"}
    
    version = live_bom[0].version or 1
    
    result = []
    buyer_name = ''
    buyer_order_no = ''
    order_date = None
    for entry in live_bom:
        bom_data = entry.extra_data or {}
        if not buyer_name and entry.buyer_name:
            buyer_name = entry.buyer_name
        if not buyer_order_no and entry.buyer_order_no:
            buyer_order_no = entry.buyer_order_no
        if order_date is None and entry.order_date:
            order_date = entry.order_date
        result.append({
            'fgKey': entry.fg_key,
            'bomItems': bom_data.get('items', []),
            'itemCount': bom_data.get('itemCount', 0),
            'bomStatus': entry.status,
            'createdAt': entry.created_date,
            'version': entry.version,
            'buyerName': entry.buyer_name or '',
            'buyerOrderNo': entry.buyer_order_no or ''
        })

    return {
        'success': True,
        'buyerOrderId': order_id,
        'buyerName': buyer_name,
        'buyerOrderNo': buyer_order_no,
        'orderDate': order_date.isoformat() if order_date else None,
        'fgs': result,
        'totalFGs': len(result),
        'version': version
    }

@router.post("/reject")
def reject_costing(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    """Reject costing for an order - moves back to BOM"""
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        rejection_reason = data.get('rejection_reason', '')
        rejected_by = data.get('rejected_by', 'admin')
        
        if not buyer_order_id:
            return {"success": False, "message": "Order ID is required"}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found for this order"}
        
        if token_state["current_stage"] != "COSTING_APPROVAL":
            return {"success": False, "message": f"Cannot reject from stage: {token_state['current_stage']}"}
        
        if not crud.can_move_backward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move backward from current stage"}
        
        move_result = crud.move_stage(db, buyer_order_id, "backward", rejected_by)
        
        entries = crud.get_ledger_entries(db, activity_type='BOM', status='COMPLETED')
        order_entries = [e for e in entries if e.buyer_order_id == buyer_order_id]
        
        if not order_entries:
            return {"success": False, "message": "No BOM found for this order"}
        
        entries_to_insert = []
        now = datetime.utcnow()
        
        for entry in order_entries:
            existing = db.query(CostingApproval).filter(
                CostingApproval.buyer_order_id == buyer_order_id,
                CostingApproval.fg_key == entry.fg_key
            ).first()
            
            if existing:
                existing.approval_status = 'REJECTED'
                existing.rejection_reason = rejection_reason
                existing.approved_by = rejected_by
                existing.approved_at = now
            else:
                approval = CostingApproval(
                    buyer_order_id=buyer_order_id,
                    fg_key=entry.fg_key,
                    approval_status='REJECTED',
                    approved_by=rejected_by,
                    approved_at=now,
                    rejection_reason=rejection_reason,
                    locked_rates=entry.extra_data.get('items', []) if entry.extra_data else []
                )
                db.add(approval)
            
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': entry.fg_key,
                'activity_type': 'COSTING_APPROVAL',
                'status': 'REJECTED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': 1,
                'extra_data': {
                    'rejectedAt': now.isoformat(),
                    'rejectedBy': rejected_by,
                    'rejectionReason': rejection_reason,
                    'version': move_result["new_version"],
                    'previous_version': move_result["previous_version"],
                    'stage_movement': 'backward',
                    'from_stage': move_result["previous_stage"],
                    'to_stage': move_result["new_stage"]
                }
            })
        
        transition = StageTransition(
            buyer_order_id=buyer_order_id,
            from_stage='COSTING_APPROVAL',
            to_stage='BOM',
            transition_type='REJECT',
            triggered_by=rejected_by,
            notes=f'Costing rejected: {rejection_reason}'
        )
        db.add(transition)
        db.commit()
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {
            "success": True,
            "message": f"Order {buyer_order_id} rejected and moved back to BOM",
            "new_stage": move_result["new_stage"],
            "new_version": move_result["new_version"]
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

@router.post("/approve")
def approve_costing(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    """Approve costing for an order - moves to RM_ORDER"""
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        approved_by = data.get('approved_by', 'admin')
        
        if not buyer_order_id:
            return {"success": False, "message": "Order ID is required"}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found for this order"}
        
        if token_state["current_stage"] != "COSTING_APPROVAL":
            return {"success": False, "message": f"Cannot approve from stage: {token_state['current_stage']}"}
        
        if not crud.can_move_forward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move forward from current stage"}
        
        entries = crud.get_ledger_entries(db, activity_type='BOM', status='COMPLETED')
        order_entries = [e for e in entries if e.buyer_order_id == buyer_order_id]
        
        if not order_entries:
            return {"success": False, "message": "No BOM found for this order"}
        
        move_result = crud.move_stage(db, buyer_order_id, "forward", approved_by)
        
        entries_to_insert = []
        now = datetime.utcnow()
        
        for entry in order_entries:
            existing = db.query(CostingApproval).filter(
                CostingApproval.buyer_order_id == buyer_order_id,
                CostingApproval.fg_key == entry.fg_key
            ).first()
            
            if existing:
                existing.approval_status = 'APPROVED'
                existing.approved_by = approved_by
                existing.approved_at = now
                existing.locked_rates = entry.extra_data.get('items', []) if entry.extra_data else []
            else:
                approval = CostingApproval(
                    buyer_order_id=buyer_order_id,
                    fg_key=entry.fg_key,
                    approval_status='APPROVED',
                    approved_by=approved_by,
                    approved_at=now,
                    locked_rates=entry.extra_data.get('items', []) if entry.extra_data else [],
                    bom_version=1
                )
                db.add(approval)
            
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': entry.fg_key,
                'activity_type': 'COSTING_APPROVAL',
                'status': 'APPROVED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': 2,
                'extra_data': {
                    'approvedAt': now.isoformat(),
                    'approvedBy': approved_by,
                    'lockedRates': entry.extra_data.get('items', []) if entry.extra_data else [],
                    'version': move_result["new_version"],
                    'previous_version': move_result["previous_version"],
                    'stage_movement': 'forward',
                    'from_stage': move_result["previous_stage"],
                    'to_stage': move_result["new_stage"]
                }
            })
        
        transition = StageTransition(
            buyer_order_id=buyer_order_id,
            from_stage='COSTING_APPROVAL',
            to_stage='RM_ORDER',
            transition_type='APPROVE',
            triggered_by=approved_by,
            notes='Costing approved, moving to RM Order'
        )
        db.add(transition)
        db.commit()
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {
            "success": True,
            "message": f"Order {buyer_order_id} approved and moved to RM Order",
            "new_stage": move_result["new_stage"],
            "new_version": move_result["new_version"]
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}
