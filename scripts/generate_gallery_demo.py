"""Generate synthetic inputs only; no provider calls or fake recognition results."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


def generate(directory: Path, start: date, *, sticker_v010: bool = False) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 36 if sticker_v010 else 32)
    except OSError:
        font = ImageFont.load_default(size=32)
    for name, strength, label in (("package", 500, False), ("label", 500, True), ("conflict", 1000, True)):
        image = Image.new("RGB", (1400, 650) if sticker_v010 else (1100, 550), "white")
        lines = ["DEMO ONLY - synthetic medicine", f"Metformin {strength} mg", "Extended Release Tablets"]
        if label:
            lines += ["Take 1 tablet at 20:00 every day with food.", f"For 7 days. Start {start.isoformat()}."]
        if sticker_v010:
            heading = "DEMO ONLY - SYNTHETIC PHARMACY LABEL" if label else "DEMO ONLY - SYNTHETIC BOX"
            lines = [heading, f"METFORMIN {strength} mg EXTENDED RELEASE"]
            if name == "label":
                lines.insert(1, "DEMO Singapore Pharmacy")
                lines += [
                    "Take ONE tablet TWICE a day AFTER FOOD for 7 days.",
                    "Swallow whole.",
                    "Quantity: 14 tablets",
                ]
            elif name == "conflict":
                lines += ["Take ONE tablet daily AFTER FOOD."]
            else:
                lines += ["TABLETS", "Product information only"]
            for index, line in enumerate(lines):
                ImageDraw.Draw(image).text((35, 30 + index * 85), line, fill="black", font=font)
        else:
            ImageDraw.Draw(image).multiline_text((35, 35), "\n".join(lines), fill="black", font=font, spacing=20)
        image.save(directory / f"{name}.png")
    pill = Image.new("RGB", (384, 384), "white")
    draw = ImageDraw.Draw(pill)
    draw.ellipse(
        (95, 140, 285, 245) if sticker_v010 else (110, 140, 275, 245),
        fill="#dededb" if sticker_v010 else "#e0e0db",
        outline="#60605d",
        width=3,
    )
    draw.line((120, 192, 255, 192) if sticker_v010 else (145, 190, 240, 190), fill="#777777", width=2)
    pill.save(directory / "pill.png")
    (directory / "fixture-course.json").write_text(
        json.dumps(
            {
                "demo_only": True,
                "start": start.isoformat(),
                "end": (start + timedelta(days=6)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    print("Synthetic gallery inputs generated; no external service invoked.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--start-date", type=date.fromisoformat, default=datetime.now(ZoneInfo("Asia/Singapore")).date()
    )
    parser.add_argument("--stage2-v010", action="store_true", help="Generate Singapore sticker upgrade fixtures")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[1] / "outputs"
    directory = directory / "stage2-v010/demo" if args.stage2_v010 else directory / "gallery-demo"
    generate(directory, args.start_date, sticker_v010=args.stage2_v010)
