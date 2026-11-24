"""Add newly created Swift files to the existing Xcode project without regenerating it.

Run from anywhere:  python Tools/patch_project_files.py App/MJPEGTranscoder.swift App/TeslaReceiverPage.swift
The project file is OpenStep-format text, so the four entries Xcode needs per source file
(PBXBuildFile, PBXFileReference, group child, Sources phase entry) are inserted next to an
existing file's entries, which keeps the surrounding formatting untouched.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'TDSCarKit.xcodeproj' / 'project.pbxproj'
TEMPLATE = 'App/BrowserReceiverPage.swift'


def uid(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()[:24].upper()


def main(files: list[str]) -> int:
    text = PROJECT.read_text(encoding='utf-8')
    anchor_lines = [line for line in text.splitlines() if TEMPLATE in line]
    if len(anchor_lines) != 4:
        print(f'unexpected template entries: {len(anchor_lines)}')
        return 1
    build_anchor = next(l for l in anchor_lines if 'isa = PBXBuildFile' in l)
    ref_anchor = next(l for l in anchor_lines if 'isa = PBXFileReference' in l)
    source_anchor = next(l for l in anchor_lines if l.strip().endswith('in Sources */,'))
    group_anchor = next(l for l in anchor_lines if l.strip().endswith('*/,'))
    indent = source_anchor[:len(source_anchor) - len(source_anchor.lstrip())]

    for relative in files:
        if relative in text:
            print(f'skip (already present): {relative}')
            continue
        name = pathlib.PurePosixPath(relative).name
        new_ref = uid('ref:' + relative)
        new_build = uid('build:' + relative)
        build_line = (f'\t\t{new_build} /* {relative} in Sources */ = {{isa = PBXBuildFile; '
                      f'fileRef = {new_ref} /* {relative} */; }};\n')
        ref_line = (f'\t\t{new_ref} /* {relative} */ = {{isa = PBXFileReference; '
                    f'lastKnownFileType = sourcecode.swift; path = {relative}; '
                    f'sourceTree = "<group>"; }};\n')
        text = text.replace(build_anchor + '\n', build_anchor + '\n' + build_line, 1)
        text = text.replace(ref_anchor + '\n', ref_anchor + '\n' + ref_line, 1)
        text = text.replace(group_anchor + '\n',
                            group_anchor + '\n' + f'{indent}{new_ref} /* {relative} */,\n', 1)
        text = text.replace(source_anchor + '\n',
                            source_anchor + '\n' + f'{indent}{new_build} /* {relative} in Sources */,\n', 1)
        print(f'added: {relative}  ref={new_ref} build={new_build}')

    PROJECT.write_text(text, encoding='utf-8')
    print(f'wrote {PROJECT} ({PROJECT.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
