import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import sys
import os

def extract_text_from_pdf(pdf_path, dpi=300):
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        return

    doc = fitz.open(pdf_path)
    print(f"Processing {len(doc)} pages...")

    for page_num, page in enumerate(doc, start=1):
        print(f"\n--- Page {page_num} ---")

        # Render page to image
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))

        # OCR with pytesseract
        text = pytesseract.image_to_string(img)
        print(text.strip())

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python extract_pdf_text.py <path_to_pdf>")
    else:
        extract_text_from_pdf(sys.argv[1])
