import sys, pdfplumber

src = sys.argv[1]
dst = sys.argv[2]
with pdfplumber.open(src) as pdf:
    print("pages:", len(pdf.pages))
    parts = []
    for i, pg in enumerate(pdf.pages):
        t = pg.extract_text() or ""
        parts.append("\n===== PAGE %d =====\n" % (i + 1) + t)
    with open(dst, "w") as f:
        f.write("".join(parts))
