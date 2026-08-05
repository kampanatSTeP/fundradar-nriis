#!/usr/bin/env python3
"""
สร้างแดชบอร์ด FundRadar (dashboard/fundradar_dashboard.html) จากข้อมูล RSS ปัจจุบัน
รันสคริปต์นี้เมื่อต้องการรีเฟรชหน้าแดชบอร์ดให้ตรงกับทุนล่าสุด:
    python3 build_dashboard.py
"""
import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone

import fundradar

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "dashboard", "template.html")
OUTPUT_PATH = os.path.join(BASE_DIR, "dashboard", "fundradar_dashboard.html")
FONTS_DIR = os.path.join(BASE_DIR, "dashboard", "fonts")
EXTRACTED_PATH = os.path.join(BASE_DIR, "data", "extracted.json")

THAI_MONTHS_FULL = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}
THAI_MONTHS_ABBR = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
MONTH_ALT = "|".join(THAI_MONTHS_FULL.keys())

# เชื่อถือได้เฉพาะป้ายกำกับที่ชัดเจนไม่กำกวมเท่านั้น ("วันปิดรับ" ตามด้วยวันที่)
# หลีกเลี่ยงคำว่า "ปิดรับ" เฉย ๆ เพราะเป็นส่วนหนึ่งของคำว่า "เปิดรับ" (วันเปิดรับ) ทำให้ match ผิดวันที่
STRICT_DEADLINE_RE = re.compile(rf"วันปิดรับ\D{{0,10}}?(\d{{1,2}})\s*({MONTH_ALT})\s*(\d{{4}})")

# ใช้เป็น fallback เท่านั้น สำหรับรายการที่ยังไม่ผ่านการสกัดข้อมูลแบบมีโครงสร้าง (data/extracted.json)
# เช่น ประกาศใหม่ที่เพิ่งเข้ามาหลังรัน extraction ครั้งล่าสุด
TYPE_RULES = [
    ("ประกาศผล", [r"ประกาศผล", r"ผลการพิจารณา", r"ผลการคัดเลือก"]),
    ("รางวัล", [r"รางวัล"]),
    ("รับฟังความเห็น", [r"ประชาพิจารณ์", r"รับฟังความคิดเห็น"]),
    ("กิจกรรม/สัมมนา", [r"ขอเชิญ.*(ประชุม|งาน|สัมมนา|เสวนา|forum|symposium)", r"เข้าร่วมกิจกรรม"]),
    ("ทุนวิจัย", [r"เปิดรับข้อเสนอ", r"ประกาศรับข้อเสนอ", r"ทุนอุดหนุน", r"ทุนวิจัย", r"รับสมัครทุน"]),
]

def classify(patterns, text):
    for label, pats in patterns:
        for p in pats:
            if re.search(p, text, re.IGNORECASE):
                return label
    return None


def extract_deadline(desc, now):
    m = STRICT_DEADLINE_RE.search(desc)
    if not m:
        return None
    day, month_name, byear = m.groups()
    try:
        dt = datetime(int(byear) - 543, THAI_MONTHS_FULL[month_name], int(day), 16, 30, tzinfo=now.tzinfo)
    except ValueError:
        return None
    days_left = (dt.date() - now.date()).days
    return {
        "display": f"{int(day)} {THAI_MONTHS_ABBR[THAI_MONTHS_FULL[month_name]]} {byear}",
        "iso": dt.isoformat(),
        "days_left": days_left,
    }


def fmt_pub_date(pubdate):
    try:
        dt = datetime.strptime(pubdate, "%a, %d %b %Y %H:%M:%S %Z")
    except ValueError:
        return {"display": pubdate, "iso": "", "dt": None}
    be_year = dt.year + 543
    return {"display": f"{dt.day} {THAI_MONTHS_ABBR[dt.month]} {be_year}", "iso": dt.isoformat(), "dt": dt}


def short_agency(author):
    author = author.strip()
    if not author:
        return "ไม่ระบุ"
    m = re.match(r"^([ก-๙A-Za-z]+\.)", author)
    if m and len(m.group(1)) <= 8:
        return m.group(1)
    m2 = re.search(r"\(([ก-๙A-Za-z.\-]{2,10})\)\s*$", author)
    if m2:
        return m2.group(1)
    return author[:12] + ("…" if len(author) > 12 else "")


def excerpt(desc, n=170):
    d = re.sub(r"\s+", " ", desc).strip()
    return d[:n] + ("…" if len(d) > n else "")


def load_extracted():
    if not os.path.exists(EXTRACTED_PATH):
        return {}
    with open(EXTRACTED_PATH, encoding="utf-8") as f:
        rows = json.load(f)
    return {row["id"]: row for row in rows}


def deadline_from_extracted(deadline_date_str, now):
    """แปลง deadline_date (YYYY-MM-DD) ที่สกัดได้จริงจากเนื้อประกาศ ให้เป็นรูปแบบแสดงผล
    รองรับกรณีที่ปิดรับไปแล้ว (days_left ติดลบ) เพราะฟีดเก็บประกาศเก่าไว้ด้วย"""
    if not deadline_date_str:
        return None
    try:
        dt = datetime.strptime(deadline_date_str, "%Y-%m-%d")
    except ValueError:
        return None
    be_year = dt.year + 543
    days_left = (dt.date() - now.date()).days
    return {
        "display": f"{dt.day} {THAI_MONTHS_ABBR[dt.month]} {be_year}",
        "iso": dt.isoformat(),
        "days_left": days_left,
    }


def build():
    now = datetime.now(timezone.utc).astimezone()
    xml_bytes = fundradar.fetch_rss()
    items = fundradar.parse_items(xml_bytes)
    seen = fundradar.load_seen()
    extracted = load_extracted()

    records = []
    for it in items:
        pub = fmt_pub_date(it["pubdate"])
        ex = extracted.get(it["id"])

        if ex:
            ann_type = ex.get("announcement_type") or "ประกาศทั่วไป"
            topics = [ex["category"]] if ex.get("category") else []
            deadline = deadline_from_extracted(ex.get("deadline_date"), now)
            funding_display = ex.get("funding_amount_display")
            target_group = ex.get("target_group")
            eligibility_summary = ex.get("eligibility_summary")
            objectives = ex.get("objectives") or []
        else:
            # fallback แบบ regex สำหรับประกาศใหม่ที่ยังไม่ผ่านการสกัดข้อมูลแบบมีโครงสร้าง
            ann_type = classify(TYPE_RULES, it["title"] + " " + it["description"][:200]) or "ประกาศทั่วไป"
            topics = []
            deadline = extract_deadline(it["description"], now)
            funding_display = None
            target_group = None
            eligibility_summary = None
            objectives = []

        is_new_week = bool(pub["dt"] and (now.replace(tzinfo=None) - pub["dt"]).days <= 7)

        records.append({
            "id": it["id"],
            "title": it["title"],
            "link": it["link"],
            "author": it["author"].strip() or "ไม่ระบุหน่วยงาน",
            "agency_short": short_agency(it["author"]),
            "type": ann_type,
            "topics": topics,
            "date": pub["display"],
            "date_iso": pub["iso"],
            "is_new_week": is_new_week,
            "excerpt": excerpt(it["description"]),
            "deadline": deadline,
            "funding_display": funding_display,
            "target_group": target_group,
            "eligibility_summary": eligibility_summary,
            "objectives": objectives,
            "has_details": bool(ex),
        })

    records.sort(key=lambda x: x["date_iso"], reverse=True)

    agencies = sorted(set(r["author"] for r in records))
    types = sorted(set(r["type"] for r in records))

    # หยิบทุนเด่น: มีกำหนดปิดรับที่ยืนยันได้และใกล้ที่สุดก่อน แล้วเติมด้วยประกาศล่าสุด
    with_deadline = [r for r in records if r["deadline"] and r["deadline"]["days_left"] >= 0]
    with_deadline.sort(key=lambda x: x["deadline"]["days_left"])
    featured_ids = []
    for r in with_deadline[:4]:
        featured_ids.append(r["id"])
    for r in records:
        if len(featured_ids) >= 6:
            break
        if r["id"] not in featured_ids:
            featured_ids.append(r["id"])
    featured = [r for r in records if r["id"] in featured_ids]

    # หัวข้อยอดนิยม (ของสัปดาห์นี้) นับจาก topic tags จริง
    topic_counts = {}
    for r in records:
        for t in r["topics"]:
            topic_counts[t] = topic_counts.get(t, 0) + 1
    trending = sorted(topic_counts.items(), key=lambda kv: kv[1], reverse=True)[:6]

    agency_counts = {}
    for r in records:
        agency_counts[r["author"]] = agency_counts.get(r["author"], 0) + 1
    top_agencies = sorted(agency_counts.items(), key=lambda kv: kv[1], reverse=True)[:6]

    meta = {
        "generated_at_display": f"{now.day} {THAI_MONTHS_ABBR[now.month]} {now.year + 543} เวลา {now.strftime('%H:%M')} น.",
        "total": len(records),
        "new_this_week": sum(1 for r in records if r["is_new_week"]),
        "agency_count": len(agencies),
        "deadline_soon_count": sum(1 for r in with_deadline if r["deadline"]["days_left"] <= 14),
        "next_check": "พรุ่งนี้ 08:07 น. (อัตโนมัติทุกวัน)",
        "extracted_count": sum(1 for r in records if r["has_details"]),
    }

    data = {
        "items": records,
        "featured": featured,
        "agencies": agencies,
        "types": types,
        "trending": [{"label": k, "count": v} for k, v in trending],
        "top_agencies": [{"label": k, "count": v} for k, v in top_agencies],
        "meta": meta,
    }

    tpl = open(TEMPLATE_PATH, encoding="utf-8").read()
    for name, key in [
        ("sarabun-400-thai", "__FONT_400_THAI__"),
        ("sarabun-400-latin", "__FONT_400_LATIN__"),
        ("sarabun-600-thai", "__FONT_600_THAI__"),
        ("sarabun-600-latin", "__FONT_600_LATIN__"),
        ("sarabun-700-thai", "__FONT_700_THAI__"),
        ("sarabun-700-latin", "__FONT_700_LATIN__"),
    ]:
        b64 = open(os.path.join(FONTS_DIR, f"{name}.woff2.b64"), encoding="ascii").read()
        tpl = tpl.replace(key, b64)

    tpl = tpl.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(tpl)

    print(f"[build_dashboard] เขียน {OUTPUT_PATH}")
    print(f"[build_dashboard] ทั้งหมด {meta['total']} | สกัดข้อมูลแล้ว {meta['extracted_count']} | ใหม่สัปดาห์นี้ {meta['new_this_week']} | ใกล้ปิดรับ(<=14วัน) {meta['deadline_soon_count']} | หน่วยงาน {meta['agency_count']}")


if __name__ == "__main__":
    build()
