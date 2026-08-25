"""
gui.py — Bảng điều khiển cho toàn bộ pipeline Novel-to-Audio.

Chạy:  python gui.py
       (hoặc double-click gui.exe nếu đã đóng gói — xem build_exe.bat)
Yêu cầu: file này (hoặc gui.exe) nằm CÙNG thư mục với config.py và 9 file
         script (RawDowloader.py, TextExtractor.py, TextCheck.py,
         TextCleaner.py, TitleDelete.py, TextSplit.py, TextMerge.py,
         AudioGenerator.py, AudioMerger.py). Vẫn cần cài Python thật (kèm đủ
         fitz/edge_tts/selenium/rich/docx2txt...) trên máy để chạy 9 script
         đó dù gui.py đã được đóng gói thành .exe hay chưa.

Tab "⚙️ Config" đọc/ghi trực tiếp config.py (có backup timestamp trước khi
ghi đè). Mỗi tab script còn lại chạy file .py tương ứng như 1 tiến trình con
riêng biệt (python <file>.py), hiển thị log thực tế theo thời gian thực,
và có thể Start/Stop độc lập.
"""

import os
import re
import sys
import json
import queue
import shutil
import signal
import platform
import subprocess
import threading
import importlib
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# =============================================================================
# ===== ĐƯỜNG DẪN GỐC ==========================================================
# =============================================================================
# Luôn tính đường dẫn tương đối theo đúng thư mục chứa gui.py/gui.exe, bất kể
# chương trình được khởi chạy từ đâu (double-click, shortcut, terminal ở thư
# mục khác...).
#
# Khi đóng gói thành .exe (PyInstaller): __file__ trỏ vào thư mục giải nén TẠM
# (sys._MEIPASS), KHÔNG phải nơi gui.exe thực sự nằm — phải dùng sys.executable
# thay thế. sys.frozen là cờ chuẩn PyInstaller đặt = True khi chạy dạng đóng gói.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# Khi chạy "python gui.py" bình thường, Python tự thêm thư mục chứa gui.py vào
# sys.path nên "import config" hoạt động sẵn. Khi đóng gói .exe thì KHÔNG tự
# thêm — phải chèn thủ công để import config.py (nằm ngoài, không bundle vào
# exe) vẫn tìm thấy được.
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.py")
BACKUP_DIR = os.path.join(SCRIPT_DIR, "config_backup")

try:
    import config
except Exception as exc:
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "Lỗi import config.py",
        f"Không thể import config.py:\n\n{exc}\n\n"
        f"Kiểm tra lại cú pháp config.py (có thể do sửa tay bị lỗi) rồi mở lại chương trình.",
    )
    sys.exit(1)


def _find_python_executable():
    """Đường dẫn python.exe dùng để chạy 9 script con.

    Chạy dạng "python gui.py" bình thường: sys.executable CHÍNH LÀ python.exe
    cần dùng.
    Chạy dạng gui.exe đã đóng gói (PyInstaller): sys.executable trỏ vào chính
    gui.exe (không tự chạy được script .py khác), nên phải dò python.exe cài
    sẵn trên máy qua PATH — pipeline vẫn cần Python thật (có đủ fitz, edge_tts,
    selenium, rich, docx2txt...) để chạy 9 script kia, gui.exe chỉ đóng vai
    launcher cho phần giao diện.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in ("python.exe", "py.exe", "python3.exe", "python"):
        found = shutil.which(name)
        if found:
            return found
    return None


PYTHON_EXE = _find_python_executable()

ADD_NEW_SENTINEL = "+ Thêm truyện mới..."
INVALID_FOLDER_CHARS = set('\\/:*?"<>|')

PIPELINE_SCRIPTS = [
    ("📥 1.RawDowloader", "RawDowloader.py"),
    ("📄 2.TextExtractor", "TextExtractor.py"),
    ("🔍 3.TextCheck", "TextCheck.py"),
    ("🧹 4.TextCleaner", "TextCleaner.py"),
    ("🗑️ 5.TitleDelete", "TitleDelete.py"),
    ("✂️ 6.TextSplit", "TextSplit.py"),
    ("🔗 7.TextMerge", "TextMerge.py"),
    ("🔊 8.AudioGenerator", "AudioGenerator.py"),
    ("🎚️ 9.AudioMerger", "AudioMerger.py"),
]

SECTION_TITLES = {
    "RAWDL": "RawDowloader.py",
    "TEXTEXTRACT": "TextExtractor.py",
    "TEXTCLEANER": "TextCleaner.py",
    "TITLEDEL": "TitleDelete.py",
    "TEXTMERGE": "TextMerge.py",
    "AUDIOGEN": "AudioGenerator.py",
    "AUDIOMERGE": "AudioMerger.py",
}

# (varname, nhãn hiển thị, loại widget, options (nếu có), section "simple"/"advanced")
# widget: checkbox | dropdown_strict | dropdown_editable | entry | multiline_list | tuple_floats | tuple_strs
FIELD_SPECS = [
    ("RAWDL_CRAWL_MODE", "Chế độ crawl", "dropdown_strict", ["index", "navigate"], "simple"),
    ("RAWDL_WORKER_COUNT", "Số luồng tải song song", "dropdown_editable", ["1", "2", "3", "4", "5", "6", "8"], "simple"),
    ("RAWDL_ADV_ISOLATE_REBUILD", "Cô lập & rebuild DOM (khuyến nghị luôn bật)", "checkbox", None, "simple"),
    ("RAWDL_ADV_HIDE_CSS", "Ẩn quảng cáo bằng CSS", "checkbox", None, "simple"),
    ("RAWDL_ADV_REMOVE_INLINE", "Xoá banner/link quảng cáo trong nội dung", "checkbox", None, "simple"),
    ("RAWDL_ADV_REMOVE_OVERLAYS", "Xoá overlay/iframe nổi", "checkbox", None, "simple"),
    ("RAWDL_ADV_REMOVE_DOMAIN_NOISE", "Xoá noise riêng theo domain", "checkbox", None, "simple"),
    ("RAWDL_PDF_SMART_CROP", "Crop PDF thông minh", "checkbox", None, "simple"),
    ("RAWDL_START_CHAPTER", "Chương bắt đầu", "entry", None, "advanced"),
    ("RAWDL_END_CHAPTER", "Chương kết thúc", "entry", None, "advanced"),
    ("RAWDL_URL_TEMPLATE", "URL template (dùng {} thay số chương)", "entry", None, "advanced"),
    ("RAWDL_URL_FIRST_CHAPTER", "URL chương đầu (chế độ navigate)", "entry", None, "advanced"),
    ("RAWDL_LOAD_WAIT_TIME", "Chờ sau khi load trang (giây)", "entry", None, "advanced"),
    ("RAWDL_SCROLL_WAIT_TIME", "Chờ giữa mỗi lần scroll (giây)", "entry", None, "advanced"),
    ("RAWDL_CHAPTER_DELAY", "Chờ giữa các chương (giây)", "entry", None, "advanced"),
    ("RAWDL_MAX_RETRY", "Số lần retry tối đa", "entry", None, "advanced"),
    ("RAWDL_RETRY_DELAY", "Chờ giữa các lần retry (giây)", "entry", None, "advanced"),
    ("RAWDL_ADV_EXTRA_WAIT_BEFORE", "Chờ thêm TRƯỚC khi xoá quảng cáo (giây)", "entry", None, "advanced"),
    ("RAWDL_ADV_EXTRA_WAIT_AFTER", "Chờ thêm SAU khi xoá quảng cáo (giây)", "entry", None, "advanced"),
    ("RAWDL_CROP_TOP_FIRST_PAGE", "Px cắt đầu trang 1", "entry", None, "advanced"),
    ("RAWDL_REMOVE_LAST_N_PAGES", "Số trang xoá cuối PDF", "entry", None, "advanced"),

    ("TEXTEXTRACT_MIN_WORD_COUNT", "Ngưỡng nghi ngờ file ngắn (số từ)", "entry", None, "advanced"),
    ("TEXTEXTRACT_ANOMALY_THRESHOLD", "Ngưỡng bất thường (0-1)", "entry", None, "advanced"),

    ("TEXTCLEANER_ADD_CHAPTER_NUMBER", "Tự thêm dòng 'Chương N' vào đầu file", "checkbox", None, "simple"),
    ("TEXTCLEANER_HEAVY_DELETE_THRESHOLD", "Ngưỡng cảnh báo cắt nhiều (%)", "entry", None, "advanced"),

    ("TITLEDEL_JUNK_PATTERNS", "Regex rác đầu chương (mỗi dòng 1 mẫu)", "multiline_list", None, "advanced"),

    ("TEXTMERGE_MERGE_SIZE", "Số chương mỗi file gộp (0 = gộp hết)", "entry", None, "advanced"),

    ("AUDIOGEN_VOICE", "Giọng đọc TTS", "dropdown_editable", ["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"], "simple"),
    ("AUDIOGEN_TTS_CONCURRENT", "Số luồng TTS song song", "dropdown_editable", ["1", "2", "3", "4", "5", "6"], "simple"),
    ("AUDIOGEN_MAX_WORKERS", "Số worker xử lý song song", "dropdown_editable", ["1", "2", "3", "4", "5", "6", "8", "10"], "simple"),
    ("AUDIOGEN_CHUNK_SIZE", "Số ký tự mỗi chunk TTS", "entry", None, "advanced"),
    ("AUDIOGEN_SENTENCE_SPLIT_REGEX", "Regex tách câu", "entry", None, "advanced"),
    ("AUDIOGEN_MAX_RETRY", "Số lần retry tối đa (TTS)", "entry", None, "advanced"),
    ("AUDIOGEN_RETRY_BASE_DELAY", "Delay retry cơ bản (giây)", "entry", None, "advanced"),
    ("AUDIOGEN_RETRY_BACKOFF", "Hệ số tăng delay mỗi lần retry", "entry", None, "advanced"),
    ("AUDIOGEN_DELAY_BETWEEN_CHUNKS", "Delay giữa các chunk (min, max giây)", "tuple_floats", None, "advanced"),
    ("AUDIOGEN_DELAY_BETWEEN_FILES", "Delay giữa các file (min, max giây)", "tuple_floats", None, "advanced"),
    ("AUDIOGEN_WORKER_STAGGER", "Delay giãn cách khởi động worker (giây)", "entry", None, "advanced"),
    ("AUDIOGEN_THROTTLE_KEYWORDS", "Từ khoá nhận diện bị throttle (mỗi dòng 1 từ)", "multiline_list", None, "advanced"),
    ("AUDIOGEN_THROTTLE_BASE_DELAY", "Delay cơ bản khi bị throttle (giây)", "entry", None, "advanced"),
    ("AUDIOGEN_THROTTLE_BACKOFF", "Delay tăng thêm khi bị throttle (giây)", "entry", None, "advanced"),
    ("AUDIOGEN_MAX_CHUNKS_PER_PART", "Số chunk tối đa mỗi file mp3 (0 = không giới hạn)", "entry", None, "advanced"),
    ("AUDIOGEN_SUPPORTED_EXT", "Đuôi file được hỗ trợ", "tuple_strs", None, "advanced"),

    ("AUDIOMERGE_OUTPUT_BITRATE", "Bitrate file mp3 gộp", "dropdown_strict", ["64k", "128k", "192k", "320k"], "simple"),
    ("AUDIOMERGE_SKIP_EXISTING", "Bỏ qua file đã gộp (an toàn khi bị kill giữa chừng)", "checkbox", None, "simple"),
    ("AUDIOMERGE_VERIFY_ENABLE", "Kiểm tra thời lượng sau khi gộp", "checkbox", None, "simple"),
    # ("AUDIOMERGE_OUTPUT_PREFIX", "Tiền tố tên file mp3 gộp", "entry", None, "advanced"),
    ("AUDIOMERGE_CHAPTERS_PER_GROUP", "Số chương tối đa mỗi file gộp (0 = không giới hạn)", "entry", None, "advanced"),
    ("AUDIOMERGE_MAX_DURATION_SECONDS", "Thời lượng tối đa mỗi file gộp (giây, 0=không giới hạn)", "entry", None, "advanced"),
    ("AUDIOMERGE_VERIFY_TOLERANCE", "Sai số cho phép khi verify (giây)", "entry", None, "advanced"),
]


# =============================================================================
# ===== ĐỌC / GHI config.py (giữ nguyên comment & cấu trúc, chỉ đổi giá trị) ==
# =============================================================================

def read_config_text():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def backup_config():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"config_{ts}.py.bak")
    shutil.copy2(CONFIG_PATH, dest)
    return dest


def set_scalar(content, varname, new_value_literal):
    """Thay giá trị của 1 dòng 'VARNAME = ...' (giữ nguyên mọi dòng khác)."""
    pattern = rf'(?m)^{re.escape(varname)}\s*=.*$'
    replacement = f'{varname} = {new_value_literal}'
    # QUAN TRỌNG: dùng hàm (không phải chuỗi) làm repl. Nếu truyền thẳng chuỗi,
    # re.sub tự diễn giải backslash trong đó theo cú pháp riêng của nó
    # (\1, \g<...>) và làm hỏng các giá trị có backslash thật, ví dụ regex
    # như AUDIOGEN_SENTENCE_SPLIT_REGEX. Hàm lambda trả nguyên văn, không bị
    # diễn giải lại.
    new_content, n = re.subn(pattern, lambda m: replacement, content, count=1)
    if n == 0:
        raise ValueError(f"Không tìm thấy biến {varname} trong config.py")
    return new_content


def set_list(content, varname, items):
    """Thay khối 'VARNAME = [ ... ]' bằng list chuỗi mới.

    Hỗ trợ cả 2 kiểu đang có trong config.py:
      - 1 dòng:     VARNAME = ["a", "b", "c"]
      - Nhiều dòng: VARNAME = [\n    "a",\n    "b",\n]  (']' đứng riêng 1 dòng)

    Dò ranh giới theo CẤU TRÚC dòng thay vì đếm ngoặc bằng regex — an toàn
    ngay cả khi bản thân item chứa ký tự ']' (thường gặp với regex character
    class kiểu [Aa]).
    """
    lines = content.split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(rf'^{re.escape(varname)}\s*=\s*\[', line):
            start_idx = i
            break
    if start_idx is None:
        raise ValueError(f"Không tìm thấy biến {varname} trong config.py")

    if lines[start_idx].rstrip().endswith("]"):
        # List gói gọn trên đúng 1 dòng — dòng mở cũng là dòng đóng
        end_idx = start_idx
    else:
        end_idx = None
        for j in range(start_idx + 1, len(lines)):
            if lines[j].strip() == "]" or lines[j].strip().startswith("]"):
                end_idx = j
                break
        if end_idx is None:
            raise ValueError(f"Không tìm thấy dòng đóng ']' cho biến {varname}")

    new_lines = [f"{varname} = ["] + [f"    {item!r}," for item in items] + ["]"]
    lines[start_idx:end_idx + 1] = new_lines
    return "\n".join(lines)


def coerce_value(raw, original_type):
    """Chuyển chuỗi nhập từ UI về đúng kiểu dữ liệu gốc của biến trong config.py."""
    raw = raw.strip()
    if original_type is bool:
        return raw.lower() in ("true", "1", "yes", "có", "bật")
    if original_type is int:
        return int(raw)
    if original_type is float:
        return float(raw)
    return raw


def list_existing_novels():
    data_root_abs = os.path.join(SCRIPT_DIR, config.DATA_ROOT)
    if not os.path.isdir(data_root_abs):
        return []
    try:
        return sorted(
            name for name in os.listdir(data_root_abs)
            if os.path.isdir(os.path.join(data_root_abs, name))
        )
    except Exception:
        return []


# =============================================================================
# ===== CONFIG RIÊNG THEO TỪNG TRUYỆN ==========================================
# =============================================================================
# config.py chỉ có 1 bộ giá trị "đang active" cho 9 script đọc. Để mỗi truyện
# nhớ được cấu hình riêng của nó (URL, số chương, giọng đọc...), GUI lưu thêm
# 1 file JSON trong Log/ của từng truyện — KHÔNG phải nơi 9 script đọc, chỉ để
# GUI tự nhớ và nạp lại đúng bộ giá trị mỗi khi chọn lại truyện đó.

def get_novel_config_path(novel_name):
    return os.path.join(SCRIPT_DIR, config.DATA_ROOT, novel_name, "Log", "pipeline_config.json")


def load_novel_config(novel_name):
    """Đọc config riêng đã lưu cho 1 truyện. None nếu truyện đó chưa từng
    được Lưu qua tính năng này (truyện mới, hoặc truyện có từ trước khi có
    tính năng này)."""
    path = get_novel_config_path(novel_name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_novel_config(novel_name, values):
    path = get_novel_config_path(novel_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False, indent=2, sort_keys=True)


# =============================================================================
# ===== ĐỌC / GHI TextCleaner_KeyWord.log ======================================
# =============================================================================
# Mirror đúng format mà TextCleaner.py tự đọc/ghi (load_keywords /
# rewrite_keyword_file) để 2 bên luôn tương thích — dù TextCleaner.py hay GUI
# ghi file này lần cuối, lần đọc sau (ở bên kia) vẫn hiểu đúng.

KEYWORD_FILE_HEADER = """\
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

_KEYWORD_SECTION_MARKERS = {
    "[DELETE]": "delete",
    "[KEEP]": "keep",
    "[UI_JUNK_WORDS]": "ui_junk_words",
    "[UI_JUNK_NUMBERS]": "ui_junk_numbers",
    "[SUSPECTED]": "suspected",
}

_DEFAULT_UI_JUNK_WORDS = ["gửi", "hủy", "sửa", "xóa", "đọc",
                          "cũ nhất", "mới nhất", "yêu thích", "-", "–", "—"]


def get_keyword_file_path():
    """Đường dẫn TextCleaner_KeyWord.log theo đúng LOG_DIR của truyện hiện tại."""
    return os.path.join(config.LOG_DIR, "TextCleaner_KeyWord.log")


def read_keyword_sections():
    """Đọc TextCleaner_KeyWord.log hiện có. Trả về (sections, ui_junk_numbers)
    — sections là dict 4 list (delete/keep/ui_junk_words/suspected), GIỮ
    NGUYÊN chữ hoa-thường và thứ tự như trong file (không chuẩn hoá) để hiển
    thị đúng những gì đang có. Nếu file chưa tồn tại (truyện mới, TextCleaner
    chưa chạy lần nào), trả về mặc định giống hệt TextCleaner.py tự tạo."""
    path = get_keyword_file_path()
    sections = {"delete": [], "keep": [], "ui_junk_words": [], "suspected": []}
    ui_junk_numbers = True

    if not os.path.exists(path):
        sections["ui_junk_words"] = list(_DEFAULT_UI_JUNK_WORDS)
        return sections, ui_junk_numbers

    section = None
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line in _KEYWORD_SECTION_MARKERS:
                section = _KEYWORD_SECTION_MARKERS[line]
                continue
            if section == "ui_junk_numbers":
                ui_junk_numbers = (line.lower() != "disabled")
            elif section in sections:
                sections[section].append(line)

    return sections, ui_junk_numbers


def _dedup_preserve_order(lines, case_insensitive=True):
    seen = set()
    out = []
    for ln in lines:
        key = ln.lower() if case_insensitive else ln
        if ln and key not in seen:
            seen.add(key)
            out.append(ln)
    return out


def write_keyword_sections(delete_lines, keep_lines, ui_junk_words_lines, ui_junk_numbers, suspected_lines):
    """Ghi lại TextCleaner_KeyWord.log theo đúng format TextCleaner.py dùng —
    backup timestamp trước khi ghi đè, giống cơ chế của config.py."""
    path = get_keyword_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if os.path.exists(path):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, os.path.join(BACKUP_DIR, f"TextCleaner_KeyWord_{ts}.log.bak"))

    with open(path, "w", encoding="utf-8") as f:
        f.write(KEYWORD_FILE_HEADER)

        f.write("[DELETE]\n")
        for k in _dedup_preserve_order(delete_lines):
            f.write(k + "\n")
        f.write("\n")

        f.write("[KEEP]\n")
        for k in _dedup_preserve_order(keep_lines):
            f.write(k + "\n")
        f.write("\n")

        f.write("[UI_JUNK_WORDS]\n")
        for k in _dedup_preserve_order(ui_junk_words_lines):
            f.write(k + "\n")
        f.write("\n")

        f.write("[UI_JUNK_NUMBERS]\n")
        f.write("enabled\n" if ui_junk_numbers else "disabled\n")
        f.write("\n")

        f.write("[SUSPECTED]\n")
        for k in _dedup_preserve_order(suspected_lines, case_insensitive=False):
            f.write(k + "\n")


# =============================================================================
# ===== KHUNG CUỘN DÙNG CHUNG ==================================================
# =============================================================================

def make_scrollable(parent):
    """Trả về 1 Frame bên trong, cuộn được, đã pack Canvas+Scrollbar vào parent."""
    canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
    vscroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas)

    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
    canvas.configure(yscrollcommand=vscroll.set)

    canvas.pack(side="left", fill="both", expand=True)
    vscroll.pack(side="right", fill="y")

    def _on_mousewheel(event):
        delta = -1 * (event.delta // 120) if event.delta else 0
        canvas.yview_scroll(int(delta), "units")

    def _bind(_event):
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

    def _unbind(_event):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    canvas.bind("<Enter>", _bind)
    canvas.bind("<Leave>", _unbind)

    return inner


# =============================================================================
# ===== TAB CONFIG =============================================================
# =============================================================================

class ConfigTab(ttk.Frame):
    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self.on_saved = on_saved
        self.field_widgets = {}
        self._build_ui()
        self._load_values()

    # ---------- Xây UI ----------

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="Truyện hiện tại:", font=("", 10, "bold")).pack(side="left")
        self.novel_var = tk.StringVar()
        self.novel_combo = ttk.Combobox(top, textvariable=self.novel_var, state="readonly", width=42)
        self.novel_combo.pack(side="left", padx=8)
        self.novel_combo.bind("<<ComboboxSelected>>", self._on_novel_selected)

        ttk.Label(
            self,
            text="Đổi truyện rồi bấm Lưu để chuyển TOÀN BỘ pipeline sang truyện đó "
                 "(tự tạo Data/<tên truyện>/ nếu là truyện mới).",
            foreground="#555",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True, padx=10)
        columns.columnconfigure(0, weight=1, uniform="col")
        columns.columnconfigure(1, weight=1, uniform="col")
        columns.rowconfigure(0, weight=1)

        simple_outer = ttk.LabelFrame(columns, text="Cấu hình đơn giản  (chọn từ danh sách)")
        simple_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        advanced_outer = ttk.LabelFrame(columns, text="Cấu hình nâng cao  (tự nhập giá trị)")
        advanced_outer.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self.simple_inner = make_scrollable(simple_outer)
        self.advanced_inner = make_scrollable(advanced_outer)

        self._build_fields()

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=8)
        ttk.Button(bottom, text="💾 Lưu cấu hình", command=self._save).pack(side="right")
        self.save_status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.save_status_var, foreground="#2a7d2a").pack(side="right", padx=10)

    def _build_fields(self):
        section_frames = {"simple": {}, "advanced": {}}
        for varname, label, kind, options, section in FIELD_SPECS:
            prefix = varname.split("_")[0]
            script_label = SECTION_TITLES.get(prefix, "Khác")
            frames = section_frames[section]
            if script_label not in frames:
                container = self.simple_inner if section == "simple" else self.advanced_inner
                frame = ttk.LabelFrame(container, text=script_label)
                frame.pack(fill="x", padx=6, pady=6, anchor="n")
                frames[script_label] = frame
            self._add_field_row(frames[script_label], varname, label, kind, options)

    def _add_field_row(self, frame, varname, label, kind, options):
        row = ttk.Frame(frame)
        row.pack(fill="x", padx=6, pady=3)

        original_value = getattr(config, varname, None)
        original_type = type(original_value) if original_value is not None else str

        if kind == "checkbox":
            var = tk.BooleanVar()
            ttk.Checkbutton(row, text=label, variable=var).pack(anchor="w")
            self.field_widgets[varname] = {"kind": kind, "var": var, "original_type": bool}

        elif kind in ("dropdown_strict", "dropdown_editable"):
            ttk.Label(row, text=label).pack(anchor="w")
            var = tk.StringVar()
            state = "readonly" if kind == "dropdown_strict" else "normal"
            ttk.Combobox(row, textvariable=var, values=options, state=state, width=30).pack(anchor="w", fill="x")
            self.field_widgets[varname] = {"kind": kind, "var": var, "original_type": original_type}

        elif kind == "entry":
            ttk.Label(row, text=label).pack(anchor="w")
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=34).pack(anchor="w", fill="x")
            self.field_widgets[varname] = {"kind": kind, "var": var, "original_type": original_type}

        elif kind == "multiline_list":
            ttk.Label(row, text=label).pack(anchor="w")
            text_widget = tk.Text(row, height=4, width=34, font=("Consolas", 9))
            text_widget.pack(anchor="w", fill="x")
            self.field_widgets[varname] = {"kind": kind, "text_widget": text_widget}

        elif kind in ("tuple_floats", "tuple_strs"):
            ttk.Label(row, text=label + "  (cách nhau bởi dấu phẩy)").pack(anchor="w")
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=34).pack(anchor="w", fill="x")
            self.field_widgets[varname] = {"kind": kind, "var": var}

    # ---------- Nạp / lưu giá trị ----------

    def _refresh_novel_list(self):
        novels = list_existing_novels()
        current = getattr(config, "NOVEL_NAME", "")
        values = list(novels)
        if current and current not in values:
            values.insert(0, current)
        values.append(ADD_NEW_SENTINEL)
        self.novel_combo["values"] = values
        self.novel_var.set(current)

    def _on_novel_selected(self, _event):
        selected = self.novel_var.get()

        if selected == ADD_NEW_SENTINEL:
            current = getattr(config, "NOVEL_NAME", "")
            name = simpledialog.askstring("Thêm truyện mới", "Tên truyện mới:", parent=self)
            if name:
                name = name.strip()
            if not name:
                self.novel_var.set(current)
                return
            bad = INVALID_FOLDER_CHARS & set(name)
            if bad:
                messagebox.showerror("Tên không hợp lệ", f"Tên truyện không được chứa: {' '.join(sorted(bad))}", parent=self)
                self.novel_var.set(current)
                return
            values = [v for v in self.novel_combo["values"] if v != ADD_NEW_SENTINEL]
            if name not in values:
                values.append(name)
            values.append(ADD_NEW_SENTINEL)
            self.novel_combo["values"] = values
            self.novel_var.set(name)
            # Truyện mới -> KHÔNG tải gì, giữ nguyên các trường đang hiển thị
            # làm mẫu tạm thời. Bấm Lưu sẽ tạo config riêng cho truyện này.
            self.save_status_var.set(f"📄 Truyện mới — đang dùng tạm cấu hình hiện có, bấm Lưu để tạo riêng cho \"{name}\"")
            return

        # Truyện đã có sẵn trong danh sách -> tải config riêng của truyện đó
        # (nếu đã từng Lưu qua tính năng này).
        self._load_values_for_novel(selected)

    def _apply_value_to_widget(self, varname, value):
        widget_info = self.field_widgets.get(varname)
        if not widget_info:
            return
        kind = widget_info["kind"]
        if kind == "checkbox":
            widget_info["var"].set(bool(value))
        elif kind in ("dropdown_strict", "dropdown_editable", "entry"):
            widget_info["var"].set("" if value is None else str(value))
        elif kind == "multiline_list":
            tw = widget_info["text_widget"]
            tw.delete("1.0", "end")
            tw.insert("1.0", "\n".join(str(v) for v in (value or [])))
        elif kind in ("tuple_floats", "tuple_strs"):
            widget_info["var"].set(", ".join(str(v) for v in (value or ())))

    def _load_values_for_novel(self, novel_name):
        """Chọn 1 truyện khác trong dropdown -> nạp config riêng đã lưu của
        truyện đó vào form. Nếu truyện đó chưa từng được Lưu qua tính năng
        này (truyện có từ trước, hoặc chưa Lưu lần nào), GIỮ NGUYÊN các
        trường đang hiển thị — coi như dùng tạm cấu hình hiện có."""
        novel_config = load_novel_config(novel_name)
        if novel_config is None:
            self.save_status_var.set(f"📄 \"{novel_name}\" chưa có config riêng — đang dùng tạm cấu hình hiện có")
            return
        for varname in self.field_widgets:
            if varname in novel_config:
                self._apply_value_to_widget(varname, novel_config[varname])
        self.save_status_var.set(f"📂 Đã tải config riêng của \"{novel_name}\"")

    def _load_values(self):
        self._refresh_novel_list()
        for varname in self.field_widgets:
            self._apply_value_to_widget(varname, getattr(config, varname, None))

        # Bootstrap: nếu truyện đang active chưa từng có config riêng (vd lần
        # đầu dùng tính năng này), tự tạo từ giá trị hiện tại trong config.py
        # -> sau này chuyển sang truyện khác rồi quay lại vẫn khôi phục đúng.
        current_novel = getattr(config, "NOVEL_NAME", "")
        if current_novel and load_novel_config(current_novel) is None:
            snapshot = {}
            for varname, label, kind, options, section in FIELD_SPECS:
                value = getattr(config, varname, None)
                if kind in ("tuple_floats", "tuple_strs") and value is not None:
                    value = list(value)
                snapshot[varname] = value
            try:
                save_novel_config(current_novel, snapshot)
            except Exception:
                pass  # không chặn khởi động GUI nếu ghi lỗi -- Lưu tay vẫn hoạt động bình thường

    def _save(self):
        novel_name = self.novel_var.get().strip()
        if not novel_name or novel_name == ADD_NEW_SENTINEL:
            messagebox.showerror("Thiếu tên truyện", "Vui lòng chọn hoặc thêm tên truyện trước khi lưu.", parent=self)
            return

        try:
            content = read_config_text()
        except Exception as exc:
            messagebox.showerror("Lỗi đọc config.py", str(exc), parent=self)
            return

        novel_values = {}   # gom lại để lưu riêng cho novel_name, song song với việc ghi config.py

        try:
            content = set_scalar(content, "NOVEL_NAME", repr(novel_name))

            for varname, widget_info in self.field_widgets.items():
                kind = widget_info["kind"]
                label = next(f[1] for f in FIELD_SPECS if f[0] == varname)

                if kind == "checkbox":
                    value = bool(widget_info["var"].get())
                    content = set_scalar(content, varname, repr(value))
                    novel_values[varname] = value

                elif kind in ("dropdown_strict", "dropdown_editable", "entry"):
                    raw = widget_info["var"].get()
                    try:
                        coerced = coerce_value(raw, widget_info["original_type"])
                    except ValueError:
                        raise ValueError(
                            f"Giá trị không hợp lệ cho '{label}': '{raw}' "
                            f"(cần kiểu {widget_info['original_type'].__name__})"
                        )
                    content = set_scalar(content, varname, repr(coerced))
                    novel_values[varname] = coerced

                elif kind == "multiline_list":
                    raw_text = widget_info["text_widget"].get("1.0", "end").strip()
                    items = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
                    content = set_list(content, varname, items)
                    novel_values[varname] = items

                elif kind == "tuple_floats":
                    raw = widget_info["var"].get()
                    parts = [p.strip() for p in raw.split(",") if p.strip()]
                    try:
                        nums = tuple(float(p) for p in parts)
                    except ValueError:
                        raise ValueError(f"Giá trị không hợp lệ cho '{label}': '{raw}' (cần các số cách nhau bởi dấu phẩy)")
                    content = set_scalar(content, varname, repr(nums))
                    novel_values[varname] = list(nums)

                elif kind == "tuple_strs":
                    raw = widget_info["var"].get()
                    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
                    content = set_scalar(content, varname, repr(parts))
                    novel_values[varname] = list(parts)

        except ValueError as exc:
            messagebox.showerror("Giá trị không hợp lệ", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror("Lỗi khi xử lý cấu hình", str(exc), parent=self)
            return

        try:
            backup_config()
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as exc:
            messagebox.showerror("Lỗi khi ghi config.py", str(exc), parent=self)
            return

        try:
            save_novel_config(novel_name, novel_values)
        except Exception as exc:
            messagebox.showwarning(
                "Cảnh báo",
                f"Đã lưu config.py nhưng lưu config riêng cho \"{novel_name}\" bị lỗi: {exc}\n"
                f"config.py vẫn đúng, chỉ là lần sau chọn lại truyện này có thể không tự khôi phục.",
                parent=self,
            )

        try:
            importlib.reload(config)
        except Exception as exc:
            messagebox.showwarning(
                "Cảnh báo",
                f"Đã lưu config.py nhưng reload lỗi: {exc}\nNên khởi động lại chương trình để chắc chắn áp dụng đúng.",
                parent=self,
            )

        self._load_values()
        self.save_status_var.set("✅ Đã lưu lúc " + datetime.now().strftime("%H:%M:%S"))
        if self.on_saved:
            self.on_saved()


# =============================================================================
# ===== TAB CHO 1 SCRIPT (Start / Stop / Log realtime) =========================
# =============================================================================

MAX_LOG_LINES = 4000


class ScriptTab(ttk.Frame):
    def __init__(self, parent, script_filename):
        super().__init__(parent)
        self.script_filename = script_filename
        self.proc = None
        self.reader_thread = None
        self.log_queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=8)

        self.start_btn = ttk.Button(toolbar, text="▶ Start", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(toolbar, text="■ Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="🧹 Xoá log", command=self._clear_log).pack(side="left", padx=(6, 0))

        self.status_var = tk.StringVar(value="Chưa chạy")
        ttk.Label(toolbar, textvariable=self.status_var, foreground="#555").pack(side="left", padx=14)

        ttk.Label(toolbar, text=self.script_filename, font=("", 9, "bold")).pack(side="right")

        # Progress riêng cho AudioGenerator khi chạy qua GUI.
        self.progress_rows = {}
        self.progress_frame = None
        self.progress_done_var = tk.StringVar(value="✅ 0    ❌ 0    ⏭ 0")
        if self.script_filename == "AudioGenerator.py":
            outer = ttk.LabelFrame(self, text="🔊 AudioGenerator — Progress")
            outer.pack(fill="x", padx=8, pady=(0, 8))
            self.progress_frame = outer
            max_workers = max(1, int(getattr(config, "AUDIOGEN_MAX_WORKERS", 1)))
            for wid in range(max_workers):
                row = ttk.Frame(outer)
                row.pack(fill="x", padx=6, pady=2)
                ttk.Label(row, text=f"W{wid}", width=4).pack(side="left")
                file_var = tk.StringVar(value="—")
                phase_var = tk.StringVar(value="idle")
                pct_var = tk.StringVar(value="0.0%")
                ttk.Label(row, textvariable=file_var, width=24, anchor="w").pack(side="left", padx=(0, 5))
                ttk.Label(row, textvariable=phase_var, width=10, anchor="w").pack(side="left", padx=(0, 5))
                pb = ttk.Progressbar(row, orient="horizontal", mode="determinate", maximum=100, value=0)
                pb.pack(side="left", fill="x", expand=True, padx=(0, 5))
                ttk.Label(row, textvariable=pct_var, width=8, anchor="e").pack(side="right")
                self.progress_rows[wid] = {"file": file_var, "phase": phase_var, "pct": pct_var, "bar": pb}
            ttk.Label(outer, textvariable=self.progress_done_var, anchor="w").pack(fill="x", padx=6, pady=(3, 5))

        if self.script_filename == "TextCleaner.py":
            # Keyword editor riêng cho TextCleaner: DELETE/KEEP/UI_JUNK_WORDS/checkbox
            # ở trên (cao vừa đủ), SUSPECTED + Log chia đôi trái/phải bên dưới, chiếm
            # hết phần còn lại của tab.
            self._build_keyword_editor()
            self._build_suspected_and_log_pane()
            self._load_keyword_editor()
        else:
            log_frame = ttk.Frame(self)
            log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            self._build_log_widget(log_frame)

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _build_log_widget(self, parent):
        """Tạo khung log (Text + Scrollbar) bên trong `parent`, gán vào self.log_text.
        Dùng chung cho layout thường (full-width, 8 tab kia) và layout chia đôi
        (TextCleaner, cột phải của PanedWindow)."""
        self.log_text = tk.Text(
            parent, state="disabled", wrap="word", font=("Consolas", 9),
            background="#111318", foreground="#dddddd", insertbackground="#dddddd",
        )
        vscroll = ttk.Scrollbar(parent, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vscroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

    def _build_suspected_and_log_pane(self):
        """SUSPECTED (trái) + Log (phải) trong 1 PanedWindow ngang — kéo được để
        đổi tỉ lệ, cả 2 bên cùng chiếm hết chiều cao còn lại của tab."""
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(pane)
        ttk.Label(
            left,
            text="SUSPECTED — dòng lặp nhiều lần TextCleaner tự phát hiện, chưa xếp loại. "
                 "Cắt/dán sang DELETE hoặc KEEP ở trên rồi xoá khỏi đây.",
            wraplength=380, foreground="#555",
        ).pack(anchor="w", padx=4, pady=(4, 2))
        self.kw_suspected_text = tk.Text(left, font=("Consolas", 9), wrap="word")
        susp_scroll = ttk.Scrollbar(left, orient="vertical", command=self.kw_suspected_text.yview)
        self.kw_suspected_text.configure(yscrollcommand=susp_scroll.set)
        self.kw_suspected_text.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        susp_scroll.pack(side="right", fill="y", pady=(0, 4))
        pane.add(left, weight=1)

        right = ttk.Frame(pane)
        self._build_log_widget(right)
        pane.add(right, weight=1)

    def _build_keyword_editor(self):
        outer = ttk.LabelFrame(self, text="🔑 Keyword (TextCleaner_KeyWord.log) — theo truyện hiện tại")
        outer.pack(fill="x", padx=8, pady=(0, 8))

        cols = ttk.Frame(outer)
        cols.pack(fill="x", padx=6, pady=6)
        cols.columnconfigure(0, weight=1, uniform="kwcol")
        cols.columnconfigure(1, weight=1, uniform="kwcol")
        cols.columnconfigure(2, weight=1, uniform="kwcol")

        self.kw_delete_text = self._make_kw_column(cols, 0, "DELETE — xoá dòng CHỨA từ này")
        self.kw_keep_text   = self._make_kw_column(cols, 1, "KEEP — giữ lại dù trùng DELETE")
        self.kw_junk_text   = self._make_kw_column(cols, 2, "UI_JUNK_WORDS — khớp ĐÚNG cả dòng")

        mid = ttk.Frame(outer)
        mid.pack(fill="x", padx=6, pady=(0, 4))
        self.kw_numbers_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            mid, text="Tự xoá dòng chỉ chứa 1 số (UI_JUNK_NUMBERS) — tắt nếu truyện dùng số đơn để đánh dấu phân cảnh",
            variable=self.kw_numbers_var,
        ).pack(anchor="w")

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", padx=6, pady=(4, 6))
        ttk.Button(btn_row, text="🔄 Tải lại", command=self._load_keyword_editor).pack(side="left")
        ttk.Button(btn_row, text="💾 Lưu keyword", command=self._save_keyword_editor).pack(side="left", padx=(6, 0))
        self.kw_status_var = tk.StringVar(value="")
        ttk.Label(btn_row, textvariable=self.kw_status_var, foreground="#2a7d2a").pack(side="left", padx=10)

    @staticmethod
    def _make_kw_column(parent, col, label):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=col, sticky="nsew", padx=4)
        ttk.Label(frame, text=label, wraplength=220).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="both", expand=True)
        text = tk.Text(row, height=8, width=28, font=("Consolas", 9))
        scroll = ttk.Scrollbar(row, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return text

    @staticmethod
    def _set_kw_text(widget, lines):
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines))

    @staticmethod
    def _get_kw_lines(widget):
        return [ln.strip() for ln in widget.get("1.0", "end").splitlines() if ln.strip()]

    def _load_keyword_editor(self):
        try:
            sections, ui_junk_numbers = read_keyword_sections()
        except Exception as exc:
            messagebox.showerror("Lỗi đọc keyword", str(exc), parent=self)
            return
        self._set_kw_text(self.kw_delete_text, sections["delete"])
        self._set_kw_text(self.kw_keep_text, sections["keep"])
        self._set_kw_text(self.kw_junk_text, sections["ui_junk_words"])
        self._set_kw_text(self.kw_suspected_text, sections["suspected"])
        self.kw_numbers_var.set(ui_junk_numbers)
        self.kw_status_var.set("")

    def _save_keyword_editor(self):
        try:
            write_keyword_sections(
                delete_lines=self._get_kw_lines(self.kw_delete_text),
                keep_lines=self._get_kw_lines(self.kw_keep_text),
                ui_junk_words_lines=self._get_kw_lines(self.kw_junk_text),
                ui_junk_numbers=bool(self.kw_numbers_var.get()),
                suspected_lines=self._get_kw_lines(self.kw_suspected_text),
            )
        except Exception as exc:
            messagebox.showerror("Lỗi lưu keyword", str(exc), parent=self)
            return
        self.kw_status_var.set("✅ Đã lưu lúc " + datetime.now().strftime("%H:%M:%S"))
        self._load_keyword_editor()
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    # ---------- Start / Stop ----------

    def start(self):
        if self.proc is not None:
            return
        script_path = os.path.join(SCRIPT_DIR, self.script_filename)
        if not os.path.isfile(script_path):
            messagebox.showerror("Không tìm thấy file", f"Không thấy {self.script_filename} trong:\n{SCRIPT_DIR}", parent=self)
            return

        if not PYTHON_EXE:
            messagebox.showerror(
                "Không tìm thấy Python",
                "Không dò được python.exe/py.exe trên máy để chạy script này.\n\n"
                "Pipeline vẫn cần cài Python thật (kèm đủ thư viện: fitz, edge_tts,\n"
                "selenium, rich, docx2txt...) và có trong PATH — gui.exe chỉ là\n"
                "giao diện điều khiển, không tự chạy được các script .py.",
                parent=self,
            )
            return

        self._append_log(f"\n{'=' * 70}\n▶ BẮT ĐẦU  {self.script_filename}   —   {datetime.now():%Y-%m-%d %H:%M:%S}\n{'=' * 70}\n")

        popen_kwargs = {}
        if platform.system() == "Windows":
            # CREATE_NEW_PROCESS_GROUP: để Stop dùng taskkill /T diệt được cả cây
            # tiến trình con (chromedriver, ffmpeg, worker...).
            # CREATE_NO_WINDOW: không cho hiện cửa sổ cmd đen cho tiến trình con —
            # quan trọng khi gui đã đóng gói --windowed (không có console riêng).
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        try:
            self.proc = subprocess.Popen(
                [PYTHON_EXE, "-u", self.script_filename],
                cwd=SCRIPT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                **popen_kwargs,
            )
        except Exception as exc:
            self._append_log(f"❌ Không khởi động được: {exc}\n")
            return

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("● Đang chạy...")


        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

    def _read_output(self):
        proc = self.proc
        try:
            for line in proc.stdout:
                self.log_queue.put(line)
        except Exception:
            pass
        finally:
            self.log_queue.put(None)

    def _poll_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item is None:
                    self._on_finished()
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _on_finished(self):
        if self.proc is None:
            return
        returncode = self.proc.poll()
        if returncode is None:
            try:
                returncode = self.proc.wait(timeout=2)
            except Exception:
                returncode = "?"
        self._append_log(
            f"\n{'=' * 70}\n⏹ KẾT THÚC  {self.script_filename}   (mã thoát: {returncode})   "
            f"—   {datetime.now():%Y-%m-%d %H:%M:%S}\n{'=' * 70}\n"
        )
        self.proc = None
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Đã dừng")
        if self.script_filename == "TextCleaner.py" and hasattr(self, "_load_keyword_editor"):
            self._load_keyword_editor()

    def stop(self):
        if self.proc is None:
            return
        self._append_log("\n⏹ Đang dừng tiến trình (và các tiến trình con)...\n")
        pid = self.proc.pid
        try:
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception as exc:
            self._append_log(f"⚠ Lỗi khi dừng: {exc}\n")

    def is_running(self):
        return self.proc is not None

    # ---------- Progress từ AudioGenerator ----------

    def _handle_progress_line(self, line):
        if self.script_filename != "AudioGenerator.py":
            return False
        marker = "@@AUDIOGEN_PROGRESS@@|"
        if not line.startswith(marker):
            return False
        try:
            parts = line.strip().split("|")
            if len(parts) < 10:
                return True
            _, wid_s, file_name, phase, cur_s, total_s, done_s, fail_s, skip_s, total_files_s = parts[:10]
            wid = int(wid_s)
            current = int(cur_s)
            total = max(int(total_s), 1)
            if wid in self.progress_rows:
                pct = max(0.0, min(100.0, current * 100.0 / total))
                try:
                    display_file_name = file_name.encode("ascii").decode("unicode_escape")
                except Exception:
                    display_file_name = file_name
                row = self.progress_rows[wid]
                row["file"].set(display_file_name or "—")
                row["phase"].set(phase)
                row["pct"].set(f"{pct:5.1f}%")
                row["bar"]["value"] = pct
            self.progress_done_var.set(
                f"✅ {int(done_s)}    ❌ {int(fail_s)}    ⏭ {int(skip_s)}    / {total_files_s} files"
            )
            return True
        except Exception:
            return True

    # ---------- Log ----------

    def _append_log(self, text):
        # Progress marker của AudioGenerator được đưa vào progress bar riêng.
        visible_lines = []
        for line in text.splitlines(True):
            raw = line.rstrip("\r\n")
            if self._handle_progress_line(raw):
                continue
            visible_lines.append(line)

        text = "".join(visible_lines)
        if not text:
            return

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.log_text.config(state="normal")
        self.log_text.insert("end", text)
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{line_count - MAX_LOG_LINES}.0")
        self.log_text.see("end")
        self.log_text.config(state="disabled")


# =============================================================================
# ===== APP CHÍNH ==============================================================
# =============================================================================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Novel-to-Audio Pipeline — {getattr(config, 'NOVEL_NAME', '')}")
        self.geometry("1180x780")
        self.minsize(960, 620)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.config_tab = ConfigTab(self.notebook, on_saved=self._on_config_saved)
        self.notebook.add(self.config_tab, text="⚙️ Config")

        self.script_tabs = []
        for label, filename in PIPELINE_SCRIPTS:
            tab = ScriptTab(self.notebook, filename)
            self.notebook.add(tab, text=label)
            self.script_tabs.append(tab)

        status_bar = ttk.Frame(self, relief="sunken")
        status_bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar()
        ttk.Label(status_bar, textvariable=self.status_var, anchor="w", padding=(8, 3)).pack(side="left")
        self._refresh_status_bar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _refresh_status_bar(self):
        novel = getattr(config, "NOVEL_NAME", "?")
        self.status_var.set(f"📖 Truyện hiện tại: {novel}    📁 {os.path.join(config.DATA_ROOT, novel)}")

    def _on_config_saved(self):
        self._refresh_status_bar()
        self.title(f"Novel-to-Audio Pipeline — {getattr(config, 'NOVEL_NAME', '')}")
        for tab in self.script_tabs:
            if hasattr(tab, "_load_keyword_editor"):
                tab._load_keyword_editor()

    def _on_close(self):
        running = [t for t in self.script_tabs if t.is_running()]
        if running:
            names = ", ".join(t.script_filename for t in running)
            if not messagebox.askyesno(
                "Vẫn còn tiến trình đang chạy",
                f"Các script sau vẫn đang chạy:\n{names}\n\nDừng tất cả và thoát?",
                parent=self,
            ):
                return
            for t in running:
                t.stop()
        self.destroy()


def main():
    try:
        app = App()
    except Exception as exc:
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showerror("Lỗi khởi động", str(exc))
        return
    app.mainloop()


if __name__ == "__main__":
    main()