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

_KEY_B64 = "QVEuQWI4Uk42TFhGOVhzQUxENGo5RDhzcmhPTlNId2JhaDVDa3gzdXo4SGlFRHI3dHVCYWc="

def extract_data_with_gemini_vision(image_bytes: bytes) -> dict:
    """Extrae datos de tickets usando IA Visión de Google Gemini."""
    fallback_key = base64.b64decode(_KEY_B64).decode("utf-8")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or fallback_key
    if not api_key:
        return None
    
    try:
        # Optimizar imagen para envío ultrarrápido por API
        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.thumbnail((1100, 1600))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            opt_bytes = buf.getvalue()
        except Exception:
            opt_bytes = image_bytes

        b64_image = base64.b64encode(opt_bytes).decode("utf-8")
        
        prompt = """Analiza la foto de este comprobante (Ticket, Factura A/B/C/M, Remito R/X, Recibo o Nota de Crédito) de Argentina y responde ÚNICAMENTE con un objeto JSON válido con este formato exacto:
{
  "vendor": "Nombre o Razón Social del Comercio / Proveedor",
  "cuit": "CUIT del Comercio / Proveedor en formato XX-XXXXXXXX-X",
  "invoice_type": "Factura A",
  "invoice_number": "Punto de Venta y Número (ej: 00004-00012345)",
  "date": "Fecha exacta en formato DD/MM/YYYY",
  "subtotal": 0.00,
  "neto_21": 0.00,
  "neto_10_5": 0.00,
  "neto_27": 0.00,
  "iva_21": 0.00,
  "iva_10_5": 0.00,
  "iva_27": 0.00,
  "percepcion_iibb": 0.00,
  "percepcion_iibb_jurisdiccion": "ARBA | AGIP | DGR Córdoba | API Santa Fe | Convenio Multilateral | Ninguna",
  "percepcion_iva": 0.00,
  "impuestos_internos": 0.00,
  "no_gravado": 0.00,
  "cae": "Número de CAE si aplica",
  "cae_vto": "Fecha vencimiento CAE si aplica",
  "total": 0.00,
  "items": [
    {
      "name": "Nombre o descripción del producto/servicio/mercadería",
      "qty": 1.0,
      "price": 0.00
    }
  ]
}
Reglas estrictas para el análisis impositivo argentino:
1. "invoice_type": Clasifica con precisión: "Factura A", "Factura B", "Factura C", "Factura M", "Remito", "Ticket", "Nota de Crédito A/B/C", "Recibo".
2. "invoice_number": Extrae el Punto de Venta (4 o 5 dígitos) y Número (6 a 8 dígitos) separados por guion.
3. "date": Extrae la FECHA REAL impresa (ej. 16/09/2026). NO inventes ni uses la fecha de hoy.
4. "subtotal": Monto neto gravado total antes de IVA y percepciones.
5. "iva_21", "iva_10_5", "iva_27": Extrae el monto discriminado en pesos de cada alícuota de IVA.
6. "percepcion_iibb": Extrae el monto total de Percepciones de Ingresos Brutos (IIBB) si las hay.
7. "percepcion_iibb_jurisdiccion": Indica la provincia o fisco (ej: ARBA Buenos Aires, AGIP CABA, Santa Fe, Córdoba, etc.).
8. "percepcion_iva": Monto de percepción de IVA (ej. RG 2408, RG 5329).
9. "impuestos_internos": Monto de impuestos internos, tasas municipales o combustibles.
10. "total": El importe total final. Si es un Remito no valorizado de mercadería, pon 0.00.
11. "cae": Extrae los 14 dígitos del Código de Autorización Electrónico si es Factura Electrónica.
12. "items": Lista detallada de productos/servicios/bultos con cantidad y precio. Si no hay ítems detallados, devuelve [].
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
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-flash-latest",
            "gemini-flash-lite-latest"
        ]
        
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=18)
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
    user_items: list = None,
    user_percepcion_iibb: float = None,
    user_percepcion_iibb_jurisdiccion: str = None,
    user_percepcion_iva: float = None,
    user_impuestos_internos: float = None,
    user_invoice_number: str = None,
    user_invoice_type: str = None,
    user_cae: str = None
) -> dict:
    """
    Analiza la foto del comprobante (Factura, Ticket o Remito) mediante IA Visión o fallback OCR.
    Extrae desglose impositivo argentino completo (IVA, IIBB, Percepciones, Retenciones y CAE).
    """
    # Si los datos principales ya vienen confirmados por el usuario
    if user_total is not None and user_total > 0 and user_vendor and user_vendor.strip() and user_vendor != "Comercio General":
        return {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "vendor": user_vendor.strip(),
            "cuit": (user_cuit or "").strip(),
            "invoice_type": (user_invoice_type or "Factura A").strip(),
            "invoice_number": (user_invoice_number or "").strip(),
            "date": (user_date or "").strip() or datetime.now().strftime("%d/%m/%Y"),
            "subtotal": user_subtotal if (user_subtotal is not None and user_subtotal > 0) else user_total,
            "iva_21": user_iva_21 if (user_iva_21 is not None and user_iva_21 >= 0) else 0.0,
            "iva_10_5": user_iva_10_5 if (user_iva_10_5 is not None and user_iva_10_5 >= 0) else 0.0,
            "iva_27": user_iva_27 if (user_iva_27 is not None and user_iva_27 >= 0) else 0.0,
            "percepcion_iibb": user_percepcion_iibb if (user_percepcion_iibb is not None and user_percepcion_iibb >= 0) else 0.0,
            "percepcion_iibb_jurisdiccion": (user_percepcion_iibb_jurisdiccion or "").strip(),
            "percepcion_iva": user_percepcion_iva if (user_percepcion_iva is not None and user_percepcion_iva >= 0) else 0.0,
            "impuestos_internos": user_impuestos_internos if (user_impuestos_internos is not None and user_impuestos_internos >= 0) else 0.0,
            "cae": (user_cae or "").strip(),
            "total": user_total,
            "items": user_items or [],
            "filename": filename_hint
        }

    # 1. Intentar primero con Visión por IA (Google Gemini 1.5/3 Flash)
    ai_data = extract_data_with_gemini_vision(image_bytes)
    if ai_data:
        vendor = user_vendor.strip() if (user_vendor and user_vendor.strip() and user_vendor != "Comercio General") else str(ai_data.get("vendor", "Comercio General"))
        total = user_total if (user_total is not None and user_total >= 0) else parse_amount(str(ai_data.get("total", 0.0)))
        cuit = user_cuit.strip() if (user_cuit and user_cuit.strip() and "X" not in user_cuit) else str(ai_data.get("cuit", ""))
        date_str = user_date.strip() if (user_date and user_date.strip() and "D" not in user_date) else str(ai_data.get("date", datetime.now().strftime("%d/%m/%Y")))
        subtotal = user_subtotal if (user_subtotal is not None and user_subtotal > 0) else parse_amount(str(ai_data.get("subtotal", 0.0)))
        iva_21 = user_iva_21 if (user_iva_21 is not None and user_iva_21 >= 0) else parse_amount(str(ai_data.get("iva_21", 0.0)))
        iva_10_5 = user_iva_10_5 if (user_iva_10_5 is not None and user_iva_10_5 >= 0) else parse_amount(str(ai_data.get("iva_10_5", 0.0)))
        iva_27 = user_iva_27 if (user_iva_27 is not None and user_iva_27 >= 0) else parse_amount(str(ai_data.get("iva_27", 0.0)))
        
        perc_iibb = user_percepcion_iibb if (user_percepcion_iibb is not None and user_percepcion_iibb >= 0) else parse_amount(str(ai_data.get("percepcion_iibb", 0.0)))
        jurisdiccion = user_percepcion_iibb_jurisdiccion.strip() if user_percepcion_iibb_jurisdiccion else str(ai_data.get("percepcion_iibb_jurisdiccion", ""))
        perc_iva = user_percepcion_iva if (user_percepcion_iva is not None and user_percepcion_iva >= 0) else parse_amount(str(ai_data.get("percepcion_iva", 0.0)))
        imp_internos = user_impuestos_internos if (user_impuestos_internos is not None and user_impuestos_internos >= 0) else parse_amount(str(ai_data.get("impuestos_internos", 0.0)))
        inv_num = user_invoice_number.strip() if user_invoice_number else str(ai_data.get("invoice_number", ""))
        inv_type = user_invoice_type.strip() if user_invoice_type else str(ai_data.get("invoice_type", "Factura A"))
        cae = user_cae.strip() if user_cae else str(ai_data.get("cae", ""))

        raw_items = ai_data.get("items", [])
        items = user_items if (user_items and len(user_items) > 0) else (raw_items if isinstance(raw_items, list) else [])
        
        return {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "vendor": vendor,
            "cuit": cuit,
            "invoice_type": inv_type,
            "invoice_number": inv_num,
            "date": date_str,
            "subtotal": subtotal,
            "iva_21": iva_21,
            "iva_10_5": iva_10_5,
            "iva_27": iva_27,
            "percepcion_iibb": perc_iibb,
            "percepcion_iibb_jurisdiccion": jurisdiccion,
            "percepcion_iva": perc_iva,
            "impuestos_internos": imp_internos,
            "cae": cae,
            "total": total,
            "items": items,
            "filename": filename_hint
        }

    # 2. Fallback OCR Clásico (Tesseract / Regex)
    raw_text = extract_raw_text_from_image(image_bytes)
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    raw_upper = raw_text.upper()
    
    # Tipo de Comprobante
    comp_type = user_invoice_type
    if not comp_type:
        if "REMITO" in raw_upper:
            comp_type = "Remito"
        elif "FACTURA A" in raw_upper or "TICKET FACTURA A" in raw_upper:
            comp_type = "Factura A"
        elif "FACTURA B" in raw_upper or "TICKET FACTURA B" in raw_upper:
            comp_type = "Factura B"
        elif "FACTURA C" in raw_upper or "TICKET FACTURA C" in raw_upper:
            comp_type = "Factura C"
        elif "FACTURA M" in raw_upper:
            comp_type = "Factura M"
        elif "NOTA DE CR" in raw_upper or "NC " in raw_upper:
            comp_type = "Nota de Crédito"
        elif "RECIBO" in raw_upper:
            comp_type = "Recibo"
        else:
            comp_type = "Ticket / Comprobante"

    # Número de Comprobante
    inv_num = user_invoice_number or ""
    if not inv_num:
        num_m = re.search(r'(?:comp\.?\s*n[°º]|factura\s*(?:[abc]\s*)?n[°º]|remito\s*(?:[rx]\s*)?n[°º]|nro\.?|punto\s*de\s*vta)\s*[:\-]?\s*(\d{4,5}\s*[\-\/]\s*\d{6,8})', raw_text, re.I)
        if num_m:
            inv_num = num_m.group(1).replace(" ", "")

    # Total
    total = user_total if (user_total is not None and user_total >= 0) else 0.0
    if total <= 0 and comp_type != "Remito":
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

    # Vendor / Comercio
    vendor = user_vendor.strip() if (user_vendor and user_vendor.strip()) else None
    if not vendor:
        for line in lines[:8]:
            if len(line) > 3 and not re.search(r'factura|cuit|dom|inicio|iva|responsable|direcc|remito|comprobante|original|nro', line, re.I):
                vendor = line.title()
                break
        if not vendor:
            vendor = "Comercio General"

    # CUIT
    cuit = user_cuit.strip() if (user_cuit and user_cuit.strip()) else ""
    if not cuit:
        for line in lines:
            cuit_match = re.search(r'\b(3[034]-?\d{8}-?\d|2[0370]-?\d{8}-?\d)\b', line)
            if cuit_match:
                cuit = cuit_match.group(1)
                break

    # Fecha
    date_str = user_date.strip() if (user_date and user_date.strip()) else ""
    if not date_str:
        date_match = re.search(r'FECHA\s*[:=]?\s*(\d{2}[/\.-]\d{2}[/\.-]\d{2,4})', raw_text, re.I)
        if not date_match:
            date_match = re.search(r'\b(\d{2}[/\.-]\d{2}[/\.-]\d{2,4})\b', raw_text)
        date_str = date_match.group(1) if date_match else ""

    # IVA 21%, 10.5%, 27%
    iva_21 = user_iva_21 if (user_iva_21 is not None and user_iva_21 >= 0) else 0.0
    if iva_21 == 0.0:
        for line in lines:
            if re.search(r'(?:I\.?V\.?A\.?|IVA)\s*(?:GRAVADO\s*)?(?:21(?:[\.,]00)?)\s*%', line, re.I):
                nums = re.findall(r'[\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b', line)
                if nums:
                    val = parse_amount(nums[-1] if ('BASE' in line.upper() and len(nums) >= 2) else nums[0])
                    if val > 0 and val != 21.0:
                        iva_21 = val
                        break

    iva_10_5 = user_iva_10_5 if (user_iva_10_5 is not None and user_iva_10_5 >= 0) else 0.0
    if iva_10_5 == 0.0:
        for line in lines:
            if re.search(r'(?:I\.?V\.?A\.?|IVA)\s*(?:GRAVADO\s*)?(?:10[\.,]5\d?)\s*%', line, re.I):
                nums = re.findall(r'[\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b', line)
                if nums:
                    val = parse_amount(nums[-1] if ('BASE' in line.upper() and len(nums) >= 2) else nums[0])
                    if val > 0 and val != 10.5:
                        iva_10_5 = val
                        break

    iva_27 = user_iva_27 if (user_iva_27 is not None and user_iva_27 >= 0) else 0.0
    if iva_27 == 0.0:
        for line in lines:
            if re.search(r'(?:I\.?V\.?A\.?|IVA)\s*(?:GRAVADO\s*)?(?:27(?:[\.,]00)?)\s*%', line, re.I):
                nums = re.findall(r'[\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b', line)
                if nums:
                    val = parse_amount(nums[-1] if ('BASE' in line.upper() and len(nums) >= 2) else nums[0])
                    if val > 0 and val != 27.0:
                        iva_27 = val
                        break

    # Percepciones IIBB y Jurisdicción
    perc_iibb = user_percepcion_iibb if (user_percepcion_iibb is not None and user_percepcion_iibb >= 0) else 0.0
    jurisdiccion = user_percepcion_iibb_jurisdiccion or ""
    if perc_iibb == 0.0:
        for line in lines:
            m = re.search(r'(?:perc(?:epci[oó]n)?\.?\s*(?:de\s*)?(?:ii\.?bb\.?|ing(?:resos)?\.?\s*brutos?|dgr|rentas))\s*[:\$]?\s*([\d\.,]{3,12})', line, re.I)
            if m:
                perc_iibb = parse_amount(m.group(1))
                break
    if not jurisdiccion and perc_iibb > 0:
        if re.search(r'arba|buenos\s*aires|bs\.?\s*as\.?', raw_text, re.I):
            jurisdiccion = "ARBA (Bs.As.)"
        elif re.search(r'agip|caba|capital\s*federal', raw_text, re.I):
            jurisdiccion = "AGIP (CABA)"
        elif re.search(r'santa\s*fe|api', raw_text, re.I):
            jurisdiccion = "API (Santa Fe)"
        elif re.search(r'c[oó]rdoba|dgr\s*cba', raw_text, re.I):
            jurisdiccion = "DGR (Córdoba)"
        elif re.search(r'convenio\s*multilateral', raw_text, re.I):
            jurisdiccion = "Convenio Multilateral"

    # Percepción IVA
    perc_iva = user_percepcion_iva if (user_percepcion_iva is not None and user_percepcion_iva >= 0) else 0.0
    if perc_iva == 0.0:
        for line in lines:
            m = re.search(r'(?:perc(?:epci[oó]n)?\.?\s*(?:de\s*)?iva|rg\s*(?:2408|5329))\s*[:\$]?\s*([\d\.,]{3,12})', line, re.I)
            if m:
                perc_iva = parse_amount(m.group(1))
                break

    # Impuestos Internos
    imp_internos = user_impuestos_internos if (user_impuestos_internos is not None and user_impuestos_internos >= 0) else 0.0
    if imp_internos == 0.0:
        for line in lines:
            m = re.search(r'(?:imp(?:uestos)?\.?\s*int(?:ernos)?\.?|tasas?)\s*[:\$]?\s*([\d\.,]{3,12})', line, re.I)
            if m:
                imp_internos = parse_amount(m.group(1))
                break

    # CAE
    cae = user_cae or ""
    if not cae:
        cae_m = re.search(r'c\.?a\.?e\.?\s*[:\-]?\s*(\d{14})', raw_text, re.I)
        if cae_m:
            cae = cae_m.group(1)

    # Subtotal Neto
    subtotal = user_subtotal if (user_subtotal is not None and user_subtotal > 0) else 0.0
    if subtotal <= 0:
        for line in lines:
            m = re.search(r'(?:NETO\s+GRAVADO|SUBTOTAL\s+NETO|TOTAL\s+NETO|NETO\s+SIN\s+IVA|BASE\s+IMPONIBLE|SUBTOTAL)\s*[:=]?\s*\$?\s*([\d\.,]{3,12})', line, re.I)
            if m:
                val = parse_amount(m.group(1))
                if val > 0 and (total == 0 or val <= total):
                    subtotal = val
                    break

        if subtotal == 0.0 and total > 0:
            sum_imp = iva_21 + iva_10_5 + iva_27 + perc_iibb + perc_iva + imp_internos
            subtotal = round(total - sum_imp, 2) if (total > sum_imp > 0) else total

    return {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "vendor": vendor,
        "cuit": cuit,
        "invoice_type": comp_type,
        "invoice_number": inv_num,
        "date": date_str,
        "subtotal": subtotal,
        "iva_21": iva_21,
        "iva_10_5": iva_10_5,
        "iva_27": iva_27,
        "percepcion_iibb": perc_iibb,
        "percepcion_iibb_jurisdiccion": jurisdiccion,
        "percepcion_iva": perc_iva,
        "impuestos_internos": imp_internos,
        "cae": cae,
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
    """Extrae YYYY_MM a partir de cualquier formato de fecha o período (DD/MM/YYYY, YYYY-MM-DD, MM/YYYY, YYYY_MM, etc.)."""
    if not date_str or not isinstance(date_str, str):
        return None
    val = date_str.strip()
    try:
        # 1. YYYY_MM o YYYY-MM (ej: 2026_10 o 2026-10)
        m_ym = re.search(r'\b(20\d{2})[-_](0[1-9]|1[0-2])\b', val)
        if m_ym:
            return f"{m_ym.group(1)}_{int(m_ym.group(2)):02d}"
            
        # 2. MM/YYYY o MM-YYYY (ej: 10/2026 o 9/2026)
        m_my = re.search(r'\b(0?[1-9]|1[0-2])[-/](20\d{2})\b', val)
        if m_my:
            return f"{m_my.group(2)}_{int(m_my.group(1)):02d}"
            
        # 3. DD/MM/YYYY o DD-MM-YYYY o DD.MM.YYYY
        m_dmy = re.search(r'\b(0?[1-9]|[12]\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](20\d{2})\b', val)
        if m_dmy:
            return f"{m_dmy.group(3)}_{int(m_dmy.group(2)):02d}"
            
        # 4. YYYY/MM/DD o YYYY-MM-DD
        m_ymd = re.search(r'\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b', val)
        if m_ymd:
            return f"{m_ymd.group(1)}_{int(m_ymd.group(2)):02d}"
            
        # 5. Split de 3 partes
        parts = re.split(r'[/.-]', val)
        if len(parts) == 3:
            p0, p1, p2 = int(parts[0]), int(parts[1]), int(parts[2])
            if p0 > 1000:
                y, m = p0, p1
            else:
                y, m = p2, p1
            if y < 100:
                y += 2000
            if 1 <= m <= 12 and 2000 <= y <= 2100:
                return f"{y:04d}_{m:02d}"
    except Exception:
        pass
    return None

def resolve_document_target_month(doc_data: dict, fallback_month: str = None) -> str:
    """Detecta inteligentemente a qué mes (YYYY_MM) pertenece un documento según sus fechas extraídas."""
    if not isinstance(doc_data, dict):
        if fallback_month:
            clean = fallback_month.replace("-", "_")
            if re.match(r'^20\d{2}_(0[1-9]|1[0-2])$', clean):
                return clean
        return datetime.now().strftime("%Y_%m")
        
    keys_priority = [
        "fecha_emision", "fecha_pago", "fecha_concertacion", "fecha_cierre",
        "periodo_hasta", "periodo_fiscal", "periodo", "fecha_vencimiento",
        "fecha_retencion", "periodo_desde", "date", "fecha"
    ]
    for k in keys_priority:
        val = doc_data.get(k)
        if val and isinstance(val, str):
            res = extract_month_from_date(val)
            if res:
                return res
                
    if fallback_month:
        clean = fallback_month.replace("-", "_")
        if re.match(r'^20\d{2}_(0[1-9]|1[0-2])$', clean):
            return clean
            
    return datetime.now().strftime("%Y_%m")

def redistribute_user_documents(user_email: str = None):
    """Revisa los registros mensuales de un usuario y mueve a su mes correspondiente los que hayan quedado mal posicionados."""
    if not user_email:
        return
    user_dir = get_user_data_dir(user_email)
    if not user_dir or not user_dir.exists():
        return
        
    base_docs_dir = BASE_DIR / "Documentos_Mensuales" / sanitize_email(user_email)
    
    # 1. Retenciones y VEPs: retenciones_YYYY_MM.json
    for f in list(user_dir.glob("retenciones_20*.json")):
        m_match = re.search(r'retenciones_(20\d{2}_[01]\d)\.json', f.name)
        if not m_match:
            continue
        curr_m = m_match.group(1)
        try:
            with open(f, 'r', encoding='utf-8') as jf:
                items = json.load(jf)
            if not isinstance(items, list):
                continue
            
            kept = []
            changed = False
            for it in items:
                target_m = resolve_document_target_month(it, fallback_month=curr_m)
                if target_m != curr_m:
                    target_file = user_dir / f"retenciones_{target_m}.json"
                    target_items = []
                    if target_file.exists():
                        try:
                            with open(target_file, 'r', encoding='utf-8') as tjf:
                                target_items = json.load(tjf)
                        except Exception:
                            target_items = []
                    it_id = it.get("id") or it.get("numero_certificado")
                    exists = any((x.get("id") == it_id or (it.get("numero_certificado") and x.get("numero_certificado") == it.get("numero_certificado"))) for x in target_items)
                    if not exists:
                        target_items.append(it)
                        with open(target_file, 'w', encoding='utf-8') as tjf:
                            json.dump(target_items, tjf, ensure_ascii=False, indent=2)
                    
                    if base_docs_dir.exists():
                        curr_docs = base_docs_dir / curr_m
                        dest_docs = base_docs_dir / target_m
                        if curr_docs.exists():
                            for pdf in list(curr_docs.glob("*.pdf")):
                                cert_num = str(it.get("numero_certificado", "")).replace("/", "_").strip()
                                if (cert_num and cert_num in pdf.name) or (it.get("fecha_emision") and it.get("fecha_emision").replace("/", "_") in pdf.name):
                                    dest_docs.mkdir(parents=True, exist_ok=True)
                                    target_pdf = dest_docs / pdf.name
                                    if not target_pdf.exists():
                                        try:
                                            pdf.rename(target_pdf)
                                        except Exception:
                                            pass
                    changed = True
                else:
                    kept.append(it)
            
            if changed:
                with open(f, 'w', encoding='utf-8') as jf:
                    json.dump(kept, jf, ensure_ascii=False, indent=2)
                logger.info(f"Redistribuidas retenciones de {curr_m} para {user_email}")
        except Exception as e:
            logger.error(f"Error redistribuyendo retenciones para {user_email} en {curr_m}: {e}")

    # 2. Inversiones: inversiones_YYYY_MM.json
    for f in list(user_dir.glob("inversiones_20*.json")):
        m_match = re.search(r'inversiones_(20\d{2}_[01]\d)\.json', f.name)
        if not m_match:
            continue
        curr_m = m_match.group(1)
        try:
            with open(f, 'r', encoding='utf-8') as jf:
                items = json.load(jf)
            if not isinstance(items, list):
                continue
            kept = []
            changed = False
            for it in items:
                target_m = resolve_document_target_month(it, fallback_month=curr_m)
                if target_m != curr_m:
                    target_file = user_dir / f"inversiones_{target_m}.json"
                    target_items = []
                    if target_file.exists():
                        try:
                            with open(target_file, 'r', encoding='utf-8') as tjf:
                                target_items = json.load(tjf)
                        except Exception:
                            target_items = []
                    it_id = it.get("id") or it.get("numero_boleto")
                    exists = any(x.get("id") == it_id for x in target_items)
                    if not exists:
                        target_items.append(it)
                        with open(target_file, 'w', encoding='utf-8') as tjf:
                            json.dump(target_items, tjf, ensure_ascii=False, indent=2)
                    changed = True
                else:
                    kept.append(it)
            if changed:
                with open(f, 'w', encoding='utf-8') as jf:
                    json.dump(kept, jf, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error redistribuyendo inversiones para {user_email}: {e}")

    # 3. Bancos: bancos_YYYY_MM.json (y compatibilidad con banco_*.json)
    for f in list(user_dir.glob("banco*_20*.json")):
        m_match = re.search(r'bancos?_(20\d{2}_[01]\d)\.json', f.name)
        if not m_match:
            continue
        curr_m = m_match.group(1)
        try:
            with open(f, 'r', encoding='utf-8') as jf:
                items = json.load(jf)
            if not isinstance(items, list):
                continue
            kept = []
            changed = False
            for it in items:
                target_m = resolve_document_target_month(it, fallback_month=curr_m)
                if target_m != curr_m:
                    target_file = user_dir / f"bancos_{target_m}.json"
                    target_items = []
                    if target_file.exists():
                        try:
                            with open(target_file, 'r', encoding='utf-8') as tjf:
                                target_items = json.load(tjf)
                        except Exception:
                            target_items = []
                    it_id = it.get("id")
                    exists = any(x.get("id") == it_id for x in target_items)
                    if not exists:
                        target_items.append(it)
                        with open(target_file, 'w', encoding='utf-8') as tjf:
                            json.dump(target_items, tjf, ensure_ascii=False, indent=2)
                    changed = True
                else:
                    kept.append(it)
            if changed:
                with open(f, 'w', encoding='utf-8') as jf:
                    json.dump(kept, jf, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error redistribuyendo bancos para {user_email}: {e}")

    # 4. Tarjetas: tarjetas_YYYY_MM.json
    for f in list(user_dir.glob("tarjetas_20*.json")):
        m_match = re.search(r'tarjetas_(20\d{2}_[01]\d)\.json', f.name)
        if not m_match:
            continue
        curr_m = m_match.group(1)
        try:
            with open(f, 'r', encoding='utf-8') as jf:
                items = json.load(jf)
            if not isinstance(items, list):
                continue
            kept = []
            changed = False
            for it in items:
                target_m = resolve_document_target_month(it, fallback_month=curr_m)
                if target_m != curr_m:
                    target_file = user_dir / f"tarjetas_{target_m}.json"
                    target_items = []
                    if target_file.exists():
                        try:
                            with open(target_file, 'r', encoding='utf-8') as tjf:
                                target_items = json.load(tjf)
                        except Exception:
                            target_items = []
                    it_id = it.get("id")
                    exists = any(x.get("id") == it_id for x in target_items)
                    if not exists:
                        target_items.append(it)
                        with open(target_file, 'w', encoding='utf-8') as tjf:
                            json.dump(target_items, tjf, ensure_ascii=False, indent=2)
                    changed = True
                else:
                    kept.append(it)
            if changed:
                with open(f, 'w', encoding='utf-8') as jf:
                    json.dump(kept, jf, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error redistribuyendo tarjetas para {user_email}: {e}")

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
    total_percepcion_iibb = sum(t.get("percepcion_iibb", 0.0) for t in tickets)
    total_percepcion_iva = sum(t.get("percepcion_iva", 0.0) for t in tickets)
    total_impuestos_internos = sum(t.get("impuestos_internos", 0.0) for t in tickets)
    total_items_count = sum(len(t.get("items", [])) for t in tickets)
    
    remitos_count = sum(1 for t in tickets if "REMITO" in (t.get("invoice_type") or "").upper())
    facturas_count = sum(1 for t in tickets if "FACTURA" in (t.get("invoice_type") or "").upper())
    
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
        "total_percepcion_iibb": round(total_percepcion_iibb, 2),
        "total_percepcion_iva": round(total_percepcion_iva, 2),
        "total_impuestos_internos": round(total_impuestos_internos, 2),
        "tickets_count": len(tickets),
        "facturas_count": facturas_count,
        "remitos_count": remitos_count,
        "total_items_count": total_items_count,
        "vendor_breakdown": vendor_breakdown,
        "tickets": tickets
    }
