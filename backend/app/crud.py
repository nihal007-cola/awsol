from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from . import models
from .config import settings
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import uuid
import re
import logging

TOLERANCE = settings.tolerance

# ==================== MASTER DATA ====================

def get_master_data(db: Session, category: Optional[str] = None):
    query = db.query(models.MasterData)
    if category:
        query = query.filter(models.MasterData.category == category.upper())
    return query.all()

def get_buyers(db: Session):
    return db.query(models.MasterData).filter(
        models.MasterData.category == "BUYER",
        models.MasterData.status == "ACTIVE"
    ).all()

def get_buyer_details(db: Session, name: str):
    return db.query(models.MasterData).filter(
        models.MasterData.category == "BUYER",
        models.MasterData.name == name,
        models.MasterData.status == "ACTIVE"
    ).first()

def get_rmsuppliers(db: Session):
    return db.query(models.MasterData).filter(
        models.MasterData.category == "SUPPLIER",
        models.MasterData.status == "ACTIVE"
    ).all()

def get_rmsupplier_details(db: Session, name: str):
    return db.query(models.MasterData).filter(
        models.MasterData.category == "SUPPLIER",
        models.MasterData.name == name,
        models.MasterData.status == "ACTIVE"
    ).first()

def add_master_entity(db: Session, data: Dict):
    entity = models.MasterData(
        id=f"{data['category'].upper()}-{uuid.uuid4().hex[:6].upper()}",
        category=data['category'].upper(),
        name=data['name'],
        gst_no=data.get('gst_no', ''),
        address=data.get('address', ''),
        contact_person=data.get('contact_person', ''),
        contact_no=data.get('contact_no', ''),
        email=data.get('email', ''),
        payment_term=data.get('payment_term', ''),
        status="ACTIVE"
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity

# ==================== LEDGER ====================

def _resolve_buyer_order_id(data: Dict) -> str:
    """Derive buyer_order_id from explicit field or from fg_key prefix."""
    bo = (data.get('buyer_order_id') or '').strip()
    if bo:
        return bo
    fg = (data.get('fg_key') or '').strip()
    if fg and '|' in fg:
        return fg.split('|')[0]
    return ''


def _resolve_version(db: Session, buyer_order_id: str, explicit_version) -> int:
    """
    Resolve ledger version for a write.
    Invariant (strict): every ledger row written for an order MUST carry the
    order's WorkflowToken.current_version. There is no silent default.
    """
    if explicit_version is not None:
        return int(explicit_version)
    if not buyer_order_id:
        raise ValueError("add_ledger_entry: buyer_order_id missing and cannot be derived from fg_key")
    token = db.query(models.WorkflowToken).filter(
        models.WorkflowToken.buyer_order_id == buyer_order_id
    ).first()
    if not token:
        raise ValueError(f"add_ledger_entry: no WorkflowToken for order {buyer_order_id} — cannot stamp version")
    return int(token.current_version or 1)


def _make_entry(data: Dict, version: int) -> "models.ActivityLedger":
    """Build an ActivityLedger row from a dict, forcing version."""
    return models.ActivityLedger(
        fg_key=data.get('fg_key', ''),
        buyer_order_id=data.get('buyer_order_id', ''),
        activity_type=data['activity_type'].upper(),
        status=data['status'].upper(),
        buyer_name=data.get('buyer_name', ''),
        buyer_order_no=data.get('buyer_order_no', ''),
        order_date=data.get('order_date'),
        created_date=data.get('created_date'),
        qty=data.get('qty', 0),
        size=data.get('size', ''),
        color=data.get('color', ''),
        extra_data=data.get('extra_data'),
        workflow_position=data.get('workflow_position', 0),
        version=version,
    )


def _supersede_live(db: Session, new_data: Dict):
    """
    Flip the previous live row (same logical key, not CANCELLED) to CANCELLED
    IN PLACE. Called before inserting the new row, for every logical-key write.
    Rationale: the ledger grows monotonically; cancelling by appending a copy
    leaves the original still live and produces duplicates.

    Exception: if the new row is itself CANCELLED, the caller is explicitly
    writing the cancellation event. Flipping the prior live row on top of that
    would create TWO CANCELLED rows for the same logical key (Bug 4). In that
    case, do nothing — the appended CANCELLED row is the authoritative
    cancellation. Read paths (get_live_ledger_entries) treat the newest row
    per key as authoritative, so the prior row is correctly hidden from the
    live view even though it is not flipped.
    """
    activity_type = new_data.get('activity_type', '')
    fields, exclude_cancelled = _live_key_shape(activity_type)
    if fields is None:
        return 0

    if (new_data.get('status') or '').upper() == 'CANCELLED':
        return 0

    buyer_order_id = new_data.get('buyer_order_id', '')

    class _FakeEntry:
        def __init__(self, d):
            self.buyer_order_id = d.get('buyer_order_id', '')
            self.fg_key = d.get('fg_key', '')
            self.extra_data = d.get('extra_data') or {}
    fake = _FakeEntry(new_data)
    target_key = _entry_key(fake, fields)

    q = db.query(models.ActivityLedger).filter(
        models.ActivityLedger.activity_type == activity_type.upper(),
        models.ActivityLedger.buyer_order_id == buyer_order_id,
    ).order_by(models.ActivityLedger.id.desc())

    flipped = 0
    for r in q.all():
        if exclude_cancelled and (r.status or '').upper() == 'CANCELLED':
            continue
        if _entry_key(r, fields) == target_key:
            r.status = 'CANCELLED'
            meta = dict(r.extra_data or {})
            meta['supersededAt'] = datetime.utcnow().isoformat()
            r.extra_data = meta
            flipped += 1
    return flipped


def add_ledger_entry(db: Session, data: Dict):
    """Write one ledger row. Version is stamped from the token. Supersedes prior live row in place."""
    data = dict(data)
    data['buyer_order_id'] = _resolve_buyer_order_id(data)
    version = _resolve_version(db, data['buyer_order_id'], data.get('version'))
    _supersede_live(db, data)
    entry = _make_entry(data, version)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def add_ledger_entries_bulk(db: Session, rows: List[Dict]):
    """Write many ledger rows. Every row is stamped with the token's current version.
    For each row, the previous live row with the same logical key is flipped to
    CANCELLED in place before insert."""
    entries = []
    for data in rows:
        data = dict(data)
        data['buyer_order_id'] = _resolve_buyer_order_id(data)
        version = _resolve_version(db, data['buyer_order_id'], data.get('version'))
        _supersede_live(db, data)
        entries.append(_make_entry(data, version))
    db.add_all(entries)
    db.commit()
    return entries

def get_ledger_entries(db: Session, fg_key: Optional[str] = None, workflow_position: Optional[float] = None,
                       activity_type: Optional[str] = None, status: Optional[str] = None):
    query = db.query(models.ActivityLedger)
    if fg_key:
        query = query.filter(models.ActivityLedger.fg_key == fg_key)
    if workflow_position is not None:
        query = query.filter(models.ActivityLedger.workflow_position == workflow_position)
    if activity_type:
        query = query.filter(models.ActivityLedger.activity_type == activity_type.upper())
    if status:
        query = query.filter(models.ActivityLedger.status == status.upper())
    return query.order_by(models.ActivityLedger.timestamp).all()

def get_latest_status(db: Session, fg_key: str, activity_type: str):
    entries = get_ledger_entries(db, fg_key, None, activity_type)
    if not entries:
        return None
    return entries[-1]

def get_current_workflow_position(db: Session, fg_key: str):
    entries = get_ledger_entries(db, fg_key)
    if not entries:
        return 0
    latest = entries[-1]
    return int(latest.workflow_position) if latest.workflow_position is not None else 0

# ==================== INVENTORY SNAPSHOT ====================

def update_inventory_snapshot(db: Session, updates: List[Dict]):
    """Apply a batch of deltas to the inventory snapshot.

    Concurrency: each requirement_key is locked with SELECT ... FOR UPDATE
    before reading. Concurrent writers on the same key serialize on the row.
    For first-time inserts we use a SAVEPOINT + catch IntegrityError and
    convert to the update path, so two concurrent inserts for the same new
    key do not lose data.
    """
    if not updates:
        return

    from datetime import datetime
    from sqlalchemy.exc import IntegrityError

    for update in updates:
        requirement_key = update.get("requirementKey")
        if not requirement_key:
            continue

        fg_key = update.get("fgKey", "")
        buyer_order_id = update.get("buyerOrderId", "")
        if not buyer_order_id and fg_key and "|" in fg_key:
            buyer_order_id = fg_key.split("|")[0]

        _req_d = Decimal(str(update.get("requiredDelta", 0)))
        _grn_d = Decimal(str(update.get("grnDelta", 0)))
        _issue_d = Decimal(str(update.get("issueDelta", 0)))

        def _apply_to_snapshot(snapshot):
            _new_grn = (snapshot.total_grn_received_qty or Decimal("0")) + _grn_d
            _new_issued = (snapshot.total_issued_qty or Decimal("0")) + _issue_d
            if _new_grn < Decimal("-0.001"):
                raise ValueError(
                    f"snapshot invariant violated: total_grn_received_qty would go negative "
                    f"({snapshot.total_grn_received_qty} + {_grn_d} = {_new_grn}) for {requirement_key}. "
                    f"Reversal likely ran twice."
                )
            if _new_issued < Decimal("-0.001"):
                raise ValueError(
                    f"snapshot invariant violated: total_issued_qty would go negative "
                    f"({snapshot.total_issued_qty} + {_issue_d} = {_new_issued}) for {requirement_key}. "
                    f"Reversal likely ran twice."
                )
            snapshot.total_required_qty += _req_d
            snapshot.total_grn_received_qty = _new_grn
            snapshot.total_issued_qty = _new_issued
            snapshot.current_stock = _new_grn - _new_issued
            snapshot.pending_shortfall = snapshot.total_required_qty - _new_grn
            snapshot.last_updated = datetime.utcnow()

        # Lock the row if it exists.
        snapshot = (
            db.query(models.InventorySnapshot)
            .filter(models.InventorySnapshot.requirement_key == requirement_key)
            .with_for_update()
            .first()
        )

        if snapshot is not None:
            _apply_to_snapshot(snapshot)
            continue

        # Try to insert. If a concurrent transaction inserted the same key,
        # the unique constraint fires; rollback to a savepoint, then re-read
        # with a lock and apply the delta to the row we just lost to.
        savepoint = db.begin_nested()
        try:
            db.add(models.InventorySnapshot(
                requirement_key=requirement_key,
                buyer_order_id=buyer_order_id,
                fg_key=fg_key,
                item_no=update.get("itemNo", ""),
                item_name=update.get("itemName", ""),
                garment_size=update.get("size", ""),
                color=update.get("color", ""),
                supplier=update.get("supplier", ""),
                total_required_qty=_req_d,
                total_grn_received_qty=_grn_d,
                total_issued_qty=_issue_d,
                current_stock=_grn_d - _issue_d,
                pending_shortfall=_req_d - _grn_d,
            ))
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            snapshot = (
                db.query(models.InventorySnapshot)
                .filter(models.InventorySnapshot.requirement_key == requirement_key)
                .with_for_update()
                .first()
            )
            if snapshot is None:
                # Should be impossible: unique violation but no row visible.
                raise
            _apply_to_snapshot(snapshot)

    db.commit()


def generate_po_token() -> str:
    from datetime import datetime
    date = datetime.utcnow()
    return f"PO-{date.strftime('%y%m%d')}-{uuid.uuid4().hex[:3].upper()}"

def get_requirement_key(fg_key: str, size: str, color: str, item_size: str, item_no: str = '') -> str:
    """Generate unique requirement key.

    item_no distinguishes different RM items on the same FG line.
    item_size is intentionally EXCLUDED from the key — it is only a descriptive
    name extension (e.g. 2", 56"), not part of the requirement identity. Keeping
    it in the key caused historical variants ('2' vs '2"' vs '56'') to be treated
    as separate live requirements and produced duplicate rows in RM Order.
    """
    return f"{fg_key}|{size}|{color}||{item_no}"

def clean_key(key: str) -> str:
    if not key:
        return ''
    return str(key).strip().upper()

def clean_key_exact(key: str) -> str:
    if not key:
        return ''
    return str(key).strip()

def get_module_position(module_name: str) -> int:
    try:
        workflow = settings.get_workflow_list()
        return workflow.index(module_name.upper())
    except ValueError:
        return -1

def get_inventory_snapshot(db: Session, fg_key: Optional[str] = None, requirement_key: Optional[str] = None):
    query = db.query(models.InventorySnapshot)
    if fg_key:
        query = query.filter(models.InventorySnapshot.fg_key == fg_key)
    if requirement_key:
        query = query.filter(models.InventorySnapshot.requirement_key == requirement_key)
    return query.all()

# ==================== RM ID GENERATION ====================

def generate_rm_id(db: Session) -> str:
    """Generate next RM ID in format RM-000001"""
    from sqlalchemy import func
    
    # Get all RM items with IDs starting with 'RM-'
    items = db.query(models.MasterInventory).filter(
        models.MasterInventory.item_no.like('RM-%')
    ).all()
    
    max_num = 0
    for item in items:
        try:
            # Extract number from RM-000001 -> 1
            num = int(item.item_no.replace('RM-', ''))
            if num > max_num:
                max_num = num
        except ValueError:
            continue
    
    next_num = max_num + 1
    return f"RM-{str(next_num).zfill(6)}"

def generate_fg_serial(db: Session) -> str:
    """Generate a new FG serial number"""
    from datetime import datetime
    date = datetime.utcnow()
    prefix = f"FG-{date.strftime('%y%m%d')}"
    
    fg_keys = db.query(models.ActivityLedger.fg_key).filter(
        models.ActivityLedger.fg_key.like(f"{prefix}-%")
    ).distinct().all()
    
    serials = []
    for row in fg_keys:
        key = row[0]
        base_key = key.split('|')[0]
        parts = base_key.split('-')
        if len(parts) == 3:
            try:
                serials.append(int(parts[2]))
            except ValueError:
                pass
    
    if serials:
        last_serial = max(serials)
        new_serial = last_serial + 1
    else:
        new_serial = 1
    
    return f"{prefix}-{str(new_serial).zfill(3)}"

# ==============================================================
# WORKFLOW TOKEN - Stage + Version + Locking Helpers
# ==============================================================

from .models import WorkflowToken
from .config import settings

WORKFLOW_STAGES = [
    "BUYER_ORDER",
    "BOM",
    "COSTING_APPROVAL",
    "RM_ORDER",
    "GRN",
    "INTERNAL_FG_ORDER",
    "ISSUE_RM",
    "FG_INSPECTION",
    "FG_INVENTORY"
]

STAGE_INDEX = {stage: idx for idx, stage in enumerate(WORKFLOW_STAGES)}

def get_token_state(db: Session, buyer_order_id: str) -> Optional[Dict]:
    """Get current stage, version, and lock status for a token"""
    token = db.query(WorkflowToken).filter(
        WorkflowToken.buyer_order_id == buyer_order_id
    ).first()
    if not token:
        return None
    return {
        "buyer_order_id": token.buyer_order_id,
        "current_stage": token.current_stage,
        "current_version": token.current_version,
        "status": token.status,
        "locked_by": token.locked_by,
        "locked_at": token.locked_at,
        "token": token
    }

def create_token(db: Session, buyer_order_id: str, initial_stage: str = "BUYER_ORDER") -> WorkflowToken:
    """Create a new workflow token for a buyer order"""
    token = WorkflowToken(
        buyer_order_id=buyer_order_id,
        current_stage=initial_stage,
        current_version=1,
        status="ACTIVE"
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token

def get_or_create_token(db: Session, buyer_order_id: str, initial_stage: str = "BUYER_ORDER") -> WorkflowToken:
    """Get existing token or create a new one"""
    token = db.query(WorkflowToken).filter(
        WorkflowToken.buyer_order_id == buyer_order_id
    ).first()
    if not token:
        token = create_token(db, buyer_order_id, initial_stage)
    return token

def can_move_forward(db: Session, buyer_order_id: str) -> bool:
    """Check if token can move to the next stage"""
    state = get_token_state(db, buyer_order_id)
    if not state:
        return False
    current_idx = STAGE_INDEX.get(state["current_stage"])
    if current_idx is None:
        return False
    return current_idx < len(WORKFLOW_STAGES) - 1

def can_move_backward(db: Session, buyer_order_id: str) -> bool:
    """Check if token can move to the previous stage"""
    state = get_token_state(db, buyer_order_id)
    if not state:
        return False
    current_idx = STAGE_INDEX.get(state["current_stage"])
    if current_idx is None:
        return False
    return current_idx > 0

def get_current_stage_position(db: Session, buyer_order_id: str) -> int:
    """Get the numeric position of the current stage"""
    state = get_token_state(db, buyer_order_id)
    if not state:
        return 0
    return STAGE_INDEX.get(state["current_stage"], 0)

def move_stage(db: Session, buyer_order_id: str, direction: str, user: str = "system") -> Dict:
    """
    Move token forward or backward by one stage.
    direction: 'forward' or 'backward'
    Returns dict with new_stage, new_version, previous_stage, previous_version
    """
    state = get_token_state(db, buyer_order_id)
    if not state:
        raise ValueError(f"Token not found for order: {buyer_order_id}")
    
    token = state["token"]
    current_idx = STAGE_INDEX.get(state["current_stage"])
    if current_idx is None:
        raise ValueError(f"Invalid current stage: {state['current_stage']}")
    
    # Dispatch lock: once dispatched, no backward movement from FG_INVENTORY
    if direction == "backward" and state["current_stage"] == "FG_INVENTORY":
        dispatch_count = db.query(models.DispatchRecord).filter(
            models.DispatchRecord.buyer_order_id == buyer_order_id
        ).count()
        if dispatch_count > 0:
            raise ValueError(f"Cannot move backward: order has {dispatch_count} dispatch record(s). Once dispatched, the order is locked.")
    
    if direction == "forward":
        new_idx = current_idx + 1
        if new_idx >= len(WORKFLOW_STAGES):
            raise ValueError(f"Cannot move forward beyond {WORKFLOW_STAGES[-1]}")
    elif direction == "backward":
        new_idx = current_idx - 1
        if new_idx < 0:
            raise ValueError(f"Cannot move backward beyond {WORKFLOW_STAGES[0]}")
    else:
        raise ValueError("Direction must be 'forward' or 'backward'")
    
    new_stage = WORKFLOW_STAGES[new_idx]
    new_version = state["current_version"] + 1
    previous_stage = state["current_stage"]
    previous_version = state["current_version"]
    
    # Update token
    token.current_stage = new_stage
    # Also update the buyer_orders table
    buyer_order = db.query(models.BuyerOrder).filter(models.BuyerOrder.buyer_order_id == buyer_order_id).first()
    if buyer_order:
        buyer_order.current_stage = new_stage
        buyer_order.version = new_version
        buyer_order.updated_date = datetime.utcnow()
    token.current_version = new_version
    token.updated_at = datetime.utcnow()
    token.locked_by = user
    token.locked_at = datetime.utcnow()
    
    # Invariant: EVERY ledger row for this order belongs to the token's
    # current version — live AND CANCELLED. On movement, bump all rows in
    # place so the version filter in get_live_ledger_entries never drops a
    # CANCELLED row. Previously only non-CANCELLED rows were bumped, which
    # stranded CANCELLED rows at their pre-move version; the newest-wins
    # dedup then picked the older still-live sibling and the cancel was
    # silently undone. That produced the recurring "cancelled row comes
    # back live" bug in RM_ORDER, MATERIAL_REQUIREMENT, GRN, etc.
    all_rows = db.query(models.ActivityLedger).filter(
        models.ActivityLedger.buyer_order_id == buyer_order_id,
    ).all()
    for r in all_rows:
        r.version = new_version
    
    db.commit()
    db.refresh(token)
    
    return {
        "new_stage": new_stage,
        "new_version": new_version,
        "previous_stage": previous_stage,
        "previous_version": previous_version,
        "direction": direction,
        "bumped_rows": len(all_rows),
    }

def update_token_stage(db: Session, buyer_order_id: str, new_stage: str, user: str = "system") -> WorkflowToken:
    """Update token stage without moving (for edits within same stage)."""
    token = get_or_create_token(db, buyer_order_id, new_stage)
    new_version = (token.current_version or 1) + 1
    token.current_stage = new_stage
    token.current_version = new_version
    token.updated_at = datetime.utcnow()
    token.locked_by = user
    token.locked_at = datetime.utcnow()
    buyer_order = db.query(models.BuyerOrder).filter(
        models.BuyerOrder.buyer_order_id == buyer_order_id
    ).first()
    if buyer_order:
        buyer_order.current_stage = new_stage
        buyer_order.version = new_version
        buyer_order.updated_date = datetime.utcnow()
    db.commit()
    db.refresh(token)
    return token

def is_token_cancelled(db: Session, buyer_order_id: str) -> bool:
    """Check if a token is cancelled"""
    state = get_token_state(db, buyer_order_id)
    if not state:
        return False
    return state["status"] == "CANCELLED"

def cancel_token(db: Session, buyer_order_id: str, user: str = "system") -> WorkflowToken:
    """Cancel a workflow token"""
    token = get_or_create_token(db, buyer_order_id)
    token.status = "CANCELLED"
    token.updated_at = datetime.utcnow()
    token.locked_by = user
    token.locked_at = datetime.utcnow()
    db.commit()
    db.refresh(token)
    return token


def get_latest_version_entries(db, buyer_order_id, activity_type):
    """Get only the latest version COMPLETED entries for an order"""
    from . import models
    
    token = db.query(models.WorkflowToken).filter(
        models.WorkflowToken.buyer_order_id == buyer_order_id
    ).first()
    
    if not token:
        return []
    
    entries = db.query(models.ActivityLedger).filter(
        models.ActivityLedger.buyer_order_id == buyer_order_id,
        models.ActivityLedger.activity_type == activity_type,
        models.ActivityLedger.version == token.current_version,
        models.ActivityLedger.status == "COMPLETED"
    ).all()
    
    return entries


def get_latest_buyer_order_version(db, buyer_order_id):
    """Get the latest version of BUYER_ORDER entries for an order"""
    from . import models
    result = db.query(models.ActivityLedger.version).filter(
        models.ActivityLedger.buyer_order_id == buyer_order_id,
        models.ActivityLedger.activity_type == "BUYER_ORDER",
        models.ActivityLedger.status == "COMPLETED"
    ).order_by(models.ActivityLedger.version.desc()).first()
    return result[0] if result else 1

def get_latest_bom_version(db, buyer_order_id):
    """Get the latest version of BOM entries for an order"""
    from . import models
    result = db.query(models.ActivityLedger.version).filter(
        models.ActivityLedger.buyer_order_id == buyer_order_id,
        models.ActivityLedger.activity_type == "BOM",
        models.ActivityLedger.status == "COMPLETED"
    ).order_by(models.ActivityLedger.version.desc()).first()
    return result[0] if result else 1


# ==============================================================
# LIVE VERSION HELPERS — dedupe ledger by logical key
# ==============================================================

def _live_key_shape(activity_type):
    """
    Return (key_fields, excludes_cancelled) for the given activity type.
    key_fields is a list of names; None means no dedup for that type.
    """
    at = (activity_type or '').upper()
    # Version is NOT part of identity. It is a filter applied by readers
    # (current version only). Including it here previously allowed stale
    # versions to leak into "live" reads and produced duplicates.
    shapes = {
        'BUYER_ORDER':          (['buyer_order_id', 'fg_key'], True),
        'BOM':                  (['buyer_order_id', 'fg_key'], True),
        'MATERIAL_REQUIREMENT': (['buyer_order_id', 'fg_key', 'requirementKey'], True),
        'COSTING_APPROVAL':     (['buyer_order_id', 'fg_key'], True),
        'RM_ORDER':             (['buyer_order_id', 'poToken', 'requirementKey'], True),
        'RM_INSPECTION':        (['buyer_order_id', 'reference'], True),
        'GRN':                  (['buyer_order_id', 'poToken', 'invoiceNo', 'requirementKey'], True),
        'INTERNAL_FG_ORDER':    (['buyer_order_id', 'fg_key'], True),
        'ISSUE_RM':             (['buyer_order_id', 'fg_key'], True),
        'FG_INSPECTION':        (['buyer_order_id', 'fg_key'], True),
        'DISPATCH':             (None, False),
    }
    return shapes.get(at, (None, False))

def _entry_key(entry, fields):
    """Build a tuple key from an entry using the given field names."""
    parts = []
    for f in fields:
        if f in ('poToken', 'requirementKey', 'invoiceNo', 'reference'):
            v = (entry.extra_data or {}).get(f, '')
        else:
            v = getattr(entry, f, '') or ''
        parts.append(str(v).strip())
    return tuple(parts)

def get_live_ledger_entries(db: Session, activity_type=None, buyer_order_id=None,
                            fg_key=None, extra_filter=None, latest_version_only=False):
    """
    Return live rows for the given activity type.

    Invariant (strict): when buyer_order_id is provided, only rows whose version
    equals the token's current_version are eligible — older versions are historical.

    Dedup: within the eligible set, keep only the latest row per logical key
    (keys are defined by _live_key_shape; version is NOT part of the key).

    latest_version_only: kept for backward compat — now a no-op, since version is
    always a filter, never a key.
    """
    q = db.query(models.ActivityLedger)
    if activity_type:
        q = q.filter(models.ActivityLedger.activity_type == activity_type.upper())
    if buyer_order_id:
        q = q.filter(models.ActivityLedger.buyer_order_id == buyer_order_id)
    if fg_key:
        q = q.filter(models.ActivityLedger.fg_key == fg_key)
    rows = q.order_by(models.ActivityLedger.id.asc()).all()

    # Version filter — only current version is live.
    if buyer_order_id:
        token = db.query(models.WorkflowToken).filter(
            models.WorkflowToken.buyer_order_id == buyer_order_id
        ).first()
        if token is not None:
            current_version = int(token.current_version or 1)
            rows = [r for r in rows if int(r.version or 1) == current_version]

    fields, exclude_cancelled = _live_key_shape(activity_type)
    if fields is None:
        # No dedup for this type
        if extra_filter:
            rows = [r for r in rows if extra_filter(r)]
        return rows

    # Latest-wins dedup: pick the NEWEST row per logical key, INCLUDING
    # CANCELLED rows. Then drop keys whose newest row is CANCELLED.
    #
    # Why: a CANCELLED append (Pattern B routers: bom.cancel, rm_order.cancel,
    # grn.cancel, etc.) must be authoritative over any older live row for the
    # same key. The previous implementation skipped CANCELLED rows BEFORE
    # dedup, which let an older COMPLETED row win the key and wrongly appear
    # live. Now the newest row is always the winner; if it is CANCELLED, the
    # key is gone.
    # Latest-wins dedup over ALL rows for the key, regardless of extra_filter.
    # CANCELLED rows must participate in dedup so they can suppress older live
    # rows with the same key. extra_filter is applied AFTER dedup, never before.
    latest = {}
    for r in rows:
        k = _entry_key(r, fields)
        prev = latest.get(k)
        if prev is None or r.id > prev.id:
            latest[k] = r

    result = []
    for r in latest.values():
        if exclude_cancelled and (r.status or '').upper() == 'CANCELLED':
            continue
        if extra_filter and not extra_filter(r):
            continue
        result.append(r)

    return result

def supersede_previous_entry(db: Session, new_row: Dict):
    """
    Before inserting a new ledger row, find the previous live row with the same
    logical key (excluding CANCELLED) and write a CANCELLED copy for it, so the
    ledger self-documents the transition. Returns the superseded entry (or None).
    """
    activity_type = new_row.get('activity_type', '')
    fields, exclude_cancelled = _live_key_shape(activity_type)
    if fields is None:
        return None

    # Build a key against a fake entry object using the same fields
    class _FakeEntry:
        def __init__(self, d):
            self.buyer_order_id = d.get('buyer_order_id', '')
            self.fg_key = d.get('fg_key', '')
            self.version = d.get('version', 1)
            self.extra_data = d.get('extra_data') or {}
    fake = _FakeEntry(new_row)
    target_key = _entry_key(fake, fields)

    q = db.query(models.ActivityLedger).filter(
        models.ActivityLedger.activity_type == activity_type.upper(),
        models.ActivityLedger.buyer_order_id == new_row.get('buyer_order_id', '')
    ).order_by(models.ActivityLedger.id.desc())

    for r in q.all():
        if exclude_cancelled and (r.status or '').upper() == 'CANCELLED':
            continue
        if _entry_key(r, fields) == target_key:
            # Write a CANCELLED copy
            meta = dict(r.extra_data or {})
            meta['supersededBy'] = new_row.get('_new_row_id_hint', '')
            meta['supersededAt'] = datetime.utcnow().isoformat()
            cancelled = models.ActivityLedger(
                buyer_order_id=r.buyer_order_id,
                fg_key=r.fg_key,
                activity_type=r.activity_type,
                status='CANCELLED',
                buyer_name=r.buyer_name,
                buyer_order_no=r.buyer_order_no,
                order_date=r.order_date,
                created_date=r.created_date,
                qty=r.qty,
                size=r.size,
                color=r.color,
                location=r.location,
                extra_data=meta,
                workflow_position=r.workflow_position,
                version=r.version,
            )
            db.add(cancelled)
            return cancelled
    return None
