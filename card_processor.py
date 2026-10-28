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

logger = logging.getLogger("card_processor")
logger.setLevel(logging.INFO)

_KEY_B64 = "QVEuQWI4Uk42TFhGOVhzQUxENGo5RDhzcmhPTlNId2JhaDVDa3gzdXo4SGlFRHI3dHVCYWc="

def get_cards_data_file(month_str: str, user_email: str = None) -> Path:
    """Ruta al archivo JSON de tarjetas para el usuario y mes."""
    data_dir = get_user_data_dir(user_email)
    month_clean = month_str.replace("-", "_")
    return data_dir / f"tarjetas_{month_clean}.json"

def load_monthly_cards(month_str: str, user_email: str = None) -> list[dict]:
    """Carga los resúmenes de tarjetas parseados para un mes dado."""
    if user_email:
        try:
            redistribute_user_documents(user_email)
        except Exception as err:
            logger.warning(f"Error verificando distribución de tarjetas: {err}")
    file_path = get_cards_data_file(month_str, user_email)
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error leyendo {file_path}: {e}")
        return []

def save_monthly_cards(month_str: str, cards_list: list[dict], user_email: str = None):
    """Guarda la lista de resúmenes de tarjetas del mes."""
    file_path = get_cards_data_file(month_str, user_email)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(cards_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando {file_path}: {e}")

def add_card_to_month(month_str: str, card_data: dict, user_email: str = None):
    """Agrega o reemplaza un resumen de tarjeta para el mes."""
    cards = load_monthly_cards(month_str, user_email)
    card_id = card_data.get("id") or f"card_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    card_data["id"] = card_id
    
    # Si ya existía con el mismo ID o misma entidad/marca/ultimos4, se actualiza
    existing_idx = -1
    for idx, c in enumerate(cards):
        if c.get("id") == card_id:
            existing_idx = idx
            break
        if (c.get("entidad") == card_data.get("entidad") and 
            c.get("marca") == card_data.get("marca") and 
            c.get("numero_tarjeta_ultimos4") == card_data.get("numero_tarjeta_ultimos4") and
            c.get("fecha_cierre") == card_data.get("fecha_cierre")):
            existing_idx = idx
            break
            
    if existing_idx >= 0:
        cards[existing_idx] = card_data
    else:
        cards.append(card_data)
        
    save_monthly_cards(month_str, cards, user_email)
    return card_data

def delete_card_from_month(month_str: str, card_id: str, user_email: str = None) -> bool:
    """Elimina un resumen de tarjeta por ID."""
    cards = load_monthly_cards(month_str, user_email)
    initial_len = len(cards)
    cards = [c for c in cards if c.get("id") != card_id]
    if len(cards) < initial_len:
        save_monthly_cards(month_str, cards, user_email)
        return True
    return False

def parse_credit_card_pdf(pdf_bytes: bytes, filename_hint: str = "") -> dict:
    """
    Extrae el texto del PDF con PyMuPDF y utiliza Gemini para interpretar y clasificar:
    - Banco / Entidad
    - Marca y Tipo (Visa, Master, Cabal, etc.)
    - Fechas de cierre y vencimiento
    - Saldos ($ y USD) y pago mínimo
    - Lista de compras/consumos con categoría y cuotas
    - Impuestos y percepciones
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        full_text = "\n".join([page.get_text() for page in doc])
    except Exception as e:
        logger.error(f"Error abriendo PDF con PyMuPDF: {e}")
        return {"error": f"No se pudo leer el archivo PDF: {str(e)}"}

    if not full_text.strip():
        return {"error": "El documento no contiene texto legible (puede ser un escaneo sin OCR)."}

    # Llamar a Gemini API
    fallback_key = base64.b64decode(_KEY_B64).decode("utf-8")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or fallback_key

    prompt = f"""Sos un contador y auditor financiero experto en resúmenes de tarjetas de crédito y bancarios de Argentina.
Analiza el siguiente texto extraído del resumen (archivo: '{filename_hint}') y responde ÚNICAMENTE con un objeto JSON válido con esta estructura exacta:

{{
  "entidad": "Nombre del Banco o Entidad emisora (ej: Banco Nación, Banco Credicoop, Banco Galicia, Lemon Cash, etc.)",
  "marca": "Visa | Mastercard | Cabal | American Express | Visa Prepaga",
  "tipo_tarjeta": "Gold | Internacional | Platinum | Black | Signature | Prepaga",
  "numero_tarjeta_ultimos4": "Últimos 4 dígitos de la tarjeta si figuran, o null",
  "titular": "Nombre completo del titular de la cuenta/tarjeta",
  "fecha_cierre": "DD/MM/YYYY",
  "fecha_vencimiento": "DD/MM/YYYY",
  "periodo": "YYYY_MM (estimado según la fecha de cierre)",
  "saldo_pesos": 0.00,
  "saldo_dolares": 0.00,
  "pago_minimo_pesos": 0.00,
  "consumos": [
    {{
      "fecha": "DD/MM/YYYY",
      "detalle": "Comercio o concepto (limpio y legible)",
      "cuota_actual": 1,
      "cuota_total": 6,
      "moneda": "ARS | USD",
      "monto": 0.00,
      "categoria": "Combustible | Peajes | Supermercado | Servicios y Software | Gastos de Oficina | Indumentaria | Restaurantes y Comidas | Transporte | Salud | Varios"
    }}
  ],
  "impuestos_y_cargos": {{
    "sellos": 0.00,
    "intereses_financiacion": 0.00,
    "iva_intereses_21": 0.00,
    "percepcion_iibb": 0.00,
    "percepcion_afip_rg4815": 0.00,
    "otros_cargos": 0.00
  }},
  "pagos_efectuados": [
    {{
      "fecha": "DD/MM/YYYY",
      "monto": 0.00
    }}
  ]
}}

REGLAS DE ORO:
1. En 'consumos' incluye ÚNICAMENTE compras de bienes y servicios y cuotas del período. NO incluyas los pagos de saldo, ni los intereses, ni los impuestos dentro de 'consumos' (esos van en sus campos específicos).
2. Los montos deben ser números flotantes positivos.
3. Si un consumo es una cuota (ej: '02/06' o 'C.02/06'), asigna cuota_actual=2 y cuota_total=6. Si es en 1 pago, cuota_actual=null y cuota_total=null.
4. Clasifica cada comercio en la categoría más precisa posible.
5. Responde estrictamente con JSON.

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
            resp = requests.post(url, headers=headers, json=payload, timeout=35)
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
            logger.warning(f"Error intentando con modelo {model_name}: {ex}")

    return {"error": "No se pudo procesar el resumen con IA. Por favor, reintenta."}
