import os
import time
import subprocess
import shutil
import random
import asyncio
import edge_tts
import docx2txt
import datetime
import warnings
import re
import multiprocessing
import sys
import config
from multiprocessing import Process, Queue, Semaphore

# pip install rich
from rich.live import Live
from rich.table import Table
from rich.progress import BarColumn, TextColumn
from rich import box

warnings.filterwarnings("ignore")

# Auto-detect ffmpeg trong bin/
_BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
if os.path.isdir(_BIN_DIR):
    os.environ["PATH"] = _BIN_DIR + os.pathsep + os.environ["PATH"]

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ================= CONFIG =================
# Giá trị nằm trong config.py, mục "AudioGenerator.py — CONFIG"
INPUT_DIR = config.CLEANED_DIR
OUTPUT_DIR = config.AUDIO_DIR
TEMP_ROOT = config.TEMP_AUDIO_DIR

VOICE = config.AUDIOGEN_VOICE

CHUNK_SIZE = config.AUDIOGEN_CHUNK_SIZE
SENTENCE_SPLIT_REGEX = config.AUDIOGEN_SENTENCE_SPLIT_REGEX

MAX_RETRY = config.AUDIOGEN_MAX_RETRY
RETRY_BASE_DELAY = config.AUDIOGEN_RETRY_BASE_DELAY
RETRY_BACKOFF = config.AUDIOGEN_RETRY_BACKOFF

DELAY_BETWEEN_CHUNKS = config.AUDIOGEN_DELAY_BETWEEN_CHUNKS
DELAY_BETWEEN_FILES  = config.AUDIOGEN_DELAY_BETWEEN_FILES

TTS_CONCURRENT = config.AUDIOGEN_TTS_CONCURRENT
MAX_WORKERS    = config.AUDIOGEN_MAX_WORKERS
WORKER_STAGGER = config.AUDIOGEN_WORKER_STAGGER

THROTTLE_KEYWORDS = config.AUDIOGEN_THROTTLE_KEYWORDS
THROTTLE_BASE_DELAY = config.AUDIOGEN_THROTTLE_BASE_DELAY
THROTTLE_BACKOFF    = config.AUDIOGEN_THROTTLE_BACKOFF

MAX_CHUNKS_PER_PART = config.AUDIOGEN_MAX_CHUNKS_PER_PART

SUPPORTED_EXT = config.AUDIOGEN_SUPPORTED_EXT

LOG_FILE   = os.path.join(config.LOG_DIR, "AudioGenerator_Log.log")
SESSION_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")  # runtime — không phải setting, giữ tại đây

# ================= GLOBAL (per-process) =================
_tts_semaphore = None

def _init_worker(sem):
    global _tts_semaphore
    _tts_semaphore = sem

# ================= LOG =================
def log(msg):
    ts  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pid = multiprocessing.current_process().name
    line = f"[{ts}] [SESSION {SESSION_ID}] [{pid}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ================= READ =================
def read_text(path):
    if path.lower().endswith(".txt"):
        return open(path, "r", encoding="utf-8", errors="ignore").read()
    return docx2txt.process(path)

# ================= SORT =================
def natural_sort_key(s):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', s)]

# ================= SPLIT =================
def split_text(text):
    sentences = re.split(SENTENCE_SPLIT_REGEX, text)
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) < CHUNK_SIZE:
            cur = (cur + " " + s).strip() if cur else s
        else:
            if cur:
                chunks.append(cur.strip())
            cur = s
    if cur:
        chunks.append(cur.strip())
    return chunks

# ================= AUDIO UTILS =================
def get_duration(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        return float(r.stdout.strip())
    except:
        return 0.0

def is_audio_valid(path):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return r.returncode == 0

# ================= TTS =================
def create_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop

async def _tts(text, out_file):
    tts = edge_tts.Communicate(text, VOICE)
    await tts.save(out_file)

def tts_save_retry(text, out_file, prefix, chunk_id, loop):
    for i in range(MAX_RETRY):
        try:
            log(f"{prefix} chunk {chunk_id} try {i+1}")
            with _tts_semaphore:
                loop.run_until_complete(_tts(text, out_file))
            if os.path.exists(out_file) and os.path.getsize(out_file) > 1000:
                log(f"{prefix} chunk {chunk_id} OK")
                return True
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in THROTTLE_KEYWORDS):
                wait = THROTTLE_BASE_DELAY + i * THROTTLE_BACKOFF
                log(f"⏳ {prefix} chunk {chunk_id} THROTTLE → wait {wait}s | {e}")
                time.sleep(wait)
            else:
                log(f"{prefix} chunk {chunk_id} ERROR {e}")
                time.sleep(RETRY_BASE_DELAY + i * RETRY_BACKOFF)

    # HARD FAIL → xóa file corrupt
    if os.path.exists(out_file):
        try:
            os.remove(out_file)
            log(f"🧹 DELETE corrupted chunk {chunk_id}")
        except:
            pass
    log(f"❌ HARD FAIL {prefix} chunk {chunk_id}")
    return False

# ================= VERIFY =================
def verify_chunks_exist(chunks, temp_dir, prefix):
    missing = []
    for i in range(len(chunks)):
        path = os.path.join(temp_dir, f"{prefix}_{i}.mp3")
        if not os.path.exists(path) or os.path.getsize(path) < 1000:
            missing.append(i)
    if missing:
        log(f"❌ Missing chunks: {missing}")
        return False
    log(f"✅ All chunks exist")
    return True

def verify_merged(files, output_file, prefix, durations):
    expected_total = sum(durations.get(f, get_duration(f)) for f in files)
    merged_total   = get_duration(output_file)
    log(f"{prefix} expected={expected_total:.2f}s merged={merged_total:.2f}s")
    if abs(expected_total - merged_total) < 2:
        log(f"✅ MERGE OK")
        return True
    acc = 0
    for i, f in enumerate(files):
        acc += durations.get(f, get_duration(f))
        if acc > merged_total:
            log(f"🚨 MISSING from chunk {i}")
            return False
    log(f"❌ MERGE FAIL")
    return False

# ================= GENERATE =================
def generate_chunks(chunks, temp_dir, prefix, loop, status_q, worker_id):
    ok_files  = []
    durations = {}
    total     = len(chunks)

    log(f"START {prefix} chunks={total}")

    for i, chunk in enumerate(chunks):
        out = os.path.join(temp_dir, f"{prefix}_{i}.mp3")

        # ✅ Resume: verify bằng duration, không chỉ size
        if os.path.exists(out) and os.path.getsize(out) > 2000:
            d = get_duration(out)
            if d > 0.1:
                # chunk hợp lệ, skip
                durations[out] = d
                ok_files.append(out)
                status_q.put(("progress", worker_id, prefix, i + 1, total))
                continue
            else:
                # size OK nhưng audio corrupt → xóa, generate lại
                try:
                    os.remove(out)
                    log(f"🧹 DELETE corrupt resume chunk {i} (duration=0)")
                except:
                    pass

        success = tts_save_retry(chunk, out, prefix, i, loop)

        if not success:
            log(f"🚨 ABORT FILE {prefix} at chunk {i}")
            status_q.put(("fail_chunk", worker_id, prefix, i))
            return None, {}

        d = get_duration(out)
        durations[out] = d
        ok_files.append(out)

        status_q.put(("progress", worker_id, prefix, i + 1, total))
        time.sleep(random.uniform(*DELAY_BETWEEN_CHUNKS))

    return ok_files, durations

# ================= MERGE =================
def create_list(files, temp_dir):
    path = os.path.join(temp_dir, "list.txt")
    with open(path, "w", encoding="utf-8") as f:
        for file in files:
            f.write(f"file '{os.path.abspath(file)}'\n")
    return path

def merge_audio(list_file, output):
    log("MERGE START")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-acodec", "libmp3lame", "-ab", "192k",
        output
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"MERGE DONE {output}")

# ================= WORKER =================
def _worker_entry(file_queue, worker_id, sem, status_q):
    _init_worker(sem)
    worker(file_queue, worker_id, status_q)

def worker(file_queue, worker_id, status_q):
    # Stagger start
    stagger = worker_id * WORKER_STAGGER
    if stagger > 0:
        log(f"⏱ Worker {worker_id} stagger {stagger}s")
        status_q.put(("state", worker_id, "stagger", f"wait {stagger:.0f}s", 0, 1))
        time.sleep(stagger)

    loop = create_loop()

    while True:
        try:
            # Chờ tối đa 5s thay vì bỏ cuộc ngay
            path = file_queue.get(timeout=5)
        except:
            # Thật sự hết file sau 5s chờ
            break

        name   = os.path.basename(path)
        prefix = os.path.splitext(name)[0]
        output_file = os.path.join(OUTPUT_DIR, prefix + ".mp3")

        log(f"START FILE {name}")
        status_q.put(("state", worker_id, "check", prefix, 0, 1))

        # Đọc text sớm để tính số parts, từ đó check skip đúng
        text   = read_text(path)
        chunks = split_text(text)
        total  = len(chunks)

        # Tính số parts và kiểm tra tất cả parts đã có output valid chưa
        if MAX_CHUNKS_PER_PART > 0 and total > MAX_CHUNKS_PER_PART:
            import math
            n_parts = math.ceil(total / MAX_CHUNKS_PER_PART)
            all_parts_valid = all(
                os.path.exists(os.path.join(OUTPUT_DIR, f"{prefix}_Part{p}.mp3")) and
                is_audio_valid(os.path.join(OUTPUT_DIR, f"{prefix}_Part{p}.mp3"))
                for p in range(1, n_parts + 1)
            )
        else:
            all_parts_valid = os.path.exists(output_file) and is_audio_valid(output_file)

        if all_parts_valid:
            log(f"SKIP {name} (valid output)")
            status_q.put(("done", worker_id, prefix, "skip"))
            continue

        temp_dir = os.path.join(TEMP_ROOT, prefix)
        os.makedirs(temp_dir, exist_ok=True)

        status_q.put(("state", worker_id, "generate", prefix, 0, total))

        files, durations = generate_chunks(chunks, temp_dir, prefix, loop, status_q, worker_id)

        if files is None:
            status_q.put(("done", worker_id, prefix, "fail"))
            log(f"❌ FILE FAIL {name}")
            continue

        status_q.put(("state", worker_id, "verify", prefix, total, total))
        if not verify_chunks_exist(chunks, temp_dir, prefix):
            status_q.put(("done", worker_id, prefix, "fail"))
            log(f"❌ CHUNK FAIL {name}")
            continue

        status_q.put(("state", worker_id, "merge", prefix, total, total))

        # Chia files thành batches nếu vượt MAX_CHUNKS_PER_PART
        if MAX_CHUNKS_PER_PART > 0 and len(files) > MAX_CHUNKS_PER_PART:
            batches = [files[i:i + MAX_CHUNKS_PER_PART]
                       for i in range(0, len(files), MAX_CHUNKS_PER_PART)]
        else:
            batches = [files]

        any_merge_fail = False
        for part_idx, batch in enumerate(batches):
            if len(batches) == 1:
                part_output = output_file
                part_label  = prefix
            else:
                part_output = os.path.join(OUTPUT_DIR, f"{prefix}_Part{part_idx + 1}.mp3")
                part_label  = f"{prefix}_Part{part_idx + 1}"

            # Skip nếu part đã có output valid
            if os.path.exists(part_output) and is_audio_valid(part_output):
                log(f"SKIP {part_label} (valid output)")
                status_q.put(("done", worker_id, part_label, "skip"))
                continue

            list_file = create_list(batch, temp_dir)
            merge_audio(list_file, part_output)

            if not verify_merged(batch, part_output, part_label, durations):
                status_q.put(("done", worker_id, part_label, "fail"))
                log(f"❌ MERGE FAIL {part_label}")
                any_merge_fail = True
                continue

            log(f"✅ DONE {part_label} ({part_idx + 1}/{len(batches)})")
            status_q.put(("done", worker_id, part_label, "ok"))

        if any_merge_fail:
            log(f"⚠️ {name} có part merge thất bại (KEEP TEMP)")
            continue

        shutil.rmtree(temp_dir)
        log(f"✅ DONE FILE {name}")

        time.sleep(random.uniform(*DELAY_BETWEEN_FILES))

    status_q.put(("state", worker_id, "idle", "—", 0, 1))

# ================= RICH UI =================
def build_table(worker_states, counts, total_files):
    """Xây bảng rich mỗi lần refresh."""
    table = Table(box=box.ROUNDED, expand=True, show_header=True)
    table.add_column("Worker", style="bold cyan",  width=8,  no_wrap=True)
    table.add_column("File",   style="white",       width=20, no_wrap=True)
    table.add_column("Phase",  style="yellow",      width=10, no_wrap=True)
    table.add_column("Progress", min_width=24)
    table.add_column("Chunks", style="white",       width=12, no_wrap=True)

    PHASE_COLOR = {
        "generate": "green",
        "merge":    "blue",
        "verify":   "magenta",
        "check":    "yellow",
        "stagger":  "dim",
        "idle":     "dim",
    }

    for wid in range(MAX_WORKERS):
        state = worker_states.get(wid, {})
        phase   = state.get("phase",   "idle")
        prefix  = state.get("prefix",  "—")
        current = state.get("current", 0)
        total   = state.get("total",   1)

        color = PHASE_COLOR.get(phase, "white")

        # Progress bar thủ công bằng unicode
        pct      = current / total if total > 0 else 0
        bar_len  = 20
        filled   = int(bar_len * pct)
        bar      = f"[{color}]{'█' * filled}{'░' * (bar_len - filled)}[/{color}]"
        pct_str  = f"[{color}]{pct*100:5.1f}%[/{color}]"
        progress = f"{bar} {pct_str}"

        chunk_str = f"{current}/{total}" if phase == "generate" else "—"

        table.add_row(
            f"[cyan]W{wid}[/cyan]",
            prefix[:20],
            f"[{color}]{phase}[/{color}]",
            progress,
            chunk_str,
        )

    # Footer
    done  = counts.get("done",  0)
    fail  = counts.get("fail",  0)
    skip  = counts.get("skip",  0)
    table.add_section()
    table.add_row(
        "", "",
        f"[green]✅ {done}[/green]  [red]❌ {fail}[/red]  [dim]⏭ {skip}[/dim]",
        f"Total: {total_files} files",
        "",
    )

    return table


def print_gui_progress(worker_states, counts, total_files):
    """Xuất progress dạng dòng dữ liệu để GUI tự vẽ progress bar."""
    for wid in range(MAX_WORKERS):
        state = worker_states.get(wid, {})
        phase = state.get("phase", "idle")
        # Giao thuc progress phai ASCII-only de khong phu thuoc encoding cp1252/cp437
        # cua console Windows khi stdout dang bi GUI redirect vao PIPE.
        prefix = str(state.get("prefix", "-"))
        prefix = prefix.replace("|", "/").encode("ascii", "backslashreplace").decode("ascii")
        current = int(state.get("current", 0))
        total = max(int(state.get("total", 1)), 1)
        print(
            f"@@AUDIOGEN_PROGRESS@@|{wid}|{prefix}|{phase}|{current}|{total}|"
            f"{counts.get('done', 0)}|{counts.get('fail', 0)}|{counts.get('skip', 0)}|{total_files}",
            flush=True,
        )


# ================= MAIN =================
def main():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log("=" * 60)
    log("🚀 SESSION START")

    files = sorted(
        [os.path.join(INPUT_DIR, f)
         for f in os.listdir(INPUT_DIR)
         if f.endswith(SUPPORTED_EXT)],
        key=lambda x: natural_sort_key(os.path.basename(x))
    )
    total_files = len(files)

    file_queue = Queue()
    for f in files:
        file_queue.put(f)

    sem      = Semaphore(TTS_CONCURRENT)
    status_q = Queue()  # worker → main

    # State cho UI
    worker_states = {i: {"phase": "idle", "prefix": "—", "current": 0, "total": 1}
                     for i in range(MAX_WORKERS)}
    counts = {"done": 0, "fail": 0, "skip": 0}

    # Start workers
    procs = []
    for i in range(MAX_WORKERS):
        p = Process(target=_worker_entry, args=(file_queue, i, sem, status_q))
        p.start()
        procs.append(p)

    # Chạy trực tiếp trong CMD -> Rich Live.
    # Chạy từ gui.py -> stdout là PIPE, nên gửi snapshot progress cho GUI.
    use_rich = bool(sys.stdout.isatty())
    live_ctx = Live(
        build_table(worker_states, counts, total_files),
        refresh_per_second=4,
        screen=False,
    ) if use_rich else None

    active = MAX_WORKERS
    last_gui_snapshot = None

    if live_ctx is not None:
        live_ctx.__enter__()

    try:
        while active > 0:
            changed = False
            while True:
                try:
                    msg = status_q.get(timeout=0.25)
                except:
                    break

                kind = msg[0]

                if kind == "progress":
                    _, wid, prefix, current, total = msg
                    worker_states[wid].update({
                        "phase": "generate",
                        "prefix": prefix,
                        "current": current,
                        "total": total,
                    })
                    changed = True

                elif kind == "state":
                    _, wid, phase, prefix, current, total = msg
                    worker_states[wid].update({
                        "phase": phase,
                        "prefix": prefix,
                        "current": current,
                        "total": total,
                    })
                    if phase == "idle":
                        active -= 1
                    changed = True

                elif kind == "done":
                    _, wid, prefix, result = msg
                    if result == "ok":
                        counts["done"] += 1
                    elif result == "fail":
                        counts["fail"] += 1
                    elif result == "skip":
                        counts["skip"] += 1
                    changed = True

                elif kind == "fail_chunk":
                    _, wid, prefix, chunk_id = msg
                    worker_states[wid]["phase"] = "fail"
                    changed = True

            if use_rich:
                live_ctx.update(build_table(worker_states, counts, total_files))
            elif changed:
                snapshot = tuple(
                    (
                        wid,
                        worker_states[wid].get("phase", "idle"),
                        worker_states[wid].get("prefix", "—"),
                        worker_states[wid].get("current", 0),
                        worker_states[wid].get("total", 1),
                    )
                    for wid in range(MAX_WORKERS)
                ) + (counts["done"], counts["fail"], counts["skip"])
                if snapshot != last_gui_snapshot:
                    print_gui_progress(worker_states, counts, total_files)
                    last_gui_snapshot = snapshot
    finally:
        if live_ctx is not None:
            live_ctx.__exit__(None, None, None)

    for p in procs:
        p.join()

    log("🎉 SESSION END")
    log("=" * 60)
    if use_rich:
        print(f"\n🎉 ALL DONE — ✅ {counts['done']}  ❌ {counts['fail']}  ⏭ {counts['skip']}")
    else:
        print(f"\nALL DONE - done={counts['done']} fail={counts['fail']} skip={counts['skip']}", flush=True)

if __name__ == "__main__":
    main()