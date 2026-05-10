# 📚 Novel-to-Audio Pipeline

Tự động tải chương truyện từ web → trích xuất text → làm sạch → tạo file audio MP3.

---

## 📋 Mục lục

- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Cài đặt môi trường](#cài-đặt-môi-trường)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Pipeline tổng quan](#pipeline-tổng-quan)
- [Hướng dẫn từng bước](#hướng-dẫn-từng-bước)
  - [Bước 1 — RawDownloader](#bước-1--rawdownloader)
  - [Bước 2 — TextExtractor](#bước-2--textextractor)
  - [Bước 3 — TextCleaner](#bước-3--textcleaner)
  - [Bước 4 — AudioGenerator](#bước-4--audiogenerator)
- [Cách test từng bước](#cách-test-từng-bước)
- [Tự cải thiện pipeline theo thời gian](#tự-cải-thiện-pipeline-theo-thời-gian)
- [Troubleshooting](#troubleshooting)

---

## Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|---|---|
| Python | 3.10 trở lên |
| Google Chrome | Bản mới nhất |
| ffmpeg + ffprobe | Để merge audio (xem hướng dẫn bên dưới) |
| RAM | Tối thiểu 4GB, khuyến nghị 8GB+ |
| Kết nối mạng | Bắt buộc cho Bước 1 và Bước 4 |

### ffmpeg

Project đã bao gồm sẵn `bin/` để chứa ffmpeg — **không cần cài vào hệ thống**.

**Cách chuẩn bị:**

1. Tải ffmpeg tại https://www.gyan.dev/ffmpeg/builds/ (Windows) hoặc https://ffmpeg.org/download.html
2. Giải nén, lấy 2 file `ffmpeg.exe` và `ffprobe.exe`
3. Bỏ vào thư mục `bin/` của project

```
bin/
├── ffmpeg.exe
└── ffprobe.exe
```

`AudioGenerator.py` sẽ tự tìm ffmpeg trong `bin/` khi chạy, không cần cấu hình thêm.

> **ChromeDriver:** Selenium 4.6+ có **Selenium Manager** tự tải và quản lý ChromeDriver phù hợp với version Chrome hiện tại — không cần cài tay.

---

## Cài đặt môi trường

```bash
# 1. Clone repo
git clone <your-repo-url>
cd <repo-folder>

# 2. Tạo virtual environment
python -m venv .venv

# 3. Kích hoạt venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 4. Cài thư viện
pip install -r requirements.txt
```

**`requirements.txt`:**

```
selenium
PyMuPDF
edge-tts
docx2txt
rich
```

---

## Cấu trúc thư mục

```
project/
│
├── bin/                        # ffmpeg, ffprobe
│   ├── ffmpeg.exe
│   └── ffprobe.exe
│
├── Raw/                        # PDF thô tải về (output Bước 1)
├── Translate/                  # Text trích xuất từ PDF (output Bước 2)
├── Cleaned/                    # Text đã làm sạch (output Bước 3)
├── Audio/                      # File MP3 cuối cùng (output Bước 4)
├── temp_audio/                 # Chunk tạm trong khi tạo audio (tự xóa)
│
├── Log/                        # Log của tất cả các bước
│   ├── RawDownloader_log.log
│   ├── TextExtractor_log.log
│   ├── TextCleaner_log.log
│   ├── TextCleaner_KeyWord.log # Keyword để lọc text (tự học)
│   └── AudioGenerator_Log.log
│
├── RawDowloader.py
├── TextExtractor.py
├── TextCleaner.py
├── AudioGenerator.py
├── requirements.txt
└── README.md
```

Các thư mục `Raw/`, `Translate/`, `Cleaned/`, `Audio/`, `Log/` sẽ được tạo tự động khi chạy. Không cần tạo tay.

---

## Pipeline tổng quan

```
[Web] ──► RawDownloader ──► Raw/*.pdf
                                │
                         TextExtractor ──► Translate/*.txt
                                                │
                                         TextCleaner ──► Cleaned/*.txt
                                                              │
                                                       AudioGenerator ──► Audio/*.mp3
```

Mỗi bước đều có **resume**: nếu bị gián đoạn giữa chừng, chạy lại script sẽ tự bỏ qua file đã xử lý xong, tiếp tục từ chỗ còn dang dở.

---

## Hướng dẫn từng bước

---

### Bước 1 — RawDownloader

**Mục đích:** Dùng Selenium điều khiển Chrome, tải từng chương truyện thành file PDF, lưu vào `Raw/`.

#### Cấu hình trước khi chạy

Mở `RawDowloader.py`, chỉnh phần CONFIG ở đầu file:

```python
START_CHAPTER = 1        # Chương bắt đầu tải
END_CHAPTER   = 1876     # Chương kết thúc

URL_TEMPLATE = "https://www.tvtruyen.com/dai-can-truong-sinh/chuong-{}/"
# Thay bằng URL truyện bạn muốn tải, giữ nguyên {} là placeholder số chương

WORKER_COUNT = 10        # Số luồng song song — tăng nếu mạng tốt, giảm nếu bị block
LOAD_WAIT_TIME  = 4      # Giây chờ sau khi load trang (tăng nếu trang chậm)
MAX_RETRY    = 3         # Số lần retry khi lỗi
```

#### Cấu hình xử lý quảng cáo (Ad-removal)

```python
ADV_ISOLATE_REBUILD     = True   # Khuyến nghị bật — rebuild DOM sạch nhất
ADV_HIDE_CSS            = True   # Ẩn quảng cáo bằng CSS
ADV_REMOVE_INLINE       = True   # Xóa banner ảnh
ADV_REMOVE_OVERLAYS     = True   # Xóa popup/fixed element
ADV_REMOVE_DOMAIN_NOISE = True   # Xóa footer/sidebar đặc thù từng site
```

> **Lưu ý:** Nếu sau khi chạy PDF bị trắng nội dung, thử tắt `ADV_REMOVE_OVERLAYS = False` trước, sau đó `ADV_ISOLATE_REBUILD = False`.

#### Cấu hình cắt PDF (tuỳ chọn)

```python
PDF_SMART_CROP       = False   # Bật nếu PDF có header/footer thừa
CROP_TOP_FIRST_PAGE  = 250     # Pixel cắt ở đầu trang 1
REMOVE_LAST_N_PAGES  = 6       # Số trang cuối bị xóa (thường là trang QC của site)
```

#### Chạy

```bash
python RawDowloader.py
```

Terminal sẽ hiện tiến độ dạng `Progress: 45/1876 (2.40%)`. Log chi tiết lưu tại `Log/RawDownloader_log.log`.

---

### Bước 2 — TextExtractor

**Mục đích:** Đọc từng file PDF trong `Raw/`, trích xuất text thuần, lưu thành file `.txt` vào `Translate/`.

#### Cấu hình

```python
MIN_WORD_COUNT    = 500    # File ít hơn ngưỡng này → đánh dấu nghi vấn ngắn
ANOMALY_THRESHOLD = 0.30   # File lệch >30% so với trung bình → nghi vấn bất thường
```

#### Chạy

```bash
python TextExtractor.py
```

Sau khi chạy xong, script in báo cáo gồm 3 nhóm cần chú ý:

- **NGHI NGỜ FILE NGẮN** — số từ dưới `MIN_WORD_COUNT`, có thể PDF lỗi hoặc chương placeholder
- **NGHI NGỜ FILE NGẮN BẤT THƯỜNG** — ngắn hơn trung bình >30%, có thể thiếu nội dung
- **NGHI NGỜ FILE DÀI BẤT THƯỜNG** — dài hơn trung bình >30%, có thể bị dính 2 chương hoặc có nhiều quảng cáo

> Kiểm tra thủ công các file trong danh sách này trước khi sang Bước 3.

---

### Bước 3 — TextCleaner

**Mục đích:** Lọc bỏ các dòng thừa (quảng cáo, watermark, chữ ký tác giả...) trong file `.txt`, lưu kết quả vào `Cleaned/`.

#### Hệ thống keyword

TextCleaner hoạt động dựa trên file `Log/TextCleaner_KeyWord.log` với 3 section:

```
[DELETE]
tên website
link tài trợ
chữ ký người dịch

[KEEP]
từ cần bảo toàn dù chứa keyword xấu

[SUSPECTED]
(tự động — các dòng lặp lại ≥5 lần chưa được phân loại)
```

**Lần đầu chạy:** Nếu chưa có file keyword, script sẽ **tự tạo** `Log/TextCleaner_KeyWord.log` với cấu trúc rỗng — không cần tạo tay. Chạy lần đầu xong sẽ có danh sách `[SUSPECTED]` để bắt đầu phân loại.

#### Cấu hình

```python
HEAVY_DELETE_THRESHOLD = 10   # % — file bị xóa nhiều hơn ngưỡng này → cảnh báo
```

#### Chạy

```bash
python TextCleaner.py
```

Sau mỗi lần chạy, script tự cập nhật section `[SUSPECTED]` trong keyword file với các dòng lặp lại ≥5 lần — đây là gợi ý để bạn xem xét thêm vào `[DELETE]` hoặc `[KEEP]`.

---

### Bước 4 — AudioGenerator

**Mục đích:** Đọc từng file `.txt` trong `Cleaned/`, dùng Microsoft Edge TTS (giọng `vi-VN-HoaiMyNeural`) tạo audio, merge thành file MP3, lưu vào `Audio/`.

#### Cấu hình

```python
VOICE      = "vi-VN-HoaiMyNeural"   # Giọng đọc — xem thêm giọng khác bên dưới
CHUNK_SIZE = 1500                    # Ký tự mỗi chunk TTS (không nên tăng quá 2000)

MAX_RETRY        = 5                 # Retry mỗi chunk khi lỗi
TTS_CONCURRENT   = 3                 # Số chunk TTS chạy đồng thời (tăng nếu mạng tốt)
MAX_WORKERS      = 5                 # Số file xử lý song song
WORKER_STAGGER   = 2.0               # Giây delay giữa mỗi worker khi start
```

**Các giọng tiếng Việt khác của Edge TTS:**

| Giọng | Giới tính | Phong cách |
|---|---|---|
| `vi-VN-HoaiMyNeural` | Nữ | Tự nhiên, phổ thông |
| `vi-VN-NamMinhNeural` | Nam | Tự nhiên, phổ thông |

#### Chạy

```bash
python AudioGenerator.py
```

Terminal hiện bảng Rich UI realtime với trạng thái từng worker. Log chi tiết tại `Log/AudioGenerator_Log.log`.

> **Lưu ý:** AudioGenerator tự tìm ffmpeg trong `bin/`. Đảm bảo `bin/ffmpeg.exe` và `bin/ffprobe.exe` đã có trước khi chạy.

---

## Cách test từng bước

Trước khi chạy toàn bộ pipeline với hàng nghìn chương, nên test với số nhỏ trước.

### Test Bước 1 — RawDownloader

```python
# Sửa tạm trong RawDowloader.py
START_CHAPTER = 1
END_CHAPTER   = 3     # Chỉ tải 3 chương
WORKER_COUNT  = 2     # Dùng ít luồng hơn khi test
```

Kiểm tra sau khi chạy:
- `Raw/` có 3 file PDF không?
- Mở thử 1 file PDF — nội dung có đúng chương đó không? Có còn quảng cáo không?
- `Log/RawDownloader_log.log` có báo SUCCESS hay ERROR không?

### Test Bước 2 — TextExtractor

Chỉ cần có vài file PDF trong `Raw/` là chạy được. Kiểm tra:
- `Translate/` có file `.txt` tương ứng không?
- Mở file txt, đọc thử — text có bị nhảy dòng lạ không? Có bị mất đoạn không?
- Báo cáo cuối có file nào vào danh sách nghi vấn không? Nếu có, mở ra kiểm tra.

### Test Bước 3 — TextCleaner

Lần đầu chạy, nếu `Log/TextCleaner_KeyWord.log` chưa tồn tại, script sẽ **tự tạo file rỗng** đúng cấu trúc — không cần tạo tay.

Sau lần chạy đầu tiên:
- Xem section `[SUSPECTED]` — những dòng nào lặp lại thường xuyên và thực sự là rác?
- Thêm vào `[DELETE]`, chạy lại
- Kiểm tra `%` bị xóa trong báo cáo — nên nằm trong khoảng 1–5% là lý tưởng

### Test Bước 4 — AudioGenerator

```python
# Sửa tạm trong AudioGenerator.py
MAX_WORKERS    = 1    # Chỉ dùng 1 worker khi test
TTS_CONCURRENT = 1
```

Kiểm tra:
- `Audio/` có file MP3 tương ứng không?
- Nghe thử file MP3 — giọng đọc có tự nhiên không? Có bị cắt giữa câu không?
- `Log/AudioGenerator_Log.log` có HARD FAIL hay MERGE FAIL không?

---

## Tự cải thiện pipeline theo thời gian

### RawDownloader — Thêm site mới

Mỗi site truyện có cấu trúc DOM khác nhau. Khi chuyển sang site mới:

1. Đổi `URL_TEMPLATE` sang URL mới
2. Kiểm tra PDF output — nếu vẫn còn quảng cáo, mở DevTools của Chrome trên trang đó, tìm `class` hoặc `id` của phần quảng cáo
3. Thêm vào hàm `step_remove_domain_noise()`:

```python
elif "ten-site-moi.com" in domain:
    driver.execute_script("""
        document.getElementById("your-ad-id")?.remove();
        document.querySelector(".your-ad-class")?.remove();
    """)
```

4. Nếu site lazy-load ảnh, tăng `SCROLL_WAIT_TIME` và `LOAD_WAIT_TIME`

### TextCleaner — Cải thiện keyword

Sau mỗi lần chạy, quy trình cải thiện keyword:

1. Xem `[SUSPECTED]` trong `Log/TextCleaner_KeyWord.log`
2. Với mỗi dòng suspected:
   - Là rác (quảng cáo, chữ ký, watermark) → thêm vào `[DELETE]`
   - Là nội dung thật → thêm vào `[KEEP]` (để tránh bị xóa nhầm nếu sau này thêm keyword liên quan)
   - Không chắc → để lại `[SUSPECTED]`, kiểm tra thêm vài lần chạy sau
3. Chạy lại TextCleaner, so sánh % bị xóa trước và sau

> Keyword là **substring matching** (không phân biệt hoa thường). Ví dụ keyword `"tvtruyen"` sẽ xóa bất kỳ dòng nào chứa chuỗi đó.

### AudioGenerator — Tối ưu hiệu suất

Nếu bị throttle (lỗi 1015/1008) thường xuyên:
```python
TTS_CONCURRENT   = 2      # Giảm xuống
THROTTLE_BASE_DELAY = 20  # Tăng thời gian chờ khi bị throttle
```

Nếu mạng tốt, muốn nhanh hơn:
```python
MAX_WORKERS    = 8
TTS_CONCURRENT = 4
WORKER_STAGGER = 1.0
```

Nếu file MP3 bị cắt giữa câu:
```python
CHUNK_SIZE = 1000   # Giảm xuống để mỗi chunk ngắn hơn
```

---

## Troubleshooting

### Chrome không mở được (Bước 1)

```
selenium.common.exceptions.WebDriverException: 'chromedriver' executable needs to be in PATH
```

→ ChromeDriver chưa có trong `bin/` hoặc version không khớp Chrome. Kiểm tra lại version Chrome và tải đúng ChromeDriver.

### PDF trắng / thiếu nội dung (Bước 1)

→ `ADV_ISOLATE_REBUILD` rebuild sai div. Thử tắt từng bước ad-removal, bắt đầu từ `ADV_REMOVE_OVERLAYS = False`.

### Text bị ký tự lạ / encoding lỗi (Bước 2)

→ PDF có thể được scan bằng ảnh (không có text layer). PyMuPDF không hỗ trợ OCR — cần dùng thêm Tesseract hoặc đổi nguồn PDF.

### ffmpeg not found (Bước 4)

```
FileNotFoundError: [WinError 2] The system cannot find the file specified
```

→ `bin/ffmpeg.exe` chưa có. Tải và bỏ vào `bin/` theo hướng dẫn phần [Yêu cầu hệ thống](#yêu-cầu-hệ-thống).

### Edge TTS bị throttle liên tục (Bước 4)

→ Giảm `TTS_CONCURRENT` xuống 1–2, tăng `THROTTLE_BASE_DELAY` lên 30–60. Nếu vẫn bị, chờ 10–15 phút rồi chạy lại (pipeline có resume, không mất progress).

### File MP3 bị thiếu / corrupt (Bước 4)

→ Xem log, tìm dòng `HARD FAIL` hoặc `MERGE FAIL`. Xóa file MP3 tương ứng trong `Audio/` và folder temp trong `temp_audio/`, chạy lại — pipeline sẽ tự generate lại file đó.

---

## Log files

| File | Nội dung |
|---|---|
| `Log/RawDownloader_log.log` | Trạng thái từng chapter: SUCCESS / SKIP / ERROR / FAILED |
| `Log/TextExtractor_log.log` | Số từ từng file, file nghi vấn ngắn/dài bất thường |
| `Log/TextCleaner_log.log` | Số ký tự trước/sau clean, % bị xóa từng file |
| `Log/TextCleaner_KeyWord.log` | Keyword DELETE/KEEP và danh sách SUSPECTED tự học |
| `Log/AudioGenerator_Log.log` | Trạng thái từng chunk TTS, merge, verify |

Tất cả log đều **append** (không ghi đè), mỗi lần chạy là một session mới được ghi tiếp vào cuối file.
