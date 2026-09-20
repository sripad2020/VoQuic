import ast
import os
import sys

def check_file_syntax(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()
    try:
        ast.parse(code, filename=filepath)
        print(f"[OK] {filepath}")
        return True
    except SyntaxError as e:
        print(f"[SYNTAX ERROR] {filepath}: {e}")
        return False

def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    success = True
    for dirpath, _, filenames in os.walk(root_dir):
        if ".git" in dirpath or "__pycache__" in dirpath:
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                full_path = os.path.join(dirpath, filename)
                if not check_file_syntax(full_path):
                    success = False
    
    if success:
        print("\nAll Python files passed syntax check successfully!")
    else:
        print("\nSyntax errors detected!")
        sys.exit(1)

if __name__ == "__main__":
    main()
