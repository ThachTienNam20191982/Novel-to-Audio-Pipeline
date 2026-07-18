import os
import glob
import re

# ==================================================
# CONFIG
# ==================================================
INPUT_FOLDER = "Cleaned"
OUTPUT_FOLDER = "Text_Merged"

# 0 = Merge tất cả thành 1 file
# >0 = Số chương mỗi file
MERGE_SIZE = 10
# ==================================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

txt_files = glob.glob(os.path.join(INPUT_FOLDER, "*.txt"))


def extract_number(filename):
    match = re.search(r'(\d+)', os.path.basename(filename))
    return int(match.group(1)) if match else float('inf')


txt_files.sort(key=extract_number)

# Nếu merge tất cả
if MERGE_SIZE == 0:
    first_chapter = extract_number(txt_files[0])
    last_chapter = extract_number(txt_files[-1])

    output_file = os.path.join(
        OUTPUT_FOLDER,
        f"Chuong{first_chapter:03d}-{last_chapter:03d}.txt"
    )

    with open(output_file, "w", encoding="utf-8") as outfile:
        for file in txt_files:
            with open(file, "r", encoding="utf-8") as infile:
                outfile.write(infile.read())
                outfile.write("\n\n")

    print(f"Đã gộp {len(txt_files)} chương -> {output_file}")

else:
    total = len(txt_files)

    for i in range(0, total, MERGE_SIZE):
        batch = txt_files[i:i + MERGE_SIZE]

        first_chapter = extract_number(batch[0])
        last_chapter = extract_number(batch[-1])

        output_file = os.path.join(
            OUTPUT_FOLDER,
            f"Chuong{first_chapter:03d}-{last_chapter:03d}.txt"
        )

        with open(output_file, "w", encoding="utf-8") as outfile:
            for file in batch:
                with open(file, "r", encoding="utf-8") as infile:
                    outfile.write(infile.read())
                    outfile.write("\n\n")

        print(f"Đã tạo: {output_file} ({len(batch)} chương)")

    print("Hoàn thành.")