#!/usr/bin/env python3

import os
from pathlib import Path
from datetime import datetime
import re

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "venv_new",      # Added: skip venv_new
    "dist",
    "build",
    ".next",
    ".idea",
    ".vscode",
    ".cache",
    "data",
}

SKIP_FILES = {
    ".wasm",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".bin",
    ".pyc",
    ".pyo",
}

# Skip patterns for files
SKIP_PATTERNS = [
    r'.*_dump\.txt$',           # Skip any file ending with _dump.txt
    r'.*_safe_dump_.*\.txt$',   # Skip safe dump files
    r'.*\.txt$',                # Skip ALL .txt files
    r'.*\.bak$',                # Skip backup files
    r'.*\.backup$',             # Skip backup files
    r'.*\.orig$',               # Skip original files
    r'.*\.patch$',              # Skip patch files
    r'.*\.rej$',                # Skip rejected patch files
    r'.*\.corrupt_backup$',     # Skip corrupt backups
    r'.*\.clean$',              # Skip clean backup files
    r'.*\.restored$',           # Skip restored files
    r'.*_bak_.*\.py$',          # Skip backup Python files
    r'.*\.bak_.*',              # Skip any .bak_* files
]

TEXT_EXTS = {
    ".js",".jsx",".ts",".tsx",
    ".py",".java",".c",".cpp",".h",".hpp",
    ".go",".rs",".php",".rb",".swift",".kt",
    ".html",".css",".scss",".sass",
    ".json",".xml",".yaml",".yml",".toml",
    ".md",".sql",".sh",".bat",
    ".env",".ini",".cfg",".conf",".csv"
}

MAX_SIZE = 5 * 1024 * 1024   # 5MB

def should_skip_file(filename):
    """Check if file should be skipped based on patterns"""
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, filename):
            return True
    return False

def is_text(path):
    return path.suffix.lower() in TEXT_EXTS

def should_skip_dir(dirname):
    return dirname in SKIP_DIRS

def write_tree(root, out):
    out.write("=" * 100 + "\n")
    out.write("PROJECT STRUCTURE\n")
    out.write("=" * 100 + "\n\n")

    for current, dirs, files in os.walk(root):
        # Skip directories properly
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        rel = os.path.relpath(current, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1

        indent = "│   " * depth
        name = os.path.basename(current) if rel != "." else os.path.basename(root)

        out.write(f"{indent}📁 {name}\n")
        
        # Filter files before writing tree
        filtered_files = []
        for f in sorted(files):
            # Skip .txt files and backup files in tree view too
            if f.endswith('.txt') or should_skip_file(f):
                continue
            # Skip .bak and .backup files
            if f.endswith(('.bak', '.backup', '.orig', '.patch', '.rej', '.clean', '.restored')):
                continue
            filtered_files.append(f)
        
        for f in filtered_files:
            out.write(f"{indent}│── {f}\n")

def dump_files(root, out):
    out.write("\n\n")
    out.write("=" * 100 + "\n")
    out.write("FILE CONTENTS\n")
    out.write("=" * 100 + "\n\n")

    for current, dirs, files in os.walk(root):
        # Skip directories properly
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for file in sorted(files):
            # Skip dump files, .txt files, and backup files
            if should_skip_file(file):
                continue
            
            # Skip any .txt files
            if file.endswith('.txt'):
                continue
                
            # Skip backup files explicitly
            if file.endswith(('.bak', '.backup', '.orig', '.patch', '.rej', '.clean', '.restored')):
                continue
            
            # Skip files with backup patterns
            if '.bak_' in file:
                continue

            path = Path(current) / file

            # Skip binary files
            if path.suffix.lower() in SKIP_FILES:
                continue

            if not is_text(path):
                continue

            if path.stat().st_size > MAX_SIZE:
                continue

            rel = path.relative_to(root)

            out.write("\n")
            out.write("=" * 100 + "\n")
            out.write(f"FILE: {rel}\n")
            out.write("=" * 100 + "\n\n")

            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        out.write(f"{i:5d}: {line}")

            except Exception as e:
                out.write(f"\nERROR: {e}\n")

            out.write("\n")

def main():
    root = os.getcwd()
    name = os.path.basename(root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(root, f"{name}_{stamp}_dump.txt")

    print(f"📂 Scanning: {root}")
    print(f"📝 Output: {outfile}")
    print("⏳ This may take a few seconds...")
    print("⚠️  Skipping: venv_new, .txt files, backup files (.bak, .backup, .orig, etc.)")

    with open(outfile, "w", encoding="utf-8") as out:
        out.write("PROJECT DUMP\n")
        out.write(f"Root : {root}\n")
        out.write(f"Date : {datetime.now()}\n\n")
        write_tree(root, out)
        dump_files(root, out)

    print(f"\n✓ Dump written to:\n{outfile}")

if __name__ == "__main__":
    main()