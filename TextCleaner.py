import os
import re
import logging
from datetime import datetime
from collections import defaultdict

# =========================
# ===== CONFIG ============
# =========================

INPUT_DIR = "Translate"
OUTPUT_DIR = "Cleaned"
LOG_DIR = "Log"
LOG_FILE = os.path.join(LOG_DIR, "TextCleaner_log.log")
KEYWORD_FILE = os.path.join(LOG_DIR, "TextCleaner_KeyWord.log")

HEAVY_DELETE_THRESHOLD = 10  # % — điều chỉnh ngưỡng "cắt nhiều" tại đây

ADD_CHAPTER_NUMBER = True

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# =========================
# ===== LOGGER SETUP ======
# =========================

logger = logging.getLogger("TextCleaner")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))

logger.addHandler(file_handler)

# =========================
# ===== LOAD KEYWORDS =====
# =========================

_KEYWORD_FILE_HEADER = """\
# ============================================================
# TextCleaner_KeyWord.log — Cấu hình keyword cho TextCleaner.py
# ============================================================
#
# CÚ PHÁP
#   - Dòng bắt đầu bằng # là comment, bị bỏ qua hoàn toàn
#   - Mỗi section bắt đầu bằng [TÊN_SECTION] trên một dòng riêng
#   - Keyword không phân biệt hoa/thường
#
# CÁC SECTION & CÁCH DÙNG
#   [DELETE]          Xóa dòng chứa keyword (substring match)
#                     → Thêm: quảng cáo, tên website, navigation lặp lại
#
#   [KEEP]            Bảo vệ dòng, ưu tiên hơn DELETE (substring match)
#                     → Thêm: từ trùng DELETE nhưng có trong nội dung thật
#
#   [UI_JUNK_WORDS]   Xóa dòng khớp CHÍNH XÁC từ/cụm (exact match)
#                     → Thêm: nút bấm 1-2 từ (Gửi, Hủy...), nhãn UI ngắn
#                     → KHÔNG dùng cho chuỗi dài, hãy dùng [DELETE]
#
#   [UI_JUNK_NUMBERS] Bật/tắt xóa dòng chỉ chứa số nguyên đơn
#                     → enabled (mặc định) hoặc disabled
#                     → disabled khi truyện dùng số đơn làm đánh dấu phân cảnh
#
#   [SUSPECTED]       Tự động cập nhật sau mỗi lần chạy
#                     → Xem qua, chuyển sang [DELETE] hoặc [KEEP] thủ công
# ============================================================

"""

def _write_default_keyword_file():
    with open(KEYWORD_FILE, "w", encoding="utf-8") as f:
        f.write(_KEYWORD_FILE_HEADER)
        f.write("[DELETE]\n\n")
        f.write("[KEEP]\n\n")
        f.write("[UI_JUNK_WORDS]\n")
        f.write("gửi\nhủy\nsửa\nxóa\nđọc\ncũ nhất\nmới nhất\nyêu thích\n-\n–\n—\n\n")
        f.write("[UI_JUNK_NUMBERS]\nenabled\n\n")
        f.write("[SUSPECTED]\n")


def load_keywords():
    delete_keys = set()
    keep_keys = set()
    suspected_keys = set()
    ui_junk_words = set()
    ui_junk_numbers = True      # Rule 1 bật mặc định

    if not os.path.exists(KEYWORD_FILE):
        _write_default_keyword_file()
        logger.info("Tạo mới KEYWORD_FILE: %s", KEYWORD_FILE)
        return load_keywords()  # load lại từ file vừa tạo

    section = None

    with open(KEYWORD_FILE, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line == "[DELETE]":
                section = "delete"
            elif line == "[KEEP]":
                section = "keep"
            elif line == "[SUSPECTED]":
                section = "suspected"
            elif line == "[UI_JUNK_WORDS]":
                section = "ui_junk_words"
            elif line == "[UI_JUNK_NUMBERS]":
                section = "ui_junk_numbers"
            elif section == "delete":
                delete_keys.add(line.lower())
            elif section == "keep":
                keep_keys.add(line.lower())
            elif section == "suspected":
                suspected_keys.add(line)
            elif section == "ui_junk_words":
                ui_junk_words.add(line.lower())
            elif section == "ui_junk_numbers":
                if line.lower() == "disabled":
                    ui_junk_numbers = False

    return delete_keys, keep_keys, suspected_keys, ui_junk_words, ui_junk_numbers


def rewrite_keyword_file(delete_keys, keep_keys, new_suspected, ui_junk_words, ui_junk_numbers):
    with open(KEYWORD_FILE, "w", encoding="utf-8") as f:
        f.write(_KEYWORD_FILE_HEADER)
        f.write("[DELETE]\n")
        for k in sorted(delete_keys):
            f.write(k + "\n")
        f.write("\n")

        f.write("[KEEP]\n")
        for k in sorted(keep_keys):
            f.write(k + "\n")
        f.write("\n")

        f.write("[UI_JUNK_WORDS]\n")
        for k in sorted(ui_junk_words):
            f.write(k + "\n")
        f.write("\n")

        f.write("[UI_JUNK_NUMBERS]\n")
        f.write("enabled\n" if ui_junk_numbers else "disabled\n")
        f.write("\n")

        f.write("[SUSPECTED]\n")
        for line in sorted(new_suspected):
            f.write(line + "\n")


# =========================
# ===== NORMALIZE =========
# =========================

def normalize(text):
    return text.lower().strip()


def extract_chapter_header(fname):
    """Trích số chương từ tên file, ví dụ 'Chuong_131.txt' → 'Chương 131'."""
    m = re.search(r'(\d+)', fname)
    return f"Chương {int(m.group(1))}" if m else None


# =========================
# ===== INLINE CLEAN ======
# =========================

PS_INLINE_SUFFIX = re.compile(r'\s+P[/\s]?[sS]\s*[:.].*$', re.DOTALL)

def clean_inline(line):
    return PS_INLINE_SUFFIX.sub('', line)


# =========================
# ===== UI JUNK FILTER ====
# =========================

_RE_ONLY_NUMBER = re.compile(r'^\d+$')

def is_ui_junk(line, ui_junk_words, ui_junk_numbers):
    """
    Rule 1: Dòng chỉ chứa số nguyên (bật/tắt qua [UI_JUNK_NUMBERS])
    Rule 2: Dòng khớp exact với từ trong [UI_JUNK_WORDS]
    Rule 3: Dòng chỉ gồm ký tự đặc biệt, không có chữ-số
    """
    s = line.strip()
    if not s:
        return False
    if ui_junk_numbers and _RE_ONLY_NUMBER.match(s):
        return True
    if s.lower() in ui_junk_words:
        return True
    if re.match(r'^[^\w]+$', s, re.UNICODE):
        return True
    return False


# =========================
# ===== LOGIC =============
# =========================

def should_delete(line, delete_keys, keep_keys):
    norm = normalize(line)
    for k in keep_keys:
        if k in norm:
            return False
    for k in delete_keys:
        if k in norm:
            return True
    return False


def should_add_suspected(line, delete_keys, keep_keys):
    norm = normalize(line)
    for k in keep_keys:
        if k in norm:
            return False
    for k in delete_keys:
        if k in norm:
            return False
    return True


# =========================
# ===== CLEAN CORE ========
# =========================

def clean_chapter(text, delete_keys, keep_keys, suspected_counter, ui_junk_words, ui_junk_numbers):
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line = clean_inline(line)

        # Bước 1: Xóa theo keyword (DELETE/KEEP)
        if should_delete(line, delete_keys, keep_keys):
            continue

        # Bước 2: Xóa nhiễu UI (số đơn, từ nút bấm, ký tự đặc biệt)
        if is_ui_junk(line, ui_junk_words, ui_junk_numbers):
            continue

        norm = normalize(line)
        if len(norm) > 10:
            suspected_counter[norm] += 1

        cleaned.append(line)

    result = "\n".join(cleaned)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


# =========================
# ===== MAIN ==============
# =========================

def process_all():
    delete_keys, keep_keys, _, ui_junk_words, ui_junk_numbers = load_keywords()

    files = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".txt"))

    if not files:
        print("❌ Không có file .txt trong thư mục", INPUT_DIR)
        logger.error("Không tìm thấy file .txt trong '%s'", INPUT_DIR)
        return

    total_files = len(files)
    total_raw = 0
    total_clean = 0
    suspected_counter = defaultdict(int)
    results = []  # (fname, raw_len, clean_len, removed_pct)

    logger.info("=" * 60)
    logger.info("SESSION START — %d file(s) cần xử lý", total_files)
    logger.info("INPUT_DIR: %s | OUTPUT_DIR: %s", INPUT_DIR, OUTPUT_DIR)
    logger.info("KEYWORD_FILE: %s", KEYWORD_FILE)
    logger.info("HEAVY_DELETE_THRESHOLD: %d%%", HEAVY_DELETE_THRESHOLD)
    logger.info("=" * 60)

    for idx, fname in enumerate(files, 1):
        in_path = os.path.join(INPUT_DIR, fname)
        out_path = os.path.join(OUTPUT_DIR, fname)

        with open(in_path, "r", encoding="utf-8") as f:
            raw = f.read()

        t_start = datetime.now()
        cleaned = clean_chapter(raw, delete_keys, keep_keys, suspected_counter, ui_junk_words, ui_junk_numbers)
        t_end = datetime.now()
        elapsed_ms = int((t_end - t_start).total_seconds() * 1000)

        if(ADD_CHAPTER_NUMBER):
            header = extract_chapter_header(fname)
            if header:
                cleaned = header + "\n\n" + cleaned

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(cleaned)

        raw_len = len(raw)
        clean_len = len(cleaned)
        removed = raw_len - clean_len
        removed_pct = (removed / raw_len * 100) if raw_len else 0

        total_raw += raw_len
        total_clean += clean_len
        results.append((fname, raw_len, clean_len, removed_pct))

        # Log chi tiết từng file
        logger.info("-" * 50)
        logger.info("FILE: %s", fname)
        logger.info("  Thời gian xử lý : %d ms", elapsed_ms)
        logger.info("  Ký tự ban đầu   : %d", raw_len)
        logger.info("  Ký tự sau clean : %d", clean_len)
        logger.info("  Đã cắt          : %d ký tự (%.1f%%)", removed, removed_pct)
        if removed_pct >= HEAVY_DELETE_THRESHOLD:
            logger.warning("  ⚠️  Cắt NẶNG (>= %d%%) — cần kiểm tra!", HEAVY_DELETE_THRESHOLD)

        # Terminal: chỉ hiện tiến độ %
        pct_done = idx / total_files * 100
        print(f"\r🔄 Đang xử lý: {idx}/{total_files} ({pct_done:.0f}%)", end="", flush=True)

    print()  # xuống dòng sau progress bar

    # =========================
    # ===== SUSPECTED =========
    # =========================

    new_suspected = set()
    for line, count in suspected_counter.items():
        if count >= 5 and should_add_suspected(line, delete_keys, keep_keys):
            new_suspected.add(line)

    rewrite_keyword_file(delete_keys, keep_keys, new_suspected, ui_junk_words, ui_junk_numbers)

    # =========================
    # ===== LOG SUMMARY =======
    # =========================

    total_pct = (1 - total_clean / total_raw) * 100 if total_raw else 0
    heavy_files = [(f, p) for f, r, c, p in results if p >= HEAVY_DELETE_THRESHOLD]

    logger.info("=" * 60)
    logger.info("SESSION END")
    logger.info("Tổng file     : %d", total_files)
    logger.info("Tổng ký tự    : %d → %d", total_raw, total_clean)
    logger.info("Đã cắt        : %.1f%%", total_pct)
    logger.info("Suspected mới : %d từ khóa", len(new_suspected))
    if heavy_files:
        logger.warning("File bị cắt NẶNG:")
        for f, p in sorted(heavy_files, key=lambda x: -x[1]):
            logger.warning("  - %s: %.1f%%", f, p)
    logger.info("=" * 60)

    # =========================
    # ===== TERMINAL REPORT ===
    # =========================

    print()
    print("=" * 60)
    print(f"✅ Hoàn thành — {total_files} file(s)")
    print(f"   Tổng ký tự : {total_raw:,} → {total_clean:,}")
    print(f"   Đã cắt     : {total_pct:.1f}%")
    print()

    # Bảng tất cả file có bị cắt
    print("📋 Chi tiết từng file:")
    print(f"  {'File':<35} {'Trước':>10} {'Bị cắt':>10} {'%':>7}")
    print(f"  {'-'*35} {'-'*10} {'-'*10} {'-'*7}")
    for fname, raw_len, clean_len, removed_pct in sorted(results, key=lambda x: -x[3]):
        removed = raw_len - clean_len
        flag = " ⚠️" if removed_pct >= HEAVY_DELETE_THRESHOLD else ""
        print(f"  {fname:<35} {raw_len:>10,} {removed:>10,} {removed_pct:>6.1f}%{flag}")

    print()

    # File bị cắt nghi ngờ lớn
    if heavy_files:
        print(f"⚠️  File bị cắt NẶNG (>= {HEAVY_DELETE_THRESHOLD}%) — cần kiểm tra:")
        for f, p in sorted(heavy_files, key=lambda x: -x[1]):
            print(f"   - {f}: {p:.1f}%")
    else:
        print(f"✅ Không có file nào bị cắt >= {HEAVY_DELETE_THRESHOLD}%")

    print()
    print(f"🧠 Suspected keyword mới: {len(new_suspected)}")
    print(f"📁 Output : {OUTPUT_DIR}/")
    print(f"📝 Log    : {LOG_FILE}")
    print(f"🔑 Keywords: {KEYWORD_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    process_all()