import io
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from PIL import Image
import pymupdf

logger = logging.getLogger("ticket_ocr")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Datos_Mensuales"
DATA_DIR.mkdir(exist_ok=True)

def parse_amount(text_str: str) -> float:
    """Convierte cadenas de texto de montos a float."""
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

def extract_data_from_image(image_bytes: bytes, filename_hint: str = "", user_vendor: str = None, user_total: float = None) -> dict:
    """
    Analiza la imagen del ticket mediante OCR y combina los datos ingresados por el usuario.
    Calcula automáticamente Neto e IVA Crédito Fiscal.
    """
    raw_text = ""
    try:
        img_doc = pymupdf.open("png", image_bytes)
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        
        pdf_mem = pymupdf.open("pdf", pdf_bytes)
        page = pdf_mem[0]
        raw_text = page.get_text("text")
        pdf_mem.close()
    except Exception as e:
        logger.warning(f"Error en OCR inicial: {e}")

    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    
    # 1. Vendor / Comercio
    vendor = user_vendor if user_vendor and user_vendor.strip() else None
    if not vendor:
        for line in lines[:5]:
            if len(line) > 3 and not re.search(r'factura|cuit|ticket|original|fecha', line, re.I):
                vendor = line.title()
                break
        if not vendor:
            vendor = "Comercio General"

    # 2. Total
    total = user_total if (user_total is not None and user_total > 0) else 0.0
    if total <= 0:
        total_match = re.search(r'(?:TOTAL|IMPORTE TOTAL|\bTOTAL \$)\s*[:=]?\s*\$?\s*([\d\.,]+)', raw_text, re.I)
        if total_match:
            total = parse_amount(total_match.group(1))
        else:
            numbers = re.findall(r'\$?\s*([\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b)', raw_text)
            parsed_nums = [parse_amount(n) for n in numbers if parse_amount(n) > 0]
            if parsed_nums:
                total = max(parsed_nums)

    # 3. CUIT
    cuit_match = re.search(r'\b\d{2}-?\d{8}-?\d{1}\b', raw_text)
    cuit = cuit_match.group(0) if cuit_match else ""

    # 4. Fecha
    date_match = re.search(r'\b(\d{2}[/\.-]\d{2}[/\.-]\d{2,4})\b', raw_text)
    date_str = date_match.group(1) if date_match else datetime.now().strftime("%d/%m/%Y")

    comp_type = "Factura A" if "FACTURA A" in raw_text.upper() else "Ticket / Comprobante"

    # 5. Desglose impositivo
    subtotal = round(total / 1.21, 2) if total > 0 else 0.0
    iva_21 = round(total - subtotal, 2) if total > 0 else 0.0
    iva_10_5 = 0.0

    return {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "vendor": vendor,
        "cuit": cuit,
        "invoice_type": comp_type,
        "date": date_str,
        "subtotal": subtotal,
        "iva_21": iva_21,
        "iva_10_5": iva_10_5,
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
    total_iva = sum(t.get("iva_21", 0.0) + t.get("iva_10_5", 0.0) for t in tickets)
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
