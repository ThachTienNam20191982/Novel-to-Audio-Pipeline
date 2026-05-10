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

def load_keywords():
    delete_keys = set()
    keep_keys = set()
    suspected_keys = set()

    if not os.path.exists(KEYWORD_FILE):
        return delete_keys, keep_keys, suspected_keys

    section = None

    with open(KEYWORD_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line == "[DELETE]":
                section = "delete"
                continue
            elif line == "[KEEP]":
                section = "keep"
                continue
            elif line == "[SUSPECTED]":
                section = "suspected"
                continue

            if section == "delete":
                delete_keys.add(line.lower())
            elif section == "keep":
                keep_keys.add(line.lower())
            elif section == "suspected":
                suspected_keys.add(line)

    return delete_keys, keep_keys, suspected_keys


# =========================
# ===== SAVE KEYWORDS =====
# =========================

def rewrite_keyword_file(delete_keys, keep_keys, new_suspected):
    with open(KEYWORD_FILE, "w", encoding="utf-8") as f:
        f.write("[DELETE]\n")
        for k in sorted(delete_keys):
            f.write(k + "\n")

        f.write("\n[KEEP]\n")
        for k in sorted(keep_keys):
            f.write(k + "\n")

        f.write("\n[SUSPECTED]\n")
        for line in sorted(new_suspected):
            f.write(line + "\n")


# =========================
# ===== NORMALIZE =========
# =========================

def normalize(text):
    return text.lower().strip()


# =========================
# ===== INLINE CLEAN ======
# =========================

PS_INLINE_SUFFIX = re.compile(r'\s+P[/\s]?[sS]\s*[:.].*$', re.DOTALL)

def clean_inline(line):
    return PS_INLINE_SUFFIX.sub('', line)


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

def clean_chapter(text, delete_keys, keep_keys, suspected_counter):
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line = clean_inline(line)

        if should_delete(line, delete_keys, keep_keys):
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
    delete_keys, keep_keys, _ = load_keywords()

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
        cleaned = clean_chapter(raw, delete_keys, keep_keys, suspected_counter)
        t_end = datetime.now()
        elapsed_ms = int((t_end - t_start).total_seconds() * 1000)

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

    rewrite_keyword_file(delete_keys, keep_keys, new_suspected)

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