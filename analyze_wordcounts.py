import os
import re

def count_words(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        words = re.findall(r'\w+', content)
        return len(words)

def analyze_scripts(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('_script.txt'):
                path = os.path.join(root, file)
                count = count_words(path)
                print(f"File: {file} - Words: {count}")

if __name__ == "__main__":
    analyze_scripts("podcast_output")
