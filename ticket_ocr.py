import io
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageEnhance, ImageOps
import pymupdf

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
    possible_tesseract_paths = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Users\barzo\AppData\Local\Programs\Tesseract-OCR\tesseract.exe")
    ]
    for tp in possible_tesseract_paths:
        if tp.exists():
            pytesseract.pytesseract.tesseract_cmd = str(tp)
            break
except ImportError:
    PYTESSERACT_AVAILABLE = False

logger = logging.getLogger("ticket_ocr")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Datos_Mensuales"
DATA_DIR.mkdir(exist_ok=True)

def parse_amount(text_str: str) -> float:
    """Convierte cadenas de texto de montos a float con precisión."""
    if not text_str:
        return 0.0
    try:
        clean = text_str.replace('$', '').replace(' ', '').strip()
        if ',' in clean and '.' in clean:
            clean = clean.replace('.', '').replace(',', '.')
        elif ',' in clean:
            clean = clean.replace(',', '.')
        return float(clean)
    except Exception:
        return 0.0

def extract_raw_text_from_image(image_bytes: bytes) -> str:
    """Extrae el texto impreso en la foto utilizando Tesseract OCR / PyMuPDF con pre-procesamiento."""
    raw_text = ""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Redimensionar si la imagen es de baja resolución (aumenta definición de caracteres impresos)
        w, h = img.size
        if w < 1200:
            scale = 1400.0 / float(w)
            new_w = 1400
            new_h = int(h * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
        # Crear versión mejorada con alto contraste y nitidez
        img_contrast = ImageEnhance.Contrast(img).enhance(1.8)
        img_contrast = ImageEnhance.Sharpness(img_contrast).enhance(1.8)
        
        enhanced_bytes_io = io.BytesIO()
        img_contrast.save(enhanced_bytes_io, format='JPEG', quality=95)
        enhanced_bytes = enhanced_bytes_io.getvalue()
    except Exception as e:
        logger.warning(f"Error procesando imagen para OCR: {e}")
        enhanced_bytes = image_bytes
        img = Image.open(io.BytesIO(image_bytes))

    # 1. Intentar con PyTesseract con cadena de fallback de idioma (spa+eng -> eng -> spa -> default)
    if PYTESSERACT_AVAILABLE:
        for lang_option in ['spa+eng', 'eng', 'spa', None]:
            try:
                if lang_option:
                    txt = pytesseract.image_to_string(img_contrast, lang=lang_option)
                else:
                    txt = pytesseract.image_to_string(img_contrast)
                if txt and len(txt.strip()) > 10:
                    return txt
            except Exception as e:
                logger.warning(f"PyTesseract error con lang={lang_option}: {e}")
            
    # 2. Intentar con PyMuPDF OCR
    try:
        img_doc = pymupdf.open("jpeg", enhanced_bytes)
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        
        pdf_mem = pymupdf.open("pdf", pdf_bytes)
        page = pdf_mem[0]
        
        for lang_option in ['eng', 'spa']:
            try:
                tp = page.get_textpage_ocr(flags=0, language=lang_option)
                raw_text = page.get_text("text", textpage=tp)
                if raw_text and len(raw_text.strip()) > 10:
                    break
            except Exception:
                continue
                
        if not raw_text or len(raw_text.strip()) <= 10:
            raw_text = page.get_text("text")
            
        pdf_mem.close()
    except Exception as e:
        logger.warning(f"PyMuPDF OCR error: {e}")
        
import os
import base64
import requests

def extract_data_with_gemini_vision(image_bytes: bytes) -> dict:
    """Extrae datos de tickets usando IA Visión de Google Gemini (si la API Key está configurada)."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    
    try:
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        
        prompt = """Analiza la foto de este ticket de compra / factura de Argentina y responde ÚNICAMENTE con un objeto JSON válido con este formato exacto:
{
  "vendor": "Nombre o Razón Social del Comercio",
  "cuit": "CUIT del Comercio Vendedor en formato XX-XXXXXXXX-X",
  "invoice_type": "Factura A",
  "date": "Fecha exacta en formato DD/MM/YYYY",
  "subtotal": 0.00,
  "iva_21": 0.00,
  "iva_10_5": 0.00,
  "iva_27": 0.00,
  "total": 0.00,
  "items": [
    {
      "name": "Nombre o descripción del producto/servicio",
      "qty": 1.0,
      "price": 0.00
    }
  ]
}
Reglas estrictas:
1. "date": Extrae la FECHA REAL impresa en el ticket (ej. 16/09/2026, 23/09/2026). NO inventes ni uses la fecha de hoy.
2. "subtotal": Monto neto gravado antes de impuestos.
3. "iva_21", "iva_10_5", "iva_27": Extrae el monto en pesos del IVA impreso.
4. "total": El importe total final a pagar impreso.
5. "vendor": Razón social o comercio impreso arriba (ej: RERIFF S.A., YPF, CENCOSUD, CARREFOUR, DISCO, COTO).
6. "items": Lista detallada de productos/servicios comprados (ej. Nafta Super XXI, Leche 1L, Huevos, Dulce de Membrillo). Si no se pueden identificar los ítems, devuelve una lista vacía [].
"""

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": b64_image
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        }
        
        models_to_try = [
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
            "gemini-2.0-flash-exp",
            "gemini-1.5-pro"
        ]
        
        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, json=payload, timeout=8)
                if resp.status_code == 200:
                    res_json = resp.json()
                    candidates = res_json.get('candidates', [])
                    if not candidates:
                        continue
                    parts = candidates[0].get('content', {}).get('parts', [])
                    text_resp = "".join([p.get('text', '') for p in parts if 'text' in p]).strip()
                    if text_resp.startswith("```"):
                        text_resp = re.sub(r'^```(?:json)?\s*', '', text_resp)
                        text_resp = re.sub(r'\s*```$', '', text_resp)
                    parsed = json.loads(text_resp.strip())
                    logger.info(f"Gemini Vision AI ({model_name}) extrajo exitosamente: {parsed}")
                    return parsed
                else:
                    logger.warning(f"Gemini Vision API ({model_name}) HTTP {resp.status_code}: {resp.text[:150]}")
            except Exception as ex_mod:
                logger.warning(f"Gemini Vision API ({model_name}) error: {ex_mod}")
    except Exception as e:
        logger.warning(f"Gemini Vision API error/bypass: {e}")
        
    return None

def extract_data_from_image(
    image_bytes: bytes,
    filename_hint: str = "",
    user_vendor: str = None,
    user_total: float = None,
    user_cuit: str = None,
    user_date: str = None,
    user_subtotal: float = None,
    user_iva_21: float = None,
    user_iva_10_5: float = None,
    user_iva_27: float = None,
    user_items: list = None
) -> dict:
    """
    Analiza la foto del ticket mediante IA Visión de Google Gemini o usa datos confirmados por el usuario.
    """
    # Si los datos principales ya vienen confirmados desde el paso de pre-lectura, retornar al instante
    if user_total is not None and user_total > 0 and user_vendor and user_vendor.strip() and user_vendor != "Comercio General":
        return {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "vendor": user_vendor.strip(),
            "cuit": (user_cuit or "").strip(),
            "invoice_type": "Factura A",
            "date": (user_date or "").strip() or datetime.now().strftime("%d/%m/%Y"),
            "subtotal": user_subtotal if (user_subtotal is not None and user_subtotal > 0) else user_total,
            "iva_21": user_iva_21 if (user_iva_21 is not None and user_iva_21 >= 0) else 0.0,
            "iva_10_5": user_iva_10_5 if (user_iva_10_5 is not None and user_iva_10_5 >= 0) else 0.0,
            "iva_27": user_iva_27 if (user_iva_27 is not None and user_iva_27 >= 0) else 0.0,
            "total": user_total,
            "items": user_items or [],
            "filename": filename_hint
        }

    # 1. Intentar primero con Visión por IA (Google Gemini 1.5 Flash) si la API Key está presente
    ai_data = extract_data_with_gemini_vision(image_bytes)
    if ai_data:
        vendor = user_vendor.strip() if (user_vendor and user_vendor.strip() and user_vendor != "Comercio General") else str(ai_data.get("vendor", "Comercio General"))
        total = user_total if (user_total is not None and user_total > 0) else parse_amount(str(ai_data.get("total", 0.0)))
        cuit = user_cuit.strip() if (user_cuit and user_cuit.strip() and "X" not in user_cuit) else str(ai_data.get("cuit", ""))
        date_str = user_date.strip() if (user_date and user_date.strip() and "D" not in user_date) else str(ai_data.get("date", datetime.now().strftime("%d/%m/%Y")))
        subtotal = user_subtotal if (user_subtotal is not None and user_subtotal > 0) else parse_amount(str(ai_data.get("subtotal", 0.0)))
        iva_21 = user_iva_21 if (user_iva_21 is not None and user_iva_21 >= 0) else parse_amount(str(ai_data.get("iva_21", 0.0)))
        iva_10_5 = user_iva_10_5 if (user_iva_10_5 is not None and user_iva_10_5 >= 0) else parse_amount(str(ai_data.get("iva_10_5", 0.0)))
        iva_27 = user_iva_27 if (user_iva_27 is not None and user_iva_27 >= 0) else parse_amount(str(ai_data.get("iva_27", 0.0)))
        raw_items = ai_data.get("items", [])
        items = user_items if (user_items and len(user_items) > 0) else (raw_items if isinstance(raw_items, list) else [])
        
        return {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "vendor": vendor,
            "cuit": cuit,
            "invoice_type": ai_data.get("invoice_type", "Factura A"),
            "date": date_str,
            "subtotal": subtotal,
            "iva_21": iva_21,
            "iva_10_5": iva_10_5,
            "iva_27": iva_27,
            "total": total,
            "items": items,
            "filename": filename_hint
        }

    raw_text = extract_raw_text_from_image(image_bytes)
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    
    # 1. Total (Leído de abajo hacia arriba o mayor monto válido)
    total = user_total if (user_total is not None and user_total > 0) else 0.0
    if total <= 0:
        for line in reversed(lines):
            m = re.search(r'(?:TOTAL|RECIBIMOS|SUMA DE SUS PAGOS|EFECTIVO|IMPORTE\s+TOTAL)\s*[:=]?\s*\$?\s*([\d\.,]{4,12})', line, re.I)
            if m:
                val = parse_amount(m.group(1))
                if val > 10:
                    total = val
                    break

        if total <= 0:
            numbers = re.findall(r'\$?\s*([\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b)', raw_text)
            parsed_nums = [parse_amount(n) for n in numbers if parse_amount(n) > 10]
            if parsed_nums:
                total = max(parsed_nums)

    # 2. Vendor / Comercio
    vendor = user_vendor.strip() if (user_vendor and user_vendor.strip()) else None
    if not vendor:
        for line in lines[:8]:
            if len(line) > 3 and not re.search(r'factura|cuit|dom|inicio|iva|responsable|direcc|remito|comprobante|original|nro', line, re.I):
                vendor = line.title()
                break
        if not vendor:
            vendor = "Comercio General"

    # 3. CUIT
    cuit = user_cuit.strip() if (user_cuit and user_cuit.strip()) else ""
    if not cuit:
        for line in lines:
            cuit_match = re.search(r'\b(3[034]-?\d{8}-?\d|2[0370]-?\d{8}-?\d)\b', line)
            if cuit_match:
                cuit = cuit_match.group(1)
                break

    # 4. Fecha
    date_str = user_date.strip() if (user_date and user_date.strip()) else ""
    if not date_str:
        date_match = re.search(r'FECHA\s*[:=]?\s*(\d{2}[/\.-]\d{2}[/\.-]\d{2,4})', raw_text, re.I)
        if not date_match:
            date_match = re.search(r'\b(\d{2}[/\.-]\d{2}[/\.-]\d{2,4})\b', raw_text)
        date_str = date_match.group(1) if date_match else ""

    comp_type = "Factura A" if ("FACTURA A" in raw_text.upper() or "TICKET FACTURA A" in raw_text.upper()) else "Ticket / Comprobante"

    # 5. IVA impreso (21%, 10.5%, 27%)
    iva_21 = user_iva_21 if (user_iva_21 is not None and user_iva_21 >= 0) else None
    if iva_21 is None:
        iva_21 = 0.0
        for line in lines:
            if re.search(r'(?:I\.?V\.?A\.?|IVA)\s*(?:GRAVADO\s*)?(?:21(?:[\.,]00)?)\s*%', line, re.I):
                nums = re.findall(r'[\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b', line)
                if nums:
                    val_str = nums[-1] if ('BASE' in line.upper() and len(nums) >= 2) else nums[0]
                    val = parse_amount(val_str)
                    if val > 0 and val != 21.0:
                        iva_21 = val
                        break

    iva_10_5 = user_iva_10_5 if (user_iva_10_5 is not None and user_iva_10_5 >= 0) else None
    if iva_10_5 is None:
        iva_10_5 = 0.0
        for line in lines:
            if re.search(r'(?:I\.?V\.?A\.?|IVA)\s*(?:GRAVADO\s*)?(?:10[\.,]5\d?)\s*%', line, re.I):
                nums = re.findall(r'[\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b', line)
                if nums:
                    val_str = nums[-1] if ('BASE' in line.upper() and len(nums) >= 2) else nums[0]
                    val = parse_amount(val_str)
                    if val > 0 and val != 10.5:
                        iva_10_5 = val
                        break

    iva_27 = user_iva_27 if (user_iva_27 is not None and user_iva_27 >= 0) else None
    if iva_27 is None:
        iva_27 = 0.0
        for line in lines:
            if re.search(r'(?:I\.?V\.?A\.?|IVA)\s*(?:GRAVADO\s*)?(?:27(?:[\.,]00)?)\s*%', line, re.I):
                nums = re.findall(r'[\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b', line)
                if nums:
                    val_str = nums[-1] if ('BASE' in line.upper() and len(nums) >= 2) else nums[0]
                    val = parse_amount(val_str)
                    if val > 0 and val != 27.0:
                        iva_27 = val
                        break

    # 6. Subtotal Neto impreso
    subtotal = user_subtotal if (user_subtotal is not None and user_subtotal > 0) else None
    if subtotal is None or subtotal <= 0:
        subtotal = 0.0
        for line in lines:
            m = re.search(r'(?:NETO\s+GRAVADO|SUBTOTAL\s+NETO|TOTAL\s+NETO|NETO\s+SIN\s+IVA|BASE\s+IMPONIBLE|SUBTOTAL)\s*[:=]?\s*\$?\s*([\d\.,]{3,12})', line, re.I)
            if m:
                val = parse_amount(m.group(1))
                if val > 0 and (total == 0 or val <= total):
                    subtotal = val
                    break

        if subtotal == 0.0 and total > 0:
            sum_iva = iva_21 + iva_10_5 + iva_27
            subtotal = round(total - sum_iva, 2) if sum_iva > 0 else total

    return {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "vendor": vendor,
        "cuit": cuit,
        "invoice_type": comp_type,
        "date": date_str,
        "subtotal": subtotal,
        "iva_21": iva_21,
        "iva_10_5": iva_10_5,
        "iva_27": iva_27,
        "total": total,
        "items": [],
        "filename": filename_hint
    }

def sanitize_email(email: str) -> str:
    """Sanitiza una dirección de correo para usar como nombre de carpeta seguro."""
    if not email or not isinstance(email, str):
        return ""
    clean = re.sub(r'[^a-zA-Z0-9_.]', '_', email.strip().lower())
    return clean

def extract_month_from_date(date_str: str) -> str:
    """Extrae YYYY_MM a partir de una cadena de fecha DD/MM/YYYY o DD-MM-YYYY."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        parts = re.split(r'[/.-]', date_str.strip())
        if len(parts) == 3:
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 2000
            if 1 <= m <= 12 and 2000 <= y <= 2100:
                return f"{y:04d}_{m:02d}"
    except Exception:
        pass
    return None

def get_user_data_dir(user_email: str = None) -> Path:
    safe_email = sanitize_email(user_email)
    if safe_email:
        user_dir = DATA_DIR / safe_email
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    return DATA_DIR

def get_month_data_file(month_str: str, user_email: str = None) -> Path:
    month_key = month_str.replace("-", "_")
    target_dir = get_user_data_dir(user_email)
    return target_dir / f"Gastos_{month_key}.json"

def load_monthly_expenses(month_str: str, user_email: str = None) -> list[dict]:
    data_file = get_month_data_file(month_str, user_email)
    if not data_file.exists():
        return []
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error cargando gastos de {month_str}: {e}")
        return []

def save_monthly_expenses(month_str: str, tickets_list: list[dict], user_email: str = None):
    data_file = get_month_data_file(month_str, user_email)
    try:
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(tickets_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando gastos de {month_str}: {e}")

def add_ticket_expense(month_str: str, ticket_data: dict, user_email: str = None):
    current = load_monthly_expenses(month_str, user_email)
    current.insert(0, ticket_data)
    save_monthly_expenses(month_str, current, user_email)

def remove_last_ticket_expense(month_str: str, user_email: str = None):
    current = load_monthly_expenses(month_str, user_email)
    if current:
        current.pop(0)
        save_monthly_expenses(month_str, current, user_email)

def delete_month_expenses(month_str: str, user_email: str = None):
    data_file = get_month_data_file(month_str, user_email)
    if data_file.exists():
        data_file.unlink()

def get_monthly_summary(month_str: str, user_email: str = None) -> dict:
    tickets = load_monthly_expenses(month_str, user_email)
    
    total_spent = sum(t.get("total", 0.0) for t in tickets)
    total_subtotal = sum(t.get("subtotal", 0.0) for t in tickets)
    total_iva = sum(t.get("iva_21", 0.0) + t.get("iva_10_5", 0.0) + t.get("iva_27", 0.0) for t in tickets)
    total_items_count = sum(len(t.get("items", [])) for t in tickets)
    
    vendors = {}
    for t in tickets:
        v_name = t.get("vendor", "Comercio General")
        v_total = t.get("total", 0.0)
        vendors[v_name] = vendors.get(v_name, 0.0) + v_total
        
    vendor_breakdown = []
    for v_name, v_total in sorted(vendors.items(), key=lambda x: x[1], reverse=True):
        pct = round((v_total / total_spent * 100), 1) if total_spent > 0 else 0
        vendor_breakdown.append({
            "vendor": v_name,
            "total": round(v_total, 2),
            "percentage": pct
        })
        
    return {
        "month": month_str,
        "total_spent": round(total_spent, 2),
        "total_subtotal": round(total_subtotal, 2),
        "total_iva": round(total_iva, 2),
        "tickets_count": len(tickets),
        "total_items_count": total_items_count,
        "vendor_breakdown": vendor_breakdown,
        "tickets": tickets
    }
