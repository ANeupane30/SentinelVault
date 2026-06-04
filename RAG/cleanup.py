import os
import shutil

files_to_remove = [
    "Dockerfile",
    "docker-compose.yml",
    ".env",
    "correction_ledger.jsonl"
]

dirs_to_remove = [
    "__pycache__"
]

for f in files_to_remove:
    if os.path.exists(f):
        os.remove(f)
        print(f"REMOVED: {f} (Unnecessary for Render deployment)")

for d in dirs_to_remove:
    if os.path.exists(d):
        shutil.rmtree(d)
        print(f"REMOVED: {d}/ (Compiled cache)")

test_files = ["test_debug_llm.py", "test_deepinfra.py", "test_e2e.py", "test_startup.py"]
for t in test_files:
    print(f"KEPT: {t} (Hard constraint: Do NOT delete any .py files)")
