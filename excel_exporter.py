import io
import csv
from pathlib import Path
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ticket_ocr import load_monthly_expenses, get_monthly_summary

def generate_excel_report(month_str: str, user_email: str = None) -> bytes:
    """
    Genera un archivo Excel (.xlsx) profesional con formato institucional CB Asesor:
    - Hoja 1: Resumen Ejecutivo y Totales por Comercio.
    - Hoja 2: Libro IVA Compras (Formato para Contador).
    - Hoja 3: Detalle Ítem por Ítem de Productos Comprados.
    """
    summary = get_monthly_summary(month_str, user_email=user_email)
    tickets = summary.get("tickets", [])
    
    wb = openpyxl.Workbook()
    
    # Estilos de marca CB Asesor
    gold_fill = PatternFill(start_color="D4AF37", end_color="D4AF37", fill_type="solid")
    dark_fill = PatternFill(start_color="121215", end_color="121215", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    gold_font = Font(name="Calibri", size=11, bold=True, color="000000")
    title_font = Font(name="Calibri", size=14, bold=True, color="D4AF37")
    thin_border = Border(
        left=Side(style='thin', color='D4AF37'),
        right=Side(style='thin', color='D4AF37'),
        top=Side(style='thin', color='D4AF37'),
        bottom=Side(style='thin', color='D4AF37')
    )
    
    # -------------------------------------------------------------
    # HOJA 1: Resumen de Gastos por Comercio
    # -------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "Resumen por Comercio"
    ws1.views.sheetView[0].showGridLines = True
    
    ws1.merge_cells("A1:D1")
    ws1["A1"] = f"CB ASESOR - RESUMEN DE GASTOS ({month_str.replace('_', '/')})"
    ws1["A1"].font = title_font
    
    ws1["A3"] = "TOTAL GASTADO:"; ws1["B3"] = summary["total_spent"]
    ws1["A4"] = "SUBTOTAL NETO:"; ws1["B4"] = summary["total_subtotal"]
    ws1["A5"] = "TOTAL IVA (Crédito Fiscal):"; ws1["B5"] = summary["total_iva"]
    ws1["A6"] = "TOTAL PERCEPCIONES IIBB:"; ws1["B6"] = summary.get("total_percepcion_iibb", 0.0)
    ws1["A7"] = "TOTAL PERCEPCIONES IVA:"; ws1["B7"] = summary.get("total_percepcion_iva", 0.0)
    ws1["A8"] = "TOTAL COMPROBANTES:"; ws1["B8"] = summary["tickets_count"]
    
    for row in range(3, 9):
        ws1[f"A{row}"].font = Font(bold=True)
        ws1[f"B{row}"].number_format = '$#,##0.00' if row < 8 else '#,##0'
        
    ws1.append([])
    ws1.append(["Comercio / Proveedor", "Monto Total ($)", "Porcentaje del Gasto", "N° de Compras"])
    header_row_idx = 10
    for col_num in range(1, 5):
        cell = ws1.cell(row=header_row_idx, column=col_num)
        cell.fill = dark_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        
    for v in summary.get("vendor_breakdown", []):
        count_v = sum(1 for t in tickets if t.get("vendor") == v["vendor"])
        ws1.append([v["vendor"], v["total"], f"{v['percentage']}%", count_v])
        
    # -------------------------------------------------------------
    # HOJA 2: Libro IVA Compras & Régimen de Percepciones (Contador)
    # -------------------------------------------------------------
    ws2 = wb.create_sheet(title="Libro IVA & Percepciones")
    ws2.append([
        "Fecha", "Tipo Comprobante", "Punto Vta - N°", "Proveedor", "CUIT", "CAE",
        "Neto Gravado ($)", "IVA 21% ($)", "IVA 10.5% ($)", "IVA 27% ($)", "Total IVA ($)",
        "Percep. IIBB ($)", "Jurisdicción IIBB", "Percep. IVA ($)", "Imp. Internos ($)", "Total ($)"
    ])
    
    for col_num in range(1, 17):
        cell = ws2.cell(row=1, column=col_num)
        cell.fill = gold_fill
        cell.font = gold_font
        cell.alignment = Alignment(horizontal="center")
        
    for t in tickets:
        sum_iva = round(float(t.get("iva_21") or 0.0) + float(t.get("iva_10_5") or 0.0) + float(t.get("iva_27") or 0.0), 2)
        ws2.append([
            t.get("date", ""),
            t.get("invoice_type", "Factura A"),
            t.get("invoice_number", ""),
            t.get("vendor", ""),
            t.get("cuit", ""),
            t.get("cae", ""),
            float(t.get("subtotal") or 0.0),
            float(t.get("iva_21") or 0.0),
            float(t.get("iva_10_5") or 0.0),
            float(t.get("iva_27") or 0.0),
            sum_iva,
            float(t.get("percepcion_iibb") or 0.0),
            t.get("percepcion_iibb_jurisdiccion", ""),
            float(t.get("percepcion_iva") or 0.0),
            float(t.get("impuestos_internos") or 0.0),
            float(t.get("total") or 0.0)
        ])
        
    # -------------------------------------------------------------
    # HOJA 3: Detalle Ítem por Ítem de Productos
    # -------------------------------------------------------------
    ws3 = wb.create_sheet(title="Detalle de Productos")
    ws3.append(["Fecha", "Comercio", "Producto / Ítem", "Cantidad", "Precio ($)"])
    
    for col_num in range(1, 6):
        cell = ws3.cell(row=1, column=col_num)
        cell.fill = dark_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        
    for t in tickets:
        for item in t.get("items", []):
            item_name = item.get("name") or item.get("description") or "Producto / Servicio"
            item_qty = item.get("qty") or item.get("quantity") or 1
            item_price = item.get("price") or item.get("amount") or 0.0
            ws3.append([
                t.get("date", ""),
                t.get("vendor", ""),
                item_name,
                item_qty,
                item_price
            ])
            
    # -------------------------------------------------------------
    # HOJA 4: Resumen de Tarjetas y Consumos Bancarios (si existen)
    # -------------------------------------------------------------
    try:
        from card_processor import load_monthly_cards
        cards = load_monthly_cards(month_str, user_email=user_email)
    except Exception:
        cards = []

    if cards:
        ws4 = wb.create_sheet(title="Resumen Tarjetas")
        
        # Título
        ws4.merge_cells("A1:G1")
        title_cell = ws4["A1"]
        title_cell.value = f"RESUMEN MENSUAL DE TARJETAS Y BANCOS - {month_str}"
        title_cell.font = title_font
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws4.row_dimensions[1].height = 25
        
        # Tabla 1: Estado de Cuentas / Tarjetas
        ws4.append([])
        ws4.append(["Banco / Entidad", "Marca", "N° Tarjeta", "Cierre", "Vencimiento", "Total ($)", "Total (USD)", "Pago Mínimo ($)"])
        hdr_row = ws4.max_row
        for col_idx in range(1, 9):
            c = ws4.cell(row=hdr_row, column=col_idx)
            c.fill = gold_fill
            c.font = gold_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            
        for card in cards:
            ws4.append([
                card.get("entidad", ""),
                f"{card.get('marca', '')} {card.get('tipo_tarjeta', '')}".strip(),
                card.get("numero_tarjeta_ultimos4") or "N/D",
                card.get("fecha_cierre", ""),
                card.get("fecha_vencimiento", ""),
                card.get("saldo_pesos", 0.0),
                card.get("saldo_dolares", 0.0),
                card.get("pago_minimo_pesos", 0.0)
            ])
            
        # Tabla 2: Consumos Detallados
        ws4.append([])
        ws4.append([])
        ws4.append(["Fecha", "Tarjeta / Banco", "Comercio / Detalle", "Cuota", "Moneda", "Monto", "Categoría"])
        tx_hdr_row = ws4.max_row
        for col_idx in range(1, 8):
            c = ws4.cell(row=tx_hdr_row, column=col_idx)
            c.fill = dark_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            
        for card in cards:
            card_label = f"{card.get('marca', 'Tarjeta')} ({card.get('entidad', '')})".strip()
            for tx in card.get("consumos", []):
                cuota_str = f"{tx.get('cuota_actual')}/{tx.get('cuota_total')}" if tx.get("cuota_actual") and tx.get("cuota_total") else "-"
                ws4.append([
                    tx.get("fecha", ""),
                    card_label,
                    tx.get("detalle", ""),
                    cuota_str,
                    tx.get("moneda", "ARS"),
                    tx.get("monto", 0.0),
                    tx.get("categoria", "Varios")
                ])
                
        # Tabla 3: Impuestos y Percepciones de Tarjetas
        ws4.append([])
        ws4.append(["Banco / Tarjeta", "Sellos ($)", "Intereses Fin. ($)", "IVA 21% Int. ($)", "Perc. IIBB ($)", "Perc. AFIP 4815 ($)", "Otros Cargos ($)"])
        tax_hdr_row = ws4.max_row
        for col_idx in range(1, 8):
            c = ws4.cell(row=tax_hdr_row, column=col_idx)
            c.fill = gold_fill
            c.font = gold_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            
        for card in cards:
            imp = card.get("impuestos_y_cargos", {})
            ws4.append([
                f"{card.get('entidad', '')} - {card.get('marca', '')}",
                imp.get("sellos", 0.0),
                imp.get("intereses_financiacion", 0.0),
                imp.get("iva_intereses_21", 0.0),
                imp.get("percepcion_iibb", 0.0),
                imp.get("percepcion_afip_rg4815", 0.0),
                imp.get("otros_cargos", 0.0)
            ])

    # -------------------------------------------------------------
    # HOJA 5: Bancos, Extractos y Préstamos (Etapa 2)
    # -------------------------------------------------------------
    try:
        from bank_processor import load_monthly_bank_data
        bank_docs = load_monthly_bank_data(month_str, user_email=user_email)
    except Exception:
        bank_docs = []

    if bank_docs:
        ws5 = wb.create_sheet(title="Bancos y Préstamos")
        ws5.views.sheetView[0].showGridLines = True
        
        # Título
        ws5.merge_cells("A1:J1")
        title_cell_b = ws5["A1"]
        title_cell_b.value = f"MOVIMIENTOS BANCARIOS Y PRÉSTAMOS - {month_str}"
        title_cell_b.font = title_font
        title_cell_b.alignment = Alignment(horizontal="center", vertical="center")
        ws5.row_dimensions[1].height = 25

        loans = [d for d in bank_docs if d.get("tipo_documento") == "cuota_prestamo"]
        statements = [d for d in bank_docs if d.get("tipo_documento") == "extracto_bancario"]

        # SECCIÓN 1: CUOTAS DE PRÉSTAMOS Y FINANCIAMIENTO
        if loans:
            ws5.append([])
            ws5.append(["PRÉSTAMOS Y CUOTAS FINANCIERAS"])
            ws5.cell(row=ws5.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
            ws5.append(["Entidad / Banco", "N° Préstamo", "Cuota", "Vencimiento / Pago", "Capital ($)", "Interés ($)", "IVA Int. 21% ($)", "Seguro / Otros ($)", "Total Cuota ($)", "Deuda Restante ($)"])
            loan_hdr_row = ws5.max_row
            for col_idx in range(1, 11):
                c = ws5.cell(row=loan_hdr_row, column=col_idx)
                c.fill = gold_fill
                c.font = gold_font
                c.alignment = Alignment(horizontal="center", vertical="center")

            for loan in loans:
                desg = loan.get("desglose", {})
                cuota_str = f"{loan.get('cuota_actual')}/{loan.get('cuota_total')}" if loan.get("cuota_actual") and loan.get("cuota_total") else "-"
                ws5.append([
                    loan.get("entidad", ""),
                    loan.get("numero_prestamo") or "N/D",
                    cuota_str,
                    loan.get("fecha_pago") or loan.get("fecha_vencimiento", ""),
                    desg.get("capital", 0.0),
                    desg.get("interes_compensatorio", 0.0),
                    desg.get("iva_intereses", 0.0),
                    desg.get("seguro_vida_deudor", 0.0) + desg.get("gastos_administrativos", 0.0) + desg.get("sellos_u_otros", 0.0),
                    loan.get("monto_total", 0.0),
                    loan.get("saldo_deuda_remanente", 0.0)
                ])

        # SECCIÓN 2: RESUMEN DE CUENTAS Y EXTRACTOS BANCARIOS
        if statements:
            ws5.append([])
            ws5.append(["RESUMEN DE CUENTAS BANCARIAS"])
            ws5.cell(row=ws5.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
            ws5.append(["Banco / Entidad", "Tipo de Cuenta", "N° de Cuenta / CBU", "Período", "Saldo Inicial ($)", "Total Débitos ($)", "Total Créditos ($)", "Saldo Final ($)"])
            stmt_hdr_row = ws5.max_row
            for col_idx in range(1, 9):
                c = ws5.cell(row=stmt_hdr_row, column=col_idx)
                c.fill = gold_fill
                c.font = gold_font
                c.alignment = Alignment(horizontal="center", vertical="center")

            for st in statements:
                periodo_str = f"{st.get('periodo_desde', '')} al {st.get('periodo_hasta', '')}" if st.get("periodo_desde") else st.get("periodo", "")
                ws5.append([
                    st.get("entidad", ""),
                    st.get("tipo_cuenta", ""),
                    st.get("numero_cuenta") or st.get("cbu") or "N/D",
                    periodo_str,
                    st.get("saldo_inicial", 0.0),
                    st.get("total_debitos", 0.0),
                    st.get("total_creditos", 0.0),
                    st.get("saldo_final", 0.0)
                ])

            # SECCIÓN 3: GASTOS E IMPUESTOS BANCARIOS DEDUCIBLES
            ws5.append([])
            ws5.append(["GASTOS E IMPUESTOS BANCARIOS DEDUCIBLES"])
            ws5.cell(row=ws5.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
            ws5.append(["Banco / Cuenta", "Comisiones Mant. ($)", "Imp. Ley 25.413 Déb/Créd ($)", "IVA Bancario 21% ($)", "Perc. SIRCREB / IIBB ($)", "Otros Impuestos ($)"])
            tax_b_hdr_row = ws5.max_row
            for col_idx in range(1, 7):
                c = ws5.cell(row=tax_b_hdr_row, column=col_idx)
                c.fill = dark_fill
                c.font = header_font
                c.alignment = Alignment(horizontal="center", vertical="center")

            for st in statements:
                g = st.get("gastos_e_impuestos_deducibles", {})
                cuenta_id = f"{st.get('entidad', '')} ({st.get('tipo_cuenta', '')})".strip()
                ws5.append([
                    cuenta_id,
                    g.get("comisiones_mantenimiento", 0.0),
                    g.get("impuesto_ley_25413_debitos_creditos", 0.0),
                    g.get("iva_bancario_21", 0.0),
                    g.get("percepcion_sircreb_iibb", 0.0),
                    g.get("otros_impuestos", 0.0)
                ])

            # SECCIÓN 4: MOVIMIENTOS BANCARIOS PRINCIPALES
            ws5.append([])
            ws5.append(["DETALLE DE MOVIMIENTOS BANCARIOS RELEVANTES"])
            ws5.cell(row=ws5.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
            ws5.append(["Fecha", "Banco / Cuenta", "Tipo", "Concepto / Descripción", "Monto ($)", "Categoría"])
            mov_hdr_row = ws5.max_row
            for col_idx in range(1, 7):
                c = ws5.cell(row=mov_hdr_row, column=col_idx)
                c.fill = dark_fill
                c.font = header_font
                c.alignment = Alignment(horizontal="center", vertical="center")

            for st in statements:
                banco_label = f"{st.get('entidad', '')}".strip()
                for mov in st.get("movimientos_principales", []):
                    ws5.append([
                        mov.get("fecha", ""),
                        banco_label,
                        mov.get("tipo", ""),
                        mov.get("concepto", ""),
                        mov.get("monto", 0.0),
                        mov.get("categoria", "Varios")
                    ])

    # -------------------------------------------------------------
    # HOJA 6: Inversiones, Cauciones y Mercado de Capitales (Etapa 3)
    # -------------------------------------------------------------
    try:
        from investment_processor import load_monthly_investments
        investments = load_monthly_investments(month_str, user_email=user_email)
    except Exception:
        investments = []

    if investments:
        ws6 = wb.create_sheet(title="Inversiones y Cauciones")
        ws6.views.sheetView[0].showGridLines = True
        
        # Título
        ws6.merge_cells("A1:K1")
        title_cell_inv = ws6["A1"]
        title_cell_inv.value = f"OPERACIONES BURSÁTILES, CAUCIONES E INVERSIONES - {month_str}"
        title_cell_inv.font = title_font
        title_cell_inv.alignment = Alignment(horizontal="center", vertical="center")
        ws6.row_dimensions[1].height = 25

        # SECCIÓN 1: BOLETOS DE OPERACIONES Y CAUCIONES
        ws6.append([])
        ws6.append(["DETALLE DE OPERACIONES Y CAUCIONES BURSÁTILES"])
        ws6.cell(row=ws6.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
        ws6.append(["ALyC / Entidad", "N° Boleto", "Operación", "Especie / Título", "Concertación", "Vencimiento", "Plazo (Días)", "TNA (%)", "Monto Operado", "Interés Bruto", "Neto Liquidado"])
        inv_hdr_row = ws6.max_row
        for col_idx in range(1, 12):
            c = ws6.cell(row=inv_hdr_row, column=col_idx)
            c.fill = gold_fill
            c.font = gold_font
            c.alignment = Alignment(horizontal="center", vertical="center")

        for inv in investments:
            tipo_op = inv.get("tipo_operacion", "").replace("_", " ").title()
            ws6.append([
                inv.get("entidad", ""),
                inv.get("numero_boleto") or "N/D",
                tipo_op,
                inv.get("especie", ""),
                inv.get("fecha_concertacion", ""),
                inv.get("fecha_vencimiento", ""),
                inv.get("plazo_dias") or "-",
                inv.get("tasa_nominal_anual", 0.0),
                inv.get("monto_operado", 0.0),
                inv.get("interes_bruto", 0.0),
                inv.get("monto_neto_liquidado", 0.0)
            ])

        # SECCIÓN 2: ARANCELES, DERECHOS DE MERCADO E IVA COMPUTABLE
        ws6.append([])
        ws6.append(["ARANCELES, DERECHOS DE MERCADO E IVA COMPUTABLE"])
        ws6.cell(row=ws6.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
        ws6.append(["ALyC / Entidad", "N° Boleto", "Arancel ALyC ($)", "Derechos Mercado ($)", "IVA 21% Aranceles ($)", "Otros Gastos ($)", "Total Gastos ($)"])
        fees_hdr_row = ws6.max_row
        for col_idx in range(1, 8):
            c = ws6.cell(row=fees_hdr_row, column=col_idx)
            c.fill = dark_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center")

        for inv in investments:
            fees = inv.get("aranceles_y_gastos", {})
            total_gasto = (fees.get("arancel_alyc", 0.0) + fees.get("derechos_mercado", 0.0) + 
                           fees.get("iva_aranceles_21", 0.0) + fees.get("otros_gastos", 0.0))
            ws6.append([
                inv.get("entidad", ""),
                inv.get("numero_boleto") or "N/D",
                fees.get("arancel_alyc", 0.0),
                fees.get("derechos_mercado", 0.0),
                fees.get("iva_aranceles_21", 0.0),
                fees.get("otros_gastos", 0.0),
                total_gasto
            ])

    # -------------------------------------------------------------
    # HOJA 7: Certificados de Retención y Pagos de VEPs (Etapa 4)
    # -------------------------------------------------------------
    try:
        from tax_processor import load_monthly_taxes
        tax_docs = load_monthly_taxes(month_str, user_email=user_email)
    except Exception:
        tax_docs = []

    if tax_docs:
        ws7 = wb.create_sheet(title="Retenciones y VEPs")
        ws7.views.sheetView[0].showGridLines = True
        
        # Título
        ws7.merge_cells("A1:I1")
        title_cell_tax = ws7["A1"]
        title_cell_tax.value = f"CERTIFICADOS DE RETENCIÓN Y PAGOS DE VEPS - {month_str}"
        title_cell_tax.font = title_font
        title_cell_tax.alignment = Alignment(horizontal="center", vertical="center")
        ws7.row_dimensions[1].height = 25

        retenciones = [t for t in tax_docs if t.get("tipo_documento") == "certificado_retencion"]
        veps = [t for t in tax_docs if t.get("tipo_documento") == "pago_vep"]

        # SECCIÓN 1: RETENCIONES SUFRIDAS (CRÉDITO FISCAL A FAVOR)
        if retenciones:
            ws7.append([])
            ws7.append(["RETENCIONES SUFRIDAS (CRÉDITO FISCAL A FAVOR)"])
            ws7.cell(row=ws7.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
            ws7.append(["Agente de Retención", "CUIT Agente", "Impuesto Retenido", "Régimen / Jurisdicción", "N° Certificado", "Fecha", "Base Imponible ($)", "Alícuota (%)", "Importe Retenido ($)"])
            ret_hdr_row = ws7.max_row
            for col_idx in range(1, 10):
                c = ws7.cell(row=ret_hdr_row, column=col_idx)
                c.fill = gold_fill
                c.font = gold_font
                c.alignment = Alignment(horizontal="center", vertical="center")

            total_retenido = 0.0
            for r in retenciones:
                monto_ret = r.get("importe_retenido", 0.0)
                total_retenido += monto_ret
                regimen_str = f"{r.get('regimen', '')} - {r.get('jurisdiccion', '')}".strip(" -")
                ws7.append([
                    r.get("agente_retencion_nombre", ""),
                    r.get("agente_retencion_cuit", ""),
                    r.get("impuesto_retenido", ""),
                    regimen_str,
                    r.get("numero_certificado") or "N/D",
                    r.get("fecha_emision", ""),
                    r.get("base_imponible", 0.0),
                    r.get("alicuota_porcentaje", 0.0),
                    monto_ret
                ])
            # Total Retenciones
            ws7.append(["TOTAL CRÉDITO RETENCIONES:", "", "", "", "", "", "", "", total_retenido])
            tot_ret_row = ws7.max_row
            ws7.cell(row=tot_ret_row, column=1).font = Font(bold=True)
            ws7.cell(row=tot_ret_row, column=9).font = Font(bold=True, color="D4AF37")

        # SECCIÓN 2: PAGOS DE VEPS IMPOSITIVOS
        if veps:
            ws7.append([])
            ws7.append(["PAGOS DE VEPS IMPOSITIVOS Y PREVISIONALES"])
            ws7.cell(row=ws7.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
            ws7.append(["Organismo", "N° de VEP", "Concepto / Subconcepto", "Período Fiscal", "Fecha de Pago", "Entidad de Pago", "Monto Pagado ($)"])
            vep_hdr_row = ws7.max_row
            for col_idx in range(1, 8):
                c = ws7.cell(row=vep_hdr_row, column=col_idx)
                c.fill = dark_fill
                c.font = header_font
                c.alignment = Alignment(horizontal="center", vertical="center")

            total_veps = 0.0
            for v in veps:
                monto_vep = v.get("monto_pagado", 0.0)
                total_veps += monto_vep
                concepto_str = f"{v.get('concepto', '')} {v.get('subconcepto', '')}".strip()
                ws7.append([
                    v.get("organismo", "AFIP / ARCA"),
                    v.get("numero_vep") or "N/D",
                    concepto_str,
                    v.get("periodo_fiscal", ""),
                    v.get("fecha_pago", ""),
                    v.get("entidad_pago", ""),
                    monto_vep
                ])
            # Total VEPs
            ws7.append(["TOTAL VEPS PAGADOS:", "", "", "", "", "", total_veps])
            tot_vep_row = ws7.max_row
            ws7.cell(row=tot_vep_row, column=1).font = Font(bold=True)
            ws7.cell(row=tot_vep_row, column=7).font = Font(bold=True, color="D4AF37")

    # -------------------------------------------------------------
    # HOJA 8: Auditoría Financiera y Consejos de Asesor IA (Etapa 5)
    # -------------------------------------------------------------
    try:
        from advisor_processor import get_advisor_cache_file, collect_month_financial_ecosystem
        cache_f = get_advisor_cache_file(month_str, user_email=user_email)
        audit_data = None
        if cache_f.exists():
            import json
            with open(cache_f, "r", encoding="utf-8") as jf:
                audit_data = json.load(jf)
        if not audit_data:
            eco = collect_month_financial_ecosystem(month_str, user_email=user_email)
            audit_data = {
                "kpis": eco["kpis"],
                "desglose_costos_ocultos": eco["desglose_costos_ocultos"],
                "rubros": eco["rubros"],
                "cuotas_futuras": eco["cuotas_futuras"],
                "ai_insights": {
                    "semaforo_salud": "Informativo",
                    "semaforo_motivo": "Diagnóstico financiero automático consolidado",
                    "resumen_ejecutivo": f"Salidas registradas por $ {eco['kpis']['total_salidas_pesos']:,.2f} y costos financieros de $ {eco['kpis']['costos_financieros_ocultos']:,.2f}.",
                    "optimizacion_fiscal": f"Crédito fiscal computable en IVA: $ {eco['kpis']['credito_fiscal_iva_total']:,.2f}.",
                    "consejos_ahorro": []
                }
            }

        ws8 = wb.create_sheet(title="Auditoría y Asesor IA")
        ws8.views.sheetView[0].showGridLines = True

        ws8.merge_cells("A1:F1")
        title_cell8 = ws8["A1"]
        title_cell8.value = f"CB ASESOR - AUDITORÍA FINANCIERA & CONSEJOS IA ({month_str.replace('_', '/')})"
        title_cell8.font = title_font
        title_cell8.alignment = Alignment(horizontal="center", vertical="center")
        ws8.row_dimensions[1].height = 25

        # KPIs Principales
        kpis = audit_data.get("kpis", {})
        insights = audit_data.get("ai_insights", {})
        ws8.append([])
        ws8.append(["DIAGNÓSTICO GENERAL Y SEMÁFORO:", insights.get("semaforo_salud", "N/D"), f"({insights.get('semaforo_motivo', '')})"])
        ws8.cell(row=ws8.max_row, column=1).font = Font(name="Calibri", size=11, bold=True, color="D4AF37")
        ws8.cell(row=ws8.max_row, column=2).font = Font(name="Calibri", size=11, bold=True, color="10B981" if insights.get("semaforo_salud") == "Optimo" else ("EF4444" if insights.get("semaforo_salud") == "Alerta" else "F59E0B"))

        ws8.append([])
        ws8.append(["Indicador Financiero Clave", "Valor ($)", "Observaciones Contables / Fiscales"])
        hdr8_row = ws8.max_row
        for col_idx in range(1, 4):
            c = ws8.cell(row=hdr8_row, column=col_idx)
            c.fill = dark_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center")

        indicadores = [
            ("Total Salidas del Mes (Pesos)", kpis.get("total_salidas_pesos", 0.0), "Compras, tarjetas, cuotas bancarias y VEPs"),
            ("Total Salidas del Mes (USD)", kpis.get("total_salidas_usd", 0.0), "Consumos en moneda extranjera"),
            ("Costos Financieros Ocultos", kpis.get("costos_financieros_ocultos", 0.0), "Intereses de tarjeta, préstamos, comisiones y sellos"),
            ("Crédito Fiscal de IVA Total Acumulado", kpis.get("credito_fiscal_iva_total", 0.0), "IVA computable de tickets, tarjetas, préstamos y bancos"),
            ("Retenciones y Percepciones a Favor", kpis.get("creditos_impositivos_favor", 0.0), "Deducibles en declaraciones juradas impositivas"),
            ("Cuotas Comprometidas Próximo Mes (+1)", kpis.get("cuotas_proximo_mes", 0.0), "Vencimientos exigibles en el mes siguiente"),
            ("Rendimiento Inversiones / Cauciones", kpis.get("inversiones_rendimiento", 0.0), f"TNA Promedio: {kpis.get('inversiones_tna_promedio', 0)}%")
        ]
        for ind, val, obs in indicadores:
            ws8.append([ind, val, obs])
            ws8.cell(row=ws8.max_row, column=2).number_format = "$ #,##0.00"

        # Resumen Ejecutivo de la IA
        ws8.append([])
        ws8.append(["RESUMEN EJECUTIVO Y DIAGNÓSTICO IA:"])
        ws8.cell(row=ws8.max_row, column=1).font = Font(name="Calibri", size=11, bold=True, color="D4AF37")
        ws8.append([insights.get("resumen_ejecutivo", "")])

        if insights.get("analisis_costos_ocultos"):
            ws8.append([])
            ws8.append(["ANÁLISIS DE COSTOS FINANCIEROS Y DEUDA:"])
            ws8.cell(row=ws8.max_row, column=1).font = Font(name="Calibri", size=11, bold=True, color="D4AF37")
            ws8.append([insights.get("analisis_costos_ocultos", "")])

        if insights.get("optimizacion_fiscal"):
            ws8.append([])
            ws8.append(["OPTIMIZACIÓN FISCAL & CRÉDITO DE IVA:"])
            ws8.cell(row=ws8.max_row, column=1).font = Font(name="Calibri", size=11, bold=True, color="D4AF37")
            ws8.append([insights.get("optimizacion_fiscal", "")])

        # Consejos de Ahorro
        consejos = insights.get("consejos_ahorro", [])
        if consejos:
            ws8.append([])
            ws8.append(["CONSEJOS CONCRETOS DE AHORRO Y EFICIENCIA (IA)"])
            ws8.cell(row=ws8.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
            ws8.append(["Prioridad", "Título de Recomendación", "Acción Táctica Sugerida", "Impacto Estimado"])
            cons_hdr = ws8.max_row
            for col_idx in range(1, 5):
                c = ws8.cell(row=cons_hdr, column=col_idx)
                c.fill = dark_fill
                c.font = header_font
                c.alignment = Alignment(horizontal="center", vertical="center")
            for cs in consejos:
                ws8.append([
                    cs.get("prioridad", "Media"),
                    cs.get("titulo", ""),
                    cs.get("descripcion", ""),
                    cs.get("impacto_estimado", "")
                ])

        # Planificación de Cuotas Futuras
        cuotas_f = audit_data.get("cuotas_futuras", [])
        if cuotas_f:
            ws8.append([])
            ws8.append(["PLANIFICACIÓN DE CUOTAS COMPROMETIDAS A FUTURO"])
            ws8.cell(row=ws8.max_row, column=1).font = Font(name="Calibri", size=12, bold=True, color="D4AF37")
            ws8.append(["Período Futuro", "Cantidad de Cuotas", "Monto Total Comprometido ($)"])
            cf_hdr = ws8.max_row
            for col_idx in range(1, 4):
                c = ws8.cell(row=cf_hdr, column=col_idx)
                c.fill = dark_fill
                c.font = header_font
                c.alignment = Alignment(horizontal="center", vertical="center")
            for cf in cuotas_f:
                ws8.append([
                    cf.get("periodo_label", cf.get("periodo", "")),
                    cf.get("cantidad_cuotas", 0),
                    cf.get("total", 0.0)
                ])
                ws8.cell(row=ws8.max_row, column=3).number_format = "$ #,##0.00"

    except Exception as ex_ws8:
        pass

    # Ajustar ancho de columnas automáticamente
    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)
            
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()

def generate_csv_report(month_str: str, user_email: str = None) -> bytes:
    """Genera archivo CSV de IVA Compras listo para enviar al contador."""
    summary = get_monthly_summary(month_str, user_email=user_email)
    tickets = summary.get("tickets", [])
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["Fecha", "Tipo Comprobante", "Proveedor", "CUIT", "Neto Gravado", "IVA 21%", "IVA 10.5%", "Total"])
    
    for t in tickets:
        writer.writerow([
            t.get("date", ""),
            t.get("invoice_type", "Factura A"),
            t.get("vendor", ""),
            t.get("cuit", ""),
            f"{t.get('subtotal', 0.0):.2f}".replace('.', ','),
            f"{t.get('iva_21', 0.0):.2f}".replace('.', ','),
            f"{t.get('iva_10_5', 0.0):.2f}".replace('.', ','),
            f"{t.get('total', 0.0):.2f}".replace('.', ',')
        ])
        
    return output.getvalue().encode('utf-8-sig')
