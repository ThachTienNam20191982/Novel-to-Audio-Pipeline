"""
gui.py — Bảng điều khiển cho toàn bộ pipeline Novel-to-Audio.

Chạy:  python gui.py
Yêu cầu: file này nằm CÙNG thư mục với config.py và 9 file script
         (RawDowloader.py, TextExtractor.py, TextCheck.py, TextCleaner.py,
          TitleDelete.py, TextSplit.py, TextMerge.py, AudioGenerator.py,
          AudioMerger.py).

Tab "⚙️ Config" đọc/ghi trực tiếp config.py (có backup timestamp trước khi
ghi đè). Mỗi tab script còn lại chạy file .py tương ứng như 1 tiến trình con
riêng biệt (python <file>.py), hiển thị log thực tế theo thời gian thực,
và có thể Start/Stop độc lập.
"""

import os
import re
import sys
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
# Luôn tính đường dẫn tương đối theo đúng thư mục chứa gui.py, bất kể chương
# trình được khởi chạy từ đâu (double-click, shortcut, terminal ở thư mục khác...)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

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
        if self.novel_var.get() != ADD_NEW_SENTINEL:
            return
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

    def _load_values(self):
        self._refresh_novel_list()
        for varname, widget_info in self.field_widgets.items():
            value = getattr(config, varname, None)
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

        try:
            content = set_scalar(content, "NOVEL_NAME", repr(novel_name))

            for varname, widget_info in self.field_widgets.items():
                kind = widget_info["kind"]
                label = next(f[1] for f in FIELD_SPECS if f[0] == varname)

                if kind == "checkbox":
                    content = set_scalar(content, varname, repr(bool(widget_info["var"].get())))

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

                elif kind == "multiline_list":
                    raw_text = widget_info["text_widget"].get("1.0", "end").strip()
                    items = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
                    content = set_list(content, varname, items)

                elif kind == "tuple_floats":
                    raw = widget_info["var"].get()
                    parts = [p.strip() for p in raw.split(",") if p.strip()]
                    try:
                        nums = tuple(float(p) for p in parts)
                    except ValueError:
                        raise ValueError(f"Giá trị không hợp lệ cho '{label}': '{raw}' (cần các số cách nhau bởi dấu phẩy)")
                    content = set_scalar(content, varname, repr(nums))

                elif kind == "tuple_strs":
                    raw = widget_info["var"].get()
                    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
                    content = set_scalar(content, varname, repr(parts))

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

        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.log_text = tk.Text(
            log_frame, state="disabled", wrap="word", font=("Consolas", 9),
            background="#111318", foreground="#dddddd", insertbackground="#dddddd",
        )
        vscroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vscroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

    def _clear_log(self):
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

        self._append_log(f"\n{'=' * 70}\n▶ BẮT ĐẦU  {self.script_filename}   —   {datetime.now():%Y-%m-%d %H:%M:%S}\n{'=' * 70}\n")

        popen_kwargs = {}
        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-u", self.script_filename],
                cwd=SCRIPT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
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