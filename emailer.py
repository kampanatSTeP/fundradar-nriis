#!/usr/bin/env python3
"""ส่งอีเมลแจ้งเตือนทุนใหม่ผ่าน SMTP โดยอ่านค่าตั้งค่าจาก config.json (ดู config.example.json)"""
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def build_body(new_items):
    lines = [f"พบประกาศทุนใหม่จาก NRIIS จำนวน {len(new_items)} รายการ", ""]
    for it in new_items:
        lines.append(f"• {it['title']}")
        lines.append(f"  ลิงก์: {it['link']}")
        if it["author"]:
            lines.append(f"  หน่วยงาน: {it['author']}")
        lines.append("")
    return "\n".join(lines)


def send_new_items_email(new_items, config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    msg = MIMEMultipart()
    msg["Subject"] = f"[FundRadar] พบทุนใหม่ {len(new_items)} รายการ"
    msg["From"] = cfg["from_addr"]
    msg["To"] = cfg["to_addr"]
    msg.attach(MIMEText(build_body(new_items), "plain", "utf-8"))

    with smtplib.SMTP(cfg["smtp_host"], cfg.get("smtp_port", 587), timeout=20) as server:
        if cfg.get("use_tls", True):
            server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["from_addr"], [cfg["to_addr"]], msg.as_string())
