import os
import re
import fitz  # PyMuPDF
import logging
from datetime import datetime
import config

# =============================================================================
# CONFIG
# =============================================================================

INPUT_DIR  = config.RAW_DIR
OUTPUT_DIR = config.TRANSLATE_DIR
LOG_DIR    = config.LOG_DIR
LOG_FILE   = os.path.join(LOG_DIR, "TextExtractor_log.log")

# Giá trị nằm trong config.py, mục "TextExtractor.py — CONFIG"
MIN_WORD_COUNT      = config.TEXTEXTRACT_MIN_WORD_COUNT
ANOMALY_THRESHOLD   = config.TEXTEXTRACT_ANOMALY_THRESHOLD

# =============================================================================
# BOOTSTRAP
# =============================================================================

def _bootstrap():
    for d in (OUTPUT_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)

# =============================================================================
# LOGGER  — file: full detail | terminal: silent trong lúc chạy
# =============================================================================

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("TextExtractor")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)
    return logger

# =============================================================================
# PDF EXTRACTION
# =============================================================================

def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    pages = [page.get_text("text").strip() for page in doc]
    doc.close()
    return "\n\n".join(pages)


def save_text(txt_path: str, content: str):
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(content)


def count_words(text: str) -> int:
    return len(text.split())


def extract_chapter_number(filename: str):
    """Trích số chương từ tên file, vd 'Chuong_7.pdf' -> 7. None nếu không tìm thấy số nào."""
    m = re.search(r'(\d+)', filename)
    return int(m.group(1)) if m else None

# =============================================================================
# TERMINAL REPORT
# =============================================================================

def _print_report(results: list[dict], avg_words: float):
    """In báo cáo sau khi chạy xong — chỉ in file đáng chú ý."""

    SHORT   = [r for r in results if r.get("flag") == "SHORT"]
    LOW_ANO = [r for r in results if r.get("flag") == "LOW_ANOMALY"]
    HIGH_ANO= [r for r in results if r.get("flag") == "HIGH_ANOMALY"]

    print()
    print("=" * 60)
    print("📊 BÁO CÁO SAU KHI CHẠY")
    print("=" * 60)
    print(f"   Trung bình số từ / file: {avg_words:,.0f} từ")
    print(f"   Ngưỡng nghi vấn ngắn   : < {MIN_WORD_COUNT:,} từ")
    print(f"   Ngưỡng bất thường      : sai số > {int(ANOMALY_THRESHOLD*100)}% so với trung bình")
    print()

    if SHORT:
        print(f"⚠️  NGHI NGỜ FILE NGẮN ({len(SHORT)} file):")
        for r in SHORT:
            print(f"   📁 {r['file']:<45} {r['words']:>6,} từ")
        print()

    if LOW_ANO:
        print(f"📉 NGHI NGỜ FILE NGẮN BẤT THƯỜNG ({len(LOW_ANO)} file):")
        for r in LOW_ANO:
            diff_pct = (avg_words - r['words']) / avg_words * 100
            print(f"   📁 {r['file']:<45} {r['words']:>6,} từ  (thấp hơn TB {diff_pct:.1f}%)")
        print()

    if HIGH_ANO:
        print(f"📈 NGHI NGỜ FILE DÀI BẤT THƯỜNG ({len(HIGH_ANO)} file):")
        for r in HIGH_ANO:
            diff_pct = (r['words'] - avg_words) / avg_words * 100
            print(f"   📁 {r['file']:<45} {r['words']:>6,} từ  (cao hơn TB {diff_pct:.1f}%)")
        print()

    if not SHORT and not LOW_ANO and not HIGH_ANO:
        print("✅ Không có file nghi vấn.")
        print()

# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run():
    _bootstrap()
    logger = _setup_logger()

    session_start = datetime.now()
    logger.info("=" * 60)
    logger.info("SESSION START  %s", session_start.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    all_pdf_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".pdf")]

    # --- Trích số chương từ tên file; bỏ qua file không xác định được số ---
    numbered_files = []  # list of (chapter_num, filename)
    for f in all_pdf_files:
        num = extract_chapter_number(f)
        if num is None:
            logger.warning("SKIP_NO_NUMBER  %s — không tìm thấy số chương trong tên file", f)
            continue
        numbered_files.append((num, f))

    numbered_files.sort(key=lambda x: x[0])  # sắp đúng thứ tự chương, không theo alphabet
    total = len(numbered_files)

    if total == 0:
        logger.warning("Không tìm thấy file PDF hợp lệ trong '%s'.", INPUT_DIR)
        print("⚠  Không có file PDF nào.")
        return

    # --- Tự tính số chữ số cần đệm theo số chương LỚN NHẤT đang có trong Raw ---
    max_chapter = numbered_files[-1][0]
    width = len(str(max_chapter))

    # --- Cảnh báo nếu Translate/ đang có sẵn file đệm số KHÁC độ dài hiện tại —
    # thường do lần chạy trước Raw/ chưa tải đủ chương nên width lúc đó nhỏ hơn ---
    existing_txt = [f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".txt")]
    mismatched = []
    for f in existing_txt:
        m = re.search(r'_(\d+)\.txt$', f)
        if m and len(m.group(1)) != width:
            mismatched.append(f)
    if mismatched:
        logger.warning("PADDING_MISMATCH  %d file trong Translate/ đệm số khác %d chữ số hiện "
                        "tại (vd: %s) — có thể do lần trước Raw/ chưa tải đủ chương.",
                        len(mismatched), width, mismatched[0])
        print(f"⚠️  {len(mismatched)} file trong Translate/ đang đệm số khác {width} chữ số "
              f"(vd: {mismatched[0]}) — có thể do lần trước Raw/ chưa tải đủ chương.\n"
              f"   Khuyên nên xoá thư mục Translate/ rồi chạy lại sau khi Raw/ đã đủ hết chương.\n")

    done = skipped = errors = 0
    results: list[dict] = []   # lưu để tính anomaly sau

    for idx, (chapter_num, file) in enumerate(numbered_files, 1):
        pdf_path = os.path.join(INPUT_DIR, file)
        txt_name = f"Chương_{chapter_num:0{width}d}.txt"
        txt_path = os.path.join(OUTPUT_DIR, txt_name)

        # --- Terminal: progress ---
        pct = int(idx / total * 100)
        print(f"\r⏳ {idx}/{total} ({pct}%)  {file[:50]:<50}", end="", flush=True)

        # --- Skip đã xử lý ---
        if os.path.exists(txt_path):
            logger.info("SKIP     %s (đã tồn tại: %s)", file, txt_name)
            skipped += 1
            continue

        t0 = datetime.now()
        try:
            raw = extract_text(pdf_path)

            if not raw.strip():
                logger.warning("EMPTY    %s — không có text", file)
                errors += 1
                continue

            words = count_words(raw)
            save_text(txt_path, raw)

            elapsed = (datetime.now() - t0).total_seconds()
            logger.info("OK       %s -> %s — %d từ  |  %.2fs", file, txt_name, words, elapsed)
            done += 1

            results.append({"file": txt_name, "words": words, "flag": None})

        except Exception as exc:
            logger.error("ERROR    %s — %s", file, exc)
            errors += 1

    # --- Xóa dòng progress, in summary ---
    summary = f"✅ Xong: {done}/{total}  |  ⏩ Bỏ qua: {skipped}  |  ❌ Lỗi: {errors}"
    print(f"\r{summary:<80}")

    # =========================================================================
    # Tính trung bình & đánh dấu anomaly
    # =========================================================================
    processed = [r for r in results]   # chỉ file mới xử lý kỳ này

    if processed:
        avg_words = sum(r["words"] for r in processed) / len(processed)

        for r in processed:
            w = r["words"]
            if w < MIN_WORD_COUNT:
                r["flag"] = "SHORT"
                logger.warning("SUSPECTED_SHORT      %s — %d từ (< %d)",
                               r["file"], w, MIN_WORD_COUNT)
            elif w < avg_words * (1 - ANOMALY_THRESHOLD):
                r["flag"] = "LOW_ANOMALY"
                logger.warning("SUSPECTED_LOW_ANOMALY  %s — %d từ (TB %.0f)",
                               r["file"], w, avg_words)
            elif w > avg_words * (1 + ANOMALY_THRESHOLD):
                r["flag"] = "HIGH_ANOMALY"
                logger.warning("SUSPECTED_HIGH_ANOMALY %s — %d từ (TB %.0f)",
                               r["file"], w, avg_words)

        _print_report(processed, avg_words)
    else:
        avg_words = 0
        print("\n(Không có file nào được xử lý mới trong phiên này.)\n")

    # =========================================================================
    # Session end log
    # =========================================================================
    session_end = datetime.now()
    elapsed_total = (session_end - session_start).total_seconds()
    logger.info("-" * 60)
    logger.info("SUMMARY  done=%d  skipped=%d  errors=%d  total=%d  avg_words=%.0f",
                done, skipped, errors, total, avg_words)
    logger.info("SESSION END    %s  (%.1fs)",
                session_end.strftime("%Y-%m-%d %H:%M:%S"), elapsed_total)
    logger.info("=" * 60)

    print("Hoàn thành Step 2!\n")


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    run()