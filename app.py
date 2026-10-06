from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from pathlib import Path
from datetime import datetime

from pdf_processor import (
    append_ticket_to_month_pdf,
    remove_last_page_from_pdf,
    delete_entire_month_pdf,
    get_monthly_stats,
    generate_zip_report,
    PDFS_DIR
)
from ticket_ocr import extract_data_from_image, get_monthly_summary, DATA_DIR
from excel_exporter import generate_excel_report, generate_csv_report
from gdrive_sync import restore_all_from_gdrive, sync_month_to_gdrive

app = FastAPI(title="Escáner de Tickets Factura A")

@app.on_event("startup")
async def startup_event():
    # El servidor inicia instantáneamente sin bloquear la cola de peticiones HTTP
    pass

BASE_DIR = Path(__file__).resolve().parent

def find_index_html() -> Path:
    possible_paths = [
        BASE_DIR / "index.html",
        Path.cwd() / "index.html",
        BASE_DIR / "templates" / "index.html",
        Path.cwd() / "templates" / "index.html"
    ]
    for p in possible_paths:
        if p.exists():
            return p
    return None

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = find_index_html()
    if not index_path:
        raise HTTPException(status_code=404, detail="Plantilla index.html no encontrada")
    return index_path.read_text(encoding="utf-8")

@app.get("/manifest.json")
async def manifest():
    manifest_path = BASE_DIR / "manifest.json"
    if manifest_path.exists():
        return FileResponse(manifest_path, media_type="application/manifest+json")
    return JSONResponse({
        "name": "CB Asesor Tickets & Gastos",
        "short_name": "CB Tickets",
        "description": "Escáner y gestor de tickets y gastos para CB Asesor",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#09090b",
        "theme_color": "#D4AF37",
        "icons": [
            {
                "src": "/icon-192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/icon-512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    })

@app.get("/favicon.ico")
async def get_favicon_ico():
    ico_path = BASE_DIR / "favicon.ico"
    if ico_path.exists():
        return FileResponse(ico_path, media_type="image/x-icon")
    return Response(status_code=404)

@app.get("/favicon.svg")
async def get_favicon_svg():
    svg_path = BASE_DIR / "favicon.svg"
    if svg_path.exists():
        return FileResponse(svg_path, media_type="image/svg+xml")
    return Response(status_code=404)

@app.get("/icon-192.png")
async def get_icon_192():
    p = BASE_DIR / "icon-192.png"
    if p.exists():
        return FileResponse(p, media_type="image/png")
    return Response(status_code=404)

@app.get("/icon-512.png")
async def get_icon_512():
    p = BASE_DIR / "icon-512.png"
    if p.exists():
        return FileResponse(p, media_type="image/png")
    return Response(status_code=404)

@app.get("/apple-touch-icon.png")
async def get_apple_touch_icon():
    p = BASE_DIR / "apple-touch-icon.png"
    if p.exists():
        return FileResponse(p, media_type="image/png")
    return Response(status_code=404)

@app.get("/sw.js")
async def service_worker():
    sw_path = BASE_DIR / "sw.js"
    if sw_path.exists():
        return FileResponse(sw_path, media_type="application/javascript")
    sw_code = """
    self.addEventListener('install', (e) => {
        self.skipWaiting();
    });
    self.addEventListener('activate', (e) => {
        e.waitUntil(clients.claim());
    });
    self.addEventListener('fetch', (e) => {});
    """
    return Response(content=sw_code, media_type="application/javascript")

@app.post("/api/scan-ocr-preview")
async def scan_ocr_preview(file: UploadFile = File(...)):
    """Pre-lectura ultra rápida para auto-completar todos los campos antes de guardar."""
    try:
        content = await file.read()
        if not content:
            return JSONResponse(content={"vendor": "", "total": 0.0, "subtotal": 0.0, "iva_21": 0.0, "iva_10_5": 0.0, "iva_27": 0.0, "cuit": "", "date": ""})
        data = extract_data_from_image(content, filename_hint=file.filename or "")
        return JSONResponse(content={
            "vendor": data.get("vendor", ""),
            "total": data.get("total", 0.0),
            "subtotal": data.get("subtotal", 0.0),
            "iva_21": data.get("iva_21", 0.0),
            "iva_10_5": data.get("iva_10_5", 0.0),
            "iva_27": data.get("iva_27", 0.0),
            "cuit": data.get("cuit", ""),
            "date": data.get("date", ""),
            "items": data.get("items", [])
        })
    except Exception as e:
        return JSONResponse(content={"vendor": "", "total": 0.0, "error": str(e)})

@app.post("/api/upload")
async def upload_ticket(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    month: str = Form(None),
    enhance: bool = Form(True),
    vendor: str = Form(None),
    total: float = Form(None),
    cuit: str = Form(None),
    date: str = Form(None),
    subtotal: float = Form(None),
    iva_21: float = Form(None),
    iva_10_5: float = Form(None),
    iva_27: float = Form(None),
    user_email: str = Form(None),
    items_json: str = Form(None)
):
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="El archivo subido está vacío")
            
        filename_hint = file.filename or "ticket.jpg"
        
        parsed_items = None
        if items_json:
            try:
                import json
                parsed_items = json.loads(items_json)
            except Exception:
                pass

        result = append_ticket_to_month_pdf(
            image_bytes=content,
            filename_hint=filename_hint,
            month_str=month,
            enhance=enhance,
            user_vendor=vendor,
            user_total=total,
            user_cuit=cuit,
            user_date=date,
            user_subtotal=subtotal,
            user_iva_21=iva_21,
            user_iva_10_5=iva_10_5,
            user_iva_27=iva_27,
            user_email=user_email,
            user_items=parsed_items
        )
        
        month_key = result.get("month")
        if month_key:
            background_tasks.add_task(sync_month_to_gdrive, month_key, PDFS_DIR, DATA_DIR, user_email)
            
        return JSONResponse(content=result)
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

@app.get("/api/expenses/{month}")
async def get_expenses(month: str, user_email: str = None):
    summary = get_monthly_summary(month, user_email=user_email)
    return JSONResponse(content=summary)

@app.get("/download/excel/{month}")
async def download_excel(month: str, user_email: str = None):
    try:
        excel_bytes = generate_excel_report(month)
        filename = f"Gastos_{month}.xlsx"
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/csv/{month}")
async def download_csv(month: str, user_email: str = None):
    try:
        csv_bytes = generate_csv_report(month)
        filename = f"Libro_IVA_Compras_{month}.csv"
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/zip/{month}")
async def download_zip(month: str, user_email: str = None):
    try:
        zip_bytes = generate_zip_report(month, user_email=user_email)
        filename = f"Fotos_Tickets_{month}.zip"
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/delete-last-ticket")
async def delete_last_ticket(month: str = Form(...), user_email: str = Form(None), background_tasks: BackgroundTasks = BackgroundTasks()):
    try:
        res = remove_last_page_from_pdf(month, user_email=user_email)
        month_key = res.get("month")
        if month_key:
            background_tasks.add_task(sync_month_to_gdrive, month_key, PDFS_DIR, DATA_DIR, user_email)
        return JSONResponse(content=res)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.post("/api/delete-month-pdf")
async def delete_month_pdf(month: str = Form(...), user_email: str = Form(None)):
    try:
        res = delete_entire_month_pdf(month, user_email=user_email)
        return JSONResponse(content=res)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.get("/api/stats")
async def stats(background_tasks: BackgroundTasks, user_email: str = None):
    monthly = get_monthly_stats(user_email=user_email)
    current_month_key = datetime.now().strftime("%Y_%m")
    current_stat = next((m for m in monthly if m["month_key"] == current_month_key), None)
    
    # Sincronización diferida en segundo plano sin ralentizar la respuesta HTTP
    background_tasks.add_task(restore_all_from_gdrive, PDFS_DIR, DATA_DIR, user_email)
    
    return {
        "current_month_key": current_month_key,
        "current_tickets_count": current_stat["pages"] if current_stat else 0,
        "monthly_files": monthly
    }

@app.get("/download/{filename}")
async def download_pdf(filename: str, user_email: str = None):
    from pdf_processor import get_user_pdf_dir
    target_pdf_dir = get_user_pdf_dir(user_email)
    file_path = target_pdf_dir / filename
    
    if not file_path.exists() or not file_path.name.startswith("Tickets_"):
        raise HTTPException(status_code=404, detail="Archivo PDF no encontrado")
        
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=filename,
        headers={
            "Content-Disposition": f"inline; filename={filename}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )
        
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=filename,
        headers={
            "Content-Disposition": f"inline; filename={filename}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )
