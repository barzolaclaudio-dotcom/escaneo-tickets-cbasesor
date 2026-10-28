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
