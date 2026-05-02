#!/usr/bin/env python3
import imaplib
import email
import smtplib
import os
import re
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

GMAIL_EMAIL = os.environ["GMAIL_EMAIL"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
SANTANDER_SENDER = "mensajesyavisos@mails.santander.com.ar"
CARD_LABELS = {
    "7527": "Visa Crédito ••••7527",
    "5295": "Tarjeta ••••5295",
}


def fetch_santander_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)

    # Buscar en todas las carpetas posibles (inbox, promociones, etc.)
    folders = ["inbox", '"[Gmail]/All Mail"']
    since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")

    seen_ids = set()
    messages = []

    for folder in folders:
        result, _ = mail.select(folder)
        if result != "OK":
            continue
        _, ids = mail.search(None, f'FROM "{SANTANDER_SENDER}" SINCE {since}')
        for msg_id in ids[0].split():
            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)
            _, data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            subject = str(msg.get("Subject", ""))
            if "Pagaste" in subject or "pagaste" in subject:
                messages.append(msg)

    mail.logout()
    return messages


def extract_html(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return part.get_payload(decode=True).decode("utf-8", errors="ignore")
    return msg.get_payload(decode=True).decode("utf-8", errors="ignore")


def parse_expense(msg):
    html = extract_html(msg)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    def find(pattern):
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else None

    card = find(r"terminada en (\d{4})")
    monto = find(r"Monto\s+\$([0-9.,]+)")
    cuotas = find(r"Cuotas\s+(\d+)")
    comercio = find(r"Comercio\s+([^\n]+)")
    fecha = find(r"Fecha\s+(\d{2}/\d{2}/\d{4})")

    if not card or not monto:
        return None

    return {
        "card": card,
        "monto": monto,
        "cuotas": int(cuotas) if cuotas else 1,
        "comercio": comercio or "Desconocido",
        "fecha": fecha or "",
    }


def to_float(monto_str):
    return float(monto_str.replace(".", "").replace(",", "."))


def format_ars(value):
    return f"${value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_card_section(expenses, label):
    if not expenses:
        return f"""
        <h2 style="color:#EC0000;font-family:Arial,sans-serif;margin-top:30px;">{label}</h2>
        <p style="font-family:Arial,sans-serif;color:#666;">Sin gastos registrados esta semana.</p>
        """

    total = sum(to_float(e["monto"]) for e in expenses)
    rows = ""
    for e in sorted(expenses, key=lambda x: x["fecha"]):
        cuotas_badge = (
            f' <span style="background:#fff3f3;color:#EC0000;border-radius:4px;padding:2px 6px;font-size:11px;">{e["cuotas"]} cuotas</span>'
            if e["cuotas"] > 1
            else ""
        )
        rows += f"""
        <tr>
            <td style="padding:10px 8px;border-bottom:1px solid #f0f0f0;font-family:Arial,sans-serif;font-size:13px;color:#555;">{e["fecha"]}</td>
            <td style="padding:10px 8px;border-bottom:1px solid #f0f0f0;font-family:Arial,sans-serif;font-size:13px;">{e["comercio"]}{cuotas_badge}</td>
            <td style="padding:10px 8px;border-bottom:1px solid #f0f0f0;font-family:Arial,sans-serif;font-size:13px;text-align:right;font-weight:bold;">{format_ars(to_float(e["monto"]))}</td>
        </tr>"""

    return f"""
    <h2 style="color:#EC0000;font-family:Arial,sans-serif;margin-top:30px;margin-bottom:12px;">{label}</h2>
    <table style="width:100%;border-collapse:collapse;">
        <thead>
            <tr style="background:#f9f9f9;">
                <th style="padding:10px 8px;text-align:left;font-family:Arial,sans-serif;font-size:12px;color:#999;font-weight:normal;border-bottom:2px solid #eee;">FECHA</th>
                <th style="padding:10px 8px;text-align:left;font-family:Arial,sans-serif;font-size:12px;color:#999;font-weight:normal;border-bottom:2px solid #eee;">COMERCIO</th>
                <th style="padding:10px 8px;text-align:right;font-family:Arial,sans-serif;font-size:12px;color:#999;font-weight:normal;border-bottom:2px solid #eee;">MONTO</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
        <tfoot>
            <tr style="background:#fff8f8;">
                <td colspan="2" style="padding:12px 8px;font-family:Arial,sans-serif;font-weight:bold;font-size:14px;">Total {label.split()[0]}</td>
                <td style="padding:12px 8px;text-align:right;font-family:Arial,sans-serif;font-weight:bold;font-size:14px;color:#EC0000;">{format_ars(total)}</td>
            </tr>
        </tfoot>
    </table>
    """


def build_html(expenses_by_card):
    week_start = (datetime.now() - timedelta(days=7)).strftime("%d/%m/%Y")
    week_end = datetime.now().strftime("%d/%m/%Y")

    sections = ""
    grand_total = 0
    for card_id, label in CARD_LABELS.items():
        expenses = expenses_by_card.get(card_id, [])
        sections += build_card_section(expenses, label)
        grand_total += sum(to_float(e["monto"]) for e in expenses)

    return f"""
    <html>
    <body style="margin:0;padding:0;background:#f4f4f4;">
        <div style="max-width:620px;margin:20px auto;background:white;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
            <div style="background:#EC0000;padding:28px 24px;text-align:center;">
                <h1 style="color:white;margin:0;font-family:Arial,sans-serif;font-size:22px;">Resumen semanal de gastos</h1>
                <p style="color:rgba(255,255,255,0.85);margin:6px 0 0;font-family:Arial,sans-serif;font-size:14px;">{week_start} — {week_end}</p>
            </div>
            <div style="padding:24px;">
                {sections}
                <div style="margin-top:24px;background:#EC0000;border-radius:8px;padding:16px 20px;display:flex;justify-content:space-between;">
                    <span style="color:white;font-family:Arial,sans-serif;font-size:16px;font-weight:bold;">Total general</span>
                    <span style="color:white;font-family:Arial,sans-serif;font-size:18px;font-weight:bold;">{format_ars(grand_total)}</span>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


def send_summary(expenses_by_card):
    week_str = datetime.now().strftime("%d/%m/%Y")
    total = sum(
        sum(to_float(e["monto"]) for e in expenses)
        for expenses in expenses_by_card.values()
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Resumen semanal Santander — {week_str} | Total: {format_ars(total)}"
    msg["From"] = GMAIL_EMAIL
    msg["To"] = GMAIL_EMAIL

    msg.attach(MIMEText(build_html(expenses_by_card), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_EMAIL, GMAIL_EMAIL, msg.as_string())

    print(f"✓ Resumen enviado a {GMAIL_EMAIL} — Total: {format_ars(total)}")


def main():
    print("Buscando mails de Santander de los últimos 7 días...")
    messages = fetch_santander_emails()
    print(f"  {len(messages)} mails encontrados.")

    expenses_by_card = {card: [] for card in CARD_LABELS}
    for msg in messages:
        expense = parse_expense(msg)
        if expense and expense["card"] in expenses_by_card:
            expenses_by_card[expense["card"]].append(expense)

    for card_id, label in CARD_LABELS.items():
        count = len(expenses_by_card[card_id])
        print(f"  {label}: {count} gasto(s)")

    send_summary(expenses_by_card)


if __name__ == "__main__":
    main()
