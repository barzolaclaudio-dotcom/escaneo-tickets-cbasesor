import io
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageEnhance, ImageOps
import pymupdf as fitz
import pypdf

from gdrive_sync import sync_file_to_gdrive
from ticket_ocr import (
    extract_data_from_image,
    add_ticket_expense,
    remove_last_ticket_expense,
    delete_month_expenses
)

BASE_DIR = Path(__file__).resolve().parent
PDFS_DIR = BASE_DIR / "PDFs_Mensuales"
IMAGES_DIR = BASE_DIR / "Imagenes_Originales"

PDFS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

def enhance_thermal_ticket(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    img = ImageEnhance.Contrast(img).enhance(1.4)
    img = ImageEnhance.Sharpness(img).enhance(1.5)
    return img

def image_to_a4_pdf(img: Image.Image) -> bytes:
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
    img.save(img_byte_arr, format='PNG')
    img_bytes = img_byte_arr.getvalue()
    
    x0 = (a4_w - new_w) / 2
    y0 = (a4_h - new_h) / 2
    rect = fitz.Rect(x0, y0, x0 + new_w, y0 + new_h)
    
    page.insert_image(rect, stream=img_bytes)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

def append_ticket_to_month_pdf(image_bytes: bytes, filename_hint: str, month_str: str = None, enhance: bool = True, user_vendor: str = None, user_total: float = None) -> dict:
    now = datetime.now()
    if not month_str:
        month_str = now.strftime("%Y_%m")
    else:
        month_str = month_str.replace("-", "_")
    
    month_img_dir = IMAGES_DIR / month_str
    month_img_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    safe_filename = f"{timestamp}_{filename_hint}"
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
    
    target_pdf_path = PDFS_DIR / f"Tickets_{month_str}.pdf"
    
    writer = pypdf.PdfWriter()
    if target_pdf_path.exists() and target_pdf_path.stat().st_size > 0:
        reader = pypdf.PdfReader(str(target_pdf_path))
        for page in reader.pages:
            writer.add_page(page)
            
    new_reader = pypdf.PdfReader(io.BytesIO(new_page_pdf_bytes))
    for page in new_reader.pages:
        writer.add_page(page)
        
    with open(target_pdf_path, 'wb') as f:
        writer.write(f)
        
    total_pages = len(pypdf.PdfReader(str(target_pdf_path)).pages)
    
    extracted_data = extract_data_from_image(image_bytes, filename_hint=safe_filename, user_vendor=user_vendor, user_total=user_total)
    add_ticket_expense(month_str, extracted_data)
    
    gdrive_link = sync_file_to_gdrive(target_pdf_path)
    
    return {
        "success": True,
        "month": month_str,
        "pdf_filename": f"Tickets_{month_str}.pdf",
        "total_tickets": total_pages,
        "image_saved": str(raw_img_path.name),
        "extracted_data": extracted_data,
        "gdrive_link": gdrive_link
    }

def remove_last_page_from_pdf(month_str: str) -> dict:
    month_str = month_str.replace("-", "_")
    target_pdf_path = PDFS_DIR / f"Tickets_{month_str}.pdf"
    
    remove_last_ticket_expense(month_str)
    
    if not target_pdf_path.exists() or target_pdf_path.stat().st_size == 0:
        return {"success": False, "error": "No existe PDF para este mes"}
        
    reader = pypdf.PdfReader(str(target_pdf_path))
    total = len(reader.pages)
    
    if total <= 1:
        target_pdf_path.unlink(missing_ok=True)
        return {"success": True, "remaining_pages": 0, "month": month_str}
        
    writer = pypdf.PdfWriter()
    for idx in range(total - 1):
        writer.add_page(reader.pages[idx])
        
    with open(target_pdf_path, 'wb') as f:
        writer.write(f)
        
    gdrive_link = sync_file_to_gdrive(target_pdf_path)
    
    return {
        "success": True,
        "remaining_pages": total - 1,
        "month": month_str,
        "gdrive_link": gdrive_link
    }

def delete_entire_month_pdf(month_str: str) -> dict:
    month_str = month_str.replace("-", "_")
    target_pdf_path = PDFS_DIR / f"Tickets_{month_str}.pdf"
    
    delete_month_expenses(month_str)
    
    if target_pdf_path.exists():
        target_pdf_path.unlink()
        return {"success": True, "month": month_str, "message": "PDF y datos eliminados completamente"}
    return {"success": False, "error": "El archivo no existe"}

def get_monthly_stats() -> list[dict]:
    stats = []
    if not PDFS_DIR.exists():
        return stats
        
    for pdf_file in sorted(PDFS_DIR.glob("Tickets_*.pdf"), reverse=True):
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
