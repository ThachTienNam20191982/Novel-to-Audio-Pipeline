import time
import os
import base64
import fitz
import logging
import threading
from queue import Queue
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


# ==============================================================================
# ===== CONFIG =================================================================
# ==============================================================================

SAVE_PATH      = "Raw"
LOG_PATH       = "Log"
LOG_FILE_NAME  = "RawDownloader_log.log"
LOG_FILE       = os.path.join(LOG_PATH, LOG_FILE_NAME)

# ------------------------------------------------------------------------------
# ===== CRAWL MODE =============================================================
# CRAWL_MODE = "index"    : dùng URL_TEMPLATE + START/END_CHAPTER như cũ.
# CRAWL_MODE = "navigate" : bắt đầu từ URL_FIRST_CHAPTER, tự tìm nút "Chương sau"
#                           để lần lượt thu thập URL từng chương, sau đó download.
# ------------------------------------------------------------------------------
CRAWL_MODE = "navigate"

# Dùng khi CRAWL_MODE = "index": sinh URL theo template.
# Dùng khi CRAWL_MODE = "navigate": giới hạn số chương thu thập (START/END_CHAPTER).
#   START_CHAPTER : bỏ qua N chương đầu, bắt đầu lưu từ chương thứ N.
#   END_CHAPTER   : dừng thu thập khi đạt đến chương này (kể cả chưa hết truyện).
#                   Đặt END_CHAPTER = 999999 nếu muốn lấy hết đến chương cuối.
START_CHAPTER = 1
END_CHAPTER   = 3000
URL_TEMPLATE = "https://www.tvtruyen.com/dai-can-truong-sinh/chuong-{}/"

# Dùng khi CRAWL_MODE = "navigate"
URL_FIRST_CHAPTER = "https://www.xtruyen.vn/truyen/au-hoang-quat-khoi/chuong-1-thuong-ky-binh-cung-tuong-thuc-/"

# Tên file log lưu danh sách URL thu thập được (phase 1 của navigate mode)
PREPARE_LOG_FILE = os.path.join(LOG_PATH, "RawDownloader_Prepare.log")

WORKER_COUNT = 1

LOAD_WAIT_TIME  = 4    # giây chờ sau khi load trang
SCROLL_WAIT_TIME = 1.5  # giây chờ giữa mỗi lần scroll
CHAPTER_DELAY   = 2    # giây chờ giữa các chapter (chỉ dùng ở single-thread)

MAX_RETRY    = 3
RETRY_DELAY  = 3

# ------------------------------------------------------------------------------
# ===== AD-REMOVAL CONFIG ======================================================
# Bật/tắt từng bước xử lý quảng cáo độc lập.
#
# Thứ tự thực thi thực tế (xem run_ad_removal):
#   ADV_ISOLATE_REBUILD chạy ĐẦU TIÊN nếu bật — đọc DOM gốc rồi rebuild sạch,
#   sau đó các bước còn lại chạy tiếp để dọn nốt phần sót.
#   Nếu ADV_ISOLATE_REBUILD = False, các bước còn lại vẫn hoạt động độc lập
#   trực tiếp trên DOM gốc của trang.
#
# Khuyến nghị: chỉ bật ADV_ISOLATE_REBUILD là đủ cho hầu hết site.
# Nếu sau khi rebuild vẫn còn sót quảng cáo, bật thêm các bước bên dưới.
# Nếu bật hết mà vẫn mất nội dung, thử tắt ADV_REMOVE_OVERLAYS trước.
# ------------------------------------------------------------------------------

# Chạy ĐẦU TIÊN — cô lập nội dung chính, rebuild lại toàn bộ DOM sạch.
# Hiệu quả nhất. Nếu tắt, các bước dưới vẫn hoạt động nhưng kém triệt để hơn.
ADV_ISOLATE_REBUILD     = True

# Inject CSS ẩn element theo class/id — chỉ ẩn, không xóa DOM.
# Lưu ý: khi in PDF, Chrome đôi khi vẫn render element bị display:none,
# nên bước này ít hiệu quả hơn các bước xóa DOM thật sự bên dưới.
ADV_HIDE_CSS            = True

# Xóa <img> banner tỉ lệ ngang, link ad-domain, thẻ <ins> — xóa DOM thật sự.
ADV_REMOVE_INLINE       = True

# Xóa fixed/sticky element + iframe — xóa DOM thật sự.
# Nếu KHÔNG dùng ADV_ISOLATE_REBUILD, bước này có thể xóa mất header/nội dung thật.
ADV_REMOVE_OVERLAYS     = True

# Xóa noise đặc thù domain (footer, sidebar riêng của từng site).
ADV_REMOVE_DOMAIN_NOISE = True

# Thời gian chờ thêm TRƯỚC khi chạy ad-removal (để quảng cáo động kịp load)
ADV_EXTRA_WAIT_BEFORE  = 2   # giây; đặt 0 để bỏ qua
# Thời gian chờ thêm SAU khi chạy ad-removal (để DOM ổn định)
ADV_EXTRA_WAIT_AFTER   = 1   # giây; đặt 0 để bỏ qua

# ------------------------------------------------------------------------------
# ===== PDF POST-PROCESSING CONFIG (chỉ dùng cho xalosach hoặc bật thủ công) ==
# ------------------------------------------------------------------------------

# Bật crop PDF sau khi tải (cắt đầu trang 1, xóa N trang cuối)
PDF_SMART_CROP = False

# Số pixel cắt ở đầu trang đầu tiên (dùng để bỏ header ảnh)
CROP_TOP_FIRST_PAGE  = 250

# Số trang xóa ở cuối PDF (thường là trang quảng cáo/mục lục của site)
REMOVE_LAST_N_PAGES  = 6


# ==============================================================================
# ===== INITIAL SETUP ==========================================================
# ==============================================================================

os.makedirs(SAVE_PATH, exist_ok=True)
os.makedirs(LOG_PATH,  exist_ok=True)


# ==============================================================================
# ===== LOG SYSTEM =============================================================
# ==============================================================================

log_lock = threading.Lock()

logger = logging.getLogger("crawler")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(file_handler)
logger.propagate = False


def log(msg):
    with log_lock:
        logger.info(msg)
        file_handler.flush()
        os.fsync(file_handler.stream.fileno())


def log_err(msg):
    with log_lock:
        logger.error(msg)
        file_handler.flush()
        os.fsync(file_handler.stream.fileno())


def log_session_start():
    log("=" * 60)
    log("SESSION START")
    log("=" * 60)


def log_session_end():
    log("=" * 60)
    log("SESSION END")
    log("=" * 60)


# ==============================================================================
# ===== RESUME SYSTEM ==========================================================
# ==============================================================================

def load_completed_from_log():
    """Đọc log để lấy danh sách file đã xong từ session trước."""
    completed = set()
    if not os.path.exists(LOG_FILE):
        return completed
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if "SUCCESS:" in line or "SKIP EXISTING:" in line:
                try:
                    filename = line.strip().split(":")[-1].strip()
                    completed.add(filename)
                except Exception:
                    pass
    return completed


def load_completed_from_disk():
    """Scan thư mục SAVE_PATH, lấy tất cả file PDF đã có — không phụ thuộc log."""
    if not os.path.exists(SAVE_PATH):
        return set()
    return {f for f in os.listdir(SAVE_PATH) if f.endswith(".pdf")}


def load_completed():
    """
    Kết hợp cả hai nguồn: log + disk.
    - Disk: File đã có trên disk
    - Log:  File đã được xác định hoàn thành trong log
    """
    from_log  = load_completed_from_log()
    from_disk = load_completed_from_disk()
    combined  = from_log & from_disk

    if from_disk:
        log(f"RESUME: tìm thấy {len(from_disk)} file trên disk, "
            f"{len(from_log)} file trong log → bỏ qua {len(combined)} file tổng cộng.")

    return combined


# ==============================================================================
# ===== PROGRESS ===============================================================
# ==============================================================================

progress_lock = threading.Lock()


def print_progress(done, total):
    percent = (done / total) * 100
    print(f"\rProgress: {done}/{total} ({percent:.2f}%)", end="", flush=True)


# ==============================================================================
# ===== SELENIUM SETUP =========================================================
# ==============================================================================

def create_driver():
    options = Options()
    options.add_argument("--kiosk-printing")
    options.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(options=options)


# ==============================================================================
# ===== CORE SCROLL ============================================================
# ==============================================================================

def scroll_full_page(driver):
    """Scroll xuống hết trang để lazy-load content, rồi về đầu."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_WAIT_TIME)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)


# ==============================================================================
# ===== AD-REMOVAL STEPS =======================================================
# Mỗi hàm độc lập — bật/tắt qua CONFIG ở trên.
# ==============================================================================

def step_hide_ads_css(driver):
    """
    Bước 1 (AN TOÀN): Inject CSS ẩn element theo class/id thông thường.
    KHÔNG xóa DOM, chỉ ẩn — ít rủi ro mất nội dung nhất.
    """
    driver.execute_script("""
        let style = document.createElement('style');
        style.innerHTML = `
            iframe,
            [class*="ads"],   [class*="banner"], [class*="popup"], [class*="modal"],
            [id*="ads"],      [id*="banner"],    [id*="popup"],    [id*="modal"],
            *[style*="position: fixed"],
            *[style*="position:fixed"],
            *[style*="position: sticky"],
            *[style*="position:sticky"] {
                display: none !important;
                visibility: hidden !important;
            }
        `;
        document.head.appendChild(style);
    """)


def step_remove_inline_ads(driver):
    """
    Bước 2 (VỪA): Xóa banner ảnh tỉ lệ ngang, link đến ad-domain, thẻ <ins>.
    Rủi ro thấp nếu nội dung truyện là text thuần.
    """
    driver.execute_script("""
        // Xóa <img> hoặc thẻ cha có tỉ lệ banner (rộng > cao * 1.5)
        document.querySelectorAll('img').forEach(img => {
            const w = img.naturalWidth  || img.offsetWidth;
            const h = img.naturalHeight || img.offsetHeight;
            const ratio = w / (h || 1);
            if (ratio > 1.5 && h > 30) {
                const parent = img.closest('a') || img.closest('div') || img;
                parent.remove();
            }
        });

        // Xóa <a> dẫn đến domain quảng cáo/thương mại
        const adDomains = [
            'shopee', 'lazada', 'tiki', 'sendo', 'choice',
            'accesstrade', 'admicro', 'adtima', 'googleads',
            'doubleclick', 'adsystem'
        ];
        document.querySelectorAll('a[href]').forEach(a => {
            if (adDomains.some(d => a.href.toLowerCase().includes(d))) {
                a.remove();
            }
        });

        // Xóa <ins> (Google AdSense)
        document.querySelectorAll('ins').forEach(e => e.remove());

        // Xóa <p>/<div> chứa chỉ ảnh banner, không có text
        document.querySelectorAll('p, div').forEach(el => {
            const text  = (el.innerText || '').trim();
            const img   = el.querySelector('img');
            if (img && !text) {
                const ratio = img.offsetWidth / (img.offsetHeight || 1);
                if (ratio > 2.5) el.remove();
            }
        });
    """)


def step_remove_overlays(driver):
    """
    Bước 3 (MẠNH): Xóa tất cả fixed/sticky element, iframe, bỏ scroll-lock.
    Có thể xóa mất header thực sự của trang — bật/tắt khi cần.
    """
    driver.execute_script("""
        document.querySelectorAll('*').forEach(el => {
            const style  = window.getComputedStyle(el);
            const zIndex = parseInt(style.zIndex) || 0;

            if (style.position === 'fixed' || style.position === 'sticky') {
                el.remove();
                return;
            }
            if (zIndex > 999 && style.position !== 'static') {
                el.remove();
            }
        });

        document.querySelectorAll('iframe').forEach(e => e.remove());

        // Bỏ scroll-lock do popup
        document.body.style.overflow                = 'auto';
        document.documentElement.style.overflow    = 'auto';
    """)


def step_remove_domain_noise(driver, domain):
    """
    Bước 4: Xóa element đặc thù theo domain (footer, banner riêng từng site).
    Thêm domain mới vào đây khi cần.
    """
    if "xalosach" in domain:
        driver.execute_script("""
            document.getElementById("taiappfooter")?.remove();
            document.getElementById("footer")?.remove();
        """)
    # Thêm domain khác bên dưới:
    # elif "truyen.vn" in domain:
    #     driver.execute_script("...")


def step_isolate_and_rebuild(driver):
    """
    Bước 5 (MẠNH NHẤT): Cô lập nội dung chính, rebuild lại toàn bộ DOM.
    Dùng heuristic text-density thay vì hardcode selector:
      - Thử selector phổ biến trước (nhanh, chính xác nếu match).
      - Fallback: duyệt tất cả block, chọn cái có text dài nhất
        nhưng tỉ lệ link/text thấp — nội dung truyện ít link,
        nav/quảng cáo nhiều link. Hoạt động tốt với mọi site lạ.
    """
    driver.execute_script("""
        function scoreBlock(el) {
            const text = (el.innerText || '').trim();
            const textLen = text.length;
            if (textLen < 200) return -1;

            // Tổng ký tự nằm trong thẻ <a>
            let linkLen = 0;
            el.querySelectorAll('a').forEach(a => {
                linkLen += (a.innerText || '').length;
            });

            // Tỉ lệ link/text cao → nav hoặc quảng cáo
            const linkRatio = linkLen / textLen;
            if (linkRatio > 0.5) return -1;

            return textLen * (1 - linkRatio);
        }

        function findMainContent() {
            // Thử selector phổ biến trước
            const selectors = [
                '#content', '.content',
                '.chapter-content', '#chapter-content',
                '.entry-content', '.reading-content',
                'article', 'main'
            ];
            for (let sel of selectors) {
                const el = document.querySelector(sel);
                if (el && scoreBlock(el) > 0) return el;
            }

            // Fallback: block có score cao nhất (text dài + ít link)
            let best = null, bestScore = 0;
            document.querySelectorAll('div, section, article').forEach(el => {
                const score = scoreBlock(el);
                if (score > bestScore) { bestScore = score; best = el; }
            });
            return best;
        }

        function findTitle() {
            const selectors = [
                'h1', 'h2', '.chapter-title', '.title', '.book-title'
            ];
            for (let sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.length < 200) return el.innerText.trim();
            }
            return document.title || "";
        }

        const main  = findMainContent();
        const title = findTitle();

        if (main) {
            const html = main.innerHTML;
            document.open();
            document.write(`
                <html>
                <head>
                    <meta charset="utf-8">
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            font-size: 18px;
                            line-height: 1.7;
                            padding: 40px;
                            max-width: 800px;
                            margin: auto;
                        }
                        h1 { text-align: center; font-size: 26px; margin-bottom: 30px; }
                        img { max-width: 100%; }
                    </style>
                </head>
                <body>
                    <h1>${title}</h1>
                    ${html}
                </body>
                </html>
            `);
            document.close();
        }
    """)


# ==============================================================================
# ===== AD-REMOVAL PIPELINE ====================================================
# ==============================================================================

def run_ad_removal(driver, domain):
    """
    Pipeline xóa quảng cáo.

    Thứ tự thực thi:
      1. ADV_ISOLATE_REBUILD  — chạy ĐẦU TIÊN nếu bật, vì nó đọc DOM gốc
                                để tìm nội dung chính rồi rebuild lại sạch.
                                Các bước xóa chạy TRƯỚC nó có thể vô tình
                                xóa mất div chứa truyện → rebuild ra trang trắng.
      2. Các bước còn lại     — chạy SAU trên DOM đã được làm sạch.

    Khuyến nghị: chỉ bật ADV_ISOLATE_REBUILD là đủ cho hầu hết site.
    Bật thêm các bước khác nếu sau khi rebuild vẫn còn sót quảng cáo.
    """
    any_enabled = any([
        ADV_HIDE_CSS, ADV_REMOVE_INLINE, ADV_REMOVE_OVERLAYS,
        ADV_REMOVE_DOMAIN_NOISE, ADV_ISOLATE_REBUILD
    ])
    if not any_enabled:
        return

    if ADV_EXTRA_WAIT_BEFORE > 0:
        time.sleep(ADV_EXTRA_WAIT_BEFORE)

    # Bước 5 chạy trước — đọc và rebuild DOM gốc
    if ADV_ISOLATE_REBUILD:
        step_isolate_and_rebuild(driver)

    # Các bước còn lại chạy sau trên DOM đã rebuild
    if ADV_HIDE_CSS:
        step_hide_ads_css(driver)

    if ADV_REMOVE_INLINE:
        step_remove_inline_ads(driver)

    if ADV_REMOVE_OVERLAYS:
        step_remove_overlays(driver)

    if ADV_REMOVE_DOMAIN_NOISE:
        step_remove_domain_noise(driver, domain)

    if ADV_EXTRA_WAIT_AFTER > 0:
        time.sleep(ADV_EXTRA_WAIT_AFTER)


# ==============================================================================
# ===== PDF SAVE ===============================================================
# ==============================================================================

def save_pdf_raw(driver, filename):
    """In trang thành PDF và lưu file."""
    pdf = driver.execute_cdp_cmd("Page.printToPDF", {
        "printBackground": True,
        "marginTop":    0.6,
        "marginBottom": 0.4,
        "scale":        0.95,
        "preferCSSPageSize": True
    })
    file_path = os.path.join(SAVE_PATH, filename)
    with open(file_path, "wb") as f:
        f.write(base64.b64decode(pdf["data"]))
    return file_path


def smart_crop_pdf(input_path, output_path):
    """
    Hậu xử lý PDF:
    - Cắt CROP_TOP_FIRST_PAGE pixel ở đầu trang 1 (xóa header ảnh).
    - Xóa REMOVE_LAST_N_PAGES trang cuối (trang QC / mục lục của site).
    - Trên trang cuối còn lại: cắt tại dòng "Mục lục" nếu tìm thấy.
    """
    doc     = fitz.open(input_path)
    new_doc = fitz.open()

    total_pages = len(doc)
    keep_until  = max(1, total_pages - REMOVE_LAST_N_PAGES)

    for i in range(keep_until):
        page = doc[i]
        rect = page.rect

        if i == 0:
            clip = fitz.Rect(rect.x0, rect.y0 + CROP_TOP_FIRST_PAGE, rect.x1, rect.y1)

        elif i == keep_until - 1:
            instances = page.search_for("Mục lục")
            if instances:
                y_cut = max(inst.y0 for inst in instances)
                clip  = fitz.Rect(rect.x0, rect.y0, rect.x1, y_cut - 10)
            else:
                clip = rect
        else:
            clip = rect

        new_page = new_doc.new_page(width=clip.width, height=clip.height)
        new_page.show_pdf_page(
            fitz.Rect(0, 0, clip.width, clip.height),
            doc, i, clip=clip
        )

    new_doc.save(output_path)
    doc.close()
    new_doc.close()


def save_pdf(driver, filename):
    """
    Lưu PDF, áp dụng smart_crop nếu PDF_SMART_CROP = True.
    """
    if PDF_SMART_CROP:
        raw_path   = os.path.join(SAVE_PATH, "raw_" + filename)
        final_path = os.path.join(SAVE_PATH, filename)
        pdf = driver.execute_cdp_cmd("Page.printToPDF", {"printBackground": True})
        with open(raw_path, "wb") as f:
            f.write(base64.b64decode(pdf["data"]))
        smart_crop_pdf(raw_path, final_path)
        os.remove(raw_path)
        return final_path
    else:
        return save_pdf_raw(driver, filename)


# ==============================================================================
# ===== NAVIGATE MODE — PHASE 1: THU THẬP URL =================================
# Dùng 1 driver duy nhất, đi từ URL_FIRST_CHAPTER, bấm nút "Chương sau"
# liên tục cho đến khi không tìm được nút hoặc URL lặp lại.
# Kết quả lưu vào PREPARE_LOG_FILE: mỗi dòng là "index|url|filename"
# ==============================================================================

# Các keyword tìm nút "Chương sau" — thêm vào nếu gặp site dùng chữ khác
NEXT_CHAPTER_KEYWORDS = [
    "chương sau", "chương tiếp", "next chapter", "tiếp theo",
    "trang sau", "next", "»", "→"
]


def find_next_chapter_url(driver):
    """
    Tìm URL chương tiếp theo. Dùng 3 chiến lược theo thứ tự:

    1. CSS selector trực tiếp — nhanh, chính xác cho site có class cố định
       (xtruyen: .btn.next_page, nhiều site khác: .nav-next a, .next-chap...)
    2. Quét <a> theo text của <span> bên trong — bắt được nút dạng
       <a><span>Chương tiếp</span><i class="icon"/></a> mà link.text bị lẫn ký tự icon
    3. Quét <a> theo link.text toàn bộ, lọc ký tự font icon (Unicode Private Use Area)
    """
    try:
        # Chiến lược 1: CSS selector phổ biến
        css_selectors = [
            "a.btn.next_page",        # xtruyen.vn
            ".nav-next a",            # WordPress manga theme
            "a.next-chap",
            "a.next_chap",
            "a#next_chap",
            "a.nextchap",
            "[rel='next']",
        ]
        for sel in css_selectors:
            try:
                el = driver.find_element("css selector", sel)
                href = (el.get_attribute("href") or "").strip()
                if href and href != driver.current_url:
                    return href
            except Exception:
                continue

        # Chiến lược 2: tìm <a> có <span> con khớp keyword
        links = driver.find_elements("tag name", "a")
        for link in links:
            href = (link.get_attribute("href") or "").strip()
            if not href or href == driver.current_url:
                continue
            try:
                spans = link.find_elements("tag name", "span")
                for span in spans:
                    span_text = (span.text or "").strip().lower()
                    if any(kw in span_text for kw in NEXT_CHAPTER_KEYWORDS):
                        return href
            except Exception:
                continue

        # Chiến lược 3: fallback — lọc ký tự Unicode Private Use Area (font icon)
        for link in links:
            href = (link.get_attribute("href") or "").strip()
            if not href or href == driver.current_url:
                continue
            text = "".join(c for c in (link.text or "") if ord(c) < 0xE000 or ord(c) > 0xF8FF)
            text = text.strip().lower()
            if any(kw in text for kw in NEXT_CHAPTER_KEYWORDS):
                return href
    except Exception:
        pass
    return None


PREPARE_DONE_MARKER = "#DONE"


def load_prepare_log():
    """
    Đọc PREPARE_LOG_FILE, trả về:
      - chapters  : list of (index, url, filename) đã thu thập
      - url_set   : set các url đã có (để tránh lặp)
      - is_done   : True nếu file có marker #DONE — tức là đã thu thập xong,
                    không cần verify hay tiếp tục nữa.
    """
    chapters = []
    url_set  = set()
    is_done  = False

    if not os.path.exists(PREPARE_LOG_FILE):
        return chapters, url_set, is_done

    with open(PREPARE_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line == PREPARE_DONE_MARKER:
                is_done = True
                continue
            if line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) == 3:
                idx, url, filename = parts
                chapters.append((int(idx), url.strip(), filename.strip()))
                url_set.add(url.strip())

    return chapters, url_set, is_done


def mark_prepare_done():
    """Ghi marker #DONE vào cuối PREPARE_LOG_FILE."""
    with open(PREPARE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{PREPARE_DONE_MARKER}\n")
        f.flush()
        os.fsync(f.fileno())


def append_prepare_log(index, url, filename):
    """Ghi thêm 1 dòng vào PREPARE_LOG_FILE."""
    with open(PREPARE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{index}|{url}|{filename}\n")
        f.flush()
        os.fsync(f.fileno())


def phase1_collect_urls():
    """
    Phase 1: Thu thập toàn bộ URL chương bằng cách bấm nút "Chương sau".
    - Resume được: nếu PREPARE_LOG_FILE đã có dữ liệu thì tiếp tục từ chương cuối.
    - Nếu file có marker #DONE thì bỏ qua hoàn toàn, không mở browser.
    - Kết thúc khi không tìm được nút tiếp theo, URL lặp, hoặc đạt END_CHAPTER.
    Trả về list of (index, url, filename).
    """
    chapters, url_set, is_done = load_prepare_log()

    if is_done:
        filtered = [c for c in chapters if START_CHAPTER <= c[0] <= END_CHAPTER]
        print(f"\n[Phase 1] Prepare log đã có marker DONE — bỏ qua phase 1.")
        print(f"[Phase 1] Lọc theo START={START_CHAPTER} END={END_CHAPTER}: {len(filtered)}/{len(chapters)} chương.")
        return filtered

    if chapters:
        last_index, last_url, _ = chapters[-1]
        print(f"\n[Phase 1] Resume: đã có {len(chapters)} chương trong prepare log.")
        print(f"[Phase 1] Tiếp tục từ chương {last_index}: {last_url[:80]}")
        current_url = last_url
        next_index  = last_index + 1
        # Chỉ giữ lại chapters nằm trong range hiện tại
        chapters = [c for c in chapters if START_CHAPTER <= c[0] <= END_CHAPTER]
        url_set  = {c[1] for c in chapters}  # rebuild url_set từ chapters đã filter
    else:
        print(f"\n[Phase 1] Bắt đầu thu thập URL từ chương {START_CHAPTER} đến {END_CHAPTER}.")
        print(f"[Phase 1] URL đầu tiên: {URL_FIRST_CHAPTER}")
        with open(PREPARE_LOG_FILE, "w", encoding="utf-8") as f:
            f.write(f"# Prepare log — mỗi dòng: index|url|filename\n")
        current_url = None
        next_index  = 1

    driver = create_driver()

    try:
        # Nếu resume, load trang cuối để tìm nút tiếp theo từ đó
        if current_url:
            driver.get(current_url)
            time.sleep(LOAD_WAIT_TIME)
            next_url = find_next_chapter_url(driver)
            if not next_url or next_url in url_set:
                print("[Phase 1] Đã đến chương cuối (resume check). Không cần thu thập thêm.")
                mark_prepare_done()
                return chapters
            current_url = next_url
        else:
            current_url = URL_FIRST_CHAPTER

        while True:
            if current_url in url_set:
                print(f"\n[Phase 1] URL lặp lại → đã đến chương cuối. Tổng: {len(chapters)} chương.")
                mark_prepare_done()
                break

            driver.get(current_url)
            time.sleep(LOAD_WAIT_TIME)

            if next_index < START_CHAPTER:
                print(f"\r[Phase 1] Bỏ qua chương {next_index} (< START_CHAPTER={START_CHAPTER})", end="", flush=True)
                url_set.add(current_url)
            else:
                filename = f"Chuong_{next_index}.pdf"
                chapters.append((next_index, current_url, filename))
                url_set.add(current_url)
                append_prepare_log(next_index, current_url, filename)
                print(f"\r[Phase 1] Thu thập: chương {next_index}/{END_CHAPTER} — {current_url[:70]}", end="", flush=True)

            # Tăng index ngay sau khi xử lý xong chương hiện tại
            next_index += 1

            # Dừng nếu đã đủ số chương — trước khi tìm và load trang tiếp
            if next_index > END_CHAPTER:
                print(f"\n[Phase 1] Đã đạt END_CHAPTER ({END_CHAPTER}). Dừng thu thập.")
                mark_prepare_done()
                break

            next_url = find_next_chapter_url(driver)

            if not next_url:
                print(f"\n[Phase 1] Không tìm thấy nút chương sau → đã đến chương cuối. Tổng: {len(chapters)} chương.")
                mark_prepare_done()
                break

            if next_url in url_set:
                print(f"\n[Phase 1] Nút chương sau dẫn về URL cũ → đã đến chương cuối. Tổng: {len(chapters)} chương.")
                mark_prepare_done()
                break

            current_url = next_url

    finally:
        driver.quit()

    return chapters


# ==============================================================================
# ===== WORKER =================================================================
# ==============================================================================

def worker(queue, completed_set, total, counter):
    driver = create_driver()

    while True:
        item = queue.get()
        if item is None:
            break

        i, url, filename = item
        domain = urlparse(url).netloc

        if filename in completed_set:
            with progress_lock:
                counter[0] += 1
                print_progress(counter[0], total)
            log(f"SKIP EXISTING: {filename}")
            queue.task_done()
            continue

        success = False

        for attempt in range(1, MAX_RETRY + 1):
            try:
                driver.get(url)
                time.sleep(LOAD_WAIT_TIME)

                scroll_full_page(driver)
                run_ad_removal(driver, domain)
                save_pdf(driver, filename)

                log(f"SUCCESS: {filename}")
                success = True
                break

            except Exception as e:
                log_err(f"ERROR {filename} attempt {attempt}: {e}")
                time.sleep(RETRY_DELAY)

        if not success:
            log_err(f"FAILED: {filename}")

        with progress_lock:
            counter[0] += 1
            print_progress(counter[0], total)

        queue.task_done()

    driver.quit()


# ==============================================================================
# ===== MAIN ===================================================================
# ==============================================================================

def run_download(chapters):
    """Phase 2: Download song song các chương từ danh sách (index, url, filename)."""
    completed = load_completed()
    q         = Queue()
    total     = len(chapters)
    counter   = [0]

    for item in chapters:
        q.put(item)

    threads = []
    for _ in range(WORKER_COUNT):
        t = threading.Thread(target=worker, args=(q, completed, total, counter))
        t.start()
        threads.append(t)

    q.join()

    for _ in range(WORKER_COUNT):
        q.put(None)
    for t in threads:
        t.join()

    print("\nHoàn thành download!")


def main():
    log_session_start()

    if CRAWL_MODE == "navigate":
        # ── Phase 1: Thu thập URL (1 worker, lưu vào Prepare log) ──────────────
        print("=" * 60)
        print("CRAWL MODE: navigate")
        print("=" * 60)
        chapters = phase1_collect_urls()

        if not chapters:
            print("Không thu thập được chương nào. Kiểm tra lại URL_FIRST_CHAPTER.")
            log_session_end()
            return

        # ── Phase 2: Download song song ─────────────────────────────────────────
        print(f"\n[Phase 2] Bắt đầu download {len(chapters)} chương với {WORKER_COUNT} workers...")
        run_download(chapters)

    elif CRAWL_MODE == "index":
        # ── Mode cũ: sinh URL theo template ─────────────────────────────────────
        print("=" * 60)
        print("CRAWL MODE: index")
        print("=" * 60)
        chapters = [
            (i, URL_TEMPLATE.format(i), f"Chuong_{i}.pdf")
            for i in range(START_CHAPTER, END_CHAPTER + 1)
        ]
        run_download(chapters)

    else:
        print(f"CRAWL_MODE không hợp lệ: '{CRAWL_MODE}'. Dùng 'index' hoặc 'navigate'.")

    log_session_end()


if __name__ == "__main__":
    main()