from sqlalchemy import text, Column, Integer, String, Float, DateTime, JSON, Text, Boolean, ForeignKey, Index, Numeric, func
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import uuid

# ==============================================================
# MODULE 1: MASTER DATA - Parties (Buyers & Suppliers)
# ==============================================================
class MasterData(Base):
    __tablename__ = "master_data"
    
    id = Column(String(50), primary_key=True, default=lambda: f"PARTY-{uuid.uuid4().hex[:6].upper()}")
    category = Column(String(20), nullable=False)  # BUYER, SUPPLIER
    name = Column(String(200), nullable=False, unique=True)
    gst_no = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    contact_person = Column(String(100), nullable=True)
    contact_no = Column(String(50), nullable=True)
    email = Column(String(100), nullable=True)
    payment_term = Column(String(100), nullable=True)
    added_date = Column(DateTime, server_default=func.now())
    status = Column(String(20), default="ACTIVE")  # ACTIVE, INACTIVE
    created_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime, onupdate=func.now())
    
    __table_args__ = (
        Index('idx_master_category', 'category'),
        Index('idx_master_name', 'name'),
        Index('idx_master_status', 'status'),
    )

# ==============================================================
# MODULE 2: MASTER INVENTORY - RM Items with Versioning
# ==============================================================
class MasterInventory(Base):
    __tablename__ = "master_inventory"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_no = Column(String(50), nullable=False, unique=True)
    item_name = Column(String(200), nullable=False)
    category = Column(String(20), default="RM")  # RM, FG
    uom = Column(String(20), nullable=False)  # PCS, MTR, KG, CONE
    hsn = Column(String(20), nullable=True)
    standard_rate = Column(Numeric(15, 4), default=0)
    cgst = Column(Numeric(10, 4), default=0)
    sgst = Column(Numeric(10, 4), default=0)
    igst = Column(Numeric(10, 4), default=0)
    preferred_supplier = Column(String(200), nullable=True)
    lead_time = Column(Integer, default=0)
    min_stock = Column(Numeric(15, 4), default=0)
    max_stock = Column(Numeric(15, 4), default=0)
    location = Column(String(200), nullable=True)
    extra_data = Column(JSON, nullable=True)
    status = Column(String(20), default="ACTIVE")  # ACTIVE, INACTIVE, OBSOLETE, REPLACED
    version = Column(Integer, default=1)
    version_of = Column(String(50), nullable=True)
    changed_at = Column(DateTime, nullable=True)
    changed_by = Column(String(100), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        Index('idx_inv_item_no', 'item_no'),
        Index('idx_inv_name', 'item_name'),
        Index('idx_inv_category', 'category'),
        Index('idx_inv_status', 'status'),
        Index('idx_inv_version_of', 'version_of'),
    )

# ==============================================================
# MODULE 3: MASTER FG - BOM Templates
# ==============================================================
class MasterFG(Base):
    __tablename__ = "master_fg"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    fg_code = Column(String(100), nullable=False, unique=True)
    design_name = Column(String(200), nullable=False)
    color = Column(String(50), nullable=False)
    status = Column(String(20), default="DRAFT")  # DRAFT, ACTIVE, OBSOLETE, REPLACED
    created_date = Column(DateTime, server_default=func.now())
    last_used = Column(DateTime, nullable=True)
    version = Column(Integer, default=1)
    version_of = Column(String(100), nullable=True)
    bom_items = Column(JSON, nullable=True)  # List of BOM items
    created_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime, onupdate=func.now())
    
    __table_args__ = (
        Index('idx_fg_design', 'design_name'),
        Index('idx_fg_color', 'color'),
        Index('idx_fg_status', 'status'),
    )

# ==============================================================
# MODULE 4: BUYER ORDERS
# ==============================================================
class BuyerOrder(Base):
    __tablename__ = "buyer_orders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    buyer_order_id = Column(String(50), nullable=False, unique=True, index=True)
    buyer_name = Column(String(200), nullable=False)
    buyer_order_no = Column(String(100), nullable=False)
    order_date = Column(DateTime, nullable=False)
    delivery_date = Column(DateTime, nullable=True)
    lead_time = Column(Integer, default=0)
    status = Column(String(30), default="DRAFT")
    total_fgs = Column(Integer, default=0)
    bom_status = Column(String(30), default="PENDING")
    rm_status = Column(String(30), default="PENDING")
    grn_status = Column(String(30), default="PENDING")
    issue_status = Column(String(30), default="PENDING")
    fg_production_status = Column(String(30), default="PENDING")
    current_stage = Column(String(50), default="BUYER_ORDER")
    version = Column(Integer, default=1)
    created_date = Column(DateTime, server_default=func.now())
    updated_date = Column(DateTime, onupdate=func.now())
    extra_data = Column(JSON, nullable=True)
    created_by = Column(String(100), nullable=True)
    
    __table_args__ = (
        Index('idx_bo_buyer', 'buyer_name'),
        Index('idx_bo_status', 'status'),
        Index('idx_bo_stage', 'current_stage'),
        Index('idx_bo_order_no', 'buyer_order_no'),
    )

# ==============================================================
# MODULE 5: ACTIVITY LEDGER (Immutable Audit Trail)
# ==============================================================
class ActivityLedger(Base):
    __tablename__ = "activity_ledger"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    fg_key = Column(String(100), nullable=False, index=True)
    activity_type = Column(String(50), nullable=False, index=True)
    status = Column(String(30), nullable=False, index=True)
    buyer_name = Column(String(200), nullable=True)
    buyer_order_no = Column(String(100), nullable=True)
    order_date = Column(DateTime, nullable=True)
    created_date = Column(DateTime, nullable=True)
    qty = Column(Numeric(15, 4), default=0)
    size = Column(String(20), nullable=True)
    color = Column(String(50), nullable=True)
    location = Column(String(200), nullable=True)
    extra_data = Column(JSON, nullable=True)
    workflow_position = Column(Float, default=0)
    version = Column(Integer, default=1)
    transaction_id = Column(String(50), nullable=True, index=True)
    
    __table_args__ = (
        Index('idx_ledger_bo', 'buyer_order_id', 'activity_type'),
        Index('idx_ledger_fg', 'fg_key', 'activity_type'),
        Index('idx_ledger_transaction', 'transaction_id'),
        # T22: expression indexes on JSONB fields for scoped lookups.
        Index('idx_ledger_bo_version', 'buyer_order_id', 'version'),
        Index('idx_ledger_bo_type_status', 'buyer_order_id', 'activity_type', 'status'),
        Index('idx_ledger_po_token', text("(extra_data->>'poToken')")),
        Index('idx_ledger_req_key', text("(extra_data->>'requirementKey')")),
    )

# ==============================================================
# MODULE 6: RM ORDERS (Purchase Orders)
# ==============================================================
class RMOrder(Base):
    __tablename__ = "rm_orders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    po_token = Column(String(50), nullable=False, unique=True, index=True)
    buyer_order_ids = Column(Text, nullable=True)  # Comma-separated
    supplier = Column(String(200), nullable=False)
    supplier_alias = Column(String(200), nullable=True)
    po_date = Column(DateTime, server_default=func.now())
    status = Column(String(30), default="DRAFT")
    total_items = Column(Integer, default=0)
    total_qty = Column(Numeric(15, 4), default=0)
    total_amount = Column(Numeric(15, 4), default=0)
    po_type = Column(String(20), default="REGULAR")  # REGULAR, SHORTFALL
    original_po_token = Column(String(50), nullable=True)
    shortfall_note = Column(Text, nullable=True)
    created_date = Column(DateTime, server_default=func.now())
    updated_date = Column(DateTime, onupdate=func.now())
    extra_data = Column(JSON, nullable=True)
    created_by = Column(String(100), nullable=True)
    
    __table_args__ = (
        Index('idx_rm_po_token', 'po_token'),
        Index('idx_rm_supplier', 'supplier'),
        Index('idx_rm_status', 'status'),
        Index('idx_rm_type', 'po_type'),
        Index('idx_rm_original_po', 'original_po_token'),
    )

# ==============================================================
# MODULE 7: INSPECTION RECORDS (RM & FG)
# ==============================================================
class InspectionRecord(Base):
    __tablename__ = "inspection_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    inspection_id = Column(String(50), nullable=False, unique=True, index=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    reference = Column(String(100), nullable=True)  # PO Token or FG Key
    inspection_type = Column(String(30), nullable=False)  # RAW_MATERIAL, FINISHED_GOODS
    date = Column(DateTime, server_default=func.now())
    inspector = Column(String(100), nullable=True)
    item = Column(String(200), nullable=False)
    quantity = Column(Numeric(15, 4), default=0)
    sample_size = Column(Numeric(15, 4), default=0)
    defects = Column(Numeric(15, 4), default=0)
    defect_type = Column(String(100), nullable=True)
    quantity_passed = Column(Numeric(15, 4), default=0)
    quantity_rejected = Column(Numeric(15, 4), default=0)
    status = Column(String(30), default="PENDING")  # PENDING, PASSED, REJECTED
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    created_by = Column(String(100), nullable=True)
    
    __table_args__ = (
        Index('idx_insp_bo', 'buyer_order_id'),
        Index('idx_insp_type', 'inspection_type'),
        Index('idx_insp_status', 'status'),
        Index('idx_insp_reference', 'reference'),
    )

# ==============================================================
# MODULE 8: INVENTORY SNAPSHOT (Materialized View)
# ==============================================================
class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshot"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    requirement_key = Column(String(200), nullable=False, unique=True, index=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    fg_key = Column(String(100), nullable=False, index=True)
    item_no = Column(String(50), nullable=True)
    item_name = Column(String(200), nullable=True)
    garment_size = Column(String(20), nullable=True)
    color = Column(String(50), nullable=True)
    supplier = Column(String(200), nullable=True)
    location = Column(String(200), nullable=True)
    extra_data = Column(JSON, nullable=True)
    total_required_qty = Column(Numeric(15, 4), default=0)
    total_grn_received_qty = Column(Numeric(15, 4), default=0)
    total_issued_qty = Column(Numeric(15, 4), default=0)
    current_stock = Column(Numeric(15, 4), default=0)
    pending_shortfall = Column(Numeric(15, 4), default=0)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_snapshot_bo', 'buyer_order_id'),
        Index('idx_snapshot_fg', 'fg_key'),
        Index('idx_snapshot_item', 'item_no'),
        Index('idx_snapshot_req', 'requirement_key'),
        # T22: per-order / per-FG aggregation.
        Index('idx_snapshot_bo_fg', 'buyer_order_id', 'fg_key'),
    )

# ==============================================================
# MODULE 9: INTERNAL FG ORDERS (Unit-wise Production)
# ==============================================================
class InternalFGOrder(Base):
    __tablename__ = "internal_fg_orders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    internal_order_id = Column(String(50), nullable=False, unique=True, index=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    fg_key = Column(String(100), nullable=False, index=True)
    unit_number = Column(Integer, default=1)
    quantity = Column(Numeric(15, 4), default=0)
    production_status = Column(String(30), default="PENDING")  # PENDING, IN_PROGRESS, COMPLETED
    worker_assigned = Column(String(100), nullable=True)
    line_assigned = Column(String(100), nullable=True)
    location = Column(String(200), nullable=True)
    extra_data = Column(JSON, nullable=True)
    created_date = Column(DateTime, server_default=func.now())
    updated_date = Column(DateTime, onupdate=func.now())
    parent_order = Column(String(50), nullable=True)
    created_by = Column(String(100), nullable=True)
    
    __table_args__ = (
        Index('idx_ifg_bo', 'buyer_order_id'),
        Index('idx_ifg_fg', 'fg_key'),
        Index('idx_ifg_status', 'production_status'),
    )

# ==============================================================
# MODULE 10: FG INVENTORY (Finished Goods)
# ==============================================================
class FGInventory(Base):
    __tablename__ = "fg_inventory"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    fg_key = Column(String(100), nullable=False, index=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    design_name = Column(String(200), nullable=True)
    color = Column(String(50), nullable=True)
    garment_size = Column(String(20), nullable=True)
    quantity_produced = Column(Numeric(15, 4), default=0)
    quantity_inspected = Column(Numeric(15, 4), default=0)
    quantity_passed = Column(Numeric(15, 4), default=0)
    quantity_rejected = Column(Numeric(15, 4), default=0)
    quantity_ready = Column(Numeric(15, 4), default=0)
    location = Column(String(200), nullable=True)
    extra_data = Column(JSON, nullable=True)
    status = Column(String(30), default="PRODUCED")  # PRODUCED, INSPECTED, READY, DISPATCHED
    batch_id = Column(String(50), nullable=True)
    production_date = Column(DateTime, nullable=True)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_fginv_fg', 'fg_key'),
        Index('idx_fginv_bo', 'buyer_order_id'),
        Index('idx_fginv_status', 'status'),
    )

# ==============================================================
# MODULE 11: WORKFLOW STATE (Token Tracking)
# ==============================================================
class WorkflowState(Base):
    __tablename__ = "workflow_state"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    token_id = Column(String(50), nullable=False, index=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    current_stage = Column(String(50), nullable=False)
    previous_stage = Column(String(50), nullable=True)
    status = Column(String(30), default="ACTIVE")
    processed_at = Column(DateTime, server_default=func.now())
    processed_by = Column(String(100), nullable=True)
    last_action = Column(String(50), nullable=True)
    
    __table_args__ = (
        Index('idx_ws_token', 'token_id'),
        Index('idx_ws_bo', 'buyer_order_id'),
        Index('idx_ws_stage', 'current_stage'),
    )

# ==============================================================
# MODULE 12: SYSTEM SETTINGS
# ==============================================================
class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), nullable=False, unique=True, index=True)
    config_value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, onupdate=func.now())
    updated_by = Column(String(100), nullable=True)
    
    __table_args__ = (
        Index('idx_settings_key', 'config_key'),
    )

# ==============================================================
# MODULE 13: USER (Authentication)
# ==============================================================
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(String(50), default="viewer")
    is_active = Column(Boolean, default=True)
    reset_token = Column(String(255), nullable=True)
    reset_token_expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    last_login = Column(DateTime, nullable=True)
    
    __table_args__ = (
        Index('idx_user_email', 'email'),
        Index('idx_user_role', 'role'),
    )

# ==============================================================
# MODULE 14: COSTING APPROVALS
# ==============================================================
class CostingApproval(Base):
    __tablename__ = "costing_approvals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    fg_key = Column(String(100), nullable=False, index=True)
    approval_status = Column(String(30), default="PENDING")  # PENDING, APPROVED, REJECTED
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    locked_rates = Column(JSON, nullable=True)
    bom_version = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    __table_args__ = (
        Index('idx_ca_buyer_order', 'buyer_order_id'),
        Index('idx_ca_status', 'approval_status'),
    )

# ==============================================================
# MODULE 15: SHORTFALL TRACKING
# ==============================================================
class ShortfallTracking(Base):
    __tablename__ = "shortfall_tracking"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    fg_key = Column(String(100), nullable=False, index=True)
    po_token = Column(String(50), nullable=False, index=True)
    requirement_key = Column(String(200), nullable=False, index=True)
    shortfall_quantity = Column(Numeric(15, 4), default=0)
    original_ordered = Column(Numeric(15, 4), default=0)
    received_quantity = Column(Numeric(15, 4), default=0)
    shortfall_status = Column(String(30), default="PENDING")  # PENDING, REORDERED, CANCELLED
    reorder_po_token = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    resolved_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('idx_st_buyer_order', 'buyer_order_id'),
        Index('idx_st_po_token', 'po_token'),
        Index('idx_st_status', 'shortfall_status'),
        Index('idx_st_requirement', 'requirement_key'),
    )

# ==============================================================
# MODULE 16: STAGE TRANSITIONS (Audit Trail)
# ==============================================================
class StageTransition(Base):
    __tablename__ = "stage_transitions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    from_stage = Column(String(50), nullable=False, index=True)
    to_stage = Column(String(50), nullable=False, index=True)
    transition_type = Column(String(30), nullable=False, index=True)  # PROCESS, CANCEL, APPROVE, REJECT
    triggered_by = Column(String(100), nullable=True)
    triggered_at = Column(DateTime, server_default=func.now())
    notes = Column(Text, nullable=True)
    transition_metadata = Column(JSON, nullable=True)
    
    __table_args__ = (
        Index('idx_stage_bo', 'buyer_order_id'),
        Index('idx_stage_from', 'from_stage'),
        Index('idx_stage_to', 'to_stage'),
        Index('idx_stage_type', 'transition_type'),
    )

# ==============================================================
# WORKFLOW TOKEN - Stage + Version + Locking
# ==============================================================
class WorkflowToken(Base):
    __tablename__ = "workflow_tokens"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    buyer_order_id = Column(String(50), nullable=False, unique=True, index=True)
    current_stage = Column(String(50), nullable=False)
    current_version = Column(Integer, default=1)
    status = Column(String(30), default="ACTIVE")  # ACTIVE, CANCELLED, CLOSED
    locked_by = Column(String(100), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    __table_args__ = (
        Index('idx_wf_token_bo', 'buyer_order_id'),
        Index('idx_wf_stage', 'current_stage'),
        Index('idx_wf_status', 'status'),
    )

# ==============================================================
# MODULE 17: FG INSPECTION RECORDS (AQL-based garment inspection)
# ==============================================================
class FGInspectionRecord(Base):
    __tablename__ = "fg_inspection_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    inspection_id = Column(String(50), nullable=False, unique=True, index=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    fg_key = Column(String(100), nullable=False, index=True)
    order_qty = Column(Numeric(15, 4), default=0)
    presented_qty = Column(Numeric(15, 4), default=0)
    inspected_qty = Column(Numeric(15, 4), default=0)
    minor_defects = Column(Integer, default=0)
    major_defects = Column(Integer, default=0)
    critical_defects = Column(Integer, default=0)
    status = Column(String(30), nullable=False, index=True)  # PASSED, FAILED
    inspector = Column(String(100), nullable=True)
    inspection_date = Column(DateTime, server_default=func.now())
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        Index('idx_fginsp_bo', 'buyer_order_id'),
        Index('idx_fginsp_fg', 'fg_key'),
        Index('idx_fginsp_status', 'status'),
    )

# ==============================================================
# MODULE 18: DISPATCH RECORDS (FG outward dispatch)
# ==============================================================
class DispatchRecord(Base):
    __tablename__ = "dispatch_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    dispatch_id = Column(String(50), nullable=False, unique=True, index=True)
    buyer_order_id = Column(String(50), nullable=False, index=True)
    buyer_order_no = Column(String(100), nullable=True)
    buyer_name = Column(String(200), nullable=True)
    invoice_no = Column(String(100), nullable=True)
    challan_no = Column(String(100), nullable=True)
    fg_key = Column(String(100), nullable=False, index=True)
    design_name = Column(String(200), nullable=True)
    color = Column(String(50), nullable=True)
    fg_qty = Column(Numeric(15, 4), default=0)
    dispatch_qty = Column(Numeric(15, 4), default=0)
    dispatched_by = Column(String(100), nullable=True)
    dispatched_at = Column(DateTime, server_default=func.now())
    remarks = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('idx_disp_bo', 'buyer_order_id'),
        Index('idx_disp_fg', 'fg_key'),
        Index('idx_disp_invoice', 'invoice_no'),
    )

# ==============================================================
# MODULE 19: SEQUENCE COUNTERS (concurrency-safe ID generation)
# ==============================================================
class SequenceCounter(Base):
    __tablename__ = "sequence_counters"

    name = Column(String(50), primary_key=True)
    value = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

# ==============================================================
# MODULE 20: PASSWORD RESET OTPs
# ==============================================================
class PasswordResetOTP(Base):
    __tablename__ = "password_reset_otps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, index=True)
    otp_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('idx_otp_email', 'email'),
        Index('idx_otp_expires', 'expires_at'),
    )
