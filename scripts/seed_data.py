from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
from fpdf import FPDF
from PIL import Image, ImageDraw

from config import config


def generate_synthetic_ledger(output_path: Path = config.LEDGER_FILE, rows: int = 200) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    roles = ["Account Executive", "Engineer", "Product Manager", "Operations"]
    merchants = [
        ("Sweetgreen", "MEALS", 24.0, 7.0),
        ("Blue Bottle Coffee", "MEALS", 15.0, 5.0),
        ("Uber Ride", "TRAVEL", 28.0, 10.0),
        ("Delta Airlines", "TRAVEL", 340.0, 80.0),
        ("Figma", "SOFTWARE", 45.0, 10.0),
    ]
    start = datetime(2026, 10, 1, 9, 0)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "txn_id", "employee_id", "role", "merchant", "category",
            "amount_usd", "hour_of_day", "is_weekend", "timestamp"
        ])
        for idx in range(rows):
            emp_id = f"E{rng.randint(101, 120)}"
            role = rng.choice(roles)
            merchant, cat, mean_amt, std_amt = rng.choice(merchants)
            amt = round(max(5.0, rng.gauss(mean_amt, std_amt)), 2)
            ts = start + timedelta(hours=rng.randint(0, 900))
            if ts.weekday() >= 5:
                ts -= timedelta(days=2)
            hour = rng.randint(8, 20)
            ts = ts.replace(hour=hour, minute=rng.randint(0, 59))
            writer.writerow([
                f"HIST-{1000+idx}", emp_id, role, merchant, cat,
                amt, hour, 0, ts.isoformat()
            ])
    print(f"Wrote {rows} rows to {output_path}")


def _save_png(path: Path, lines: list[str]) -> None:
    img = Image.new("RGB", (540, 48 + len(lines) * 26), color=(252, 251, 248))
    draw = ImageDraw.Draw(img)
    y = 20
    for line in lines:
        draw.text((24, y), line, fill=(25, 28, 34))
        y += 26
    img.save(path)
    print(f"Created {path}")


def _save_pdf(path: Path, lines: list[str]) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", size=11)
    for line in lines:
        pdf.cell(0, 8, text=line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))
    print(f"Created {path}")


def generate_sample_receipts(out_dir: Path = config.SAMPLES_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    _save_png(out_dir / "01_clean_us_lunch.png", [
        "SWEETGREEN - NEW YORK, NY",
        "Date: 2026-11-18 | Employee: E104",
        "----------------------------------------",
        "1x Harvest Bowl                  $16.50",
        "1x Green Goddess Salad            $8.00",
        "Subtotal:                        $24.50",
        "Tax:                              $2.18",
        "Tip:                              $4.00",
        "TOTAL (USD):                     $30.68",
    ])

    _save_pdf(out_dir / "02_uk_dinner_alcohol.pdf", [
        "THE IVY SOHO BRASSERIE - LONDON, UK",
        "Date: 2026-11-18 | Employee: E109",
        "----------------------------------------",
        "1x Sirloin Steak              GBP 44.00",
        "1x Roasted Potatoes           GBP 10.00",
        "2x Negroni Cocktail           GBP 38.00",
        "Subtotal:                     GBP 92.00",
        "VAT:                          GBP 18.40",
        "Service / Tip:                GBP 11.50",
        "TOTAL (GBP):                 GBP 121.90",
    ])

    _save_png(out_dir / "03_split_part_a.png", [
        "BLUE BOTTLE COFFEE - SAN FRANCISCO, CA",
        "Date: 2026-11-19 | Employee: E102",
        "----------------------------------------",
        "3x Oat Cortado                   $18.00",
        "4x Morning Bun                   $24.00",
        "Subtotal:                        $42.00",
        "Tax:                              $3.73",
        "TOTAL (USD):                     $45.73",
    ])

    _save_png(out_dir / "03_split_part_b.png", [
        "BLUE BOTTLE COFFEE - SAN FRANCISCO, CA",
        "Date: 2026-11-19 | Employee: E102",
        "----------------------------------------",
        "3x Cold Brew                     $19.50",
        "2x Avocado Toast                 $22.00",
        "Subtotal:                        $41.50",
        "Tax:                              $3.68",
        "TOTAL (USD):                     $45.18",
    ])

    _save_png(out_dir / "04_math_mismatch.png", [
        "LOCAL BISTRO - CHICAGO, IL",
        "Date: 2026-11-19 | Employee: E107",
        "----------------------------------------",
        "Subtotal:                        $50.00",
        "Tax:                              $4.00",
        "Tip:                              $6.00",
        "TOTAL (USD):                     $72.00",
    ])


if __name__ == "__main__":
    generate_synthetic_ledger()
    generate_sample_receipts()