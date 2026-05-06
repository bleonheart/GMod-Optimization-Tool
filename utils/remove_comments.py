"""
Simple script to remove comments from Lua files.
Preserves long comment blocks that start at the beginning of a line ("--[[ ... ]]").
Removes:
- Pure single-line comments that start with "--" (with any leading whitespace)
- Inline comments introduced by "--" that appear after code, while respecting strings
"""
import os
import re
import sys
import subprocess

def remove_comments(content):
    """Remove Lua single-line and inline comments, preserve top-of-line long blocks."""
    bom_prefix = '\ufeff' if content.startswith('\ufeff') else ''
    if bom_prefix:
        content = content[1:]
    lines = content.split('\n')
    cleaned_lines = []
    long_block_start_re = re.compile('^\\s*--\\[(=*)\\[')

    def find_inline_comment_start(s: str) -> int:
        """Return index of first '--' outside of strings/long strings; -1 if none."""
        in_single = False
        in_double = False
        long_str_eq = -1
        i = 0
        length = len(s)
        while i < length:
            ch = s[i]
            if in_single:
                if ch == '\\':
                    i += 2
                    continue
                if ch == "'":
                    in_single = False
                i += 1
                continue
            if in_double:
                if ch == '\\':
                    i += 2
                    continue
                if ch == '"':
                    in_double = False
                i += 1
                continue
            if long_str_eq >= 0:
                if ch == ']':
                    j = i + 1
                    eq_count = 0
                    while j < length and s[j] == '=':
                        eq_count += 1
                        j += 1
                    if eq_count == long_str_eq and j < length and (s[j] == ']'):
                        long_str_eq = -1
                        i = j + 1
                        continue
                i += 1
                continue
            if ch == "'":
                in_single = True
                i += 1
                continue
            if ch == '"':
                in_double = True
                i += 1
                continue
            if ch == '[':
                j = i + 1
                eq_count = 0
                while j < length and s[j] == '=':
                    eq_count += 1
                    j += 1
                if j < length and s[j] == '[':
                    long_str_eq = eq_count
                    i = j + 1
                    continue
            if ch == '-' and i + 1 < length and (s[i + 1] == '-'):
                return i
            i += 1
        return -1
    i = 0
    while i < len(lines):
        line = lines[i]
        m = long_block_start_re.match(line)
        if m is not None:
            eqs = m.group(1)
            closing = ']' + eqs + ']'
            cleaned_lines.append(line.rstrip())
            if closing in line:
                i += 1
                continue
            i += 1
            closing_re = re.compile(re.escape(closing))
            found_closing = False
            while i < len(lines):
                cleaned_lines.append(lines[i].rstrip())
                if closing_re.search(lines[i]):
                    i += 1
                    found_closing = True
                    break
                i += 1
            if not found_closing and i >= len(lines):
                break
            continue
        if line.lstrip().startswith('--'):
            i += 1
            continue
        idx = find_inline_comment_start(line)
        if idx >= 0:
            kept = line[:idx].rstrip()
            tail = line[idx:]
            m2 = re.match('--\\[(=*)\\[', tail)
            if m2 is not None:
                eqs2 = m2.group(1)
                closing2 = ']' + eqs2 + ']'
                closing2_re = re.compile(re.escape(closing2))
                if closing2_re.search(tail):
                    cleaned_lines.append(kept)
                    i += 1
                    continue
                i += 1
                found_closing2 = False
                max_skip = 50
                skipped = 0
                start_skip = i
                while i < len(lines) and skipped < max_skip:
                    if closing2_re.search(lines[i]):
                        i += 1
                        found_closing2 = True
                        break
                    i += 1
                    skipped += 1
                if not found_closing2:
                    i = start_skip
                    cleaned_lines.append(kept)
                    i += 1
                    continue
                cleaned_lines.append(kept)
                continue
            cleaned_lines.append(kept)
        else:
            cleaned_lines.append(line.rstrip())
        i += 1
    result = '\n'.join(cleaned_lines)
    return bom_prefix + result

def run_glualint_pretty_print(target_dir):
    """Run glualint pretty-print on the target directory."""
    try:
        print(f'Running glualint pretty-print on {target_dir}...')
        result = subprocess.run(['glualint', 'pretty-print', target_dir], capture_output=True, text=True, check=True)
        print('glualint pretty-print completed successfully')
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f'Error running glualint pretty-print: {e}')
        if e.stdout:
            print(f'stdout: {e.stdout}')
        if e.stderr:
            print(f'stderr: {e.stderr}')
    except FileNotFoundError:
        print("Error: glualint not found. Make sure it's installed and in your PATH.")

def process_file(filepath):
    """Process a single file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        cleaned = remove_comments(content)
        if content != cleaned:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            print(f'Cleaned: {filepath}')
            return True
        return False
    except Exception as e:
        print(f'Error: {filepath} - {e}')
        return False

def main():
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = '.'
    if os.path.isfile(target) and target.endswith('.lua'):
        process_file(target)
    else:
        count = 0
        for root, dirs, files in os.walk(target):
            for file in files:
                if file.endswith('.lua'):
                    if process_file(os.path.join(root, file)):
                        count += 1
        print(f'Processed {count} files')
        run_glualint_pretty_print(target)

def remove_comments_from_directory(target_dir):
    """Remove comments from all Lua files in the target directory.

    Returns:
        tuple: (size_saved, files_processed) where size_saved is the total bytes saved
               and files_processed is the number of files that had comments removed.
    """
    import os
    total_size_saved = 0
    files_processed = 0
    if os.path.isfile(target_dir) and target_dir.endswith('.lua'):
        original_size = os.path.getsize(target_dir)
        if process_file(target_dir):
            new_size = os.path.getsize(target_dir)
            total_size_saved = original_size - new_size
            files_processed = 1
    else:
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                if file.endswith('.lua'):
                    filepath = os.path.join(root, file)
                    original_size = os.path.getsize(filepath)
                    if process_file(filepath):
                        new_size = os.path.getsize(filepath)
                        total_size_saved += original_size - new_size
                        files_processed += 1
    run_glualint_pretty_print(target_dir)
    return (total_size_saved, files_processed)
if __name__ == '__main__':
    main()
