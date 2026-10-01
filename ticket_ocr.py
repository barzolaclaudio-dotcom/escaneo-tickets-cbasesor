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

    # 1. Intentar con PyTesseract (Tesseract OCR Engine nativo)
    if PYTESSERACT_AVAILABLE:
        try:
            raw_text = pytesseract.image_to_string(img_contrast, lang='spa+eng')
            if len(raw_text.strip()) > 15:
                return raw_text
        except Exception as e:
            logger.debug(f"PyTesseract error: {e}")
            
    # 2. Intentar con PyMuPDF OCR
    try:
        img_doc = pymupdf.open("jpeg", enhanced_bytes)
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        
        pdf_mem = pymupdf.open("pdf", pdf_bytes)
        page = pdf_mem[0]
        
        try:
            tp = page.get_textpage_ocr(flags=0, language='spa')
            raw_text = page.get_text("text", textpage=tp)
        except Exception:
            raw_text = page.get_text("text")
            
        pdf_mem.close()
    except Exception as e:
        logger.warning(f"PyMuPDF OCR error: {e}")
        
    return raw_text

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
    user_iva_27: float = None
) -> dict:
    """
    Analiza la foto del ticket mediante OCR real en Linux/Windows y reconoce:
    - Razón Social / Comercio
    - CUIT
    - Tipo de Comprobante
    - Fecha
    - Lectura directa de IVA 21%, IVA 10.5% e IVA 27% impresos
    - Monto Total
    
    Permite sobreescribir cualquiera de los campos desde la interfaz de usuario si el usuario lo edita.
    """
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
        date_match = re.search(r'\b(\d{2}[/\.-]\d{2}[/\.-]\d{2,4})\b', raw_text)
        date_str = date_match.group(1) if date_match else datetime.now().strftime("%d/%m/%Y")

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

def get_month_data_file(month_str: str) -> Path:
    month_key = month_str.replace("-", "_")
    return DATA_DIR / f"Gastos_{month_key}.json"

def load_monthly_expenses(month_str: str) -> list[dict]:
    data_file = get_month_data_file(month_str)
    if not data_file.exists():
        return []
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error cargando gastos de {month_str}: {e}")
        return []

def save_monthly_expenses(month_str: str, tickets_list: list[dict]):
    data_file = get_month_data_file(month_str)
    try:
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(tickets_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando gastos de {month_str}: {e}")

def add_ticket_expense(month_str: str, ticket_data: dict):
    current = load_monthly_expenses(month_str)
    current.append(ticket_data)
    save_monthly_expenses(month_str, current)

def remove_last_ticket_expense(month_str: str):
    current = load_monthly_expenses(month_str)
    if current:
        current.pop()
        save_monthly_expenses(month_str, current)

def delete_month_expenses(month_str: str):
    data_file = get_month_data_file(month_str)
    if data_file.exists():
        data_file.unlink()

def get_monthly_summary(month_str: str) -> dict:
    tickets = load_monthly_expenses(month_str)
    
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
