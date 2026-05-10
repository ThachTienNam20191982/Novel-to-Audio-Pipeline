import timeimport os
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

START_CHAPTER = 1
END_CHAPTER   = 1876

URL_TEMPLATE = "https://www.tvtruyen.com/dai-can-truong-sinh/chuong-{}/"

WORKER_COUNT = 10

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
    - Disk: đáng tin cậy nhất, không bị mất khi log bị xóa.
    - Log:  bắt thêm các file đã xong nhưng vì lý do nào đó bị xóa khỏi disk.
    """
    from_log  = load_completed_from_log()
    from_disk = load_completed_from_disk()
    combined  = from_log | from_disk

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

def main():
    log_session_start()

    completed = load_completed()
    q         = Queue()
    total     = END_CHAPTER - START_CHAPTER + 1
    counter   = [0]

    for i in range(START_CHAPTER, END_CHAPTER + 1):
        url      = URL_TEMPLATE.format(i)
        filename = f"Chuong_{i}.pdf"
        q.put((i, url, filename))

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

    print("\nHoàn thành!")
    log_session_end()


if __name__ == "__main__":
    main()
