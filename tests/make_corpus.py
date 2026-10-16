"""Build a small fake corpus for testing local-file-kit.

Everything here is made-up sample data (recipes, travel notes, hobby notes).
Usage:  python tests/make_corpus.py <empty-or-new-folder>
Pillow is optional; without it the image files are skipped.
"""
import json
import os
import random
import sys
import zipfile
from pathlib import Path

NOTES = {
    "레시피 모음/김치찌개.txt": "김치찌개 만드는 법\n돼지고기를 먼저 볶고 잘 익은 김치를 넣는다. 물을 붓고 20분 끓인 뒤 두부와 대파를 넣는다.\n",
    "레시피 모음/된장국.md": "# 된장국\n멸치 육수에 된장을 풀고 애호박, 감자, 양파를 넣어 끓인다. 마지막에 청양고추를 넣으면 칼칼하다.\n",
    "레시피 모음/pancakes.txt": "Fluffy pancakes\nWhisk flour, sugar, baking powder and salt. Add milk, eggs and melted butter. Cook on a hot griddle until bubbles form, then flip.\n",
    "Work Docs/meeting notes 2024-03.md": "# Weekly sync\n- Budget review moved to Friday\n- The vendor contract renewal is due next month\n- Action: draft the onboarding checklist\n",
    "Work Docs/분기 보고서 초안.txt": "1분기 매출은 전년 대비 12% 늘었다. 신규 고객 확보가 주된 이유이며, 물류 비용은 줄었다.\n",
    "Hobby Notes/chess openings.txt": "Chess openings to practise: the Italian Game for open positions and the Caro-Kann as a solid reply to e4.\n",
    "Hobby Notes/뜨개질 시작.txt": "처음 뜨개질은 굵은 실과 대바늘로 목도리부터 시작한다. 겉뜨기만 반복해도 무늬가 생긴다.\n",
    "여행 사진 2024/여행 메모.txt": "바닷가 마을 3일 여행. 첫날 등대 구경, 둘째 날 해안 자전거, 셋째 날 언덕 산책.\n",
}

DUP_TEXT = "This file is duplicated on purpose for the duplicate finder test.\n"


def docx(path, paragraphs):
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body>{body}</w:body></w:document>")


def pdf(path, lines):
    # A minimal one-page PDF with Helvetica text (ASCII only).
    text = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    Path(path).write_bytes(out)


def _scene(kind, size=(320, 240)):
    from PIL import Image, ImageDraw
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    if kind == "sea":
        for y in range(h // 2):  # sky gradient
            d.line([(0, y), (w, y)], fill=(120 + y // 2, 170 + y // 3, 235))
        for y in range(h // 2, h):  # sea
            d.line([(0, y), (w, y)], fill=(20, 70 + (y - h // 2) // 2, 150 - (y - h // 2) // 3))
        d.ellipse([w - 90, 25, w - 40, 75], fill=(255, 220, 120))  # sun
        d.polygon([(30, h // 2), (110, 60), (190, h // 2)], fill=(90, 100, 90))  # island
        rnd = random.Random(7)
        for _ in range(400):  # waves
            x, y = rnd.randrange(w), rnd.randrange(h // 2, h)
            d.line([(x, y), (x + rnd.randrange(5, 25), y)], fill=(200, 220, 240))
    else:  # forest: vertical trunks on green
        d.rectangle([0, 0, w, h], fill=(40, 120, 50))
        for x in range(10, w, 40):
            d.rectangle([x, 30, x + 12, h], fill=(90, 60, 30))
            d.ellipse([x - 20, 0, x + 32, 70], fill=(20, 90, 30))
    return img


def images(root):
    try:
        from PIL import Image, ImageEnhance
    except ImportError:
        print("Pillow not installed: image files skipped", file=sys.stderr)
        return 0
    folder = root / "여행 사진 2024"
    sea = _scene("sea")
    edited = ImageEnhance.Brightness(sea).enhance(1.08).resize((300, 225))  # same scene, slightly edited
    made = 0
    for name, img, when, model in [
        ("바다 풍경.jpg", sea, "2024:05:03 09:12:00", "Sample Camera A"),
        ("바다 풍경 (보정).jpg", edited, "2024:05:03 09:12:00", "Sample Camera A"),
        ("forest walk.jpg", _scene("forest"), "2024:05:04 15:40:10", "Sample Phone B"),
    ]:
        exif = Image.Exif()
        exif[271] = "SampleMaker"      # Make
        exif[272] = model              # Model
        exif[306] = when               # DateTime
        img.save(folder / name, "JPEG", quality=90, exif=exif.tobytes())
        made += 1
    return made


def build(root):
    """Write the sample files under root (must be empty or missing). Returns (file count, images made)."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"{root} is not empty")
    for rel, text in NOTES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    docx(root / "Work Docs" / "project plan.docx",
         ["Project plan", "Phase 1: collect requirements from the sales team.", "Phase 2: build the prototype and test it with five customers."])
    pdf(root / "Work Docs" / "travel policy.pdf",
        ["Travel policy", "Economy class for flights under six hours.", "Hotel receipts must be submitted within 30 days."])
    dup = root / "중복 테스트"
    (dup / "a").mkdir(parents=True)
    (dup / "b c").mkdir(parents=True)
    for p in (dup / "a" / "copy1.txt", dup / "b c" / "copy 2.txt", root / "Hobby Notes" / "copy3.txt"):
        p.write_text(DUP_TEXT, encoding="utf-8")
    (root / "빈 폴더" / "안쪽 빈 폴더").mkdir(parents=True)
    (root / "Work Docs" / "empty.txt").write_bytes(b"")
    with open(root / "Work Docs" / "big_backup.bin", "wb") as f:
        f.truncate(6 * 1024 * 1024)
    made = images(root)
    return sum(1 for _ in root.rglob("*") if _.is_file()), made


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        count, made = build(sys.argv[1])
    except ValueError as e:
        print(f"refusing: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"root": sys.argv[1], "files": count, "images": made}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
