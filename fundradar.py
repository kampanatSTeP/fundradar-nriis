#!/usr/bin/env python3
"""
FundRadar (ทุนเรดาร์) — ติดตามประกาศทุนวิจัย/นวัตกรรมใหม่จาก NRIIS
แหล่งข้อมูล: https://nriis.go.th/rss.aspx

การทำงาน:
  1. ดึง RSS feed
  2. เทียบกับรายการที่เคยเห็นแล้ว (data/seen.json) เพื่อหาประกาศใหม่
  3. ถ้ามีของใหม่ -> เขียนรายงาน (reports/YYYY-MM-DD.md) และส่งอีเมลแจ้งเตือน (ถ้าตั้งค่า config.json ไว้)
  4. รันครั้งแรกจะไม่แจ้งเตือน (ใช้เป็น baseline) เพื่อไม่ให้ล้นด้วยประกาศเก่าที่มีอยู่แล้ว
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_PATH = os.path.join(BASE_DIR, "data", "seen.json")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
RSS_URL = "https://nriis.go.th/rss.aspx"


def fetch_rss(url=RSS_URL, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "FundRadar/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_items(xml_bytes):
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.findall("./channel/item"):
        def text(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        link = text("link")
        nid_match = re.search(r"nid=(\d+)", link)
        item_id = nid_match.group(1) if nid_match else link

        items.append({
            "id": item_id,
            "title": text("title"),
            "link": link,
            "author": text("author"),
            "pmu": text("pmu"),
            "pubdate": text("pubdate"),
            "description": text("description"),
        })
    return items


def load_seen():
    if not os.path.exists(SEEN_PATH):
        return {}
    with open(SEEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def write_report(new_items):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(REPORTS_DIR, f"{today}.md")

    lines = [f"# ทุนใหม่จาก NRIIS — {today}", ""]
    for it in new_items:
        lines.append(f"## {it['title']}")
        lines.append(f"- ลิงก์: {it['link']}")
        if it["author"]:
            lines.append(f"- หน่วยงาน: {it['author']}")
        if it["pubdate"]:
            lines.append(f"- วันที่ประกาศ: {it['pubdate']}")
        desc = it["description"]
        if desc:
            snippet = desc[:400] + ("..." if len(desc) > 400 else "")
            lines.append(f"- รายละเอียดโดยย่อ: {snippet}")
        lines.append("")

    # append to today's file if run multiple times per day
    mode = "a" if os.path.exists(path) else "w"
    with open(path, mode, encoding="utf-8") as f:
        if mode == "a":
            f.write("\n---\n\n")
        f.write("\n".join(lines))
    return path


def notify_macos(new_items):
    title = "FundRadar - พบทุนใหม่"
    if len(new_items) == 1:
        message = new_items[0]["title"]
    else:
        message = f"พบทุนใหม่ {len(new_items)} รายการ ดูรายละเอียดในโฟลเดอร์ reports/"
    # ผ่านค่าด้วย argv แทนการต่อสตริงเข้า AppleScript โดยตรง เพื่อกัน injection
    script = 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run'
    try:
        subprocess.run(
            ["osascript", "-e", script, title, message],
            check=False, timeout=10,
        )
    except FileNotFoundError:
        pass  # ไม่ใช่ macOS หรือไม่มี osascript


def main():
    report_all = "--report-all" in sys.argv

    try:
        xml_bytes = fetch_rss()
    except Exception as e:
        print(f"[FundRadar] ดึง RSS ไม่สำเร็จ: {e}", file=sys.stderr)
        sys.exit(1)

    items = parse_items(xml_bytes)
    seen = load_seen()
    is_first_run = len(seen) == 0

    new_items = [it for it in items if it["id"] not in seen]

    now_iso = datetime.now(timezone.utc).isoformat()
    for it in items:
        if it["id"] not in seen:
            seen[it["id"]] = {"title": it["title"], "first_seen": now_iso}
    save_seen(seen)

    if is_first_run and not report_all:
        print(f"[FundRadar] รันครั้งแรก: บันทึก baseline {len(items)} รายการ (ยังไม่แจ้งเตือน)")
        return

    if not new_items:
        print("[FundRadar] ไม่มีประกาศทุนใหม่")
        return

    report_path = write_report(new_items)
    print(f"[FundRadar] พบทุนใหม่ {len(new_items)} รายการ -> {report_path}")
    for it in new_items:
        print(f"  - {it['title']} ({it['link']})")
    notify_macos(new_items)

    # ส่งอีเมลถ้ามีการตั้งค่าไว้
    config_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(config_path):
        try:
            from emailer import send_new_items_email
            send_new_items_email(new_items, config_path)
            print("[FundRadar] ส่งอีเมลแจ้งเตือนแล้ว")
        except Exception as e:
            print(f"[FundRadar] ส่งอีเมลไม่สำเร็จ: {e}", file=sys.stderr)
    else:
        print("[FundRadar] ยังไม่ได้ตั้งค่าอีเมล (config.json) — ดูรายละเอียดที่ไฟล์รายงานแทน")


if __name__ == "__main__":
    main()
