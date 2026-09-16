from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas, models
from ..database import get_db
from ..config import settings
from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/reports", tags=["Reports"])

@router.post("/data")
def get_report_data(data: Dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    report_type = data.get('reportType')
    filters = data.get('filters', {})
    
    if report_type == 'RM_STOCK':
        return get_rm_stock_report(db, filters)
    elif report_type == 'RM_ORDERED':
        return get_rm_ordered_report(db, filters)
    else:
        raise ValueError('Invalid report type')

def get_rm_stock_report(db: Session, filters: Dict):
    snapshot = crud.get_inventory_snapshot(db)

    # One lookup pass: live MATERIAL_REQUIREMENT rows by requirement_key, so we
    # can read per-FG consumption for the tooltip and for the FG breakdown.
    live_mrs = crud.get_live_ledger_entries(db, activity_type='MATERIAL_REQUIREMENT')
    mr_by_key = {}
    for m in live_mrs:
        rk = (m.extra_data or {}).get('requirementKey')
        if rk and rk not in mr_by_key:
            mr_by_key[rk] = m

    # Aggregate snapshot rows that describe the same purchased line.
    # Identity: (item_no, item_name, garment_size, color, supplier).
    agg = {}
    order = []

    for item in snapshot:
        stock = item.current_stock or 0

        if filters.get('supplier') and filters['supplier'] != 'ALL':
            if item.supplier != filters['supplier']:
                continue
        if filters.get('fgKey'):
            if filters['fgKey'].lower() not in (item.fg_key or '').lower():
                continue
        if filters.get('status') and filters['status'] != 'ALL':
            if filters['status'] == 'IN_STOCK' and stock <= settings.tolerance:
                continue
            if filters['status'] == 'OUT_OF_STOCK' and stock > settings.tolerance:
                continue
            if filters['status'] == 'LOW_STOCK' and (stock <= settings.tolerance or stock >= 10):
                continue
            if filters['status'] == 'ZERO_STOCK' and stock > settings.tolerance:
                continue

        agg_key = (
            item.item_no or '',
            item.item_name or '',
            item.garment_size or '',
            item.color or '',
            item.supplier or '',
        )

        if agg_key not in agg:
            agg[agg_key] = {
                'fgKey': item.fg_key or '—',
                'itemNo': item.item_no or '—',
                'itemName': item.item_name or '—',
                'garmentSize': item.garment_size or '—',
                'color': item.color or '—',
                'supplier': item.supplier or '—',
                'rate': 0,
                'uom': 'PCS',
                'grnReceived': 0,
                'issued': 0,
                'stock': 0,
                'required': 0,
                'lastGRN': None,
                'lastIssue': None,
                '_fgSeen': set(),
                'fgBreakdown': [],
            }
            order.append(agg_key)

        row = agg[agg_key]
        row['grnReceived'] += float(item.total_grn_received_qty or 0)
        row['issued']      += float(item.total_issued_qty or 0)
        row['stock']       += float(stock)
        row['required']    += float(item.total_required_qty or 0)

        # Per-FG breakdown for the tooltip. Only LIVE FGs (they are live by
        # construction, since the snapshot rows themselves are live).
        fg_key = item.fg_key or ''
        if fg_key and fg_key not in row['_fgSeen']:
            row['_fgSeen'].add(fg_key)
            parts = fg_key.split('|')
            design = parts[1] if len(parts) > 1 else ''
            color = parts[2] if len(parts) > 2 else ''
            mr = mr_by_key.get(item.requirement_key)
            consumption = 0
            buyer_name = ''
            buyer_order_no = ''
            if mr is not None:
                try:
                    consumption = float((mr.extra_data or {}).get('consumption', 0) or 0)
                except (TypeError, ValueError):
                    consumption = 0
                buyer_name = mr.buyer_name or ''
                buyer_order_no = mr.buyer_order_no or ''
            row['fgBreakdown'].append({
                'fgKey': fg_key,
                'design': design,
                'color': color,
                'consumption': consumption,
                'qty': float(item.total_required_qty or 0),
                'buyerName': buyer_name,
                'buyerOrderNo': buyer_order_no,
            })

    result = []
    for k in order:
        row = agg[k]
        row.pop('_fgSeen', None)
        row['fgCount'] = len(row['fgBreakdown'])
        # Sort breakdown by fg_key for a stable tooltip.
        row['fgBreakdown'].sort(key=lambda x: x['fgKey'])
        result.append(row)

    result.sort(key=lambda x: x['stock'])
    return result

def get_rm_ordered_report(db: Session, filters: Dict):
    # Live RM_ORDER rows only (latest per (buyer_order_id, poToken, requirementKey), CANCELLED excluded)
    live_rows = crud.get_live_ledger_entries(
        db, activity_type='RM_ORDER',
        extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
    )
    resolved_lines = {}
    for entry in live_rows:
        line_key = f"{entry.extra_data.get('poToken')}_{entry.extra_data.get('requirementKey', entry.fg_key)}"
        resolved_lines[line_key] = entry
    
    po_map = {}
    for line_key, entry in resolved_lines.items():
        if entry.status == 'CANCELLED':
            continue
        
        po_token = entry.extra_data.get('poToken')
        if not po_token:
            continue
        
        po_date = entry.created_date or entry.timestamp or entry.order_date
        if po_token not in po_map:
            po_map[po_token] = {
                'poToken': po_token or '—',
                'supplier': entry.extra_data.get('supplier') or entry.extra_data.get('supplierAlias') or '',
                'orderDate': po_date.isoformat() if po_date else '',
                'fgKeys': [],
                'items': [],
                'totalQty': 0,
                'totalAmount': 0,
                'status': entry.status or 'DRAFT'
            }
        
        fg_key = crud.clean_key_exact(entry.fg_key)
        if fg_key and fg_key not in po_map[po_token]['fgKeys']:
            po_map[po_token]['fgKeys'].append(fg_key)
        
        qty = float(entry.qty or 0)
        rate = float(entry.extra_data.get('rate', 0) or 0)
        
        po_map[po_token]['items'].append({
            'fgKey': fg_key or '—',
            'itemNo': entry.extra_data.get('itemNo', ''),
            'itemName': entry.extra_data.get('itemName', ''),
            'garmentSize': entry.size or 'ALL',
            'color': entry.color or '',
            'qty': qty,
            'rate': rate,
            'amount': qty * rate
        })
        
        po_map[po_token]['totalQty'] += qty
        po_map[po_token]['totalAmount'] += qty * rate
    
    result = []
    for po_token, po in po_map.items():
        if filters.get('supplier') and filters['supplier'] != 'ALL':
            if po['supplier'] != filters['supplier']:
                continue
        if filters.get('status') and filters['status'] != 'ALL':
            if po['status'] != filters['status']:
                continue
        if filters.get('dateFrom'):
            try:
                date_from = datetime.fromisoformat(filters['dateFrom'])
                order_date = datetime.fromisoformat(po['orderDate']) if po['orderDate'] else datetime(1970, 1, 1)
                if order_date < date_from:
                    continue
            except:
                pass
        if filters.get('dateTo'):
            try:
                date_to = datetime.fromisoformat(filters['dateTo'])
                order_date = datetime.fromisoformat(po['orderDate']) if po['orderDate'] else datetime(1970, 1, 1)
                if order_date > date_to:
                    continue
            except:
                pass
        
        result.append(po)
    
    result.sort(key=lambda x: x.get('orderDate') or '', reverse=True)
    return result

@router.get("/buyer-order-status")
def get_buyer_order_status(db: Session = Depends(get_db)):
    """Buyer Order Status report — all buyer orders with FGs, qty, current stage."""
    from decimal import Decimal
    from collections import defaultdict
    
    all_tokens = db.query(models.WorkflowToken).all()
    
    counters = {
        'totalBuyerOrders': 0,
        'buyerOrderQty': 0.0,
        'fgInventoryQty': 0.0,
        'dispatchedQty': 0.0,
        'balanceAfterDispatch': 0.0,
    }
    
    passed_all = db.query(models.FGInspectionRecord).filter(
        models.FGInspectionRecord.status == 'PASSED'
    ).order_by(models.FGInspectionRecord.id.desc()).all()
    latest_passed = {}
    for ins in passed_all:
        key = (ins.buyer_order_id, ins.fg_key)
        if key not in latest_passed:
            latest_passed[key] = ins
    counters['fgInventoryQty'] = sum(float(i.inspected_qty or 0) for i in latest_passed.values())
    
    dispatch_records = db.query(models.DispatchRecord).all()
    counters['dispatchedQty'] = sum(float(d.dispatch_qty or 0) for d in dispatch_records)
    
    fg_inv_all = db.query(models.FGInventory).all()
    counters['balanceAfterDispatch'] = sum(float(fi.quantity_ready or 0) for fi in fg_inv_all)
    
    result = []
    for token in all_tokens:
        if token.status != 'ACTIVE':
            continue
        
        buyer_order_id = token.buyer_order_id
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        if not buyer_order:
            continue
        
        if (buyer_order.status or '').upper() == 'CANCELLED':
            continue
        
        fg_entries = crud.get_live_ledger_entries(
            db, activity_type='BUYER_ORDER', buyer_order_id=buyer_order_id,
            latest_version_only=True,
            extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
        )
        
        fg_map = {}
        for e in fg_entries:
            if e.fg_key not in fg_map or e.id > fg_map[e.fg_key].id:
                fg_map[e.fg_key] = e
        
        fg_details = []
        total_qty = 0
        for fg_key, entry in fg_map.items():
            ed = entry.extra_data or {}
            design = ed.get('fgDesign', '')
            color = ed.get('fgColor', '')
            grid_row = ed.get('gridRow', [])
            sizes = ed.get('sizes', [])
            fg_qty = 0
            # gridRow layout: [serial, design, color, <sizes...>, buyer_name, buyer_order_no, order_date, created_date]
            # Last 4 cells are trailing metadata, not sizes. Bound the size
            # loop so we never call float() on a metadata string (e.g. 'UCB').
            size_end = max(0, len(grid_row) - 4)
            for i in range(len(sizes)):
                col_idx = 3 + i
                if col_idx < size_end:
                    fg_qty += float(grid_row[col_idx] or 0)
            fg_details.append({
                'fgKey': fg_key,
                'design': design,
                'color': color,
                'qty': fg_qty
            })
            total_qty += fg_qty
        
        has_dispatch = db.query(models.DispatchRecord).filter(
            models.DispatchRecord.buyer_order_id == buyer_order_id
        ).count() > 0

        result.append({
            'buyerOrderId': buyer_order_id,
            'buyer': buyer_order.buyer_name or 'Unknown',
            'buyerOrderNo': buyer_order.buyer_order_no or 'N/A',
            'orderDate': buyer_order.order_date,
            'fgCount': len(fg_map),
            'quantity': total_qty,
            'status': token.current_stage,
            'currentVersion': token.current_version,
            'fgDetails': fg_details,
            'dispatched': has_dispatch
        })
        
        counters['totalBuyerOrders'] += 1
        counters['buyerOrderQty'] += total_qty
    
    for k in counters:
        if k != 'totalBuyerOrders':
            counters[k] = round(counters[k], 2)
    
    return {
        'counters': counters,
        'orders': result
    }

@router.get("/filters")
def get_report_filters(db: Session = Depends(get_db)):
    suppliers = set()
    fg_keys = set()
    statuses = ['ALL', 'DRAFT', 'PROCESSED', 'COMPLETED', 'PARTIAL', 'CANCELLED', 'CLOSED']
    
    # Iterate live rows per activity type (dedup excludes cancelled superseded rows)
    for at in ('RM_ORDER', 'MATERIAL_REQUIREMENT', 'BUYER_ORDER', 'BOM', 'GRN'):
        live = crud.get_live_ledger_entries(db, activity_type=at)
        for entry in live:
            if entry.extra_data:
                if entry.extra_data.get('supplier'):
                    suppliers.add(entry.extra_data['supplier'])
                if entry.extra_data.get('supplierAlias'):
                    suppliers.add(entry.extra_data['supplierAlias'])
            fg_key = crud.clean_key_exact(entry.fg_key)
            if fg_key:
                fg_keys.add(fg_key)
    
    snapshot = crud.get_inventory_snapshot(db)
    for item in snapshot:
        if item.supplier:
            suppliers.add(item.supplier)
    
    return {
        'suppliers': sorted([s for s in suppliers if s]),
        'fgKeys': sorted([k for k in fg_keys if k]),
        'statuses': statuses
    }


# ==============================================================
# STAGE-SENSITIVE PRINT ENDPOINTS
# ==============================================================

from fastapi.responses import HTMLResponse

def _print_header(company, order_info, stage_label):
    return f"""
    <div class="header">
        <div class="company-name">{company['name']}</div>
        <div class="company-details">{company['address']}</div>
        <div class="company-details">GST: {company['gst']} | State: {company['state']}</div>
    </div>
    <div class="doc-title">{stage_label}</div>
    <div class="info-grid">
        <span><strong>Order ID:</strong> {order_info.get('orderId', '&mdash;')}</span>
        <span><strong>Order Date:</strong> {order_info.get('orderDate', '&mdash;')}</span>
        <span><strong>Buyer:</strong> {order_info.get('buyerName', '&mdash;')}</span>
        <span><strong>Buyer Order No:</strong> {order_info.get('buyerOrderNo', '&mdash;')}</span>
        <span><strong>Current Stage:</strong> {order_info.get('currentStage', '&mdash;')}</span>
        <span><strong>Version:</strong> {order_info.get('version', '&mdash;')}</span>
    </div>
    """

def _print_footer(company):
    return f"""
    <div class="footer">
        <p>This is a computer generated document. No signature required.</p>
        <p><strong>For {company['name']}</strong></p>
        <p class="brand-micro">Powered by Offices of Nawnit Nihal</p>
    </div>
    """

_PRINT_CSS = """
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:'Segoe UI',Arial,sans-serif; padding:24px; background:#f8f9fa; }
    .container { max-width:1100px; margin:0 auto; background:white; padding:30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.1); }
    .header { text-align:center; border-bottom:3px solid #2a6df4; padding-bottom:18px; margin-bottom:16px; }
    .company-name { font-size:24px; font-weight:700; color:#1a3a6a; }
    .company-details { font-size:12px; color:#555; }
    .doc-title { text-align:center; font-size:19px; font-weight:700; color:#1a3a6a; margin:14px 0; letter-spacing:1px; }
    .info-grid { display:grid; grid-template-columns:1fr 1fr; gap:6px; background:#f0f4fe; padding:12px 16px; border-radius:8px; margin:12px 0; font-size:13px; }
    table { width:100%; border-collapse:collapse; margin:12px 0; font-size:12px; }
    table th { background:#1a3a6a; color:white; padding:8px; text-align:left; }
    table td { padding:6px 8px; border-bottom:1px solid #e9edf4; }
    .fg-block { margin-top:18px; border:1px solid #e0e6f0; border-radius:8px; overflow:hidden; }
    .fg-block-head { background:#f0f4fe; padding:8px 14px; font-weight:600; color:#1a3a6a; font-size:13px; display:flex; justify-content:space-between; }
    .totals { text-align:right; margin-top:12px; font-size:13px; }
    .grand-total { font-size:16px; font-weight:700; color:#1a3a6a; }
    .footer { margin-top:30px; border-top:2px solid #e9edf4; padding-top:18px; text-align:center; font-size:12px; color:#666; }
    .brand-micro { font-size:9px; color:#bbb; margin-top:6px; letter-spacing:0.5px; }
    .no-print { display:inline-block; }
    @media print { body { padding:10px; background:white; } .container { box-shadow:none; padding:15px; } .no-print { display:none; } }
"""

def _print_wrapper(title, stage_label, company, order_info, body_html):
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{_PRINT_CSS}</style>
</head>
<body>
<div class="container">
    {_print_header(company, order_info, stage_label)}
    {body_html}
    <div style="margin-top:18px;" class="no-print">
        <button onclick="window.print()" style="padding:10px 24px; background:#2a6df4; color:white; border:none; border-radius:6px; cursor:pointer; font-size:14px;">Print</button>
    </div>
    {_print_footer(company)}
</div>
</body>
</html>"""

def _get_order_info(db, buyer_order_id):
    bo = db.query(models.BuyerOrder).filter(
        models.BuyerOrder.buyer_order_id == buyer_order_id
    ).first()
    token_state = crud.get_token_state(db, buyer_order_id)
    if not bo:
        return None
    return {
        'orderId': bo.buyer_order_id,
        'buyerName': bo.buyer_name or '&mdash;',
        'buyerOrderNo': bo.buyer_order_no or '&mdash;',
        'orderDate': bo.order_date.strftime('%d-%m-%Y') if bo.order_date else '&mdash;',
        'currentStage': token_state['current_stage'] if token_state else (bo.current_stage or '&mdash;'),
        'version': token_state['current_version'] if token_state else (bo.version or 1),
    }

def _company():
    return {
        'name': settings.company_name,
        'address': settings.company_address,
        'gst': settings.company_gst,
        'state': settings.company_state,
    }

@router.get("/print/BUYER_ORDER/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_buyer_order(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    order_entries = crud.get_live_ledger_entries(
        db, activity_type='BUYER_ORDER', buyer_order_id=buyer_order_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )

    sizes = settings.get_default_sizes_list()
    rows_html = ""
    total_qty = 0
    for entry in order_entries:
        if entry.extra_data and entry.extra_data.get('gridRow'):
            row = entry.extra_data['gridRow']
            design = row[1] if len(row) > 1 else ''
            color = row[2] if len(row) > 2 else ''
            if entry.extra_data.get('sizes'):
                sizes = entry.extra_data['sizes']
            # gridRow layout: [serial, design, color, <sizes...>, buyer_name, buyer_order_no, order_date, created_date]
            # Last 4 cells are trailing metadata, not sizes. Bound the size
            # loop so we never call float() on a metadata string (e.g. 'UCB').
            size_end = max(0, len(row) - 4)
            for i, size in enumerate(sizes):
                col_idx = 3 + i
                if col_idx < size_end:
                    qty = float(row[col_idx] or 0)
                    if qty > 0:
                        rows_html += f"<tr><td>{design}</td><td>{color}</td><td>{size}</td><td style='text-align:right;'>{int(round(qty))}</td></tr>"
                        total_qty += qty

    body = f"""
    <table>
        <thead><tr><th>Design</th><th>Color</th><th>Size</th><th style="text-align:right;">Quantity</th></tr></thead>
        <tbody>{rows_html or '<tr><td colspan="4" style="text-align:center;color:#888;">No order lines</td></tr>'}</tbody>
    </table>
    <div class="totals"><span class="grand-total">Total Quantity: {int(round(total_qty))}</span></div>
    """
    html = _print_wrapper(
        f"Buyer Order - {buyer_order_id}",
        "BUYER ORDER",
        _company(),
        order_info,
        body
    )
    return HTMLResponse(html)

@router.get("/print/BOM/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_bom(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    bom_entries = crud.get_live_ledger_entries(
        db, activity_type='BOM', buyer_order_id=buyer_order_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    fg_map = {}
    for e in bom_entries:
        if e.fg_key not in fg_map or e.id > fg_map[e.fg_key].id:
            fg_map[e.fg_key] = e

    if not fg_map:
        return HTMLResponse("<h1>No BOM found for this order</h1>", status_code=404)

    body = ""
    grand_total = 0.0
    for fg_key, entry in fg_map.items():
        parts = fg_key.split('|')
        design = parts[1] if len(parts) > 1 else '&mdash;'
        color = parts[2] if len(parts) > 2 else '&mdash;'
        items = (entry.extra_data or {}).get('items', []) or []
        fg_total = 0.0
        rows = ""
        for idx, it in enumerate(items, 1):
            consumption = float(it.get('consumption', 0) or 0)
            rate = float(it.get('rate', 0) or 0)
            cost = consumption * rate
            fg_total += cost
            rows += f"""<tr>
                <td>{idx}</td>
                <td>{it.get('item_no', '&mdash;')}</td>
                <td>{it.get('item_name', '&mdash;')}</td>
                <td>{it.get('item_color', '&mdash;')}</td>
                <td>{it.get('item_size', '&mdash;')}</td>
                <td style="text-align:right;">{consumption:.4f}</td>
                <td>{it.get('uom', 'PCS')}</td>
                <td>{it.get('size_sensitive', 'No')}</td>
                <td style="text-align:right;">{rate:.2f}</td>
                <td>{it.get('supplier', '&mdash;')}</td>
                <td style="text-align:right;">{float(it.get('leadtime', 0) or 0):.0f}</td>
                <td style="text-align:right;">{cost:.2f}</td>
            </tr>"""
        grand_total += fg_total
        body += f"""
        <div class="fg-block">
            <div class="fg-block-head">
                <span>FG: {design} | Color: {color}</span>
                <span>Cost/PC: &#8377;{fg_total:.2f}</span>
            </div>
            <table>
                <thead><tr>
                    <th>#</th><th>Item No</th><th>Item Name</th><th>Color</th><th>Size</th>
                    <th style="text-align:right;">Cons/PC</th><th>UOM</th><th>Size Sens</th>
                    <th style="text-align:right;">Rate</th><th>Supplier</th>
                    <th style="text-align:right;">Lead</th><th style="text-align:right;">Cost</th>
                </tr></thead>
                <tbody>{rows or '<tr><td colspan="12" style="text-align:center;color:#888;">No items</td></tr>'}</tbody>
            </table>
        </div>
        """
    body += f'<div class="totals"><span class="grand-total">Total BOM Cost: &#8377;{grand_total:.2f}</span></div>'

    html = _print_wrapper(
        f"BOM - {buyer_order_id}",
        "BILL OF MATERIALS",
        _company(),
        order_info,
        body
    )
    return HTMLResponse(html)

@router.get("/print/COSTING_APPROVAL/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_costing_approval(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    bom_entries = crud.get_live_ledger_entries(
        db, activity_type='BOM', buyer_order_id=buyer_order_id,
        latest_version_only=True,
        extra_filter=lambda e: (e.status or '').upper() == 'COMPLETED'
    )
    fg_map = {}
    for e in bom_entries:
        if e.fg_key not in fg_map or e.id > fg_map[e.fg_key].id:
            fg_map[e.fg_key] = e

    if not fg_map:
        return HTMLResponse("<h1>No BOM found for this order</h1>", status_code=404)

    approval = db.query(models.CostingApproval).filter(
        models.CostingApproval.buyer_order_id == buyer_order_id
    ).first()
    approval_status = approval.approval_status if approval else 'PENDING'
    approved_by = approval.approved_by if approval else ''
    approved_at = approval.approved_at.strftime('%d-%m-%Y %H:%M') if approval and approval.approved_at else ''

    body = f"""
    <div style="background:#f0f4fe;padding:10px 14px;border-radius:8px;margin-bottom:12px;font-size:13px;">
        <strong>Approval Status:</strong> {approval_status}
        {f" | <strong>Approved By:</strong> {approved_by}" if approved_by else ""}
        {f" | <strong>Approved At:</strong> {approved_at}" if approved_at else ""}
    </div>
    """
    grand_total = 0.0
    for fg_key, entry in fg_map.items():
        parts = fg_key.split('|')
        design = parts[1] if len(parts) > 1 else '&mdash;'
        color = parts[2] if len(parts) > 2 else '&mdash;'
        items = (entry.extra_data or {}).get('items', []) or []
        fg_total = 0.0
        rows = ""
        for idx, it in enumerate(items, 1):
            consumption = float(it.get('consumption', 0) or 0)
            rate = float(it.get('rate', 0) or 0)
            cost = consumption * rate
            fg_total += cost
            rows += f"""<tr>
                <td>{idx}</td>
                <td>{it.get('item_no', '&mdash;')}</td>
                <td>{it.get('item_name', '&mdash;')}</td>
                <td>{it.get('item_size', '&mdash;')}</td>
                <td style="text-align:right;">{consumption:.4f}</td>
                <td>{it.get('uom', 'PCS')}</td>
                <td style="text-align:right;">{rate:.2f}</td>
                <td style="text-align:right;">{cost:.2f}</td>
            </tr>"""
        grand_total += fg_total
        body += f"""
        <div class="fg-block">
            <div class="fg-block-head">
                <span>FG: {design} | Color: {color}</span>
                <span>Cost/PC: &#8377;{fg_total:.2f}</span>
            </div>
            <table>
                <thead><tr>
                    <th>#</th><th>Item No</th><th>Item Name</th><th>Size</th>
                    <th style="text-align:right;">Consumption</th><th>UOM</th>
                    <th style="text-align:right;">Rate</th><th style="text-align:right;">Cost</th>
                </tr></thead>
                <tbody>{rows or '<tr><td colspan="8" style="text-align:center;color:#888;">No items</td></tr>'}</tbody>
            </table>
        </div>
        """
    body += f'<div class="totals"><span class="grand-total">Total Cost: &#8377;{grand_total:.2f}</span></div>'

    html = _print_wrapper(
        f"Costing Approval - {buyer_order_id}",
        "COSTING APPROVAL",
        _company(),
        order_info,
        body
    )
    return HTMLResponse(html)

@router.get("/print/RM_ORDER/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_rm_order(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    rm_entries = crud.get_live_ledger_entries(
        db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
        extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
                              and ((e.extra_data.get('itemNo') or '').strip() or float(e.qty or 0) > 0)
    )

    po_map = {}
    for e in rm_entries:
        po = e.extra_data.get('poToken', '')
        if not po:
            continue
        if po not in po_map:
            po_map[po] = {
                'poToken': po,
                'supplier': e.extra_data.get('supplierAlias') or e.extra_data.get('supplier') or '&mdash;',
                'poDate': (e.created_date or e.order_date),
                'status': e.status,
                'items': []
            }
        qty = float(e.qty or 0)
        rate = float((e.extra_data or {}).get('rate', 0) or 0)
        po_map[po]['items'].append({
            'itemNo': e.extra_data.get('itemNo', ''),
            'itemName': e.extra_data.get('itemName', ''),
            'garmentSize': e.size or 'ALL',
            'itemSize': e.extra_data.get('itemSize', ''),
            'color': e.color or e.extra_data.get('color', ''),
            'hsn': e.extra_data.get('hsn', ''),
            'qty': qty,
            'uom': e.extra_data.get('uom', 'PCS'),
            'rate': rate,
            'cgst': float(e.extra_data.get('cgst', 0) or 0),
            'igst': float(e.extra_data.get('igst', 0) or 0),
            'amount': qty * rate,
        })

    if not po_map:
        return HTMLResponse("<h1>No RM Orders found for this order</h1>", status_code=404)

    body = ""
    grand_total = 0.0
    for po, data in po_map.items():
        po_total = 0.0
        rows = ""
        for idx, it in enumerate(data['items'], 1):
            po_total += it['amount']
            rows += f"""<tr>
                <td>{idx}</td>
                <td>{it['itemNo'] or '&mdash;'}</td>
                <td>{it['itemName'] or '&mdash;'}</td>
                <td>{it['garmentSize']}</td>
                <td>{it['itemSize'] or '&mdash;'}</td>
                <td>{it['color'] or '&mdash;'}</td>
                <td>{it['hsn'] or '&mdash;'}</td>
                <td style="text-align:right;">{it['qty']:.2f}</td>
                <td>{it['uom']}</td>
                <td style="text-align:right;">&#8377;{it['rate']:.2f}</td>
                <td style="text-align:right;">{it['cgst']:.2f}</td>
                <td style="text-align:right;">{it['igst']:.2f}</td>
                <td style="text-align:right;">&#8377;{it['amount']:.2f}</td>
            </tr>"""
        grand_total += po_total
        po_date_str = data['poDate'].strftime('%d-%m-%Y') if data['poDate'] else '&mdash;'
        body += f"""
        <div class="fg-block">
            <div class="fg-block-head">
                <span>PO: {data['poToken']} | Supplier: {data['supplier']} | Date: {po_date_str} | Status: {data['status']}</span>
                <span>Subtotal: &#8377;{po_total:.2f}</span>
            </div>
            <table>
                <thead><tr>
                    <th>#</th><th>Item No</th><th>Item Name</th><th>Garment Size</th><th>Item Size</th>
                    <th>Color</th><th>HSN</th><th style="text-align:right;">Qty</th><th>UOM</th>
                    <th style="text-align:right;">Rate</th><th style="text-align:right;">CGST%</th>
                    <th style="text-align:right;">IGST%</th><th style="text-align:right;">Amount</th>
                </tr></thead>
                <tbody>{rows or '<tr><td colspan="13" style="text-align:center;color:#888;">No items</td></tr>'}</tbody>
            </table>
        </div>
        """
    body += f'<div class="totals"><span class="grand-total">Total RM Order Value: &#8377;{grand_total:.2f}</span></div>'

    html = _print_wrapper(
        f"RM Order - {buyer_order_id}",
        "RM ORDER (PURCHASE ORDERS)",
        _company(),
        order_info,
        body
    )
    return HTMLResponse(html)

@router.get("/print/RM_INSPECTION/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_rm_inspection(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    inspections = db.query(models.InspectionRecord).filter(
        models.InspectionRecord.inspection_type == 'RAW_MATERIAL'
    ).all()
    po_tokens = set()
    live_rm = crud.get_live_ledger_entries(
        db, activity_type='RM_ORDER', buyer_order_id=buyer_order_id,
        extra_filter=lambda e: bool((e.extra_data or {}).get('poToken'))
    )
    for e in live_rm:
        po_tokens.add(e.extra_data.get('poToken'))

    rows = ""
    idx = 0
    for insp in inspections:
        if insp.reference not in po_tokens:
            continue
        idx += 1
        is_stub = (insp.item == 'All Items' and insp.inspector == 'system')
        qty_disp = '&mdash;' if is_stub else f"{float(insp.quantity or 0):.2f}"
        passed_disp = '&mdash;' if is_stub else f"{float(insp.quantity_passed or 0):.2f}"
        rej_disp = '&mdash;' if is_stub else f"{float(insp.quantity_rejected or 0):.2f}"
        rows += f"""<tr>
            <td>{idx}</td>
            <td>{insp.reference or '&mdash;'}</td>
            <td>{insp.item or '&mdash;'}</td>
            <td style="text-align:right;">{qty_disp}</td>
            <td style="text-align:right;">{passed_disp}</td>
            <td style="text-align:right;">{rej_disp}</td>
            <td>{insp.inspector or '&mdash;'}</td>
            <td>{insp.status or 'PENDING'}</td>
            <td>{insp.date.strftime('%d-%m-%Y') if insp.date else '&mdash;'}</td>
        </tr>"""

    body = f"""
    <table>
        <thead><tr>
            <th>#</th><th>PO Token</th><th>Item</th>
            <th style="text-align:right;">Quantity</th><th style="text-align:right;">Passed</th>
            <th style="text-align:right;">Rejected</th><th>Inspector</th><th>Status</th><th>Date</th>
        </tr></thead>
        <tbody>{rows or '<tr><td colspan="9" style="text-align:center;color:#888;">No RM Inspections</td></tr>'}</tbody>
    </table>
    """
    html = _print_wrapper(f"RM Inspection - {buyer_order_id}", "RM INSPECTION", _company(), order_info, body)
    return HTMLResponse(html)

@router.get("/print/GRN/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_grn(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    grn_entries = crud.get_live_ledger_entries(
        db, activity_type='GRN', buyer_order_id=buyer_order_id,
        extra_filter=lambda e: bool((e.extra_data or {}).get('items'))
    )

    body = ""
    idx = 0
    for grn in grn_entries:
        items = grn.extra_data.get('items', []) or []
        invoice = grn.extra_data.get('invoiceNo', '&mdash;')
        po_token = grn.extra_data.get('poToken', '&mdash;')
        rows = ""
        total_recv = 0.0
        total_amt = 0.0
        for j, it in enumerate(items, 1):
            ordered = float(it.get('orderedQty', 0) or 0)
            received = float(it.get('receivedQty', 0) or 0)
            balance = max(0, ordered - received)
            rate = float(it.get('rate', 0) or 0)
            amt = received * rate
            total_recv += received
            total_amt += amt
            rows += f"""<tr>
                <td>{j}</td>
                <td>{it.get('itemNo', '&mdash;')}</td>
                <td>{it.get('itemName', '&mdash;')}</td>
                <td>{it.get('garmentSize', 'ALL')}</td>
                <td>{it.get('itemSize', '&mdash;')}</td>
                <td>{it.get('color', '&mdash;')}</td>
                <td style="text-align:right;">{ordered:.2f}</td>
                <td style="text-align:right;">{received:.2f}</td>
                <td style="text-align:right;">{balance:.2f}</td>
                <td>{it.get('uom', 'PCS')}</td>
                <td style="text-align:right;">&#8377;{rate:.2f}</td>
                <td style="text-align:right;">&#8377;{amt:.2f}</td>
            </tr>"""
        idx += 1
        body += f"""
        <div class="fg-block">
            <div class="fg-block-head">
                <span>PO: {po_token} | Invoice: {invoice} | Status: {grn.status}</span>
                <span>Received: {total_recv:.2f} | Value: &#8377;{total_amt:.2f}</span>
            </div>
            <table>
                <thead><tr>
                    <th>#</th><th>Item No</th><th>Item Name</th><th>Garment Size</th><th>Item Size</th>
                    <th>Color</th><th style="text-align:right;">Ordered</th><th style="text-align:right;">Received</th>
                    <th style="text-align:right;">Balance</th><th>UOM</th>
                    <th style="text-align:right;">Rate</th><th style="text-align:right;">Amount</th>
                </tr></thead>
                <tbody>{rows or '<tr><td colspan="12" style="text-align:center;color:#888;">No items</td></tr>'}</tbody>
            </table>
        </div>
        """
    if not body:
        body = '<p style="text-align:center;color:#888;">No GRN records</p>'

    html = _print_wrapper(f"GRN - {buyer_order_id}", "GOODS RECEIPT NOTE", _company(), order_info, body)
    return HTMLResponse(html)

@router.get("/print/INTERNAL_FG_ORDER/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_internal_fg_order(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    internal_orders = db.query(models.InternalFGOrder).filter(
        models.InternalFGOrder.buyer_order_id == buyer_order_id
    ).all()

    rows = ""
    total_base = 0.0
    total_factory = 0.0
    for idx, io in enumerate(internal_orders, 1):
        ed = io.extra_data or {}
        base = float(ed.get('base_quantity', 0) or 0)
        extra_pct = float(ed.get('extra_percentage', 0) or 0)
        extra_qty = float(ed.get('extra_quantity', 0) or 0)
        factory_qty = float(io.quantity or 0)
        total_base += base
        total_factory += factory_qty
        parts = io.fg_key.split('|')
        design = parts[1] if len(parts) > 1 else '&mdash;'
        color = parts[2] if len(parts) > 2 else '&mdash;'
        rows += f"""<tr>
            <td>{idx}</td>
            <td>{design}</td>
            <td>{color}</td>
            <td style="text-align:right;">{base:.2f}</td>
            <td style="text-align:right;">{extra_pct:.2f}%</td>
            <td style="text-align:right;">{extra_qty:.2f}</td>
            <td style="text-align:right;">{factory_qty:.2f}</td>
            <td>{io.production_status or 'PENDING'}</td>
        </tr>"""

    body = f"""
    <table>
        <thead><tr>
            <th>#</th><th>Design</th><th>Color</th>
            <th style="text-align:right;">Base Qty</th><th style="text-align:right;">Extra %</th>
            <th style="text-align:right;">Extra Qty</th><th style="text-align:right;">Factory Qty</th><th>Status</th>
        </tr></thead>
        <tbody>{rows or '<tr><td colspan="8" style="text-align:center;color:#888;">No factory orders</td></tr>'}</tbody>
    </table>
    <div class="totals">
        <div>Total Base: {total_base:.2f}</div>
        <div>Total Factory: {total_factory:.2f}</div>
        <div class="grand-total">Extra: {(total_factory - total_base):.2f}</div>
    </div>
    """
    html = _print_wrapper(f"Internal FG Order - {buyer_order_id}", "INTERNAL FG ORDER", _company(), order_info, body)
    return HTMLResponse(html)

@router.get("/print/ISSUE_RM/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_issue_rm(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    issue_entries = crud.get_live_ledger_entries(
        db, activity_type='MATERIAL_REQUIREMENT', buyer_order_id=buyer_order_id,
        extra_filter=lambda e: (e.status or '').upper() == 'ISSUED'
    )

    rows = ""
    total_issued = 0.0
    idx = 0
    for e in issue_entries:
        idx += 1
        ed = e.extra_data or {}
        parts = (e.fg_key or '').split('|')
        design = parts[1] if len(parts) > 1 else '&mdash;'
        color = parts[2] if len(parts) > 2 else '&mdash;'
        qty = float(e.qty or 0)
        total_issued += qty
        issued_at = ed.get('issuedAt', '')
        issued_date = issued_at[:10] if issued_at else '&mdash;'
        rows += f"""<tr>
            <td>{idx}</td>
            <td>{design}</td>
            <td>{color}</td>
            <td>{ed.get('itemNo', '&mdash;')}</td>
            <td>{ed.get('itemName', '&mdash;')}</td>
            <td>{e.size or 'ALL'}</td>
            <td>{e.color or '&mdash;'}</td>
            <td style="text-align:right;">{qty:.2f}</td>
            <td>{ed.get('uom', 'PCS')}</td>
            <td>{issued_date}</td>
        </tr>"""

    body = f"""
    <table>
        <thead><tr>
            <th>#</th><th>Design</th><th>Color</th><th>Item No</th><th>Item Name</th>
            <th>Garment Size</th><th>RM Color</th>
            <th style="text-align:right;">Issued Qty</th><th>UOM</th><th>Issued At</th>
        </tr></thead>
        <tbody>{rows or '<tr><td colspan="10" style="text-align:center;color:#888;">No issued items</td></tr>'}</tbody>
    </table>
    <div class="totals"><span class="grand-total">Total Issued: {total_issued:.2f}</span></div>
    """
    html = _print_wrapper(f"Issue RM - {buyer_order_id}", "ISSUE RM", _company(), order_info, body)
    return HTMLResponse(html)

@router.get("/print/FG_INSPECTION/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_fg_inspection(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    inspections = db.query(models.FGInspectionRecord).filter(
        models.FGInspectionRecord.buyer_order_id == buyer_order_id
    ).order_by(models.FGInspectionRecord.id.desc()).all()

    latest_by_fg = {}
    for ins in inspections:
        if ins.fg_key not in latest_by_fg:
            latest_by_fg[ins.fg_key] = ins

    rows = ""
    total_presented = 0.0
    total_inspected = 0.0
    idx = 0
    for fg_key, ins in latest_by_fg.items():
        idx += 1
        parts = fg_key.split('|')
        design = parts[1] if len(parts) > 1 else '&mdash;'
        color = parts[2] if len(parts) > 2 else '&mdash;'
        presented = float(ins.presented_qty or 0)
        inspected = float(ins.inspected_qty or 0)
        total_presented += presented
        total_inspected += inspected
        rows += f"""<tr>
            <td>{idx}</td>
            <td>{design}</td>
            <td>{color}</td>
            <td style="text-align:right;">{float(ins.order_qty or 0):.2f}</td>
            <td style="text-align:right;">{presented:.2f}</td>
            <td style="text-align:right;">{inspected:.2f}</td>
            <td style="text-align:right;">{ins.minor_defects or 0}</td>
            <td style="text-align:right;">{ins.major_defects or 0}</td>
            <td style="text-align:right;">{ins.critical_defects or 0}</td>
            <td>{ins.status or 'PENDING'}</td>
            <td>{ins.inspector or '&mdash;'}</td>
        </tr>"""

    body = f"""
    <table>
        <thead><tr>
            <th>#</th><th>Design</th><th>Color</th>
            <th style="text-align:right;">Order Qty</th><th style="text-align:right;">Presented</th>
            <th style="text-align:right;">Inspected</th><th style="text-align:right;">Minor</th>
            <th style="text-align:right;">Major</th><th style="text-align:right;">Critical</th>
            <th>Status</th><th>Inspector</th>
        </tr></thead>
        <tbody>{rows or '<tr><td colspan="11" style="text-align:center;color:#888;">No inspections</td></tr>'}</tbody>
    </table>
    <div class="totals">
        <div>Total Presented: {total_presented:.2f}</div>
        <div class="grand-total">Total Inspected: {total_inspected:.2f}</div>
    </div>
    """
    html = _print_wrapper(f"FG Inspection - {buyer_order_id}", "FG INSPECTION (AQL)", _company(), order_info, body)
    return HTMLResponse(html)

@router.get("/print/FG_INVENTORY/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_fg_inventory(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    items = db.query(models.FGInventory).filter(
        models.FGInventory.buyer_order_id == buyer_order_id
    ).all()

    rows = ""
    total_produced = 0.0
    total_ready = 0.0
    idx = 0
    for it in items:
        idx += 1
        parts = (it.fg_key or '').split('|')
        design = parts[1] if len(parts) > 1 else '&mdash;'
        color = parts[2] if len(parts) > 2 else '&mdash;'
        produced = float(it.quantity_produced or 0)
        passed = float(it.quantity_passed or 0)
        ready = float(it.quantity_ready or 0)
        total_produced += produced
        total_ready += ready
        rows += f"""<tr>
            <td>{idx}</td>
            <td>{design}</td>
            <td>{color}</td>
            <td style="text-align:right;">{produced:.2f}</td>
            <td style="text-align:right;">{passed:.2f}</td>
            <td style="text-align:right;">{float(it.quantity_rejected or 0):.2f}</td>
            <td style="text-align:right;">{ready:.2f}</td>
            <td>{it.status or 'PRODUCED'}</td>
        </tr>"""

    body = f"""
    <table>
        <thead><tr>
            <th>#</th><th>Design</th><th>Color</th>
            <th style="text-align:right;">Produced</th><th style="text-align:right;">Passed</th>
            <th style="text-align:right;">Rejected</th><th style="text-align:right;">Ready</th><th>Status</th>
        </tr></thead>
        <tbody>{rows or '<tr><td colspan="8" style="text-align:center;color:#888;">No FG inventory</td></tr>'}</tbody>
    </table>
    <div class="totals">
        <div>Total Produced: {total_produced:.2f}</div>
        <div class="grand-total">Balance (Ready): {total_ready:.2f}</div>
    </div>
    """
    html = _print_wrapper(f"FG Inventory - {buyer_order_id}", "FG INVENTORY", _company(), order_info, body)
    return HTMLResponse(html)

@router.get("/print/DISPATCH/{buyer_order_id}", response_class=HTMLResponse)
def print_stage_dispatch(buyer_order_id: str, db: Session = Depends(get_db)):
    order_info = _get_order_info(db, buyer_order_id)
    if not order_info:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)

    records = db.query(models.DispatchRecord).filter(
        models.DispatchRecord.buyer_order_id == buyer_order_id
    ).order_by(models.DispatchRecord.dispatched_at.desc()).all()

    rows = ""
    total_dispatched = 0.0
    idx = 0
    for d in records:
        idx += 1
        qty = float(d.dispatch_qty or 0)
        total_dispatched += qty
        rows += f"""<tr>
            <td>{idx}</td>
            <td>{d.dispatch_id or '&mdash;'}</td>
            <td>{d.invoice_no or '&mdash;'}</td>
            <td>{d.challan_no or '&mdash;'}</td>
            <td>{d.design_name or '&mdash;'}</td>
            <td>{d.color or '&mdash;'}</td>
            <td style="text-align:right;">{float(d.fg_qty or 0):.2f}</td>
            <td style="text-align:right;">{qty:.2f}</td>
            <td>{d.dispatched_by or '&mdash;'}</td>
            <td>{d.dispatched_at.strftime('%d-%m-%Y') if d.dispatched_at else '&mdash;'}</td>
        </tr>"""

    body = f"""
    <table>
        <thead><tr>
            <th>#</th><th>Dispatch ID</th><th>Invoice No</th><th>Challan No</th>
            <th>Design</th><th>Color</th>
            <th style="text-align:right;">FG Qty</th><th style="text-align:right;">Dispatched</th>
            <th>Dispatched By</th><th>Date</th>
        </tr></thead>
        <tbody>{rows or '<tr><td colspan="10" style="text-align:center;color:#888;">No dispatch records</td></tr>'}</tbody>
    </table>
    <div class="totals"><span class="grand-total">Total Dispatched: {total_dispatched:.2f}</span></div>
    """
    html = _print_wrapper(f"Dispatch - {buyer_order_id}", "DISPATCH", _company(), order_info, body)
    return HTMLResponse(html)