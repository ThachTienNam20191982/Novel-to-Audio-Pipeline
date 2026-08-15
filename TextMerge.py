import os
import glob
import re
import config

# ==================================================
# CONFIG
# ==================================================
INPUT_FOLDER = config.CLEANED_DIR
OUTPUT_FOLDER = config.TEXT_MERGED_DIR

# Giá trị nằm trong config.py, mục "TextMerge.py — CONFIG"
# 0 = Merge tất cả thành 1 file | >0 = Số chương mỗi file
MERGE_SIZE = config.TEXTMERGE_MERGE_SIZE
# ==================================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

txt_files = glob.glob(os.path.join(INPUT_FOLDER, "*.txt"))


def extract_number(filename):
    match = re.search(r'(\d+)', os.path.basename(filename))
    return int(match.group(1)) if match else float('inf')


txt_files.sort(key=extract_number)

# --- Tự động tính số chữ số cần đệm ---
numbers = [extract_number(f) for f in txt_files]
max_num = max(numbers)                     # số lớn nhất
width = len(str(max_num))                  # số chữ số của nó
# (Hoặc dùng max(len(str(n)) for n in numbers) nếu có số 0)

# Hàm tạo tên file với width động
def make_output_name(first, last):
    return os.path.join(OUTPUT_FOLDER, f"Chuong{first:0{width}d}-{last:0{width}d}.txt")

# --- Merge ---
if MERGE_SIZE == 0:
    first = numbers[0]
    last = numbers[-1]
    out_path = make_output_name(first, last)
    with open(out_path, "w", encoding="utf-8") as outfile:
        for f in txt_files:
            with open(f, "r", encoding="utf-8") as infile:
                outfile.write(infile.read())
                outfile.write("\n\n")
    print(f"Đã gộp {len(txt_files)} chương -> {out_path}")
else:
    total = len(txt_files)
    for i in range(0, total, MERGE_SIZE):
        batch = txt_files[i:i+MERGE_SIZE]
        first = extract_number(batch[0])
        last = extract_number(batch[-1])
        out_path = make_output_name(first, last)
        with open(out_path, "w", encoding="utf-8") as outfile:
            for f in batch:
                with open(f, "r", encoding="utf-8") as infile:
                    outfile.write(infile.read())
                    outfile.write("\n\n")
        print(f"Đã tạo: {out_path} ({len(batch)} chương)")
    print("Hoàn thành.")