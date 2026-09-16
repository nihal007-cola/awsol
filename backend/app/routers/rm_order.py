from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas, models
from ..database import get_db
from ..config import settings
from ..auth import get_current_user
from ..models import User
import json
import logging

router = APIRouter(prefix="/rm-order", tags=["RM Order"])

@router.get("/orders")
def get_rm_orders(db: Session = Depends(get_db)):
    """Get all orders in RM_ORDER stage - table format like BOM"""
    from .. import models
    
    tokens = db.query(crud.WorkflowToken).filter(
        crud.WorkflowToken.current_stage == "RM_ORDER",
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
        
        # Live MATERIAL_REQUIREMENT (latest version per key, CANCELLED excluded)
        req_entries = crud.get_live_ledger_entries(
            db, activity_type='MATERIAL_REQUIREMENT', buyer_order_id=buyer_order_id,
            latest_version_only=True
        )
        suppliers = set()
        for e in req_entries:
            if e.extra_data and e.extra_data.get('supplier'):
                suppliers.add(e.extra_data.get('supplier'))
        total_suppliers = len(suppliers)
        
        # Live RM_ORDER with status PROCESSED
        processed_entries = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: (e.status or '').upper() == 'PROCESSED'
        )
        processed_suppliers = set()
        for e in processed_entries:
            if e.extra_data and e.extra_data.get('supplier'):
                processed_suppliers.add(e.extra_data.get('supplier'))
        
        # Live BUYER_ORDER for this order (latest version only)
        fg_entries = crud.get_live_ledger_entries(
            db, activity_type='BUYER_ORDER', buyer_order_id=buyer_order_id,
            latest_version_only=True,
            extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
        )
        total_fgs = len(set(e.fg_key for e in fg_entries))
        
        # Count distinct live PO tokens for this buyer order.
        # This is the "No of POs Made" counter shown on the RM Order table.
        live_po_entries = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
        )
        po_tokens = set()
        for e in live_po_entries:
            pt = (e.extra_data or {}).get('poToken')
            if pt:
                po_tokens.add(pt)

        result.append({
            "buyerOrderId": buyer_order_id,
            "buyerName": buyer_order.buyer_name or "Unknown",
            "buyerOrderNo": buyer_order.buyer_order_no or "N/A",
            "orderDate": buyer_order.order_date,
            "totalFGs": total_fgs,
            "totalSuppliers": total_suppliers,
            "processedSuppliers": len(processed_suppliers),
            "totalPOsMade": len(po_tokens),
            "status": "RM_ORDER",
            "currentStage": token.current_stage,
            "currentVersion": token.current_version
        })
    
    return result

@router.post("/generate-po")
def generate_po_for_supplier(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        all_entries = crud.get_ledger_entries(db)
        supplier = crud.clean_key_exact(data.get('supplier', ''))
        selected_items = data.get('selected_items', [])
        cgst_override = data.get('cgst_override', {})
        sgst_override = data.get('sgst_override', {})
        igst_override = data.get('igst_override', {})
        allow_extra = data.get('allow_extra', False)
        supplier_alias = data.get('supplier_alias', supplier)
        excess_percentage = data.get('excess_percentage', 0)
        if not supplier or not selected_items:
            raise ValueError('Supplier and items required')
        po_token = crud.generate_po_token(db)
        po_date = datetime.utcnow()
        supplier_details = crud.get_rmsupplier_details(db, supplier)

        # Canonical ledger version for every row written by this PO generation.
        # The buyer_order_id varies per item (each item carries its own), so we
        # resolve the token per buyer_order_id lazily below.
        def _ledger_version_for(bo_id):
            t = db.query(models.WorkflowToken).filter(
                models.WorkflowToken.buyer_order_id == bo_id
            ).first()
            return t.current_version if t else 1
        if not supplier_details:
            raise ValueError('Supplier details not found')
        total_amount = 0
        total_cgst = 0
        total_sgst = 0
        total_igst = 0
        fg_keys = set()
        aggregated_items = {}
        for item in selected_items:
            fg_key = item.get('fgKey')
            fg_keys.add(fg_key)
            hsn = item.get('hsn', '')
            cgst = float(cgst_override.get(item.get('requirementKey'), item.get('cgst', 0)))
            sgst = float(sgst_override.get(item.get('requirementKey'), item.get('sgst', 0)))
            igst = float(igst_override.get(item.get('requirementKey'), item.get('igst', 0)))
            quantity = float(item.get('balanceToOrder', item.get('requiredQty', 0)))
            rate = float(item.get('rate', 0))
            if excess_percentage > 5:
                raise ValueError(f"Excess percentage cannot exceed 5%. Current: {excess_percentage}%")
            if excess_percentage > 0:
                quantity = quantity * (1 + (excess_percentage / 100))
                quantity = round(quantity * 100) / 100
            amount = quantity * rate
            cgst_amount = amount * (cgst / 100)
            sgst_amount = amount * (sgst / 100)
            igst_amount = amount * (igst / 100)
            # Aggregation identity: two lines are the same purchased line iff
            # itemNo, itemName, garmentSize, itemSize, and RM color all match.
            # Missing itemNo or color previously merged distinct RM items.
            agg_key = f"{item.get('itemNo','')}|{item.get('itemName')}|{item.get('garmentSize', 'ALL')}|{item.get('itemSize', '')}|{item.get('color', '')}"
            if agg_key not in aggregated_items:
                aggregated_items[agg_key] = {
                    'itemNo': item.get('itemNo'),
                    'itemName': item.get('itemName'),
                    'garmentSize': item.get('garmentSize', 'ALL'),
                    'color': item.get('color', ''),
                    'itemSize': item.get('itemSize', ''),
                    'totalQuantity': 0,
                    'uom': item.get('uom', 'PCS'),
                    'rate': rate,
                    'cgst': cgst,
                    'sgst': sgst,
                    'igst': igst,
                    'hsn': hsn,
                    'supplierAlias': supplier_alias,
                    'amount': 0
                }
            aggregated_items[agg_key]['totalQuantity'] += quantity
            aggregated_items[agg_key]['amount'] += amount
            total_amount += amount
            total_cgst += cgst_amount
            total_sgst += sgst_amount
            total_igst += igst_amount
        display_items = list(aggregated_items.values())
        grand_total = total_amount + total_cgst + total_sgst + total_igst
        entries_to_insert = []
        snapshot_updates = []
        for item in selected_items:
            fg_key = item.get('fgKey')
            quantity = float(item.get('balanceToOrder', item.get('requiredQty', 0)))
            rate = float(item.get('rate', 0))
            if excess_percentage > 5:
                raise ValueError(f"Excess percentage cannot exceed 5%. Current: {excess_percentage}%")
            if excess_percentage > 0:
                quantity = quantity * (1 + (excess_percentage / 100))
                quantity = round(quantity * 100) / 100
            _bo_id = item.get('buyerOrderId', '')
            _req_key = item.get('requirementKey', '')

            # Resolve the real FG key from the MATERIAL_REQUIREMENT row for this
            # requirementKey. The frontend sends only the buyer order id in
            # item.fgKey, which corrupts inventory_snapshot.fg_key downstream
            # (Issue RM filters snapshot by fg_key and finds nothing).
            _real_fg_key = fg_key
            if _req_key:
                for _e in all_entries:
                    if (_e.activity_type == 'MATERIAL_REQUIREMENT'
                        and _e.buyer_order_id == _bo_id
                        and _e.status != 'CANCELLED'
                        and (_e.extra_data or {}).get('requirementKey') == _req_key):
                        _real_fg_key = _e.fg_key or fg_key
                        break

            # Before writing the new DRAFT, supersede any PRIOR live DRAFT/SAVED
            # RM_ORDER row for the same (buyer_order_id, supplier, requirementKey),
            # REGARDLESS of poToken. Rationale: re-issuing a PO for the same
            # supplier + requirement gets a fresh poToken, and the RM_ORDER live
            # key includes poToken — so without this step the old DRAFT row would
            # survive and inflate totalPOsMade.
            if _bo_id and _req_key:
                prior_live = [e for e in all_entries
                              if e.activity_type == 'RM_ORDER'
                              and e.buyer_order_id == _bo_id
                              and e.status in ('DRAFT', 'SAVED')
                              and (e.extra_data or {}).get('supplier') == supplier
                              and (e.extra_data or {}).get('requirementKey') == _req_key]
                for old_draft in prior_live:
                    entries_to_insert.append({
                        'fg_key': old_draft.fg_key,
                        'buyer_order_id': _bo_id,
                        'activity_type': 'RM_ORDER',
                        'status': 'CANCELLED',
                        'buyer_name': old_draft.buyer_name,
                        'buyer_order_no': old_draft.buyer_order_no,
                        'order_date': old_draft.order_date,
                        'created_date': old_draft.created_date,
                        'qty': old_draft.qty,
                        'size': old_draft.size,
                        'color': old_draft.color,
                        'workflow_position': old_draft.workflow_position,
                        'version': old_draft.version or 1,
                        'extra_data': {
                            **(old_draft.extra_data or {}),
                            'cancelledAt': datetime.utcnow().isoformat(),
                            'cancelledReason': 'Superseded by new PO generation for same supplier+requirement',
                            'supersededBy': 'generate_po_for_supplier'
                        }
                    })

            entries_to_insert.append({
                'fg_key': _real_fg_key,
                'buyer_order_id': _bo_id,
                'activity_type': 'RM_ORDER',
                'status': 'DRAFT',
                'buyer_name': 'Unknown',
                'buyer_order_no': item.get('buyerOrderNo', ''),
                'order_date': po_date,
                'created_date': po_date,
                'qty': quantity,
                'size': item.get('garmentSize', item.get('size', '')),
                'color': item.get('color', ''),
                'workflow_position': 2,
                'version': _ledger_version_for(_bo_id),
                'extra_data': {
                    'poToken': po_token,
                    'supplier': supplier,
                    'supplierAlias': supplier_alias,
                    'supplierDetails': {
                        'id': supplier_details.id,
                        'category': supplier_details.category,
                        'name': supplier_details.name,
                        'gstNo': supplier_details.gst_no,
                        'address': supplier_details.address,
                        'contactPerson': supplier_details.contact_person,
                        'contactNo': supplier_details.contact_no,
                        'paymentTerm': supplier_details.payment_term
                    },
                    'itemNo': item.get('itemNo'),
                    'itemName': item.get('itemName'),
                    'hsn': item.get('hsn', ''),
                    'reqQty': float(item.get('requiredQty', 0)),
                    'balanceToOrder': float(item.get('balanceToOrder', 0)),
                    'orderedQty': quantity,
                    'uom': item.get('uom', 'PCS'),
                    'rate': rate,
                    'cgst': float(cgst_override.get(item.get('requirementKey'), item.get('cgst', 0))),
                    'sgst': float(sgst_override.get(item.get('requirementKey'), item.get('sgst', 0))),
                    'igst': float(igst_override.get(item.get('requirementKey'), item.get('igst', 0))),
                    'garmentSize': item.get('garmentSize', 'ALL'),
                    'itemSize': item.get('itemSize', ''),
                    'color': item.get('color', ''),
                    'requirementKey': item.get('requirementKey'),
                    'originalFGKey': fg_key,
                    'excessPercentage': excess_percentage,
                    'allowExtra': allow_extra,
                    'status': 'DRAFT',
                    'displayGroup': f"{item.get('itemName')}|{item.get('garmentSize')}|{item.get('color')}",
                    'consumption': item.get('consumption', 0),
                    'leadtime': item.get('leadtime', 0)
                }
            })
            _req_key = item.get('requirementKey')
            req_entries = [e for e in all_entries if e.activity_type == 'MATERIAL_REQUIREMENT'
                          and e.status == 'PENDING'
                          and e.extra_data and e.extra_data.get('requirementKey') == _req_key]
            for req in req_entries:
                _mr_bo_id = req.buyer_order_id or ''
                _mr_ver = _ledger_version_for(_mr_bo_id) if _mr_bo_id else 1
                # Supersede prior non-CANCELLED MR rows for the same logical key
                # (buyer_order_id, fg_key, requirementKey) before writing ORDERED.
                prior_mr = [e for e in all_entries
                            if e.activity_type == 'MATERIAL_REQUIREMENT'
                            and e.buyer_order_id == _mr_bo_id
                            and e.fg_key == req.fg_key
                            and e.status != 'CANCELLED'
                            and (e.extra_data or {}).get('requirementKey') == _req_key]
                for old_mr in prior_mr:
                    entries_to_insert.append({
                        'fg_key': old_mr.fg_key,
                        'buyer_order_id': _mr_bo_id,
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
                            'cancelledReason': 'New PO generated for same requirement',
                            'supersededBy': 'generate_po_for_supplier'
                        }
                    })
                entries_to_insert.append({
                    'fg_key': req.fg_key,
                    'buyer_order_id': _mr_bo_id,
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'ORDERED',
                    'buyer_name': req.buyer_name,
                    'buyer_order_no': req.buyer_order_no,
                    'order_date': req.order_date,
                    'created_date': req.created_date,
                    'qty': req.qty,
                    'size': req.size,
                    'color': req.color,
                    'workflow_position': 1.5,
                    'version': _mr_ver,
                    'extra_data': {**(req.extra_data or {}), 'poToken': po_token, 'orderedAt': datetime.utcnow().isoformat()}
                })
                snapshot_updates.append({
                    'requirementKey': req.extra_data.get('requirementKey') if req.extra_data else None,
                    'fgKey': req.fg_key,
                    'itemNo': req.extra_data.get('itemNo') if req.extra_data else None,
                    'itemName': req.extra_data.get('itemName') if req.extra_data else None,
                    'size': req.size,
                    'color': req.color,
                    'supplier': req.extra_data.get('supplier') if req.extra_data else None,
                    'requiredDelta': 0,
                    'grnDelta': 0,
                    'issueDelta': 0
                })
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        po_html = generate_po_html(po_token, supplier_alias, supplier_details, display_items, grand_total, total_cgst, total_sgst, total_igst, po_date)
        return {
            'success': True,
            'poToken': po_token,
            'poHTML': po_html,
            'message': 'PO generated successfully',
            'itemCount': len(display_items),
            'fgCount': len(fg_keys),
            'aggregatedItems': display_items
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

def generate_po_html(po_token, supplier_alias, supplier_details, items, grand_total, total_cgst, total_sgst, total_igst, po_date):
    company = {
        'name': settings.company_name,
        'address': settings.company_address,
        'gst': settings.company_gst,
        'state': settings.company_state
    }
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>Purchase Order - {po_token}</title>
    <style>
      * {{ margin:0; padding:0; box-sizing:border-box; }}
      body {{ font-family:'Segoe UI',Arial,sans-serif; margin:20px; background:#f8f9fa; }}
      .container {{ max-width:1100px; margin:0 auto; background:white; padding:30px; border-radius:12px; }}
      .header {{ text-align:center; border-bottom:3px solid #2a6df4; padding-bottom:20px; margin-bottom:20px; }}
      .company-name {{ font-size:24px; font-weight:700; color:#1a3a6a; }}
      .po-title {{ text-align:center; font-size:20px; font-weight:700; color:#1a3a6a; margin:15px 0; }}
      table {{ width:100%; border-collapse:collapse; margin:15px 0; font-size:11px; }}
      table th {{ background:#1a3a6a; color:white; padding:8px; text-align:left; }}
      table td {{ padding:6px; border-bottom:1px solid #e9edf4; }}
      .totals {{ text-align:right; margin-top:15px; }}
      .grand-total {{ font-size:18px; font-weight:700; color:#1a3a6a; }}
    </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <div class="company-name">{company['name']}</div>
          <div style="font-size:12px;color:#555;">{company['address']}</div>
          <div style="font-size:12px;color:#555;">GST: {company['gst']} | State: {company['state']}</div>
        </div>
        <div class="po-title">PURCHASE ORDER</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;background:#f0f4fe;padding:12px;border-radius:8px;margin:10px 0;">
          <span><strong>PO Number:</strong> {po_token}</span>
          <span><strong>Date:</strong> {po_date.strftime('%d-%m-%Y')}</span>
          <span><strong>Supplier:</strong> {supplier_alias}</span>
        </div>
        <div style="background:#f8faff;padding:12px;border-radius:8px;margin:10px 0;">
          <strong>Supplier Details</strong>
          <div>{supplier_alias}</div>
          <div>{supplier_details.address or 'Address not available'}</div>
          <div>GST: {supplier_details.gst_no or 'N/A'}</div>
        </div>
        <table>
          <thead><tr><th>#</th><th>Item</th><th>Size</th><th>Color</th><th>HSN</th><th>Quantity</th><th>UOM</th><th>Rate</th><th>Amount</th></tr></thead>
          <tbody>"""
    for idx, item in enumerate(items, 1):
        html += f"<tr><td>{idx}</td><td>{item.get('itemName', '')}</td><td>{item.get('garmentSize', 'ALL')}</td>"
        html += f"<td>{item.get('color', '-')}</td><td>{item.get('hsn', '-')}</td>"
        html += f"<td>{item.get('totalQuantity', 0):.2f}</td><td>{item.get('uom', 'PCS')}</td>"
        html += f"<td>₹{item.get('rate', 0):.2f}</td><td>₹{item.get('amount', 0):.2f}</td></tr>"
    subtotal = grand_total - total_cgst - total_sgst - total_igst
    html += f"""
          </tbody></table>
        <div class="totals">
          <div><strong>Subtotal:</strong> ₹{subtotal:.2f}</div>
          <div><strong>CGST:</strong> ₹{total_cgst:.2f}</div>
          <div><strong>SGST:</strong> ₹{total_sgst:.2f}</div>
          <div><strong>IGST:</strong> ₹{total_igst:.2f}</div>
          <div class="grand-total"><strong>Grand Total:</strong> ₹{grand_total:.2f}</div>
        </div>
        <div style="margin-top:20px;padding-top:20px;border-top:2px solid #e9edf4;text-align:center;font-size:12px;color:#666;">
          <p>This is a computer generated Purchase Order. No signature required.</p>
          <p><strong>For {company['name']}</strong></p>
        </div>
      </div>
    </body>
    </html>
    """
    return html

@router.post("/save")
def save_po(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        po_token = crud.clean_key_exact(data.get('po_token', ''))
        all_entries = crud.get_ledger_entries(db)
        entries_to_insert = []
        updated = 0
        for entry in all_entries:
            if entry.activity_type == 'RM_ORDER' and entry.extra_data and entry.extra_data.get('poToken') == po_token and entry.status == 'DRAFT':
                extra_data_copy = dict(entry.extra_data or {})
                extra_data_copy['status'] = 'SAVED'
                entries_to_insert.append({
                    'fg_key': entry.fg_key,
                    'activity_type': 'RM_ORDER',
                    'status': 'SAVED',
                    'buyer_name': entry.buyer_name,
                    'buyer_order_no': entry.buyer_order_no,
                    'order_date': entry.order_date,
                    'created_date': entry.created_date,
                    'qty': entry.qty,
                    'size': entry.size,
                    'color': entry.color,
                    'workflow_position': 2,
                    'extra_data': extra_data_copy
                })
                updated += 1
        if entries_to_insert:
            crud.add_ledger_entries_bulk(db, entries_to_insert)
        return {'success': True, 'message': 'PO saved successfully', 'updated': updated}
    except Exception as e:
        return {'success': False, 'message': str(e)}

@router.post("/process")
def process_po(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        po_token = crud.clean_key_exact(data.get('po_token', ''))
        if not po_token:
            return {"success": False, "message": "PO Token is required"}
        all_entries = crud.get_ledger_entries(db)
        draft_entries = [e for e in all_entries if e.activity_type == 'RM_ORDER' 
                        and e.extra_data and e.extra_data.get('poToken') == po_token 
                        and e.status == 'DRAFT']
        if not draft_entries:
            return {"success": False, "message": "PO Token not found: " + po_token}
        buyer_order_id = draft_entries[0].buyer_order_id
        if not buyer_order_id:
            return {"success": False, "message": "Buyer Order ID not found"}
        
        # Get all RM_ORDER entries for this buyer order
        all_rm_entries = [e for e in all_entries if e.buyer_order_id == buyer_order_id 
                         and e.activity_type == 'RM_ORDER'
                         and e.status != 'CANCELLED']
        
        # Get unique suppliers from MATERIAL_REQUIREMENT
        req_entries = [e for e in all_entries if e.buyer_order_id == buyer_order_id 
                       and e.activity_type == 'MATERIAL_REQUIREMENT'
                       and e.status not in ['CANCELLED']]
        suppliers = set()
        for e in req_entries:
            if e.extra_data and e.extra_data.get('supplier'):
                suppliers.add(e.extra_data.get('supplier'))
        total_suppliers = len(suppliers)
        
        # Get processed suppliers
        processed_rm = [e for e in all_rm_entries if e.status == 'PROCESSED']
        processed_suppliers = set()
        for e in processed_rm:
            if e.extra_data and e.extra_data.get('supplier'):
                processed_suppliers.add(e.extra_data.get('supplier'))
        
        # Mark this PO as PROCESSED
        entries_to_insert = []
        fg_keys = set()
        now = datetime.utcnow()
        for entry in draft_entries:
            fg_key = entry.fg_key
            if fg_key:
                fg_keys.add(fg_key)
            extra_data_copy = dict(entry.extra_data or {})
            extra_data_copy['status'] = 'PROCESSED'
            extra_data_copy['processedAt'] = now.isoformat()
            entries_to_insert.append({
                'fg_key': fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'RM_ORDER',
                'status': 'PROCESSED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': 2.5,
                'extra_data': extra_data_copy
            })
        crud.add_ledger_entries_bulk(db, entries_to_insert)

        # Recompute processed suppliers after insert.
        processed_rm_after = [e for e in all_entries if e.buyer_order_id == buyer_order_id
                             and e.activity_type == 'RM_ORDER'
                             and e.status == 'PROCESSED']
        processed_suppliers_after = set()
        for e in processed_rm_after:
            if e.extra_data and e.extra_data.get('supplier'):
                processed_suppliers_after.add(e.extra_data.get('supplier'))
        for e in entries_to_insert:
            if e['extra_data'].get('supplier'):
                processed_suppliers_after.add(e['extra_data'].get('supplier'))

        # Count distinct live PO tokens (excluding this one we just wrote,
        # since the same token may now have multiple live rows).
        live_po_entries = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
        )
        po_tokens = set()
        for e in live_po_entries:
            pt = (e.extra_data or {}).get('poToken')
            if pt:
                po_tokens.add(pt)

        # NOTE: token movement does NOT happen here. The buyer order stays in
        # RM_ORDER until every PO of the order is PASSED in RM Inspection.
        return {
            'success': True,
            'message': f'PO {po_token} processed. Awaiting RM Inspection.',
            'poToken': po_token,
            'fgKeys': list(fg_keys),
            'totalSuppliers': total_suppliers,
            'processedSuppliers': len(processed_suppliers_after),
            'totalPOsMade': len(po_tokens),
        }
        
    except Exception as e:
        return {'success': False, 'message': str(e)}

@router.post("/cancel")
def cancel_rm_order(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        po_token = crud.clean_key_exact(data.get('po_token', ''))
        if not po_token:
            return {"success": False, "message": "PO Token is required"}
        all_entries = crud.get_ledger_entries(db)
        draft_entries = [e for e in all_entries if e.activity_type == 'RM_ORDER' 
                        and e.extra_data and e.extra_data.get('poToken') == po_token 
                        and e.status not in ['CANCELLED', 'PROCESSED']]
        if not draft_entries:
            return {"success": False, "message": "PO Token not found or already processed: " + po_token}
        buyer_order_id = draft_entries[0].buyer_order_id
        if not buyer_order_id:
            return {"success": False, "message": "Buyer Order ID not found"}
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "No workflow token found"}
        if token_state["current_stage"] != "RM_ORDER":
            return {"success": False, "message": f"Cannot cancel from stage: {token_state['current_stage']}"}
        if not crud.can_move_backward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move backward"}
        move_result = crud.move_stage(db, buyer_order_id, "backward", "system")
        entries_to_insert = []
        now = datetime.utcnow()
        for entry in draft_entries:
            extra_data_copy = dict(entry.extra_data or {})
            extra_data_copy['status'] = 'CANCELLED'
            extra_data_copy['cancelledAt'] = now.isoformat()
            extra_data_copy['version'] = move_result["new_version"]
            extra_data_copy['previous_version'] = move_result["previous_version"]
            extra_data_copy['stage_movement'] = 'backward'
            extra_data_copy['from_stage'] = move_result["previous_stage"]
            extra_data_copy['to_stage'] = move_result["new_stage"]
            entries_to_insert.append({
                'fg_key': entry.fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'RM_ORDER',
                'status': 'CANCELLED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': 1.5,
                'extra_data': extra_data_copy
            })
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        return {
            'success': True, 
            'message': 'RM Order cancelled. Moved back to Costing Approval.',
            'new_stage': move_result["new_stage"],
            'new_version': move_result["new_version"]
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

@router.get("/materials/{order_id}")
def get_rm_order_materials(order_id: str, db: Session = Depends(get_db)):
    """Get materials for an RM Order grouped by supplier"""
    from .. import models
    
    buyer_order = db.query(models.BuyerOrder).filter(
        models.BuyerOrder.buyer_order_id == order_id
    ).first()
    
    if not buyer_order:
        return {"success": False, "message": "Order not found"}
    
    req_entries = crud.get_live_ledger_entries(
        db, activity_type='MATERIAL_REQUIREMENT', buyer_order_id=order_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() not in ('CANCELLED', 'ORDERED')
    )
    
    supplier_groups = {}
    for entry in req_entries:
        extra = entry.extra_data or {}
        supplier = extra.get('supplier', 'Unknown')
        if supplier not in supplier_groups:
            supplier_groups[supplier] = {
                'supplier': supplier,
                'items': [],
                'totalQty': 0,
                'totalAmount': 0,
                '_agg': {},          # key -> item index in items[]
            }
        item_size = extra.get('itemSize', '')
        color = extra.get('color', '')
        item_no = extra.get('itemNo', '')
        item_name = extra.get('itemName', '')
        garment_size = entry.size or 'ALL'
        # Aggregation identity matches generate_po_for_supplier: two lines are
        # the same purchased line iff itemNo, itemName, garmentSize, itemSize,
        # and RM colour all match. Without this, the modal showed one row per FG
        # even when the PO itself aggregated them.
        agg_key = f"{item_no}|{item_name}|{garment_size}|{item_size}|{color}"
        grp = supplier_groups[supplier]
        if agg_key in grp['_agg']:
            existing = grp['items'][grp['_agg'][agg_key]]
            existing['requiredQty'] += entry.qty or 0
        else:
            item = {
                'itemNo': item_no,
                'itemName': item_name,
                'garmentSize': garment_size,
                'itemSize': item_size,
                'color': color,
                'requiredQty': entry.qty or 0,
                'uom': extra.get('uom', 'PCS'),
                'rate': extra.get('rate', 0),
                'consumption': extra.get('consumption', 0),
                'cgst': extra.get('cgst', 0),
                'sgst': extra.get('sgst', 0),
                'igst': extra.get('igst', 0),
                'hsn': extra.get('hsn', ''),
                'requirementKey': extra.get('requirementKey', ''),
                'leadtime': extra.get('leadtime', 0)
            }
            grp['_agg'][agg_key] = len(grp['items'])
            grp['items'].append(item)
        grp['totalQty'] += entry.qty or 0
        grp['totalAmount'] += (entry.qty or 0) * (extra.get('rate', 0) or 0)
    # Drop the private aggregation index before returning.
    for grp in supplier_groups.values():
        grp.pop('_agg', None)
    
    return {
        'success': True,
        'buyerOrderId': order_id,
        'buyerName': buyer_order.buyer_name,
        'buyerOrderNo': buyer_order.buyer_order_no,
        'supplierGroups': list(supplier_groups.values())
    }

@router.post("/cancel-buyer-order")
def cancel_rm_order_for_buyer(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Cancel the RM Order stage for a whole buyer order:
    - Cancel all non-cancelled RM_ORDER entries for this buyer order
    - Revert MATERIAL_REQUIREMENT ORDERED lines back to PENDING
    - Move token backward RM_ORDER -> COSTING_APPROVAL
    """
    try:
        buyer_order_id = crud.clean_key_exact(data.get('buyer_order_id', ''))
        if not buyer_order_id:
            return {'success': False, 'message': 'Buyer Order ID required'}

        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {'success': False, 'message': 'No workflow token found'}
        if token_state['current_stage'] != 'RM_ORDER':
            return {'success': False, 'message': f"Cannot cancel from stage: {token_state['current_stage']}"}
        if not crud.can_move_backward(db, buyer_order_id):
            return {'success': False, 'message': 'Cannot move backward'}

        move_result = crud.move_stage(db, buyer_order_id, 'backward', 'system')

        all_entries = crud.get_ledger_entries(db)
        rm_entries = [e for e in all_entries
                      if e.buyer_order_id == buyer_order_id
                      and e.activity_type == 'RM_ORDER'
                      and e.status not in ('CANCELLED',)]
        req_entries = [e for e in all_entries
                       if e.buyer_order_id == buyer_order_id
                       and e.activity_type == 'MATERIAL_REQUIREMENT'
                       and e.status == 'ORDERED']

        now = datetime.utcnow()
        entries_to_insert = []
        cancelled_pos = set()

        for e in rm_entries:
            po = (e.extra_data or {}).get('poToken', '')
            if po:
                cancelled_pos.add(po)
            meta = dict(e.extra_data or {})
            meta['status'] = 'CANCELLED'
            meta['cancelledAt'] = now.isoformat()
            meta['cancelledReason'] = 'RM Order cancelled at buyer-order level'
            meta['version'] = move_result['new_version']
            meta['previous_version'] = move_result['previous_version']
            meta['stage_movement'] = 'backward'
            meta['from_stage'] = move_result['previous_stage']
            meta['to_stage'] = move_result['new_stage']
            entries_to_insert.append({
                'fg_key': e.fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'RM_ORDER',
                'status': 'CANCELLED',
                'buyer_name': e.buyer_name,
                'buyer_order_no': e.buyer_order_no,
                'order_date': e.order_date,
                'created_date': e.created_date,
                'qty': e.qty,
                'size': e.size,
                'color': e.color,
                'workflow_position': 1.5,
                'extra_data': meta
            })

        for e in req_entries:
            meta = dict(e.extra_data or {})
            meta['poToken'] = None
            meta['cancelledAt'] = now.isoformat()
            meta['restoredFrom'] = 'RM_ORDER_CANCELLATION'
            entries_to_insert.append({
                'fg_key': e.fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'PENDING',
                'buyer_name': e.buyer_name,
                'buyer_order_no': e.buyer_order_no,
                'order_date': e.order_date,
                'created_date': e.created_date,
                'qty': e.qty,
                'size': e.size,
                'color': e.color,
                'workflow_position': 1.5,
                'extra_data': meta
            })

        crud.add_ledger_entries_bulk(db, entries_to_insert)

        return {
            'success': True,
            'message': f'RM Order cancelled. {len(cancelled_pos)} PO(s) cancelled, {len(req_entries)} requirement line(s) reverted to PENDING. Moved back to Costing Approval.',
            'newStage': move_result['new_stage'],
            'newVersion': move_result['new_version'],
            'cancelledPOs': list(cancelled_pos),
            'revertedRequirements': len(req_entries)
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}
