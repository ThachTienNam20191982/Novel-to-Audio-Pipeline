# 📚 Novel-to-Audio Pipeline

Tự động hoá việc chuyển 1 bộ truyện từ web đọc truyện thành audiobook: tải PDF từng chương → trích xuất text → dọn dẹp → tạo giọng đọc MP3 → gộp thành file nghe hoàn chỉnh. Điều khiển toàn bộ qua **GUI** (`gui.py` / `gui.exe`) hoặc chạy tay từng script.

## Mục lục

- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Cài đặt](#cài-đặt)
- [⭐ Cách dùng nhanh nhất — GUI](#-cách-dùng-nhanh-nhất--gui)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [config.py — cấu hình trung tâm](#configpy--cấu-hình-trung-tâm)
- [Pipeline tổng quan](#pipeline-tổng-quan)
- [Hướng dẫn từng script](#hướng-dẫn-từng-script)
- [Đóng gói GUI thành .exe](#đóng-gói-gui-thành-exe)
- [Log & file trạng thái](#log--file-trạng-thái)
- [Troubleshooting](#troubleshooting)

---

## Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|---|---|
| Python | 3.10+ (bản cài từ python.org trên Windows đã có sẵn `tkinter` cho GUI; trên Linux có thể cần cài thêm gói hệ thống `python3-tk`) |
| Google Chrome | Bản mới nhất — `RawDowloader.py` dùng Selenium điều khiển Chrome để tải PDF từng chương |
| RAM | Tối thiểu 4GB, khuyến nghị 8GB+ khi tăng số worker song song (`RAWDL_WORKER_COUNT`, `AUDIOGEN_MAX_WORKERS`) |
| Mạng | Bắt buộc cho `RawDowloader.py` (tải chương) và `AudioGenerator.py` (gọi dịch vụ TTS của Edge) |

> Selenium 4.6+ có Selenium Manager, tự tải và khớp version ChromeDriver với Chrome đang cài — không cần tải ChromeDriver thủ công.

## Cài đặt

```bash
git clone <repo-url>
cd <thư-mục-repo>
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

---

## ⭐ Cách dùng nhanh nhất — GUI

Thay vì mở từng script bằng tay, dùng **`gui.py`** — 1 file duy nhất điều khiển toàn bộ 9 script + toàn bộ `config.py`.

```bash
python gui.py
```

Hoặc double-click **`gui.exe`** nếu đã đóng gói (xem [Đóng gói GUI thành .exe](#đóng-gói-gui-thành-exe)) — mở thẳng giao diện, không cần mở cmd, không cần gõ lệnh Python.

**Bố cục:**

- Tab **⚙️ Config** — sửa toàn bộ `config.py` trên giao diện thay vì mở file text:
  - Chọn truyện đang xử lý qua dropdown (chỉ hiện các truyện đã có trong `Data/`) hoặc **"+ Thêm truyện mới..."** để tạo truyện mới.
  - Mỗi truyện tự nhớ cấu hình riêng (lưu trong `Data/<tên truyện>/Log/pipeline_config.json`) — chọn lại truyện cũ sẽ tự nạp lại đúng URL/số chương/giọng đọc... của truyện đó, không bị lẫn giữa các truyện.
  - Tham số chia 2 cột: **Cấu hình đơn giản** (dropdown/checkbox — chế độ crawl, giọng đọc, bitrate, số worker...) và **Cấu hình nâng cao** (ô nhập tay — URL, số chương, các ngưỡng, regex...).
  - Nút **💾 Lưu cấu hình** ghi vào `config.py` (có backup timestamp vào `config_backup/` trước khi ghi đè) và lưu riêng cho đúng truyện đang chọn.
- 9 tab còn lại — mỗi tab ứng với 1 script, có nút **▶ Start**, **■ Stop**, khung log hiển thị output thực tế theo thời gian thực.
  - Tab **TextCleaner** có thêm khu vực chỉnh keyword trực quan (xem mục [TextCleaner.py](#4-textcleanerpy)) thay vì phải mở `TextCleaner_KeyWord.log` bằng tay.
  - Tab **AudioGenerator** hiển thị thanh tiến độ riêng cho từng worker (file đang đọc, phase, % hoàn thành).

> **Lưu ý đã biết:** trên một số máy Windows, bấm Start nhiều lần liên tiếp trên cùng 1 tab đôi khi bị treo giao diện, log chỉ hiện ra khi script chạy xong thay vì theo thời gian thực. Đang tìm nguyên nhân chính xác; nếu gặp phải, workaround tạm thời là đóng và mở lại `gui.py`/`gui.exe`.

Dù dùng GUI hay chạy tay từng file, **`config.py` vẫn là nơi duy nhất 9 script thực sự đọc khi chạy** — GUI chỉ là công cụ đọc/ghi file đó an toàn hơn, không thay thế nó.

---

## Cấu trúc dự án

```
.
├── gui.py                  # GUI điều khiển toàn bộ pipeline (khuyến nghị dùng)
├── build_exe.bat           # Đóng gói gui.py -> gui.exe (double-click để build)
├── config.py                # Cấu hình trung tâm — đổi NOVEL_NAME để chuyển truyện
├── RawDowloader.py           # Bước 1: tải PDF từng chương
├── TextExtractor.py          # Bước 2: PDF -> text thô
├── TextCheck.py               # (tuỳ chọn) kiểm tra Raw/ có thiếu chương nào không
├── TextCleaner.py             # Bước 3: dọn rác theo keyword
├── TitleDelete.py              # (tuỳ chọn) xoá dòng rác cố định ở đầu mỗi chương
├── TextSplit.py                 # (đường vào khác) tách 1 file text lớn thành từng chương
├── TextMerge.py                  # (tuỳ chọn) gộp nhiều chương .txt thành từng cụm
├── AudioGenerator.py              # Bước 4: text -> mp3 từng chương (TTS)
├── AudioMerger.py                  # Bước 5: gộp mp3 từng chương thành file lớn
├── bin/                              # (tuỳ chọn) đặt ffmpeg.exe/ffprobe.exe ở đây nếu không cài vào PATH hệ thống
├── requirements.txt
├── README.md
├── config_backup/            # GUI tự tạo — backup config.py có timestamp mỗi lần Lưu
└── Data/
    └── <Tên truyện>/          # 1 thư mục riêng cho mỗi truyện, tự tạo khi đổi NOVEL_NAME
        ├── Raw/                 # PDF gốc từng chương          (RawDowloader)
        ├── Translate/            # Text thô sau khi trích PDF   (TextExtractor, TextSplit input)
        ├── Cleaned/               # Text đã dọn rác              (TextCleaner, TitleDelete, AudioGenerator input)
        ├── Text_Merged/            # Text gộp theo cụm            (TextMerge, không dùng cho bước audio)
        ├── Audio/                   # MP3 từng chương              (AudioGenerator output, AudioMerger input)
        ├── Merged/                   # MP3 đã gộp cụm               (AudioMerger output — sản phẩm cuối)
        ├── temp_audio/                 # File tạm khi tạo audio       (AudioGenerator, tự dọn khi xong)
        └── Log/                         # Log từng script + file trạng thái
            ├── TextCleaner_KeyWord.log     # Danh sách keyword lọc rác
            ├── pipeline_config.json         # Config riêng của truyện này (GUI tự quản lý)
            ├── AudioMerger_state.json        # Trạng thái resume của AudioMerger
            └── *_log.log                      # Log chi tiết từng script
```

## config.py — cấu hình trung tâm

Toàn bộ tham số của cả 9 script nằm trong 1 file `config.py`, chia theo section rõ ràng theo tên từng file (`RawDowloader.py — CONFIG`, `AudioGenerator.py — CONFIG`...). Đổi truyện = đổi đúng 1 dòng:

```python
NOVEL_NAME = "Tên truyện của bạn"
```

Toàn bộ thư mục `Data/<NOVEL_NAME>/...` tự tạo và tự trỏ theo tên này — không cần sửa gì khác, không cần clone lại repo khi chuyển sang truyện mới. Có thể sửa trực tiếp file này bằng text editor, hoặc dùng tab **⚙️ Config** trong `gui.py` (khuyến nghị — có kiểm tra kiểu dữ liệu, dropdown cho các giá trị cố định, tự nhớ theo từng truyện).

---

## Pipeline tổng quan

```
                    ┌─────────────────┐
  (đã có sẵn text)  │  TextSplit.py   │  ← đường vào khác: có sẵn 1 file text lớn
        ┌──────────►│  (tuỳ chọn)     │    đã dịch (đặt tên Translate/<NOVEL_NAME>.txt)
        │           └────────┬────────┘
        │                    │
┌───────┴──────┐   ┌─────────▼────────┐   ┌────────────────┐   ┌─────────────────┐
│ RawDowloader │──►│  TextExtractor    │──►│  TextCleaner    │──►│  AudioGenerator  │──► (Audio/)
│  (Raw/)      │   │  (Translate/)      │   │  (Cleaned/)     │   │   text → mp3      │
└──────┬───────┘   └─────────┬──────────┘   └────────┬────────┘   └────────┬─────────┘
       │                     │                        │                      │
       ▼                     ▼                        ▼                      ▼
 ┌───────────┐        (không bắt buộc)          ┌───────────────┐    ┌───────────────┐
 │TextCheck  │                                  │  TitleDelete   │    │  AudioMerger   │
 │(kiểm tra  │                                  │  (tuỳ chọn)     │    │  mp3 → mp3 gộp  │
 │thiếu chương)│                                └───────┬────────┘    └────────────────┘
 └───────────┘                                          ▼
                                                  ┌──────────────┐
                                                  │ TextMerge     │
                                                  │ (tuỳ chọn,    │
                                                  │  không phục vụ│
                                                  │  bước audio)  │
                                                  └──────────────┘
```

**Chuỗi bắt buộc để ra audio hoàn chỉnh:** RawDowloader → TextExtractor → TextCleaner → AudioGenerator → AudioMerger.
**Tuỳ chọn/bổ trợ:** TextCheck (kiểm tra), TitleDelete (dọn thêm rác đặc thù truyện), TextMerge (gộp text để đọc/lưu riêng, không cần cho audio).
**Đường vào khác:** TextSplit — dùng khi đã có sẵn 1 file text lớn đã dịch (không cần RawDowloader + TextExtractor).

---

## Hướng dẫn từng script

### 1. RawDowloader.py
Tải PDF từng chương bằng Selenium điều khiển Chrome, có bước tự động xoá quảng cáo trước khi in PDF. 2 chế độ (`RAWDL_CRAWL_MODE`):
- **`index`** — sinh URL theo `RAWDL_URL_TEMPLATE` (chứa `{}` thay số chương) + `RAWDL_START_CHAPTER`/`RAWDL_END_CHAPTER`.
- **`navigate`** — bắt đầu từ `RAWDL_URL_FIRST_CHAPTER`, tự tìm link "chương sau" trên từng trang để lần lượt thu thập URL (lưu tạm vào `Log/RawDownloader_Prepare.log`), rồi mới tải song song.

Tự resume — chương đã tải rồi sẽ bỏ qua ở lần chạy sau. Số luồng tải song song: `RAWDL_WORKER_COUNT`.

### 2. TextExtractor.py
Trích text từ toàn bộ PDF trong `Raw/`, lưu vào `Translate/`. Tự tính số chữ số cần đệm theo số chương lớn nhất đang có (vd 980 chương → `Chương_001.txt` … `Chương_980.txt`) để sắp xếp đúng thứ tự ở các bước sau, kèm cảnh báo nếu phát hiện file cũ bị đệm số khác (thường do lần trước `Raw/` chưa tải đủ). Có báo cáo file nghi ngờ quá ngắn/quá dài bất thường so với trung bình (`TEXTEXTRACT_MIN_WORD_COUNT`, `TEXTEXTRACT_ANOMALY_THRESHOLD`).

### 3. TextCheck.py
Tiện ích kiểm tra nhanh: quét `Raw/`, báo chương đầu/cuối/tổng số file và liệt kê số chương bị thiếu nếu có. Không tạo file mới.

### 4. TextCleaner.py
Dọn rác trong text theo `Log/TextCleaner_KeyWord.log`, gồm 5 phần:
- `[DELETE]` — xoá dòng **chứa** từ khoá (khớp 1 phần).
- `[KEEP]` — bảo vệ dòng, ưu tiên hơn `[DELETE]` nếu trùng.
- `[UI_JUNK_WORDS]` — xoá dòng khớp **chính xác** cả dòng (nút bấm, nhãn UI ngắn).
- `[UI_JUNK_NUMBERS]` — bật/tắt tự xoá dòng chỉ chứa 1 số nguyên đơn.
- `[SUSPECTED]` — TextCleaner tự đề xuất (dòng lặp ≥5 lần trong cùng 1 lần chạy mà chưa được xếp loại), người dùng xem rồi tự chuyển sang `DELETE`/`KEEP`.

File này có thể sửa tay, hoặc sửa trực quan trong tab **TextCleaner** của `gui.py` (3 ô DELETE/KEEP/UI_JUNK_WORDS, checkbox UI_JUNK_NUMBERS, ô SUSPECTED riêng cạnh khung log) — tab tự tải lại SUSPECTED mới sau mỗi lần chạy. Không có resume — mỗi lần chạy xử lý lại toàn bộ file trong `Translate/`.

### 5. TitleDelete.py
Xoá các dòng rác cố định ở **đầu mỗi chương** trong `Cleaned/`, theo danh sách regex `TITLEDEL_JUNK_PATTERNS` trong `config.py` — đặc thù riêng từng truyện/nguồn convert (vd tên truyện cũ sót lại, tiền tố kiểu "Nguồn: ...").

### 6. TextSplit.py
Đường vào khác cho trường hợp đã có sẵn 1 file text lớn đã dịch (không qua RawDowloader/TextExtractor): đặt file tại `Translate/<NOVEL_NAME>.txt`, mỗi chương trong file phải có dòng đánh dấu dạng `Chương <số>` ở đầu dòng — script tách thành từng file `Chương_XXX.txt` trong `Cleaned/`.

### 7. TextMerge.py
Gộp các file trong `Cleaned/` thành từng cụm theo `TEXTMERGE_MERGE_SIZE` chương/file (0 = gộp hết thành 1), lưu vào `Text_Merged/`. Không phục vụ bước tạo audio (AudioGenerator đọc trực tiếp từ `Cleaned/`) — dùng khi cần bản text gộp để đọc/lưu/đăng riêng.

### 8. AudioGenerator.py
Chuyển từng file trong `Cleaned/` thành mp3 bằng Edge TTS (`AUDIOGEN_VOICE`), chạy `AUDIOGEN_MAX_WORKERS` tiến trình song song, mỗi tiến trình xử lý `AUDIOGEN_TTS_CONCURRENT` chunk cùng lúc. Tự retry khi lỗi, tự chờ lâu hơn khi bị TTS giới hạn tốc độ (nhận diện qua `AUDIOGEN_THROTTLE_KEYWORDS`). Chương dài chia thành nhiều "part" theo `AUDIOGEN_MAX_CHUNKS_PER_PART`. Có resume — chunk đã tạo và hợp lệ sẽ bỏ qua. Chạy trực tiếp trong terminal hiện bảng tiến độ đẹp (thư viện `rich`); chạy qua `gui.py` tự chuyển sang gửi dữ liệu tiến độ cho GUI vẽ thanh riêng.

### 9. AudioMerger.py
Gộp các mp3 trong `Audio/` thành từng file lớn bằng ffmpeg, chia nhóm theo `AUDIOMERGE_CHAPTERS_PER_GROUP` chương và/hoặc `AUDIOMERGE_MAX_DURATION_SECONDS` giây (đạt 1 trong 2 ngưỡng là chốt nhóm). Tên file vd `1.<Tên truyện>_001-010.mp3`. Có resume qua `Log/AudioMerger_state.json` + kiểm tra lại file output còn hợp lệ không trước khi bỏ qua. Có verify tổng thời lượng sau khi gộp (`AUDIOMERGE_VERIFY_ENABLE`).

---

## Đóng gói GUI thành .exe

Double-click **`build_exe.bat`** (đặt cùng thư mục với `gui.py`) — script tự cài PyInstaller nếu chưa có, build, dọn file tạm, để lại đúng 1 file `gui.exe` cùng thư mục với các script. Từ đó chỉ cần double-click `gui.exe`, không cần cài đặt gì thêm để MỞ giao diện — nhưng máy vẫn cần Python + các thư viện trong `requirements.txt` đã cài sẵn để 9 script bên trong chạy được (gui.exe chỉ đóng gói riêng phần giao diện).

> Windows Defender đôi khi báo nhầm với `.exe` đóng gói bằng PyInstaller (do cách `--onefile` tự giải nén lúc chạy) — nếu bị chặn, thêm ngoại lệ cho `gui.exe`.

Build tay không qua `.bat`:
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name gui --distpath . gui.py
```

---

## Log & file trạng thái

Tất cả nằm trong `Data/<Tên truyện>/Log/`:

| File | Nội dung |
|---|---|
| `RawDownloader_log.log` | Log chi tiết quá trình tải chương |
| `RawDownloader_Prepare.log` | Danh sách URL đã thu thập (chế độ `navigate`) |
| `TextExtractor_log.log` | Log trích xuất PDF, cảnh báo file ngắn/lệch đệm số |
| `TextCleaner_log.log` | Log dọn rác từng file, % đã cắt |
| `TextCleaner_KeyWord.log` | Danh sách keyword lọc rác — sửa tay hoặc qua GUI |
| `AudioGenerator_Log.log` | Log tạo audio, theo từng session |
| `AudioMerger_log.log` | Log gộp audio |
| `AudioMerger_state.json` | Trạng thái resume của AudioMerger |
| `pipeline_config.json` | Cấu hình riêng của truyện này (GUI tự quản lý, không cần sửa tay) |

Ngoài ra `config_backup/` ở thư mục gốc lưu bản sao `config.py` có timestamp mỗi lần bấm Lưu trong GUI.

---

## Troubleshooting

| Vấn đề | Hướng xử lý |
|---|---|
| `ModuleNotFoundError` khi chạy script | Chưa `pip install -r requirements.txt`, hoặc chưa kích hoạt đúng virtualenv |
| RawDowloader không tải được / trang trắng | Kiểm tra lại Chrome đã cập nhật, thử tăng `RAWDL_LOAD_WAIT_TIME`/`RAWDL_ADV_EXTRA_WAIT_BEFORE` |
| PDF vẫn còn dính quảng cáo | Bật thêm các bước `RAWDL_ADV_*` còn tắt; nếu bật hết mà mất luôn nội dung thật, thử tắt `RAWDL_ADV_REMOVE_OVERLAYS` trước |
| `ffmpeg`/`ffprobe` not found | Đặt `ffmpeg.exe`/`ffprobe.exe` vào thư mục `bin/` cùng cấp với các file `.py` (cả AudioGenerator và AudioMerger đều tự thêm `bin/` vào `PATH` khi chạy), hoặc cài ffmpeg vào `PATH` hệ thống máy |
| Text sau `TextExtractor` bị sai thứ tự chương | Thường do `Raw/` chưa tải đủ hết chương ở lần chạy trước rồi lại chạy tiếp — xem cảnh báo `PADDING_MISMATCH` trong log, khuyên xoá `Translate/` và chạy lại sau khi `Raw/` đã đủ |
| Audio bị lỗi/ngắt giữa chừng | Chạy lại `AudioGenerator.py` — các chunk đã tạo hợp lệ sẽ tự bỏ qua, chỉ tạo tiếp phần còn thiếu |
| GUI treo khi Start nhiều lần liên tiếp | Xem lưu ý ở mục [GUI](#-cách-dùng-nhanh-nhất--gui) — hiện đóng/mở lại `gui.py`/`gui.exe` là workaround tạm thời |