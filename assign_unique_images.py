from pathlib import Path
import hashlib, math, re

ROOT = Path(__file__).resolve().parent
CATEGORIES = {"rings", "necklaces", "earrings", "bracelets", "bangles", "chains", "pendants", "anklets"}

def make_svg(category: str, sku: str, title: str) -> str:
    h = hashlib.sha256(f"{category}|{sku}|{title}".encode("utf-8")).digest()
    golds = ["#C69A45", "#D8B56B", "#B88735", "#E0C27A", "#A9782D", "#D4AF37"]
    stones = ["#6C8FAE", "#9B4D62", "#5E8C72", "#7663A8", "#D58B45", "#5A9C9A", "#B8A0C8"]
    gold, stone = golds[h[0] % len(golds)], stones[h[1] % len(stones)]
    accent = golds[h[2] % len(golds)]
    width, gem = 8 + h[3] % 6, 17 + h[4] % 17
    tilt = int(h[5] % 25) - 12
    cx, cy = 300 + int(h[6] % 21) - 10, 300 + int(h[7] % 17) - 8
    gem_svg = f'<path d="M {cx} {cy-gem} L {cx+gem} {cy} L {cx} {cy+gem} L {cx-gem} {cy} Z" fill="url(#gem)" stroke="#fff" stroke-width="3"/>'
    if category == "rings":
        design = f'<ellipse cx="300" cy="330" rx="{104+h[8]%28}" ry="{68+h[9]%18}" fill="none" stroke="url(#metal)" stroke-width="{width+7}"/><path d="M 300 250 L 300 225" stroke="url(#metal)" stroke-width="12"/>{gem_svg}'
    elif category in ("necklaces", "chains"):
        design = f'<path d="M 125 145 Q 145 430 300 455 Q 455 430 475 145" fill="none" stroke="url(#metal)" stroke-width="{width+2}" stroke-linecap="round"/><path d="M 300 455 L 300 480" stroke="url(#metal)" stroke-width="10"/>{gem_svg}'
        if category == "chains":
            design += "".join(f'<ellipse cx="{155+i*29}" cy="{190+(i%3)*16}" rx="12" ry="6" transform="rotate(35 {155+i*29} {190+(i%3)*16})" fill="none" stroke="{accent}" stroke-width="4"/>' for i in range(10))
    elif category == "earrings":
        design = f'<path d="M 205 175 C 145 235 160 380 230 410 C 300 440 315 320 260 255 M 395 175 C 455 235 440 380 370 410 C 300 440 285 320 340 255" fill="none" stroke="url(#metal)" stroke-width="{width+5}"/><circle cx="230" cy="420" r="{gem}" fill="url(#gem)"/><circle cx="370" cy="420" r="{gem}" fill="url(#gem)"/>'
    elif category in ("bracelets", "bangles", "anklets"):
        ry = 75 if category == "bangles" else 88
        design = f'<ellipse cx="300" cy="315" rx="150" ry="{ry}" fill="none" stroke="url(#metal)" stroke-width="{width+7}"/><ellipse cx="300" cy="315" rx="137" ry="{ry-13}" fill="none" stroke="#fff0c0" stroke-width="3"/>{gem_svg}'
        for i in range(7):
            a = i * math.pi / 3.5 + h[10] / 80
            x, y = 300+150*math.cos(a), 315+ry*math.sin(a)
            design += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5+h[11]%5}" fill="{accent}"/>'
    else:
        design = f'<path d="M 300 115 L 300 205" stroke="url(#metal)" stroke-width="10"/><path d="M 300 205 C 220 260 220 370 300 425 C 380 370 380 260 300 205 Z" fill="none" stroke="url(#metal)" stroke-width="{width+4}"/>{gem_svg}'
    sparkle = "".join(f'<circle cx="{70+(h[(i+12)%32]*7)%460}" cy="{80+(h[(i+18)%32]*5)%390}" r="{2+h[(i+20)%32]%4}" fill="{gold}" opacity=".3"/>' for i in range(10))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#FCFAF5"/><stop offset="1" stop-color="#E9E0D0"/></linearGradient>
<linearGradient id="metal" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#FFF1BD"/><stop offset=".38" stop-color="{gold}"/><stop offset=".72" stop-color="#8B6229"/><stop offset="1" stop-color="#F3D68A"/></linearGradient>
<radialGradient id="gem" cx=".3" cy=".22"><stop stop-color="#fff"/><stop offset=".3" stop-color="{stone}"/><stop offset="1" stop-color="#253247"/></radialGradient>
<filter id="shadow"><feGaussianBlur stdDeviation="10"/></filter>
</defs>
<rect width="600" height="600" rx="28" fill="url(#bg)"/>{sparkle}
<ellipse cx="300" cy="470" rx="170" ry="20" fill="#655239" opacity=".15" filter="url(#shadow)"/>
<g transform="rotate({tilt} 300 300)">{design}</g>
<path d="M 45 48 H 555" stroke="{gold}" opacity=".3"/>
<text x="300" y="535" text-anchor="middle" font-family="Georgia,serif" font-size="18" letter-spacing="4" fill="#725B36">PJ ATELIER</text>
<text x="300" y="565" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" letter-spacing="2" fill="#8A7B62">{sku}</text>
</svg>'''


def assign_unique_product_images():
    from app.main import SessionLocal, Product, Category
    from sqlalchemy import select

    preserved_photos = 0
    generated_svgs = 0

    with SessionLocal() as db:
        categories = {
            c.id: c.name.lower()
            for c in db.scalars(select(Category)).all()
        }

        products = db.scalars(
            select(Product).order_by(Product.id)
        ).all()

        counts = {name: 0 for name in CATEGORIES}

        for product in products:
            category = categories.get(product.category_id, "")
            if category in counts:
                counts[category] += 1

        if len(categories) != 8 or any(
            counts[name] != 100 for name in CATEGORIES
        ):
            raise RuntimeError(
                f"Catalogue verification failed. "
                f"Categories={len(categories)}, counts={counts}"
            )

        for product in products:
            category = categories.get(product.category_id, "")

            if category not in CATEGORIES:
                continue

            # Preserve existing real product photographs.
            if product.image_path:
                current_image = ROOT / "uploads" / product.image_path

                if (
                    current_image.suffix.lower()
                    in {".jpg", ".jpeg", ".png", ".webp"}
                    and current_image.is_file()
                ):
                    preserved_photos += 1
                    continue

            # Generate an SVG only when a valid photograph is unavailable.
            safe_sku = re.sub(
                r"[^A-Za-z0-9_-]+", "-", product.sku
            ).strip("-")

            filename = f"{safe_sku}.svg"
            folder = ROOT / "uploads" / category
            folder.mkdir(parents=True, exist_ok=True)

            svg_path = folder / filename

            if not svg_path.exists():
                svg_path.write_text(
                    make_svg(category, product.sku, product.title),
                    encoding="utf-8"
                )

            product.image_path = f"{category}/{filename}"
            generated_svgs += 1

        db.commit()

    print(f"Real photographs preserved: {preserved_photos}")
    print(f"SVG illustrations assigned: {generated_svgs}")

    return len(products)

if __name__ == "__main__":
    print(f"Generated and assigned images for {assign_unique_product_images()} products.")
