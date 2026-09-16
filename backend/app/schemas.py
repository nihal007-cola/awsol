from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class Category(str, Enum):
    BUYER = "BUYER"
    SUPPLIER = "SUPPLIER"

class ActivityType(str, Enum):
    BUYER_ORDER = "BUYER_ORDER"
    BOM = "BOM"
    MATERIAL_REQUIREMENT = "MATERIAL_REQUIREMENT"
    RM_ORDER = "RM_ORDER"
    GRN = "GRN"
    ISSUE_RM = "ISSUE_RM"
    LIFECYCLE = "LIFECYCLE"

class Status(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    PROCESSED = "PROCESSED"
    CANCELLED = "CANCELLED"
    SAVED = "SAVED"
    ISSUED = "ISSUED"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    SKIPPED = "SKIPPED"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"
    ISSUANCE_PENDING = "ISSUANCE_PENDING"
    PARTIALLY_ISSUED = "PARTIALLY_ISSUED"
    LIFECYCLE = "LIFECYCLE"

# Master Data
class MasterDataBase(BaseModel):
    category: Category
    name: str
    gst_no: Optional[str] = None
    address: Optional[str] = None
    contact_person: Optional[str] = None
    contact_no: Optional[str] = None
    payment_term: Optional[str] = None

class MasterDataCreate(MasterDataBase):
    pass

class MasterDataResponse(MasterDataBase):
    id: str
    added_date: datetime
    status: str

    class Config:
        from_attributes = True

# Buyer Order
class OrderGridRequest(BaseModel):
    buyer_name: str
    buyer_gst: Optional[str] = None
    buyer_order_no: str
    order_date: str
    delivery_date: str
    lead_time: int
    no_of_fg: int

class SaveOrderRequest(BaseModel):
    fg_order_serial: str
    grid_data: List[List[Any]]

# BOM
class BOMItem(BaseModel):
    item_no: str
    item_name: str
    item_color: str
    item_size: str
    consumption: float
    uom: str
    size_sensitive: str = "No"
    hsn: Optional[str] = None
    rate: float
    supplier: str
    leadtime: float
    cgst: Optional[float] = 0
    sgst: Optional[float] = 0
    igst: Optional[float] = 0

class BOMSaveRequest(BaseModel):
    fg_key: str
    items: List[BOMItem]

# GRN
class GRNItem(BaseModel):
    po_token: str
    fg_key: str
    item_no: str
    garment_size: str
    item_name: str
    item_size: str
    color: str
    ordered_qty: float
    received_qty: float
    rate: float
    hsn: str
    uom: str
    cgst: float = 0
    sgst: float = 0
    igst: float = 0
    requirement_key: str

class GRNSaveRequest(BaseModel):
    po_token: str
    invoice_no: Optional[str] = None
    items: List[GRNItem]

# Issue RM
class IssueRMItem(BaseModel):
    item_no: str
    item_name: str
    garment_size: str
    item_size: str
    color: str
    required_qty: float
    issuing_qty: float
    uom: str
    requirement_key: str

class IssueRMSaveRequest(BaseModel):
    fg_key: str
    items: List[IssueRMItem]
