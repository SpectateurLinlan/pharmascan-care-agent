"""Generate synthetic inputs only; no provider calls or fake recognition results."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


def generate(directory: Path, start: date) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except OSError:
        font = ImageFont.load_default(size=32)
    for name, strength, label in (("package", 500, False), ("label", 500, True), ("conflict", 1000, True)):
        image = Image.new("RGB", (1100, 550), "white")
        lines = ["DEMO ONLY - synthetic medicine", f"Metformin {strength} mg", "Extended Release Tablets"]
        if label:
            lines += ["Take 1 tablet at 20:00 every day with food.", f"For 7 days. Start {start.isoformat()}."]
        ImageDraw.Draw(image).multiline_text((35, 35), "\n".join(lines), fill="black", font=font, spacing=20)
        image.save(directory / f"{name}.png")
    pill = Image.new("RGB", (384, 384), "white")
    draw = ImageDraw.Draw(pill)
    draw.ellipse((110, 140, 275, 245), fill="#e0e0db", outline="#60605d", width=3)
    draw.line((145, 190, 240, 190), fill="#777777", width=2)
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
    args = parser.parse_args()
    generate(Path(__file__).resolve().parents[1] / "outputs" / "gallery-demo", args.start_date)
