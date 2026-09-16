from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
from ..auth import get_current_user
from ..models import User
from ..models import InspectionRecord, ActivityLedger, FGInventory, StageTransition
import uuid

router = APIRouter(prefix="/fg-inspection", tags=["FG Inspection"])

@router.get("/orders")
def get_fg_inspections(db: Session = Depends(get_db)):
    """Get buyer orders in FG_INSPECTION stage"""
    from .. import models
    from decimal import Decimal
    from collections import defaultdict
    
    tokens = db.query(crud.WorkflowToken).filter(
        crud.WorkflowToken.current_stage == "FG_INSPECTION",
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
        
        # Live BUYER_ORDER rows for this order (latest version only)
        fg_entries = crud.get_live_ledger_entries(
            db, activity_type='BUYER_ORDER', buyer_order_id=buyer_order_id,
            latest_version_only=True,
            extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
        )
        fg_keys = sorted(set(e.fg_key for e in fg_entries))
        
        # Live MATERIAL_REQUIREMENT rows with status ISSUED
        issued_entries = crud.get_live_ledger_entries(
            db, activity_type='MATERIAL_REQUIREMENT', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: (e.status or '').upper() == 'ISSUED'
        )
        total_issued = sum(float(e.qty or 0) for e in issued_entries)
        
        # Get FG inspection records if any
        inspections = db.query(InspectionRecord).filter(
            InspectionRecord.inspection_type == 'FINISHED_GOODS',
            InspectionRecord.buyer_order_id == buyer_order_id
        ).all()
        insp_map = {i.reference: i for i in inspections}
        
        # Total produced qty from internal FG orders (order qty)
        internal_orders = db.query(models.InternalFGOrder).filter(
            models.InternalFGOrder.buyer_order_id == buyer_order_id
        ).all()
        produced_qty = sum(float(io.quantity or 0) for io in internal_orders)
        
        # Fail count from fg_inspection_records
        fail_count = db.query(models.FGInspectionRecord).filter(
            models.FGInspectionRecord.buyer_order_id == buyer_order_id,
            models.FGInspectionRecord.status == 'FAILED'
        ).count()
        
        result.append({
            'buyerOrderId': buyer_order_id,
            'buyerOrderNo': buyer_order.buyer_order_no or 'N/A',
            'buyerName': buyer_order.buyer_name or 'Unknown',
            'orderDate': buyer_order.order_date,
            'fgCount': len(fg_keys),
            'fgKeys': fg_keys,
            'totalIssuedQty': total_issued,
            'producedQty': produced_qty,
            'orderQty': produced_qty,
            'failCount': fail_count,
            'status': 'PENDING',
            'currentStage': token.current_stage,
            'currentVersion': token.current_version,
            'hasInspections': len(inspections) > 0,
        })
    
    return result

@router.post("/cancel")
def cancel_fg_inspection(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Cancel FG Inspection for a buyer order:
    - Undo the FGInventory rows that PASSED inspection created
    - Move token backward FG_INSPECTION -> ISSUE_RM
    """
    from .. import models
    try:
        buyer_order_id = crud.clean_key_exact(data.get('buyer_order_id', ''))
        if not buyer_order_id:
            return {'success': False, 'message': 'Buyer Order ID required'}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {'success': False, 'message': 'No workflow token found'}
        if token_state['current_stage'] != 'FG_INSPECTION':
            return {'success': False, 'message': f'Cannot cancel from stage: {token_state["current_stage"]}'}
        if not crud.can_move_backward(db, buyer_order_id):
            return {'success': False, 'message': 'Cannot move backward'}
        
        # Reverse FGInventory rows written by PASSED inspections.
        # Only the LATEST PASSED record per (buyer_order_id, fg_key) counts:
        # across inspection cycles prior PASSED rows are never cancelled, so
        # summing them all double/triple-counts and over-decrements FGInventory.
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
        
        all_entries = crud.get_ledger_entries_for_order(db, buyer_order_id)
        bo = next((e for e in all_entries if e.buyer_order_id == buyer_order_id and e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        now = datetime.utcnow()
        crud.add_ledger_entry(db, {
            'fg_key': bo.fg_key if bo else '',
            'buyer_order_id': buyer_order_id,
            'activity_type': 'FG_INSPECTION',
            'status': 'CANCELLED',
            'buyer_name': bo.buyer_name if bo else '',
            'buyer_order_no': bo.buyer_order_no if bo else '',
            'order_date': bo.order_date if bo else None,
            'created_date': now,
            'qty': -total_reversed,
            'workflow_position': 8,
            'extra_data': {
                'cancelledAt': now.isoformat(),
                'reversedFGCount': len(reversed_map),
                'totalReversed': total_reversed,
                'version': move_result['new_version'],
                'previous_version': move_result['previous_version'],
                'stage_movement': 'backward',
                'from_stage': move_result['previous_stage'],
                'to_stage': move_result['new_stage']
            }
        })
        
        return {
            'success': True,
            'message': f'FG Inspection cancelled. {len(reversed_map)} FG(s) reverted, {total_reversed:.2f} qty removed from inventory. Moved back to Issue RM.',
            'newStage': move_result['new_stage'],
            'newVersion': move_result['new_version'],
            'reversedFGCount': len(reversed_map),
            'totalReversed': total_reversed
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}


# ==============================================================
# RESTORED: detail + submit (were missing from live file)
# ==============================================================

@router.get("/detail/{buyer_order_id}")
def get_fg_inspection_detail(buyer_order_id: str, db: Session = Depends(get_db)):
    """Get buyer order detail with one row per FG for inspection"""
    from .. import models
    from decimal import Decimal
    
    clean_bo_id = crud.clean_key_exact(buyer_order_id)
    
    buyer_order = db.query(models.BuyerOrder).filter(
        models.BuyerOrder.buyer_order_id == clean_bo_id
    ).first()
    if not buyer_order:
        return {'success': False, 'message': 'Buyer order not found'}
    
    fg_entries = crud.get_live_ledger_entries(
        db, activity_type='BUYER_ORDER', buyer_order_id=clean_bo_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    
    # Deduplicate by fg_key
    fg_map = {}
    for e in fg_entries:
        if e.fg_key not in fg_map or e.id > fg_map[e.fg_key].id:
            fg_map[e.fg_key] = e
    
    # Internal FG orders (order qty per fg)
    internal_orders = db.query(models.InternalFGOrder).filter(
        models.InternalFGOrder.buyer_order_id == clean_bo_id
    ).all()
    fg_order_qty = {io.fg_key: float(io.quantity or 0) for io in internal_orders}
    
    # Latest inspection per fg
    inspections = db.query(models.FGInspectionRecord).filter(
        models.FGInspectionRecord.buyer_order_id == clean_bo_id
    ).order_by(models.FGInspectionRecord.id.desc()).all()
    latest_insp_by_fg = {}
    for ins in inspections:
        if ins.fg_key not in latest_insp_by_fg:
            latest_insp_by_fg[ins.fg_key] = ins
    
    # Fail count per buyer order
    fail_count = db.query(models.FGInspectionRecord).filter(
        models.FGInspectionRecord.buyer_order_id == clean_bo_id,
        models.FGInspectionRecord.status == 'FAILED'
    ).count()
    
    fgs = []
    for fg_key, entry in fg_map.items():
        ed = entry.extra_data or {}
        design = ed.get('fgDesign', '')
        color = ed.get('fgColor', '')
        order_qty = fg_order_qty.get(fg_key, 0)
        latest = latest_insp_by_fg.get(fg_key)
        
        fgs.append({
            'fgKey': fg_key,
            'design': design,
            'color': color,
            'orderQty': order_qty,
            'presentedQty': float(latest.presented_qty or 0) if latest else 0,
            'inspectedQty': float(latest.inspected_qty or 0) if latest else 0,
            'minor': int(latest.minor_defects or 0) if latest else 0,
            'major': int(latest.major_defects or 0) if latest else 0,
            'critical': int(latest.critical_defects or 0) if latest else 0,
            'lastStatus': latest.status if latest else None,
        })
    
    return {
        'success': True,
        'buyerOrderId': clean_bo_id,
        'buyerName': buyer_order.buyer_name or 'Unknown',
        'buyerOrderNo': buyer_order.buyer_order_no or 'N/A',
        'orderDate': buyer_order.order_date.isoformat() if buyer_order.order_date else None,
        'failCount': fail_count,
        'totalFGs': len(fgs),
        'fgs': fgs
    }


@router.post("/submit")
def submit_fg_inspection(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Submit FG inspection for a buyer order.
    Payload: {
      buyer_order_id, decision ('PASS'/'FAIL'),
      inspector, rows: [{fgKey, orderQty, presentedQty, inspectedQty, minor, major, critical}]
    }
    """
    from .. import models
    from decimal import Decimal
    import uuid as _uuid
    
    try:
        buyer_order_id = crud.clean_key_exact(data.get('buyer_order_id', ''))
        decision = (data.get('decision') or '').upper()
        inspector = data.get('inspector', 'admin')
        rows = data.get('rows', [])
        
        if not buyer_order_id:
            return {'success': False, 'message': 'Buyer Order ID required'}
        if decision not in ('PASS', 'FAIL'):
            return {'success': False, 'message': 'Decision must be PASS or FAIL'}
        if not rows:
            return {'success': False, 'message': 'No rows provided'}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {'success': False, 'message': 'No workflow token found'}
        if token_state['current_stage'] != 'FG_INSPECTION':
            return {'success': False, 'message': f'Order not in FG_INSPECTION (currently {token_state["current_stage"]})'}
        
        ledger_version = token_state['current_version']
        
        records_to_add = []
        for r in rows:
            fg_key = r.get('fgKey', '')
            order_qty = float(r.get('orderQty', 0) or 0)
            presented = float(r.get('presentedQty', 0) or 0)
            inspected = float(r.get('inspectedQty', 0) or 0)
            minor = int(r.get('minor', 0) or 0)
            major = int(r.get('major', 0) or 0)
            critical = int(r.get('critical', 0) or 0)
            
            if not fg_key:
                return {'success': False, 'message': 'FG key missing in row'}
            
            if order_qty > 0:
                min_presented = order_qty * 0.95
                max_presented = order_qty * 1.05
                if presented < min_presented - 0.01 or presented > max_presented + 0.01:
                    return {'success': False, 'message': f'Presented qty for {fg_key} must be within ±5% of Order Qty ({min_presented:.2f} - {max_presented:.2f})'}
            
            if inspected > presented + 0.01:
                return {'success': False, 'message': f'Inspected qty cannot exceed Presented qty for {fg_key}'}
            
            records_to_add.append(models.FGInspectionRecord(
                inspection_id=f"FG-INSP-{_uuid.uuid4().hex[:6].upper()}",
                buyer_order_id=buyer_order_id,
                fg_key=fg_key,
                order_qty=Decimal(str(order_qty)),
                presented_qty=Decimal(str(presented)),
                inspected_qty=Decimal(str(inspected)),
                minor_defects=minor,
                major_defects=major,
                critical_defects=critical,
                status='PASSED' if decision == 'PASS' else 'FAILED',
                inspector=inspector,
            ))
        
        for rec in records_to_add:
            db.add(rec)
        db.commit()
        
        # Log entry in activity ledger
        all_entries = crud.get_ledger_entries_for_order(db, buyer_order_id)
        bo = next((e for e in all_entries if e.buyer_order_id == buyer_order_id and e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        
        # On PASS: upsert FGInventory rows and move the token FORWARD
        # BEFORE writing any CANCELLED ledger rows. CANCELLED rows are
        # excluded from move_stage's live-row version bump, so a CANCELLED
        # row written before the move would be stranded at the pre-move
        # version and filtered out of the live view.
        move_result = None
        if decision == 'PASS':
            from .. import models as _m
            for r in rows:
                fg_key = r.get('fgKey', '')
                inspected_qty = float(r.get('inspectedQty', 0) or 0)
                parts = fg_key.split('|')
                design = parts[1] if len(parts) > 1 else ''
                color = parts[2] if len(parts) > 2 else ''
                existing = db.query(_m.FGInventory).filter(
                    _m.FGInventory.buyer_order_id == buyer_order_id,
                    _m.FGInventory.fg_key == fg_key
                ).first()
                if existing:
                    existing.quantity_produced = float(existing.quantity_produced or 0) + inspected_qty
                    existing.quantity_passed = float(existing.quantity_passed or 0) + inspected_qty
                    existing.quantity_ready = float(existing.quantity_ready or 0) + inspected_qty
                    existing.status = 'READY'
                    existing.last_updated = datetime.utcnow()
                else:
                    db.add(_m.FGInventory(
                        fg_key=fg_key,
                        buyer_order_id=buyer_order_id,
                        design_name=design,
                        color=color,
                        quantity_produced=inspected_qty,
                        quantity_inspected=inspected_qty,
                        quantity_passed=inspected_qty,
                        quantity_rejected=0,
                        quantity_ready=inspected_qty,
                        status='READY',
                        production_date=datetime.utcnow(),
                    ))
            db.commit()
            
            if not crud.can_move_forward(db, buyer_order_id):
                return {'success': False, 'message': 'Cannot move forward from FG_INSPECTION'}
            move_result = crud.move_stage(db, buyer_order_id, 'forward', 'system')
        
        # Version to stamp the ledger rows written below. If PASS moved the
        # token, use the new version; otherwise keep the pre-call version.
        final_version = move_result['new_version'] if move_result else ledger_version
        
        # Supersede any prior non-CANCELLED FG_INSPECTION ledger rows for this
        # order. Written AFTER the move so the CANCELLED rows carry the
        # post-move version and are not stranded.
        prior_fgi = [e for e in all_entries
                     if e.activity_type == 'FG_INSPECTION'
                     and e.buyer_order_id == buyer_order_id
                     and e.status != 'CANCELLED']
        now_ts = datetime.utcnow()
        for old_row in prior_fgi:
            crud.add_ledger_entry(db, {
                'fg_key': old_row.fg_key or '',
                'buyer_order_id': buyer_order_id,
                'activity_type': 'FG_INSPECTION',
                'status': 'CANCELLED',
                'buyer_name': old_row.buyer_name,
                'buyer_order_no': old_row.buyer_order_no,
                'order_date': old_row.order_date,
                'created_date': old_row.created_date,
                'qty': old_row.qty,
                'workflow_position': old_row.workflow_position,
                'version': final_version,
                'extra_data': {
                    **(old_row.extra_data or {}),
                    'cancelledAt': now_ts.isoformat(),
                    'cancelledReason': 'Superseded by new FG inspection submit',
                    'supersededBy': 'submit_fg_inspection'
                }
            })
        
        crud.add_ledger_entry(db, {
            'fg_key': bo.fg_key if bo else '',
            'buyer_order_id': buyer_order_id,
            'activity_type': 'FG_INSPECTION',
            'status': 'PASSED' if decision == 'PASS' else 'FAILED',
            'buyer_name': bo.buyer_name if bo else '',
            'buyer_order_no': bo.buyer_order_no if bo else '',
            'order_date': bo.order_date if bo else None,
            'created_date': datetime.utcnow(),
            'qty': sum(float(r.get('inspectedQty', 0) or 0) for r in rows),
            'workflow_position': 8,
            'version': final_version,
            'extra_data': {
                'inspector': inspector,
                'decision': decision,
                'rowCount': len(rows),
                'submittedAt': datetime.utcnow().isoformat()
            }
        })
        
        return {
            'success': True,
            'message': f'Inspection recorded: {decision}. ' + ('Buyer order moved to FG Inventory.' if decision == 'PASS' else 'Order remains in FG Inspection.'),
            'decision': decision,
            'failCount': db.query(models.FGInspectionRecord).filter(
                models.FGInspectionRecord.buyer_order_id == buyer_order_id,
                models.FGInspectionRecord.status == 'FAILED'
            ).count(),
            'newStage': move_result['new_stage'] if move_result else None,
            'newVersion': move_result['new_version'] if move_result else None,
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}
