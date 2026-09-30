from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_PDFS_DIR = DATA_DIR / "raw_pdfs"
PROCESSED_DIR = DATA_DIR / "processed"
INDEXES_DIR = DATA_DIR / "indexes"

DOCS_DIR = PROJECT_ROOT / "docs"
EDA_DIR = DOCS_DIR / "eda"
REPORT_PATH = DOCS_DIR / "EDA.md"
STRUCTURE_CSV = EDA_DIR / "polizas_estructura.csv"
STRUCTURE_JSON = EDA_DIR / "polizas_estructura.json"
COBERTURA_MD = EDA_DIR / "cobertura_articulo2.md"


def ensure_data_dirs() -> None:
    for directory in (RAW_PDFS_DIR, PROCESSED_DIR, INDEXES_DIR):
        directory.mkdir(parents=True, exist_ok=True)