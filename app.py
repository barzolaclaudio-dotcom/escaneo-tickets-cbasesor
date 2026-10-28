from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from pathlib import Path
from datetime import datetime
import io
import zipfile
import logging

logger = logging.getLogger("app")

from pdf_processor import (
    append_ticket_to_month_pdf,
    remove_last_page_from_pdf,
    delete_entire_month_pdf,
    get_monthly_stats,
    generate_zip_report,
    PDFS_DIR
)
from ticket_ocr import extract_data_from_image, get_monthly_summary, DATA_DIR, sanitize_email
from excel_exporter import generate_excel_report, generate_csv_report
from gdrive_sync import restore_all_from_gdrive, sync_month_to_gdrive
from card_processor import (
    parse_credit_card_pdf,
    load_monthly_cards,
    add_card_to_month,
    delete_card_from_month
)
from bank_processor import (
    parse_bank_or_loan_pdf,
    load_monthly_bank_data,
    add_bank_doc_to_month,
    delete_bank_doc_from_month
)
from investment_processor import (
    parse_investment_pdf,
    load_monthly_investments,
    add_investment_to_month,
    delete_investment_from_month
)
from tax_processor import (
    parse_tax_or_vep_pdf,
    load_monthly_taxes,
    add_tax_doc_to_month,
    delete_tax_doc_from_month
)
from pydantic import BaseModel
from typing import Optional, List
from fastapi import Request, Header

import auth_db
import email_sender

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "Documentos_Mensuales"
DOCS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Escáner de Tickets Factura A")

class RegisterRequest(BaseModel):
    name: str
    email: str

class VerifyCodeRequest(BaseModel):
    email: str
    code: str

class SetPasswordRequest(BaseModel):
    name: str
    email: str
    code: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str

class UpdateProfileRequest(BaseModel):
    name: str
    accountant_email: Optional[str] = ""
    accountant_name: Optional[str] = ""

class SendAccountantReportRequest(BaseModel):
    month: str
    include_excel: bool = True
    include_pdf_tickets: bool = False
    selected_docs: Optional[list] = []
    custom_message: Optional[str] = ""

def get_auth_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization or not isinstance(authorization, str):
        return None
    token = authorization.replace("Bearer ", "").strip()
    return auth_db.validate_session(token)

@app.post("/api/auth/register-request")
async def auth_register_request(req: RegisterRequest):
    name = req.name.strip()
    email = req.email.strip().lower()
    if not name or not email or "@" not in email:
        return JSONResponse(status_code=400, content={"success": False, "error": "Nombre y correo válido requeridos"})
    
    if auth_db.user_exists(email):
        return JSONResponse(status_code=400, content={
            "success": False, 
            "error": "Este correo ya está registrado. Por favor selecciona Iniciar Sesión."
        })
    
    code = auth_db.create_verification_code(email, name)
    email_res = email_sender.send_verification_email(email, name, code)
    
    return {
        "success": True,
        "email": email,
        "name": name,
        "dev_mode": email_res.get("dev_mode", False),
        "dev_code": email_res.get("code") if email_res.get("dev_mode") else None,
        "message": "Código de verificación enviado."
    }

@app.post("/api/auth/verify-code")
async def auth_verify_code(req: VerifyCodeRequest):
    email = req.email.strip().lower()
    code = req.code.strip()
    if not auth_db.verify_code(email, code):
        return JSONResponse(status_code=400, content={"success": False, "error": "Código incorrecto o vencido (validez: 15 min)"})
    return {"success": True, "message": "Código validado correctamente."}

@app.post("/api/auth/set-password")
async def auth_set_password(req: SetPasswordRequest):
    name = req.name.strip()
    email = req.email.strip().lower()
    code = req.code.strip()
    password = req.password.strip()
    
    if len(password) < 4:
        return JSONResponse(status_code=400, content={"success": False, "error": "La contraseña debe tener al menos 4 caracteres"})
        
    result = auth_db.register_user(name, email, password, code)
    if not result:
        return JSONResponse(status_code=400, content={"success": False, "error": "No se pudo registrar el usuario. Código inválido o correo en uso."})
        
    return {
        "success": True,
        "token": result["token"],
        "user": {
            "name": result["name"],
            "email": result["email"]
        }
    }

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    email = req.email.strip().lower()
    password = req.password.strip()
    result = auth_db.authenticate_user(email, password)
    if not result:
        return JSONResponse(status_code=401, content={"success": False, "error": "Correo o contraseña incorrectos"})
    return {
        "success": True,
        "token": result["token"],
        "user": {
            "name": result["name"],
            "email": result["email"]
        }
    }

@app.post("/api/auth/forgot-password")
async def auth_forgot_password(req: ForgotPasswordRequest):
    email = req.email.strip().lower()
    if not email or "@" not in email:
        return JSONResponse(status_code=400, content={"success": False, "error": "Correo electrónico inválido"})
    user = auth_db.get_user_by_email(email)
    if not user:
        return JSONResponse(status_code=404, content={"success": False, "error": "No existe una cuenta registrada con este correo electrónico."})
    code = auth_db.create_verification_code(email, user["name"])
    email_res = email_sender.send_verification_email(email, user["name"], code, is_recovery=True)
    return {
        "success": True,
        "email": email,
        "dev_mode": email_res.get("dev_mode", False),
        "dev_code": email_res.get("code") if email_res.get("dev_mode") else None,
        "message": "Código de recuperación enviado a tu correo."
    }

@app.post("/api/auth/reset-password")
async def auth_reset_password(req: ResetPasswordRequest):
    email = req.email.strip().lower()
    code = req.code.strip()
    new_password = req.new_password.strip()
    if len(new_password) < 4:
        return JSONResponse(status_code=400, content={"success": False, "error": "La contraseña debe tener al menos 4 caracteres"})
    user = auth_db.reset_password(email, new_password, code)
    if not user:
        return JSONResponse(status_code=400, content={"success": False, "error": "Código incorrecto o vencido (validez: 15 min)"})
    return {
        "success": True,
        "token": user["token"],
        "user": {
            "name": user["name"],
            "email": user["email"]
        },
        "message": "Contraseña actualizada exitosamente."
    }

@app.get("/api/auth/me")
async def auth_me(authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Sesión inválida o expirada"})
    return {"success": True, "user": user}

@app.post("/api/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(None)):
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        auth_db.delete_session(token)
    return {"success": True}

@app.get("/api/user/profile")
async def get_profile(authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Sesión inválida o expirada"})
    return {"success": True, "profile": user}

@app.post("/api/user/profile")
async def update_profile(req: UpdateProfileRequest, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Sesión inválida o expirada"})
    
    name = req.name.strip()
    if not name:
        return JSONResponse(status_code=400, content={"success": False, "error": "El nombre no puede estar vacío"})
    
    ok = auth_db.update_user_profile(
        user_id=user["user_id"],
        name=name,
        accountant_email=req.accountant_email or "",
        accountant_name=req.accountant_name or ""
    )
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "error": "No se pudo actualizar el perfil"})
    
    updated_user = auth_db.validate_session(authorization.replace("Bearer ", "").strip())
    return {"success": True, "user": updated_user}

def get_user_month_docs_dir(user_email: str, month: str) -> Path:
    safe_email = sanitize_email(user_email)
    month_key = month.replace("-", "_")
    target_dir = DOCS_DIR / safe_email / month_key
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir

@app.get("/api/documents/{month}")
async def list_month_documents(month: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    
    docs_dir = get_user_month_docs_dir(user["email"], month)
    doc_files = []
    if docs_dir.exists():
        for f in sorted(docs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                size_kb = round(f.stat().st_size / 1024, 1)
                name_l = f.name.lower()
                cat = "banco" if any(w in name_l for w in ["banco", "extracto", "cuenta", "galicia", "santander", "bbva", "macro", "nacion", "resumen_cta"]) else \
                      ("tarjeta" if any(w in name_l for w in ["tarjeta", "visa", "master", "amex", "credito"]) else \
                      ("prestamo" if any(w in name_l for w in ["prestamo", "cuota", "credito", "mutuo", "financiacion"]) else "otro"))
                doc_files.append({
                    "name": f.name,
                    "size_kb": size_kb,
                    "category": cat,
                    "uploaded_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
                })
    
    summary = get_monthly_summary(month, user_email=user["email"])
    has_expenses = len(summary.get("tickets", [])) > 0
    safe_email = sanitize_email(user["email"])
    pdf_user_path = PDFS_DIR / safe_email / f"Tickets_{month.replace('-', '_')}.pdf"
    pdf_root_path = PDFS_DIR / f"Tickets_{month.replace('-', '_')}.pdf"
    has_pdf = pdf_user_path.exists() or pdf_root_path.exists()

    return {
        "success": True,
        "month": month,
        "documents": doc_files,
        "has_excel": has_expenses,
        "tickets_count": len(summary.get("tickets", [])),
        "has_pdf_tickets": has_pdf
    }

@app.post("/api/documents/{month}/upload")
async def upload_month_document(
    month: str, 
    file: UploadFile = File(...), 
    category: str = Form("otro"),
    authorization: Optional[str] = Header(None)
):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    
    docs_dir = get_user_month_docs_dir(user["email"], month)
    clean_name = Path(file.filename).name.replace(" ", "_")
    dest_path = docs_dir / clean_name
    
    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)
        
    return {
        "success": True, 
        "filename": clean_name, 
        "size_kb": round(len(content) / 1024, 1),
        "message": f"Archivo '{clean_name}' adjuntado correctamente al mes {month}."
    }

@app.delete("/api/documents/{month}/{filename}")
async def delete_month_document(month: str, filename: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    
    clean_name = Path(filename).name
    docs_dir = get_user_month_docs_dir(user["email"], month)
    target = docs_dir / clean_name
    if target.exists() and target.is_file():
        target.unlink()
        return {"success": True, "message": "Documento eliminado."}
    return JSONResponse(status_code=404, content={"success": False, "error": "Archivo no encontrado."})

@app.get("/api/documents/{month}/{filename}/download")
async def download_month_document(month: str, filename: str, token: Optional[str] = None, authorization: Optional[str] = Header(None)):
    auth_header = authorization or (f"Bearer {token}" if token else None)
    user = get_auth_user(auth_header)
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    clean_name = Path(filename).name
    docs_dir = get_user_month_docs_dir(user["email"], month)
    target = docs_dir / clean_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path=str(target), filename=clean_name)

# -------------------------------------------------------------
# Endpoints de Tarjetas de Crédito y Débito (Etapa 1)
# -------------------------------------------------------------
@app.post("/api/cards/{month}/upload-and-parse")
async def upload_and_parse_card(
    month: str,
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    
    content = await file.read()
    if not content:
        return JSONResponse(status_code=400, content={"success": False, "error": "Archivo vacío"})
        
    filename = file.filename or "resumen.pdf"
    clean_name = Path(filename).name.replace(" ", "_")
    
    # 1. Guardar copia física en la carpeta de documentos del usuario
    docs_dir = get_user_month_docs_dir(user["email"], month)
    dest_path = docs_dir / clean_name
    try:
        with open(dest_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"Error guardando archivo físico de tarjeta: {e}")

    # 2. Parsear con PyMuPDF + Gemini
    parsed = parse_credit_card_pdf(content, filename_hint=clean_name)
    if not parsed.get("success"):
        return JSONResponse(status_code=422, content={"success": False, "error": parsed.get("error", "Error procesando el resumen")})
        
    # 3. Guardar en JSON mensual
    card_saved = add_card_to_month(month, parsed, user["email"])
    return {"success": True, "card": card_saved, "message": f"Resumen de {card_saved.get('marca', 'Tarjeta')} procesado con éxito."}

@app.get("/api/cards/{month}")
async def get_monthly_cards_api(month: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    cards = load_monthly_cards(month, user["email"])
    return {"success": True, "cards": cards}

@app.delete("/api/cards/{month}/{card_id}")
async def delete_monthly_card_api(month: str, card_id: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    ok = delete_card_from_month(month, card_id, user["email"])
    return {"success": ok}

# -------------------------------------------------------------
# Endpoints de Extractos Bancarios y Cuotas de Préstamos (Etapa 2)
# -------------------------------------------------------------
@app.post("/api/bank/{month}/upload-and-parse")
async def upload_and_parse_bank_doc(
    month: str,
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    
    content = await file.read()
    if not content:
        return JSONResponse(status_code=400, content={"success": False, "error": "Archivo vacío"})
        
    filename = file.filename or "documento_bancario.pdf"
    clean_name = Path(filename).name.replace(" ", "_")
    
    # 1. Guardar copia física en la carpeta de documentos del usuario
    docs_dir = get_user_month_docs_dir(user["email"], month)
    dest_path = docs_dir / clean_name
    try:
        with open(dest_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"Error guardando archivo físico bancario: {e}")

    # 2. Parsear con PyMuPDF + Gemini
    parsed = parse_bank_or_loan_pdf(content, filename_hint=clean_name)
    if not parsed.get("success"):
        return JSONResponse(status_code=422, content={"success": False, "error": parsed.get("error", "Error procesando el documento bancario")})
        
    # 3. Guardar en JSON mensual
    doc_saved = add_bank_doc_to_month(month, parsed, user["email"])
    tipo_desc = "Comprobante de Cuota/Préstamo" if doc_saved.get("tipo_documento") == "cuota_prestamo" else "Extracto Bancario"
    return {"success": True, "bank_doc": doc_saved, "message": f"{tipo_desc} de {doc_saved.get('entidad', 'Banco')} procesado con éxito."}

@app.get("/api/bank/{month}")
async def get_monthly_bank_docs_api(month: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    docs = load_monthly_bank_data(month, user["email"])
    return {"success": True, "bank_docs": docs}

@app.delete("/api/bank/{month}/{doc_id}")
async def delete_monthly_bank_doc_api(month: str, doc_id: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    ok = delete_bank_doc_from_month(month, doc_id, user["email"])
    return {"success": ok}

# -------------------------------------------------------------
# Endpoints de Inversiones, Cauciones y Mercado de Capitales (Etapa 3)
# -------------------------------------------------------------
@app.post("/api/investments/{month}/upload-and-parse")
async def upload_and_parse_investment(
    month: str,
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    
    content = await file.read()
    if not content:
        return JSONResponse(status_code=400, content={"success": False, "error": "Archivo vacío"})
        
    filename = file.filename or "boleto_inversion.pdf"
    clean_name = Path(filename).name.replace(" ", "_")
    
    # 1. Guardar copia física en la carpeta de documentos del usuario
    docs_dir = get_user_month_docs_dir(user["email"], month)
    dest_path = docs_dir / clean_name
    try:
        with open(dest_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"Error guardando archivo físico de inversión: {e}")

    # 2. Parsear con PyMuPDF + Gemini
    parsed = parse_investment_pdf(content, filename_hint=clean_name)
    if not parsed.get("success"):
        return JSONResponse(status_code=422, content={"success": False, "error": parsed.get("error", "Error procesando el comprobante bursátil")})
        
    # 3. Guardar en JSON mensual
    inv_saved = add_investment_to_month(month, parsed, user["email"])
    return {"success": True, "investment": inv_saved, "message": f"Operación de {inv_saved.get('especie', 'Inversión')} en {inv_saved.get('entidad', 'ALyC')} procesada con éxito."}

@app.get("/api/investments/{month}")
async def get_monthly_investments_api(month: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    investments = load_monthly_investments(month, user["email"])
    return {"success": True, "investments": investments}

@app.delete("/api/investments/{month}/{inv_id}")
async def delete_monthly_investment_api(month: str, inv_id: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    ok = delete_investment_from_month(month, inv_id, user["email"])
    return {"success": ok}

# -------------------------------------------------------------
# Endpoints de Retenciones y VEPs Impositivos (Etapa 4)
# -------------------------------------------------------------
@app.post("/api/taxes/{month}/upload-and-parse")
async def upload_and_parse_tax_doc(
    month: str,
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    
    content = await file.read()
    if not content:
        return JSONResponse(status_code=400, content={"success": False, "error": "Archivo vacío"})
        
    filename = file.filename or "comprobante_fiscal.pdf"
    clean_name = Path(filename).name.replace(" ", "_")
    
    # 1. Guardar copia física en la carpeta de documentos del usuario
    docs_dir = get_user_month_docs_dir(user["email"], month)
    dest_path = docs_dir / clean_name
    try:
        with open(dest_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"Error guardando archivo físico tributario: {e}")

    # 2. Parsear con PyMuPDF + Gemini
    parsed = parse_tax_or_vep_pdf(content, filename_hint=clean_name)
    if not parsed.get("success"):
        return JSONResponse(status_code=422, content={"success": False, "error": parsed.get("error", "Error procesando el comprobante impositivo")})
        
    # 3. Guardar en JSON mensual
    tax_saved = add_tax_doc_to_month(month, parsed, user["email"])
    tipo_desc = "Certificado de Retención" if tax_saved.get("tipo_documento") == "certificado_retencion" else "Pago de VEP"
    entidad_desc = tax_saved.get("agente_retencion_nombre") or tax_saved.get("organismo") or "AFIP/ARCA"
    return {"success": True, "tax_doc": tax_saved, "message": f"{tipo_desc} ({entidad_desc}) procesado con éxito."}

@app.get("/api/taxes/{month}")
async def get_monthly_taxes_api(month: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    tax_docs = load_monthly_taxes(month, user["email"])
    return {"success": True, "taxes": tax_docs}

@app.delete("/api/taxes/{month}/{doc_id}")
async def delete_monthly_tax_doc_api(month: str, doc_id: str, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "No autorizado"})
    ok = delete_tax_doc_from_month(month, doc_id, user["email"])
    return {"success": ok}

@app.post("/api/user/send-accountant-report")
async def send_accountant_report(req: SendAccountantReportRequest, authorization: Optional[str] = Header(None)):
    user = get_auth_user(authorization)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Sesión inválida o expirada"})
    
    accountant_email = (user.get("accountant_email") or "").strip()
    if not accountant_email or "@" not in accountant_email:
        return JSONResponse(status_code=400, content={
            "success": False, 
            "error": "No tienes configurado el correo de tu contador. Por favor agrégalo en Configuración."
        })
    
    month = req.month.strip()
    summary = get_monthly_summary(month, user_email=user["email"])
    
    attachments_list = []
    
    # 1. Planilla Excel de comprobantes e IVA
    if req.include_excel:
        excel_bytes = generate_excel_report(month, user_email=user["email"])
        if excel_bytes:
            excel_filename = f"reporte_comprobantes_{month}_{user['name'].replace(' ', '_')}.xlsx"
            attachments_list.append({"filename": excel_filename, "content": excel_bytes})
            
    # 2. PDF con las fotos de comprobantes escaneados
    if req.include_pdf_tickets:
        safe_email = sanitize_email(user["email"])
        pdf_path = PDFS_DIR / safe_email / f"Tickets_{month.replace('-', '_')}.pdf"
        if not pdf_path.exists():
            pdf_path = PDFS_DIR / f"Tickets_{month.replace('-', '_')}.pdf"
        if pdf_path.exists():
            with open(pdf_path, "rb") as f:
                attachments_list.append({
                    "filename": f"Tickets_Escaneados_{month}.pdf",
                    "content": f.read()
                })
                
    # 3. Documentos adicionales seleccionados (bancarios, tarjetas, préstamos)
    docs_dir = get_user_month_docs_dir(user["email"], month)
    selected_docs = req.selected_docs or []
    for doc_name in selected_docs:
        clean_name = Path(doc_name).name
        target_file = docs_dir / clean_name
        if target_file.exists() and target_file.is_file():
            with open(target_file, "rb") as f:
                attachments_list.append({
                    "filename": clean_name,
                    "content": f.read()
                })
                
    if not attachments_list:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": "Debes seleccionar al menos un archivo para enviar a tu contador."
        })
    
    res = email_sender.send_accountant_report_email(
        to_email=accountant_email,
        user_name=user["name"],
        user_email=user["email"],
        month=month,
        stats={
            "total_spent": summary.get("total_spent", 0.0),
            "total_subtotal": summary.get("total_subtotal", 0.0),
            "total_iva": summary.get("total_iva", 0.0),
            "total_iibb": summary.get("total_iibb", 0.0),
            "total_tickets": len(summary.get("tickets", []))
        },
        attachments=attachments_list,
        custom_message=req.custom_message or ""
    )
    return res


@app.on_event("startup")
async def startup_event():
    # El servidor inicia instantáneamente sin bloquear la cola de peticiones HTTP
    pass

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Endpoint liviano para monitores externos (mantiene el servicio activo)."""
    return {"status": "ok"}

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
            "percepcion_iibb": data.get("percepcion_iibb", 0.0),
            "percepcion_iibb_jurisdiccion": data.get("percepcion_iibb_jurisdiccion", ""),
            "percepcion_iva": data.get("percepcion_iva", 0.0),
            "impuestos_internos": data.get("impuestos_internos", 0.0),
            "invoice_number": data.get("invoice_number", ""),
            "invoice_type": data.get("invoice_type", "Factura A"),
            "cae": data.get("cae", ""),
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
    percepcion_iibb: float = Form(None),
    percepcion_iibb_jurisdiccion: str = Form(None),
    percepcion_iva: float = Form(None),
    impuestos_internos: float = Form(None),
    invoice_number: str = Form(None),
    invoice_type: str = Form(None),
    cae: str = Form(None),
    user_email: str = Form(None),
    items_json: str = Form(None),
    force: bool = Form(False)
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
            user_items=parsed_items,
            force=force,
            save_pdf=True,
            user_percepcion_iibb=percepcion_iibb,
            user_percepcion_iibb_jurisdiccion=percepcion_iibb_jurisdiccion,
            user_percepcion_iva=percepcion_iva,
            user_impuestos_internos=impuestos_internos,
            user_invoice_number=invoice_number,
            user_invoice_type=invoice_type,
            user_cae=cae
        )
        
        month_key = result.get("month")
        if month_key and result.get("success"):
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
        excel_bytes = generate_excel_report(month, user_email=user_email)
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
        csv_bytes = generate_csv_report(month, user_email=user_email)
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

@app.get("/download/accountant-pack/{month}")
async def download_accountant_pack(
    month: str, 
    token: Optional[str] = None, 
    user_email: Optional[str] = None, 
    authorization: Optional[str] = Header(None)
):
    """
    Descarga el Paquete Contable Completo del Mes en formato ZIP:
    - Gastos_{Mes}_{Año}.xlsx (Excel profesional con Resumen, IVA Compras y Productos)
    - Libro_IVA_Compras_{Mes}_{Año}.csv (para importar en sistemas contables)
    - Tickets_Comprobantes_{Mes}_{Año}.pdf (PDF con todos los tickets/facturas escaneados)
    - Documentos del Período (Extractos bancarios, resúmenes de tarjetas, cuotas de préstamos, etc.)
    - RESUMEN_CIERRE.txt (resumen ejecutivo de totales)
    """
    try:
        auth_str = authorization if isinstance(authorization, str) else None
        auth_header = auth_str or (f"Bearer {token}" if token else None)
        user = get_auth_user(auth_header) if auth_header else None
        email = user["email"] if user else (user_email or "").strip()
        user_name = user["name"] if user else "Usuario"
        
        month_key = month.replace("-", "_")
        parts = month_key.split("_")
        meses_nombres = {
            "01": "Octubre" if False else "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
            "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
            "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
        }
        if len(parts) == 2 and parts[1] in meses_nombres:
            month_label = f"{meses_nombres[parts[1]]}_{parts[0]}"
        else:
            month_label = month_key
            
        zip_filename = f"Contador_{month_label}.zip"
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            summary = get_monthly_summary(month_key, user_email=email)
            
            # 1. Planilla Excel institucional CB Asesor
            try:
                excel_bytes = generate_excel_report(month_key, user_email=email)
                if excel_bytes:
                    zip_file.writestr(f"Gastos_{month_label}.xlsx", excel_bytes)
            except Exception as e:
                logger.error(f"Error generando Excel para zip contador: {e}")
                
            # 2. Libro IVA Compras en CSV
            try:
                csv_bytes = generate_csv_report(month_key, user_email=email)
                if csv_bytes:
                    zip_file.writestr(f"Libro_IVA_Compras_{month_label}.csv", csv_bytes)
            except Exception as e:
                logger.error(f"Error generando CSV para zip contador: {e}")
                
            # 3. PDF unificado de tickets y facturas escaneados
            try:
                safe_email = sanitize_email(email) if email else ""
                pdf_path = None
                if safe_email:
                    pdf_path = PDFS_DIR / safe_email / f"Tickets_{month_key}.pdf"
                if not pdf_path or not pdf_path.exists():
                    pdf_path = PDFS_DIR / f"Tickets_{month_key}.pdf"
                    
                if pdf_path.exists():
                    with open(pdf_path, "rb") as f:
                        zip_file.writestr(f"Tickets_Comprobantes_{month_label}.pdf", f.read())
            except Exception as e:
                logger.error(f"Error adjuntando PDF para zip contador: {e}")
                
            # 4. Documentos adicionales del período (Bancos, Tarjetas, Préstamos, Boletos)
            if email:
                docs_dir = get_user_month_docs_dir(email, month_key)
                if docs_dir.exists():
                    for doc_file in sorted(docs_dir.glob("*")):
                        if doc_file.is_file():
                            try:
                                with open(doc_file, "rb") as f:
                                    zip_file.writestr(doc_file.name, f.read())
                            except Exception as e:
                                logger.error(f"Error agregando doc {doc_file.name} al zip: {e}")
                                
            # 5. Resumen Ejecutivo de Cierre
            resumen_txt = (
                f"====================================================\n"
                f" CB ASESOR - PAQUETE CONTABLE MENSUAL\n"
                f" Período: {month_label.replace('_', ' ')}\n"
                f" Contribuyente: {user_name} ({email if email else 'Local'})\n"
                f" Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                f"====================================================\n\n"
                f"RESUMEN FISCAL DEL PERÍODO:\n"
                f"- Total Gastado:            $ {summary.get('total_spent', 0.0):,.2f}\n"
                f"- Subtotal Neto Gravado:    $ {summary.get('total_subtotal', 0.0):,.2f}\n"
                f"- Total IVA Crédito Fiscal: $ {summary.get('total_iva', 0.0):,.2f}\n"
                f"- Percepciones IIBB:        $ {summary.get('total_percepcion_iibb', 0.0):,.2f}\n"
                f"- Percepciones IVA:         $ {summary.get('total_percepcion_iva', 0.0):,.2f}\n"
                f"- Cantidad de Comprobantes: {summary.get('tickets_count', 0)}\n\n"
                f"ARCHIVOS INCLUIDOS EN ESTE PAQUETE:\n"
                f"1. Gastos_{month_label}.xlsx (Planilla Excel CB Asesor)\n"
                f"2. Libro_IVA_Compras_{month_label}.csv (Formato exportable)\n"
                f"3. Tickets_Comprobantes_{month_label}.pdf (Comprobantes escaneados)\n"
                f"4. Documentación adicional adjunta (resúmenes bancarios, cuotas, extractos)\n"
            )
            zip_file.writestr("RESUMEN_CIERRE.txt", resumen_txt.encode("utf-8"))
            
        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'}
        )
    except Exception as e:
        logger.error(f"Error en download_accountant_pack: {e}")
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

@app.get("/api/ticket-image/{month}/{index}")
async def ticket_image(month: str, index: int, user_email: str = None):
    from ticket_manager import render_ticket_page_jpeg
    try:
        data = render_ticket_page_jpeg(month, index, user_email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not data:
        raise HTTPException(status_code=404, detail="Imagen del ticket no disponible")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@app.post("/api/ticket-delete")
async def ticket_delete(
    background_tasks: BackgroundTasks,
    month: str = Form(...),
    index: int = Form(...),
    user_email: str = Form(None)
):
    from ticket_manager import delete_ticket
    try:
        res = delete_ticket(month, index, user_email)
        if res.get("success") and res.get("remaining", 0) > 0:
            background_tasks.add_task(sync_month_to_gdrive, res["month"], PDFS_DIR, DATA_DIR, user_email)
        return JSONResponse(content=res)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.post("/api/ticket-edit")
async def ticket_edit(
    background_tasks: BackgroundTasks,
    month: str = Form(...),
    index: int = Form(...),
    vendor: str = Form(None),
    date: str = Form(None),
    cuit: str = Form(None),
    total: float = Form(None),
    subtotal: float = Form(None),
    iva_21: float = Form(None),
    iva_10_5: float = Form(None),
    iva_27: float = Form(None),
    percepcion_iibb: float = Form(None),
    percepcion_iibb_jurisdiccion: str = Form(None),
    percepcion_iva: float = Form(None),
    impuestos_internos: float = Form(None),
    invoice_number: str = Form(None),
    invoice_type: str = Form(None),
    cae: str = Form(None),
    user_email: str = Form(None)
):
    from ticket_manager import edit_ticket
    try:
        fields = {
            "vendor": vendor, "date": date, "cuit": cuit, "total": total,
            "subtotal": subtotal, "iva_21": iva_21, "iva_10_5": iva_10_5, "iva_27": iva_27,
            "percepcion_iibb": percepcion_iibb, "percepcion_iibb_jurisdiccion": percepcion_iibb_jurisdiccion,
            "percepcion_iva": percepcion_iva, "impuestos_internos": impuestos_internos,
            "invoice_number": invoice_number, "invoice_type": invoice_type, "cae": cae
        }
        res = edit_ticket(month, index, fields, user_email)
        if res.get("success"):
            for m in {res.get("month"), res.get("new_month")}:
                if m:
                    background_tasks.add_task(sync_month_to_gdrive, m, PDFS_DIR, DATA_DIR, user_email)
        return JSONResponse(content=res)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.post("/api/sync-restore-expenses")
async def sync_restore_expenses(
    month: str = Form(...),
    expenses_json: str = Form(...),
    user_email: str = Form(None)
):
    try:
        import json
        from ticket_ocr import save_monthly_expenses
        tickets = json.loads(expenses_json)
        save_monthly_expenses(month, tickets, user_email)
        return {"success": True, "count": len(tickets), "month": month}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.post("/api/sync-restore-pdf")
async def sync_restore_pdf(
    month: str = Form(...),
    file: UploadFile = File(...),
    user_email: str = Form(None)
):
    try:
        from pdf_processor import get_user_pdf_dir
        target_pdf_dir = get_user_pdf_dir(user_email)
        month_key = month.replace("-", "_")
        pdf_path = target_pdf_dir / f"Tickets_{month_key}.pdf"
        content = await file.read()
        if content:
            with open(pdf_path, "wb") as f:
                f.write(content)
        return {"success": True, "month": month_key, "size": len(content)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

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
