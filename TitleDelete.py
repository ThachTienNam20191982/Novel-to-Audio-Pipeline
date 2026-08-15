import os
import re
import config

FOLDER = config.CLEANED_DIR

for filename in os.listdir(FOLDER):
    if not filename.endswith(".txt"):
        continue

    path = os.path.join(FOLDER, filename)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Xóa các dòng "rác" đầu chương — danh sách pattern khai báo trong
    # config.py (TITLE_JUNK_PATTERNS), đổi truyện thì sửa ở đó
    for pattern in config.TITLEDEL_JUNK_PATTERNS:
        content = re.sub(pattern, '', content, count=1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✔ {filename}")

print("Hoàn thành!")