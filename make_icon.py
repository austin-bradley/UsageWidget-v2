"""Generate icon.ico: the static app icon, in the same visual style as the
live tray icon (dark rounded square, colored glyph)."""
from PIL import Image, ImageDraw, ImageFont

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((6, 6, SIZE - 6, SIZE - 6), radius=52, fill=(30, 30, 30, 255))

text = "%"
font = None
for path in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
    try:
        font = ImageFont.truetype(path, 150)
        break
    except Exception:
        continue
if font is None:
    font = ImageFont.load_default()

color = (110, 200, 120, 255)
bbox = d.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
x = (SIZE - tw) / 2 - bbox[0]
y = (SIZE - th) / 2 - bbox[1]
d.text((x, y), text, font=font, fill=color)

img.save(
    r"C:\Users\austi\ClaudeUsageWidget\icon.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("wrote icon.ico")
