import os
import smtplib
import logging
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

logger = logging.getLogger("email_sender")

def load_env_file():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        os.environ[k] = v
        except Exception as e:
            logger.warning(f"Error leyendo .env: {e}")

load_env_file()

def get_smtp_config():
    load_env_file()
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    smtp_from = os.environ.get("SMTP_FROM", f"CB Asesor <{smtp_user}>" if smtp_user else "CB Asesor <notificaciones@cbasesor.com>")
    return smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from

def get_email_footer_html() -> str:
    return """
    <div style="margin-top: 32px; padding-top: 24px; border-top: 1px solid #27272a; text-align: center; color: #a1a1aa; font-size: 12px; line-height: 1.6;">
        <div style="margin-bottom: 16px;">
            <a href="https://cbasesor.com" target="_blank" style="display: inline-block; padding: 8px 16px; margin: 4px; background-color: #1f1f23; border: 1px solid #d4af37; border-radius: 8px; color: #d4af37; text-decoration: none; font-weight: 600; font-size: 12px;">
                🌐 Visitar Sitio Web: cbasesor.com
            </a>
            <a href="https://tickets.cbasesor.com" target="_blank" style="display: inline-block; padding: 8px 16px; margin: 4px; background-color: #d4af37; border: 1px solid #d4af37; border-radius: 8px; color: #000000; text-decoration: none; font-weight: 700; font-size: 12px;">
                📲 Descargar / Abrir App en tu Móvil
            </a>
        </div>
        <p style="margin: 4px 0; color: #fafafa; font-weight: 600;">
            CB Asesor • Asesoría, Finanzas & Tecnología
        </p>
        <p style="margin: 4px 0; font-size: 11px; color: #71717a;">
            Contacto y Soporte: <a href="mailto:contacto@cbasesor.com" style="color: #d4af37; text-decoration: none;">contacto@cbasesor.com</a>
        </p>
        <div style="margin-top: 16px; font-size: 10px; color: #52525b; line-height: 1.4; text-align: justify; padding: 10px; background-color: #0d0d10; border-radius: 6px;">
            <strong>Aviso Legal y de Confidencialidad:</strong> La información contenida en este correo y sus archivos adjuntos es de carácter confidencial y para uso exclusivo del destinatario. CB Asesor es una plataforma de digitalización documental y consolidación contable. Los cálculos y lecturas automáticas constituyen herramientas de asistencia y deben ser validados conforme a las normativas de AFIP/ARCA vigentes por el contribuyente y su profesional matriculado.
        </div>
    </div>
    """

def send_verification_email(to_email: str, name: str, code: str) -> dict:
    """
    Envía un correo con el código de verificación de 6 dígitos.
    Si no hay variables SMTP configuradas, opera en modo desarrollo para pruebas inmediatas.
    """
    smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from = get_smtp_config()

    # Si falta configuración de servidor SMTP, retornamos modo desarrollo para no bloquear el flujo
    if not smtp_host or not smtp_user or not smtp_pass:
        logger.info(f"[MODO DEV / PRUEBAS] Código de verificación para {to_email} ({name}): {code}")
        print(f"\n==========================================")
        print(f"🔑 CÓDIGO DE VERIFICACIÓN PARA: {to_email}")
        print(f"👉 CÓDIGO: {code}")
        print(f"==========================================\n")
        return {
            "sent": False,
            "dev_mode": True,
            "code": code,
            "message": "Servidor SMTP no configurado. Código disponible para pruebas inmediatas."
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"{code} es tu código de verificación | CB Asesor"
        msg["From"] = smtp_from
        msg["To"] = to_email

        text_content = f"Hola {name},\n\nTu código de verificación para CB Asesor es: {code}\n\nEste código vencerá en 15 minutos.\n\nEquipo CB Asesor."
        footer_html = get_email_footer_html()
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #09090b; color: #f4f4f5; margin: 0; padding: 20px; }}
            .card {{ max-width: 520px; margin: 0 auto; background-color: #18181b; border: 1px solid #d4af37; border-radius: 16px; padding: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
            .logo {{ color: #d4af37; font-size: 22px; font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 24px; text-align: center; }}
            .title {{ font-size: 18px; font-weight: 700; color: #fafafa; margin-bottom: 12px; }}
            .code-box {{ background-color: #09090b; border: 2px dashed #d4af37; border-radius: 12px; padding: 20px; text-align: center; font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #f59e0b; margin: 24px 0; font-family: monospace; }}
          </style>
        </head>
        <body>
          <div class="card">
            <div class="logo">CB Asesor</div>
            <div class="title">Verificación de tu cuenta</div>
            <p>Hola <strong>{name}</strong>,</p>
            <p>Usa el siguiente código de 6 dígitos para verificar tu dirección de correo y activar tu cuenta:</p>
            <div class="code-box">{code}</div>
            <p style="font-size: 13px; color: #a1a1aa;">Este código es de uso único y vence en 15 minutos. Si no solicitaste este registro, podés desestimar este mensaje.</p>
            {footer_html}
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(text_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to_email], msg.as_string())

        return {"sent": True, "dev_mode": False, "message": "Correo enviado con éxito."}

    except Exception as e:
        logger.error(f"Error enviando correo de verificación a {to_email}: {e}")
        # En caso de fallo de red/SMTP, dev_mode permite seguir probando
        return {
            "sent": False,
            "dev_mode": True,
            "code": code,
            "message": f"Fallo envío SMTP ({str(e)}). Código disponible en log para pruebas."
        }

def send_accountant_report_email(
    to_email: str,
    user_name: str,
    user_email: str,
    month: str,
    stats: dict,
    excel_bytes: bytes,
    filename: str = "reporte_comprobantes.xlsx"
) -> dict:
    """
    Envía por correo el reporte contable mensual e impositivo con el archivo Excel adjunto al contador.
    """
    smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from = get_smtp_config()

    total_spent = stats.get("total_spent", 0.0)
    total_subtotal = stats.get("total_subtotal", 0.0)
    total_iva = stats.get("total_iva", 0.0)
    total_iibb = stats.get("total_iibb", 0.0)
    total_tickets = stats.get("total_tickets", 0)

    if not smtp_host or not smtp_user or not smtp_pass:
        logger.info(f"[MODO DEV / PRUEBAS] Envío a contador {to_email} de {user_name} ({user_email}) para mes {month}: ${total_spent:.2f}")
        return {
            "sent": False,
            "dev_mode": True,
            "message": f"Servidor SMTP no configurado. Reporte simulado con éxito hacia {to_email}."
        }

    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"Reporte Contable e Impositivo {month} | {user_name}"
        msg["From"] = smtp_from
        msg["To"] = to_email
        msg["Reply-To"] = user_email

        footer_html = get_email_footer_html()
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #09090b; color: #f4f4f5; margin: 0; padding: 20px; }}
            .card {{ max-width: 560px; margin: 0 auto; background-color: #18181b; border: 1px solid #d4af37; border-radius: 12px; padding: 28px; }}
            .logo {{ color: #d4af37; font-size: 20px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 20px; text-align: center; }}
            .title {{ font-size: 16px; font-weight: 700; color: #fafafa; margin-bottom: 12px; }}
            .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background-color: #121215; border-radius: 8px; overflow: hidden; }}
            .table td {{ padding: 10px 14px; border-bottom: 1px solid #27272a; font-size: 13px; }}
            .table td.val {{ text-align: right; font-weight: bold; color: #d4af37; font-family: monospace; font-size: 14px; }}
            .footer {{ font-size: 12px; color: #71717a; text-align: center; margin-top: 24px; border-top: 1px solid #27272a; padding-top: 14px; }}
          </style>
        </head>
        <body>
          <div class="card">
            <div class="logo">CB Asesor • Control Contable</div>
            <div class="title">Comprobantes & Gastos del Período: {month}</div>
            <p>Estimado/a Contador/a,</p>
            <p>Le compartimos el consolidado de comprobantes, facturas y gastos generado por <strong>{user_name}</strong> ({user_email}):</p>
            
            <table class="table">
              <tr>
                <td><strong>Total Facturado / Gastado</strong></td>
                <td class="val">${total_spent:,.2f}</td>
              </tr>
              <tr>
                <td>Subtotal Neto Gravado</td>
                <td class="val">${total_subtotal:,.2f}</td>
              </tr>
              <tr>
                <td>IVA Crédito Fiscal (21% / 10.5%)</td>
                <td class="val" style="color: #34d399;">${total_iva:,.2f}</td>
              </tr>
              <tr>
                <td>Percepciones IIBB (ARBA / AGIP / Otras)</td>
                <td class="val" style="color: #fbbf24;">${total_iibb:,.2f}</td>
              </tr>
              <tr>
                <td>Cantidad de Comprobantes</td>
                <td class="val" style="color: #f4f4f5;">{total_tickets}</td>
              </tr>
            </table>

            <p style="font-size: 13px; color: #a1a1aa;">
              📎 Se adjunta a este mensaje el archivo Excel (<strong>{filename}</strong>) que contiene el Libro IVA Compras detallado y el resumen de comprobantes para su liquidación contable.
            </p>

            {footer_html}
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_content, "html", "utf-8"))

        if excel_bytes:
            part = MIMEApplication(excel_bytes, Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to_email], msg.as_string())

        return {"sent": True, "dev_mode": False, "message": f"Reporte enviado con éxito a {to_email}."}

    except Exception as e:
        logger.error(f"Error enviando reporte al contador {to_email}: {e}")
        return {"sent": False, "dev_mode": False, "error": str(e)}
