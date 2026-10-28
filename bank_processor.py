import io
import re
import json
import base64
import logging
from pathlib import Path
from datetime import datetime
import pymupdf
import requests
import os
from ticket_ocr import sanitize_email, get_user_data_dir

logger = logging.getLogger("bank_processor")
logger.setLevel(logging.INFO)

_KEY_B64 = "QVEuQWI4Uk42TFhGOVhzQUxENGo5RDhzcmhPTlNId2JhaDVDa3gzdXo4SGlFRHI3dHVCYWc="

def get_bank_data_file(month_str: str, user_email: str = None) -> Path:
    """Ruta al archivo JSON de bancos y préstamos para el usuario y mes."""
    data_dir = get_user_data_dir(user_email)
    month_clean = month_str.replace("-", "_")
    return data_dir / f"bancos_{month_clean}.json"

def load_monthly_bank_data(month_str: str, user_email: str = None) -> list[dict]:
    """Carga los documentos bancarios y préstamos procesados para un mes dado."""
    file_path = get_bank_data_file(month_str, user_email)
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error leyendo {file_path}: {e}")
        return []

def save_monthly_bank_data(month_str: str, docs_list: list[dict], user_email: str = None):
    """Guarda la lista de documentos bancarios del mes."""
    file_path = get_bank_data_file(month_str, user_email)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(docs_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando {file_path}: {e}")

def add_bank_doc_to_month(month_str: str, doc_data: dict, user_email: str = None) -> dict:
    """Agrega o reemplaza un documento bancario o de préstamo para el mes."""
    docs = load_monthly_bank_data(month_str, user_email)
    doc_id = doc_data.get("id") or f"bank_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    doc_data["id"] = doc_id
    
    # Si ya existía con el mismo ID o mismos identificadores clave, se actualiza
    existing_idx = -1
    for idx, d in enumerate(docs):
        if d.get("id") == doc_id:
            existing_idx = idx
            break
        # Comparación si es préstamo
        if doc_data.get("tipo_documento") == "cuota_prestamo" and d.get("tipo_documento") == "cuota_prestamo":
            if (d.get("entidad") == doc_data.get("entidad") and 
                d.get("numero_prestamo") == doc_data.get("numero_prestamo") and
                d.get("cuota_actual") == doc_data.get("cuota_actual")):
                existing_idx = idx
                break
        # Comparación si es extracto
        elif doc_data.get("tipo_documento") == "extracto_bancario" and d.get("tipo_documento") == "extracto_bancario":
            if (d.get("entidad") == doc_data.get("entidad") and 
                d.get("numero_cuenta") == doc_data.get("numero_cuenta") and
                d.get("periodo_desde") == doc_data.get("periodo_desde")):
                existing_idx = idx
                break

    if existing_idx >= 0:
        docs[existing_idx] = doc_data
    else:
        docs.append(doc_data)

    save_monthly_bank_data(month_str, docs, user_email)
    return doc_data

def delete_bank_doc_from_month(month_str: str, doc_id: str, user_email: str = None) -> bool:
    """Elimina un documento bancario por ID."""
    docs = load_monthly_bank_data(month_str, user_email)
    initial_len = len(docs)
    docs = [d for d in docs if d.get("id") != doc_id]
    if len(docs) < initial_len:
        save_monthly_bank_data(month_str, docs, user_email)
        return True
    return False

def parse_bank_or_loan_pdf(pdf_bytes: bytes, filename_hint: str = "") -> dict:
    """
    Extrae el texto del PDF con PyMuPDF y utiliza Gemini IA para interpretar y estructurar:
    - Comprobantes de pago de cuotas de préstamos (Capital, Intereses, IVA 21%, Seguros, etc.)
    - Extractos bancarios (Cuentas corrientes / cajas de ahorro: Saldos, Débitos/Créditos,
      Comisiones, Impuesto Ley 25413, Retenciones SIRCREB/IIBB).
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        full_text = "\n".join([page.get_text() for page in doc])
    except Exception as e:
        logger.error(f"Error abriendo PDF bancario con PyMuPDF: {e}")
        return {"error": f"No se pudo leer el archivo PDF: {str(e)}"}

    if not full_text.strip():
        return {"error": "El documento no contiene texto legible (puede ser un escaneo de baja resolución o imagen sin capa de texto)."}

    # Clave de Gemini API
    fallback_key = base64.b64decode(_KEY_B64).decode("utf-8")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or fallback_key

    prompt = f"""Sos un contador público y perito bancario experto en el sistema financiero de Argentina.
Analiza con máxima precisión el siguiente texto extraído de un documento bancario o de financiamiento (nombre archivo: '{filename_hint}').

Determina si es:
A) Un 'cuota_prestamo' (comprobante de pago o débito de cuota de préstamo, mutuo bancario o liquidación financiera).
B) Un 'extracto_bancario' (resumen de cuenta corriente o caja de ahorro con movimientos y saldos).

Responde ÚNICAMENTE con un JSON válido con una de estas dos estructuras exactas según corresponda:

SI ES 'cuota_prestamo':
{{
  "tipo_documento": "cuota_prestamo",
  "entidad": "Banco o Entidad Financiera (ej: Banco Supervielle, Banco Credicoop, Banco Nación, Banco Galicia, etc.)",
  "titular": "Nombre del titular o razón social",
  "numero_prestamo": "Número de operación o préstamo si figura (o null)",
  "cuota_actual": 2,
  "cuota_total": 24,
  "fecha_vencimiento": "DD/MM/YYYY",
  "fecha_pago": "DD/MM/YYYY",
  "periodo": "YYYY_MM (estimado por la fecha de pago o vencimiento)",
  "moneda": "ARS | USD",
  "monto_total": 0.00,
  "desglose": {{
    "capital": 0.00,
    "interes_compensatorio": 0.00,
    "interes_punitorio": 0.00,
    "iva_intereses": 0.00,
    "seguro_vida_deudor": 0.00,
    "gastos_administrativos": 0.00,
    "sellos_u_otros": 0.00
  }},
  "saldo_deuda_remanente": 0.00,
  "observaciones": "Breve resumen legible (ej: 'Cuota 2/24 Préstamo Personal / Comercial Supervielle')"
}}

SI ES 'extracto_bancario':
{{
  "tipo_documento": "extracto_bancario",
  "entidad": "Banco o Entidad (ej: Banco Nación, Banco Supervielle, Banco Credicoop, Brubank, etc.)",
  "titular": "Nombre del titular o razón social",
  "tipo_cuenta": "Cuenta Corriente | Caja de Ahorro | Cuenta Sueldo",
  "numero_cuenta": "Número de cuenta si figura",
  "cbu": "CBU si figura o null",
  "moneda": "ARS | USD",
  "periodo_desde": "DD/MM/YYYY",
  "periodo_hasta": "DD/MM/YYYY",
  "periodo": "YYYY_MM",
  "saldo_inicial": 0.00,
  "saldo_final": 0.00,
  "total_debitos": 0.00,
  "total_creditos": 0.00,
  "gastos_e_impuestos_deducibles": {{
    "comisiones_mantenimiento": 0.00,
    "impuesto_ley_25413_debitos_creditos": 0.00,
    "iva_bancario_21": 0.00,
    "percepcion_sircreb_iibb": 0.00,
    "otros_impuestos": 0.00
  }},
  "movimientos_principales": [
    {{
      "fecha": "DD/MM/YYYY",
      "concepto": "Descripción del movimiento limpia",
      "tipo": "DEBITO | CREDITO",
      "monto": 0.00,
      "categoria": "Transferencia | Débito Automático | Impuestos y Comisiones | Cuota Préstamo | Sueldos | Varios"
    }}
  ]
}}

REGLAS DE ORO:
1. Todos los montos deben ser números flotantes no negativos (ej: 145000.50).
2. Si cuota_actual o cuota_total no figuran explícitamente pero dice 'Cuota 02 de 24', asigna cuota_actual=2 y cuota_total=24.
3. El IVA de los intereses bancarios y el Impuesto a los Débitos y Créditos (Ley 25.413) son vitales para el contador; extráelos con suma precisión si están presentes.
4. En 'movimientos_principales' resume hasta un máximo de 35 movimientos más significativos (priorizando débitos automáticos, préstamos, impuestos e importes grandes) para evitar saturar memoria.
5. Devuelve EXCLUSIVAMENTE el JSON.

TEXTO DEL DOCUMENTO:
{full_text}
"""

    models_to_try = [
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite-preview",
        "gemini-3.8-flash"
    ]

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=40)
            if resp.status_code == 200:
                res_json = resp.json()
                candidates = res_json.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    raw_text = "".join([p.get("text", "") for p in parts if "text" in p]).strip()
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                        raw_text = re.sub(r"\s*```$", "", raw_text)
                    parsed_data = json.loads(raw_text)
                    parsed_data["success"] = True
                    parsed_data["filename"] = filename_hint
                    return parsed_data
            else:
                logger.warning(f"Gemini API ({model_name}) HTTP {resp.status_code}: {resp.text[:150]}")
        except Exception as ex:
            logger.warning(f"Error intentando modelo {model_name} en bank_processor: {ex}")

    return {"error": "No se pudo interpretar el documento bancario con IA. Verifique que sea un PDF válido y reintente."}
