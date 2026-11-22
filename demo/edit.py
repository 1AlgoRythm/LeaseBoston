"""Cut the raw recording into the final demo video.

For each scenario in steps.json: a 3-second title card, then the clip. Long clips
are sped up (Claude thinking, pages loading) so each scenario lasts at most
MAX_SECONDS; a small "sped up Nx" note is put on the title card when that happens.
Run: uv run --with pillow python edit.py
"""
import json, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "out"
W, H, FPS, MAX_SECONDS = 1512, 950, 30, 40  # step times are from T0, which starts 2 s into raw.mov
FONT = "/System/Library/Fonts/SFNS.ttf"

SUBTITLES = {
    "1": "The renter asks Claude. LeaseBoston's MCP server returns ranked listings, drawn as cards in the chat.",
    "2": "\"Ask the landlord\" on a card. The landlord already answered this, so the saved answer comes back word for word.",
    "3": "No saved answer yet. The renter sends it to the landlord from the card, and picks how to hear back.",
    "4": "The renter decides not to send this one. Nothing goes out, but the landlord still sees the demand.",
    "5": "The landlord's page: questions arrive, the landlord replies, and saves an answer for next time.",
    "6": "Back in Claude: the landlord's reply reaches the renter.",
    "7": "The next renter asks the same thing and gets the landlord's new answer instantly.",
}


def card(path, title, sub, note=""):
    img = Image.new("RGB", (W, H), (24, 24, 24))
    d = ImageDraw.Draw(img)
    big, mid, small = ImageFont.truetype(FONT, 46), ImageFont.truetype(FONT, 26), ImageFont.truetype(FONT, 20)
    d.text((W // 2, H // 2 - 70), title, font=big, fill=(240, 240, 240), anchor="mm")
    words, lines, line = sub.split(), [], ""
    for w_ in words:
        if d.textlength(line + " " + w_, font=mid) > W - 300:
            lines.append(line); line = w_
        else:
            line = (line + " " + w_).strip()
    lines.append(line)
    for i, l in enumerate(lines):
        d.text((W // 2, H // 2 + 10 + i * 38), l, font=mid, fill=(185, 185, 185), anchor="mm")
    foot = "LeaseBoston · MCP demo in Claude Desktop · synthetic data" + (f" · {note}" if note else "")
    d.text((W // 2, H - 60), foot, font=small, fill=(120, 120, 120), anchor="mm")
    img.save(path)


def run(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


steps = json.loads((OUT / "steps.json").read_text())
parts = []
card(OUT / "c_intro.png", "LeaseBoston, inside Claude",
     "A renter searches and asks landlords in the chat. Landlords answer once; the answer is reused. Recorded live on a Mac.")
run("-loop", "1", "-t", "4", "-i", str(OUT / "c_intro.png"), "-vf", f"scale={W}:{H},fps={FPS},format=yuv420p",
    "-c:v", "libx264", "-preset", "veryfast", str(OUT / "p_intro.mp4"))
parts.append(OUT / "p_intro.mp4")

for i, s in enumerate(steps):
    if "end" not in s:
        continue
    n = s["label"].split(".")[0]
    dur = s["end"] - s["start"]
    speed = max(1.0, dur / MAX_SECONDS)
    note = f"sped up {speed:.1f}x" if speed > 1.05 else ""
    card(OUT / f"c_{i}.png", s["label"], SUBTITLES.get(n, ""), note)
    run("-loop", "1", "-t", "3.5", "-i", str(OUT / f"c_{i}.png"), "-vf", f"scale={W}:{H},fps={FPS},format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", str(OUT / f"p_card_{i}.mp4"))
    run("-ss", str(s["start"] + 2.0), "-t", str(dur), "-i", str(OUT / s.get("file", "raw.mov")),
        "-vf", f"setpts=PTS/{speed},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(OUT / f"p_clip_{i}.mp4"))
    parts += [OUT / f"p_card_{i}.mp4", OUT / f"p_clip_{i}.mp4"]

(OUT / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
run("-f", "concat", "-safe", "0", "-i", str(OUT / "list.txt"), "-c", "copy", str(OUT / "leaseboston-demo.mp4"))
print("wrote", OUT / "leaseboston-demo.mp4")
