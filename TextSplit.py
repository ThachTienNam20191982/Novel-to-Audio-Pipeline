import re
import os
import config

input_file = config.TEXTSPLIT_INPUT_FILE  # tên file lớn, tự lấy theo NOVEL_NAME trong config.py
output_dir = config.CLEANED_DIR

# Tạo thư mục nếu chưa có
os.makedirs(output_dir, exist_ok=True)

with open(input_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

chapter_pattern = re.compile(r'^Chương\s+(\d+)\b')

chapters = []  # list of (chapter_num, start_line_index)
for i, line in enumerate(lines):
    match = chapter_pattern.match(line)
    if match:
        chap_num = int(match.group(1))
        chapters.append((chap_num, i))

if not chapters:
    print("Không tìm thấy chương nào trong file.")
    exit()

# Xử lý từng chương
for idx, (chap_num, start_idx) in enumerate(chapters):
    # Tìm dòng bắt đầu chương tiếp theo
    if idx + 1 < len(chapters):
        next_start_idx = chapters[idx+1][1]
        chapter_lines = lines[start_idx:next_start_idx]
    else:
        chapter_lines = lines[start_idx:]  # đến hết file

    # Tạo tên file
    filename = f"Chương_{chap_num:03d}.txt"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as out_f:
        out_f.writelines(chapter_lines)

    print(f"Đã tạo {filename}")

print(f"Hoàn tất. Các file chương được lưu trong thư mục '{output_dir}'.")