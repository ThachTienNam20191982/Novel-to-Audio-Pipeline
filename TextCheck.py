import os
import re

folder = "Cleaned"

pattern = re.compile(r"^Chuong_(\d+)\.txt$")

numbers = []

for filename in os.listdir(folder):
    match = pattern.match(filename)
    if match:
        numbers.append(int(match.group(1)))

numbers.sort()

missing = []

for expected in range(numbers[0], numbers[-1] + 1):
    if expected not in numbers:
        missing.append(expected)

print(f"Chương đầu: {numbers[0]}")
print(f"Chương cuối: {numbers[-1]}")
print(f"Tổng file: {len(numbers)}")

if missing:
    print("\nCác chương bị thiếu:")
    print(", ".join(map(str, missing)))
else:
    print("\nDanh sách chương liên tiếp, không thiếu chương nào.")