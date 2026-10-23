import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("email_sender")

def send_verification_email(to_email: str, name: str, code: str) -> dict:
    """
    Envía un correo con el código de verificación de 6 dígitos.
    Si no hay variables SMTP configuradas, opera en modo desarrollo para pruebas inmediatas.
    """
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    smtp_from = os.environ.get("SMTP_FROM", f"CB Asesor <{smtp_user}>" if smtp_user else "CB Asesor <noreply@cbasesor.com>")

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
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #09090b; color: #f4f4f5; margin: 0; padding: 20px; }}
            .card {{ max-width: 480px; margin: 0 auto; background-color: #18181b; border: 1px solid #27272a; border-radius: 12px; padding: 32px; }}
            .logo {{ color: #d4af37; font-size: 22px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 24px; text-align: center; }}
            .title {{ font-size: 18px; font-weight: 600; color: #fafafa; margin-bottom: 12px; }}
            .code-box {{ background-color: #09090b; border: 2px dashed #d4af37; border-radius: 8px; padding: 18px; text-align: center; font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #f59e0b; margin: 24px 0; }}
            .footer {{ font-size: 12px; color: #71717a; text-align: center; margin-top: 24px; border-top: 1px solid #27272a; padding-top: 16px; }}
          </style>
        </head>
        <body>
          <div class="card">
            <div class="logo">CB Asesor</div>
            <div class="title">Verificación de tu cuenta</div>
            <p>Hola <strong>{name}</strong>,</p>
            <p>Usa el siguiente código de 6 dígitos para verificar tu dirección de correo y crear tu clave de acceso:</p>
            <div class="code-box">{code}</div>
            <p style="font-size: 13px; color: #a1a1aa;">Este código es de uso único y vence en 15 minutos. Si no solicitaste este registro, puedes desestimar este mensaje.</p>
            <div class="footer">
              CB Asesor Profesional • Gestión de Tickets y Gastos
            </div>
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
