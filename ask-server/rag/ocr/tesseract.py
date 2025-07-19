import importlib.util
import shutil
import pytesseract
import fitz  # PyMuPDF
from PIL import Image
import io
import sys
import os

# Check if pytesseract is installed
def is_pytesseract_installed():
    return importlib.util.find_spec("pytesseract") is not None

# Check if the Tesseract binary is in the system path
def is_tesseract_installed():
    return shutil.which("tesseract") is not None

def is_tesseract():
    # Combined check
    if is_pytesseract_installed():
        print("✅ pytesseract is installed.")
        
        if is_tesseract_installed():
            print("✅ Tesseract is installed and accessible.")
            print(f"pytesseract uses: {pytesseract.pytesseract.tesseract_cmd}")
            return True
        else:
            print("❌ Tesseract binary not found in system PATH.")
            print("You may need to install it or configure `pytesseract.pytesseract.tesseract_cmd` manually.")
    else:
        print("❌ pytesseract is NOT installed.")
    return False

def extract_text_from_pdf(pdf_path, dpi=300):
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        return

    try:
        doc = fitz.open(pdf_path)
        print(f"Processing {len(doc)} pages...")

        for page_num, page in enumerate(doc, start=1):
            string_buffer = ""
            string_buffer += (f"\n--- Page {page_num} ---")
            # Render page to image
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))

            # OCR with pytesseract
            text = pytesseract.image_to_string(img)
            string_buffer += text.strip()
            return string_buffer
    except Exception as e:
        print(f"Could not parse text due to {e}")
        return ""
