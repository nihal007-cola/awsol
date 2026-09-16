from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas, models
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/buyer-order", tags=["Buyer Order"])

def parse_date(date_val):
    if date_val is None:
        return datetime.utcnow()
    if isinstance(date_val, datetime):
        return date_val
    if isinstance(date_val, str):
        for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%d %H:%M:%S']:
            try:
                return datetime.strptime(date_val, fmt)
            except ValueError:
                continue
        return datetime.utcnow()
    return datetime.utcnow()

# ==============================================================
# GENERATE FG SERIAL
# ==============================================================
@router.get("/fg-serial")
def get_fg_serial(db: Session = Depends(get_db)):
    today = datetime.utcnow()
    return {"serial": f"FG-{today.strftime('%y%m%d')}-{today.strftime('%H%M%S')}"}

# ==============================================================
# GENERATE GRID
# ==============================================================
@router.post("/generate-grid")
def generate_grid(request: dict, db: Session = Depends(get_db)):
    try:
        buyer_name = request.get('buyer_name', '')
        buyer_order_no = request.get('buyer_order_no', '')
        no_of_fg = request.get('no_of_fg', 0)
        order_date = request.get('order_date', datetime.utcnow().strftime('%Y-%m-%d'))
        
        today = datetime.utcnow()
        fg_order_serial = f"FG-{today.strftime('%y%m%d')}-{today.strftime('%H%M%S')}"
        
        sizes_from_request = request.get("sizes", [])
        default_sizes = sizes_from_request if sizes_from_request else settings.get_default_sizes_list()
        
        grid_data = []
        for i in range(int(no_of_fg)):
            row = [i + 1, f"Design{i+1}", f"Color{i+1}"] + [''] * len(default_sizes) + [buyer_name, buyer_order_no, order_date, datetime.utcnow().strftime('%Y-%m-%d')]
            grid_data.append(row)
        
        return {
            "success": True,
            "fg_order_serial": fg_order_serial,
            "grid_data": grid_data,
            "sizes": default_sizes
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

# ==============================================================
# SAVE BUYER ORDER
# ==============================================================
@router.post("/save")
def save_buyer_order(request: dict, db: Session = Depends(get_db)):
    try:
        grid_data = request.get('grid_data', [])
        fg_order_serial = request.get('fg_order_serial', '')
        if not grid_data:
            return {"success": False, "message": "No data provided"}
        
        sizes_from_request = request.get("sizes", [])
        default_sizes = sizes_from_request if sizes_from_request else settings.get_default_sizes_list()
        
        first_row = grid_data[0]
        
        buyer_name = first_row[-4] if len(first_row) >= 4 else 'Unknown'
        buyer_order_no = first_row[-3] if len(first_row) >= 3 else 'N/A'
        order_date = parse_date(first_row[-2]) if len(first_row) >= 2 else datetime.utcnow()
        created_date = parse_date(first_row[-1]) if len(first_row) >= 1 else datetime.utcnow()
        
        existing_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == fg_order_serial
        ).first()
        
        if not existing_order:
            buyer_order = models.BuyerOrder(
                buyer_order_id=fg_order_serial,
                buyer_name=buyer_name,
                buyer_order_no=buyer_order_no,
                order_date=order_date,
                status="COMPLETED",
                total_fgs=len(grid_data),
                current_stage="BUYER_ORDER",
                version=1
            )
            db.add(buyer_order)
            db.commit()
        
        # Create (or fetch) the workflow token FIRST so that ledger writes can
        # stamp version = token.current_version. add_ledger_entries_bulk now
        # raises if no token exists for the order.
        token = crud.get_or_create_token(db, fg_order_serial, "BUYER_ORDER")
        if not token.current_version:
            token.current_version = 1
            db.commit()
        
        entries = []
        for row in grid_data:
            fg_key = f"{fg_order_serial}|{row[1]}|{row[2]}"
            entries.append({
                'buyer_order_id': fg_order_serial,
                'fg_key': fg_key,
                'activity_type': 'BUYER_ORDER',
                'status': 'COMPLETED',
                'buyer_name': buyer_name,
                'buyer_order_no': buyer_order_no,
                'order_date': order_date,
                'created_date': created_date,
                'workflow_position': 0,
                'extra_data': {
                    'gridRow': row,
                    'sizes': default_sizes,
                    'fgDesign': row[1] or '',
                    'fgColor': row[2] or '',
                    'orderVersion': token.current_version
                }
            })
        
        crud.add_ledger_entries_bulk(db, entries)
        
        return {"success": True, "message": f"Order {fg_order_serial} saved"}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ==============================================================
# GET BUYER ORDERS
# ==============================================================
@router.get("/orders")
def get_buyer_orders(db: Session = Depends(get_db), show_cancelled: bool = False):
    """Get buyer orders - optionally include cancelled"""
    if show_cancelled:
        tokens = db.query(models.WorkflowToken).filter(
            models.WorkflowToken.status == "CANCELLED"
        ).all()
    else:
        tokens = db.query(models.WorkflowToken).filter(
            models.WorkflowToken.current_stage == "BUYER_ORDER",
            models.WorkflowToken.status == "ACTIVE"
        ).all()
    
    if not tokens:
        return []
    
    result = []
    for token in tokens:
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == token.buyer_order_id
        ).first()
        
        if not buyer_order:
            continue
        
        entries = db.query(models.ActivityLedger).filter(
            models.ActivityLedger.buyer_order_id == token.buyer_order_id,
            models.ActivityLedger.activity_type == "BUYER_ORDER",
            models.ActivityLedger.status == "COMPLETED",
            models.ActivityLedger.version == token.current_version
        ).all()
        
        total_fgs = len(set(e.fg_key for e in entries))
        
        result.append({
            "buyerOrderId": token.buyer_order_id,
            "buyerName": buyer_order.buyer_name or "Unknown",
            "buyerOrderNo": buyer_order.buyer_order_no or "N/A",
            "orderDate": buyer_order.order_date,
            "totalFGs": total_fgs,
            "status": token.status,
            "currentStage": token.current_stage,
            "currentVersion": token.current_version,
            "lastUpdated": buyer_order.updated_date or buyer_order.order_date,
            "is_locked": token.locked_by is not None
        })
    
    result.sort(key=lambda x: x.get("orderDate") or "", reverse=True)
    return result

# ==============================================================
# CANCEL BUYER ORDER
# ==============================================================
@router.post("/cancel")
def cancel_buyer_order(data: Dict, db: Session = Depends(get_db)):
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        if not buyer_order_id:
            return {"success": False, "message": "Order ID is required"}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "Order not found"}
        
        if token_state["current_stage"] != "BUYER_ORDER":
            return {"success": False, "message": f"Cannot cancel order in {token_state['current_stage']} stage"}
        
        buyer_order = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        if buyer_order:
            buyer_order.status = "CANCELLED"
            buyer_order.updated_date = datetime.utcnow()
            db.commit()
        
        crud.cancel_token(db, buyer_order_id, "system")
        
        entries = crud.get_ledger_entries(db, activity_type='BUYER_ORDER')
        order_entries = [e for e in entries if e.buyer_order_id == buyer_order_id and e.status == 'COMPLETED']
        
        entries_to_insert = []
        for entry in order_entries:
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': entry.fg_key,
                'activity_type': 'BUYER_ORDER',
                'status': 'CANCELLED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'version': token_state["current_version"],
                'extra_data': {
                    **(entry.extra_data or {}),
                    'cancelledAt': datetime.utcnow().isoformat(),
                    'cancelledBy': 'system'
                },
                'workflow_position': entry.workflow_position
            })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        return {"success": True, "message": f"Order {buyer_order_id} cancelled successfully"}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ==============================================================
# PRINT BUYER ORDER
# ==============================================================
@router.get("/print/{order_id}")
def print_buyer_order(order_id: str, db: Session = Depends(get_db)):
    from ..config import settings
    from fastapi.responses import HTMLResponse
    
    token = db.query(models.WorkflowToken).filter(
        models.WorkflowToken.buyer_order_id == order_id
    ).first()
    
    if not token:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)
    
    entries = crud.get_ledger_entries(db, activity_type="BUYER_ORDER")
    order_entries = [e for e in entries if e.buyer_order_id == order_id and e.version == token.current_version and e.status == 'COMPLETED']
    
    if not order_entries:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)
    
    latest = order_entries[0]
    buyer_name = latest.buyer_name or "Unknown"
    buyer_order_no = latest.buyer_order_no or "N/A"
    order_date = latest.order_date.strftime("%d-%m-%Y") if latest.order_date else "N/A"
    last_updated = latest.timestamp.strftime("%d-%m-%Y %H:%M") if latest.timestamp else order_date
    
    default_sizes = settings.get_default_sizes_list()
    
    rows_html = ""
    total_qty = 0
    for entry in order_entries:
        if entry.extra_data and entry.extra_data.get("gridRow"):
            row = entry.extra_data["gridRow"]
            design = row[1] if len(row) > 1 else ""
            color = row[2] if len(row) > 2 else ""
            sizes = row[3:-4] if len(row) > 4 else []
            
            for i, qty in enumerate(sizes):
                if qty > 0 and i < len(default_sizes):
                    size_val = default_sizes[i]
                    rows_html += f"<tr><td>{design}</td><td>{color}</td><td>{size_val}</td><td><strong>{qty}</strong></td></tr>"
                    total_qty += qty
    
    company = settings.company_name
    company_addr = settings.company_address
    company_gst = settings.company_gst
    company_state = settings.company_state
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Buyer Order - {order_id}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; padding: 40px; background: #f8f9fa; }}
        .container {{ max-width: 1100px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ text-align: center; border-bottom: 3px solid #2a6df4; padding-bottom: 20px; margin-bottom: 20px; }}
        .company-name {{ font-size: 24px; font-weight: 700; color: #1a3a6a; }}
        .company-details {{ font-size: 12px; color: #555; }}
        .po-title {{ text-align: center; font-size: 20px; font-weight: 700; color: #1a3a6a; margin: 15px 0; }}
        .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; background: #f0f4fe; padding: 12px 16px; border-radius: 8px; margin: 12px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 12px; }}
        table th {{ background: #1a3a6a; color: white; padding: 8px; text-align: center; }}
        table td {{ padding: 6px 8px; border-bottom: 1px solid #e9edf4; text-align: center; }}
        .totals {{ text-align: right; margin-top: 15px; }}
        .grand-total {{ font-size: 18px; font-weight: 700; color: #1a3a6a; }}
        .footer {{ margin-top: 40px; border-top: 2px solid #e9edf4; padding-top: 20px; text-align: center; font-size: 12px; color: #666; }}
        .footer .brand {{ font-weight: 600; color: #1a3a6a; }}
        .no-print {{ display: inline-block; }}
        @media print {{ body {{ padding: 20px; background: white; }} .container {{ box-shadow: none; }} .no-print {{ display: none; }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="company-name">{company}</div>
            <div class="company-details">{company_addr}</div>
            <div class="company-details">GST: {company_gst} | State: {company_state}</div>
        </div>
        <div class="po-title">BUYER ORDER</div>
        <div class="info-grid">
            <span><strong>Order ID:</strong> {order_id}</span>
            <span><strong>Date:</strong> {order_date}</span>
            <span><strong>Buyer:</strong> {buyer_name}</span>
            <span><strong>Buyer Order No:</strong> {buyer_order_no}</span>
            <span><strong>Last Updated:</strong> {last_updated}</span>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Design</th>
                    <th>Color</th>
                    <th>Size</th>
                    <th>Quantity</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <div class="totals">
            <p class="grand-total"><strong>Total Quantity:</strong> {total_qty}</p>
        </div>
        <div style="margin-top:20px;">
            <button class="no-print" onclick="window.print()" style="padding:10px 24px; background:#2a6df4; color:white; border:none; border-radius:6px; cursor:pointer; font-size:14px;">🖨️ Print</button>
        </div>
        <div class="footer">
            <p>This is a computer generated document. No signature required.</p>
            <p><strong>For {company}</strong></p>
            <p class="brand">SNEHA CREATIONS · Powered by Offices of Nawnit Nihal</p>
        </div>
    </div>
</body>
</html>"""
    
    return HTMLResponse(html)

# ==============================================================
# GET ORDER GRID - Only latest version
# ==============================================================
@router.get("/grid/{order_id}")
def get_order_grid(order_id: str, db: Session = Depends(get_db)):
    """Get grid data - uses latest BUYER_ORDER version from activity_ledger"""
    # Get the latest version from activity_ledger
    latest_version = db.query(models.ActivityLedger.version).filter(
        models.ActivityLedger.buyer_order_id == order_id,
        models.ActivityLedger.activity_type == "BUYER_ORDER",
        models.ActivityLedger.status == "COMPLETED"
    ).order_by(models.ActivityLedger.version.desc()).first()
    
    if not latest_version:
        return {"success": False, "message": "Order not found"}
    
    version = latest_version[0]
    
    entries = crud.get_ledger_entries(db, activity_type='BUYER_ORDER')
    order_entries = [e for e in entries if e.buyer_order_id == order_id and e.version == version and e.status == 'COMPLETED']
    
    if not order_entries:
        return {"success": False, "message": "No grid data found"}
    
    grid_rows = []
    sizes = settings.get_default_sizes_list()
    
    for entry in order_entries:
        if entry.extra_data and entry.extra_data.get('gridRow'):
            grid_rows.append(entry.extra_data['gridRow'])
            if entry.extra_data.get('sizes'):
                sizes = entry.extra_data['sizes']
    
    if not grid_rows:
        return {"success": False, "message": "No grid data found"}
    
    return {
        "success": True,
        "grid_data": grid_rows,
        "sizes": sizes,
        "version": version
    }

# ==============================================================
# UPDATE BUYER ORDER
# ==============================================================
@router.post("/update")
def update_buyer_order(data: Dict, db: Session = Depends(get_db)):
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        grid_data = data.get('grid_data', [])
        buyer_name = data.get('buyer_name', '')
        buyer_order_no = data.get('buyer_order_no', '')
        order_date = data.get('order_date', '')
        
        if not buyer_order_id or not grid_data:
            return {"success": False, "message": "Missing required data"}
        
        token = db.query(models.WorkflowToken).filter(
            models.WorkflowToken.buyer_order_id == buyer_order_id
        ).first()
        
        if not token:
            return {"success": False, "message": "Order not found"}
        
        if token.current_stage != "BUYER_ORDER":
            return {"success": False, "message": f"Cannot edit order in {token.current_stage} stage"}
        
        old_version = token.current_version
        new_version = old_version + 1
        
        buyer_order_record = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        
        if buyer_order_record:
            buyer_order_record.version = new_version
            buyer_order_record.buyer_name = buyer_name
            buyer_order_record.buyer_order_no = buyer_order_no
            buyer_order_record.order_date = parse_date(order_date) if order_date else datetime.utcnow()
            buyer_order_record.total_fgs = len(grid_data)
            buyer_order_record.status = "COMPLETED"
            buyer_order_record.updated_date = datetime.utcnow()
            db.commit()
        
        token.current_version = new_version
        token.updated_at = datetime.utcnow()
        db.commit()
        
        entries = crud.get_ledger_entries(db, activity_type='BUYER_ORDER')
        order_entries = [e for e in entries if e.buyer_order_id == buyer_order_id and e.status == 'COMPLETED' and e.version == old_version]
        
        if not order_entries:
            return {"success": False, "message": "Order not found"}
        
        entries_to_insert = []
        now = datetime.utcnow()
        
        for entry in order_entries:
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': entry.fg_key,
                'activity_type': 'BUYER_ORDER',
                'status': 'CANCELLED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'version': new_version,
                'extra_data': {
                    **(entry.extra_data or {}),
                    'updatedAt': now.isoformat(),
                    'updatedBy': 'admin',
                    'previousStatus': entry.status,
                    'cancelled_version': new_version
                },
                'workflow_position': entry.workflow_position
            })
        
        sizes_from_request = data.get("sizes", [])
        default_sizes = sizes_from_request if sizes_from_request else settings.get_default_sizes_list()
        order_date_parsed = parse_date(order_date) if order_date else datetime.utcnow()
        
        for row in grid_data:
            fg_key = f"{buyer_order_id}|{row[1]}|{row[2]}"
            entries_to_insert.append({
                'buyer_order_id': buyer_order_id,
                'fg_key': fg_key,
                'activity_type': 'BUYER_ORDER',
                'status': 'COMPLETED',
                'buyer_name': buyer_name,
                'buyer_order_no': buyer_order_no,
                'order_date': order_date_parsed,
                'created_date': now,
                'version': new_version,
                'workflow_position': 0,
                'extra_data': {
                    'gridRow': row,
                    'sizes': default_sizes,
                    'fgDesign': row[1] or '',
                    'fgColor': row[2] or '',
                    'updatedAt': now.isoformat(),
                    'updatedBy': 'admin',
                    'orderVersion': new_version,
                    'previous_version': old_version
                }
            })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        return {"success": True, "message": f"Order {buyer_order_id} updated successfully", "new_version": new_version}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ==============================================================
# PROCESS ORDER TO BOM
# ==============================================================
@router.post("/process-to-bom")
def process_order_to_bom(data: Dict, db: Session = Depends(get_db)):
    try:
        buyer_order_id = data.get('buyer_order_id', '')
        if not buyer_order_id:
            return {"success": False, "message": "Order ID is required"}
        
        token_state = crud.get_token_state(db, buyer_order_id)
        if not token_state:
            return {"success": False, "message": "Order not found"}
        
        if token_state["current_stage"] != "BUYER_ORDER":
            return {"success": False, "message": f"Order is currently in {token_state['current_stage']}. Cannot process to BOM."}
        
        if not crud.can_move_forward(db, buyer_order_id):
            return {"success": False, "message": "Cannot move forward from current stage"}

        # Look up the live BUYER_ORDER rows BEFORE the move so we can validate
        # that FGs exist. If we looked them up after move_stage, the version
        # bump would make the pre-move version filter return nothing.
        entries = crud.get_ledger_entries(db, activity_type='BUYER_ORDER')
        order_entries = [e for e in entries
                         if e.buyer_order_id == buyer_order_id
                         and e.version == token_state["current_version"]
                         and e.status == 'COMPLETED']

        if not order_entries:
            return {"success": False, "message": "No FGs found for this order"}

        move_result = crud.move_stage(db, buyer_order_id, "forward", "system")
        
        entries_to_insert = []
        processed_fg = set()
        
        buyer_order_record = db.query(models.BuyerOrder).filter(
            models.BuyerOrder.buyer_order_id == buyer_order_id
        ).first()
        version = buyer_order_record.version if buyer_order_record else 1
        
        for entry in order_entries:
            fg_key = entry.fg_key
            if fg_key in processed_fg:
                continue
            
            entries_to_insert.append({
                'fg_key': fg_key,
                'buyer_order_id': buyer_order_id,
                'activity_type': 'BOM',
                'status': 'PENDING',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'workflow_position': 1,
                'extra_data': {
                    'sourceOrder': buyer_order_id,
                    'processedAt': datetime.utcnow().isoformat(),
                    'fgDesign': entry.extra_data.get('fgDesign', '') if entry.extra_data else '',
                    'fgColor': entry.extra_data.get('fgColor', '') if entry.extra_data else '',
                    'orderVersion': version,
                    'version': move_result["new_version"],
                    'previous_version': move_result["previous_version"],
                    'stage_movement': 'forward',
                    'from_stage': move_result["previous_stage"],
                    'to_stage': move_result["new_stage"]
                }
            })
            processed_fg.add(fg_key)
        
        if not entries_to_insert:
            return {"success": False, "message": "All FGs already have BOM or no FGs found"}
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {
            "success": True,
            "message": "Processed " + str(len(entries_to_insert)) + " FGs to BOM stage",
            "fgCount": len(entries_to_insert)
        }
    except Exception as e:
        return {"success": False, "message": str(e)}
