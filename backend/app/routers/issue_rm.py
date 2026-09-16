from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas, models
from ..database import get_db
from ..config import settings
import logging

router = APIRouter(prefix="/issue-rm", tags=["Issue RM"])

@router.get("/orders")
def get_issue_rm_orders(db: Session = Depends(get_db)):
    """Get buyer orders in ISSUE_RM stage with aggregate RM requirements"""
    from .. import models
    from decimal import Decimal
    
    tokens = db.query(crud.WorkflowToken).filter(
        crud.WorkflowToken.current_stage == "ISSUE_RM",
        crud.WorkflowToken.status == "ACTIVE"
    ).all()
    
    if not tokens:
        return []
    
    buyer_order_ids = [t.buyer_order_id for t in tokens]
    snapshot = crud.get_inventory_snapshot(db)
    
    result = []
    for token in tokens:
        buyer_order_id = token.buyer_order_id
        
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        if not buyer_order:
            continue
        
        # Aggregate snapshot rows for this buyer order
        total_required = Decimal('0')
        total_grn = Decimal('0')
        total_issued = Decimal('0')
        fg_keys = set()
        for s in snapshot:
            if s.buyer_order_id != buyer_order_id:
                continue
            total_required += Decimal(str(s.total_required_qty or 0))
            total_grn += Decimal(str(s.total_grn_received_qty or 0))
            total_issued += Decimal(str(s.total_issued_qty or 0))
            if s.fg_key:
                fg_keys.add(s.fg_key)
        
        available = total_grn - total_issued
        remaining = total_required - total_issued
        
        # Status: COMPLETED / PARTIAL / PENDING
        if remaining <= Decimal('0.001'):
            status = 'COMPLETED'
        elif total_issued > Decimal('0.001'):
            status = 'PARTIAL'
        else:
            status = 'PENDING'
        
        result.append({
            'buyerOrderId': buyer_order_id,
            'buyerOrderNo': buyer_order.buyer_order_no or 'N/A',
            'buyerName': buyer_order.buyer_name or 'Unknown',
            'orderDate': buyer_order.order_date,
            'required': float(total_required),
            'grnReceived': float(total_grn),
            'issued': float(total_issued),
            'available': float(available),
            'status': status,
            'fgCount': len(fg_keys),
            'currentStage': token.current_stage,
            'currentVersion': token.current_version,
        })
    
    return result

@router.get("/buyer-order/{buyer_order_id}")
def get_issue_rm_buyer_order_detail(buyer_order_id: str, db: Session = Depends(get_db)):
    """
    Get all FG grids for a buyer order in ISSUE_RM stage.
    Each FG grid shows RM item lines with:
      - Order Qty (from InternalFGOrder factory quantity)
      - Consumption (from BOM)
      - Required Qty (= Order Qty × Consumption, or snapshot's total_required_qty)
      - Available Qty (= current_stock from snapshot)
      - Issue Qty (user input)
    """
    from .. import models
    from decimal import Decimal
    from collections import defaultdict
    
    clean_bo_id = crud.clean_key_exact(buyer_order_id)
    snapshot = crud.get_inventory_snapshot(db)
    
    # Live BUYER_ORDER rows for this order (latest version only)
    fg_entries = crud.get_live_ledger_entries(
        db, activity_type='BUYER_ORDER', buyer_order_id=clean_bo_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    
    if not fg_entries:
        return {'success': False, 'message': 'Buyer order not found'}
    
    buyer_order = db.query(models.BuyerOrder).filter(
        models.BuyerOrder.buyer_order_id == clean_bo_id
    ).first()
    
    # Get InternalFGOrders for this buyer order (factory quantities)
    internal_orders = db.query(models.InternalFGOrder).filter(
        models.InternalFGOrder.buyer_order_id == clean_bo_id
    ).all()
    fg_order_qty = {}
    for io in internal_orders:
        base_qty = Decimal(str((io.extra_data or {}).get('base_quantity', 0) or io.quantity or 0))
        factory_qty = Decimal(str(io.quantity or 0))
        fg_order_qty[io.fg_key] = {
            'baseQty': float(base_qty),
            'factoryQty': float(factory_qty),
            'extraPercent': float((io.extra_data or {}).get('extra_percentage', 0))
        }
    
    # Get live BOM per FG (latest version per fg_key, COMPLETED only)
    live_bom = crud.get_live_ledger_entries(
        db, activity_type='BOM', buyer_order_id=clean_bo_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    bom_by_fg = {}
    for e in live_bom:
        fg_key = e.fg_key
        if fg_key not in bom_by_fg or (e.id > (bom_by_fg[fg_key].id or 0)):
            bom_by_fg[fg_key] = e
    
    # Build FG list
    fgs = []
    for fg_entry in fg_entries:
        fg_key = fg_entry.fg_key
        ed = fg_entry.extra_data or {}
        design = ed.get('fgDesign', '')
        color = ed.get('fgColor', '')
        
        # Snapshot rows for this FG
        fg_snapshot = [s for s in snapshot if s.fg_key == fg_key]
        
        # BOM items for this FG (for consumption)
        bom_entry = bom_by_fg.get(fg_key)
        bom_items = []
        if bom_entry and bom_entry.extra_data:
            bom_items = bom_entry.extra_data.get('items', [])
        
        # Build a lookup of BOM items by item_no + item_size
        bom_lookup = {}
        for bi in bom_items:
            k = f"{bi.get('item_no', '')}|{bi.get('item_size', '')}"
            bom_lookup[k] = bi
        
        # Order quantity for this FG (factory qty from InternalFGOrder)
        order_info = fg_order_qty.get(fg_key, {'baseQty': 0, 'factoryQty': 0, 'extraPercent': 0})
        order_qty = order_info['factoryQty']
        
        # Build item lines
        items = []
        for s in fg_snapshot:
            consumption = Decimal('0')
            # Look up consumption from BOM
            bom_item = bom_lookup.get(f"{s.item_no or ''}|{''}")
            if not bom_item:
                # Try matching just by item_no
                for bi in bom_items:
                    if bi.get('item_no') == s.item_no:
                        bom_item = bi
                        break
            if bom_item:
                consumption = Decimal(str(bom_item.get('consumption', 0) or 0))
            
            # Required for display = factory_qty x consumption.
            # The snapshot stores base x consumption; that stays untouched.
            # Only the value shown in the Issue RM modal is recomputed here.
            required = Decimal(str(order_qty)) * consumption
            grn = Decimal(str(s.total_grn_received_qty or 0))
            issued = Decimal(str(s.total_issued_qty or 0))
            available = grn - issued
            
            items.append({
                'requirementKey': s.requirement_key,
                'itemNo': s.item_no or '',
                'itemName': s.item_name or '',
                'garmentSize': s.garment_size or 'ALL',
                'color': s.color or '',
                'uom': 'PCS',
                'orderQty': float(order_qty),
                'consumption': float(consumption),
                'requiredQty': float(required),
                'grnQty': float(grn),
                'issuedQty': float(issued),
                'availableQty': float(available),
                'maxIssuable': float(min(available, required * Decimal(str(settings.issue_buffer_percent)))),
            })
        
        fgs.append({
            'fgKey': fg_key,
            'design': design,
            'color': color,
            'orderQty': float(order_qty),
            'baseQty': order_info['baseQty'],
            'extraPercent': order_info['extraPercent'],
            'items': items
        })
    
    return {
        'success': True,
        'buyerOrderId': clean_bo_id,
        'buyerOrderNo': buyer_order.buyer_order_no if buyer_order else 'N/A',
        'buyerName': buyer_order.buyer_name if buyer_order else 'Unknown',
        'orderDate': buyer_order.order_date.isoformat() if buyer_order and buyer_order.order_date else None,
        'fgs': fgs,
        'totalFGs': len(fgs)
    }

@router.get("/{fg_key}/items")
def get_issuable_items(fg_key: str, db: Session = Depends(get_db)):
    clean_fg_key = crud.clean_key_exact(fg_key)
    snapshot = crud.get_inventory_snapshot(db, clean_fg_key)
    
    return [{
        'itemNo': item.item_no or '',
        'itemName': item.item_name or '',
        'garmentSize': item.garment_size or 'ALL',
        'itemSize': '',
        'color': item.color or '',
        'requiredQty': item.total_required_qty or 0,
        'grnQty': item.total_grn_received_qty or 0,
        'issuedQty': item.total_issued_qty or 0,
        'availableToIssue': (item.total_grn_received_qty - item.total_issued_qty) if (item.total_grn_received_qty - item.total_issued_qty) > settings.tolerance else 0,
        'maxIssuable': item.total_required_qty * settings.issue_buffer_percent,
        'uom': 'PCS',
        'requirementKey': item.requirement_key or ''
    } for item in snapshot]

@router.post("/save")
def save_issue_rm(data: schemas.IssueRMSaveRequest, db: Session = Depends(get_db)):
    try:
        fg_key = crud.clean_key_exact(data.fg_key)
        items = data.items
        
        if not fg_key:
            raise ValueError('FG Key is required')
        if not items:
            raise ValueError('No items to issue')
        
        all_entries = crud.get_ledger_entries(db, fg_key)
        grn = next((e for e in all_entries if e.activity_type == 'GRN' and e.status == 'COMPLETED'), None)
        if not grn:
            raise ValueError('GRN must be completed before issuing materials')
        
        buyer_order = next((e for e in all_entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        order_info = {
            'buyerName': buyer_order.buyer_name if buyer_order else '',
            'buyerOrderNo': buyer_order.buyer_order_no if buyer_order else '',
            'orderDate': buyer_order.order_date if buyer_order else None,
            'createdDate': buyer_order.created_date if buyer_order else None
        }
        
        total_issued = 0
        total_required = 0
        all_complete = True
        issuance_items = []
        entries_to_insert = []
        snapshot_updates = []
        
        for item in items:
            requirement_key = item.requirement_key
            
            if not requirement_key:
                snapshot = crud.get_inventory_snapshot(db, fg_key)
                match = next((s for s in snapshot if s.item_name == item.item_name and 
                             (s.garment_size == item.garment_size or 'ALL')), None)
                if match:
                    requirement_key = match.requirement_key
            
            if not requirement_key:
                raise ValueError(f'Requirement key not found for item: {item.item_name}')
            
            required_qty = item.required_qty
            max_issuable = required_qty * settings.issue_buffer_percent
            issuing_qty = item.issuing_qty
            
            snapshot_items = crud.get_inventory_snapshot(db, None, requirement_key)
            current_stock = snapshot_items[0].current_stock if snapshot_items else 0
            total_req_from_snapshot = snapshot_items[0].total_required_qty if snapshot_items else required_qty
            
            if issuing_qty > current_stock + settings.tolerance:
                raise ValueError(f'Issuance for {item.item_name} exceeds available stock')
            if issuing_qty > max_issuable + settings.tolerance:
                raise ValueError(f'Issuance for {item.item_name} exceeds buffer limit')
            
            req_entry = next((e for e in all_entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                             and e.status == 'RECEIVED'
                             and e.extra_data and e.extra_data.get('requirementKey') == requirement_key), None)
            
            if not req_entry:
                raise ValueError(f'Requirement {requirement_key} not found')
            
            previously_issued = sum(e.qty or 0 for e in all_entries 
                                   if e.activity_type == 'MATERIAL_REQUIREMENT' 
                                   and e.status == 'ISSUED'
                                   and e.extra_data and e.extra_data.get('requirementKey') == requirement_key)
            
            remaining = total_req_from_snapshot - previously_issued - issuing_qty
            
            issuance_items.append({
                'itemNo': item.item_no or '',
                'itemName': item.item_name or '',
                'garmentSize': item.garment_size or 'ALL',
                'itemSize': item.item_size or '',
                'color': item.color or '',
                'requiredQty': total_req_from_snapshot,
                'previouslyIssued': previously_issued,
                'currentlyIssuing': issuing_qty,
                'remaining': remaining,
                'maxIssuable': max_issuable,
                'availableToIssue': current_stock,
                'uom': item.uom or 'PCS',
                'requirementKey': requirement_key
            })
            
            total_issued += issuing_qty
            total_required += total_req_from_snapshot
            if remaining > settings.tolerance:
                all_complete = False
            
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'ISSUED',
                'buyer_name': req_entry.buyer_name,
                'buyer_order_no': req_entry.buyer_order_no,
                'order_date': req_entry.order_date,
                'created_date': req_entry.created_date,
                'qty': issuing_qty,
                'size': req_entry.size,
                'color': req_entry.color,
                'workflow_position': 1.5,
                'extra_data': {
                    **(req_entry.extra_data or {}),
                    'issuedAt': datetime.utcnow().isoformat(),
                    'previouslyIssued': previously_issued,
                    'cumulativeIssued': previously_issued + issuing_qty,
                    'remaining': remaining,
                    'grnAvailable': current_stock
                }
            })
            
            snapshot_updates.append({
                'requirementKey': requirement_key,
                'fgKey': fg_key,
                'itemNo': item.item_no or '',
                'itemName': item.item_name or '',
                'size': item.garment_size or 'ALL',
                'color': item.color or '',
                'supplier': '',
                'requiredDelta': 0,
                'grnDelta': 0,
                'issueDelta': issuing_qty
            })
        
        issue_status = 'COMPLETED' if all_complete else ('PARTIALLY_ISSUED' if total_issued > settings.tolerance else 'ISSUANCE_PENDING')
        
        entries_to_insert.append({
            'fg_key': fg_key,
            'activity_type': 'ISSUE_RM',
            'status': issue_status,
            'buyer_name': order_info['buyerName'],
            'buyer_order_no': order_info['buyerOrderNo'],
            'order_date': order_info['orderDate'],
            'created_date': order_info['createdDate'],
            'workflow_position': 4,
            'extra_data': {
                'items': issuance_items,
                'totalIssued': total_issued,
                'totalRequired': total_required,
                'allComplete': all_complete,
                'issuedAt': datetime.utcnow().isoformat()
            }
        })
        
        if all_complete:
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'LIFECYCLE',
                'status': 'CLOSED',
                'buyer_name': order_info['buyerName'],
                'buyer_order_no': order_info['buyerOrderNo'],
                'order_date': order_info['orderDate'],
                'created_date': order_info['createdDate'],
                'workflow_position': 5,
                'extra_data': {
                    'closedAt': datetime.utcnow().isoformat(),
                    'totalIssued': total_issued,
                    'totalRequired': total_required,
                    'reason': 'All requirements fulfilled'
                }
            })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        
        # ==============================================================
        # TOKEN MOVEMENT: Issue RM → FG_INSPECTION
        # ==============================================================
        buyer_order_id = None
        entries = crud.get_ledger_entries(db, fg_key)
        buyer_order_entry = next((e for e in entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        if buyer_order_entry:
            buyer_order_id = buyer_order_entry.buyer_order_id
        
        move_result = None
        if buyer_order_id and all_complete:
            token_state = crud.get_token_state(db, buyer_order_id)
            if token_state and token_state["current_stage"] == "ISSUE_RM":
                if crud.can_move_forward(db, buyer_order_id):
                    move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
                    logging.info(f"Issue RM saved: Token moved to FG_INSPECTION for {buyer_order_id}")
        
        response = {
            'success': True,
            'message': f'Issue RM saved successfully. Status: {issue_status}',
            'status': issue_status,
            'allComplete': all_complete
        }
        
        if move_result:
            response['new_stage'] = move_result["new_stage"]
            response['new_version'] = move_result["new_version"]
            response['message'] = f'Issue RM completed. Moved to FG Inspection.'
        
        return response
    except Exception as e:
        return {'success': False, 'message': str(e)}
@router.post("/save-bulk")
def save_issue_rm_bulk(data: Dict, db: Session = Depends(get_db)):
    """
    Bulk issue RM: accepts list of {requirement_key, issuing_qty} for a buyer order.
    Writes ISSUE_RM entries, updates snapshot with issueDelta (stock out),
    then moves token ISSUE_RM -> FG_INSPECTION.
    """
    from .. import models
    from decimal import Decimal
    import logging
    
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        items = data.get('items', [])
        
        if not buyer_order_id:
            return {'success': False, 'message': 'Buyer Order ID is required'}
        if not items:
            return {'success': False, 'message': 'No items to issue'}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {'success': False, 'message': 'No workflow token found'}
        if token_state['current_stage'] != 'ISSUE_RM':
            return {'success': False, 'message': f'Cannot issue from stage: {token_state["current_stage"]}'}
        
        ledger_version = token_state['current_version']
        
        snapshot = crud.get_inventory_snapshot(db)
        snapshot_by_key = {s.requirement_key: s for s in snapshot}
        
        all_entries = crud.get_ledger_entries(db)
        buyer_order_entry = next((e for e in all_entries 
                                  if e.buyer_order_id == buyer_order_id 
                                  and e.activity_type == 'BUYER_ORDER' 
                                  and e.status == 'COMPLETED'), None)
        buyer_name = buyer_order_entry.buyer_name if buyer_order_entry else ''
        buyer_order_no = buyer_order_entry.buyer_order_no if buyer_order_entry else ''
        order_date = buyer_order_entry.order_date if buyer_order_entry else None
        created_date = buyer_order_entry.created_date if buyer_order_entry else None
        
        entries_to_insert = []
        snapshot_updates = []
        total_issued = Decimal('0')
        
        for item in items:
            req_key = item.get('requirement_key', '')
            issue_qty = Decimal(str(item.get('issuing_qty', 0)))
            
            if not req_key or issue_qty <= 0:
                continue
            
            snap = snapshot_by_key.get(req_key)
            if not snap:
                return {'success': False, 'message': f'Snapshot not found for {req_key}'}
            
            available = Decimal(str(snap.current_stock or 0))
            if issue_qty > available + Decimal('0.001'):
                return {'success': False, 'message': f'Issue qty {issue_qty} exceeds available {available} for {snap.item_name}'}

            required = Decimal(str(snap.total_required_qty or 0))
            buffer_cap = required * Decimal(str(settings.issue_buffer_percent))
            if issue_qty > buffer_cap + Decimal('0.001'):
                return {'success': False, 'message': f'Issue qty {issue_qty} exceeds 5% buffer cap {buffer_cap} (required {required}) for {snap.item_name}'}
            
            # Supersede any prior non-CANCELLED MR rows for the same
            # (buyer_order_id, fg_key, requirementKey) before writing ISSUED.
            prior_mr = [e for e in all_entries
                        if e.activity_type == 'MATERIAL_REQUIREMENT'
                        and e.buyer_order_id == buyer_order_id
                        and e.fg_key == snap.fg_key
                        and e.status != 'CANCELLED'
                        and (e.extra_data or {}).get('requirementKey') == req_key]
            for old_mr in prior_mr:
                entries_to_insert.append({
                    'fg_key': old_mr.fg_key,
                    'buyer_order_id': buyer_order_id,
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'CANCELLED',
                    'buyer_name': old_mr.buyer_name,
                    'buyer_order_no': old_mr.buyer_order_no,
                    'order_date': old_mr.order_date,
                    'created_date': old_mr.created_date,
                    'qty': old_mr.qty,
                    'size': old_mr.size,
                    'color': old_mr.color,
                    'workflow_position': 1.5,
                    'version': old_mr.version or 1,
                    'extra_data': {
                        **(old_mr.extra_data or {}),
                        'cancelledAt': datetime.utcnow().isoformat(),
                        'cancelledReason': 'Superseded by new ISSUE_RM save',
                        'supersededBy': 'save_issue_rm_bulk'
                    }
                })
            # Write MATERIAL_REQUIREMENT ISSUED entry.
            # Carry forward the prior row's extra_data so supplier / poToken /
            # grnReceivedAt / consumption / rate / uom survive the transition.
            # A fresh dict here strips those fields and downstream reverts
            # (cancel_issue_rm, cancel_fg_inspection) then produce MR rows with
            # no supplier, breaking totalSuppliers in /rm-order/orders.
            _carry = {}
            for _old in prior_mr:
                _carry.update(_old.extra_data or {})
            entries_to_insert.append({
                'fg_key': snap.fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'ISSUED',
                'buyer_name': buyer_name,
                'buyer_order_no': buyer_order_no,
                'order_date': order_date,
                'created_date': created_date,
                'qty': float(issue_qty),
                'size': snap.garment_size or 'ALL',
                'color': snap.color or '',
                'workflow_position': 1.5,
                'version': ledger_version,
                'extra_data': {
                    **_carry,
                    'itemNo': snap.item_no or _carry.get('itemNo', ''),
                    'itemName': snap.item_name or _carry.get('itemName', ''),
                    'itemSize': _carry.get('itemSize', ''),
                    'requirementKey': req_key,
                    'supplier': _carry.get('supplier') or snap.supplier or '',
                    'issuedAt': datetime.utcnow().isoformat(),
                    'issuedQty': float(issue_qty)
                }
            })
            
            snapshot_updates.append({
                'requirementKey': req_key,
                'buyerOrderId': buyer_order_id,
                'fgKey': snap.fg_key,
                'itemNo': snap.item_no or '',
                'itemName': snap.item_name or '',
                'size': snap.garment_size or 'ALL',
                'color': snap.color or '',
                'supplier': snap.supplier or '',
                'requiredDelta': 0,
                'grnDelta': 0,
                'issueDelta': float(issue_qty)
            })
            
            total_issued += issue_qty
        
        if not entries_to_insert:
            return {'success': False, 'message': 'No valid items to issue'}
        
        # Supersede any prior non-CANCELLED ISSUE_RM summary for this order.
        # Q2 key is (buyer_order_id, fg_key) and summary rows use fg_key='',
        # so this collapses to one live summary per order.
        prior_summary = [e for e in all_entries
                         if e.activity_type == 'ISSUE_RM'
                         and e.buyer_order_id == buyer_order_id
                         and e.status != 'CANCELLED']
        for old_sum in prior_summary:
            entries_to_insert.append({
                'fg_key': old_sum.fg_key or '',
                'buyer_order_id': buyer_order_id,
                'activity_type': 'ISSUE_RM',
                'status': 'CANCELLED',
                'buyer_name': old_sum.buyer_name,
                'buyer_order_no': old_sum.buyer_order_no,
                'order_date': old_sum.order_date,
                'created_date': old_sum.created_date,
                'qty': old_sum.qty,
                'workflow_position': old_sum.workflow_position,
                'version': old_sum.version or 1,
                'extra_data': {
                    **(old_sum.extra_data or {}),
                    'cancelledAt': datetime.utcnow().isoformat(),
                    'cancelledReason': 'Superseded by new ISSUE_RM save',
                    'supersededBy': 'save_issue_rm_bulk'
                }
            })
        
        # Write an ISSUE_RM summary entry
        entries_to_insert.append({
            'fg_key': '',
            'buyer_order_id': buyer_order_id,
            'activity_type': 'ISSUE_RM',
            'status': 'COMPLETED',
            'buyer_name': buyer_name,
            'buyer_order_no': buyer_order_no,
            'order_date': order_date,
            'created_date': created_date,
            'qty': float(total_issued),
            'workflow_position': 7,
            'version': ledger_version,
            'extra_data': {
                'itemsIssued': sum(1 for e in entries_to_insert if e['activity_type'] == 'MATERIAL_REQUIREMENT' and e['status'] == 'ISSUED'),
                'totalIssued': float(total_issued),
                'issuedAt': datetime.utcnow().isoformat()
            }
        })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        
        # Move token ISSUE_RM -> FG_INSPECTION
        move_result = None
        if crud.can_move_forward(db, buyer_order_id):
            move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
            logging.info(f"Issue RM complete: token moved to FG_INSPECTION for {buyer_order_id}")
        
        response = {
            'success': True,
            'message': f'Issued {len(snapshot_updates)} item(s). Buyer order moved to FG Inspection.',
            'totalIssued': float(total_issued),
            'itemCount': len(snapshot_updates),
        }
        if move_result:
            response['newStage'] = move_result['new_stage']
            response['newVersion'] = move_result['new_version']
        
        return response
    except Exception as e:
        import logging
        logging.error(f"Issue RM bulk error: {str(e)}")
        return {'success': False, 'message': str(e)}

@router.post("/cancel")
def cancel_issue_rm(data: Dict, db: Session = Depends(get_db)):
    """
    Cancel Issue RM for a whole buyer order:
    - Reverse issueDelta on inventory snapshot for every ISSUED MATERIAL_REQUIREMENT line
    - Revert those MATERIAL_REQUIREMENT entries from ISSUED back to RECEIVED
    - Move token backward ISSUE_RM -> INTERNAL_FG_ORDER
    """
    try:
        buyer_order_id = crud.clean_key_exact(data.get('buyer_order_id', ''))
        if not buyer_order_id:
            return {"success": False, "message": "Buyer Order ID is required"}

        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found for this order"}
        if token_state["current_stage"] != "ISSUE_RM":
            return {"success": False, "message": f"Cannot cancel from stage: {token_state['current_stage']}. Order is not in Issue RM stage."}
        if not crud.can_move_backward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move backward from current stage"}

        all_entries = crud.get_ledger_entries(db)
        issued_entries = [e for e in all_entries
                          if e.buyer_order_id == buyer_order_id
                          and e.activity_type == 'MATERIAL_REQUIREMENT'
                          and e.status == 'ISSUED']

        move_result = crud.move_stage(db, buyer_order_id, "backward", "system")

        # The token is now back at INTERNAL_FG_ORDER, so the factory orders
        # that were issued on the way forward must be undone too. Otherwise
        # the Internal FG Order table still shows a live order for a stage
        # the buyer order has already left.
        from .. import models as _models
        _now_ifg = datetime.utcnow()
        _active_ifgs = db.query(_models.InternalFGOrder).filter(
            _models.InternalFGOrder.buyer_order_id == buyer_order_id,
            _models.InternalFGOrder.production_status != 'CANCELLED',
        ).all()
        for _io in _active_ifgs:
            _io.production_status = 'CANCELLED'
            _ed = dict(_io.extra_data or {})
            _ed['cancelledAt'] = _now_ifg.isoformat()
            _ed['cancelledReason'] = 'Issue RM cancelled - reversing to Internal FG Order'
            _io.extra_data = _ed
        if _active_ifgs:
            db.commit()

        now = datetime.utcnow()
        entries_to_insert = []
        snapshot_updates = []
        reverted_count = 0
        total_reversed = 0.0

        for e in issued_entries:
            req_key = (e.extra_data or {}).get('requirementKey', '')
            qty = float(e.qty or 0)
            if qty <= 0:
                continue

            meta = dict(e.extra_data or {})
            meta['issuedAt'] = None
            meta['revertedAt'] = now.isoformat()
            meta['revertedReason'] = 'Issue RM cancelled'
            meta['version'] = move_result['new_version']
            meta['previous_version'] = move_result['previous_version']
            meta['stage_movement'] = 'backward'
            meta['from_stage'] = move_result['previous_stage']
            meta['to_stage'] = move_result['new_stage']

            entries_to_insert.append({
                'fg_key': e.fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'RECEIVED',
                'buyer_name': e.buyer_name,
                'buyer_order_no': e.buyer_order_no,
                'order_date': e.order_date,
                'created_date': e.created_date,
                'qty': qty,
                'size': e.size,
                'color': e.color,
                'workflow_position': 1.5,
                'extra_data': meta
            })

            if req_key:
                snapshot_updates.append({
                    'requirementKey': req_key,
                    'fgKey': e.fg_key,
                    'itemNo': (e.extra_data or {}).get('itemNo', ''),
                    'itemName': (e.extra_data or {}).get('itemName', ''),
                    'size': e.size or 'ALL',
                    'color': e.color or '',
                    'supplier': '',
                    'requiredDelta': 0,
                    'grnDelta': 0,
                    'issueDelta': -qty
                })

            reverted_count += 1
            total_reversed += qty

        entries_to_insert.append({
            'fg_key': '',
            'buyer_order_id': buyer_order_id,
            'activity_type': 'ISSUE_RM',
            'status': 'CANCELLED',
            'buyer_name': (issued_entries[0].buyer_name if issued_entries else ''),
            'buyer_order_no': (issued_entries[0].buyer_order_no if issued_entries else ''),
            'order_date': (issued_entries[0].order_date if issued_entries else None),
            'created_date': now,
            'qty': -total_reversed,
            'workflow_position': 7,
            'extra_data': {
                'cancelledAt': now.isoformat(),
                'revertedRequirements': reverted_count,
                'totalReversed': total_reversed,
                'version': move_result["new_version"],
                'previous_version': move_result["previous_version"],
                'stage_movement': 'backward',
                'from_stage': move_result["previous_stage"],
                'to_stage': move_result["new_stage"]
            }
        })

        crud.add_ledger_entries_bulk(db, entries_to_insert)
        if snapshot_updates:
            crud.update_inventory_snapshot(db, snapshot_updates)

        return {
            'success': True,
            'message': f'Issue RM cancelled. {reverted_count} requirement line(s) reverted, {total_reversed:.2f} qty returned to stock. Moved back to Internal FG Order.',
            'new_stage': move_result["new_stage"],
            'new_version': move_result["new_version"],
            'revertedRequirements': reverted_count,
            'totalReversed': total_reversed
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}
