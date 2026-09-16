from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
from ..models import InternalFGOrder, ActivityLedger, StageTransition
import uuid

router = APIRouter(prefix="/internal-fg", tags=["Internal FG Order"])

@router.get("/orders")
def get_internal_fg_orders(db: Session = Depends(get_db)):
    """
    Get all buyer orders currently in INTERNAL_FG_ORDER stage,
    enriched with their FG grid (from the latest BUYER_ORDER version)
    and any existing InternalFGOrder factory records.
    """
    from .. import models
    
    tokens = db.query(crud.WorkflowToken).filter(
        crud.WorkflowToken.current_stage == "INTERNAL_FG_ORDER",
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
        
        # Deduplicate by fg_key (defensive; live query already returns one per fg)
        fg_map = {}
        for e in fg_entries:
            if e.fg_key not in fg_map or e.id > fg_map[e.fg_key].id:
                fg_map[e.fg_key] = e
        
        # Build FG list with size-wise breakdown
        fgs = []
        for fg_key, entry in fg_map.items():
            grid_row = (entry.extra_data or {}).get('gridRow', [])
            sizes = (entry.extra_data or {}).get('sizes', [])
            design = (entry.extra_data or {}).get('fgDesign', '')
            color = (entry.extra_data or {}).get('fgColor', '')
            
            # Parse size-wise qty from grid row (indices 3 onwards before trailing meta)
            size_qtys = {}
            total_qty = 0
            # gridRow layout: [serial, design, color, <sizes...>, buyer_name, buyer_order_no, order_date, created_date]
            # The last 4 cells are trailing metadata, not sizes. Bound the size loop
            # so we never call float() on a metadata string (which would raise
            # "could not convert string to float" — e.g. on a truncated grid row).
            size_end = max(0, len(grid_row) - 4)
            for i, size in enumerate(sizes):
                col_idx = 3 + i
                if col_idx < size_end:
                    qty = float(grid_row[col_idx] or 0)
                    size_qtys[str(size)] = qty
                    total_qty += qty
            
            # Check if there's an existing factory order for this FG
            existing_order = db.query(InternalFGOrder).filter(
                InternalFGOrder.buyer_order_id == buyer_order_id,
                InternalFGOrder.fg_key == fg_key
            ).first()
            
            fgs.append({
                'fgKey': fg_key,
                'design': design,
                'color': color,
                'sizes': sizes,
                'sizeQtys': size_qtys,
                'totalQty': total_qty,
                'extraPercentage': (existing_order.extra_data or {}).get('extra_percentage', 0) if existing_order else 0,
                'factoryOrderId': existing_order.internal_order_id if existing_order else None,
                'factoryQty': float(existing_order.quantity) if existing_order else 0,
                'productionStatus': existing_order.production_status if existing_order else None
            })
        
        result.append({
            'buyerOrderId': buyer_order_id,
            'buyerName': buyer_order.buyer_name or 'Unknown',
            'buyerOrderNo': buyer_order.buyer_order_no or 'N/A',
            'orderDate': buyer_order.order_date,
            'currentStage': token.current_stage,
            'currentVersion': token.current_version,
            'totalFGs': len(fgs),
            'fgs': fgs
        })
    
    return result

@router.post("/save")
def save_internal_fg_order(data: Dict, db: Session = Depends(get_db)):
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        fg_key = data.get('fg_key', '')
        units = data.get('units', 1)
        qty_per_unit = data.get('qty_per_unit', 0)
        worker = data.get('worker', '')
        line = data.get('line', '')
        extra_percentage = data.get('extra_percentage', 0)
        if not buyer_order_id or not fg_key or qty_per_unit <= 0:
            return {"success": False, "message": "Missing required fields"}
        existing = db.query(InternalFGOrder).filter(
            InternalFGOrder.buyer_order_id == buyer_order_id,
            InternalFGOrder.fg_key == fg_key
        ).first()
        if existing:
            return {"success": False, "message": "FG Order already exists"}
        base_total = units * qty_per_unit
        extra_quantity = base_total * (extra_percentage / 100)
        total_quantity = base_total + extra_quantity
        internal_order = InternalFGOrder(
            internal_order_id=f"IFG-{uuid.uuid4().hex[:6].upper()}",
            buyer_order_id=buyer_order_id,
            fg_key=fg_key,
            unit_number=units,
            quantity=total_quantity,
            production_status='PENDING',
            worker_assigned=worker,
            line_assigned=line,
            extra_data={
                'base_quantity': base_total,
                'extra_percentage': extra_percentage,
                'extra_quantity': extra_quantity,
                'createdAt': datetime.utcnow().isoformat()
            }
        )
        db.add(internal_order)
        db.commit()
        return {"success": True, "message": f"Internal FG Order created: {internal_order.internal_order_id}"}
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

@router.post("/issue-factory-order")
def issue_factory_order(data: Dict, db: Session = Depends(get_db)):
    """
    Issue factory orders for all FGs of a buyer order with per-FG extra percentage (0-7% cap).
    Creates InternalFGOrder records, then moves token INTERNAL_FG_ORDER -> ISSUE_RM.
    """
    from .. import models
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        fg_data = data.get('fg_data', [])  # [{fgKey, extraPercentage}, ...]
        
        if not buyer_order_id:
            return {"success": False, "message": "Buyer Order ID is required"}
        if not fg_data:
            return {"success": False, "message": "No FG data provided"}
        
        # Validate extra% range
        for fg in fg_data:
            pct = float(fg.get('extraPercentage', 0))
            if pct < 0 or pct > 7:
                return {"success": False, "message": f"Extra % must be 0-7 (got {pct})"}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found"}
        if token_state["current_stage"] != "INTERNAL_FG_ORDER":
            return {"success": False, "message": f"Cannot issue from stage: {token_state['current_stage']}"}
        if not crud.can_move_forward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move forward"}
        
        all_entries = crud.get_ledger_entries(db)
        latest_version = crud.get_latest_buyer_order_version(db, buyer_order_id)
        fg_entries = [e for e in all_entries 
                     if e.buyer_order_id == buyer_order_id 
                     and e.activity_type == 'BUYER_ORDER' 
                     and e.status == 'COMPLETED'
                     and e.version == latest_version]
        fg_map = {}
        for e in fg_entries:
            if e.fg_key not in fg_map or e.id > fg_map[e.fg_key].id:
                fg_map[e.fg_key] = e
        
        # Check for existing LIVE factory orders. CANCELLED rows do not block
        # a re-issue: once Issue RM is reversed, the old factory orders are
        # cancelled and the user can issue fresh ones at this stage.
        existing_orders = db.query(InternalFGOrder).filter(
            InternalFGOrder.buyer_order_id == buyer_order_id,
            InternalFGOrder.production_status != 'CANCELLED',
        ).all()
        existing_fg_keys = {o.fg_key for o in existing_orders}
        
        created_orders = []
        for fg in fg_data:
            fg_key = fg.get('fgKey', '')
            pct = float(fg.get('extraPercentage', 0))
            
            if fg_key in existing_fg_keys:
                return {"success": False, "message": f"Factory order already exists for FG {fg_key}"}
            
            entry = fg_map.get(fg_key)
            if not entry:
                return {"success": False, "message": f"FG {fg_key} not found in buyer order"}
            
            grid_row = (entry.extra_data or {}).get('gridRow', [])
            sizes = (entry.extra_data or {}).get('sizes', [])
            
            # Compute total qty from all sizes
            total_qty = 0
            # gridRow layout: [serial, design, color, <sizes...>, buyer_name, buyer_order_no, order_date, created_date]
            # The last 4 cells are trailing metadata, not sizes. Bound the size loop
            # so we never call float() on a metadata string.
            size_end = max(0, len(grid_row) - 4)
            for i in range(len(sizes)):
                col_idx = 3 + i
                if col_idx < size_end:
                    total_qty += float(grid_row[col_idx] or 0)
            
            if total_qty <= 0:
                continue
            
            extra_qty = total_qty * (pct / 100)
            factory_qty = total_qty + extra_qty
            
            order = InternalFGOrder(
                internal_order_id=f"IFG-{uuid.uuid4().hex[:6].upper()}",
                buyer_order_id=buyer_order_id,
                fg_key=fg_key,
                unit_number=1,
                quantity=factory_qty,
                production_status='PENDING',
                extra_data={
                    'base_quantity': total_qty,
                    'extra_percentage': pct,
                    'extra_quantity': extra_qty,
                    'createdAt': datetime.utcnow().isoformat(),
                    'buyerOrderVersion': latest_version
                }
            )
            db.add(order)
            created_orders.append({
                'internalOrderId': order.internal_order_id,
                'fgKey': fg_key,
                'baseQty': total_qty,
                'extraPercent': pct,
                'extraQty': extra_qty,
                'factoryQty': factory_qty
            })
        
        if not created_orders:
            return {"success": False, "message": "No factory orders created (all FGs had zero qty)"}
        
        db.commit()
        
        # Move token INTERNAL_FG_ORDER -> ISSUE_RM
        move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
        
        # Write ledger entry for traceability
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        
        # Supersede any prior non-CANCELLED INTERNAL_FG_ORDER rows for this order.
        # Q2 key is (buyer_order_id, fg_key); rows here use fg_key='', so this
        # collapses to one live summary row per order.
        prior_ifg = [e for e in crud.get_ledger_entries(db, activity_type='INTERNAL_FG_ORDER')
                     if e.buyer_order_id == buyer_order_id and e.status != 'CANCELLED']
        now_ts = datetime.utcnow()
        for old_row in prior_ifg:
            crud.add_ledger_entry(db, {
                'buyer_order_id': buyer_order_id,
                'fg_key': old_row.fg_key or '',
                'activity_type': 'INTERNAL_FG_ORDER',
                'status': 'CANCELLED',
                'buyer_name': old_row.buyer_name,
                'buyer_order_no': old_row.buyer_order_no,
                'order_date': old_row.order_date,
                'created_date': old_row.created_date,
                'qty': old_row.qty,
                'workflow_position': old_row.workflow_position,
                'version': old_row.version or 1,
                'extra_data': {
                    **(old_row.extra_data or {}),
                    'cancelledAt': now_ts.isoformat(),
                    'cancelledReason': 'New factory order issued',
                    'supersededBy': 'issue_factory_order'
                }
            })
        
        ledger_entry = {
            'buyer_order_id': buyer_order_id,
            'fg_key': '',
            'activity_type': 'INTERNAL_FG_ORDER',
            'status': 'COMPLETED',
            'buyer_name': buyer_order.buyer_name if buyer_order else '',
            'buyer_order_no': buyer_order.buyer_order_no if buyer_order else '',
            'order_date': buyer_order.order_date if buyer_order else None,
            'created_date': buyer_order.created_date if buyer_order else None,
            'qty': sum(o['factoryQty'] for o in created_orders),
            'workflow_position': 6,
            'version': move_result['new_version'],
            'extra_data': {
                'factoryOrders': created_orders,
                'issuedAt': datetime.utcnow().isoformat(),
                'version': move_result['new_version'],
                'previous_version': move_result['previous_version'],
                'stage_movement': 'forward',
                'from_stage': move_result['previous_stage'],
                'to_stage': move_result['new_stage']
            }
        }
        crud.add_ledger_entry(db, ledger_entry)
        
        return {
            'success': True,
            'message': f'Factory orders issued for {len(created_orders)} FGs. Buyer order moved to Issue RM.',
            'factoryOrders': created_orders,
            'newStage': move_result['new_stage'],
            'newVersion': move_result['new_version']
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

@router.post("/process")
def process_internal_fg_order(data: Dict, db: Session = Depends(get_db)):
    try:
        internal_order_id = data.get('internal_order_id', '')
        if not internal_order_id:
            return {"success": False, "message": "Internal Order ID is required"}
        internal_order = db.query(InternalFGOrder).filter(
            InternalFGOrder.internal_order_id == internal_order_id
        ).first()
        if not internal_order:
            return {"success": False, "message": "Internal FG Order not found"}
        buyer_order_id = internal_order.buyer_order_id
        if not buyer_order_id:
            return {"success": False, "message": "Buyer Order ID not found"}
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found"}
        if token_state["current_stage"] != "INTERNAL_FG_ORDER":
            return {"success": False, "message": f"Cannot process from stage: {token_state['current_stage']}"}
        if not crud.can_move_forward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move forward"}
        move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
        internal_order.production_status = 'COMPLETED'
        db.commit()
        return {
            'success': True,
            'message': f'Internal FG Order processed. Moved to Issue RM.',
            'new_stage': move_result["new_stage"],
            'new_version': move_result["new_version"]
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}

@router.post("/cancel")
def cancel_internal_fg_order(data: Dict, db: Session = Depends(get_db)):
    try:
        internal_order_id = data.get('internal_order_id', '')
        if not internal_order_id:
            return {"success": False, "message": "Internal Order ID is required"}
        internal_order = db.query(InternalFGOrder).filter(
            InternalFGOrder.internal_order_id == internal_order_id
        ).first()
        if not internal_order:
            return {"success": False, "message": "Internal FG Order not found"}
        buyer_order_id = internal_order.buyer_order_id
        if not buyer_order_id:
            return {"success": False, "message": "Buyer Order ID not found"}
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found"}
        if token_state["current_stage"] != "INTERNAL_FG_ORDER":
            return {"success": False, "message": f"Cannot cancel from stage: {token_state['current_stage']}"}
        if not crud.can_move_backward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move backward"}
        move_result = crud.move_stage(db, buyer_order_id, "backward", "system")
        internal_order.production_status = 'CANCELLED'
        db.commit()
        return {
            'success': True,
            'message': f'Internal FG Order cancelled. Moved back to GRN.',
            'new_stage': move_result["new_stage"],
            'new_version': move_result["new_version"]
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}


@router.post("/cancel-buyer-order")
def cancel_internal_fg_for_buyer(data: Dict, db: Session = Depends(get_db)):
    """
    Cancel INTERNAL_FG_ORDER stage for a whole buyer order.

    Semantically this is a GRN cancellation viewed from one stage forward:
    the only way to reach INTERNAL_FG_ORDER is a completed GRN, so cancelling
    here must reverse the GRN intake (stock out), flip the PO back to NR, and
    land the token on GRN.

    Requires return_doc_no and cancel_reason so the ledger carries an audit
    trail for the stock reversal.
    """
    from .. import models
    try:
        buyer_order_id = crud.clean_key_exact(data.get('buyer_order_id', ''))
        return_doc_no = (data.get('return_doc_no') or '').strip()
        cancel_reason = (data.get('cancel_reason') or '').strip()

        if not buyer_order_id:
            return {'success': False, 'message': 'Buyer Order ID required'}
        if not return_doc_no:
            return {'success': False, 'message': 'Return Document No is required'}
        if not cancel_reason:
            return {'success': False, 'message': 'Reason for Cancellation is required'}

        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {'success': False, 'message': 'No workflow token found'}
        if token_state['current_stage'] != 'INTERNAL_FG_ORDER':
            return {'success': False, 'message': f"Cannot cancel from stage: {token_state['current_stage']}"}
        if not crud.can_move_backward(db, buyer_order_id):
            return {'success': False, 'message': 'Cannot move backward'}

        active_orders = db.query(InternalFGOrder).filter(
            InternalFGOrder.buyer_order_id == buyer_order_id,
            InternalFGOrder.production_status != 'CANCELLED'
        ).all()

        now = datetime.utcnow()
        cancelled_count = 0
        for io in active_orders:
            io.production_status = 'CANCELLED'
            ed = dict(io.extra_data or {})
            ed['cancelledAt'] = now.isoformat()
            ed['cancelledReason'] = cancel_reason
            ed['returnDocNo'] = return_doc_no
            io.extra_data = ed
            cancelled_count += 1

        db.commit()

        # ------------------------------------------------------------------
        # Reverse GRN intake BEFORE flipping statuses / moving the token.
        # For every live GRN row of this buyer order, subtract its received
        # qty from inventory_snapshot (grnDelta negative) and mark the GRN
        # row CANCELLED so the PO's GRN table status goes back to NR.
        # ------------------------------------------------------------------
        # Move the token FIRST so the version bump stamps every row we
        # are about to write. CANCELLED rows written before move_stage
        # get stranded at the pre-move version and are excluded from the
        # live view by the version filter — the PO would still show
        # RECEIVED. Move first, then write cancellations at the new version.
        move_result = crud.move_stage(db, buyer_order_id, 'backward', 'system')
        cancel_version = move_result['new_version']
        now_ts = datetime.utcnow()
        live_grns = crud.get_live_ledger_entries(
            db, activity_type='GRN', buyer_order_id=buyer_order_id
        )
        snapshot_updates = []
        grn_cancel_rows = []
        # Pre-load all ledger rows once so the idempotency check below is O(1) per line.
        _all_entries_for_guard = crud.get_ledger_entries(db)
        for grn in live_grns:
            ed = grn.extra_data or {}
            req_key = ed.get('requirementKey', '')
            received_qty = float(grn.qty or 0)
            if received_qty <= 0 or not req_key:
                continue

            # Idempotency guard: if this exact (receive row, line) has
            # already been reversed by an earlier Internal FG cancel, skip.
            # Keyed on reverseOfLedgerId + reverseOfLineKey so re-running
            # cancel cannot double-subtract from the snapshot.
            line_key = f"{ed.get('itemNo','')}|{ed.get('garmentSize', grn.size or 'ALL')}|{req_key}"
            already_reversed = False
            for e in _all_entries_for_guard:
                if (e.activity_type == 'GRN'
                    and e.status == 'CANCELLED'
                    and e.extra_data
                    and e.extra_data.get('reverseOfLedgerId') == grn.id
                    and e.extra_data.get('reverseOfLineKey') == line_key):
                    already_reversed = True
                    break
            if already_reversed:
                continue

            snapshot_updates.append({
                'requirementKey': req_key,
                'fgKey': grn.fg_key,
                'itemNo': ed.get('itemNo', ''),
                'itemName': ed.get('itemName', ''),
                'size': ed.get('garmentSize', grn.size or 'ALL'),
                'color': ed.get('color', grn.color or ''),
                'supplier': ed.get('supplier', ''),
                'requiredDelta': 0,
                'grnDelta': -received_qty,
                'issueDelta': 0
            })
            grn_cancel_rows.append({
                'fg_key': grn.fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'GRN',
                'status': 'CANCELLED',
                'buyer_name': grn.buyer_name,
                'buyer_order_no': grn.buyer_order_no,
                'order_date': grn.order_date,
                'created_date': grn.created_date,
                'qty': 0,
                'size': grn.size,
                'color': grn.color,
                'workflow_position': grn.workflow_position,
                'version': cancel_version,
                'extra_data': {
                    **ed,
                    'cancelledAt': now_ts.isoformat(),
                    'cancelledReason': cancel_reason,
                    'returnDocNo': return_doc_no,
                    'supersededBy': 'cancel_internal_fg_for_buyer',
                    'reverseOfLedgerId': grn.id,
                    'reverseOfLineKey': line_key
                }
            })

        # Apply stock reversal + GRN cancellations
        if snapshot_updates:
            crud.update_inventory_snapshot(db, snapshot_updates)
        if grn_cancel_rows:
            crud.add_ledger_entries_bulk(db, grn_cancel_rows)


        bo = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        
        # Supersede any prior non-CANCELLED INTERNAL_FG_ORDER ledger rows.
        # Without this, get_live_ledger_entries would still return the old
        # COMPLETED row as "live" after cancel — because CANCELLED rows are
        # excluded from candidacy but the old COMPLETED row was never cancelled.
        prior_ifg = [e for e in crud.get_ledger_entries(db, activity_type='INTERNAL_FG_ORDER')
                     if e.buyer_order_id == buyer_order_id and e.status != 'CANCELLED']
        for old_row in prior_ifg:
            crud.add_ledger_entry(db, {
                'buyer_order_id': buyer_order_id,
                'fg_key': old_row.fg_key or '',
                'activity_type': 'INTERNAL_FG_ORDER',
                'status': 'CANCELLED',
                'buyer_name': old_row.buyer_name,
                'buyer_order_no': old_row.buyer_order_no,
                'order_date': old_row.order_date,
                'created_date': old_row.created_date,
                'qty': old_row.qty,
                'workflow_position': old_row.workflow_position,
                'version': old_row.version or 1,
                'extra_data': {
                    **(old_row.extra_data or {}),
                    'cancelledAt': now.isoformat(),
                    'cancelledReason': cancel_reason,
                    'returnDocNo': return_doc_no,
                    'supersededBy': 'cancel-buyer-order',
                    'cancelledFGOrders': cancelled_count
                }
            })
        
        return {
            'success': True,
            'message': f'Internal FG Order cancelled. {cancelled_count} factory order(s) cancelled. Moved back to GRN.',
            'newStage': move_result['new_stage'],
            'newVersion': move_result['new_version'],
            'cancelledFGOrders': cancelled_count
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}
