import io
import re
import json
import base64
import logging
from pathlib import Path
from datetime import datetime
import requests

from ticket_ocr import (
    sanitize_email, 
    get_user_data_dir, 
    get_monthly_summary, 
    load_monthly_expenses,
    redistribute_user_documents
)
from card_processor import load_monthly_cards
from bank_processor import load_monthly_bank_data
from investment_processor import load_monthly_investments
from tax_processor import load_monthly_taxes

logger = logging.getLogger("advisor_processor")
logger.setLevel(logging.INFO)

_KEY_B64 = "QVEuQWI4Uk42TFhGOVhzQUxENGo5RDhzcmhPTlNId2JhaDVDa3gzdXo4SGlFRHI3dHVCYWc="

def get_gemini_api_key() -> str:
    return base64.b64decode(_KEY_B64).decode("utf-8")

def get_advisor_cache_file(month_str: str, user_email: str = None) -> Path:
    """Ruta al archivo JSON de auditoría/diagnóstico financiero del usuario y mes."""
    data_dir = get_user_data_dir(user_email)
    month_clean = month_str.replace("-", "_")
    return data_dir / f"auditoria_{month_clean}.json"

def collect_month_financial_ecosystem(month_str: str, user_email: str = None) -> dict:
    """
    Recopila y consolida el 100% de la información financiera y contable del mes:
    - Tickets y Comprobantes de Compras (Facturas A, B, C, etc.)
    - Resúmenes de Tarjetas de Crédito y Débito
    - Documentos Bancarios y Cuotas de Préstamos
    - Inversiones Bursátiles y Cauciones
    - Certificados de Retención y VEPs Impositivos
    - Proyección de cuotas futuras detectadas
    """
    month_clean = month_str.replace("-", "_")
    
    # 1. Comprobantes de Gastos / Tickets
    tickets_summary = get_monthly_summary(month_clean, user_email=user_email)
    tickets = tickets_summary.get("tickets", [])
    
    # 2. Tarjetas de Crédito
    cards = load_monthly_cards(month_clean, user_email=user_email)
    
    # 3. Bancos y Préstamos
    bank_docs = load_monthly_bank_data(month_clean, user_email=user_email)
    loans = [d for d in bank_docs if d.get("tipo_documento") == "prestamo"]
    bank_accounts = [d for d in bank_docs if d.get("tipo_documento") == "extracto_bancario"]
    
    # 4. Inversiones y Cauciones
    investments = load_monthly_investments(month_clean, user_email=user_email)
    
    # 5. Retenciones y VEPs
    tax_docs = load_monthly_taxes(month_clean, user_email=user_email)
    retenciones = [t for t in tax_docs if t.get("tipo_documento") == "certificado_retencion"]
    veps = [t for t in tax_docs if t.get("tipo_documento") == "pago_vep"]
    
    # ---------------------------------------------------------
    # CÁLCULOS MATEMÁTICOS DETERMINÍSTICOS (KPIs EXACTOS)
    # ---------------------------------------------------------
    # Gastos en tickets
    spent_tickets = float(tickets_summary.get("total_spent", 0.0))
    subtotal_tickets = float(tickets_summary.get("total_subtotal", 0.0))
    iva_tickets = float(tickets_summary.get("total_iva", 0.0))
    percep_iibb_tickets = float(tickets_summary.get("total_percepcion_iibb", 0.0))
    percep_iva_tickets = float(tickets_summary.get("total_percepcion_iva", 0.0))

    # Tarjetas
    cards_saldo_pesos = sum(float(c.get("saldo_pesos") or 0.0) for c in cards)
    cards_saldo_usd = sum(float(c.get("saldo_dolares") or 0.0) for c in cards)
    cards_intereses_financiacion = sum(float(c.get("impuestos_y_cargos", {}).get("intereses_financiacion") or 0.0) for c in cards)
    cards_iva_intereses = sum(float(c.get("impuestos_y_cargos", {}).get("iva_intereses_21") or 0.0) for c in cards)
    cards_sellos = sum(float(c.get("impuestos_y_cargos", {}).get("sellos") or 0.0) for c in cards)
    cards_percep_iibb = sum(float(c.get("impuestos_y_cargos", {}).get("percepcion_iibb") or 0.0) for c in cards)
    cards_percep_afip = sum(float(c.get("impuestos_y_cargos", {}).get("percepcion_afip_rg4815") or 0.0) for c in cards)

    # Préstamos
    loans_total_cuotas = sum(float(p.get("total_cuota") or 0.0) for p in loans)
    loans_capital = sum(float(p.get("capital_cuota") or 0.0) for p in loans)
    loans_intereses = sum(float(p.get("interes_compensatorio") or 0.0) for p in loans)
    loans_iva_intereses = sum(float(p.get("iva_intereses_21") or 0.0) for p in loans)
    loans_saldo_deuda_remanente = sum(float(p.get("saldo_deuda") or 0.0) for p in loans)

    # Cuentas bancarias
    bank_comisiones = sum(float(b.get("comisiones_bancarias") or 0.0) for b in bank_accounts)
    bank_impuesto_ley25413 = sum(float(b.get("impuesto_ley_25413") or 0.0) for b in bank_accounts)
    bank_iva_comisiones = sum(float(b.get("iva_bancario_21") or 0.0) for b in bank_accounts)
    bank_sircreb = sum(float(b.get("sircreb_iibb") or 0.0) for b in bank_accounts)

    # Inversiones
    inv_monto_operado = sum(float(i.get("monto_operado") or 0.0) for i in investments)
    inv_interes_ganado = sum(float(i.get("interes_ganado") or 0.0) for i in investments)
    inv_aranceles = sum(float(i.get("aranceles") or 0.0) for i in investments)
    inv_iva_aranceles = sum(float(i.get("iva_aranceles") or 0.0) for i in investments)
    tnas = [float(i.get("tna")) for i in investments if i.get("tna")]
    inv_tna_promedio = (sum(tnas) / len(tnas)) if tnas else 0.0

    # Retenciones y VEPs
    retenciones_total_computable = sum(float(r.get("importe_retenido") or 0.0) for r in retenciones)
    veps_total_pagado = sum(float(v.get("monto_pagado") or 0.0) for v in veps)

    # Costos Financieros Ocultos Consolidados
    costos_financieros_ocultos = (
        cards_intereses_financiacion +
        loans_intereses +
        bank_comisiones +
        cards_sellos +
        bank_impuesto_ley25413
    )

    # Crédito Fiscal IVA Total Consolidado
    credito_fiscal_iva_total = (
        iva_tickets +
        cards_iva_intereses +
        loans_iva_intereses +
        bank_iva_comisiones +
        inv_iva_aranceles
    )

    # Total Percepciones y Retenciones a Favor (Deducibles de DDJJ)
    creditos_impositivos_favor = (
        percep_iibb_tickets +
        percep_iva_tickets +
        cards_percep_iibb +
        cards_percep_afip +
        bank_sircreb +
        retenciones_total_computable
    )

    # Total Salidas Estimadas del Mes en Pesos
    total_salidas_pesos = (
        spent_tickets +
        cards_saldo_pesos +
        loans_total_cuotas +
        bank_comisiones +
        veps_total_pagado
    )

    # ---------------------------------------------------------
    # DESGLOSE POR RUBROS / CATEGORÍAS
    # ---------------------------------------------------------
    rubros_dict = {
        "Combustible": 0.0,
        "Supermercado & Alimentos": 0.0,
        "Peajes": 0.0,
        "Servicios & Software": 0.0,
        "Gastos Bancarios & Financieros": costos_financieros_ocultos,
        "Impuestos & VEPs": veps_total_pagado,
        "Indumentaria": 0.0,
        "Otros Gastos": 0.0
    }

    # Sumar consumos de tarjetas clasificados
    for c in cards:
        for cons in c.get("consumos", []):
            cat = cons.get("categoria", "Varios")
            m = float(cons.get("monto") or 0.0)
            if "Combustible" in cat:
                rubros_dict["Combustible"] += m
            elif "Supermercado" in cat or "Alimentos" in cat:
                rubros_dict["Supermercado & Alimentos"] += m
            elif "Peaje" in cat:
                rubros_dict["Peajes"] += m
            elif "Software" in cat or "Servicio" in cat:
                rubros_dict["Servicios & Software"] += m
            elif "Indumentaria" in cat:
                rubros_dict["Indumentaria"] += m
            else:
                rubros_dict["Otros Gastos"] += m

    # Sumar tickets clasificados por comercio
    for t in tickets:
        vendor = (t.get("vendor") or "").lower()
        tot = float(t.get("total") or 0.0)
        if any(w in vendor for w in ["ypf", "shell", "axion", "opessa", "combust", "estacion"]):
            rubros_dict["Combustible"] += tot
        elif any(w in vendor for w in ["coto", "carrefour", "dia", "jumbo", "disco", "chango", "super"]):
            rubros_dict["Supermercado & Alimentos"] += tot
        elif any(w in vendor for w in ["autopista", "aubasa", "ausol", "peaje", "au oeste"]):
            rubros_dict["Peajes"] += tot
        else:
            rubros_dict["Otros Gastos"] += tot

    rubros_list = [
        {"rubro": k, "monto": round(v, 2), "porcentaje": round((v / total_salidas_pesos * 100), 1) if total_salidas_pesos > 0 else 0.0}
        for k, v in rubros_dict.items() if v > 0
    ]
    rubros_list.sort(key=lambda x: x["monto"], reverse=True)

    # ---------------------------------------------------------
    # PLANIFICACIÓN DE CUOTAS FUTURAS (Tarjetas y Préstamos)
    # ---------------------------------------------------------
    cuotas_futuras = {}
    try:
        # 1. Cuotas de tarjetas activas
        for c in cards:
            for cons in c.get("consumos", []):
                c_act = cons.get("cuota_actual")
                c_tot = cons.get("cuota_total")
                monto_c = float(cons.get("monto") or 0.0)
                if c_act and c_tot and c_act < c_tot and monto_c > 0:
                    cuotas_restantes = c_tot - c_act
                    # Proyectar para los próximos meses
                    m_year, m_mes = map(int, month_clean.split("_"))
                    for offset in range(1, min(cuotas_restantes + 1, 12)):
                        f_mes = m_mes + offset
                        f_year = m_year
                        while f_mes > 12:
                            f_mes -= 12
                            f_year += 1
                        f_key = f"{f_year}_{f_mes:02d}"
                        if f_key not in cuotas_futuras:
                            cuotas_futuras[f_key] = {"total": 0.0, "items": []}
                        cuotas_futuras[f_key]["total"] += monto_c
                        cuotas_futuras[f_key]["items"].append({
                            "detalle": cons.get("detalle", "Consumo"),
                            "cuota": f"{c_act + offset}/{c_tot}",
                            "monto": monto_c,
                            "origen": f"{c.get('marca', 'Tarjeta')} ({c.get('entidad', '')})"
                        })

        # 2. Cuotas de préstamos activos
        for p in loans:
            c_act = p.get("cuota_actual")
            c_tot = p.get("cuota_total")
            monto_cuota = float(p.get("total_cuota") or 0.0)
            if c_act and c_tot and c_act < c_tot and monto_cuota > 0:
                cuotas_restantes = c_tot - c_act
                m_year, m_mes = map(int, month_clean.split("_"))
                for offset in range(1, min(cuotas_restantes + 1, 12)):
                    f_mes = m_mes + offset
                    f_year = m_year
                    while f_mes > 12:
                        f_mes -= 12
                        f_year += 1
                    f_key = f"{f_year}_{f_mes:02d}"
                    if f_key not in cuotas_futuras:
                        cuotas_futuras[f_key] = {"total": 0.0, "items": []}
                    cuotas_futuras[f_key]["total"] += monto_cuota
                    cuotas_futuras[f_key]["items"].append({
                        "detalle": f"Préstamo {p.get('entidad', '')} (N° {p.get('numero_prestamo', '')})",
                        "cuota": f"{c_act + offset}/{c_tot}",
                        "monto": monto_cuota,
                        "origen": "Préstamo Bancario"
                    })
    except Exception as e:
        logger.error(f"Error calculando cuotas futuras: {e}")

    # Ordenar cuotas futuras cronológicamente
    cuotas_futuras_ordenadas = []
    for k in sorted(cuotas_futuras.keys()):
        cuotas_futuras_ordenadas.append({
            "periodo": k,
            "periodo_label": k.replace("_", "/"),
            "total": round(cuotas_futuras[k]["total"], 2),
            "cantidad_cuotas": len(cuotas_futuras[k]["items"]),
            "items": cuotas_futuras[k]["items"]
        })

    # Total de cuotas comprometidas para el mes siguiente (+1)
    cuotas_proximo_mes = cuotas_futuras_ordenadas[0]["total"] if cuotas_futuras_ordenadas else 0.0

    return {
        "month": month_clean,
        "kpis": {
            "total_salidas_pesos": round(total_salidas_pesos, 2),
            "total_salidas_usd": round(cards_saldo_usd, 2),
            "costos_financieros_ocultos": round(costos_financieros_ocultos, 2),
            "credito_fiscal_iva_total": round(credito_fiscal_iva_total, 2),
            "creditos_impositivos_favor": round(creditos_impositivos_favor, 2),
            "cuotas_proximo_mes": round(cuotas_proximo_mes, 2),
            "gastos_tickets": round(spent_tickets, 2),
            "tickets_count": len(tickets),
            "tarjetas_pesos": round(cards_saldo_pesos, 2),
            "tarjetas_count": len(cards),
            "prestamos_cuotas": round(loans_total_cuotas, 2),
            "prestamos_deuda_remanente": round(loans_saldo_deuda_remanente, 2),
            "comisiones_bancarias": round(bank_comisiones, 2),
            "impuestos_bancarios": round(bank_impuesto_ley25413, 2),
            "inversiones_operadas": round(inv_monto_operado, 2),
            "inversiones_rendimiento": round(inv_interes_ganado, 2),
            "inversiones_tna_promedio": round(inv_tna_promedio, 2),
            "veps_pagados": round(veps_total_pagado, 2),
            "retenciones_computables": round(retenciones_total_computable, 2)
        },
        "desglose_costos_ocultos": {
            "intereses_tarjetas": round(cards_intereses_financiacion, 2),
            "intereses_prestamos": round(loans_intereses, 2),
            "comisiones_bancarias": round(bank_comisiones, 2),
            "sellos_tarjetas": round(cards_sellos, 2),
            "impuesto_ley25413": round(bank_impuesto_ley25413, 2)
        },
        "rubros": rubros_list,
        "cuotas_futuras": cuotas_futuras_ordenadas,
        "documentos_resumen": {
            "tickets": len(tickets),
            "tarjetas": len(cards),
            "prestamos": len(loans),
            "cuentas_bancarias": len(bank_accounts),
            "inversiones": len(investments),
            "retenciones": len(retenciones),
            "veps": len(veps)
        }
    }


def generate_financial_audit(month_str: str, user_email: str = None, force_refresh: bool = False) -> dict:
    """
    Genera el Diagnóstico y Auditoría Financiera Integral con IA (CB Asesor IA).
    Si ya existe en caché y no se solicita recálculo forzado, lo devuelve inmediatamente.
    """
    month_clean = month_str.replace("-", "_")
    cache_file = get_advisor_cache_file(month_clean, user_email)
    
    if not force_refresh and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
                return cached
        except Exception as e:
            logger.warning(f"Error leyendo auditoría en caché: {e}")

    # 1. Obtener ecosistema financiero completo y KPIs determinísticos
    ecosystem = collect_month_financial_ecosystem(month_str, user_email)
    kpis = ecosystem["kpis"]
    rubros = ecosystem["rubros"]
    cuotas_futuras = ecosystem["cuotas_futuras"]
    costos_ocultos = ecosystem["desglose_costos_ocultos"]
    
    # 2. Formular prompt especializado para Gemini
    month_label = month_str.replace("_", "/")
    
    prompt = f"""Eres CB Asesor Financiero & Tributario IA, el auditor sénior de finanzas corporativas, pymes y planificación fiscal argentina de CB Asesor.
Analiza la siguiente información financiera y contable real y consolidada correspondiente al período {month_label}:

=== RADIOGRAFÍA FINANCIERA DEL MES ({month_label}) ===
- Total Salidas Estimadas en Pesos: $ {kpis['total_salidas_pesos']:,.2f}
- Consumos / Saldo en Dólares (USD): USD {kpis['total_salidas_usd']:,.2f}
- Total Gastado en Comprobantes/Facturas: $ {kpis['gastos_tickets']:,.2f} ({kpis['tickets_count']} comprobantes)
- Saldo Tarjetas de Crédito: $ {kpis['tarjetas_pesos']:,.2f} ({kpis['tarjetas_count']} resúmenes)
- Cuotas de Préstamos Pagadas: $ {kpis['prestamos_cuotas']:,.2f} (Deuda capital remanente: $ {kpis['prestamos_deuda_remanente']:,.2f})
- Comisiones Bancarias de Mantenimiento: $ {kpis['comisiones_bancarias']:,.2f}
- Impuesto a los Débitos y Créditos (Ley 25.413): $ {kpis['impuestos_bancarios']:,.2f}
- Inversiones y Cauciones Bursátiles: $ {kpis['inversiones_operadas']:,.2f} colocados (Interés ganado: $ {kpis['inversiones_rendimiento']:,.2f}, TNA Promedio: {kpis['inversiones_tna_promedio']}%)
- VEPs Impositivos Abonados: $ {kpis['veps_pagados']:,.2f}

=== COSTOS FINANCIEROS OCULTOS (INEFICIENCIAS) ===
- Intereses de Financiación de Tarjetas: $ {costos_ocultos['intereses_tarjetas']:,.2f}
- Intereses de Préstamos Bancarios: $ {costos_ocultos['intereses_prestamos']:,.2f}
- Comisiones de Mantenimiento de Cuentas: $ {costos_ocultos['comisiones_bancarias']:,.2f}
- Impuesto de Sellos en Tarjetas: $ {costos_ocultos['sellos_tarjetas']:,.2f}
- TOTAL COSTOS OCULTOS / FUGAS FINANCIERAS: $ {kpis['costos_financieros_ocultos']:,.2f}

=== CRÉDITOS FISCALES Y RETENCIONES (A FAVOR PARA DEDUCIR) ===
- Crédito Fiscal de IVA Total Acumulado: $ {kpis['credito_fiscal_iva_total']:,.2f} (computable en Libro IVA Compras)
- Retenciones y Percepciones Impositivas a Favor: $ {kpis['creditos_impositivos_favor']:,.2f} (Ganancias, IIBB, SIRCREB, AFIP)

=== PLANIFICACIÓN DE CUOTAS FUTURAS COMPROMETIDAS ===
- Total a pagar en cuotas el próximo mes (+1): $ {kpis['cuotas_proximo_mes']:,.2f}
- Cronograma de cuotas futuras detectadas: {json.dumps(cuotas_futuras[:4], ensure_ascii=False)}

=== CONCENTRACIÓN POR RUBROS ===
{json.dumps(rubros, ensure_ascii=False)}

=== INSTRUCCIONES DE AUDITORÍA ===
Genera una auditoría ejecutiva, rigurosa, profesional y 100% orientada a la acción.
Debes responder EXCLUSIVAMENTE con un objeto JSON válido con la siguiente estructura:
{{
  "semaforo_salud": "Optimo" | "Atencion" | "Alerta",
  "semaforo_motivo": "Breve justificación de 1 o 2 oraciones del estado del semáforo",
  "resumen_ejecutivo": "Diagnóstico integral del mes, analizando el volumen total de salidas, nivel de endeudamiento y solvencia general.",
  "analisis_costos_ocultos": "Evaluación crítica y detallada sobre los intereses pagados (especialmente si hay crédito rotativo en tarjetas), comisiones y sellos bancarios, explicando el impacto en el flujo y si conviene precancelar deuda.",
  "planificacion_cuotas_futuras": "Evaluación del horizonte de compromisos futuros. Diagnostica si las cuotas futuras comprometen el flujo de fondos disponible.",
  "optimizacion_fiscal": "Consejos estratégicos concretos para aprovechar el IVA crédito fiscal acumulado ($ {kpis['credito_fiscal_iva_total']:,.2f}) y las retenciones en las DDJJ mensuales/anuales del contador.",
  "consejos_ahorro": [
    {{
      "titulo": "Título de la recomendación",
      "descripcion": "Acción concreta y práctica a implementar",
      "impacto_estimado": "Ahorro estimado en pesos o porcentaje (ej: '$ 70.000 / mes' o '15% de reducción')",
      "prioridad": "Alta" | "Media" | "Baja"
    }}
  ],
  "recomendaciones_inversiones": "Recomendación táctica para el manejo de excedentes transitorios o liquidez (ej: cauciones bursátiles a 1 o 7 días, fondos money market T+0) para compensar los costos bancarios y defenderse de la inflación."
}}
"""

    api_key = get_gemini_api_key()
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

    ai_insights = None
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
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
                    ai_insights = json.loads(raw_text)
                    break
            else:
                logger.warning(f"Advisor Gemini API ({model_name}) HTTP {resp.status_code}: {resp.text[:150]}")
        except Exception as ex:
            logger.warning(f"Error intentando modelo {model_name} para auditoría: {ex}")

    # Fallback si falla la llamada al LLM
    if not ai_insights:
        semaforo = "Atencion" if kpis["costos_financieros_ocultos"] > 50000 else "Optimo"
        ai_insights = {
            "semaforo_salud": semaforo,
            "semaforo_motivo": f"Costos financieros ocultos en $ {kpis['costos_financieros_ocultos']:,.2f} y cuotas proyectadas en $ {kpis['cuotas_proximo_mes']:,.2f}.",
            "resumen_ejecutivo": f"El período {month_label} presenta un total de salidas operativas de $ {kpis['total_salidas_pesos']:,.2f} y USD {kpis['total_salidas_usd']:,.2f}, con {kpis['tickets_count']} comprobantes procesados.",
            "analisis_costos_ocultos": f"Se registraron costos financieros de $ {kpis['costos_financieros_ocultos']:,.2f} entre intereses bancarios, tarjetas y comisiones.",
            "planificacion_cuotas_futuras": f"Se proyectan $ {kpis['cuotas_proximo_mes']:,.2f} en cuotas comprometidas para el próximo mes.",
            "optimizacion_fiscal": f"Tienes a favor $ {kpis['credito_fiscal_iva_total']:,.2f} de Crédito Fiscal de IVA y $ {kpis['creditos_impositivos_favor']:,.2f} en retenciones computables.",
            "consejos_ahorro": [
                {
                    "titulo": "Revisar intereses de tarjetas",
                    "descripcion": "Evitar el pago mínimo de tarjetas para no devengar tasas de interés resarcitorias elevadas.",
                    "impacto_estimado": f"Ahorro de hasta $ {costos_ocultos['intereses_tarjetas']:,.2f}",
                    "prioridad": "Alta"
                },
                {
                    "titulo": "Deducción de Crédito Fiscal",
                    "descripcion": "Enviar el reporte Excel al contador para computar el IVA de tickets, gastos bancarios y tarjetas.",
                    "impacto_estimado": f"Recupero de $ {kpis['credito_fiscal_iva_total']:,.2f}",
                    "prioridad": "Alta"
                }
            ],
            "recomendaciones_inversiones": "Colocar los excedentes transitorios en cauciones bursátiles en pesos para generar rendimiento diario sin inmovilizar capital."
        }

    # Consolidar objeto completo
    full_audit = {
        "success": True,
        "month": month_clean,
        "month_label": month_label,
        "fecha_generacion": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "kpis": kpis,
        "desglose_costos_ocultos": costos_ocultos,
        "rubros": rubros,
        "cuotas_futuras": cuotas_futuras,
        "documentos_resumen": ecosystem["documentos_resumen"],
        "ai_insights": ai_insights
    }

    # Guardar en caché
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(full_audit, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando auditoría en caché: {e}")

    return full_audit


def chat_financial_advisor(month_str: str, user_email: str, user_message: str, history: list = None) -> dict:
    """
    Chat consultivo en vivo con CB Asesor IA sobre el ecosistema financiero del mes.
    Responde en lenguaje natural fundamentado en datos contables y bancarios reales.
    """
    month_clean = month_str.replace("-", "_")
    month_label = month_clean.replace("_", "/")
    
    # 1. Obtener contexto financiero del mes
    ecosystem = collect_month_financial_ecosystem(month_clean, user_email)
    kpis = ecosystem["kpis"]
    costos_ocultos = ecosystem["desglose_costos_ocultos"]
    rubros = ecosystem["rubros"]
    cuotas_futuras = ecosystem["cuotas_futuras"]

    # 2. Resumen condensado de comprobantes para contexto preciso
    tickets_summary = get_monthly_summary(month_clean, user_email=user_email)
    top_vendors = tickets_summary.get("vendors_summary", [])[:8]
    
    cards = load_monthly_cards(month_clean, user_email=user_email)
    cards_info = []
    for c in cards:
        cards_info.append(f"- {c.get('marca', 'Tarjeta')} {c.get('entidad', '')}: Saldo $ {c.get('saldo_pesos', 0):,.2f}, USD {c.get('saldo_dolares', 0):,.2f}, Intereses: $ {c.get('impuestos_y_cargos', {}).get('intereses_financiacion', 0):,.2f}")
    
    loans = [d for d in load_monthly_bank_data(month_clean, user_email=user_email) if d.get("tipo_documento") == "prestamo"]
    loans_info = []
    for p in loans:
        loans_info.append(f"- Préstamo {p.get('entidad', '')} N° {p.get('numero_prestamo', '')}: Cuota {p.get('cuota_actual')}/{p.get('cuota_total')}, Total Cuota: $ {p.get('total_cuota', 0):,.2f}, Deuda Remanente: $ {p.get('saldo_deuda', 0):,.2f}")

    investments = load_monthly_investments(month_clean, user_email=user_email)
    inv_info = [f"- {i.get('tipo_operacion', 'Inversión')} en {i.get('alyc', '')}: $ {i.get('monto_operado', 0):,.2f} a TNA {i.get('tna', 0)}% (Ganancia: $ {i.get('interes_ganado', 0):,.2f})" for i in investments]

    system_context = f"""Eres CB Asesor Financiero IA, un consultor y asesor financiero y tributario personal sénior en Argentina.
Estás conversando con el titular de la cuenta sobre sus finanzas del período {month_label}.

=== DATOS FINANCIEROS Y CONTABLES REALES DEL PERÍODO {month_label} ===
- Total Salidas Pesos: $ {kpis['total_salidas_pesos']:,.2f} | Total Dólares: USD {kpis['total_salidas_usd']:,.2f}
- Gastos en Comprobantes/Tickets: $ {kpis['gastos_tickets']:,.2f} ({kpis['tickets_count']} comprobantes)
  Mayores comercios de compras: {json.dumps(top_vendors, ensure_ascii=False)}
- Resúmenes de Tarjetas ({kpis['tarjetas_count']}):
  {chr(10).join(cards_info) if cards_info else 'No hay resúmenes de tarjetas registrados en el mes.'}
- Préstamos Bancarios ({len(loans)}):
  {chr(10).join(loans_info) if loans_info else 'No hay cuotas de préstamos registradas en el mes.'}
- Comisiones Bancarias de Cuenta: $ {kpis['comisiones_bancarias']:,.2f} | Impuesto Ley 25.413: $ {kpis['impuestos_bancarios']:,.2f}
- Costos Financieros Ocultos Consolidados (intereses tarjetas + préstamos + comisiones + sellos): $ {kpis['costos_financieros_ocultos']:,.2f}
- Crédito Fiscal de IVA Acumulado: $ {kpis['credito_fiscal_iva_total']:,.2f}
- Retenciones y Percepciones a Favor: $ {kpis['creditos_impositivos_favor']:,.2f}
- Inversiones y Cauciones:
  {chr(10).join(inv_info) if inv_info else 'No hay inversiones bursátiles registradas en el mes.'}
- Cuotas Comprometidas para el Próximo Mes: $ {kpis['cuotas_proximo_mes']:,.2f}
- Próximos vencimientos de cuotas: {json.dumps(cuotas_futuras[:3], ensure_ascii=False)}
- Desglose por rubros: {json.dumps(rubros, ensure_ascii=False)}

=== INSTRUCCIONES DE RESPUESTA ===
1. Responde de forma cálida, profesional, directa y con números exactos basados en la información anterior.
2. Formatea montos en pesos con `$ X.XXX,XX`.
3. Ofrece consejos concretos sobre cómo optimizar gastos, evitar intereses, aprovechar el crédito fiscal de IVA para el contador o rentabilizar fondos con cauciones bursátiles.
4. Mantén tus respuestas concisas pero completas, usando viñetas o negritas para facilitar la lectura en el celular.
"""

    # Construir historial para Gemini
    messages = []
    if history and isinstance(history, list):
        for h in history[-6:]:  # últimos 6 turnos
            role = "user" if h.get("sender") == "user" else "model"
            text = h.get("text", "")
            if text:
                messages.append({"role": role, "parts": [{"text": text}]})

    # Mensaje actual
    messages.append({
        "role": "user",
        "parts": [{"text": f"[CONTEXTO DEL SISTEMA]:\n{system_context}\n\n[PREGUNTA DEL USUARIO]:\n{user_message}"}]
    })

    api_key = get_gemini_api_key()
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

    reply_text = None
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": messages,
            "generationConfig": {
                "temperature": 0.4
            }
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=35)
            if resp.status_code == 200:
                res_json = resp.json()
                candidates = res_json.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    reply_text = "".join([p.get("text", "") for p in parts if "text" in p]).strip()
                    if reply_text:
                        break
            else:
                logger.warning(f"Advisor Chat Gemini API ({model_name}) HTTP {resp.status_code}: {resp.text[:150]}")
        except Exception as ex:
            logger.warning(f"Error en chat con modelo {model_name}: {ex}")

    if not reply_text:
        reply_text = f"En {month_label}, tus salidas totales registradas ascienden a $ {kpis['total_salidas_pesos']:,.2f}, con costos financieros de $ {kpis['costos_financieros_ocultos']:,.2f} y un crédito fiscal de IVA acumulado de $ {kpis['credito_fiscal_iva_total']:,.2f} para tu contador. ¿En qué aspecto puntual te gustaría profundizar?"

    return {
        "success": True,
        "reply": reply_text,
        "month": month_clean
    }
