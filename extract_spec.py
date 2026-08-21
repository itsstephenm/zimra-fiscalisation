"""Extract CloseDay hash specification from the downloaded ZIMRA PDF."""
import sys

pdf_path = r'C:\Users\Stephen J Muregwi\.gemini\antigravity\brain\470af931-687c-499a-8741-bb11626d0d9b\.tempmediaStorage\12185aab903373ec.pdf'

try:
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        hits = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ''
            # Look for pages that have both fiscal day signature content
            if any(kw in text for kw in ['fiscalDayCounters', 'fiscalDayDate', '13.3', 'CloseDay', 'fiscal day sign']):
                hits.append((i+1, text))
        
        print(f"Found {len(hits)} relevant pages")
        with open("spec_output.txt", "w", encoding="utf-8") as f:
            for page_no, text in hits:
                f.write(f"\n{'='*70}\n")
                f.write(f"PAGE {page_no}\n")
                f.write('='*70 + '\n')
                f.write(text + '\n')

except ImportError:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        hits = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ''
            if any(kw in text for kw in ['fiscalDayCounters', 'fiscalDayDate', '13.3', 'CloseDay']):
                hits.append((i+1, text))
        print(f"Found {len(hits)} relevant pages via PyPDF2")
        for page_no, text in hits[:8]:
            print(f"\n{'='*70}")
            print(f"PAGE {page_no}")
            print('='*70)
            print(text[:3000])
    except ImportError:
        print("No PDF library available. Install pdfplumber: pip install pdfplumber")
        sys.exit(1)
