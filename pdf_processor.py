import io
import zipfile
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageEnhance, ImageOps
import pymupdf as fitz
import pypdf

from gdrive_sync import sync_file_to_gdrive, delete_file_from_gdrive
from ticket_ocr import (
    extract_data_from_image,
    add_ticket_expense,
    remove_last_ticket_expense,
    delete_month_expenses,
    sanitize_email,
    extract_month_from_date,
    get_monthly_summary
)

BASE_DIR = Path(__file__).resolve().parent
PDFS_DIR = BASE_DIR / "PDFs_Mensuales"
IMAGES_DIR = BASE_DIR / "Imagenes_Originales"

PDFS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

def get_user_pdf_dir(user_email: str = None) -> Path:
    safe_email = sanitize_email(user_email)
    if safe_email:
        user_dir = PDFS_DIR / safe_email
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    return PDFS_DIR

def enhance_thermal_ticket(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    img = ImageEnhance.Contrast(img).enhance(1.4)
    img = ImageEnhance.Sharpness(img).enhance(1.5)
    return img

def image_to_a4_pdf(img: Image.Image) -> bytes:
    # Redimensionar si excede 1200px para mantener uso de RAM mínimo (< 50MB)
    max_dim = 1200
    w, h = img.size
    if max(w, h) > max_dim:
        scale_factor = max_dim / float(max(w, h))
        img = img.resize((int(w * scale_factor), int(h * scale_factor)), Image.Resampling.LANCZOS)
        
    a4_w, a4_h = 595.27, 841.89  # A4 a 72 dpi
    margin = 36.0
    max_w = a4_w - (margin * 2)
    max_h = a4_h - (margin * 2)
    
    img_w, img_h = img.size
    scale = min(max_w / img_w, max_h / img_h)
    new_w = img_w * scale
    new_h = img_h * scale
    
    doc = fitz.open()
    page = doc.new_page(width=a4_w, height=a4_h)
    
    img_byte_arr = io.BytesIO()
    # Guardar en JPEG optimizado (calidad 80) para reducir el PDF de 7.5 MB a ~250 KB
    img.save(img_byte_arr, format='JPEG', quality=80, optimize=True)
    img_bytes = img_byte_arr.getvalue()
    
    x0 = (a4_w - new_w) / 2
    y0 = (a4_h - new_h) / 2
    rect = fitz.Rect(x0, y0, x0 + new_w, y0 + new_h)
    
    page.insert_image(rect, stream=img_bytes)
    pdf_bytes = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return pdf_bytes

def append_ticket_to_month_pdf(
    image_bytes: bytes,
    filename_hint: str,
    month_str: str = None,
    enhance: bool = True,
    user_vendor: str = None,
    user_total: float = None,
    user_cuit: str = None,
    user_date: str = None,
    user_subtotal: float = None,
    user_iva_21: float = None,
    user_iva_10_5: float = None,
    user_iva_27: float = None,
    user_email: str = None,
    user_items: list = None
) -> dict:
    now = datetime.now()
    
    # 1. Extraer datos del ticket primero para identificar la fecha real impresa
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    safe_filename = f"{timestamp}_{filename_hint}"
    
    extracted_data = extract_data_from_image(
        image_bytes,
        filename_hint=safe_filename,
        user_vendor=user_vendor,
        user_total=user_total,
        user_cuit=user_cuit,
        user_date=user_date,
        user_subtotal=user_subtotal,
        user_iva_21=user_iva_21,
        user_iva_10_5=user_iva_10_5,
        user_iva_27=user_iva_27,
        user_items=user_items
    )
    
    # 2. Ruteo automático del mes según la FECHA REAL del ticket
    printed_date = user_date or extracted_data.get("date")
    auto_month = extract_month_from_date(printed_date)
    
    if auto_month:
        target_month = auto_month
    elif month_str:
        target_month = month_str.replace("-", "_")
    else:
        target_month = now.strftime("%Y_%m")
        
    month_img_dir = IMAGES_DIR / target_month
    month_img_dir.mkdir(parents=True, exist_ok=True)
    
    raw_img_path = month_img_dir / safe_filename
    with open(raw_img_path, "wb") as f:
        f.write(image_bytes)
        
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode != 'RGB':
        img = img.convert('RGB')
        
    if enhance:
        img = enhance_thermal_ticket(img)
        
    new_page_pdf_bytes = image_to_a4_pdf(img)
    
    target_pdf_dir = get_user_pdf_dir(user_email)
    target_pdf_path = target_pdf_dir / f"Tickets_{target_month}.pdf"
    
    writer = pypdf.PdfWriter()
    # 1. Agregar PRIMERO el nuevo ticket (Página 1)
    new_reader = pypdf.PdfReader(io.BytesIO(new_page_pdf_bytes))
    for page in new_reader.pages:
        writer.add_page(page)
        
    # 2. Agregar los tickets anteriores (Páginas 2, 3...)
    if target_pdf_path.exists() and target_pdf_path.stat().st_size > 0:
        reader = pypdf.PdfReader(str(target_pdf_path))
        for page in reader.pages:
            writer.add_page(page)
            
    with open(target_pdf_path, 'wb') as f:
        writer.write(f)
        
    total_pages = len(pypdf.PdfReader(str(target_pdf_path)).pages)
    
    add_ticket_expense(target_month, extracted_data, user_email)
    
    import gc
    gc.collect()
    
    summary = get_monthly_summary(target_month, user_email)
    
    return {
        "success": True,
        "month": target_month,
        "pdf_filename": f"Tickets_{target_month}.pdf",
        "total_tickets": total_pages,
        "image_saved": str(raw_img_path.name),
        "extracted_data": extracted_data,
        "expenses_summary": summary
    }

def remove_last_page_from_pdf(month_str: str, user_email: str = None) -> dict:
    month_str = month_str.replace("-", "_")
    target_pdf_dir = get_user_pdf_dir(user_email)
    target_pdf_path = target_pdf_dir / f"Tickets_{month_str}.pdf"
    
    remove_last_ticket_expense(month_str, user_email)
    
    if not target_pdf_path.exists() or target_pdf_path.stat().st_size == 0:
        return {"success": False, "error": "No existe PDF para este mes"}
        
    reader = pypdf.PdfReader(str(target_pdf_path))
    total = len(reader.pages)
    
    if total <= 1:
        target_pdf_path.unlink(missing_ok=True)
        try:
            delete_file_from_gdrive(f"Tickets_{month_str}.pdf", user_email=user_email)
            delete_file_from_gdrive(f"Gastos_{month_str}.json", user_email=user_email)
        except Exception:
            pass
        return {"success": True, "remaining_pages": 0, "month": month_str}
        
    writer = pypdf.PdfWriter()
    for idx in range(1, total):
        writer.add_page(reader.pages[idx])
        
    with open(target_pdf_path, 'wb') as f:
        writer.write(f)
        
    return {
        "success": True,
        "remaining_pages": total - 1,
        "month": month_str
    }

def delete_entire_month_pdf(month_str: str, user_email: str = None) -> dict:
    month_str = month_str.replace("-", "_")
    target_pdf_dir = get_user_pdf_dir(user_email)
    target_pdf_path = target_pdf_dir / f"Tickets_{month_str}.pdf"
    
    delete_month_expenses(month_str, user_email)
    
    if target_pdf_path.exists():
        target_pdf_path.unlink()
        
    try:
        delete_file_from_gdrive(f"Tickets_{month_str}.pdf", user_email=user_email)
        delete_file_from_gdrive(f"Gastos_{month_str}.json", user_email=user_email)
    except Exception:
        pass
        
    return {"success": True, "month": month_str, "message": "PDF y datos eliminados completamente"}

def get_monthly_stats(user_email: str = None) -> list[dict]:
    stats = []
    target_pdf_dir = get_user_pdf_dir(user_email)
    if not target_pdf_dir.exists():
        return stats
        
    for pdf_file in sorted(target_pdf_dir.glob("Tickets_*.pdf"), reverse=True):
        try:
            reader = pypdf.PdfReader(str(pdf_file))
            num_pages = len(reader.pages)
            size_mb = round(pdf_file.stat().st_size / (1024 * 1024), 2)
            mtime = datetime.fromtimestamp(pdf_file.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            month_key = pdf_file.stem.replace("Tickets_", "")
            
            stats.append({
                "filename": pdf_file.name,
                "month_key": month_key,
                "pages": num_pages,
                "size_mb": size_mb,
                "last_updated": mtime
            })
        except Exception as e:
            print(f"Error leyendo {pdf_file}: {e}")
    return stats

def generate_zip_report(month_str: str, user_email: str = None) -> bytes:
    """
    Genera un archivo ZIP con todas las imágenes de los tickets del mes.
    Si las imágenes en la carpeta de imágenes no están disponibles, las extrae del PDF.
    """
    month_key = month_str.replace("-", "_")
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        month_img_dir = IMAGES_DIR / month_key
        added_files = 0
        if month_img_dir.exists():
            for img_path in sorted(month_img_dir.glob("*")):
                if img_path.is_file() and img_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                    zip_file.write(img_path, arcname=img_path.name)
                    added_files += 1
                    
        # Si no hay imágenes directas en disco, extraer del PDF del usuario
        if added_files == 0:
            target_pdf_dir = get_user_pdf_dir(user_email)
            pdf_path = target_pdf_dir / f"Tickets_{month_key}.pdf"
            if pdf_path.exists():
                doc = fitz.open(str(pdf_path))
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    image_list = page.get_images()
                    for img_index, img_info in enumerate(image_list):
                        xref = img_info[0]
                        base_img = doc.extract_image(xref)
                        img_bytes = base_img["image"]
                        ext = base_img["ext"]
                        filename = f"Ticket_{month_key}_pag_{page_num+1}.{ext}"
                        zip_file.writestr(filename, img_bytes)
                doc.close()
                
    return zip_buffer.getvalue()

