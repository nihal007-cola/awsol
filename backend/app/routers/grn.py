from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas, models
from ..database import get_db
from ..config import settings
import json
import logging

router = APIRouter(prefix="/grn", tags=["GRN"])

def build_identity(po_token, fg_key, item_no, garment_size):
    return {
        'poToken': crud.clean_key_exact(po_token),
        'fgKey': crud.clean_key_exact(fg_key),
        'itemNo': crud.clean_key_exact(item_no),
        'garmentSize': crud.clean_key_exact(garment_size)
    }

def identity_to_string(identity):
    return f"{identity['poToken']}|{identity['fgKey']}|{identity['itemNo']}|{identity['garmentSize']}"

def find_po_line(entries, identity):
    clean_po_token = crud.clean_key_exact(identity['poToken'])
    clean_fg_key = crud.clean_key_exact(identity['fgKey'])
    clean_item_no = crud.clean_key_exact(identity['itemNo'])
    clean_garment_size = crud.clean_key_exact(identity['garmentSize'])
    
    for e in entries:
        if (e.activity_type == 'RM_ORDER' and 
            (e.status == 'PROCESSED' or e.status == 'PARTIAL') and
            e.extra_data and 
            crud.clean_key_exact(e.extra_data.get('poToken', '')) == clean_po_token and
            crud.clean_key_exact(e.fg_key) == clean_fg_key and
            crud.clean_key_exact(e.extra_data.get('itemNo', '')) == clean_item_no and
            crud.clean_key_exact(e.size) == clean_garment_size):
            return e
    return None

def calculate_received_qty(grn_entries, identity):
    """Sum received qty across GRN entries for a given item identity.
    Handles both:
      (a) nested format: grn.extra_data['items'] = [{itemNo, receivedQty, garmentSize, ...}]
      (b) flat format: grn.extra_data = {itemNo, receivedQty, garmentSize, poToken, ...}
    """
    total = 0
    clean_po_token = crud.clean_key_exact(identity['poToken'])
    clean_item_no = crud.clean_key_exact(identity['itemNo'])
    clean_garment_size = crud.clean_key_exact(identity['garmentSize'])
    
    def matches(po, item_no, garment_size):
        return (crud.clean_key_exact(po) == clean_po_token
                and crud.clean_key_exact(item_no) == clean_item_no
                and crud.clean_key_exact(garment_size or 'ALL') == clean_garment_size)
    
    for grn in grn_entries:
        if not grn.extra_data:
            continue
        # Skip cancelled
        if grn.status == 'CANCELLED':
            continue
        
        ed = grn.extra_data
        # Try nested first
        grn_items = ed.get('items', [])
        if grn_items:
            for grn_item in grn_items:
                if matches(ed.get('poToken', ''), grn_item.get('itemNo', ''), grn_item.get('garmentSize', '')):
                    total += float(grn_item.get('receivedQty', 0) or 0)
        else:
            # Flat format
            po = ed.get('poToken', '')
            item_no = ed.get('itemNo', '')
            garment_size = ed.get('garmentSize') or grn.size or 'ALL'
            if matches(po, item_no, garment_size):
                total += float(ed.get('receivedQty', 0) or 0)
    return total

@router.get("/orders")
def get_grn_orders(buyer_order_id: str = None, db: Session = Depends(get_db)):
    result = []
    processed_po_tokens = set()
    
    # Live RM_ORDER rows (per (buyer_order_id, poToken, requirementKey))
    rm_order_filter = lambda e: (e.status or '').upper() in ('PROCESSED', 'PARTIAL', 'COMPLETED') and bool((e.extra_data or {}).get('poToken'))
    if buyer_order_id:
        rm_orders = crud.get_live_ledger_entries(db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id, extra_filter=rm_order_filter)
    else:
        rm_orders = crud.get_live_ledger_entries(db, activity_type='RM_ORDER', extra_filter=rm_order_filter)
    
    # Filter out junk lines: empty itemNo AND zero qty
    def is_valid_line(e):
        item_no = (e.extra_data.get('itemNo') or '').strip()
        qty = float(e.qty or 0)
        return bool(item_no) or qty > 0
    
    rm_orders = [e for e in rm_orders if is_valid_line(e)]
    
    for entry in rm_orders:
        po_token = entry.extra_data.get('poToken', '')
        if not po_token or po_token in processed_po_tokens:
            continue
        
        line_items = [e for e in rm_orders if crud.clean_key_exact(e.extra_data.get('poToken', '')) == crud.clean_key_exact(po_token)]
        if not line_items:
            continue
        
        first_item = line_items[0]
        metadata = first_item.extra_data or {}
        
        # Live GRN rows for this poToken
        grn_entries = crud.get_live_ledger_entries(
            db, activity_type='GRN',
            buyer_order_id=first_item.buyer_order_id or None,
            extra_filter=lambda e: crud.clean_key_exact((e.extra_data or {}).get('poToken', '')) == crud.clean_key_exact(po_token)
        )
        
        has_grn = len(grn_entries) > 0
        status = metadata.get('status', 'PROCESSED')
        
        # Compute displayStatus: NR / PARTIAL / RECEIVED
        # Based on GRN entries with matching poToken
        active_grns = [g for g in grn_entries if g.status != 'CANCELLED']
        has_received = any(g.status == 'RECEIVED' for g in active_grns)
        has_partial = any(g.status == 'PARTIAL' for g in active_grns)
        
        if has_received:
            display_status = 'RECEIVED'
        elif has_partial:
            display_status = 'PARTIAL'
        else:
            display_status = 'NR'
        
        if has_grn:
            total_ordered = sum(float(e.qty or e.extra_data.get('orderedQty', 0) or 0) for e in line_items)
            total_received = 0
            for grn in grn_entries:
                items = grn.extra_data.get('items', []) if grn.extra_data else []
                for item in items:
                    total_received += float(item.get('receivedQty', 0) or 0)
                # Also flat format
                if not items and grn.extra_data:
                    total_received += float(grn.extra_data.get('receivedQty', 0) or 0)
            is_complete = total_received >= total_ordered - settings.tolerance
            status = 'COMPLETED' if is_complete else 'PARTIAL'
        
        unpacked_items = []
        for item in line_items:
            identity = build_identity(po_token, item.fg_key or '', item.extra_data.get('itemNo', ''), item.size or 'ALL')
            ordered_qty = float(item.qty or item.extra_data.get('orderedQty', 0) or 0)
            received_qty = float(calculate_received_qty(grn_entries, identity) or 0)
            balance_to_receive = ordered_qty - received_qty
            
            unpacked_items.append({
                'poToken': identity['poToken'],
                'fgKey': identity['fgKey'],
                'itemNo': identity['itemNo'],
                'garmentSize': identity['garmentSize'],
                'itemName': item.extra_data.get('itemName', ''),
                'itemSize': item.extra_data.get('itemSize', ''),
                'color': item.color or item.extra_data.get('color', ''),
                'orderedQty': ordered_qty,
                'receivedQty': received_qty,
                'balanceToReceive': balance_to_receive if balance_to_receive > settings.tolerance else 0,
                'isComplete': balance_to_receive <= settings.tolerance,
                'uom': item.extra_data.get('uom', 'PCS'),
                'rate': item.extra_data.get('rate', 0),
                'cgst': item.extra_data.get('cgst', 0),
                'igst': item.extra_data.get('igst', 0),
                'hsn': item.extra_data.get('hsn', ''),
                'requirementKey': item.extra_data.get('requirementKey', ''),
                'supplier': item.extra_data.get('supplier', ''),
                'supplierAlias': item.extra_data.get('supplierAlias', '')
            })
        
        grouped_by_fg = {}
        for item in unpacked_items:
            if item['fgKey'] not in grouped_by_fg:
                grouped_by_fg[item['fgKey']] = {
                    'fgKey': item['fgKey'],
                    'items': []
                }
            grouped_by_fg[item['fgKey']]['items'].append(item)
        
        result.append({
            'poToken': po_token,
            'supplier': metadata.get('supplier', metadata.get('supplierAlias', '')),
            'supplierAlias': metadata.get('supplierAlias', metadata.get('supplier', '')),
            'items': unpacked_items,
            'groupedByFG': list(grouped_by_fg.values()),
            'totalOrdered': sum(float(i['orderedQty'] or 0) for i in unpacked_items),
            'totalReceived': sum(float(i['receivedQty'] or 0) for i in unpacked_items),
            'totalBalance': sum(float(i['balanceToReceive'] or 0) for i in unpacked_items),
            'status': status,
            'displayStatus': display_status,
            'hasGRN': has_grn,
            'orderDate': entry.order_date,
            'fgKeys': list(set(i['fgKey'] for i in unpacked_items if i['fgKey']))
        })
        processed_po_tokens.add(po_token)
    
    return result

@router.get("/buyer-orders")
def get_grn_buyer_orders(db: Session = Depends(get_db)):
    """Get all buyer orders currently in GRN stage with their PO summary"""
    from .. import models
    
    tokens = db.query(models.WorkflowToken).filter(
        models.WorkflowToken.current_stage == "GRN",
        models.WorkflowToken.status == "ACTIVE"
    ).all()
    
    if not tokens:
        return []
    
    result = []
    
    for token in tokens:
        buyer_order_id = token.buyer_order_id
        
        # Get buyer order details
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        
        if not buyer_order:
            continue
        
        # Live RM_ORDER rows for this order
        live_rm = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: (e.status or '').upper() in ('PROCESSED', 'COMPLETED', 'PARTIAL') and bool((e.extra_data or {}).get('poToken'))
        )
        po_tokens = set(e.extra_data.get('poToken') for e in live_rm if e.extra_data and e.extra_data.get('poToken'))
        
        # Live BUYER_ORDER, latest version only
        fg_entries = crud.get_live_ledger_entries(
            db, activity_type='BUYER_ORDER', buyer_order_id=buyer_order_id,
            latest_version_only=True,
            extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
        )
        total_fgs = len(set(e.fg_key for e in fg_entries))

        # Any live GRN row means at least one PO was received — pre-receive
        # cancel for the whole buyer order must be disabled.
        live_grns = crud.get_live_ledger_entries(
            db, activity_type='GRN', buyer_order_id=buyer_order_id
        )
        has_any_grn = len(live_grns) > 0
        
        result.append({
            'buyerOrderId': buyer_order_id,
            'buyerName': buyer_order.buyer_name or 'Unknown',
            'buyerOrderNo': buyer_order.buyer_order_no or 'N/A',
            'orderDate': buyer_order.order_date,
            'totalFGs': total_fgs,
            'totalPOs': len(po_tokens),
            'status': 'PENDING',
            'hasAnyGRN': has_any_grn,
            'currentStage': token.current_stage,
            'currentVersion': token.current_version
        })
    
    return result

from fastapi.responses import HTMLResponse

@router.get("/print-po/{po_token}")
def print_po_html(po_token: str, db: Session = Depends(get_db)):
    """Return professional PO HTML for printing"""
    from .. import models
    
    clean_token = crud.clean_key_exact(po_token)
    all_entries = crud.get_ledger_entries(db)
    
    # Get PO line items from activity_ledger
    po_entries = [e for e in all_entries 
                 if e.activity_type == 'RM_ORDER'
                 and e.extra_data 
                 and crud.clean_key_exact(e.extra_data.get('poToken', '')) == clean_token]
    
    # Filter out junk lines: empty itemNo AND zero qty
    po_entries = [e for e in po_entries 
                 if ((e.extra_data.get('itemNo') or '').strip() 
                     or float(e.qty or 0) > 0)]
    
    if not po_entries:
        return HTMLResponse("<h1>PO not found</h1>", status_code=404)
    
    first = po_entries[0]
    metadata = first.extra_data or {}
    supplier = metadata.get('supplierAlias', metadata.get('supplier', 'Unknown'))
    buyer_order_id = first.buyer_order_id or '—'
    po_date = first.order_date or first.created_date
    
    # Aggregate items by item+size+color
    aggregated = {}
    total_amount = 0
    total_cgst = 0
    total_sgst = 0
    total_igst = 0
    for e in po_entries:
        qty = float(e.qty or 0)
        rate = float(e.extra_data.get('rate') or 0)
        amount = qty * rate
        cgst = float(e.extra_data.get('cgst') or 0)
        sgst = float(e.extra_data.get('sgst') or 0)
        igst = float(e.extra_data.get('igst') or 0)
        cgst_amt = amount * cgst / 100
        sgst_amt = amount * sgst / 100
        igst_amt = amount * igst / 100
        key = f"{e.extra_data.get('itemNo','')}|{e.size or 'ALL'}|{e.color or ''}|{e.extra_data.get('itemSize','')}"
        if key not in aggregated:
            aggregated[key] = {
                'itemNo': e.extra_data.get('itemNo', ''),
                'itemName': e.extra_data.get('itemName', ''),
                'garmentSize': e.size or 'ALL',
                'itemSize': e.extra_data.get('itemSize', ''),
                'color': e.color or e.extra_data.get('color', ''),
                'hsn': e.extra_data.get('hsn', ''),
                'qty': 0,
                'uom': e.extra_data.get('uom', 'PCS'),
                'rate': rate,
                'cgst': cgst,
                'sgst': sgst,
                'igst': igst,
                'amount': 0
            }
        aggregated[key]['qty'] += qty
        aggregated[key]['amount'] += amount
        total_amount += amount
        total_cgst += cgst_amt
        total_sgst += sgst_amt
        total_igst += igst_amt

    grand_total = total_amount + total_cgst + total_sgst + total_igst
    items = list(aggregated.values())
    
    company = {
        'name': settings.company_name,
        'address': settings.company_address,
        'gst': settings.company_gst,
        'state': settings.company_state
    }
    
    rows_html = ''
    for idx, item in enumerate(items, 1):
        rows_html += f"""<tr>
            <td style="text-align:center;">{idx}</td>
            <td>{item['itemName']}</td>
            <td style="text-align:center;">{item['itemNo']}</td>
            <td style="text-align:center;">{item['garmentSize']}</td>
            <td style="text-align:center;">{item['itemSize']}</td>
            <td style="text-align:center;">{item['color']}</td>
            <td style="text-align:center;">{item['hsn']}</td>
            <td style="text-align:right;">{item['qty']:.2f}</td>
            <td style="text-align:center;">{item['uom']}</td>
            <td style="text-align:right;">₹{item['rate']:.2f}</td>
            <td style="text-align:right;">₹{item['amount']:.2f}</td>
        </tr>"""
    
    po_date_str = po_date.strftime('%d-%m-%Y') if po_date else '—'
    
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Purchase Order - {clean_token}</title>
<style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:'Segoe UI',Arial,sans-serif; padding:24px; background:#f8f9fa; }}
    .container {{ max-width:1100px; margin:0 auto; background:white; padding:30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.1); }}
    .header {{ text-align:center; border-bottom:3px solid #2a6df4; padding-bottom:20px; margin-bottom:20px; }}
    .company-name {{ font-size:24px; font-weight:700; color:#1a3a6a; }}
    .company-details {{ font-size:12px; color:#555; }}
    .po-title {{ text-align:center; font-size:20px; font-weight:700; color:#1a3a6a; margin:15px 0; }}
    .info-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; background:#f0f4fe; padding:12px 16px; border-radius:8px; margin:12px 0; font-size:13px; }}
    table {{ width:100%; border-collapse:collapse; margin:15px 0; font-size:12px; }}
    table th {{ background:#1a3a6a; color:white; padding:8px; text-align:left; }}
    table td {{ padding:6px 8px; border-bottom:1px solid #e9edf4; }}
    .totals {{ text-align:right; margin-top:15px; font-size:13px; }}
    .grand-total {{ font-size:18px; font-weight:700; color:#1a3a6a; }}
    .footer {{ margin-top:30px; border-top:2px solid #e9edf4; padding-top:20px; text-align:center; font-size:12px; color:#666; }}
    .no-print {{ display:inline-block; }}
    @media print {{ body {{ padding:10px; background:white; }} .container {{ box-shadow:none; padding:15px; }} .no-print {{ display:none; }} }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="company-name">{company['name']}</div>
        <div class="company-details">{company['address']}</div>
        <div class="company-details">GST: {company['gst']} | State: {company['state']}</div>
    </div>
    <div class="po-title">PURCHASE ORDER</div>
    <div class="info-grid">
        <span><strong>PO Number:</strong> {clean_token}</span>
        <span><strong>Date:</strong> {po_date_str}</span>
        <span><strong>Supplier:</strong> {supplier}</span>
        <span><strong>Buyer Order Ref:</strong> {buyer_order_id}</span>
    </div>
    <table>
        <thead>
            <tr>
                <th>#</th><th>Item Name</th><th>Item No</th><th>Garment Size</th><th>Item Size</th>
                <th>Color</th><th>HSN</th><th>Qty</th><th>UOM</th><th>Rate</th><th>Amount</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    <div class="totals">
        <div><strong>Subtotal:</strong> ₹{total_amount:.2f}</div>
        <div><strong>CGST:</strong> ₹{total_cgst:.2f}</div>
        <div><strong>SGST:</strong> ₹{total_sgst:.2f}</div>
        <div><strong>IGST:</strong> ₹{total_igst:.2f}</div>
        <div class="grand-total"><strong>Grand Total:</strong> ₹{grand_total:.2f}</div>
    </div>
    <div style="margin-top:20px;" class="no-print">
        <button onclick="window.print()" style="padding:10px 24px; background:#2a6df4; color:white; border:none; border-radius:6px; cursor:pointer; font-size:14px;">🖨️ Print</button>
    </div>
    <div class="footer">
        <p>This is a computer generated Purchase Order. No signature required.</p>
        <p><strong>For {company['name']}</strong></p>
    </div>
</div>
</body>
</html>"""
    
    return HTMLResponse(html)

@router.post("/save")
def save_grn(data: schemas.GRNSaveRequest, db: Session = Depends(get_db)):
    try:
        po_token = crud.clean_key_exact(data.po_token)
        invoice_no = data.invoice_no or ''
        received_items = data.items
        
        if not po_token:
            raise ValueError('PO Token is required')
        if not received_items:
            raise ValueError('No items to receive')
        
        valid_items = [item for item in received_items if item.received_qty > settings.tolerance]
        if not valid_items:
            raise ValueError('No valid items to receive')
        
        all_entries = crud.get_ledger_entries(db)
        validated_items = []
        has_shortfall = False
        shortfall_map = {}
        grn_entries = [e for e in all_entries if e.activity_type == 'GRN' 
                      and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token]
        
        snapshot_updates = []
        processed_lines = {}  # For deduplication
        
        for received in valid_items:
            identity = build_identity(po_token, received.fg_key or '', received.item_no or '', received.garment_size or 'ALL')
            
            matching_line = find_po_line(all_entries, identity)
            if not matching_line:
                raise ValueError(f"Item {identity['itemNo']} for FG {identity['fgKey']} not found in ledger")
            
            ordered_qty = matching_line.qty or matching_line.extra_data.get('orderedQty', 0)
            previously_received = calculate_received_qty(grn_entries, identity)
            received_qty = received.received_qty
            balance_to_receive = ordered_qty - previously_received
            
            if received_qty > balance_to_receive + settings.tolerance:
                raise ValueError(f"Over-receipt for {identity['itemNo']} (Balance: {balance_to_receive})")
            
            total_received_after = previously_received + received_qty
            if total_received_after < ordered_qty - settings.tolerance:
                has_shortfall = True
                shortfall_map[identity_to_string(identity)] = {
                    'poToken': identity['poToken'],
                    'fgKey': identity['fgKey'],
                    'itemNo': identity['itemNo'],
                    'garmentSize': identity['garmentSize'],
                    'itemName': received.item_name or matching_line.extra_data.get('itemName', ''),
                    'itemSize': received.item_size or matching_line.extra_data.get('itemSize', ''),
                    'color': received.color or matching_line.extra_data.get('color', ''),
                    'orderedQty': ordered_qty,
                    'previouslyReceived': previously_received,
                    'receivedQty': received_qty,
                    'shortfall': ordered_qty - total_received_after,
                    'uom': received.uom or matching_line.extra_data.get('uom', 'PCS'),
                    'rate': received.rate or matching_line.extra_data.get('rate', 0),
                    'requirementKey': matching_line.extra_data.get('requirementKey', '')
                }
            
            validated_items.append({
                'poToken': identity['poToken'],
                'fgKey': identity['fgKey'],
                'itemNo': identity['itemNo'],
                'garmentSize': identity['garmentSize'],
                'itemName': received.item_name or matching_line.extra_data.get('itemName', ''),
                'itemSize': received.item_size or matching_line.extra_data.get('itemSize', ''),
                'color': received.color or matching_line.extra_data.get('color', ''),
                'orderedQty': ordered_qty,
                'previouslyReceived': previously_received,
                'receivedQty': received_qty,
                'rate': received.rate or matching_line.extra_data.get('rate', 0),
                'hsn': received.hsn or matching_line.extra_data.get('hsn', ''),
                'uom': received.uom or matching_line.extra_data.get('uom', 'PCS'),
                'cgst': received.cgst or matching_line.extra_data.get('cgst', 0),
                'sgst': getattr(received, 'sgst', 0) or matching_line.extra_data.get('sgst', 0),
                'igst': received.igst or matching_line.extra_data.get('igst', 0),
                'requirementKey': matching_line.extra_data.get('requirementKey', ''),
                'balanceToReceive': balance_to_receive,
                'supplier': matching_line.extra_data.get('supplier', ''),
                'supplierAlias': matching_line.extra_data.get('supplierAlias', '')
            })
            
            line_key = matching_line.extra_data.get('requirementKey', identity_to_string(identity))
            if line_key not in processed_lines:
                processed_lines[line_key] = matching_line
        
        entries_to_insert = []
        grn_extra_data = {
            'poToken': po_token,
            'invoiceNo': invoice_no,
            'items': [{
                'poToken': item['poToken'],
                'fgKey': item['fgKey'],
                'itemNo': item['itemNo'],
                'garmentSize': item['garmentSize'],
                'itemName': item['itemName'],
                'itemSize': item['itemSize'],
                'color': item['color'],
                'orderedQty': item['orderedQty'],
                'receivedQty': item['receivedQty'],
                'rate': item['rate'],
                'hsn': item['hsn'],
                'uom': item['uom'],
                'cgst': item['cgst'],
                'sgst': item.get('sgst', 0),
                'igst': item['igst'],
                'requirementKey': item['requirementKey'],
                'balanceToReceive': item['balanceToReceive'],
                'supplier': item['supplier'],
                'supplierAlias': item['supplierAlias']
            } for item in validated_items],
            'receivedAt': datetime.utcnow().isoformat(),
            'hasShortfall': has_shortfall
        }
        
        fg_keys = list(set(item['fgKey'] for item in validated_items if item['fgKey']))
        
        for fg_key in fg_keys:
            fg_items = [item for item in validated_items if item['fgKey'] == fg_key]
            fg_extra_data = dict(grn_extra_data)
            fg_extra_data['fgKey'] = fg_key
            fg_extra_data['fgItems'] = fg_items
            
            rm_order = next((e for e in all_entries if e.activity_type == 'RM_ORDER' 
                           and crud.clean_key_exact(e.fg_key) == crud.clean_key_exact(fg_key)
                           and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token), None)
            
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'GRN',
                'status': 'PARTIAL' if has_shortfall else 'COMPLETED',
                'buyer_name': rm_order.buyer_name if rm_order else '',
                'buyer_order_no': rm_order.buyer_order_no if rm_order else '',
                'order_date': rm_order.order_date if rm_order else None,
                'created_date': rm_order.created_date if rm_order else None,
                'qty': sum(item['receivedQty'] for item in fg_items),
                'size': fg_items[0]['garmentSize'] if fg_items else 'ALL',
                'color': fg_items[0]['color'] if fg_items else '',
                'workflow_position': 3,
                'extra_data': fg_extra_data
            })
        
        new_status = 'PARTIAL' if has_shortfall else 'COMPLETED'
        
        for line_key, item in processed_lines.items():
            extra_data_copy = dict(item.extra_data or {})
            extra_data_copy['status'] = new_status
            extra_data_copy['grnCompletedAt'] = datetime.utcnow().isoformat()
            
            entries_to_insert.append({
                'fg_key': item.fg_key,
                'activity_type': 'RM_ORDER',
                'status': new_status,
                'buyer_name': item.buyer_name,
                'buyer_order_no': item.buyer_order_no,
                'order_date': item.order_date,
                'created_date': item.created_date,
                'qty': item.qty,
                'size': item.size,
                'color': item.color,
                'workflow_position': 2,
                'extra_data': extra_data_copy
            })
        
        for item in validated_items:
            req_entries = [e for e in all_entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                          and e.extra_data and e.extra_data.get('requirementKey') == item['requirementKey']
                          and e.status == 'ORDERED']
            
            for req in req_entries:
                entries_to_insert.append({
                    'fg_key': req.fg_key,
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'RECEIVED',
                    'buyer_name': req.buyer_name,
                    'buyer_order_no': req.buyer_order_no,
                    'order_date': req.order_date,
                    'created_date': req.created_date,
                    'qty': req.qty,
                    'size': req.size,
                    'color': req.color,
                    'workflow_position': 1.5,
                    'extra_data': {
                        **(req.extra_data or {}),
                        'grnReceivedAt': datetime.utcnow().isoformat(),
                        'poToken': po_token,
                        'receivedQty': item['receivedQty']
                    }
                })
            
            snapshot_updates.append({
                'requirementKey': item['requirementKey'],
                'fgKey': item['fgKey'],
                'itemNo': item['itemNo'],
                'itemName': item['itemName'],
                'size': item['garmentSize'],
                'color': item['color'],
                'supplier': item['supplier'],
                'requiredDelta': 0,
                'grnDelta': item['receivedQty'],
                'issueDelta': 0
            })
        
        # Handle shortfalls
        if has_shortfall:
            buyer_order = next((e for e in all_entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
            for key, shortfall in shortfall_map.items():
                entries_to_insert.append({
                    'fg_key': shortfall['fgKey'],
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'PENDING',
                    'buyer_name': buyer_order.buyer_name if buyer_order else '',
                    'buyer_order_no': buyer_order.buyer_order_no if buyer_order else '',
                    'order_date': buyer_order.order_date if buyer_order else None,
                    'created_date': buyer_order.created_date if buyer_order else None,
                    'qty': shortfall['shortfall'],
                    'size': shortfall['garmentSize'] or 'ALL',
                    'color': shortfall['color'] or '',
                    'workflow_position': 1.5,
                    'extra_data': {
                        'itemNo': shortfall['itemNo'],
                        'itemName': shortfall['itemName'],
                        'uom': shortfall['uom'],
                        'consumption': 1,
                        'supplier': '',
                        'rate': shortfall['rate'],
                        'leadtime': 0,
                        'cgst': 0,
                        'igst': 0,
                        'hsn': '',
                        'isSizeSensitive': False,
                        'itemSize': shortfall['itemSize'],
                        'shortfallFrom': po_token,
                        'requirementKey': shortfall['requirementKey']
                    }
                })
                
                snapshot_updates.append({
                    'requirementKey': shortfall['requirementKey'],
                    'fgKey': shortfall['fgKey'],
                    'itemNo': shortfall['itemNo'],
                    'itemName': shortfall['itemName'],
                    'size': shortfall['garmentSize'],
                    'color': shortfall['color'],
                    'supplier': '',
                    'requiredDelta': shortfall['shortfall'],
                    'grnDelta': 0,
                    'issueDelta': 0
                })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        
        # ==============================================================
        # TOKEN MOVEMENT: GRN → INTERNAL_FG_ORDER
        # ==============================================================
        buyer_order_id = None
        if fg_keys:
            for fg_key in fg_keys:
                entries = crud.get_ledger_entries(db, fg_key)
                buyer_order_entry = next((e for e in entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
                if buyer_order_entry:
                    buyer_order_id = buyer_order_entry.buyer_order_id
                    break
        
        move_result = None
        if buyer_order_id:
            token_state = crud.get_token_state(db, buyer_order_id)
            if token_state and token_state["current_stage"] == "GRN":
                if crud.can_move_forward(db, buyer_order_id):
                    move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
                    logging.info(f"GRN saved: Token moved to INTERNAL_FG_ORDER for {buyer_order_id}")
        
        response = {
            'success': True,
            'message': f'GRN saved successfully. Status: {new_status}',
            'hasShortfall': has_shortfall,
            'shortfallCount': len(shortfall_map),
            'fgKeys': fg_keys,
            'snapshotUpdates': len(snapshot_updates)
        }
        
        if move_result:
            response['new_stage'] = move_result["new_stage"]
            response['new_version'] = move_result["new_version"]
            response['message'] = f'GRN saved successfully. Status: {new_status}. Moved to Internal FG Order.'
        
        return response
    except Exception as e:
        logging.error(f"GRN save error: {str(e)}")
        return {'success': False, 'message': str(e)}

@router.post("/receive")
def receive_po(data: Dict, db: Session = Depends(get_db)):
    """
    Mark a PO as RECEIVED after user enters invoice no, received date, and quantities.
    Creates GRN entries for each item, updates inventory snapshot.
    
    TODO (Placeholder): After ALL POs of a buyer order are RECEIVED, move buyer order token
    from GRN -> INTERNAL_FG_ORDER. Currently keeps token in GRN until auto-move logic is added.
    """
    try:
        po_token = crud.clean_key_exact(data.get('poToken', ''))
        buyer_order_id = data.get('buyerOrderId', '')
        supplier = data.get('supplier', '')
        invoice_no = data.get('invoiceNo', '')
        received_date = data.get('receivedDate', '')
        items = data.get('items', [])
        is_final = data.get('isFinal', False)

        if not po_token:
            raise ValueError('PO Token is required')
        if not buyer_order_id:
            raise ValueError('Buyer Order ID is required')
        if not invoice_no:
            raise ValueError('Invoice No is required')
        if not received_date:
            raise ValueError('Received Date is required')
        if not items:
            raise ValueError('No items received')

        # Parse received date
        try:
            from datetime import datetime as dt
            parsed_date = dt.strptime(received_date, '%Y-%m-%d')
        except Exception:
            parsed_date = datetime.utcnow()

        all_entries = crud.get_ledger_entries(db)
        
        # Canonical ledger version for every row written by this receive.
        _token = db.query(models.WorkflowToken).filter(
            models.WorkflowToken.buyer_order_id == buyer_order_id
        ).first()
        ledger_version = _token.current_version if _token else 1

        # Find buyer order details for context
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
        has_shortfall = False

        # Pre-compute cumulative received per requirementKey for this PO,
        # so we can enforce the 5% over-receipt cap server-side. Sum of all
        # live (non-CANCELLED) GRN rows for this poToken + requirementKey.
        def _prior_received_for(po, req_key):
            total = 0.0
            for e in all_entries:
                if (e.activity_type == 'GRN'
                    and e.buyer_order_id == buyer_order_id
                    and (e.status or '').upper() != 'CANCELLED'
                    and (e.extra_data or {}).get('poToken') == po
                    and (e.extra_data or {}).get('requirementKey') == req_key):
                    total += float(e.qty or 0)
            return total

        # Per-PO total cap: sum of ALL line received must not exceed sum of
        # ALL line ordered * 1.05. Track running totals across this request too.
        po_cap_multiplier = 1.05
        total_ordered_po = float(sum(float(it.get('orderedQty', 0) or 0) for it in items))
        total_prior_received_po = 0.0
        # Reuse the same helper per line, but the PO-level total also counts
        # lines from other requirement keys on this PO.
        _seen_req_keys = set()
        for _it in items:
            _rk = _it.get('requirementKey') or ''
            if _rk and _rk not in _seen_req_keys:
                _seen_req_keys.add(_rk)
                total_prior_received_po += _prior_received_for(po_token, _rk)

        incoming_total = 0.0

        for item in items:
            received_qty = float(item.get('receivedQty', 0))
            ordered_qty = float(item.get('orderedQty', 0))
            shortage_qty = float(item.get('shortageQty', 0))

            if received_qty <= settings.tolerance:
                # Skip zero-qty rows but note shortfall if applicable
                if ordered_qty > settings.tolerance:
                    has_shortfall = True
                continue

            # 5% over-receipt cap — per line item
            req_key_for_cap = item.get('requirementKey', '') or ''
            if ordered_qty > settings.tolerance:
                prior_line = _prior_received_for(po_token, req_key_for_cap)
                line_cap = ordered_qty * po_cap_multiplier
                if prior_line + received_qty > line_cap + settings.tolerance:
                    return {
                        'success': False,
                        'message': (
                            f"Over-receipt for {item.get('itemName', 'item')}: "
                            f"already received {prior_line:.2f}, adding {received_qty:.2f} "
                            f"would exceed cap {line_cap:.2f} (Ordered {ordered_qty:.2f} × 1.05)."
                        )
                    }

            # 5% over-receipt cap — PO total (all lines combined)
            incoming_total += received_qty
            if total_ordered_po > settings.tolerance:
                po_cap = total_ordered_po * po_cap_multiplier
                if total_prior_received_po + incoming_total > po_cap + settings.tolerance:
                    return {
                        'success': False,
                        'message': (
                            f"Over-receipt for PO {po_token}: "
                            f"already received {total_prior_received_po:.2f}, this request adds "
                            f"{incoming_total:.2f}, exceeding PO cap {po_cap:.2f} "
                            f"(Ordered total {total_ordered_po:.2f} × 1.05)."
                        )
                    }

            requirement_key = item.get('requirementKey', '')
            if not requirement_key:
                requirement_key = crud.get_requirement_key(
                    f"{buyer_order_id}|{item.get('itemName', '')}",
                    item.get('garmentSize', 'ALL'),
                    item.get('color', ''),
                    item.get('itemSize', ''),
                    item.get('itemNo', '')
                )

            # Resolve fg_key from the MATERIAL_REQUIREMENT row whose
            # requirementKey matches. requirementKey is unique per
            # (FG, size, color, item), so this cannot collapse two FGs that
            # share a PO line (the old poToken+itemNo+garmentSize match did,
            # because it broke on the first hit regardless of FG).
            fg_key_for_req = ''
            if requirement_key:
                for e in all_entries:
                    if (e.activity_type == 'MATERIAL_REQUIREMENT'
                        and e.extra_data
                        and e.extra_data.get('requirementKey') == requirement_key):
                        fg_key_for_req = e.fg_key or ''
                        break
            # Fallback: RM_ORDER match, but only if it does not collide across FGs.
            if not fg_key_for_req:
                for e in all_entries:
                    if (e.activity_type == 'RM_ORDER'
                        and e.extra_data
                        and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token
                        and crud.clean_key_exact(e.extra_data.get('itemNo', '')) == crud.clean_key_exact(item.get('itemNo', ''))
                        and crud.clean_key_exact(e.size or '') == crud.clean_key_exact(item.get('garmentSize', 'ALL'))):
                        fg_key_for_req = e.fg_key or ''
                        break
            
            # Supersede any prior non-CANCELLED GRN row for the same
            # (buyer_order_id, poToken, invoiceNo, requirementKey) before insert.
            prior_grn = [e for e in all_entries
                         if e.activity_type == 'GRN'
                         and e.buyer_order_id == buyer_order_id
                         and e.status != 'CANCELLED'
                         and (e.extra_data or {}).get('poToken') == po_token
                         and (e.extra_data or {}).get('invoiceNo') == invoice_no
                         and (e.extra_data or {}).get('requirementKey') == requirement_key]
            for old_grn in prior_grn:
                entries_to_insert.append({
                    'fg_key': old_grn.fg_key,
                    'buyer_order_id': buyer_order_id,
                    'activity_type': 'GRN',
                    'status': 'CANCELLED',
                    'buyer_name': old_grn.buyer_name,
                    'buyer_order_no': old_grn.buyer_order_no,
                    'order_date': old_grn.order_date,
                    'created_date': old_grn.created_date,
                    'qty': old_grn.qty,
                    'size': old_grn.size,
                    'color': old_grn.color,
                    'workflow_position': old_grn.workflow_position,
                    'version': old_grn.version or 1,
                    'extra_data': {
                        **(old_grn.extra_data or {}),
                        'cancelledAt': datetime.utcnow().isoformat(),
                        'cancelledReason': 'Superseded by new GRN receive',
                        'supersededBy': 'receive_po'
                    }
                })
            
            # Supersede prior MR rows (ORDERED/RECEIVED) for the same key
            prior_mr = [e for e in all_entries
                        if e.activity_type == 'MATERIAL_REQUIREMENT'
                        and e.buyer_order_id == buyer_order_id
                        and e.status != 'CANCELLED'
                        and (e.extra_data or {}).get('requirementKey') == requirement_key]
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
                    'workflow_position': old_mr.workflow_position,
                    'version': old_mr.version or 1,
                    'extra_data': {
                        **(old_mr.extra_data or {}),
                        'cancelledAt': datetime.utcnow().isoformat(),
                        'cancelledReason': 'Superseded by GRN receive',
                        'supersededBy': 'receive_po'
                    }
                })
                # Also write the new RECEIVED row for this MR key
                entries_to_insert.append({
                    'fg_key': old_mr.fg_key,
                    'buyer_order_id': buyer_order_id,
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'RECEIVED',
                    'buyer_name': old_mr.buyer_name,
                    'buyer_order_no': old_mr.buyer_order_no,
                    'order_date': old_mr.order_date,
                    'created_date': old_mr.created_date,
                    'qty': old_mr.qty,
                    'size': old_mr.size,
                    'color': old_mr.color,
                    'workflow_position': 1.5,
                    'version': ledger_version,
                    'extra_data': {
                        **(old_mr.extra_data or {}),
                        'grnReceivedAt': datetime.utcnow().isoformat(),
                        'poToken': po_token,
                        'receivedQty': received_qty
                    }
                })
            
            # Write GRN entry with RECEIVED status
            entries_to_insert.append({
                'fg_key': fg_key_for_req,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'GRN',
                'status': 'RECEIVED' if is_final else 'PARTIAL',
                'buyer_name': buyer_name,
                'buyer_order_no': buyer_order_no,
                'order_date': order_date,
                'created_date': created_date,
                'qty': received_qty,
                'size': item.get('garmentSize', 'ALL'),
                'color': item.get('color', ''),
                'workflow_position': 3,
                'version': ledger_version,
                'extra_data': {
                    'poToken': po_token,
                    'invoiceNo': invoice_no,
                    'receivedDate': received_date,
                    'supplier': supplier,
                    'itemNo': item.get('itemNo', ''),
                    'itemName': item.get('itemName', ''),
                    'itemSize': item.get('itemSize', ''),
                    'garmentSize': item.get('garmentSize', 'ALL'),
                    'color': item.get('color', ''),
                    'hsn': item.get('hsn', ''),
                    'uom': item.get('uom', 'PCS'),
                    'rate': item.get('rate', 0),
                    'orderedQty': ordered_qty,
                    'receivedQty': received_qty,
                    'shortageQty': shortage_qty,
                    'requirementKey': requirement_key,
                    'receivedAt': datetime.utcnow().isoformat()
                }
            })

            # Update inventory snapshot with grnDelta
            snapshot_updates.append({
                'requirementKey': requirement_key,
                'buyerOrderId': buyer_order_id,
                'fgKey': fg_key_for_req or '',
                'itemNo': item.get('itemNo', ''),
                'itemName': item.get('itemName', ''),
                'size': item.get('garmentSize', 'ALL'),
                'color': item.get('color', ''),
                'supplier': supplier,
                'requiredDelta': 0,
                'grnDelta': received_qty,
                'issueDelta': 0
            })

            if shortage_qty > settings.tolerance:
                has_shortfall = True

        if not entries_to_insert:
            return {'success': False, 'message': 'No received quantities entered'}

        crud.add_ledger_entries_bulk(db, entries_to_insert)
        if snapshot_updates:
            crud.update_inventory_snapshot(db, snapshot_updates)

        # =============================================================
        # Auto-move to INTERNAL_FG_ORDER when ALL POs are RECEIVED
        # Only triggered on is_final = True (Receive & Close)
        # =============================================================
        move_result = None
        if is_final:
            # Refresh entries to include the ones we just inserted
            all_entries_after = crud.get_ledger_entries(db)
            
            # Get all POs for this buyer order (RM_ORDER entries with poToken)
            po_tokens_for_order = set()
            for e in all_entries_after:
                if (e.activity_type == 'RM_ORDER' 
                    and e.buyer_order_id == buyer_order_id
                    and e.status in ['PROCESSED', 'PARTIAL', 'COMPLETED']
                    and e.extra_data 
                    and e.extra_data.get('poToken')):
                    po_tokens_for_order.add(e.extra_data.get('poToken'))
            
            # Get all POs that have been RECEIVED (from GRN entries)
            received_po_tokens = set()
            for e in all_entries_after:
                if (e.activity_type == 'GRN' 
                    and e.buyer_order_id == buyer_order_id
                    and e.status == 'RECEIVED'
                    and e.extra_data 
                    and e.extra_data.get('poToken')):
                    received_po_tokens.add(e.extra_data.get('poToken'))
            
            # Check if all POs are received
            all_received = (po_tokens_for_order 
                           and po_tokens_for_order.issubset(received_po_tokens))
            
            if all_received:
                token_state = crud.get_token_state(db, buyer_order_id)
                if token_state and token_state["current_stage"] == "GRN":
                    if crud.can_move_forward(db, buyer_order_id):
                        move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
                        logging.info(f"All POs RECEIVED. Token moved GRN -> INTERNAL_FG_ORDER for {buyer_order_id}")

        action = 'closed and marked RECEIVED' if is_final else 'partially inwarded'
        response = {
            'success': True,
            'message': f'PO {po_token} {action}.' + (' Shortfall detected.' if has_shortfall else ''),
            'poToken': po_token,
            'hasShortfall': has_shortfall,
            'isFinal': is_final,
            'itemCount': len(entries_to_insert),
            'snapshotUpdates': len(snapshot_updates)
        }
        if move_result:
            response['allPOsReceived'] = True
            response['newStage'] = move_result['new_stage']
            response['newVersion'] = move_result['new_version']
            response['message'] = f'PO {po_token} closed. All POs RECEIVED. Buyer order moved to Internal FG Order.'
        
        return response

    except Exception as e:
        logging.error(f"GRN receive error: {str(e)}")
        return {'success': False, 'message': str(e)}

@router.post("/close-po")
def close_po(data: Dict, db: Session = Depends(get_db)):
    """
    Close a PO's GRN without adding new quantity.

    Gate: every line item (by requirementKey) must have cumulative received
    qty >= 80% of its ordered qty. Otherwise reject.

    On success:
      - Flip the PO's live GRN rows to status RECEIVED (in place supersede
        via add_ledger_entries_bulk — same version stamping as everywhere).
      - Write MATERIAL_REQUIREMENT PENDING shortfall rows for any line that
        still has balance after the flip.
      - If ALL POs of the buyer order are now RECEIVED, move the token
        GRN -> INTERNAL_FG_ORDER.
    """
    try:
        po_token = crud.clean_key_exact(data.get('po_token', ''))
        if not po_token:
            return {'success': False, 'message': 'PO Token is required'}

        all_entries = crud.get_ledger_entries(db)

        # Resolve the buyer order for this PO
        rm_order_entry = next((e for e in all_entries
                               if e.activity_type == 'RM_ORDER'
                               and e.extra_data
                               and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token), None)
        if not rm_order_entry:
            return {'success': False, 'message': f'No RM_ORDER rows found for PO {po_token}'}
        buyer_order_id = rm_order_entry.buyer_order_id

        # Live GRN rows for this PO
        live_grns = crud.get_live_ledger_entries(
            db, activity_type='GRN', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: (e.extra_data or {}).get('poToken') == po_token
        )
        if not live_grns:
            return {'success': False, 'message': 'PO has no GRN rows yet. Receive something before closing.'}

        # Ordered qty per requirementKey, from LIVE RM_ORDER rows for this PO.
        # Using get_live_ledger_entries (not raw get_ledger_entries) so that
        # superseded/CANCELLED rows for the same logical key are excluded and
        # ordered qty is not double-counted.
        live_rm_rows = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: crud.clean_key_exact((e.extra_data or {}).get('poToken', '')) == po_token
        )
        ordered_by_req = {}
        for e in live_rm_rows:
            rk = (e.extra_data or {}).get('requirementKey') or ''
            if rk:
                ordered_by_req[rk] = ordered_by_req.get(rk, 0.0) + float(e.qty or 0)

        # Cumulative received per requirementKey across the live GRN rows
        received_by_req = {}
        for g in live_grns:
            ed = g.extra_data or {}
            rk = ed.get('requirementKey') or ''
            if rk:
                received_by_req[rk] = received_by_req.get(rk, 0.0) + float(g.qty or 0)

        # 80% gate — every line must be >= 80% of ordered
        shortfall_lines = []
        for rk, ordered_qty in ordered_by_req.items():
            if ordered_qty <= settings.tolerance:
                continue
            received_qty = received_by_req.get(rk, 0.0)
            if received_qty < ordered_qty * 0.80 - settings.tolerance:
                pct = (received_qty / ordered_qty * 100.0) if ordered_qty else 0.0
                shortfall_lines.append({
                    'requirementKey': rk,
                    'orderedQty': ordered_qty,
                    'receivedQty': received_qty,
                    'receivedPct': round(pct, 2)
                })

        if shortfall_lines:
            bad = ', '.join(f"{x['requirementKey']} ({x['receivedPct']}%)" for x in shortfall_lines)
            return {
                'success': False,
                'message': f'Cannot close PO: every line must be at least 80% received. Below threshold: {bad}',
                'belowThreshold': shortfall_lines
            }

        # Token version stamp for new rows
        token = db.query(models.WorkflowToken).filter(
            models.WorkflowToken.buyer_order_id == buyer_order_id
        ).first()
        ledger_version = token.current_version if token else 1

        # Buyer context
        bo_entry = next((e for e in all_entries
                         if e.buyer_order_id == buyer_order_id
                         and e.activity_type == 'BUYER_ORDER'
                         and e.status == 'COMPLETED'), None)
        buyer_name = bo_entry.buyer_name if bo_entry else ''
        buyer_order_no = bo_entry.buyer_order_no if bo_entry else ''
        order_date = bo_entry.order_date if bo_entry else None
        created_date = bo_entry.created_date if bo_entry else None

        entries_to_insert = []
        snapshot_updates = []
        now_ts = datetime.utcnow()

        # Flip each live GRN row to RECEIVED. Shortfall is computed ONCE per
        # requirementKey from the aggregate (received_by_req), not per GRN row,
        # so multiple partial rows for the same reqKey do not each emit a
        # bogus shortfall.
        seen_shortfall = set()
        for g in live_grns:
            ed = g.extra_data or {}
            rk = ed.get('requirementKey') or ''
            received_qty = float(g.qty or 0)

            # New RECEIVED row (supersedes PARTIAL in place via bulk writer)
            entries_to_insert.append({
                'fg_key': g.fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'GRN',
                'status': 'RECEIVED',
                'buyer_name': g.buyer_name or buyer_name,
                'buyer_order_no': g.buyer_order_no or buyer_order_no,
                'order_date': g.order_date or order_date,
                'created_date': g.created_date or created_date,
                'qty': received_qty,
                'size': g.size,
                'color': g.color,
                'workflow_position': 3,
                'version': ledger_version,
                'extra_data': {
                    **ed,
                    'closedAt': now_ts.isoformat(),
                    'closedBy': 'close_po'
                }
            })

            # Shortfall MR PENDING row — once per reqKey, computed against the
            # aggregate received qty for that reqKey.
            if rk and rk not in seen_shortfall:
                seen_shortfall.add(rk)
                ordered_qty = ordered_by_req.get(rk, 0.0)
                total_received = received_by_req.get(rk, 0.0)
                remaining = max(0.0, ordered_qty - total_received)
                if remaining > settings.tolerance:
                    entries_to_insert.append({
                        'fg_key': g.fg_key,
                        'buyer_order_id': buyer_order_id,
                        'activity_type': 'MATERIAL_REQUIREMENT',
                        'status': 'PENDING',
                        'buyer_name': g.buyer_name or buyer_name,
                        'buyer_order_no': g.buyer_order_no or buyer_order_no,
                        'order_date': g.order_date or order_date,
                        'created_date': g.created_date or created_date,
                        'qty': remaining,
                        'size': g.size,
                        'color': g.color,
                        'workflow_position': 1.5,
                        'version': ledger_version,
                        'extra_data': {
                            **ed,
                            'shortfallFrom': po_token,
                            'requirementKey': rk,
                            'closedShort': True,
                            'closedAt': now_ts.isoformat()
                        }
                    })

                    snapshot_updates.append({
                        'requirementKey': rk,
                        'buyerOrderId': buyer_order_id,
                        'fgKey': g.fg_key,
                        'itemNo': ed.get('itemNo', ''),
                        'itemName': ed.get('itemName', ''),
                        'size': g.size or 'ALL',
                        'color': g.color or '',
                        'supplier': ed.get('supplier', ''),
                        'requiredDelta': remaining,
                        'grnDelta': 0,
                        'issueDelta': 0
                    })

        if entries_to_insert:
            crud.add_ledger_entries_bulk(db, entries_to_insert)
        if snapshot_updates:
            crud.update_inventory_snapshot(db, snapshot_updates)

        # =============================================================
        # Auto-move to INTERNAL_FG_ORDER when ALL POs are RECEIVED
        # =============================================================
        move_result = None
        all_entries_after = crud.get_ledger_entries(db)

        po_tokens_for_order = set()
        for e in all_entries_after:
            if (e.activity_type == 'RM_ORDER'
                and e.buyer_order_id == buyer_order_id
                and e.status in ['PROCESSED', 'PARTIAL', 'COMPLETED']
                and e.extra_data
                and e.extra_data.get('poToken')):
                po_tokens_for_order.add(e.extra_data.get('poToken'))

        received_po_tokens = set()
        for e in all_entries_after:
            if (e.activity_type == 'GRN'
                and e.buyer_order_id == buyer_order_id
                and e.status == 'RECEIVED'
                and e.extra_data
                and e.extra_data.get('poToken')):
                received_po_tokens.add(e.extra_data.get('poToken'))

        all_received = bool(po_tokens_for_order) and po_tokens_for_order.issubset(received_po_tokens)

        if all_received:
            token_state = crud.get_token_state(db, buyer_order_id)
            if token_state and token_state['current_stage'] == 'GRN':
                if crud.can_move_forward(db, buyer_order_id):
                    move_result = crud.move_stage(db, buyer_order_id, 'forward', 'system')
                    logging.info(f"All POs RECEIVED (close-po). Token moved GRN -> INTERNAL_FG_ORDER for {buyer_order_id}")

        response = {
            'success': True,
            'message': f'PO {po_token} closed as RECEIVED.',
            'poToken': po_token,
            'shortfallCount': len(snapshot_updates),
        }
        if move_result:
            response['allPOsReceived'] = True
            response['newStage'] = move_result['new_stage']
            response['newVersion'] = move_result['new_version']
            response['message'] = f'PO {po_token} closed. All POs RECEIVED. Buyer order moved to Internal FG Order.'
        return response

    except Exception as e:
        logging.error(f"close_po error: {str(e)}")
        return {'success': False, 'message': str(e)}


@router.post("/cancel")
def cancel_grn(data: Dict, db: Session = Depends(get_db)):
    """
    Cancel GRN for a PO. Behavior:
      - Reverse grnDelta on inventory snapshot.
      - Revert MATERIAL_REQUIREMENT RECEIVED -> ORDERED for affected keys.
      - Move the buyer-order token backward GRN -> RM_ORDER.
      - Supersede every live RM_ORDER PO of the buyer order, so the
        "No of POs Made" counter resets to 0 and all suppliers come back
        into the RM Order process modal.
      - Clear the InspectionRecord status for those POs so a re-order can
        re-inspect cleanly.
    """
    try:
        po_token = crud.clean_key_exact(data.get('po_token', ''))
        invoice_no = crud.clean_key_exact(data.get('invoice_no', ''))
        return_doc_no = (data.get('return_doc_no') or '').strip()
        cancel_reason = (data.get('cancel_reason') or '').strip()

        if not po_token:
            raise ValueError('PO Token is required')

        all_entries = crud.get_ledger_entries(db)
        grn_entries = [e for e in all_entries if e.activity_type == 'GRN'
                       and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token
                       and e.status != 'CANCELLED']

        if invoice_no:
            grn_entries = [e for e in grn_entries if crud.clean_key_exact(e.extra_data.get('invoiceNo', '')) == invoice_no]

        if not grn_entries:
            raise ValueError(f'No active GRN found for PO: {po_token}')

        # Resolve buyer_order_id up front.
        buyer_order_id = None
        for grn in grn_entries:
            if grn.buyer_order_id:
                buyer_order_id = grn.buyer_order_id
                break
        if not buyer_order_id:
            raise ValueError('Could not resolve buyer_order_id for this GRN')

        # ---- Move token FIRST: GRN -> RM_ORDER ----------------------------
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            raise ValueError('No workflow token found')
        if token_state["current_stage"] != "GRN":
            return {
                'success': False,
                'message': f'Cannot cancel GRN from stage: {token_state["current_stage"]}'
            }
        if not crud.can_move_backward(db, buyer_order_id):
            raise ValueError('Cannot move backward from GRN')

        move_result = crud.move_stage(db, buyer_order_id, "backward", "system")
        new_version = move_result["new_version"]
        logging.info(f"GRN cancelled: token moved GRN -> RM_ORDER for {buyer_order_id}")

        # ---- Reverse GRN effects on snapshot & MATERIAL_REQUIREMENT -------
        entries_to_insert = []
        snapshot_updates = []
        affected_req_keys = set()
        now = datetime.utcnow()

        for grn in grn_entries:
            ed = grn.extra_data or {}
            nested_items = ed.get('items') or []
            if nested_items:
                grn_items = nested_items
            elif ed.get('itemNo') or ed.get('receivedQty') is not None:
                grn_items = [{
                    'itemNo': ed.get('itemNo', ''),
                    'itemName': ed.get('itemName', ''),
                    'garmentSize': ed.get('garmentSize') or grn.size or 'ALL',
                    'itemSize': ed.get('itemSize', ''),
                    'color': ed.get('color') or grn.color or '',
                    'supplier': ed.get('supplier', ''),
                    'receivedQty': float(ed.get('receivedQty', 0) or 0),
                    'orderedQty': float(ed.get('orderedQty', 0) or 0),
                    'requirementKey': ed.get('requirementKey', ''),
                }]
            else:
                grn_items = []

            for grn_item in grn_items:
                received_qty = grn_item.get('receivedQty', 0)
                if received_qty <= settings.tolerance:
                    continue

                req_key = grn_item.get('requirementKey', '')
                if req_key:
                    affected_req_keys.add(req_key)

                # Idempotency guard: if this exact (receive row, line) has
                # already been reversed by an earlier cancel, skip. The
                # reversal is keyed on reverseOfLedgerId + reverseOfLineKey,
                # so re-running cancel on the same receive is a no-op and
                # cannot double-subtract from the snapshot.
                line_key = f"{grn_item.get('itemNo','')}|{grn_item.get('garmentSize','ALL')}|{req_key}"
                already_reversed = False
                for e in all_entries:
                    if (e.activity_type == 'GRN'
                        and e.status == 'CANCELLED'
                        and e.extra_data
                        and e.extra_data.get('reverseOfLedgerId') == grn.id
                        and e.extra_data.get('reverseOfLineKey') == line_key):
                        already_reversed = True
                        break
                if already_reversed:
                    logging.info(f"GRN reversal already exists for ledger {grn.id} line {line_key}; skipping")
                    continue

                entries_to_insert.append({
                    'fg_key': grn.fg_key,
                    'buyer_order_id': buyer_order_id,
                    'activity_type': 'GRN',
                    'status': 'CANCELLED',
                    'buyer_name': grn.buyer_name,
                    'buyer_order_no': grn.buyer_order_no,
                    'order_date': grn.order_date,
                    'created_date': grn.created_date,
                    'qty': -received_qty,
                    'size': grn_item.get('garmentSize', 'ALL'),
                    'color': grn_item.get('color', ''),
                    'workflow_position': 3,
                    'version': new_version,
                    'extra_data': {
                        'poToken': po_token,
                        'invoiceNo': invoice_no or ed.get('invoiceNo', ''),
                        'requirementKey': req_key,
                        'cancelledAt': now.isoformat(),
                        'cancelledFrom': grn.timestamp.isoformat() if grn.timestamp else None,
                        'originalItems': grn_items,
                        'reversal': True,
                        'reason': 'GRN Cancellation',
                        'returnDocNo': return_doc_no,
                        'cancelReason': cancel_reason,
                        'reverseOfLedgerId': grn.id,
                        'reverseOfLineKey': line_key
                    }
                })

                snapshot_updates.append({
                    'requirementKey': req_key,
                    'fgKey': grn.fg_key,
                    'itemNo': grn_item.get('itemNo', ''),
                    'itemName': grn_item.get('itemName', ''),
                    'size': grn_item.get('garmentSize', 'ALL'),
                    'color': grn_item.get('color', ''),
                    'supplier': grn_item.get('supplier', ''),
                    'requiredDelta': 0,
                    'grnDelta': -received_qty,
                    'issueDelta': 0
                })

        # Revert MATERIAL_REQUIREMENT RECEIVED -> ORDERED
        for req_key in affected_req_keys:
            received_lines = [e for e in all_entries
                              if e.activity_type == 'MATERIAL_REQUIREMENT'
                              and e.status == 'RECEIVED'
                              and e.extra_data
                              and e.extra_data.get('requirementKey') == req_key]
            for rl in received_lines:
                meta = dict(rl.extra_data or {})
                meta['grnCancelledAt'] = now.isoformat()
                meta['revertedToStatus'] = 'ORDERED'
                entries_to_insert.append({
                    'fg_key': rl.fg_key,
                    'buyer_order_id': buyer_order_id,
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'ORDERED',
                    'buyer_name': rl.buyer_name,
                    'buyer_order_no': rl.buyer_order_no,
                    'order_date': rl.order_date,
                    'created_date': rl.created_date,
                    'qty': rl.qty,
                    'size': rl.size,
                    'color': rl.color,
                    'workflow_position': 1.5,
                    'version': new_version,
                    'extra_data': meta
                })

        # ---- Supersede every live RM_ORDER PO of the buyer order ----------
        # The version bump in move_stage has already re-stamped live rows.
        # We now need to explicitly cancel every live PO so get_rm_orders
        # reports totalPOsMade = 0 and the RM Order process modal shows all
        # suppliers again.
        live_pos = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
        )
        cancelled_po_tokens = set()
        for live_po in live_pos:
            pt = (live_po.extra_data or {}).get('poToken')
            if pt:
                cancelled_po_tokens.add(pt)
            ed = dict(live_po.extra_data or {})
            entries_to_insert.append({
                'fg_key': live_po.fg_key or '',
                'buyer_order_id': buyer_order_id,
                'activity_type': 'RM_ORDER',
                'status': 'CANCELLED',
                'buyer_name': live_po.buyer_name,
                'buyer_order_no': live_po.buyer_order_no,
                'order_date': live_po.order_date,
                'created_date': live_po.created_date,
                'qty': live_po.qty,
                'size': live_po.size,
                'color': live_po.color,
                'workflow_position': live_po.workflow_position,
                'version': new_version,
                'extra_data': {
                    **ed,
                    'cancelledAt': now.isoformat(),
                    'cancelledReason': 'GRN cancelled — PO undone',
                    'supersededBy': 'cancel_grn',
                    'from_stage': move_result['previous_stage'],
                    'to_stage': move_result['new_stage']
                }
            })

        # ---- Clear InspectionRecords for those POs ------------------------
        if cancelled_po_tokens:
            insp_to_reset = db.query(models.InspectionRecord).filter(
                models.InspectionRecord.inspection_type == 'RAW_MATERIAL',
                models.InspectionRecord.reference.in_(list(cancelled_po_tokens))
            ).all()
            for insp in insp_to_reset:
                insp.status = 'CANCELLED'
            db.commit()

        # ---- Persist ledger + snapshot changes ---------------------------
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)

        return {
            'success': True,
            'message': f'GRN cancelled. {len(affected_req_keys)} requirement line(s) reverted. '
                       f'{len(cancelled_po_tokens)} PO(s) undone. Buyer order moved back to RM Order.',
            'newStage': move_result["new_stage"],
            'newVersion': new_version,
            'cancelledCount': len(grn_entries),
            'reversedItems': len(snapshot_updates),
            'revertedRequirements': len(affected_req_keys),
            'cancelledPOs': list(cancelled_po_tokens),
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

@router.post("/cancel-buyer-order")
def cancel_grn_buyer_order(data: Dict, db: Session = Depends(get_db)):
    """
    Pre-receive exit for a buyer order in GRN stage.

    Allowed ONLY when no PO of this buyer order has any live GRN yet.
    If even one PO has been GRNed, this cancel is blocked — the user must
    cancel that specific GRN instead (which requires Return Doc No + reason).

    On success: move token GRN -> RM_ORDER and rewind every live RM_ORDER PO
    for this buyer order (status -> CANCELLED), plus cancel the corresponding
    RM_INSPECTION records so the POs can be re-issued. No stock reversal —
    nothing was received yet.
    """
    try:
        buyer_order_id = crud.clean_key_exact(data.get('buyer_order_id', ''))
        if not buyer_order_id:
            return {'success': False, 'message': 'Buyer Order ID is required'}

        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {'success': False, 'message': 'No workflow token found for this order'}
        if token_state['current_stage'] != 'GRN':
            return {'success': False,
                    'message': f"Cannot cancel from stage: {token_state['current_stage']}. Order is not in GRN."}
        if not crud.move_stage:
            return {'success': False, 'message': 'Workflow helpers unavailable'}

        # Gate: NO live GRN row may exist for this buyer order.
        live_grns = crud.get_live_ledger_entries(
            db, activity_type='GRN', buyer_order_id=buyer_order_id
        )
        if live_grns:
            return {
                'success': False,
                'message': 'Cannot cancel at buyer-order level: one or more POs have already been GRNed. '
                           'Cancel the individual GRN instead.'
            }

        if not crud.can_move_backward(db, buyer_order_id):
            return {'success': False, 'message': 'Cannot move backward from GRN'}

        move_result = crud.move_stage(db, buyer_order_id, 'backward', 'system')
        new_version = move_result['new_version']

        # Log a CANCELLED GRN summary row for traceability (no reversal).
        all_entries = crud.get_ledger_entries(db)
        bo = next((e for e in all_entries
                   if e.buyer_order_id == buyer_order_id
                   and e.activity_type == 'BUYER_ORDER'
                   and e.status == 'COMPLETED'), None)
        now = datetime.utcnow()
        crud.add_ledger_entry(db, {
            'fg_key': '',
            'buyer_order_id': buyer_order_id,
            'activity_type': 'GRN',
            'status': 'CANCELLED',
            'buyer_name': bo.buyer_name if bo else '',
            'buyer_order_no': bo.buyer_order_no if bo else '',
            'order_date': bo.order_date if bo else None,
            'created_date': now,
            'qty': 0,
            'workflow_position': 3,
            'version': new_version,
            'extra_data': {
                'cancelledAt': now.isoformat(),
                'cancelledReason': 'Buyer order cancelled at GRN stage (no POs received)',
                'supersededBy': 'cancel_grn_buyer_order',
                'version': new_version,
                'previous_version': move_result['previous_version'],
                'stage_movement': 'backward',
                'from_stage': move_result['previous_stage'],
                'to_stage': move_result['new_stage']
            }
        })

        # Rewind the RM_ORDER POs for this buyer order so "No of POs Made"
        # resets to 0 and the RM Order table shows nothing done. Nothing was
        # received yet, so there is no stock to reverse here — stock is only
        # touched when the token moves GRN -> INTERNAL_FG_ORDER.
        live_pos = crud.get_live_ledger_entries(
            db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
            extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
        )
        cancelled_po_tokens = set()
        entries_to_insert = []
        for live_po in live_pos:
            pt = (live_po.extra_data or {}).get('poToken')
            if pt:
                cancelled_po_tokens.add(pt)
            ed = dict(live_po.extra_data or {})
            entries_to_insert.append({
                'fg_key': live_po.fg_key or '',
                'buyer_order_id': buyer_order_id,
                'activity_type': 'RM_ORDER',
                'status': 'CANCELLED',
                'buyer_name': live_po.buyer_name,
                'buyer_order_no': live_po.buyer_order_no,
                'order_date': live_po.order_date,
                'created_date': live_po.created_date,
                'qty': live_po.qty,
                'size': live_po.size,
                'color': live_po.color,
                'workflow_position': live_po.workflow_position,
                'version': new_version,
                'extra_data': {
                    **ed,
                    'cancelledAt': now.isoformat(),
                    'cancelledReason': 'GRN buyer-order cancel rewound POs',
                    'supersededBy': 'cancel_grn_buyer_order'
                }
            })

        # Cancel the corresponding RM_INSPECTION records so the POs come back
        # for re-issuing cleanly (same as cancel_grn does for a single PO).
        if cancelled_po_tokens:
            insp_to_reset = db.query(models.InspectionRecord).filter(
                models.InspectionRecord.inspection_type == 'RAW_MATERIAL',
                models.InspectionRecord.reference.in_(list(cancelled_po_tokens))
            ).all()
            for insp in insp_to_reset:
                insp.status = 'CANCELLED'
            db.commit()

        if entries_to_insert:
            crud.add_ledger_entries_bulk(db, entries_to_insert)

        return {
            'success': True,
            'message': f'Buyer order cancelled at GRN stage (no POs were received). '
                       f'{len(cancelled_po_tokens)} PO(s) rewound. Moved back to RM Order.',
            'newStage': move_result['new_stage'],
            'newVersion': new_version,
            'cancelledPOs': list(cancelled_po_tokens)
        }
    except Exception as e:
        db.rollback()
        return {'success': False, 'message': str(e)}

