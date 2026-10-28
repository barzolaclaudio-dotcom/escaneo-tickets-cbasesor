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
from ticket_ocr import sanitize_email, get_user_data_dir, redistribute_user_documents

logger = logging.getLogger("tax_processor")
logger.setLevel(logging.INFO)

_KEY_B64 = "QVEuQWI4Uk42TFhGOVhzQUxENGo5RDhzcmhPTlNId2JhaDVDa3gzdXo4SGlFRHI3dHVCYWc="

def get_taxes_data_file(month_str: str, user_email: str = None) -> Path:
    """Ruta al archivo JSON de retenciones y VEPs para el usuario y mes."""
    data_dir = get_user_data_dir(user_email)
    month_clean = month_str.replace("-", "_")
    return data_dir / f"retenciones_{month_clean}.json"

def load_monthly_taxes(month_str: str, user_email: str = None) -> list[dict]:
    """Carga los certificados de retención y VEPs procesados para un mes dado."""
    if user_email:
        try:
            redistribute_user_documents(user_email)
        except Exception as err:
            logger.warning(f"Error verificando distribución de retenciones: {err}")
    file_path = get_taxes_data_file(month_str, user_email)
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error leyendo {file_path}: {e}")
        return []

def save_monthly_taxes(month_str: str, tax_list: list[dict], user_email: str = None):
    """Guarda la lista de retenciones y VEPs del mes."""
    file_path = get_taxes_data_file(month_str, user_email)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(tax_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando {file_path}: {e}")

def add_tax_doc_to_month(month_str: str, tax_data: dict, user_email: str = None) -> dict:
    """Agrega o actualiza un certificado de retención o VEP para el mes."""
    tax_docs = load_monthly_taxes(month_str, user_email)
    doc_id = tax_data.get("id") or f"tax_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    tax_data["id"] = doc_id
    
    # Comprobar si ya existe por ID o número de certificado / VEP
    existing_idx = -1
    for idx, item in enumerate(tax_docs):
        if item.get("id") == doc_id:
            existing_idx = idx
            break
        # Si es certificado de retención
        if (tax_data.get("tipo_documento") == "certificado_retencion" and 
            tax_data.get("numero_certificado") and
            item.get("numero_certificado") == tax_data.get("numero_certificado") and
            item.get("agente_retencion_cuit") == tax_data.get("agente_retencion_cuit")):
            existing_idx = idx
            break
        # Si es pago de VEP
        if (tax_data.get("tipo_documento") == "pago_vep" and
            tax_data.get("numero_vep") and
            item.get("numero_vep") == tax_data.get("numero_vep")):
            existing_idx = idx
            break

    if existing_idx >= 0:
        tax_docs[existing_idx] = tax_data
    else:
        tax_docs.append(tax_data)

    save_monthly_taxes(month_str, tax_docs, user_email)
    return tax_data

def delete_tax_doc_from_month(month_str: str, doc_id: str, user_email: str = None) -> bool:
    """Elimina un documento fiscal por ID."""
    tax_docs = load_monthly_taxes(month_str, user_email)
    initial_len = len(tax_docs)
    tax_docs = [item for item in tax_docs if item.get("id") != doc_id]
    if len(tax_docs) < initial_len:
        save_monthly_taxes(month_str, tax_docs, user_email)
        return True
    return False

def parse_tax_or_vep_pdf(pdf_bytes: bytes, filename_hint: str = "") -> dict:
    """
    Extrae el texto del PDF con PyMuPDF y utiliza Gemini IA para interpretar y estructurar:
    - Certificados de Retención (Ganancias RG 830, IVA, Ingresos Brutos / SIRCUPA, Seguridad Social)
    - Comprobantes de Pago de VEP (AFIP/ARCA, Convenio Multilateral, Autónomos, Monotributo)
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        full_text = "\n".join([page.get_text() for page in doc])
    except Exception as e:
        logger.error(f"Error abriendo PDF tributario con PyMuPDF: {e}")
        return {"error": f"No se pudo leer el archivo PDF: {str(e)}"}

    if not full_text.strip():
        return {"error": "El documento no contiene texto legible (puede ser una imagen sin capa de texto)."}

    # Clave de Gemini API
    fallback_key = base64.b64decode(_KEY_B64).decode("utf-8")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or fallback_key

    prompt = f"""Sos un contador público y especialista tributario experto en impuestos de Argentina (AFIP / ARCA y provinciales).
Analiza con máxima precisión técnica el texto extraído de este comprobante tributario (archivo: '{filename_hint}').

Determina si es:
A) Un 'certificado_retencion' (Constancia o certificado oficial de retención sufrida emitido por un cliente, banco o agente de recaudación).
B) Un 'pago_vep' (Comprobante de pago de Volante Electrónico de Pago de AFIP/ARCA o Rentas Provincial).

Responde ÚNICAMENTE con un JSON válido con una de estas dos estructuras exactas:

SI ES 'certificado_retencion':
{{
  "tipo_documento": "certificado_retencion",
  "agente_retencion_nombre": "Razón Social o Nombre del Agente de Retención (cliente o entidad que retiene)",
  "agente_retencion_cuit": "CUIT del agente con guiones (ej: 30-12345678-9)",
  "sujeto_retenido_nombre": "Nombre o razón social del contribuyente beneficiario",
  "sujeto_retenido_cuit": "CUIT del contribuyente retenido",
  "impuesto_retenido": "Ganancias | IVA | Ingresos Brutos | SIRCUPA | Seguridad Social | Sellos",
  "regimen": "Código o nombre del régimen (ej: 'RG 830 - Locaciones y Servicios', 'General IIBB', 'Régimen Simplificado')",
  "jurisdiccion": "Nacional (AFIP/ARCA) | Buenos Aires (ARBA) | CABA (AGIP) | Córdoba | Santa Fe | etc.",
  "numero_certificado": "Número oficial de certificado de retención",
  "fecha_emision": "DD/MM/YYYY",
  "periodo": "YYYY_MM (estimado por la fecha de emisión)",
  "base_imponible": 0.00,
  "alicuota_porcentaje": 0.00,
  "importe_retenido": 0.00,
  "comprobante_asociado": "Factura o recibo sobre el que se practicó la retención (si figura)",
  "observaciones": "Breve resumen (ej: 'Retención Ganancias RG 830 practicada por Empresa SA')"
}}

SI ES 'pago_vep':
{{
  "tipo_documento": "pago_vep",
  "organismo": "AFIP / ARCA | ARBA | AGIP | Convenio Multilateral (Comarb) | Rentas",
  "numero_vep": "Número de VEP",
  "cuit_contribuyente": "CUIT del contribuyente pagador",
  "contribuyente_nombre": "Nombre o razón social del contribuyente",
  "concepto": "Concepto principal (ej: 'Autónomos', 'IVA Declaración Jurada', 'Anticipo Ganancias', 'Convenio Multilateral 901', 'Monotributo')",
  "subconcepto": "Subconcepto o código si figura",
  "periodo_fiscal": "MM/YYYY",
  "fecha_pago": "DD/MM/YYYY",
  "monto_pagado": 0.00,
  "entidad_pago": "Plataforma o banco recaudador (ej: PagoMisCuentas, Interbanking, Red Link, Supervielle, BNA)",
  "numero_transaccion": "Número de control, transacción o terminal bancaria si figura",
  "observaciones": "Breve resumen (ej: 'Pago de VEP Autónomos período 10/2026')"
}}

REGLAS DE ORO:
1. 'importe_retenido' o 'monto_pagado' son números flotantes no negativos (ej: 45210.50).
2. 'alicuota_porcentaje' debe ser el porcentaje numérico (ej: 2.0, 3.5, 21.0).
3. 'agente_retencion_cuit' debe extraerse con extrema precisión porque el contador lo necesita para el SIRE / SICORE / aplicativo de DDJJ.
4. Devuelve EXCLUSIVAMENTE el JSON.

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
            logger.warning(f"Error intentando modelo {model_name} en tax_processor: {ex}")

    return {"error": "No se pudo interpretar el comprobante impositivo con IA. Verifique que sea un PDF válido y reintente."}
