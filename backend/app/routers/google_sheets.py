from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Base, User
from ..auth import require_role

router = APIRouter(prefix="/api/google-sheets", tags=["Google Sheets"])


@router.get("/tables-list")
def list_tables(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """List all tables in the database with row counts. Admin only."""
    try:
        tables = {}
        for model in Base.__subclasses__():
            table_name = model.__tablename__
            try:
                count = db.query(model).count()
                tables[table_name] = count
            except Exception as e:
                tables[table_name] = str(e)
        return {"status": "success", "tables": tables}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/export-json")
def export_json(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Export all data as JSON. Admin only."""
    try:
        all_data = {}
        for model in Base.__subclasses__():
            table_name = model.__tablename__
            data = db.query(model).all()
            columns = [c.name for c in model.__table__.columns]
            rows = []
            for row in data:
                row_dict = {}
                for col in columns:
                    value = getattr(row, col)
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    row_dict[col] = value
                rows.append(row_dict)
            all_data[table_name] = rows
        return {"status": "success", "data": all_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}
