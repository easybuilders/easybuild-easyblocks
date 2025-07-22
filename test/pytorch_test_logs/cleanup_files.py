#!/usr/bin/env python3

"""This script strips content and filenames of PyTorch test result XML files in a deterministic way and formats them.
The intent is to keep the general structure of the files but still make them shorter and easier to read.

Usage: Pass the target directory as the single argument or
run this script to format the XML files in the "full" directory next to the script.
"""

import re
import subprocess
import sys
from hashlib import md5
from pathlib import Path


def shorten_filename(path: Path) -> Path:
    """Shorten the file name by truncating random part of .e.g. test_quantization-d1303cbc2b57cf06.xml"""
    match = re.search(r'-(?P<hash>[a-z0-9]{6,})\.xml$', path.name)
    if match:
        fixed_part: str = path.name[:match.start()]
        short_hash = match['hash'][:5]
        new_name: Path = path.with_name(f"{fixed_part}-{short_hash}.xml")
        path.rename(new_name)
        return new_name
    return path


def shorten_content(path: Path):
    """Shorten attribute values and tag content (stdout, stderr, etc.) in the XML file."""
    content: str = path.read_text(encoding='utf-8')

    # Shorten messages in tags: <skipped message="...">
    content = re.sub(r'message="[^"]+"', 'message="..."', content)
    # Shorten time
    content = re.sub(r'time="[^"]+"', 'time="4.2"', content)
    # Ignore timestamp & hostname
    content = re.sub(r'timestamp="[^"]+"', '', content)
    content = re.sub(r'hostname="[^"]+"', '', content)
    # Remove type attribute from <skipped> tags
    content = re.sub(r'(<skipped)\s+type="[^"]+"', r'\1', content)

    # Remove stdout/stderr from about half of the files.
    # For the other half just shorten it.
    remove_output: bool = int(md5(str(path.name).encode('utf-8')).hexdigest(), 16) % 2 == 0

    # Shorten output shown between various tags
    for tag in ["error", "failure", "skipped", "system-out", "system-err", "rerun"]:
        # Beware of multiline content in tags and empty tags (<tag/> or <tag key="value"/>)
        pattern = re.compile(
            rf'(<{tag}([^>/]*?)>)(.*?)</{tag}>',
            re.DOTALL
        )
        if remove_output and tag in ["system-out", "system-err"]:
            content = pattern.sub('', content)
        else:
            content = pattern.sub(rf'\1[snip]</{tag}>', content)

    # Remove empty lines
    content = re.sub(r'\n\s*\n', '\n', content)
    # Combine empty tags
    content = re.sub(r'(<(\w+) [^>]*)>\s*</\2>', r'\1/>', content)

    path.write_text(content, encoding='utf-8')


def format_xml(path: Path) -> bool:
    try:
        subprocess.check_output(
            ["xmllint", "--format", str(path), "-o", str(path)],
            encoding='utf-8',
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        print(f'\nError formatting {path}: {e.output}', file=sys.stderr)
        return False
    return True


def remove_if_empty(path: Path) -> bool:
    content = path.read_text(encoding='utf-8')
    if not re.search(r'<testsuite[^>]*[^/]>', content) and '<!--' not in content:
        path.unlink()
        return True
    return False


def main():
    default_directory = Path(__file__).resolve().parent / "test-reports"
    if '--help' in sys.argv or '-h' in sys.argv:
        print("Usage: python cleanup_files.py [target_directory]")
        print(f"Default target directory {default_directory}.")
        sys.exit(1)
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_directory
    xml_files = list(target_dir.rglob("*.xml"))
    num_files = len(xml_files)

    reply = input(f"Process {num_files} XML files in {target_dir}? [y/n] ").strip()
    if not re.match(r'^[Yy]$', reply):
        print("Aborting.")
        sys.exit(1)

    print(f"Processing file 0/{num_files}...", end='', flush=True)

    for i, path in enumerate(xml_files, 1):
        print(f"\rProcessing file {i}/{num_files}...", end='', flush=True)

        if remove_if_empty(path):
            continue

        path = shorten_filename(path)
        shorten_content(path)
        if not format_xml(path):
            sys.exit(1)

    # Delete empty directories
    for d in sorted(target_dir.rglob("*"), key=lambda p: -len(str(p))):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()

    print(" done.")


if __name__ == "__main__":
    main()
