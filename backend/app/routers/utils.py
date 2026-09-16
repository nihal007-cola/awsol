from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/utils", tags=["Utilities"])

@router.get("/debug/fg-status")
def debug_fg_status(fg_key: str, db: Session = Depends(get_db)):
    """Debug endpoint to check FG status"""
    try:
        clean_fg_key = crud.clean_key_exact(fg_key)
        entries = crud.get_ledger_entries(db, clean_fg_key)
        workflow = settings.get_workflow_list()
        result = {
            'fgKey': clean_fg_key,
            'currentPosition': crud.get_current_workflow_position(db, clean_fg_key),
            'totalEntries': len(entries),
            'allStatuses': {},
            'entries': [{
                'activity': e.activity_type,
                'status': e.status,
                'qty': e.qty,
                'size': e.size,
                'color': e.color,
                'extra_data': e.extra_data
            } for e in entries]
        }
        for module in workflow:
            status = crud.get_latest_status(db, clean_fg_key, module)
            result['allStatuses'][module] = status.status if status else 'NOT FOUND'
        return result
    except Exception as e:
        return {'error': str(e), 'fgKey': fg_key}

@router.post("/cancel/stage")
def cancel_stage(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Thin router. Delegates to the per-stage cancel endpoints, which own the
    token movement and the snapshot reversal. This endpoint no longer writes
    ledger or snapshot rows itself (that was a token-less bypass that could
    reverse the same stock more than once)."""
    from . import (
        bom as _bom,
        costing_approval as _ca,
        grn as _grn,
        issue_rm as _issue,
        rm_order as _rm,
        internal_fg_order as _ifg,
        fg_inspection as _fgi,
        fg_inventory as _fginv,
    )
    from .. import models as _models
    try:
        fg_key = crud.clean_key_exact(data.get('fgKey', ''))
        target_stage = (data.get('targetStage') or '').upper()
        if not fg_key:
            return {'success': False, 'message': 'FG Key is required'}
        if not target_stage:
            return {'success': False, 'message': 'Target stage is required'}

        buyer_order_id = fg_key.split('|')[0] if '|' in fg_key else fg_key

        token = db.query(_models.WorkflowToken).filter(
            _models.WorkflowToken.buyer_order_id == buyer_order_id
        ).first()
        if not token:
            return {'success': False, 'message': f'No workflow token for {buyer_order_id}'}
        if token.current_stage != target_stage:
            return {
                'success': False,
                'message': f'Order is at {token.current_stage}, cannot cancel {target_stage}',
            }

        passthrough = {
            'buyer_order_id': buyer_order_id,
            'return_doc_no': data.get('return_doc_no', ''),
            'cancel_reason': data.get('cancel_reason', '') or f'Cancelled {target_stage} via /utils/cancel/stage',
        }

        if target_stage == 'BOM':
            return _bom.cancel_bom(passthrough, db)
        if target_stage == 'COSTING_APPROVAL':
            passthrough['rejection_reason'] = data.get('rejection_reason', '') or passthrough['cancel_reason']
            return _ca.reject_costing(passthrough, db)
        if target_stage == 'RM_ORDER':
            return _rm.cancel_rm_order_for_buyer(passthrough, db)
        if target_stage == 'GRN':
            live_pos = crud.get_live_ledger_entries(
                db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
                extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
            )
            po_tokens = sorted({(e.extra_data or {}).get('poToken') for e in live_pos if (e.extra_data or {}).get('poToken')})
            if not po_tokens:
                return _grn.cancel_grn_buyer_order(passthrough, db)
            results = []
            for pt in po_tokens:
                results.append(_grn.cancel_grn({
                    'po_token': pt,
                    'invoice_no': data.get('invoice_no', ''),
                    'return_doc_no': passthrough['return_doc_no'],
                    'cancel_reason': passthrough['cancel_reason'],
                }, db))
            ok = all(r.get('success') for r in results) if results else False
            return {
                'success': ok,
                'message': f'Delegated GRN cancel to {len(po_tokens)} PO(s)',
                'results': results,
            }
        if target_stage == 'INTERNAL_FG_ORDER':
            return _ifg.cancel_internal_fg_for_buyer(passthrough, db)
        if target_stage == 'ISSUE_RM':
            return _issue.cancel_issue_rm(passthrough, db)
        if target_stage == 'FG_INSPECTION':
            return _fgi.cancel_fg_inspection(passthrough, db)
        if target_stage == 'FG_INVENTORY':
            return _fginv.send_back_to_inspection(passthrough, db)

        return {'success': False, 'message': f'No delegation for stage {target_stage}'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

def can_cancel_stage(db: Session, fg_key: str, target_stage: str) -> Dict:
    """Check if a stage can be cancelled"""
    clean_fg_key = crud.clean_key_exact(fg_key)
    entries = crud.get_ledger_entries(db, clean_fg_key)
    workflow = settings.get_workflow_list()
    
    statuses = {}
    for module in workflow:
        status = crud.get_latest_status(db, clean_fg_key, module)
        statuses[module] = status.status if status else 'NOT_FOUND'
    
    target_pos = crud.get_module_position(target_stage)
    current_pos = crud.get_current_workflow_position(db, clean_fg_key)
    
    if current_pos < target_pos:
        return {'canCancel': False, 'reason': f'{target_stage} not yet reached. Current position: {current_pos}'}
    
    downstream_stages = workflow[target_pos + 1:]
    for stage in downstream_stages:
        status = statuses.get(stage)
        if status and status != 'NOT_FOUND' and status != 'CANCELLED':
            return {'canCancel': False, 'reason': f'Cannot cancel {target_stage}. {stage} already exists ({status}).'}
    
    return {'canCancel': True, 'reason': 'Can cancel'}

@router.post("/cancel/order")
def cancel_whole_order(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Cancel an entire order (all FGs)"""
    try:
        fg_order_serial = crud.clean_key_exact(data.get('fgOrderSerial', ''))
        if not fg_order_serial:
            raise ValueError('FG Order Serial is required')
        
        entries = crud.get_ledger_entries_for_order(db, fg_order_serial)
        fg_keys = []
        
        for entry in entries:
            fg_key = crud.clean_key_exact(entry.fg_key)
            serial = fg_key.split('|')[0] if fg_key else ''
            if serial == fg_order_serial:
                if fg_key not in fg_keys:
                    fg_keys.append(fg_key)
        
        if not fg_keys:
            raise ValueError('Order not found: ' + fg_order_serial)
        
        results = []
        for fg_key in fg_keys:
            current_pos = crud.get_current_workflow_position(db, fg_key)
            if current_pos > 1:
                check = can_cancel_stage(db, fg_key, 'BOM')
                if not check['canCancel']:
                    results.append({'fgKey': fg_key, 'success': False, 'reason': check['reason']})
                    continue
            
            cancel_result = cancel_stage({'fgKey': fg_key, 'targetStage': 'BUYER_ORDER'}, db)
            results.append({'fgKey': fg_key, 'success': cancel_result.get('success', False), 'message': cancel_result.get('message', '')})
        
        all_success = all(r.get('success', False) for r in results)
        return {
            'success': all_success,
            'message': 'Order cancelled successfully' if all_success else 'Some FGs could not be cancelled',
            'results': results
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

@router.get("/cancellations/{buyer_order_id}")
def get_cancellations(buyer_order_id: str, db: Session = Depends(get_db)):
    """
    Consolidated cancellation ledger for a buyer order.
    One row per CANCELLED ledger entry, across every activity type,
    with the reason / supersededBy / reverse markers flattened so the
    flow can be eyeballed in one place.

    Grouped by activity_type, sorted by id.
    """
    from collections import defaultdict

    clean_bo = crud.clean_key_exact(buyer_order_id)
    from .. import models as _models
    rows = db.query(_models.ActivityLedger).filter(
        _models.ActivityLedger.buyer_order_id == clean_bo,
        _models.ActivityLedger.status == 'CANCELLED',
    ).order_by(_models.ActivityLedger.id.asc()).all()

    grouped = defaultdict(list)
    for r in rows:
        ed = r.extra_data or {}
        grouped[r.activity_type].append({
            'id': r.id,
            'version': r.version,
            'qty': float(r.qty or 0),
            'fg_key': r.fg_key or '',
            'size': r.size or '',
            'color': r.color or '',
            'poToken': ed.get('poToken', ''),
            'requirementKey': ed.get('requirementKey', ''),
            'invoiceNo': ed.get('invoiceNo', ''),
            'itemNo': ed.get('itemNo', ''),
            'cancelledAt': ed.get('cancelledAt', ''),
            'cancelledReason': ed.get('cancelledReason', ''),
            'supersededBy': ed.get('supersededBy', ''),
            'reverseOfLedgerId': ed.get('reverseOfLedgerId'),
            'reverseOfLineKey': ed.get('reverseOfLineKey', ''),
        })

    return {
        'buyerOrderId': clean_bo,
        'totalCancelled': len(rows),
        'byActivity': {k: v for k, v in sorted(grouped.items())},
    }


@router.get("/health")
def health_check():
    return {"status": "healthy", "version": "1.0.0"}

@router.get("/workflow")
def get_workflow():
    return {"workflow": settings.get_workflow_list()}

@router.get("/settings")
def get_settings():
    return {
        "company_name": settings.company_name,
        "company_address": settings.company_address,
        "company_gst": settings.company_gst,
        "company_state": settings.company_state,
        "tolerance": settings.tolerance,
        "issue_buffer_percent": settings.issue_buffer_percent,
        "default_sizes": settings.get_default_sizes_list()
    }
# ==============================================================
# ADD THIS TO backend/app/routers/utils.py
# After the existing code, before the final router
# ==============================================================

# ==============================================================
# REPLACE the /cancel/fg endpoint in backend/app/routers/utils.py
# With this corrected version that enforces workflow rules
# ==============================================================

# ==============================================================
# FIX: Replace the /cancel/fg endpoint with corrected syntax
# ==============================================================

@router.post("/cancel/fg")
def cancel_entire_fg(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Cancel an FG ONLY if it's still in BOM stage.
    Cancellation is blocked if downstream records exist.
    """
    try:
        fg_key = crud.clean_key_exact(data.get('fg_key', ''))
        
        if not fg_key:
            raise ValueError('FG Key is required')
        
        # Get all entries for this FG
        entries = crud.get_ledger_entries(db, fg_key)
        
        if not entries:
            raise ValueError(f'FG {fg_key} not found')
        
        # Check if already cancelled
        latest = entries[-1] if entries else None
        if latest and latest.status == 'CANCELLED':
            return {'success': False, 'message': f'FG {fg_key} is already cancelled'}
        
        # Check for downstream records
        rm_order_exists = any(e for e in entries if e.activity_type == 'RM_ORDER' and e.status not in ['CANCELLED'])
        req_exists = any(e for e in entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                       and e.status in ['ORDERED', 'RECEIVED'] and e.status not in ['CANCELLED'])
        grn_exists = any(e for e in entries if e.activity_type == 'GRN' and e.status not in ['CANCELLED'])
        issue_exists = any(e for e in entries if e.activity_type == 'ISSUE_RM' and e.status not in ['CANCELLED'])
        
        # BLOCK cancellation if any downstream exists
        if rm_order_exists or req_exists or grn_exists or issue_exists:
            error_msg = []
            if rm_order_exists:
                error_msg.append("RM Order exists")
            if req_exists:
                error_msg.append("RM Requirement exists")
            if grn_exists:
                error_msg.append("GRN exists")
            if issue_exists:
                error_msg.append("Issue RM exists")
            
            # Build error message without backslash in f-string expression
            blocked_msg = "This FG has already progressed beyond the BOM stage.\n\nBlocked because:\n- " + "\n- ".join(error_msg) + "\n\nPlease reverse the workflow one stage before cancelling."
            
            return {
                'success': False, 
                'message': blocked_msg,
                'blocked': True,
                'reason': error_msg
            }
        
        # If we get here, cancellation is allowed (only BOM exists)
        entries_to_insert = []
        cancelled_count = 0
        
        # Find BOM entry
        bom_entry = next((e for e in entries if e.activity_type == 'BOM' and e.status not in ['CANCELLED']), None)
        if bom_entry:
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'BOM',
                'status': 'CANCELLED',
                'buyer_name': bom_entry.buyer_name,
                'buyer_order_no': bom_entry.buyer_order_no,
                'order_date': bom_entry.order_date,
                'created_date': bom_entry.created_date,
                'qty': bom_entry.qty,
                'size': bom_entry.size,
                'color': bom_entry.color,
                'workflow_position': 0,
                'extra_data': {
                    **(bom_entry.extra_data or {}),
                    'cancelledAt': datetime.utcnow().isoformat(),
                    'cancelledFrom': 'BOM',
                    'previousStatus': bom_entry.status,
                    'cancelReason': 'BOM cancelled by user'
                }
            })
            cancelled_count += 1
        
        # Also cancel any PENDING MATERIAL_REQUIREMENT
        req_entries = [e for e in entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                      and e.status == 'PENDING' and e.status not in ['CANCELLED']]
        for req in req_entries:
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'CANCELLED',
                'buyer_name': req.buyer_name,
                'buyer_order_no': req.buyer_order_no,
                'order_date': req.order_date,
                'created_date': req.created_date,
                'qty': req.qty,
                'size': req.size,
                'color': req.color,
                'workflow_position': 0,
                'extra_data': {
                    **(req.extra_data or {}),
                    'cancelledAt': datetime.utcnow().isoformat(),
                    'cancelledFrom': 'BOM_CANCELLATION',
                    'previousStatus': req.status
                }
            })
            cancelled_count += 1
        
        if not bom_entry:
            buyer_order = next((e for e in entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
            if buyer_order:
                entries_to_insert.append({
                    'fg_key': fg_key,
                    'activity_type': 'BUYER_ORDER',
                    'status': 'CANCELLED',
                    'buyer_name': buyer_order.buyer_name,
                    'buyer_order_no': buyer_order.buyer_order_no,
                    'order_date': buyer_order.order_date,
                    'created_date': buyer_order.created_date,
                    'qty': buyer_order.qty,
                    'size': buyer_order.size,
                    'color': buyer_order.color,
                    'workflow_position': -1,
                    'extra_data': {
                        **(buyer_order.extra_data or {}),
                        'cancelledAt': datetime.utcnow().isoformat(),
                        'cancelledFrom': 'BOM_CANCELLATION',
                        'cancelReason': 'BOM cancelled by user'
                    }
                })
                cancelled_count += 1
        
        if not entries_to_insert:
            return {'success': False, 'message': 'No active records found to cancel'}
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {
            'success': True,
            'message': f'FG {fg_key} cancelled successfully from BOM stage',
            'cancelledCount': cancelled_count
        }
        
    except Exception as e:
        db.rollback()
        logging.error(f"Cancel FG error: {str(e)}")
        return {'success': False, 'message': str(e)}

# ==============================================================
# UOM MANAGEMENT ENDPOINTS
# ==============================================================

@router.get("/uoms")
def get_uoms(db: Session = Depends(get_db)):
    """Get all UOMs from settings"""
    from ..models import Settings
    import json
    
    uom_setting = db.query(Settings).filter(Settings.config_key == "uom_list").first()
    if not uom_setting:
        default_uoms = ["PCS", "MTR", "KG", "CONE", "SET", "ROLL"]
        return default_uoms
    try:
        return json.loads(uom_setting.config_value)
    except:
        return ["PCS", "MTR", "KG", "CONE", "SET", "ROLL"]

@router.post("/uoms")
def add_uom(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Add a new UOM"""
    from ..models import Settings
    import json
    
    uom = data.get('uom', '').strip().upper()
    if not uom:
        return {"success": False, "message": "UOM is required"}
    
    uom_setting = db.query(Settings).filter(Settings.config_key == "uom_list").first()
    if uom_setting:
        try:
            uoms = json.loads(uom_setting.config_value)
        except:
            uoms = ["PCS", "MTR", "KG", "CONE", "SET", "ROLL"]
        if uom in uoms:
            return {"success": False, "message": f"UOM '{uom}' already exists"}
        uoms.append(uom)
        uom_setting.config_value = json.dumps(uoms)
        uom_setting.updated_at = datetime.utcnow()
    else:
        default_uoms = ["PCS", "MTR", "KG", "CONE", "SET", "ROLL"]
        default_uoms.append(uom)
        uom_setting = Settings(
            config_key="uom_list",
            config_value=json.dumps(default_uoms),
            description="List of UOMs for RM items"
        )
        db.add(uom_setting)
    
    db.commit()
    return {"success": True, "message": f"UOM '{uom}' added successfully", "uom": uom}
