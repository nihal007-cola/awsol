from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
from ..auth import get_current_user
from ..models import User
import json

router = APIRouter(prefix="/bom", tags=["BOM"])

# ==============================================================
# GET BOM ORDERS - Shows orders with BOM saved
# ==============================================================

@router.get("/orders")
def get_bom_orders(db: Session = Depends(get_db)):
    """Get all orders in BOM stage only - uses live ledger (latest version per FG)"""
    tokens = db.query(crud.WorkflowToken).filter(
        crud.WorkflowToken.current_stage == "BOM",
        crud.WorkflowToken.status == "ACTIVE"
    ).all()
    
    buyer_order_ids = [t.buyer_order_id for t in tokens]
    
    if not buyer_order_ids:
        return []
    
    result = []
    for buyer_order_id in buyer_order_ids:
        # Live BOM rows only (latest version per fg_key, CANCELLED excluded)
        live_bom = crud.get_live_ledger_entries(
            db, activity_type='BOM', buyer_order_id=buyer_order_id,
            latest_version_only=True
        )
        
        if not live_bom:
            continue
        
        # All live BOM rows must be COMPLETED for this order to appear in BOM stage
        if not all((e.status or '').upper() == 'COMPLETED' for e in live_bom):
            continue
        
        # Latest BUYER_ORDER version to count FGs
        latest_version = crud.get_latest_buyer_order_version(db, buyer_order_id)
        live_buyer_orders = crud.get_live_ledger_entries(
            db, activity_type='BUYER_ORDER', buyer_order_id=buyer_order_id,
            latest_version_only=True,
            extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED' and (e.version or 1) == latest_version
        )
        fg_keys = list(set(e.fg_key for e in live_buyer_orders))
        total_fgs = len(fg_keys)
        
        first_fg = live_buyer_orders[0] if live_buyer_orders else None
        
        result.append({
            "buyerOrderId": buyer_order_id,
            "buyerName": first_fg.buyer_name if first_fg else "Unknown",
            "buyerOrderNo": first_fg.buyer_order_no if first_fg else "N/A",
            "orderDate": first_fg.order_date if first_fg else None,
            "totalFGs": total_fgs,
            "bomStatus": "COMPLETED",
            "status": "BOM_READY"
        })
    
    return result


# ==============================================================
# GET BOM DATA FOR A SPECIFIC FG
# ==============================================================
@router.get("/{fg_key}")
def get_bom_data(fg_key: str, db: Session = Depends(get_db)):
    clean_fg_key = crud.clean_key_exact(fg_key)
    
    # Live BOM rows for this fg_key (latest version, COMPLETED only)
    bom_entries = crud.get_live_ledger_entries(
        db, activity_type='BOM', fg_key=clean_fg_key,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    
    items = []
    bom_status = 'PENDING'
    if bom_entries:
        latest_bom = max(bom_entries, key=lambda e: e.id)
        if latest_bom.extra_data and latest_bom.extra_data.get('items'):
            items = latest_bom.extra_data['items']
        bom_status = latest_bom.status or 'PENDING'
    
    # Live BUYER_ORDER for the same fg_key
    buyer_order_entries = crud.get_live_ledger_entries(
        db, activity_type='BUYER_ORDER', fg_key=clean_fg_key,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    buyer_order = max(buyer_order_entries, key=lambda e: e.id) if buyer_order_entries else None
    
    grid_data = None
    if buyer_order and buyer_order.extra_data:
        grid_data = buyer_order.extra_data.get('gridRow')
    
    return {
        'fgKey': clean_fg_key,
        'bomStatus': bom_status,
        'items': items,
        'gridData': grid_data,
        'buyerName': buyer_order.buyer_name if buyer_order else '',
        'buyerOrderNo': buyer_order.buyer_order_no if buyer_order else '',
        'orderDate': buyer_order.order_date if buyer_order else '',
        'createdDate': buyer_order.created_date if buyer_order else ''
    }

# ==============================================================
# SAVE BOM - Legacy per-FG BOM save (kept for compatibility)
# ==============================================================
@router.post("/save")
def save_bom(data: schemas.BOMSaveRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        fg_key = crud.clean_key_exact(data.fg_key)
        if not fg_key:
            raise ValueError('FG Key missing')
        if not data.items:
            raise ValueError('No items to save')

        # FREEZE GATE: derive buyer_order_id from fg_key prefix and refuse if the
        # token has advanced past RM_ORDER. Same rule as save_bom_order.
        _buyer_order_id = fg_key.split('|')[0] if '|' in fg_key else fg_key
        from .. import models as _models
        _token = db.query(_models.WorkflowToken).filter(
            _models.WorkflowToken.buyer_order_id == _buyer_order_id
        ).first()
        if _token and _token.current_stage not in ('BOM', 'COSTING_APPROVAL', 'RM_ORDER'):
            return {
                "success": False,
                "message": (
                    f"BOM is locked at stage {_token.current_stage}. "
                    f"Reverse the workflow to RM Order or earlier to edit."
                ),
            }

        entries = crud.get_ledger_entries(db, fg_key)
        buyer_order = next((e for e in entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        if not buyer_order:
            raise ValueError(f'BUYER_ORDER not found or not COMPLETED for FG: {fg_key}')
        
        existing_bom = next((e for e in entries if e.activity_type == 'BOM' and e.status == 'COMPLETED'), None)
        if existing_bom:
            raise ValueError(f'BOM is already COMPLETED for FG: {fg_key}')
        
        for i, item in enumerate(data.items):
            if not item.item_no.strip():
                raise ValueError(f'Row {i+1}: Item No is required')
            if not item.item_name.strip():
                raise ValueError(f'Row {i+1}: Item Name is required')
            if not item.item_color.strip():
                raise ValueError(f'Row {i+1}: Item Color is required')
            if not item.item_size.strip():
                raise ValueError(f'Row {i+1}: Item Size is required')
            if item.consumption <= 0:
                raise ValueError(f'Row {i+1}: Consumption must be > 0')
            if not item.uom.strip():
                raise ValueError(f'Row {i+1}: UOM is required')
            if item.rate <= 0:
                raise ValueError(f'Row {i+1}: Rate must be > 0')
            if not item.supplier.strip():
                raise ValueError(f'Row {i+1}: Supplier is required')
            if item.leadtime <= 0:
                raise ValueError(f'Row {i+1}: Leadtime must be > 0')
        
        default_sizes = settings.get_default_sizes_list()
        grid_data = None
        if buyer_order.extra_data and buyer_order.extra_data.get('gridRow'):
            grid_row = buyer_order.extra_data['gridRow']
            grid_data = {}
            for i, size in enumerate(default_sizes):
                qty_index = 3 + i
                if qty_index < len(grid_row):
                    grid_data[str(size)] = grid_row[qty_index] or 0
        
        order_info = {
            'buyerName': buyer_order.buyer_name or '',
            'buyerOrderNo': buyer_order.buyer_order_no or '',
            'orderDate': buyer_order.order_date,
            'createdDate': buyer_order.created_date
        }
        
        entries_to_insert = []
        snapshot_updates = []
        
        existing_reqs = [e for e in entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                        and e.status not in ['CANCELLED', 'RECEIVED', 'ISSUED']]
        for req in existing_reqs:
            entries_to_insert.append({
                'fg_key': fg_key,
            'buyer_order_id': buyer_order_id,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'CANCELLED',
                'buyer_name': req.buyer_name,
                'buyer_order_no': req.buyer_order_no,
                'order_date': req.order_date,
                'created_date': req.created_date,
                'qty': req.qty,
                'size': req.size,
                'color': req.color,
                'workflow_position': 1.5,
                'extra_data': {**(req.extra_data or {}), 'cancelledAt': datetime.utcnow().isoformat(), 'cancelledReason': 'New BOM saved'}
            })
        
        entries_to_insert.append({
            'fg_key': fg_key,
            'buyer_order_id': buyer_order_id,
            'activity_type': 'BOM',
            'status': 'COMPLETED',
            'buyer_name': order_info['buyerName'],
            'buyer_order_no': order_info['buyerOrderNo'],
            'order_date': order_info['orderDate'],
            'created_date': order_info['createdDate'],
            'workflow_position': 1,
            'extra_data': {
                'items': [item.model_dump() for item in data.items],
                'itemCount': len(data.items),
                'savedAt': datetime.utcnow().isoformat()
            }
        })
        
        def calculate_requirements(item, grid_data):
            consumption = item.consumption
            is_sensitive = item.size_sensitive == 'Yes'
            item_size = item.item_size.strip()
            default_sizes = settings.get_default_sizes_list()
            
            size_map = {}
            for size in default_sizes:
                size_str = str(size)
                if grid_data:
                    size_map[size_str] = grid_data.get(size_str, 0)
                else:
                    size_map[size_str] = 0
            
            requirements = []
            if is_sensitive:
                for size in default_sizes:
                    size_str = str(size)
                    order_qty = size_map.get(size_str, 0)
                    if order_qty > 0:
                        required_qty = order_qty * consumption
                        requirements.append({
                            'size': size_str,
                            'itemSize': item_size,
                            'qty': required_qty,
                            'color': item.item_color,
                            'itemNo': item.item_no,
                            'itemName': item.item_name,
                            'uom': item.uom,
                            'isSizeSensitive': True,
                            'orderQty': order_qty,
                            'consumption': consumption
                        })
            else:
                total_order_qty = sum(size_map.values())
                if total_order_qty > 0:
                    required_qty = total_order_qty * consumption
                    requirements.append({
                        'size': 'ALL',
                        'itemSize': item_size,
                        'qty': required_qty,
                        'color': item.item_color,
                        'itemNo': item.item_no,
                        'itemName': item.item_name,
                        'uom': item.uom,
                        'isSizeSensitive': False,
                        'totalOrderQty': total_order_qty,
                        'consumption': consumption
                    })
            return requirements
        
        for item in data.items:
            requirements = calculate_requirements(item, grid_data)
            for req in requirements:
                if req['qty'] > 0:
                    requirement_key = crud.get_requirement_key(fg_key, req['size'], req['color'], req['itemSize'], req['itemNo'])
                    
                    entries_to_insert.append({
                        'fg_key': fg_key,
            'buyer_order_id': buyer_order_id,
                        'activity_type': 'MATERIAL_REQUIREMENT',
                        'status': 'PENDING',
                        'buyer_name': order_info['buyerName'],
                        'buyer_order_no': order_info['buyerOrderNo'],
                        'order_date': order_info['orderDate'],
                        'created_date': order_info['createdDate'],
                        'qty': round(req['qty'] * 100) / 100,
                        'size': req['size'],
                        'color': req['color'],
                        'workflow_position': 1.5,
                        'extra_data': {
                            'itemNo': req['itemNo'],
                            'itemName': req['itemName'],
                            'uom': req['uom'],
                            'consumption': req['consumption'],
                            'supplier': item.supplier,
                            'rate': item.rate,
                            'leadtime': item.leadtime,
                            'cgst': item.cgst or 0,
                            'igst': item.igst or 0,
                            'hsn': item.hsn or '',
                            'isSizeSensitive': req['isSizeSensitive'],
                            'itemSize': req['itemSize'],
                            'garmentSize': req['size'],
                            'orderQty': req.get('orderQty') or req.get('totalOrderQty') or 0,
                            'requirementKey': requirement_key
                        }
                    })
                    
                    snapshot_updates.append({
                        'requirementKey': requirement_key,
                        'buyerOrderId': buyer_order.buyer_order_id,
                        'fgKey': fg_key,
                        'itemNo': req['itemNo'],
                        'itemName': req['itemName'],
                        'size': req['size'],
                        'color': req['color'],
                        'supplier': item.supplier,
                        'requiredDelta': round(req['qty'] * 100) / 100,
                        'grnDelta': 0,
                        'issueDelta': 0
                    })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        
        return {"success": True, "message": f"BOM saved with {len(entries_to_insert)} entries"}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ==============================================================
# SAVE BOM ORDER - Save BOM for entire buyer order
# ==============================================================
@router.post("/save-order")
def save_bom_order(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        fg_bom_data = data.get('fg_bom_data', {})
        
        if not buyer_order_id:
            raise ValueError('Buyer Order ID is required')
        if not fg_bom_data:
            raise ValueError('No BOM data provided')

        # FREEZE GATE: BOM and MATERIAL_REQUIREMENT are editable only while the
        # token is at BUYER_ORDER, BOM, COSTING_APPROVAL, or RM_ORDER. Once the
        # token reaches GRN or later, they are frozen. Reversing the workflow
        # re-opens them.
        from .. import models as _models
        _token = db.query(_models.WorkflowToken).filter(
            _models.WorkflowToken.buyer_order_id == buyer_order_id
        ).first()
        if _token and _token.current_stage not in ('BOM', 'COSTING_APPROVAL', 'RM_ORDER'):
            return {
                "success": False,
                "message": (
                    f"BOM is locked at stage {_token.current_stage}. "
                    f"Reverse the workflow to RM Order or earlier to edit."
                ),
            }

        all_entries = crud.get_ledger_entries_for_order(db, buyer_order_id)
        order_entries = [e for e in all_entries if e.buyer_order_id == buyer_order_id and e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED']
        
        if not order_entries:
            raise ValueError(f'Buyer Order {buyer_order_id} not found or not COMPLETED')
        
        default_sizes = settings.get_default_sizes_list()
        success_count = 0
        error_messages = []
        
        from .. import models
        buyer_order_record = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        order_version = buyer_order_record.version if buyer_order_record else 1
        
        # Also fetch the token's current version — this is the canonical version
        # for all ledger rows written by this save (BOM + MATERIAL_REQUIREMENT).
        token = db.query(models.WorkflowToken).filter(
            models.WorkflowToken.buyer_order_id == buyer_order_id
        ).first()
        ledger_version = token.current_version if token else order_version
        
        for fg_key, items in fg_bom_data.items():
            if not items:
                continue
            
            fg_entry = next((e for e in order_entries if crud.clean_key_exact(e.fg_key) == crud.clean_key_exact(fg_key)), None)
            if not fg_entry:
                error_messages.append(f'FG {fg_key} not found in order')
                continue
            
            # Cancel ALL non-CANCELLED BOM siblings for this (buyer_order_id, fg_key),
            # regardless of status (PENDING from process_to_bom, COMPLETED from prior save).
            # Prevents the 2-PENDING + 2-COMPLETED duplicate seen on FG-260911-154945.
            bom_siblings = [e for e in all_entries
                            if e.activity_type == 'BOM'
                            and e.fg_key == fg_key
                            and e.buyer_order_id == buyer_order_id
                            and e.status != 'CANCELLED']
            
            entries_to_insert = []
            snapshot_updates = []
            now = datetime.utcnow()
            
            # NOTE: The previous live BOM row(s) for this (buyer_order_id, fg_key) are
            # flipped to CANCELLED in place by crud._supersede_live() when the new
            # COMPLETED BOM row is written below. Do NOT write an explicit CANCELLED
            # copy here — it would duplicate the in-place flip.
            
            # Cancel non-terminal MATERIAL_REQUIREMENT siblings (leave RECEIVED/ISSUED alone).
            # This MUST run regardless of whether BOM siblings exist: a prior BOM save may
            # have written MR rows whose requirement_key no longer matches the new one
            # (e.g. item_size spelling change), leaving orphan PENDING rows that would
            # otherwise duplicate every downstream RM Order view.
            # Use get_live_ledger_entries so we cancel only rows the live view
            # still considers live. all_entries is the raw ledger: it includes
            # rows that were superseded but not flipped CANCELLED in place, and
            # cancelling those writes reversal snapshot rows for keys that never
            # contributed a positive requiredDelta — producing negative
            # total_required_qty rows and compounding forever.
            _live_mr = crud.get_live_ledger_entries(
                db, activity_type='MATERIAL_REQUIREMENT',
                buyer_order_id=buyer_order_id
            )
            req_entries = [e for e in _live_mr
                           if e.fg_key == fg_key
                           and e.status not in ['CANCELLED', 'RECEIVED', 'ISSUED']]
            for req in req_entries:
                entries_to_insert.append({
                    'buyer_order_id': buyer_order_id,
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
                    'version': req.version or 1,
                    'extra_data': {
                        **(req.extra_data or {}),
                        'cancelledAt': now.isoformat(),
                        'cancelledReason': 'New BOM version saved',
                        'supersededBy': 'save_bom_order'
                    }
                })
                # Reverse the cancelled MR's contribution to the snapshot.
                # Without this, every BOM re-save compounds total_required_qty:
                # the ledger row is cancelled but the snapshot keeps the old
                # +qty forever. Every other cancel path in the codebase pushes
                # a matching negative delta; save_bom_order was the outlier.
                _rk = (req.extra_data or {}).get('requirementKey') or ''
                if _rk:
                    snapshot_updates.append({
                        'requirementKey': _rk,
                        'buyerOrderId': buyer_order_id,
                        'fgKey': fg_key,
                        'itemNo': (req.extra_data or {}).get('itemNo', ''),
                        'itemName': (req.extra_data or {}).get('itemName', ''),
                        'size': req.size or 'ALL',
                        'color': req.color or '',
                        'supplier': (req.extra_data or {}).get('supplier', ''),
                        'requiredDelta': -float(req.qty or 0),
                        'grnDelta': 0,
                        'issueDelta': 0
                    })
            
            for i, item in enumerate(items):
                if not item.get('item_no', '').strip():
                    raise ValueError(f'FG {fg_key} Row {i+1}: Item No is required')
                if not item.get('item_size', '').strip():
                    raise ValueError(f'FG {fg_key} Row {i+1}: Item Size is required')
                if item.get('consumption', 0) <= 0:
                    raise ValueError(f'FG {fg_key} Row {i+1}: Consumption must be > 0')
                if item.get('rate', 0) <= 0:
                    raise ValueError(f'FG {fg_key} Row {i+1}: Rate must be > 0')
                if not item.get('supplier', '').strip():
                    raise ValueError(f'FG {fg_key} Row {i+1}: Supplier is required')
                if item.get('leadtime', 0) <= 0:
                    raise ValueError(f'FG {fg_key} Row {i+1}: Leadtime must be > 0')
            
            order_info = {
                'buyerName': fg_entry.buyer_name or '',
                'buyerOrderNo': fg_entry.buyer_order_no or '',
                'orderDate': fg_entry.order_date,
                'createdDate': fg_entry.created_date
            }
            
            grid_data = None
            if fg_entry.extra_data and fg_entry.extra_data.get('gridRow'):
                grid_row = fg_entry.extra_data['gridRow']
                grid_data = {}
                for i, size in enumerate(default_sizes):
                    qty_index = 3 + i
                    if qty_index < len(grid_row):
                        grid_data[str(size)] = grid_row[qty_index] or 0
            
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': fg_key,
                'activity_type': 'BOM',
                'status': 'COMPLETED',
                'buyer_name': order_info['buyerName'],
                'buyer_order_no': order_info['buyerOrderNo'],
                'order_date': order_info['orderDate'],
                'created_date': order_info['createdDate'],
                'workflow_position': 1,
                'version': ledger_version,
                'extra_data': {
                    'items': items,
                    'orderVersion': order_version,
                    'itemCount': len(items),
                    'savedAt': now.isoformat(),
                    'buyerOrderId': buyer_order_id
                }
            })
            
            for item in items:
                consumption = item['consumption']
                is_sensitive = item.get('size_sensitive', 'No') == 'Yes'
                item_size = item['item_size'].strip()
                
                requirements = []
                if is_sensitive:
                    for size in default_sizes:
                        size_str = str(size)
                        order_qty = grid_data.get(size_str, 0) if grid_data else 0
                        if order_qty > 0:
                            required_qty = order_qty * consumption
                            requirements.append({
                                'size': size_str,
                                'itemSize': item_size,
                                'qty': required_qty,
                                'color': item.get('item_color', ''),
                                'itemNo': item['item_no'],
                                'itemName': item['item_name'],
                                'uom': item.get('uom', 'PCS'),
                                'isSizeSensitive': True,
                                'orderQty': order_qty,
                                'consumption': consumption
                            })
                else:
                    total_order_qty = sum(grid_data.values()) if grid_data else 0
                    if total_order_qty > 0:
                        required_qty = total_order_qty * consumption
                        requirements.append({
                            'size': 'ALL',
                            'itemSize': item_size,
                            'qty': required_qty,
                            'color': item.get('item_color', ''),
                            'itemNo': item['item_no'],
                            'itemName': item['item_name'],
                            'uom': item.get('uom', 'PCS'),
                            'isSizeSensitive': False,
                            'totalOrderQty': total_order_qty,
                            'consumption': consumption
                        })
                
                for req in requirements:
                    if req['qty'] > 0:
                        requirement_key = crud.get_requirement_key(fg_key, req['size'], req['color'], req['itemSize'], req['itemNo'])
                        
                        entries_to_insert.append({
                            'fg_key': fg_key,
                            'buyer_order_id': buyer_order_id,
                            'activity_type': 'MATERIAL_REQUIREMENT',
                            'status': 'PENDING',
                            'buyer_name': order_info['buyerName'],
                            'buyer_order_no': order_info['buyerOrderNo'],
                            'order_date': order_info['orderDate'],
                            'created_date': order_info['createdDate'],
                            'qty': round(req['qty'] * 100) / 100,
                            'size': req['size'],
                            'color': req['color'],
                            'workflow_position': 1.5,
                            'version': ledger_version,
                            'extra_data': {
                                'itemNo': req['itemNo'],
                                'itemName': req['itemName'],
                                'uom': req['uom'],
                                'consumption': req['consumption'],
                                'supplier': item.get('supplier', ''),
                                'rate': item.get('rate', 0),
                                'leadtime': item.get('leadtime', 0),
                                'cgst': item.get('cgst', 0),
                                'igst': item.get('igst', 0),
                                'hsn': item.get('hsn', ''),
                                'isSizeSensitive': req['isSizeSensitive'],
                                'itemSize': req['itemSize'],
                                'garmentSize': req['size'],
                                'orderQty': req.get('orderQty') or req.get('totalOrderQty') or 0,
                                'requirementKey': requirement_key
                            }
                        })
                        
                        snapshot_updates.append({
                            'requirementKey': requirement_key,
                            'buyerOrderId': buyer_order_id,
                            'fgKey': fg_key,
                            'itemNo': req['itemNo'],
                            'itemName': req['itemName'],
                            'size': req['size'],
                            'color': req['color'],
                            'supplier': item.get('supplier', ''),
                            'requiredDelta': round(req['qty'] * 100) / 100,
                            'grnDelta': 0,
                            'issueDelta': 0
                        })
            
            crud.add_ledger_entries_bulk(db, entries_to_insert)
            crud.update_inventory_snapshot(db, snapshot_updates)
            success_count += 1
        
        if success_count == 0 and error_messages:
            return {"success": False, "message": "; ".join(error_messages)}
        
        return {
            "success": True,
            "message": f"BOM saved for {success_count} FGs",
            "successCount": success_count,
            "errors": error_messages
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

# ==============================================================
# CANCEL BOM - Move order back to Buyer Orders
# ==============================================================
@router.post("/cancel")
def cancel_bom(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        if not buyer_order_id:
            return {"success": False, "message": "Buyer Order ID is required"}
        
        # Check token state using new workflow system
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found for this order"}
        
        # Validate current stage - can only cancel from BOM stage
        if token_state["current_stage"] != "BOM":
            return {"success": False, "message": f"Cannot cancel from stage: {token_state['current_stage']}. Order is not in BOM stage."}
        
        # Check if can move backward
        if not crud.can_move_backward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move backward from current stage"}
        
        # Move token backward to BUYER_ORDER
        move_result = crud.move_stage(db, buyer_order_id, "backward", "system")
        
        all_entries = crud.get_ledger_entries_for_order(db, buyer_order_id)
        
        # Get the original buyer order details
        buyer_order_entry = next((e for e in all_entries if e.buyer_order_id == buyer_order_id and e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        if not buyer_order_entry:
            return {"success": False, "message": "Original buyer order not found"}
        
        # Cancel all COMPLETED BOM entries (mark as CANCELLED)
        bom_entries = [e for e in all_entries if e.buyer_order_id == buyer_order_id and e.activity_type == 'BOM' and e.status == 'COMPLETED']
        entries_to_insert = []
        now = datetime.utcnow()
        
        for entry in bom_entries:
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': entry.fg_key,
                'activity_type': 'BOM',
                'status': 'CANCELLED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': 0,
                'extra_data': {
                    **(entry.extra_data or {}),
                    'cancelledAt': now.isoformat(),
                    'cancelledReason': 'BOM cancelled by user - reverting to Buyer Order',
                    'version': move_result["new_version"],
                    'previous_version': move_result["previous_version"],
                    'stage_movement': 'backward',
                    'from_stage': move_result["previous_stage"],
                    'to_stage': move_result["new_stage"]
                }
            })
        
        # Cancel all MATERIAL_REQUIREMENT entries
        req_entries = [e for e in all_entries if e.buyer_order_id == buyer_order_id and e.activity_type == 'MATERIAL_REQUIREMENT' and e.status not in ['CANCELLED', 'RECEIVED', 'ISSUED']]
        for entry in req_entries:
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': entry.fg_key,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'CANCELLED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': 0,
                'extra_data': {
                    **(entry.extra_data or {}),
                    'cancelledAt': now.isoformat(),
                    'cancelledReason': 'BOM cancelled by user - reverting to Buyer Order',
                    'version': move_result["new_version"],
                    'stage_movement': 'backward'
                }
            })
        
        # Restore the buyer order to COMPLETED status at stage 0
        entries_to_insert.append({
            'buyer_order_id': buyer_order_id,
            'fg_key': buyer_order_entry.fg_key,
            'activity_type': 'BUYER_ORDER',
            'status': 'COMPLETED',
            'buyer_name': buyer_order_entry.buyer_name,
            'buyer_order_no': buyer_order_entry.buyer_order_no,
            'order_date': buyer_order_entry.order_date,
            'created_date': buyer_order_entry.created_date,
            'qty': buyer_order_entry.qty,
            'size': buyer_order_entry.size,
            'color': buyer_order_entry.color,
            'workflow_position': 0,
            'extra_data': {
                **(buyer_order_entry.extra_data or {}),
                'restoredAt': now.isoformat(),
                'restoredFrom': 'BOM_CANCELLATION',
                'restoredReason': 'BOM cancelled - order returned to Buyer Orders',
                'version': move_result["new_version"],
                'previous_version': move_result["previous_version"],
                'stage_movement': 'backward',
                'from_stage': move_result["previous_stage"],
                'to_stage': move_result["new_stage"]
            }
        })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        return {
            "success": True, 
            "message": f"BOM cancelled for order {buyer_order_id}. Order moved back to Buyer Orders.",
            "new_stage": move_result["new_stage"],
            "new_version": move_result["new_version"]
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

# ==============================================================
# GET BOM DATA FOR AN ORDER (Edit BOM)
# ==============================================================
@router.get("/order/{buyer_order_id}")
def get_bom_order_data(buyer_order_id: str, db: Session = Depends(get_db)):
    """Get BOM data for all FGs in a buyer order - only latest version"""
    from .. import models
    
    # Live BOM rows for this order (latest version per fg_key, COMPLETED only)
    bom_entries = crud.get_live_ledger_entries(
        db, activity_type='BOM', buyer_order_id=buyer_order_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    
    if not bom_entries:
        return {"success": False, "message": "No BOM found for this order"}
    
    latest_version = bom_entries[0].version or 1
    
    # Deduplicate by fg_key (defensive; live query already returns one per fg)
    fg_map = {}
    for entry in bom_entries:
        fg_key = entry.fg_key
        if fg_key not in fg_map or entry.id > fg_map[fg_key].id:
            fg_map[fg_key] = entry
    
    result = []
    for fg_key, entry in fg_map.items():
        bom_data = entry.extra_data or {}
        result.append({
            'fgKey': fg_key,
            'bomItems': bom_data.get('items', []),
            'itemCount': bom_data.get('itemCount', 0),
            'bomStatus': entry.status,
            'createdAt': entry.created_date,
            'version': entry.version
        })
    
    # Live BUYER_ORDER rows for this order (latest version only)
    order_entries = crud.get_live_ledger_entries(
        db, activity_type='BUYER_ORDER', buyer_order_id=buyer_order_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    
    grid_data = []
    for entry in order_entries:
        if entry.extra_data and entry.extra_data.get('gridRow'):
            grid_data.append(entry.extra_data['gridRow'])
    
    return {
        "success": True,
        "buyerOrderId": buyer_order_id,
        "fgs": result,
        "gridData": grid_data,
        "totalFGs": len(result),
        "version": latest_version
    }

# ==============================================================
# SUBMIT BOM FOR APPROVAL - Move from BOM to COSTING_APPROVAL
# ==============================================================
@router.post("/submit-approval")
def submit_bom_for_approval(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        if not buyer_order_id:
            return {"success": False, "message": "Buyer Order ID is required"}
        
        # Check token state
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found for this order"}
        
        # Validate current stage - can only submit from BOM stage
        if token_state["current_stage"] != "BOM":
            return {"success": False, "message": f"Cannot submit from stage: {token_state['current_stage']}. Order is not in BOM stage."}
        
        # Check if can move forward
        if not crud.can_move_forward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move forward from current stage"}
        
        # Check if BOM is COMPLETED
        all_entries = crud.get_ledger_entries_for_order(db, buyer_order_id)
        bom_entries = [e for e in all_entries if e.buyer_order_id == buyer_order_id and e.activity_type == 'BOM' and e.status == 'COMPLETED']
        if not bom_entries:
            return {"success": False, "message": "BOM must be completed before submitting for approval"}
        
        # Move token forward to COSTING_APPROVAL
        move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
        
        # Create approval transition entry
        entries_to_insert = []
        now = datetime.utcnow()
        
        for entry in bom_entries:
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': entry.fg_key,
                'activity_type': 'COSTING_APPROVAL',
                'status': 'PENDING',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': 2,
                'extra_data': {
                    'bomData': entry.extra_data.get('items', []) if entry.extra_data else [],
                    'submittedAt': now.isoformat(),
                    'version': move_result["new_version"],
                    'previous_version': move_result["previous_version"],
                    'stage_movement': 'forward',
                    'from_stage': move_result["previous_stage"],
                    'to_stage': move_result["new_stage"]
                }
            })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {
            "success": True,
            "message": f"BOM submitted for approval. Order moved to Costing Approval.",
            "new_stage": move_result["new_stage"],
            "new_version": move_result["new_version"]
        }
    except Exception as e:
        return {"success": False, "message": str(e)}
