from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
from ..models import InspectionRecord, ActivityLedger, StageTransition
import uuid

router = APIRouter(prefix="/rm-inspection", tags=["RM Inspection"])

@router.get("/orders")
def get_rm_inspections(db: Session = Depends(get_db)):
    """
    List every live PO of every buyer order currently in RM_ORDER stage.
    Grouped by buyer order. A buyer order stays in the list until every one
    of its POs is PASSED. PASSED POs remain visible while any sibling PO is
    still pending.
    """
    from .. import models

    tokens_in_rm_order = db.query(models.WorkflowToken).filter(
        models.WorkflowToken.current_stage == "RM_ORDER",
        models.WorkflowToken.status == "ACTIVE"
    ).all()
    buyer_order_ids = [t.buyer_order_id for t in tokens_in_rm_order]

    if not buyer_order_ids:
        return []

    # Latest inspection row per PO (we need status + remarks)
    all_insp = db.query(InspectionRecord).filter(
        InspectionRecord.inspection_type == 'RAW_MATERIAL'
    ).order_by(InspectionRecord.id.desc()).all()
    latest_insp = {}
    for insp in all_insp:
        if insp.reference and insp.reference not in latest_insp:
            latest_insp[insp.reference] = insp

    result = []

    for bo_id in buyer_order_ids:
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == bo_id
        ).first()

        # Live MATERIAL_REQUIREMENT rows -> required suppliers for this order
        live_reqs = crud.get_live_ledger_entries(
            db, activity_type='MATERIAL_REQUIREMENT', buyer_order_id=bo_id
        )
        required_suppliers = set()
        for req in live_reqs:
            sup = (req.extra_data or {}).get('supplier')
            if sup:
                required_suppliers.add(sup)

        # Live RM_ORDER rows -> POs made
        live_po_entries = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=bo_id,
            extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
        )

        po_map = {}
        for entry in live_po_entries:
            ed = entry.extra_data or {}
            po_token = ed.get('poToken', '')
            if not po_token:
                continue
            if po_token not in po_map:
                po_map[po_token] = {
                    'poToken': po_token,
                    'supplier': ed.get('supplier', 'Unknown'),
                    'items': [],
                    'buyerOrderId': bo_id
                }
            po_map[po_token]['items'].append({
                'fgKey': entry.fg_key,
                'itemNo': ed.get('itemNo', ''),
                'itemName': ed.get('itemName', ''),
                'garmentSize': entry.size or 'ALL',
                'color': entry.color or '',
                'orderedQty': entry.qty or 0,
                'uom': ed.get('uom', 'PCS'),
                'rate': ed.get('rate', 0)
            })

        # Attach latest inspection status + observation per PO
        pos = []
        any_pending = False
        for po_token, po_data in po_map.items():
            insp = latest_insp.get(po_token)
            status = insp.status if insp else 'PENDING'
            observation = (insp.remarks or '') if insp else ''
            if status != 'PASSED':
                any_pending = True
            pos.append({
                'poToken': po_token,
                'supplier': po_data['supplier'],
                'items': po_data['items'],
                'status': status,
                'observation': observation,
                'itemCount': len(po_data['items'])
            })

        # Every supplier must have a PO made before pass/fail is allowed
        suppliers_covered = bool(required_suppliers) and all(
            sup in {p['supplier'] for p in pos} for sup in required_suppliers
        )
        all_pos_made = suppliers_covered

        # A buyer order leaves the list only when it has at least one PO AND
        # every PO is PASSED. If it has PASSED POs but siblings are pending,
        # it stays visible.
        if pos and not any_pending:
            continue

        # If NO PO has been made yet, the buyer order has nothing to inspect —
        # skip it here (it still shows on the RM Order list).
        if not pos:
            continue

        result.append({
            'buyerOrderId': bo_id,
            'buyerName': buyer_order.buyer_name if buyer_order else 'Unknown',
            'buyerOrderNo': buyer_order.buyer_order_no if buyer_order else 'N/A',
            'orderDate': buyer_order.order_date if buyer_order else None,
            'requiredSuppliers': sorted(required_suppliers),
            'totalRequiredSuppliers': len(required_suppliers),
            'totalPOsMade': len(pos),
            'allPOsMade': all_pos_made,
            'pos': pos
        })

    return result

@router.post("/save")
def save_rm_inspection(data: Dict, db: Session = Depends(get_db)):
    try:
        po_token = data.get('po_token', '')
        item = data.get('item', '')
        quantity = data.get('quantity', 0)
        rejected = data.get('rejected', 0)
        remarks = data.get('remarks', '')
        inspector = data.get('inspector', 'admin')
        if not po_token or not item or quantity <= 0:
            return {"success": False, "message": "Missing required fields"}
        passed = quantity - rejected
        status = 'PASSED' if rejected == 0 else ('REJECTED' if rejected == quantity else 'PARTIAL')
        inspection = InspectionRecord(
            inspection_id=f"RM-INSP-{uuid.uuid4().hex[:6].upper()}",
            buyer_order_id=po_token,
            reference=po_token,
            inspection_type='RAW_MATERIAL',
            inspector=inspector,
            item=item,
            quantity=quantity,
            quantity_passed=passed,
            quantity_rejected=rejected,
            status=status,
            remarks=remarks
        )
        db.add(inspection)
        db.commit()
        return {"success": True, "message": f"Inspection saved: {status}"}
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

@router.post("/pass")
def pass_rm_inspection(data: Dict, db: Session = Depends(get_db)):
    try:
        po_token = data.get('po_token', '')
        if not po_token:
            return {"success": False, "message": "PO Token is required"}
        
        # Look up the buyer_order_id for this PO from the ledger.
        # We must NOT store po_token in the buyer_order_id column — it is a
        # real FK to the buyer order and is used by the scoped passed-PO query.
        all_entries_lookup = crud.get_ledger_entries(db)
        rm_order_lookup = next((e for e in all_entries_lookup
                                if e.activity_type == 'RM_ORDER'
                                and e.extra_data
                                and e.extra_data.get('poToken') == po_token), None)
        po_buyer_order_id = rm_order_lookup.buyer_order_id if rm_order_lookup else ''

        if not po_buyer_order_id:
            return {"success": False, "message": "Buyer order not found for this PO"}

        # Gate: every required supplier of the buyer order must have a PO made.
        live_reqs = crud.get_live_ledger_entries(
            db, activity_type='MATERIAL_REQUIREMENT', buyer_order_id=po_buyer_order_id
        )
        required_suppliers = set()
        for req in live_reqs:
            sup = (req.extra_data or {}).get('supplier')
            if sup:
                required_suppliers.add(sup)
        live_pos_for_order = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=po_buyer_order_id,
            extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
        )
        made_suppliers = set()
        for e in live_pos_for_order:
            sup = (e.extra_data or {}).get('supplier')
            if sup:
                made_suppliers.add(sup)
        missing_suppliers = required_suppliers - made_suppliers
        if missing_suppliers:
            return {
                "success": False,
                "message": "Complete all POs before passing inspection. "
                           f"Missing PO for: {', '.join(sorted(missing_suppliers))}",
                "missingSuppliers": sorted(missing_suppliers)
            }

        inspection = db.query(InspectionRecord).filter(
            InspectionRecord.reference == po_token,
            InspectionRecord.inspection_type == 'RAW_MATERIAL'
        ).first()
        
        if not inspection:
            inspection = InspectionRecord(
                inspection_id=f"RM-INSP-{uuid.uuid4().hex[:6].upper()}",
                buyer_order_id=po_buyer_order_id,
                reference=po_token,
                inspection_type='RAW_MATERIAL',
                inspector='system',
                item='All Items',
                quantity=0,
                quantity_passed=0,
                quantity_rejected=0,
                status='PASSED',
                remarks='Auto-passed'
            )
            db.add(inspection)
        else:
            inspection.status = 'PASSED'
            if po_buyer_order_id and not inspection.buyer_order_id:
                inspection.buyer_order_id = po_buyer_order_id
        
        db.commit()
        
        # ==============================================================
        # CRITICAL LOGIC: Check if ALL POs for this buyer order are PASSED
        # ==============================================================
        
        # Find the buyer_order_id for this PO
        all_entries = crud.get_ledger_entries(db)
        rm_order_entry = next((e for e in all_entries 
                              if e.activity_type == 'RM_ORDER' 
                              and e.extra_data 
                              and e.extra_data.get('poToken') == po_token), None)
        
        if rm_order_entry and rm_order_entry.buyer_order_id:
            buyer_order_id = rm_order_entry.buyer_order_id
            
            # Every SUPPLIER on the live MATERIAL_REQUIREMENT must have at least
            # one PASSED PO. Comparing only live PO tokens was insufficient:
            # a supplier with no PO yet would not appear in that set, so the
            # all-passed check wrongly returned True.
            live_reqs = crud.get_live_ledger_entries(
                db, activity_type='MATERIAL_REQUIREMENT', buyer_order_id=buyer_order_id
            )
            required_suppliers = set()
            for req in live_reqs:
                sup = (req.extra_data or {}).get('supplier')
                if sup:
                    required_suppliers.add(sup)

            # Live POs, grouped by supplier
            live_po_entries = crud.get_live_ledger_entries(
                db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
                extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
            )
            live_po_tokens = set()
            po_tokens_by_supplier = {}
            for e in live_po_entries:
                ed = e.extra_data or {}
                pt = ed.get('poToken')
                sup = ed.get('supplier')
                if pt:
                    live_po_tokens.add(pt)
                if sup and pt:
                    po_tokens_by_supplier.setdefault(sup, set()).add(pt)

            # Passed POs scoped to this buyer order
            passed_po_tokens = set()
            all_inspections = db.query(InspectionRecord).filter(
                InspectionRecord.inspection_type == 'RAW_MATERIAL',
                InspectionRecord.status == 'PASSED',
                InspectionRecord.buyer_order_id == buyer_order_id
            ).all()
            for insp in all_inspections:
                if insp.reference:
                    passed_po_tokens.add(insp.reference)

            # All passed iff:
            #   1. Every required supplier has at least one PO made, and
            #   2. Every live PO token has been PASSED.
            every_supplier_covered = bool(required_suppliers) and all(
                sup in po_tokens_by_supplier and po_tokens_by_supplier[sup]
                for sup in required_suppliers
            )
            every_po_passed = bool(live_po_tokens) and live_po_tokens.issubset(passed_po_tokens)
            all_passed = every_supplier_covered and every_po_passed

            if all_passed:
                token_state = crud.get_token_state(db, buyer_order_id)
                # The buyer order is parked in RM_ORDER during the whole
                # ordering + inspection window. Only here does it move forward.
                if token_state and token_state["current_stage"] == "RM_ORDER":
                    if crud.can_move_forward(db, buyer_order_id):
                        move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
                        return {
                            'success': True,
                            'message': f'All POs passed. Buyer order moved to GRN.',
                            'new_stage': move_result["new_stage"],
                            'new_version': move_result["new_version"],
                            'all_passed': True
                        }
        
        return {'success': True, 'message': f'RM Inspection passed for PO: {po_token}'}
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}

@router.post("/fail")
def fail_rm_inspection(data: Dict, db: Session = Depends(get_db)):
    try:
        po_token = data.get('po_token', '')
        if not po_token:
            return {"success": False, "message": "PO Token is required"}
        
        # Resolve the true buyer_order_id for this PO (see /pass for rationale).
        all_entries_lookup = crud.get_ledger_entries(db)
        rm_order_lookup = next((e for e in all_entries_lookup
                                if e.activity_type == 'RM_ORDER'
                                and e.extra_data
                                and e.extra_data.get('poToken') == po_token), None)
        po_buyer_order_id = rm_order_lookup.buyer_order_id if rm_order_lookup else ''

        if not po_buyer_order_id:
            return {"success": False, "message": "Buyer order not found for this PO"}

        # Gate: every required supplier of the buyer order must have a PO made.
        live_reqs = crud.get_live_ledger_entries(
            db, activity_type='MATERIAL_REQUIREMENT', buyer_order_id=po_buyer_order_id
        )
        required_suppliers = set()
        for req in live_reqs:
            sup = (req.extra_data or {}).get('supplier')
            if sup:
                required_suppliers.add(sup)
        live_pos_for_order = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=po_buyer_order_id,
            extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
        )
        made_suppliers = set()
        for e in live_pos_for_order:
            sup = (e.extra_data or {}).get('supplier')
            if sup:
                made_suppliers.add(sup)
        missing_suppliers = required_suppliers - made_suppliers
        if missing_suppliers:
            return {
                "success": False,
                "message": "Complete all POs before failing inspection. "
                           f"Missing PO for: {', '.join(sorted(missing_suppliers))}",
                "missingSuppliers": sorted(missing_suppliers)
            }

        inspection = db.query(InspectionRecord).filter(
            InspectionRecord.reference == po_token,
            InspectionRecord.inspection_type == 'RAW_MATERIAL'
        ).first()
        
        if not inspection:
            inspection = InspectionRecord(
                inspection_id=f"RM-INSP-{uuid.uuid4().hex[:6].upper()}",
                buyer_order_id=po_buyer_order_id,
                reference=po_token,
                inspection_type='RAW_MATERIAL',
                inspector='system',
                item='All Items',
                quantity=0,
                quantity_passed=0,
                quantity_rejected=0,
                status='REJECTED',
                remarks='Auto-rejected'
            )
            db.add(inspection)
        else:
            inspection.status = 'REJECTED'
            if po_buyer_order_id and not inspection.buyer_order_id:
                inspection.buyer_order_id = po_buyer_order_id
        
        db.commit()
        return {'success': True, 'message': f'RM Inspection failed for PO: {po_token}'}
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}

@router.post("/set-observation")
def set_rm_inspection_observation(data: Dict, db: Session = Depends(get_db)):
    """
    Set / update the free-text observation (remarks) for a PO's latest RM
    Inspection record. Does NOT change status. If no inspection row exists
    yet, creates a PENDING stub so the note has somewhere to live.
    """
    try:
        po_token = data.get('po_token', '')
        observation = data.get('observation', '')
        if not po_token:
            return {"success": False, "message": "PO Token is required"}

        # Resolve buyer_order_id for this PO
        all_entries_lookup = crud.get_ledger_entries(db)
        rm_order_lookup = next((e for e in all_entries_lookup
                                if e.activity_type == 'RM_ORDER'
                                and e.extra_data
                                and e.extra_data.get('poToken') == po_token), None)
        po_buyer_order_id = rm_order_lookup.buyer_order_id if rm_order_lookup else ''

        inspection = db.query(InspectionRecord).filter(
            InspectionRecord.reference == po_token,
            InspectionRecord.inspection_type == 'RAW_MATERIAL'
        ).order_by(InspectionRecord.id.desc()).first()

        if not inspection:
            inspection = InspectionRecord(
                inspection_id=f"RM-INSP-{uuid.uuid4().hex[:6].upper()}",
                buyer_order_id=po_buyer_order_id,
                reference=po_token,
                inspection_type='RAW_MATERIAL',
                inspector='system',
                item='All Items',
                quantity=0,
                quantity_passed=0,
                quantity_rejected=0,
                status='PENDING',
                remarks=observation
            )
            db.add(inspection)
        else:
            inspection.remarks = observation
            if po_buyer_order_id and not inspection.buyer_order_id:
                inspection.buyer_order_id = po_buyer_order_id

        db.commit()
        return {"success": True, "message": "Observation saved"}
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}


@router.post("/cancel")
def cancel_rm_inspection(data: Dict, db: Session = Depends(get_db)):
    """
    DEPRECATED.

    RM Inspection is no longer a token stage. The buyer order sits in RM_ORDER
    while POs are being created and inspected. There is no backward movement
    from inspection to ordering.

    Pass/Fail both keep the token where it is. The only way the token leaves
    RM_ORDER is forward to GRN, and that happens when ALL POs of the buyer
    order are PASSED. To undo a received PO, cancel the GRN instead.
    """
    return {
        'success': False,
        'message': 'RM Inspection cannot be cancelled. Pass or Fail each PO. '
                   'The buyer order moves to GRN only when all POs are PASSED. '
                   'To revert received material, cancel the GRN.',
        'deprecated': True
    }
