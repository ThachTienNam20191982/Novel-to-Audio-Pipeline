import os

# ==============================================================================
# ===== DÙNG CHUNG CHO TOÀN BỘ PIPELINE (nhiều file cùng đọc) =================
# ==============================================================================
# Khi chuyển sang xử lý 1 truyện khác: CHỈ CẦN đổi NOVEL_NAME bên dưới.
# Mọi thư mục sẽ tự động trỏ sang Data/<NOVEL_NAME>/... — không cần clone lại
# repo, không cần sửa từng file .py.
# ==============================================================================

# ------------------------------------------------------------------------------
# ⭐ CHỈ CẦN SỬA DÒNG NÀY MỖI KHI CHUYỂN TRUYỆN ⭐
# ------------------------------------------------------------------------------
NOVEL_NAME = "Quật Khởi Chi Đệ Tam Đế Quốc"

DATA_ROOT = "Data"
BASE_DIR = os.path.join(DATA_ROOT, NOVEL_NAME)

RAW_DIR          = os.path.join(BASE_DIR, "Raw")           # PDF chương gốc          (RawDowloader)
TRANSLATE_DIR    = os.path.join(BASE_DIR, "Translate")      # Text convert từ PDF      (TextExtractor, TextSplit)
CLEANED_DIR      = os.path.join(BASE_DIR, "Cleaned")        # Text đã dọn dẹp          (TextCleaner, TitleDelete, TextSplit output, AudioGenerator input)
TEXT_MERGED_DIR  = os.path.join(BASE_DIR, "Text_Merged")    # Text gộp nhiều chương    (TextMerge)
AUDIO_DIR        = os.path.join(BASE_DIR, "Audio")          # MP3 từng chương          (AudioGenerator output, AudioMerger input)
AUDIO_MERGED_DIR = os.path.join(BASE_DIR, "Merged")         # MP3 đã gộp               (AudioMerger output)
TEMP_AUDIO_DIR   = os.path.join(BASE_DIR, "temp_audio")     # File tạm khi tạo audio   (AudioGenerator)
LOG_DIR          = os.path.join(BASE_DIR, "Log")            # Log + state file của mọi script

for _dir in (RAW_DIR, TRANSLATE_DIR, CLEANED_DIR, TEXT_MERGED_DIR,
             AUDIO_DIR, AUDIO_MERGED_DIR, TEMP_AUDIO_DIR, LOG_DIR):
    os.makedirs(_dir, exist_ok=True)


# ==============================================================================
# ===== RawDowloader.py — CONFIG ===============================================
# ==============================================================================

# CRAWL_MODE = "index"    : dùng URL_TEMPLATE + START/END_CHAPTER
# CRAWL_MODE = "navigate" : bắt đầu từ URL_FIRST_CHAPTER, tự tìm nút "Chương sau"
#                           để lần lượt thu thập URL từng chương, sau đó download.
RAWDL_CRAWL_MODE = "navigate"

# Dùng khi CRAWL_MODE = "index": sinh URL theo template.
# Dùng khi CRAWL_MODE = "navigate": giới hạn số chương thu thập.
#   START_CHAPTER : bỏ qua N chương đầu, bắt đầu lưu từ chương thứ N.
#   END_CHAPTER   : dừng thu thập khi đạt đến chương này (999999 = lấy hết).
RAWDL_START_CHAPTER = 1
RAWDL_END_CHAPTER   = 10000
RAWDL_URL_TEMPLATE = "https://thungtruyen.com/truyen/khoai-lac-he-thong/chuong-{}/"

# Dùng khi CRAWL_MODE = "navigate"
RAWDL_URL_FIRST_CHAPTER = "https://metruyenchuvn.org/quat-khoi-chi-de-tam-de-quoc/chuong-0-EK8G1vTPiwMD"

RAWDL_WORKER_COUNT = 1

RAWDL_LOAD_WAIT_TIME   = 4    # giây chờ sau khi load trang
RAWDL_SCROLL_WAIT_TIME = 1.5  # giây chờ giữa mỗi lần scroll
RAWDL_CHAPTER_DELAY    = 2    # giây chờ giữa các chapter (chỉ dùng ở single-thread)

RAWDL_MAX_RETRY   = 3
RAWDL_RETRY_DELAY = 3

# --- Ad-removal: bật/tắt từng bước xử lý quảng cáo độc lập ---
# Khuyến nghị: chỉ bật ADV_ISOLATE_REBUILD là đủ cho hầu hết site. Nếu sau khi
# rebuild vẫn còn sót quảng cáo, bật thêm các bước bên dưới. Nếu bật hết mà
# vẫn mất nội dung, thử tắt ADV_REMOVE_OVERLAYS trước.
RAWDL_ADV_ISOLATE_REBUILD     = True   # cô lập nội dung chính, rebuild lại DOM sạch — hiệu quả nhất
RAWDL_ADV_HIDE_CSS            = True   # inject CSS ẩn element theo class/id (chỉ ẩn, không xóa DOM)
RAWDL_ADV_REMOVE_INLINE       = True   # xóa <img> banner, link ad-domain, thẻ <ins>
RAWDL_ADV_REMOVE_OVERLAYS     = True   # xóa fixed/sticky element + iframe
RAWDL_ADV_REMOVE_DOMAIN_NOISE = True   # xóa noise đặc thù domain (footer, sidebar riêng từng site)
RAWDL_ADV_EXTRA_WAIT_BEFORE   = 2      # giây chờ thêm TRƯỚC ad-removal; đặt 0 để bỏ qua
RAWDL_ADV_EXTRA_WAIT_AFTER    = 1      # giây chờ thêm SAU ad-removal; đặt 0 để bỏ qua

# --- PDF post-processing (chỉ dùng cho xalosach hoặc bật thủ công) ---
RAWDL_PDF_SMART_CROP      = False
RAWDL_CROP_TOP_FIRST_PAGE = 250   # px cắt ở đầu trang 1 (bỏ header ảnh)
RAWDL_REMOVE_LAST_N_PAGES = 6     # số trang xóa ở cuối PDF (quảng cáo/mục lục)


# ==============================================================================
# ===== TextExtractor.py — CONFIG ==============================================
# ==============================================================================
TEXTEXTRACT_MIN_WORD_COUNT    = 500   # file ít hơn ngưỡng này → nghi ngờ file ngắn
TEXTEXTRACT_ANOMALY_THRESHOLD = 0.30  # sai số > ngưỡng này so với trung bình → bất thường


# ==============================================================================
# ===== TextCheck.py — CONFIG ===================================================
# ==============================================================================
# (không có tham số riêng — chỉ dùng RAW_DIR ở block dùng chung phía trên)


# ==============================================================================
# ===== TextCleaner.py — CONFIG ================================================
# ==============================================================================
TEXTCLEANER_HEAVY_DELETE_THRESHOLD = 10    # % — điều chỉnh ngưỡng "cắt nhiều" tại đây
TEXTCLEANER_ADD_CHAPTER_NUMBER     = True


# ==============================================================================
# ===== TitleDelete.py — CONFIG ================================================
# ==============================================================================
# Các dòng "rác" cần xóa ở đầu mỗi chương — ĐẶC THÙ THEO TỪNG TRUYỆN.
# Đổi truyện thì sửa danh sách này, không cần mở TitleDelete.py
TITLEDEL_JUNK_PATTERNS = [
    r'^Huấn Luyện Gia Tầng Lớp Thấp Nhất Của Thế Giới\s*\r?\n',
    r'^Pokemon\s*/\s*',
]


# ==============================================================================
# ===== TextSplit.py — CONFIG ===================================================
# ==============================================================================
# File text lớn (đã dịch/gộp) cần tách thành từng chương — mặc định lấy theo
# NOVEL_NAME, nằm trong TRANSLATE_DIR ở block dùng chung phía trên
TEXTSPLIT_INPUT_FILE = os.path.join(TRANSLATE_DIR, f"{NOVEL_NAME}.txt")


# ==============================================================================
# ===== TextMerge.py — CONFIG ===================================================
# ==============================================================================
# 0 = merge tất cả thành 1 file | >0 = số chương mỗi file
TEXTMERGE_MERGE_SIZE = 10


# ==============================================================================
# ===== AudioGenerator.py — CONFIG =============================================
# ==============================================================================
AUDIOGEN_VOICE = "vi-VN-HoaiMyNeural"

AUDIOGEN_CHUNK_SIZE = 1500
AUDIOGEN_SENTENCE_SPLIT_REGEX = r'(?<=[.!?…])\s+'

AUDIOGEN_MAX_RETRY = 10
AUDIOGEN_RETRY_BASE_DELAY = 1.0
AUDIOGEN_RETRY_BACKOFF = 1.5

AUDIOGEN_DELAY_BETWEEN_CHUNKS = (0.1, 0.2)
AUDIOGEN_DELAY_BETWEEN_FILES  = (0.3, 0.5)

AUDIOGEN_TTS_CONCURRENT = 3
AUDIOGEN_MAX_WORKERS    = 5
AUDIOGEN_WORKER_STAGGER = 2.0

AUDIOGEN_THROTTLE_KEYWORDS = ["1015", "1008", "connection", "reset", "timeout", "too many", "no audio"]
AUDIOGEN_THROTTLE_BASE_DELAY = 15
AUDIOGEN_THROTTLE_BACKOFF    = 20

# 0 = không giới hạn, >0 = tối đa N chunk mỗi file mp3 → Prefix_Part1.mp3, Part2...
AUDIOGEN_MAX_CHUNKS_PER_PART = 500

AUDIOGEN_SUPPORTED_EXT = (".docx", ".txt")


# ==============================================================================
# ===== AudioMerger.py — CONFIG ================================================
# ==============================================================================
# Tiền tố tên file mp3 đã gộp — vd "Truyen_Chuong_001-010.mp3". Mặc định lấy
# theo NOVEL_NAME, có thể override riêng nếu muốn tên hiển thị khác tên thư mục.
AUDIOMERGE_OUTPUT_PREFIX = NOVEL_NAME

# Số chương tối đa trong 1 file merged (0 = không giới hạn, chỉ dùng MAX_DURATION_SECONDS)
AUDIOMERGE_CHAPTERS_PER_GROUP = 100

# Thời lượng tối đa (giây) của 1 file merged (0 = không giới hạn, chỉ dùng CHAPTERS_PER_GROUP)
# Khi CẢ HAI đều >0: dừng nhóm khi thoả 1 trong 2. Khi CẢ HAI = 0: gộp hết thành 1.
AUDIOMERGE_MAX_DURATION_SECONDS = 36000

AUDIOMERGE_OUTPUT_BITRATE = "192k"    # 64k / 128k / 192k / 320k

AUDIOMERGE_SKIP_EXISTING = True    # True = bỏ qua file merged đã tồn tại (an toàn khi bị kill giữa chừng)

AUDIOMERGE_VERIFY_ENABLE    = True   # kiểm tra tổng thời lượng sau khi merge
AUDIOMERGE_VERIFY_TOLERANCE = 2.0    # sai số cho phép, tính bằng giây
