import os
import glob
import re

folder_path = "Cleaned"
output_file = os.path.join(folder_path, "0_Merged.txt")

txt_files = glob.glob(os.path.join(folder_path, "*.txt"))

def extract_number(filename):
    match = re.search(r'(\d+)', os.path.basename(filename))
    return int(match.group(1)) if match else float('inf')

txt_files.sort(key=extract_number)

with open(output_file, "w", encoding="utf-8") as outfile:
    for file in txt_files:
        with open(file, "r", encoding="utf-8") as infile:
            outfile.write(infile.read())
            outfile.write("\n\n")

print(f"Đã gộp {len(txt_files)} file.")