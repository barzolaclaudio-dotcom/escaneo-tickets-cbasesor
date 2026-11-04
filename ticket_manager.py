"""
Gestión de tickets individuales: ver imagen, editar y eliminar.

Convención: el ticket en la posición N de la lista de gastos (Gastos_YYYY_MM.json)
corresponde a la página N del PDF mensual (Tickets_YYYY_MM.pdf). Ambos se
insertan siempre al principio al escanear un ticket nuevo.
"""
import io
import shutil
from pathlib import Path
import pypdf
import pymupdf as fitz

from gdrive_sync import delete_file_from_gdrive
from pdf_processor import get_user_pdf_dir
from ticket_ocr import (
    load_monthly_expenses,
    save_monthly_expenses,
    delete_month_expenses,
    extract_month_from_date,
    get_monthly_summary,
)

BASE_DIR = Path(__file__).resolve().parent

NUMERIC_FIELDS = ("total", "subtotal", "iva_21", "iva_10_5", "iva_27", "percepcion_iibb", "percepcion_iva", "impuestos_internos")
TEXT_FIELDS = ("vendor", "cuit", "date", "invoice_type", "invoice_number", "percepcion_iibb_jurisdiccion", "cae", "cae_vto")


def _pdf_path(month_key: str, user_email: str = None):
    return get_user_pdf_dir(user_email) / f"Tickets_{month_key}.pdf"


def render_ticket_page_jpeg(month: str, index: int, user_email: str = None):
    """Devuelve la imagen (JPEG) del ticket que está en la página `index` del PDF del mes."""
    month_key = month.replace("-", "_")
    path = _pdf_path(month_key, user_email)
    if not path.exists() or path.stat().st_size == 0:
        return None
    doc = fitz.open(str(path))
    try:
        if index < 0 or index >= len(doc):
            return None
        page = doc[index]
        clip = page.rect
        for img in page.get_images(full=True):
            rects = page.get_image_rects(img[0])
            if rects:
                clip = rects[0]
                break
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip)
        return pix.tobytes("jpeg")
    finally:
        doc.close()


def _remove_page(month_key: str, index: int, user_email: str = None):
    """Quita la página `index` del PDF. Devuelve (bytes_de_la_pagina | None, paginas_restantes)."""
    path = _pdf_path(month_key, user_email)
    if not path.exists() or path.stat().st_size == 0:
        return None, 0
    reader = pypdf.PdfReader(str(path))
    total = len(reader.pages)
    if index < 0 or index >= total:
        return None, total

    removed = io.BytesIO()
    single = pypdf.PdfWriter()
    single.add_page(reader.pages[index])
    single.write(removed)

    if total <= 1:
        path.unlink(missing_ok=True)
        return removed.getvalue(), 0

    writer = pypdf.PdfWriter()
    for i in range(total):
        if i != index:
            writer.add_page(reader.pages[i])
    with open(path, "wb") as f:
        writer.write(f)
    return removed.getvalue(), total - 1


def _insert_page_first(month_key: str, page_bytes: bytes, user_email: str = None):
    path = _pdf_path(month_key, user_email)
    writer = pypdf.PdfWriter()
    for p in pypdf.PdfReader(io.BytesIO(page_bytes)).pages:
        writer.add_page(p)
    if path.exists() and path.stat().st_size > 0:
        for p in pypdf.PdfReader(str(path)).pages:
            writer.add_page(p)
    with open(path, "wb") as f:
        writer.write(f)


def _cleanup_empty_month(month_key: str, user_email: str = None):
    delete_month_expenses(month_key, user_email)
    try:
        delete_file_from_gdrive(f"Tickets_{month_key}.pdf", user_email=user_email)
        delete_file_from_gdrive(f"Gastos_{month_key}.json", user_email=user_email)
    except Exception:
        pass


def delete_ticket(month: str, index: int, user_email: str = None) -> dict:
    month_key = month.replace("-", "_")
    tickets = load_monthly_expenses(month_key, user_email)
    if index < 0 or index >= len(tickets):
        return {"success": False, "error": "Ticket no encontrado"}

    tickets.pop(index)
    _remove_page(month_key, index, user_email)

    if not tickets:
        _cleanup_empty_month(month_key, user_email)
        return {"success": True, "month": month_key, "remaining": 0}

    save_monthly_expenses(month_key, tickets, user_email)
    return {"success": True, "month": month_key, "remaining": len(tickets)}


def edit_ticket(month: str, index: int, fields: dict, user_email: str = None) -> dict:
    """
    Edita los datos de un ticket. Si la nueva fecha cae en otro mes, el ticket
    (datos + imagen) se mueve automáticamente al mes correspondiente.
    """
    month_key = month.replace("-", "_")
    tickets = load_monthly_expenses(month_key, user_email)
    if index < 0 or index >= len(tickets):
        return {"success": False, "error": "Ticket no encontrado"}

    ticket = dict(tickets[index])
    for k in TEXT_FIELDS:
        if k in fields and fields[k] is not None:
            ticket[k] = str(fields[k]).strip()
    for k in NUMERIC_FIELDS:
        if k in fields and fields[k] is not None:
            ticket[k] = round(float(fields[k]), 2)

    new_month = extract_month_from_date(ticket.get("date")) or month_key

    if new_month == month_key:
        tickets[index] = ticket
        save_monthly_expenses(month_key, tickets, user_email)
        return {"success": True, "month": month_key, "moved": False}

    # Mover a otro mes
    tickets.pop(index)
    page_bytes, _ = _remove_page(month_key, index, user_email)
    if tickets:
        save_monthly_expenses(month_key, tickets, user_email)
    else:
        _cleanup_empty_month(month_key, user_email)

    target = load_monthly_expenses(new_month, user_email)
    target.insert(0, ticket)
    save_monthly_expenses(new_month, target, user_email)
    if page_bytes:
        _insert_page_first(new_month, page_bytes, user_email)

    return {"success": True, "month": month_key, "new_month": new_month, "moved": True}


def delete_vendor_tickets(month: str, vendor: str, user_email: str = None) -> dict:
    """
    Elimina todos los tickets (datos y páginas del PDF) de un comercio específico en el mes.
    """
    month_key = month.replace("-", "_")
    tickets = load_monthly_expenses(month_key, user_email)
    if not tickets:
        return {"success": True, "month": month_key, "remaining": 0, "deleted_count": 0}

    target_vendor_norm = (vendor or "Comercio General").strip().lower()

    indices_to_delete = []
    kept_tickets = []
    kept_indices = []

    for idx, t in enumerate(tickets):
        t_vendor_norm = (t.get("vendor") or "Comercio General").strip().lower()
        if t_vendor_norm == target_vendor_norm:
            indices_to_delete.append(idx)
        else:
            kept_tickets.append(t)
            kept_indices.append(idx)

    if not indices_to_delete:
        return {"success": False, "error": f"No se encontraron tickets de {vendor}"}

    deleted_count = len(indices_to_delete)
    path = _pdf_path(month_key, user_email)

    if not kept_tickets:
        if path.exists():
            path.unlink(missing_ok=True)
        _cleanup_empty_month(month_key, user_email)
        return {"success": True, "month": month_key, "remaining": 0, "deleted_count": deleted_count}

    if path.exists() and path.stat().st_size > 0:
        reader = pypdf.PdfReader(str(path))
        writer = pypdf.PdfWriter()
        for idx in kept_indices:
            if idx < len(reader.pages):
                writer.add_page(reader.pages[idx])
        with open(path, "wb") as f:
            writer.write(f)

    save_monthly_expenses(month_key, kept_tickets, user_email)
    return {"success": True, "month": month_key, "remaining": len(kept_tickets), "deleted_count": deleted_count}


def delete_entire_month_total(month_str: str, user_email: str = None, delete_all_docs: bool = True) -> dict:
    """
    Elimina de forma total y completa todos los datos y comprobantes del mes:
    - PDF consolidado de tickets
    - JSON de gastos y tickets
    - Imágenes del mes en Imagenes_Originales
    - Si delete_all_docs=True: tarjetas, bancos, inversiones, retenciones/VEPs del mes
    - Limpieza en Google Drive
    """
    month_key = month_str.replace("-", "_")

    # 1. Eliminar tickets y PDF consolidado
    target_pdf_dir = get_user_pdf_dir(user_email)
    target_pdf_path = target_pdf_dir / f"Tickets_{month_key}.pdf"
    if target_pdf_path.exists():
        target_pdf_path.unlink(missing_ok=True)

    delete_month_expenses(month_key, user_email)

    try:
        delete_file_from_gdrive(f"Tickets_{month_key}.pdf", user_email=user_email)
        delete_file_from_gdrive(f"Gastos_{month_key}.json", user_email=user_email)
    except Exception:
        pass

    # 2. Eliminar imágenes temporales en Imagenes_Originales
    img_dir = BASE_DIR / "Imagenes_Originales" / month_key
    if img_dir.exists():
        try:
            shutil.rmtree(img_dir, ignore_errors=True)
        except Exception:
            pass

    # 3. Eliminar otros módulos del mes si se solicita
    if delete_all_docs:
        from ticket_ocr import get_user_data_dir, sanitize_email
        data_dir = get_user_data_dir(user_email)
        for doc_name in [f"tarjetas_{month_key}.json", f"bancos_{month_key}.json", f"inversiones_{month_key}.json", f"retenciones_{month_key}.json"]:
            fpath = data_dir / doc_name
            if fpath.exists():
                fpath.unlink(missing_ok=True)
            try:
                delete_file_from_gdrive(doc_name, user_email=user_email)
            except Exception:
                pass

        if user_email:
            docs_user_dir = BASE_DIR / "Documentos_Mensuales" / sanitize_email(user_email)
            if docs_user_dir.exists():
                for sub in docs_user_dir.glob(f"**/*{month_key}*"):
                    if sub.is_file():
                        sub.unlink(missing_ok=True)

    return {
        "success": True,
        "month": month_key,
        "message": "Todos los comprobantes y datos del mes han sido eliminados de forma total."
    }
