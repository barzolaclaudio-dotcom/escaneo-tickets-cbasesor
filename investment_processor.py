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

logger = logging.getLogger("investment_processor")
logger.setLevel(logging.INFO)

_KEY_B64 = "QVEuQWI4Uk42TFhGOVhzQUxENGo5RDhzcmhPTlNId2JhaDVDa3gzdXo4SGlFRHI3dHVCYWc="

def get_investments_data_file(month_str: str, user_email: str = None) -> Path:
    """Ruta al archivo JSON de inversiones para el usuario y mes."""
    data_dir = get_user_data_dir(user_email)
    month_clean = month_str.replace("-", "_")
    return data_dir / f"inversiones_{month_clean}.json"

def load_monthly_investments(month_str: str, user_email: str = None) -> list[dict]:
    """Carga las inversiones y boletos bursátiles procesados para un mes dado."""
    file_path = get_investments_data_file(month_str, user_email)
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error leyendo {file_path}: {e}")
        return []

def save_monthly_investments(month_str: str, inv_list: list[dict], user_email: str = None):
    """Guarda la lista de inversiones del mes."""
    file_path = get_investments_data_file(month_str, user_email)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(inv_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando {file_path}: {e}")

def add_investment_to_month(month_str: str, inv_data: dict, user_email: str = None) -> dict:
    """Agrega o actualiza una operación de inversión para el mes."""
    investments = load_monthly_investments(month_str, user_email)
    inv_id = inv_data.get("id") or f"inv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    inv_data["id"] = inv_id
    
    # Comprobar si ya existe por ID o número de boleto / entidad / fecha
    existing_idx = -1
    for idx, item in enumerate(investments):
        if item.get("id") == inv_id:
            existing_idx = idx
            break
        if (inv_data.get("numero_boleto") and 
            item.get("numero_boleto") == inv_data.get("numero_boleto") and
            item.get("entidad") == inv_data.get("entidad")):
            existing_idx = idx
            break

    if existing_idx >= 0:
        investments[existing_idx] = inv_data
    else:
        investments.append(inv_data)

    save_monthly_investments(month_str, investments, user_email)
    return inv_data

def delete_investment_from_month(month_str: str, inv_id: str, user_email: str = None) -> bool:
    """Elimina una inversión por ID."""
    investments = load_monthly_investments(month_str, user_email)
    initial_len = len(investments)
    investments = [item for item in investments if item.get("id") != inv_id]
    if len(investments) < initial_len:
        save_monthly_investments(month_str, investments, user_email)
        return True
    return False

def parse_investment_pdf(pdf_bytes: bytes, filename_hint: str = "") -> dict:
    """
    Extrae el texto del PDF con PyMuPDF y utiliza Gemini IA para interpretar y estructurar:
    - Boletos de Caución Bursátil (Colocadora / Tomadora de Allaria, Balanz, Cocos, Bull Market, IOL, etc.)
    - Operaciones de Títulos Valores (Lecaps, Bonos, CEDEARs, Acciones, Obligaciones Negociables)
    - Estados de cuenta y rendimientos de ALyCs y Fintech (Digifin, Lemon Earn, etc.)
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        full_text = "\n".join([page.get_text() for page in doc])
    except Exception as e:
        logger.error(f"Error abriendo PDF de inversión con PyMuPDF: {e}")
        return {"error": f"No se pudo leer el archivo PDF: {str(e)}"}

    if not full_text.strip():
        return {"error": "El documento no contiene texto legible (puede ser una imagen sin capa de texto)."}

    # Clave de Gemini API
    fallback_key = base64.b64decode(_KEY_B64).decode("utf-8")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or fallback_key

    prompt = f"""Sos un operador financiero de mercado de capitales (ALyC) y contador tributario experto en Argentina.
Analiza con máxima precisión el texto de este boleto o comprobante de inversión bursátil (archivo: '{filename_hint}').

Responde ÚNICAMENTE con un objeto JSON válido con esta estructura exacta:

{{
  "entidad": "Nombre de la ALyC o Entidad (ej: Allaria Ledesma, Balanz, Cocos Capital, InvertirOnline, Bull Market Brokers, Digifin, Lemon, etc.)",
  "numero_boleto": "Número de boleto, liquidación u operación (o null si no figura)",
  "tipo_operacion": "caucion_colocadora | caucion_tomadora | compra_titulos | venta_titulos | rendimiento_cuenta",
  "especie": "Nombre del instrumento (ej: Caución Bursátil en Pesos, Lecap S31O4, AL30D, GD30, Apple AAPL, etc.)",
  "moneda": "ARS | USD",
  "fecha_concertacion": "DD/MM/YYYY",
  "fecha_vencimiento": "DD/MM/YYYY",
  "plazo_dias": 1,
  "tasa_nominal_anual": 0.00,
  "monto_operado": 0.00,
  "interes_bruto": 0.00,
  "aranceles_y_gastos": {{
    "arancel_alyc": 0.00,
    "derechos_mercado": 0.00,
    "iva_aranceles_21": 0.00,
    "otros_gastos": 0.00
  }},
  "monto_neto_liquidado": 0.00,
  "titular": "Nombre completo del comitente o titular de la cuenta",
  "cuenta_comitente": "Número de cuenta comitente si figura (o null)",
  "observaciones": "Breve resumen (ej: 'Colocación de Caución Bursátil a 3 días al 38.5% TNA en Allaria')"
}}

REGLAS DE ORO:
1. 'tasa_nominal_anual' (TNA): porcentaje numérico flotante (ej: si la tasa es 38.5% o 0.385, colocar 38.50). Si no aplica, poner 0.0.
2. Si es una caución colocadora, el monto neto liquidado suele ser: monto_operado + interes_bruto - aranceles - derechos_mercado - iva_aranceles.
3. El IVA de los aranceles bursátiles es computable fiscalmente para el contador; extráelo con precisión si figura.
4. 'plazo_dias' debe ser un número entero (ej: 1, 3, 7, 30).
5. Todos los montos deben ser números flotantes no negativos.
6. Devuelve EXCLUSIVAMENTE el JSON.

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
            logger.warning(f"Error intentando modelo {model_name} en investment_processor: {ex}")

    return {"error": "No se pudo interpretar el comprobante de inversión con IA. Verifique que sea un PDF legible y reintente."}
