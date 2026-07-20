import os
import re

FOLDER = "Cleaned"

for filename in os.listdir(FOLDER):
    if not filename.endswith(".txt"):
        continue

    path = os.path.join(FOLDER, filename)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Xóa dòng đầu
    content = re.sub(
        r'^Huấn Luyện Gia Tầng Lớp Thấp Nhất Của Thế Giới\s*\r?\n',
        '',
        content,
        count=1
    )

    # Xóa đúng chuỗi "Pokemon / " ở đầu dòng, giữ lại phần sau
    content = re.sub(
        r'^Pokemon\s*/\s*',
        '',
        content,
        count=1
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✔ {filename}")

print("Hoàn thành!")