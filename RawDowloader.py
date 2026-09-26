import time
import os
import shutil
import tempfile
import base64
import fitz
import logging
import threading
from queue import Queue
from urllib.parse import urlparse
import undetected_chromedriver as uc
import config


# ==============================================================================
# ===== CONFIG =================================================================
# Toàn bộ tham số cấu hình của file này nằm trong config.py, mục
# "RawDowloader.py — CONFIG". Sửa giá trị ở đó khi cần, không sửa ở đây.
# ==============================================================================

SAVE_PATH      = config.RAW_DIR
LOG_PATH       = config.LOG_DIR
LOG_FILE_NAME  = "RawDownloader_log.log"
LOG_FILE       = os.path.join(LOG_PATH, LOG_FILE_NAME)

CRAWL_MODE        = config.RAWDL_CRAWL_MODE
START_CHAPTER     = config.RAWDL_START_CHAPTER
END_CHAPTER       = config.RAWDL_END_CHAPTER
URL_TEMPLATE      = config.RAWDL_URL_TEMPLATE
URL_FIRST_CHAPTER = config.RAWDL_URL_FIRST_CHAPTER

# Tên file log lưu danh sách URL thu thập được (phase 1 của navigate mode)
PREPARE_LOG_FILE = os.path.join(LOG_PATH, "RawDownloader_Prepare.log")

WORKER_COUNT = config.RAWDL_WORKER_COUNT

LOAD_WAIT_TIME   = config.RAWDL_LOAD_WAIT_TIME
SCROLL_WAIT_TIME = config.RAWDL_SCROLL_WAIT_TIME
CHAPTER_DELAY    = config.RAWDL_CHAPTER_DELAY

MAX_RETRY   = config.RAWDL_MAX_RETRY
RETRY_DELAY = config.RAWDL_RETRY_DELAY

# ------------------------------------------------------------------------------
# ===== AD-REMOVAL CONFIG (giá trị nằm trong config.py) ========================
# ------------------------------------------------------------------------------
ADV_ISOLATE_REBUILD     = config.RAWDL_ADV_ISOLATE_REBUILD
ADV_HIDE_CSS            = config.RAWDL_ADV_HIDE_CSS
ADV_REMOVE_INLINE       = config.RAWDL_ADV_REMOVE_INLINE
ADV_REMOVE_OVERLAYS     = config.RAWDL_ADV_REMOVE_OVERLAYS
ADV_REMOVE_DOMAIN_NOISE = config.RAWDL_ADV_REMOVE_DOMAIN_NOISE
ADV_EXTRA_WAIT_BEFORE   = config.RAWDL_ADV_EXTRA_WAIT_BEFORE
ADV_EXTRA_WAIT_AFTER    = config.RAWDL_ADV_EXTRA_WAIT_AFTER

# ------------------------------------------------------------------------------
# ===== PDF POST-PROCESSING CONFIG (giá trị nằm trong config.py) ==============
# ------------------------------------------------------------------------------
PDF_SMART_CROP      = config.RAWDL_PDF_SMART_CROP
CROP_TOP_FIRST_PAGE = config.RAWDL_CROP_TOP_FIRST_PAGE
REMOVE_LAST_N_PAGES = config.RAWDL_REMOVE_LAST_N_PAGES

# ------------------------------------------------------------------------------
# ===== DOWNLOAD TRỰC TIẾP TỪ WEB CONFIG (giá trị nằm trong config.py) ========
# ------------------------------------------------------------------------------
DIRECT_DOWNLOAD_ENABLED      = config.RAWDL_DIRECT_DOWNLOAD_ENABLED
DIRECT_DOWNLOAD_BUTTON_TEXTS = config.RAWDL_DIRECT_DOWNLOAD_BUTTON_TEXTS
DIRECT_DOWNLOAD_TIMEOUT      = config.RAWDL_DIRECT_DOWNLOAD_TIMEOUT

# Thư mục tạm chứa file vừa tải xuống trước khi đổi tên/di chuyển vào SAVE_PATH.
DIRECT_DOWNLOAD_TMP_ROOT = os.path.join(tempfile.gettempdir(), "rawdl_dltmp")


# ==============================================================================
# ===== INITIAL SETUP ==========================================================
# ==============================================================================

os.makedirs(SAVE_PATH, exist_ok=True)
os.makedirs(LOG_PATH,  exist_ok=True)

if DIRECT_DOWNLOAD_ENABLED:
    os.makedirs(DIRECT_DOWNLOAD_TMP_ROOT, exist_ok=True)


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

# undetected-chromedriver cần patch driver lúc khởi tạo — nếu nhiều thread
# cùng patch một lúc (lần chạy đầu, chưa có bản patch cache sẵn) dễ đụng file,
# nên khóa lại đoạn TẠO driver cho chạy tuần tự. Việc mở trang/scroll/in PDF
# sau đó vẫn chạy song song bình thường như cũ, không bị ảnh hưởng.
_driver_create_lock = threading.Lock()


def get_local_chrome_version():
    """Tự dò version Chrome ĐANG CÀI trên máy, để ép undetected-chromedriver
    tải đúng bản chromedriver khớp version đó.

    Lý do cần hàm này: nếu không truyền version_main, undetected-chromedriver
    có thể tải nhầm bản chromedriver mới hơn Chrome thật đang cài (VD: Chrome
    tự update chậm hơn, máy đang ở bản 151 nhưng UC lại tải bản hỗ trợ 152),
    gây lỗi ngay lúc khởi tạo:
        "This version of ChromeDriver only supports Chrome version 152
         Current browser version is 151.0.7922.174"
    Dò lại đúng version máy đang có mỗi lần chạy giúp tránh lỗi này vĩnh
    viễn, kể cả sau này Chrome tự cập nhật lên bản khác.
    """
    # Cách 1: đọc thẳng registry (Windows) — không cần biết đường dẫn cài Chrome
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
        version, _ = winreg.QueryValueEx(key, "version")
        return int(version.split(".")[0])
    except Exception:
        pass

    # Cách 2: gọi chrome.exe --version ở vài đường dẫn cài đặt phổ biến
    try:
        import re
        import subprocess
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in candidates:
            if os.path.exists(path):
                out = subprocess.check_output([path, "--version"], text=True)
                match = re.search(r"(\d+)\.", out)
                if match:
                    return int(match.group(1))
    except Exception:
        pass

    return None  # không dò được — để undetected-chromedriver tự lo (có thể lệch)


# Trang truyện dùng thư viện JS "disable-devtool" (theajack) để phát hiện có
# công cụ debug/CDP đang gắn vào trang: gọi console.log/table/... với dữ liệu
# "gài bẫy" (getter có side-effect, hoặc dữ liệu nặng để đo thời gian xử lý),
# rồi kiểm tra NGAY SAU ĐÓ (đồng bộ) xem bẫy có bị kích hoạt / bị chậm bất
# thường không. Selenium/CDP luôn cần bật Runtime domain để execute_script
# hoạt động — không cách nào tránh nếu còn dùng execute_script — nên các phép
# đo "ngay sau đó" này luôn thấy dấu hiệu bất thường và site sẽ tự điều
# hướng lùi lại (window.history.back()) làm mất nội dung đang đọc.
#
# Cách vá: hoãn TOÀN BỘ lệnh console.* ra sau 1 tick (setTimeout 0) — mọi
# phép kiểm tra "ngay lập tức" của detector sẽ luôn thấy console.log trả về
# gần như tức thì / bẫy chưa kịp kích hoạt, trong khi log thật vẫn được gọi
# (chỉ trễ chút xíu) nên driver vẫn đọc log bình thường nếu cần. Vá kèm 2 lớp
# phòng hờ: tự tắt qua window.DisableDevtool.isSuspend nếu site có lộ biến
# này ra global, và vô hiệu hoá window.history.back() (phương án cuối mà
# thư viện dùng để "đá" tab) để dù có lọt detector nào khác cũng không mất
# nội dung đang đọc.
ANTI_DEVTOOL_DETECT_JS = """
(function () {
    var methods = ['log', 'info', 'warn', 'error', 'debug', 'table', 'dir',
                    'trace', 'group', 'groupCollapsed', 'groupEnd'];
    methods.forEach(function (m) {
        var original = console[m];
        if (typeof original === 'function') {
            console[m] = function () {
                var args = arguments;
                setTimeout(function () {
                    try { original.apply(console, args); } catch (e) {}
                }, 0);
            };
        }
    });

    try {
        var _dd;
        Object.defineProperty(window, 'DisableDevtool', {
            configurable: true,
            get: function () { return _dd; },
            set: function (v) {
                _dd = v;
                try { if (v) { v.isSuspend = true; } } catch (e) {}
            }
        });
    } catch (e) {}

    try {
        window.history.back = function () {};
    } catch (e) {}
})();
"""


def _setup_direct_download(driver):
    """
    Tạo 1 thư mục tạm RIÊNG cho driver này rồi ép Chrome LƯU file (thay vì mở
    PDF bằng viewer nội bộ) vào đúng thư mục đó — cần thiết để bấm nút tải
    PDF do site cung cấp (VD "Tải PDF") thực sự tải được file xuống đĩa.

    Gắn đường dẫn thư mục vào driver._direct_dl_dir để direct_download_pdf()
    dùng lại. Set cả 2 cấp lệnh CDP để chắc ăn:
      - Browser.setDownloadBehavior : áp dụng cho TOÀN BỘ browser, kể cả tab
        mới mở (site có thể mở tab mới để trả file, target="_blank").
      - Page.setDownloadBehavior    : dự phòng cho bản chromedriver cũ không
        hỗ trợ lệnh Browser.*.
    """
    dl_dir = tempfile.mkdtemp(prefix="dl_", dir=DIRECT_DOWNLOAD_TMP_ROOT)
    params = {"behavior": "allow", "downloadPath": dl_dir}

    cdp_ok = False
    try:
        driver.execute_cdp_cmd("Browser.setDownloadBehavior", params)
        cdp_ok = True
    except Exception as e:
        log_err(f"[DirectDownload] Browser.setDownloadBehavior lỗi: {e}")
    try:
        driver.execute_cdp_cmd("Page.setDownloadBehavior", params)
        cdp_ok = True
    except Exception as e:
        log_err(f"[DirectDownload] Page.setDownloadBehavior lỗi: {e}")

    if not cdp_ok:
        # Cả 2 lệnh CDP đều lỗi -> Chrome sẽ KHÔNG lưu file vào dl_dir, mà
        # rơi về thư mục download mặc định của hệ thống (hoặc hiện hộp
        # thoại). wait_for_completed_download() sẽ luôn timeout vì nó chỉ
        # theo dõi đúng dl_dir này. Ghi log rõ để dễ tra khi debug.
        log_err(f"[DirectDownload] CẢNH BÁO: không redirect được download vào {dl_dir} — "
                f"direct_download_pdf() sẽ luôn báo timeout dù nút bấm và tải thành công.")

    driver._direct_dl_dir = dl_dir


def create_driver():
    options = uc.ChromeOptions()
    options.add_argument("--kiosk-printing")
    options.add_argument("--lang=vi-VN")
    options.add_argument("--disable-features=CalculateNativeWinOcclusion")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    chrome_version = get_local_chrome_version()
    with _driver_create_lock:
        # use_subprocess=True bắt buộc phải có khi tạo driver trong thread
        # phụ (không phải main thread) — mặc định UC cố đăng ký signal
        # handler, mà Python chỉ cho phép làm điều đó ở main thread, nếu
        # không sẽ crash với lỗi "signal only works in main thread".
        # version_main=chrome_version: ép tải chromedriver đúng khớp bản
        # Chrome đang cài trên máy (xem get_local_chrome_version() ở trên).
        driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_version)

    # Tiêm script chống disable-devtool vào MỌI trang mới trong suốt phiên
    # làm việc của driver này (addScriptToEvaluateOnNewDocument chạy trước
    # cả script của chính trang, trên mọi lần điều hướng).
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": ANTI_DEVTOOL_DETECT_JS
        })
    except Exception:
        pass

    # Một vài trường hợp UC mở thêm 1 cửa sổ/tab thừa ngay lúc khởi tạo —
    # dọn sạch, chỉ giữ đúng 1 cửa sổ trước khi bắt đầu điều hướng, để driver
    # không bị "lạc" sang cửa sổ trống thay vì cửa sổ có nội dung thật.
    handles = driver.window_handles
    if len(handles) > 1:
        for h in handles[1:]:
            try:
                driver.switch_to.window(h)
                driver.close()
            except Exception:
                pass
        driver.switch_to.window(handles[0])

    if DIRECT_DOWNLOAD_ENABLED:
        _setup_direct_download(driver)

    return driver


def safe_quit(driver):
    """Đóng driver an toàn — undetected-chromedriver đôi khi ném lỗi vô hại lúc quit().
    Dọn luôn thư mục tải tạm riêng của driver này nếu có (chế độ download trực tiếp)."""
    dl_dir = getattr(driver, "_direct_dl_dir", None)
    try:
        driver.quit()
    except Exception:
        pass
    if dl_dir:
        try:
            shutil.rmtree(dl_dir, ignore_errors=True)
        except Exception:
            pass


def goto(driver, url):
    """Thay cho driver.get(url) + time.sleep(LOAD_WAIT_TIME) gọi thẳng.

    Vấn đề thực tế gặp phải: trang vẫn load được nội dung thật (nhìn thấy
    bằng mắt), nhưng driver lại bị "lạc" sang một cửa sổ/tab khác đang trống
    (chrome://new-tab-page/...) — có thể do UC hoặc do trang tự mở thêm
    tab/cửa sổ. Vì chrome://... là URL nội bộ trình duyệt, trang web KHÔNG
    thể tự điều hướng tới đó bằng JS, nên gần như chắc chắn đây là vấn đề
    driver đang trỏ sai cửa sổ chứ không phải nội dung bị site xoá thật.

    Hàm này sau khi load sẽ rà qua toàn bộ cửa sổ đang mở, tìm đúng cửa sổ
    có URL khớp domain của trang đích, chuyển driver sang đó, rồi đóng bớt
    các cửa sổ thừa còn lại.
    """
    domain = urlparse(url).netloc

    driver.get(url)
    time.sleep(LOAD_WAIT_TIME)

    handles = driver.window_handles
    target = None

    if len(handles) > 1 or domain not in driver.current_url:
        for h in handles:
            driver.switch_to.window(h)
            if domain in driver.current_url:
                target = h
                break

        if target is None:
            # Không cửa sổ nào khớp domain — quay về cửa sổ đầu tiên, ít
            # nhất các bước sau vẫn có gì đó để đọc (và để log/báo lỗi).
            target = handles[0]
            driver.switch_to.window(target)

        for h in handles:
            if h != target:
                try:
                    driver.switch_to.window(h)
                    driver.close()
                except Exception:
                    pass
        driver.switch_to.window(target)


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
    return driver.execute_script(r"""
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

        function escapeHtml(s) {
            return String(s || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }

        // Tìm tiêu đề chương ĐẦY ĐỦ ("Chương 1: Tên chương").
        // Lỗi cũ: <title> của trang và các phần tử "lá" thường chỉ chứa mỗi
        // "Chương 1", còn phần tên chương nằm chung trong 1 thẻ cha (h1/h2/a...)
        // có nhiều <span> con -> bị bỏ sót. Ở đây quét MỌI phần tử (kể cả phần
        // tử có con), lấy innerText thật (đúng thứ hiển thị trên màn hình), chỉ
        // nhận text bắt đầu bằng "Chương <số>", rồi chọn ứng viên DÀI NHẤT.
        function findChapterTitleStrict() {
            const START_RE = /^[\[\(\s]*(chương|chuong|chapter)\s*(\d+)/i;
            const NAV_RE   = /chương\s*(trước|sau|tiếp)|chuong\s*(truoc|sau|tiep)|(prev(ious)?|next)\s*chapter|mục\s*lục/i;
            const SKIP     = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'OPTION', 'SELECT', 'TITLE', 'HEAD', 'META', 'LINK']);

            // Số chương trong URL (vd .../chuong-1/ -> 1) để loại các mục
            // "Chương 2, Chương 3..." nằm trong menu/mục lục cùng trang.
            const um = window.location.pathname.match(/(?:chuong|chapter|chap)[-_]?(\d+)/i);
            const urlNum = um ? parseInt(um[1], 10) : null;

            function collect(useUrlNum) {
                const found = [];
                document.querySelectorAll('body *').forEach(el => {
                    if (SKIP.has(el.tagName)) return;
                    if ((el.textContent || '').length > 300) return;  // lọc rẻ trước khi gọi innerText
                    let t = (el.innerText || '').trim();
                    if (t.length < 4) return;
                    if (/\n/.test(t)) {
                        // Thẻ heading được phép xuống dòng (số chương / tên chương
                        // ở 2 dòng); thẻ khác nhiều dòng thường là container -> bỏ.
                        if (!/^H[1-4]$/.test(el.tagName)) return;
                        t = t.split(/\n+/).map(s => s.trim()).filter(Boolean).join(' ');
                    }
                    t = t.replace(/^\[+\s*|\s*\]+$/g, '').replace(/\s+/g, ' ').trim();
                    if (t.length < 4 || t.length > 150) return;
                    const m = t.match(START_RE);
                    if (!m) return;
                    if (NAV_RE.test(t)) return;
                    if (useUrlNum && urlNum !== null && parseInt(m[2], 10) !== urlNum) return;
                    found.push(t);
                });
                return found;
            }

            let list = collect(true);
            if (!list.length) list = collect(false);
            if (!list.length) return null;
            list.sort((a, b) => b.length - a.length);
            return list[0];
        }

        function findTitle(mainEl) {
            // Thử cách quét đầy đủ trước; chỉ chấp nhận nếu kết quả có nhiều hơn
            // mỗi "Chương N" (tức có kèm tên chương). Nếu không thì chạy tiếp
            // các cách cũ bên dưới.
            const strict = findChapterTitleStrict();
            if (strict && !/^[\[\(\s]*(chương|chuong|chapter)\s*\d+\s*$/i.test(strict)) return strict;

            // Bản trước dựa vào VỊ TRÍ heading (gần main content) vẫn có thể vớ
            // nhầm "Bookmarks" nếu main content được nhận diện là một khối RỘNG
            // (bao luôn cả mấy mục UI phía trên), hoặc nếu tiêu đề chương bị xé
            // nhỏ qua nhiều <span> con (mỗi span không đủ để nhận ra là tiêu đề).
            // Đổi hướng: tìm theo NGỮ NGHĨA — cụm "Chương <số>" — thay vì theo vị
            // trí trong DOM. Ưu tiên cao nhất là thẻ <title> của trang vì đó luôn
            // là 1 CHUỖI DUY NHẤT (không bị chia nhỏ qua nhiều thẻ con).
            const CHAPTER_RE = /chương\s*\d+|chuong\s*\d+|chapter\s*\d+/i;
            const VOLUME_RE  = /minh\s*họa|minh\s*hoa|phụ\s*lục|phu\s*luc|tập\s*\d+|tap\s*\d+/i;

            const titleParts = (document.title || '').split(/\s*[-–—|]\s*/);

            // Ưu tiên 1: đoạn trong <title> khớp "Chương <số>"
            for (const part of titleParts) {
                const t = part.trim();
                if (t && t.length < 150 && CHAPTER_RE.test(t)) return t;
            }

            // Ưu tiên 2: quét từng phần tử "lá" (không có thẻ con) trên trang,
            // tìm text ngắn khớp "Chương <số>" — không cần biết nó là heading
            // hay div/span/a, miễn nằm trọn trong 1 phần tử.
            function scanForPattern(re) {
                const all = document.querySelectorAll('body *');
                for (const el of all) {
                    const tag = el.tagName;
                    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') continue;
                    if (el.children.length > 0) continue;
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t && t.length < 150 && re.test(t)) return t;
                }
                return null;
            }
            let found = scanForPattern(CHAPTER_RE);
            if (found) return found;

            // Ưu tiên 3: khớp lỏng hơn cho trang không có chữ "Chương"
            // (vd trang "Minh họa Tập X", "Phụ lục ...")
            for (const part of titleParts) {
                const t = part.trim();
                if (t && t.length < 150 && VOLUME_RE.test(t)) return t;
            }
            found = scanForPattern(VOLUME_RE);
            if (found) return found;

            // Ưu tiên 4 (dự phòng cho site không dùng tiếng Việt / không có
            // pattern trên): heading gần main content nhất trong DOM.
            if (mainEl) {
                const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6'));
                let candidate = null;
                for (const h of headings) {
                    if (h.compareDocumentPosition(mainEl) & Node.DOCUMENT_POSITION_FOLLOWING) {
                        candidate = h;
                    }
                }
                if (candidate) {
                    const t = (candidate.innerText || '').trim();
                    if (t && t.length < 200) return t;
                }
                const inner = mainEl.querySelector('h1, h2, h3, h4, h5, h6');
                if (inner) {
                    const t = (inner.innerText || '').trim();
                    if (t && t.length < 200) return t;
                }
            }

            // Fallback cuối cùng — selector cũ
            const selectors = ['h1', 'h2', '.chapter-title', '.title', '.book-title'];
            for (let sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.length < 200) return el.innerText.trim();
            }
            return document.title || "";
        }

        const main  = findMainContent();
        const title = findTitle(main);

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
                    <h1>${escapeHtml(title)}</h1>
                    ${html}
                </body>
                </html>
            `);
            document.close();
        }
        return title;
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
        detected_title = step_isolate_and_rebuild(driver)
        log(f"TITLE DETECTED: {detected_title!r}")

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
# ===== DOWNLOAD TRỰC TIẾP TỪ WEB ==============================================
# Một số site tự cung cấp sẵn nút tải PDF (VD: "Tải PDF") thay vì phải tự in
# trang thành PDF (Page.printToPDF). Khi bật RAWDL_DIRECT_DOWNLOAD_ENABLED,
# pipeline sẽ ưu tiên tìm 1 trong các nút liệt kê ở
# RAWDL_DIRECT_DOWNLOAD_BUTTON_TEXTS (config.py) và bấm để tải file gốc do
# site cung cấp — áp dụng cho CẢ 2 CRAWL_MODE (index và navigate).
#
# Nếu KHÔNG tìm thấy nút nào trên trang -> tự động rơi về (fallback) phương
# án in trang thành PDF như cũ (xem worker()), không cần cấu hình gì thêm.
# ==============================================================================

def _list_files(dir_path):
    try:
        return set(os.listdir(dir_path))
    except Exception:
        return set()


def find_direct_download_button(driver, button_texts):
    """
    Tìm 1 trong các nút tải PDF trực tiếp do site cung cấp.
    - Khớp theo text HIỂN THỊ của <a>/<button>, không phân biệt hoa/thường.
    - Khớp kiểu "chứa chuỗi con" (không cần khớp tuyệt đối) để dễ khớp với
      nút có thêm icon/khoảng trắng quanh chữ (VD: "⬇ Tải PDF").
    - button_texts lấy từ RAWDL_DIRECT_DOWNLOAD_BUTTON_TEXTS (config.py) — có
      thể bổ sung thêm mẫu mới vào đó khi gặp site dùng chữ khác.
    """
    texts_lower = [t.strip().lower() for t in button_texts if t and t.strip()]
    if not texts_lower:
        return None

    candidates = []
    for tag in ("a", "button"):
        try:
            candidates.extend(driver.find_elements("tag name", tag))
        except Exception:
            pass

    for el in candidates:
        try:
            if not el.is_displayed():
                continue
            text = (el.text or "").strip().lower()
            if not text:
                continue
            if any(t in text for t in texts_lower):
                return el
        except Exception:
            continue
    return None


def wait_for_completed_download(download_dir, before_files, timeout):
    """
    Đợi 1 file MỚI xuất hiện trong download_dir và tải xong. Chrome đặt đuôi
    tạm (.crdownload/.tmp/.part) trong lúc tải, xoá đuôi này khi tải xong ->
    chỉ nhận file KHÔNG còn đuôi tạm, và double-check size không còn tăng
    (đề phòng file vừa đổi tên xong nhưng ghi đĩa chưa kịp hoàn tất).

    Trả về đường dẫn file khi thành công, None nếu hết thời gian chờ.
    """
    TEMP_EXT = (".crdownload", ".tmp", ".part")
    deadline = time.time() + timeout

    while time.time() < deadline:
        new_files = _list_files(download_dir) - before_files
        finished = [f for f in new_files if not f.lower().endswith(TEMP_EXT)]
        if finished:
            candidate = max(
                (os.path.join(download_dir, f) for f in finished),
                key=lambda p: os.path.getmtime(p)
            )
            try:
                size1 = os.path.getsize(candidate)
                time.sleep(0.3)
                size2 = os.path.getsize(candidate)
                if size1 == size2:
                    return candidate
            except OSError:
                pass
        time.sleep(0.5)
    return None


def direct_download_pdf(driver, filename):
    """
    Thử tải PDF TRỰC TIẾP do site cung cấp (bấm 1 trong các nút cấu hình ở
    DIRECT_DOWNLOAD_BUTTON_TEXTS), lưu vào SAVE_PATH/filename — ĐÚNG cách đặt
    tên hiện tại của RawDowloader (không dùng tên file gốc do site đặt).

    Trả về:
      True  — tải thành công.
      False — KHÔNG tìm thấy nút nào trên trang này -> nơi gọi (worker())
              sẽ tự fallback sang phương án in trang thành PDF (save_pdf)
              như cũ.

    Ném Exception nếu tìm thấy nút nhưng bấm/tải không thành công — để vòng
    lặp retry ở worker() xử lý giống các lỗi khác (thử lại), thay vì âm thầm
    fallback sang phương án khác và có thể lưu nhầm nội dung không mong muốn.
    """
    download_dir = getattr(driver, "_direct_dl_dir", None)
    if not download_dir:
        # Driver chưa được cấu hình thư mục tải riêng (VD bật config sau khi
        # driver đã tạo) -> coi như direct download không khả dụng lúc này.
        return False

    button = find_direct_download_button(driver, DIRECT_DOWNLOAD_BUTTON_TEXTS)
    if button is None:
        return False

    before_handles = set(driver.window_handles)
    before_files = _list_files(download_dir)
    original_handle = driver.current_window_handle

    button.click()

    # QUAN TRỌNG: phải CHỜ TẢI XONG (hoặc hết timeout) TRƯỚC KHI đóng tab
    # mới. Trước đây code đóng tab mới sau đúng 0.5s — nếu site mở
    # target="_blank" và server cần vài giây để generate/trả file (PDF
    # dựng động), request vẫn đang ở tab đó và CHƯA kịp được browser nhận
    # diện là 1 download (chưa có response header) thì bị đóng tab sẽ HỦY
    # LUÔN request → không bao giờ có file, dù bấm nút và mạng đều ổn.
    # Đây rất có thể là lý do site tải được bằng Playwright (expect_download
    # đợi tới 30s, không đụng tới tab) nhưng lại fail ở đây.
    downloaded_path = wait_for_completed_download(download_dir, before_files, DIRECT_DOWNLOAD_TIMEOUT)

    # Dọn tab mới (nếu có) SAU KHI đã xong việc chờ — không còn nguy cơ hủy
    # ngang download nữa.
    new_handles = [h for h in driver.window_handles if h not in before_handles]
    for h in new_handles:
        try:
            driver.switch_to.window(h)
            driver.close()
        except Exception:
            pass
    try:
        driver.switch_to.window(original_handle)
    except Exception:
        pass

    if not downloaded_path:
        raise RuntimeError(
            f"Tìm thấy nút tải PDF trực tiếp nhưng không tải xong file "
            f"trong {DIRECT_DOWNLOAD_TIMEOUT}s (dự kiến lưu: {filename})"
        )

    dest_path = os.path.join(SAVE_PATH, filename)
    if os.path.exists(dest_path):
        os.remove(dest_path)
    shutil.move(downloaded_path, dest_path)

    # Dọn file rác còn sót trong thư mục tạm (VD .crdownload lỗi từ lần thử
    # trước) để lần tải kế tiếp không bị nhận nhầm là "file mới".
    for f in _list_files(download_dir):
        try:
            os.remove(os.path.join(download_dir, f))
        except Exception:
            pass

    return True


# ==============================================================================
# ===== NAVIGATE MODE — PHASE 1: THU THẬP URL =================================
# Dùng 1 driver duy nhất, đi từ URL_FIRST_CHAPTER, bấm nút "Chương sau"
# liên tục cho đến khi không tìm được nút hoặc URL lặp lại.
# Kết quả lưu vào PREPARE_LOG_FILE: mỗi dòng là "index|url|filename"
# ==============================================================================

# Các keyword tìm nút "Chương sau" — thêm vào nếu gặp site dùng chữ khác
NEXT_CHAPTER_KEYWORDS = [
    "chương sau", "chương tiếp", "next chapter", "tiếp theo",
    "trang sau", "next", "»", "→", "Tiếp", ">>", "Đọc tiếp", "Next", "Next Chapter"
]


def find_next_chapter_url(driver):
    """
    Tìm URL chương tiếp theo. Dùng nhiều chiến lược theo thứ tự:

    0. [MỚI] Mục lục dạng <li><a> (sidebar/dropdown chương) — dành cho site
       mà nút "chương sau" chỉ là ICON, hoàn toàn KHÔNG có chữ/keyword để
       so khớp (vd: docln.sbs — nút chỉ là hình mũi tên/">>" không có text).

       Cách làm: nhận diện "tiền tố chương" từ URL hiện tại — tức phần URL
       đứng trước đoạn cuối dạng "/c<số>-..." (vd với
       ".../c12210-chuong-1-cai-bay" thì tiền tố là phần trước "/c12210-").
       Sau đó gom mọi link CÙNG tiền tố này mà nằm trong thẻ <li> (tức nằm
       trong mục lục dạng danh sách), giữ đúng thứ tự xuất hiện trong DOM
       (= đúng thứ tự đọc trên docln.sbs), rồi trả về link đứng ngay SAU
       link của trang hiện tại. Không phụ thuộc text hay class cụ thể nên
       khá bền vững, kể cả khi hết tập này sang tập khác.

    0b.[MỚI] Nhóm nút "prev / mục lục / next" dạng icon nằm cạnh nhau, dùng
       khi trang không có mục lục <li> đầy đủ trong DOM. Tìm một khối cha
       chứa 2-4 thẻ <a>, trong đó có đúng 1 link trỏ về đúng trang mục lục
       truyện (URL không có phần "/c<số>") và các link còn lại là link
       chương cùng bộ — lấy link chương CUỐI CÙNG trong khối đó (vị trí
       bên phải, đúng quy ước prev-giữa-next) làm "chương sau".

    1. CSS selector trực tiếp — nhanh, chính xác cho site có class cố định
       (xtruyen: .btn.next_page, nhiều site khác: .nav-next a, .next-chap...)
    2. Quét <a> theo text của <span> bên trong — bắt được nút dạng
       <a><span>Chương tiếp</span><i class="icon"/></a> mà link.text bị lẫn ký tự icon
    3. Quét <a> theo link.text toàn bộ, lọc ký tự font icon (Unicode Private Use Area)
    """
    # Hàm JS dùng chung cho chiến lược 0 và 0b: xác định "tiền tố chương"
    # từ 1 URL, và kiểm tra 1 href có cùng tiền tố (cùng truyện) hay không.
    # Viết dưới dạng string thuần (không regex động) để tránh lỗi escape
    # khi nhúng vào Python.
    JS_HELPERS = r"""
        function chapterPrefix(url) {
            const clean = url.split('?')[0].split('#')[0].replace(/\/$/, '');
            const parts = clean.split('/');
            if (parts.length < 2) return null;
            const last = parts[parts.length - 1];
            if (last.length < 2 || last[0] !== 'c' || last[1] < '0' || last[1] > '9') return null;
            return parts.slice(0, -1).join('/');
        }
        function isChapterOfPrefix(href, prefix) {
            const clean = href.split('?')[0].split('#')[0].replace(/\/$/, '');
            if (!clean.startsWith(prefix + '/c')) return false;
            const rest = clean.slice((prefix + '/c').length);
            return rest.length > 0 && rest[0] >= '0' && rest[0] <= '9';
        }
    """

    try:
        # ---- Chiến lược 0: mục lục <li><a> ----
        next_url = driver.execute_script(JS_HELPERS + r"""
            const curUrl = window.location.href.split('?')[0].split('#')[0].replace(/\/$/, '');
            const prefix = chapterPrefix(curUrl);
            if (!prefix) return null;

            const links = Array.from(document.querySelectorAll('li a[href]'))
                .filter(a => isChapterOfPrefix(a.href, prefix));

            const seen = new Set();
            const ordered = [];
            links.forEach(a => {
                const href = a.href.split('?')[0].split('#')[0].replace(/\/$/, '');
                if (!seen.has(href)) { seen.add(href); ordered.push(href); }
            });

            const idx = ordered.indexOf(curUrl);
            if (idx !== -1 && idx + 1 < ordered.length) return ordered[idx + 1];
            return null;
        """)
        if next_url and next_url != driver.current_url:
            return next_url
    except Exception:
        pass

    try:
        # ---- Chiến lược 0b: nhóm icon prev / mục lục / next cạnh nhau ----
        next_url = driver.execute_script(JS_HELPERS + r"""
            const curUrl = window.location.href.split('?')[0].split('#')[0].replace(/\/$/, '');
            const prefix = chapterPrefix(curUrl);
            if (!prefix) return null;

            const allLinks = Array.from(document.querySelectorAll('a[href]'));
            const groups = new Map();
            allLinks.forEach(a => {
                const p = a.parentElement;
                if (!p) return;
                if (!groups.has(p)) groups.set(p, []);
                groups.get(p).push(a);
            });

            for (const entry of groups.values()) {
                if (entry.length < 2 || entry.length > 4) continue;
                const hasRoot = entry.some(a => {
                    const clean = a.href.split('?')[0].split('#')[0].replace(/\/$/, '');
                    return clean === prefix;
                });
                const chapLinks = entry.filter(a => {
                    const clean = a.href.split('?')[0].split('#')[0].replace(/\/$/, '');
                    return isChapterOfPrefix(a.href, prefix) && clean !== curUrl;
                });
                if (hasRoot && chapLinks.length >= 1) {
                    return chapLinks[chapLinks.length - 1].href;
                }
            }
            return null;
        """)
        if next_url and next_url != driver.current_url:
            return next_url
    except Exception:
        pass

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
            goto(driver, current_url)
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

            goto(driver, current_url)

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
        safe_quit(driver)

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
                goto(driver, url)

                downloaded_directly = False
                if DIRECT_DOWNLOAD_ENABLED:
                    downloaded_directly = direct_download_pdf(driver, filename)

                if not downloaded_directly:
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

    safe_quit(driver)


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

    if DIRECT_DOWNLOAD_ENABLED:
        print(f"[Direct Download] BẬT — sẽ ưu tiên bấm nút: {DIRECT_DOWNLOAD_BUTTON_TEXTS}")
        print("[Direct Download] (không tìm thấy nút thì tự fallback in trang thành PDF)")

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