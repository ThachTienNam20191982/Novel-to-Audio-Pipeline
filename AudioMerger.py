import os
import re
import subprocess
import logging
import json
from datetime import datetime

# =============================================================================
# CONFIG
# =============================================================================

INPUT_DIR  = "Audio"       # Thư mục chứa file .mp3 từ AudioGenerator
OUTPUT_DIR = "Merged"      # Thư mục xuất file đã merge
LOG_DIR    = "Log"
LOG_FILE   = os.path.join(LOG_DIR, "AudioMerger_log.log")

# --- Chiến lược nhóm ---
# Số chương tối đa trong 1 file merged (0 = không giới hạn, chỉ dùng MAX_DURATION_SECONDS)
CHAPTERS_PER_GROUP = 100

# Thời lượng tối đa (giây) của 1 file merged (0 = không giới hạn, chỉ dùng CHAPTERS_PER_GROUP)
# Ví dụ: 3600 = 1 giờ, 5400 = 1.5 giờ, 7200 = 2 giờ
MAX_DURATION_SECONDS = 36000

# Khi CẢ HAI đều được đặt (> 0): dừng nhóm khi THỎA MÃN 1 trong 2 điều kiện
# Khi CHỈ 1 điều kiện được đặt (> 0): chỉ dùng điều kiện đó
# Khi CẢ HAI = 0: mỗi nhóm chứa toàn bộ file (merge tất cả thành 1)

# --- Bitrate output ---
OUTPUT_BITRATE = "192k"    # Bitrate file merged (64k / 128k / 192k / 320k)

# --- Tên file output ---
# Ví dụ: OUTPUT_PREFIX = "Truyen" → Truyen_Chuong_001-010.mp3
OUTPUT_PREFIX = "Merged"

# --- Resume ---
# True  = bỏ qua file merged đã tồn tại (an toàn khi bị kill giữa chừng)
# False = luôn tạo lại từ đầu
SKIP_EXISTING = True

# --- Verify merge ---
# Kiểm tra tổng thời lượng sau khi merge, cho phép sai số VERIFY_TOLERANCE giây
VERIFY_ENABLE    = True
VERIFY_TOLERANCE = 2.0     # giây

# --- Tên file state (để resume khi bị kill) ---
STATE_FILE = os.path.join(LOG_DIR, "AudioMerger_state.json")

# =============================================================================
# BOOTSTRAP
# =============================================================================

def _bootstrap():
    for d in (OUTPUT_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)

# =============================================================================
# LOGGER
# =============================================================================

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("AudioMerger")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(fh)

    return logger

# =============================================================================
# STATE (resume khi bị kill)
# =============================================================================

def _load_state() -> dict:
    """Đọc state từ file JSON, trả về dict rỗng nếu không có."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict):
    """Ghi state xuống file JSON (overwrite)."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _mark_done(state: dict, group_key: str, output_file: str):
    state[group_key] = {"done": True, "output": output_file}
    _save_state(state)


def _is_done(state: dict, group_key: str) -> bool:
    return state.get(group_key, {}).get("done", False)

# =============================================================================
# FFMPEG UTILS
# =============================================================================

def get_duration(path: str) -> float:
    """Lấy thời lượng (giây) của file audio bằng ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def is_audio_valid(path: str) -> bool:
    """Kiểm tra file audio có hợp lệ không bằng ffmpeg."""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return r.returncode == 0


def merge_files(input_paths: list, output_path: str, logger: logging.Logger) -> bool:
    """
    Merge danh sách file mp3 thành 1 file output bằng ffmpeg concat.
    Trả về True nếu thành công.
    """
    # Tạo file list tạm trong LOG_DIR để tránh xung đột
    list_file = os.path.join(LOG_DIR, "_merge_list_tmp.txt")
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for p in input_paths:
                abs_p = os.path.abspath(p)
                f.write(f"file '{abs_p}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-acodec", "libmp3lame", "-ab", OUTPUT_BITRATE,
            output_path
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            logger.error("ffmpeg error:\n%s", result.stderr[-1000:])
            return False

        return True

    except Exception as exc:
        logger.error("merge_files exception: %s", exc)
        return False

    finally:
        if os.path.exists(list_file):
            try:
                os.remove(list_file)
            except Exception:
                pass

# =============================================================================
# NATURAL SORT
# =============================================================================

def natural_sort_key(s: str):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', s)]

# =============================================================================
# GROUP BUILDER
# =============================================================================

def build_groups(files_with_dur: list) -> list:
    """
    Chia danh sách (filename, duration) thành các nhóm theo CONFIG.
    Trả về list of list: mỗi phần tử là [(fname, dur), ...]
    """
    use_chapters = CHAPTERS_PER_GROUP > 0
    use_duration = MAX_DURATION_SECONDS > 0

    groups = []
    current_group = []
    current_dur   = 0.0

    for fname, dur in files_with_dur:
        chapter_limit_hit  = use_chapters and len(current_group) >= CHAPTERS_PER_GROUP
        duration_limit_hit = use_duration and (current_dur + dur) > MAX_DURATION_SECONDS

        # Nếu nhóm hiện tại đã đạt ngưỡng VÀ nhóm không rỗng → chốt nhóm
        if current_group and (chapter_limit_hit or duration_limit_hit):
            groups.append(current_group)
            current_group = []
            current_dur   = 0.0

        current_group.append((fname, dur))
        current_dur += dur

    if current_group:
        groups.append(current_group)

    return groups

# =============================================================================
# OUTPUT NAME
# =============================================================================

def group_output_name(group: list) -> str:
    """
    Sinh tên file output từ nhóm.
    Ví dụ: Merged_Chuong_001-010.mp3 hoặc Merged_001-010.mp3
    """
    # Tách số chương từ tên file đầu và cuối
    def extract_num(fname):
        nums = re.findall(r'\d+', os.path.splitext(fname)[0])
        return nums[-1] if nums else "?"

    first = extract_num(group[0][0])
    last  = extract_num(group[-1][0])

    # Zero-pad cho đẹp
    try:
        width = max(len(first), len(last), 3)
        first_pad = first.zfill(width)
        last_pad  = last.zfill(width)
    except Exception:
        first_pad = first
        last_pad  = last

    if first_pad == last_pad:
        return f"{OUTPUT_PREFIX}_{first_pad}.mp3"
    return f"{OUTPUT_PREFIX}_{first_pad}-{last_pad}.mp3"

# =============================================================================
# TERMINAL PROGRESS
# =============================================================================

def _print_progress(done: int, total: int, current_label: str = ""):
    pct = done / total * 100 if total > 0 else 0
    label = f"  [{current_label}]" if current_label else ""
    print(f"\r⏳ {done}/{total} nhóm ({pct:.1f}%){label:<50}", end="", flush=True)

# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run():
    _bootstrap()
    logger = _setup_logger()

    session_start = datetime.now()
    logger.info("=" * 60)
    logger.info("SESSION START  %s", session_start.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("CONFIG  CHAPTERS_PER_GROUP=%d  MAX_DURATION_SECONDS=%d  BITRATE=%s  SKIP_EXISTING=%s",
                CHAPTERS_PER_GROUP, MAX_DURATION_SECONDS, OUTPUT_BITRATE, SKIP_EXISTING)
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # 1. Quét file đầu vào
    # ------------------------------------------------------------------
    all_mp3 = sorted(
        [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".mp3")],
        key=natural_sort_key
    )

    if not all_mp3:
        logger.warning("Không tìm thấy file .mp3 trong '%s'.", INPUT_DIR)
        print("⚠  Không có file MP3 nào.")
        return

    logger.info("Tìm thấy %d file MP3 trong '%s'.", len(all_mp3), INPUT_DIR)

    # ------------------------------------------------------------------
    # 2. Lấy duration của toàn bộ file (cần để group theo thời lượng)
    # ------------------------------------------------------------------
    print(f"🔍 Đang đọc thời lượng {len(all_mp3)} file MP3...")
    files_with_dur = []
    total_source_dur = 0.0

    for i, fname in enumerate(all_mp3, 1):
        path = os.path.join(INPUT_DIR, fname)
        dur  = get_duration(path)
        files_with_dur.append((fname, dur))
        total_source_dur += dur

        # Mini progress khi quét
        pct = i / len(all_mp3) * 100
        print(f"\r🔍 Đọc duration: {i}/{len(all_mp3)} ({pct:.0f}%)", end="", flush=True)

    print()
    logger.info("Tổng thời lượng nguồn: %.1f giây (%.1f phút)",
                total_source_dur, total_source_dur / 60)

    # ------------------------------------------------------------------
    # 3. Chia nhóm
    # ------------------------------------------------------------------
    groups = build_groups(files_with_dur)
    total_groups = len(groups)
    logger.info("Chia thành %d nhóm.", total_groups)

    for gi, grp in enumerate(groups, 1):
        names = [g[0] for g in grp]
        dur_grp = sum(g[1] for g in grp)
        logger.debug("Nhóm %02d: %d chương  %.1fs  [%s ... %s]",
                     gi, len(grp), dur_grp, names[0], names[-1])

    # ------------------------------------------------------------------
    # 4. Load resume state
    # ------------------------------------------------------------------
    state = _load_state()
    logger.info("Resume state: %d nhóm đã hoàn thành từ trước.", sum(1 for v in state.values() if v.get("done")))

    # ------------------------------------------------------------------
    # 5. Merge từng nhóm
    # ------------------------------------------------------------------
    done_count = skipped = errors = 0

    for gi, group in enumerate(groups, 1):
        out_name   = group_output_name(group)
        out_path   = os.path.join(OUTPUT_DIR, out_name)
        group_key  = out_name  # dùng tên file làm key state

        _print_progress(gi - 1, total_groups, out_name)

        # --- Resume: kiểm tra state JSON trước ---
        if SKIP_EXISTING and _is_done(state, group_key):
            # Kiểm tra thêm file có thực sự tồn tại không
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                logger.info("SKIP (state)  %s", out_name)
                skipped += 1
                _print_progress(gi, total_groups, "")
                continue
            else:
                # State nói done nhưng file không có → làm lại
                logger.warning("State nói DONE nhưng file không tồn tại → merge lại: %s", out_name)
                state.pop(group_key, None)

        # --- Resume: kiểm tra file output đã tồn tại & hợp lệ ---
        if SKIP_EXISTING and os.path.exists(out_path):
            if is_audio_valid(out_path):
                logger.info("SKIP (file)   %s", out_name)
                _mark_done(state, group_key, out_path)
                skipped += 1
                _print_progress(gi, total_groups, "")
                continue
            else:
                logger.warning("File tồn tại nhưng không hợp lệ → xóa & làm lại: %s", out_name)
                try:
                    os.remove(out_path)
                except Exception:
                    pass

        # --- Chuẩn bị đường dẫn ---
        input_paths = [os.path.join(INPUT_DIR, g[0]) for g in group]
        grp_dur     = sum(g[1] for g in group)
        chapters    = [g[0] for g in group]

        logger.info("-" * 50)
        logger.info("MERGE START  Nhóm %02d/%02d  %s", gi, total_groups, out_name)
        logger.info("  Chương  : %s → %s  (%d file)", chapters[0], chapters[-1], len(chapters))
        logger.info("  Duration: %.1f giây (%.1f phút)", grp_dur, grp_dur / 60)

        t0 = datetime.now()
        success = merge_files(input_paths, out_path, logger)
        elapsed = (datetime.now() - t0).total_seconds()

        if not success:
            logger.error("MERGE FAIL  %s", out_name)
            errors += 1
            _print_progress(gi, total_groups, "")
            continue

        # --- Verify ---
        if VERIFY_ENABLE:
            merged_dur = get_duration(out_path)
            diff = abs(merged_dur - grp_dur)
            if diff <= VERIFY_TOLERANCE:
                logger.info("VERIFY OK  merged=%.1fs  expected=%.1fs  diff=%.2fs",
                            merged_dur, grp_dur, diff)
            else:
                logger.warning("VERIFY WARN  merged=%.1fs  expected=%.1fs  diff=%.2fs (> %.1fs)",
                               merged_dur, grp_dur, diff, VERIFY_TOLERANCE)

        logger.info("MERGE OK  %s  |  %.2fs  |  size=%s",
                    out_name, elapsed,
                    _human_size(os.path.getsize(out_path)))

        _mark_done(state, group_key, out_path)
        done_count += 1
        _print_progress(gi, total_groups, "")

    # ------------------------------------------------------------------
    # 6. Tổng kết terminal
    # ------------------------------------------------------------------
    print()  # xuống dòng sau progress bar
    session_end = datetime.now()
    total_elapsed = (session_end - session_start).total_seconds()

    print()
    print("=" * 60)
    print("📊 KẾT QUẢ MERGE AUDIO")
    print("=" * 60)
    print(f"   Tổng nhóm     : {total_groups}")
    print(f"   ✅ Đã merge   : {done_count}")
    print(f"   ⏩ Bỏ qua     : {skipped}")
    print(f"   ❌ Lỗi        : {errors}")
    print(f"   ⏱  Thời gian  : {total_elapsed:.1f}s")
    print()

    # Bảng chi tiết từng nhóm
    print(f"{'Nhóm':<4}  {'File output':<40}  {'Chương':>7}  {'Thời lượng':>12}")
    print(f"{'-'*4}  {'-'*40}  {'-'*7}  {'-'*12}")
    for gi, group in enumerate(groups, 1):
        out_name  = group_output_name(group)
        out_path  = os.path.join(OUTPUT_DIR, out_name)
        grp_dur   = sum(g[1] for g in group)
        status    = "✅" if os.path.exists(out_path) else "❌"
        dur_str   = _fmt_duration(grp_dur)
        print(f"{gi:>3}.  {status} {out_name:<40}  {len(group):>5} ch  {dur_str:>12}")

    print()
    print(f"📁 Output : {OUTPUT_DIR}/")
    print(f"📝 Log    : {LOG_FILE}")
    print("=" * 60)

    # Log tổng kết
    logger.info("=" * 60)
    logger.info("SUMMARY  done=%d  skipped=%d  errors=%d  total_groups=%d  elapsed=%.1fs",
                done_count, skipped, errors, total_groups, total_elapsed)
    logger.info("SESSION END  %s", session_end.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    print("\nHoàn thành AudioMerger!\n")

# =============================================================================
# HELPERS
# =============================================================================

def _human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def _fmt_duration(seconds: float) -> str:
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    run()