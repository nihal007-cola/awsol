from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Base
import json

router = APIRouter(prefix="/api/google-sheets", tags=["Google Sheets"])

@router.get("/tables-list")
async def list_tables(db: Session = Depends(get_db)):
    """List all tables in the database"""
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
async def export_json(db: Session = Depends(get_db)):
    """Export all data as JSON"""
    try:
        all_data = {}
        for model in Base.__subclasses__():
            table_name = model.__tablename__
            data = db.query(model).all()
            if data:
                columns = [c.name for c in model.__table__.columns]
                table_data = []
                for row in data:
                    row_dict = {}
                    for col in columns:
                        value = getattr(row, col)
                        if hasattr(value, 'isoformat'):
                            value = value.isoformat()
                        row_dict[col] = value
                    table_data.append(row_dict)
                all_data[table_name] = table_data
            else:
                all_data[table_name] = []
        return {"status": "success", "data": all_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}
