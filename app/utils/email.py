import smtplib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import SMTP_USERNAME, SMTP_PASSWORD, FRONTEND_URL

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

def send_password_set_email(to: str, token: str) -> None:
    url = f"{FRONTEND_URL}/set-password?token={token}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Configura tu contraseña — Flowdesk"
    msg["From"] = SMTP_USERNAME
    msg["To"] = to
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;border:1px solid #e5e7eb;border-radius:8px;">
        <h2 style="color:#111827;margin-bottom:8px;">Bienvenido a Flowdesk</h2>
        <p style="color:#6b7280;margin-bottom:24px;">Tu cuenta ha sido creada. Configura tu contraseña para comenzar.</p>
        <a href="{url}" style="background:#111827;color:#ffffff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">
            Configurar contraseña
        </a>
        <p style="color:#9ca3af;font-size:12px;margin-top:32px;">Este enlace expira en 48 horas.</p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, to, msg.as_string())

def send_password_reset_email(to: str, token: str) -> None:
    url = f"{FRONTEND_URL}/reset-password?token={token}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Recupera tu contraseña — Flowdesk"
    msg["From"] = SMTP_USERNAME
    msg["To"] = to
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;border:1px solid #e5e7eb;border-radius:8px;">
        <h2 style="color:#111827;margin-bottom:8px;">Recuperación de contraseña</h2>
        <p style="color:#6b7280;margin-bottom:24px;">Recibimos una solicitud para restablecer tu contraseña.</p>
        <a href="{url}" style="background:#111827;color:#ffffff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">
            Restablecer contraseña
        </a>
        <p style="color:#9ca3af;font-size:12px;margin-top:32px;">Este enlace expira en 15 minutos. Si no solicitaste esto, ignora este mensaje.</p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, to, msg.as_string())