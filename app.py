from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil
import socket
from datetime import datetime

from pdf_processor import append_ticket_to_month_pdf, get_monthly_stats, PDFS_DIR

app = FastAPI(title="Escáner de Tickets Factura A")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=4404, detail="Plantilla no encontrada")
    return index_path.read_text(encoding="utf-8")

@app.post("/api/upload")
async def upload_ticket(
    file: UploadFile = File(...),
    month: str = Form(None),
    enhance: bool = Form(True)
):
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="El archivo subido está vacío")
            
        # Determinar nombre base para guardado
        filename_hint = file.filename or "ticket.jpg"
        
        result = append_ticket_to_month_pdf(
            image_bytes=content,
            filename_hint=filename_hint,
            month_str=month,
            enhance=enhance
        )
        return JSONResponse(content=result)
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

@app.get("/api/stats")
async def stats():
    monthly = get_monthly_stats()
    current_month_key = datetime.now().strftime("%Y_%m")
    current_stat = next((m for m in monthly if m["month_key"] == current_month_key), None)
    
    return {
        "current_month_key": current_month_key,
        "current_tickets_count": current_stat["pages"] if current_stat else 0,
        "monthly_files": monthly
    }

@app.get("/download/{filename}")
async def download_pdf(filename: str):
    file_path = PDFS_DIR / filename
    if not file_path.exists() or not file_path.name.startswith("Tickets_"):
        raise HTTPException(status_code=404, detail="Archivo PDF no encontrado")
        
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )
