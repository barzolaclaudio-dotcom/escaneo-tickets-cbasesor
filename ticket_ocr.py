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
    """Convierte cadenas de texto de montos en formato argentino/internacional a float."""
    if not text_str:
        return 0.0
    try:
        clean = text_str.replace('$', '').strip()
        # Formato argentino: 141.424,30 -> 141424.30
        if ',' in clean and '.' in clean:
            clean = clean.replace('.', '').replace(',', '.')
        elif ',' in clean:
            clean = clean.replace(',', '.')
        return float(clean)
    except Exception:
        return 0.0

def extract_data_from_image(image_bytes: bytes, filename_hint: str = "") -> dict:
    """
    Analiza la imagen del ticket mediante OCR y patrones regex inteligentes para extraer:
    - Nombre del Comercio
    - CUIT
    - Tipo de Comprobante (Factura A / Ticket)
    - Fecha
    - Subtotal Neto, IVA 21%, IVA 10.5%, Monto Total
    - Lista de Ítems / Productos comprados
    """
    raw_text = ""
    try:
        # Usar PyMuPDF para extraer texto de la imagen
        doc = pymupdf.open()
        img_doc = pymupdf.open("png", image_bytes)
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        
        pdf_mem = pymupdf.open("pdf", pdf_bytes)
        page = pdf_mem[0]
        
        # Intentar extracción de texto
        raw_text = page.get_text("text")
        pdf_mem.close()
    except Exception as e:
        logger.warning(f"Error en OCR inicial: {e}")

    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    
    # 1. Detectar Nombre de Comercio (primeras líneas no vacías)
    vendor = "Comercio General"
    for line in lines[:5]:
        if len(line) > 3 and not re.search(r'factura|cuit|ticket|original|fecha', line, re.I):
            vendor = line.title()
            break

    # 2. Detectar CUIT (Formato XX-XXXXXXXX-X)
    cuit_match = re.search(r'\b\d{2}-?\d{8}-?\d{1}\b', raw_text)
    cuit = cuit_match.group(0) if cuit_match else ""

    # 3. Detectar Fecha
    date_match = re.search(r'\b(\d{2}[/\.-]\d{2}[/\.-]\d{2,4})\b', raw_text)
    date_str = date_match.group(1) if date_match else datetime.now().strftime("%d/%m/%Y")

    # 4. Detectar Tipo de Comprobante
    comp_type = "Factura A" if "FACTURA A" in raw_text.upper() else "Ticket / Comprobante"

    # 5. Detectar Monto Total
    total = 0.0
    total_match = re.search(r'(?:TOTAL|IMPORTE TOTAL|\bTOTAL \$)\s*[:=]?\s*\$?\s*([\d\.,]+)', raw_text, re.I)
    if total_match:
        total = parse_amount(total_match.group(1))
    else:
        # Buscar el número más alto cerca del final
        numbers = re.findall(r'\$?\s*([\d]{1,3}(?:\.[\d]{3})*(?:,[\d]{2})|\b[\d]+\.[\d]{2}\b)', raw_text)
        parsed_nums = [parse_amount(n) for n in numbers if parse_amount(n) > 0]
        if parsed_nums:
            total = max(parsed_nums)

    # 6. Detectar Subtotal e IVA
    subtotal = 0.0
    neto_match = re.search(r'(?:SUBTOTAL|NETO GRAVADO|NETO)\s*[:=]?\s*\$?\s*([\d\.,]+)', raw_text, re.I)
    if neto_match:
        subtotal = parse_amount(neto_match.group(1))
    else:
        subtotal = round(total / 1.21, 2) if total > 0 else 0.0

    iva_21 = 0.0
    iva_match = re.search(r'(?:IVA 21%|IVA 21|IVA GRAVADO)\s*[:=]?\s*\$?\s*([\d\.,]+)', raw_text, re.I)
    if iva_match:
        iva_21 = parse_amount(iva_match.group(1))
    else:
        iva_21 = round(total - subtotal, 2) if total > 0 else 0.0

    iva_10_5 = 0.0
    iva10_match = re.search(r'(?:IVA 10\.5%|IVA 10,5)\s*[:=]?\s*\$?\s*([\d\.,]+)', raw_text, re.I)
    if iva10_match:
        iva_10_5 = parse_amount(iva10_match.group(1))

    # 7. Extraer Ítems / Productos (Líneas del cuerpo del ticket)
    items = []
    for line in lines[3:-2]:
        # Buscar patrón: Descripción + Precio
        price_match = re.search(r'([A-Za-z0-9\s%-]{3,30})\s+\$?\s*([\d\.,]{3,10})$', line)
        if price_match and not re.search(r'total|subtotal|iva|cuit|fecha|base', price_match.group(1), re.I):
            p_name = price_match.group(1).strip()
            p_price = parse_amount(price_match.group(2))
            if p_price > 0:
                items.append({
                    "name": p_name,
                    "qty": 1,
                    "price": p_price
                })

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
        "items": items,
        "filename": filename_hint
    }

def get_month_data_file(month_str: str) -> Path:
    """Retorna la ruta del archivo JSON de datos del mes."""
    month_key = month_str.replace("-", "_")
    return DATA_DIR / f"Gastos_{month_key}.json"

def load_monthly_expenses(month_str: str) -> list[dict]:
    """Carga la lista de gastos/tickets registrados en un mes determinado."""
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
    """Guarda la lista completa de gastos del mes en formato JSON."""
    data_file = get_month_data_file(month_str)
    try:
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(tickets_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando gastos de {month_str}: {e}")

def add_ticket_expense(month_str: str, ticket_data: dict):
    """Agrega un nuevo ticket analizado a la base de datos del mes."""
    current = load_monthly_expenses(month_str)
    current.append(ticket_data)
    save_monthly_expenses(month_str, current)

def remove_last_ticket_expense(month_str: str):
    """Elimina el último ticket de la base de datos del mes."""
    current = load_monthly_expenses(month_str)
    if current:
        current.pop()
        save_monthly_expenses(month_str, current)

def delete_month_expenses(month_str: str):
    """Elimina toda la base de datos de gastos de un mes."""
    data_file = get_month_data_file(month_str)
    if data_file.exists():
        data_file.unlink()

def get_monthly_summary(month_str: str) -> dict:
    """
    Calcula en tiempo real los totales, desglose por comercio e ítems del mes.
    """
    tickets = load_monthly_expenses(month_str)
    
    total_spent = sum(t.get("total", 0.0) for t in tickets)
    total_subtotal = sum(t.get("subtotal", 0.0) for t in tickets)
    total_iva = sum(t.get("iva_21", 0.0) + t.get("iva_10_5", 0.0) for t in tickets)
    total_items_count = sum(len(t.get("items", [])) for t in tickets)
    
    # Desglose por comercio
    vendors = {}
    for t in tickets:
        v_name = t.get("vendor", "Otros")
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
