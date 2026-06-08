#!/usr/bin/env python3
"""
Preprocessing module: given a CIA dataset instance and a cloned repo, produces
three input files under output_dir/:
  - issue.json            : issue + seed method info (no ground truth fields)
  - repo_structure.xml    : all non-test Java methods with source + Javadoc summary
  - commit_history.json   : full git log up to parent_commit, files-per-commit

Can also be run standalone:
    python3 extract_methods.py <instance_id> <repo_dir> [output_dir]

If output_dir is omitted it defaults to  input/<instance_id>/  relative to this file.
"""

import json
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Java parsing helpers
# ---------------------------------------------------------------------------

def _extract_class_name(src: str) -> str:
    m = re.search(r'\bclass\s+(\w+)', src)
    return m.group(1) if m else "Unknown"


def _extract_javadoc(src: str, method_start: int) -> str:
    """Return the Javadoc comment immediately preceding method_start, if any."""
    block = src[:method_start].rstrip()
    if not block.endswith("*/"):
        return ""
    doc_end   = block.rfind("*/")
    doc_start = block.rfind("/**")
    if doc_start == -1:
        return ""
    raw   = block[doc_start:doc_end + 2]
    lines = [re.sub(r'^\s*\*\s?', '', l) for l in raw.split('\n')]
    lines = [l for l in lines if l.strip() not in ('/**', '*/')]
    text  = ' '.join(l.strip() for l in lines if l.strip())
    m     = re.match(r'([^.!?]+[.!?])', text)
    return m.group(1).strip() if m else text[:200].strip()


def _extract_methods(src: str, filepath: str) -> list:
    """
    Extract methods using a two-pass approach:
      1. Regex to find method-signature candidates.
      2. Brace-walking to find the closing '}'.
    Returns list of dicts: {name, body, summary, start_line, end_line, path}
    """
    sig_pattern = re.compile(
        r'(?:(?:public|protected|private|static|final|synchronized|abstract|native|'
        r'default|strictfp)\s+)*'
        r'(?!if\b|for\b|while\b|switch\b|catch\b|return\b)'
        r'(?:(?:<[^>]+>\s+)?)'
        r'(?:[\w\[\]<>,\s]+?\s+)'
        r'(\w+)'
        r'\s*\([^)]*\)'
        r'(?:\s*throws\s+[\w\s,]+)?'
        r'\s*\{',
        re.MULTILINE,
    )

    _SKIP = frozenset({
        'if', 'for', 'while', 'switch', 'catch', 'try', 'else',
        'new', 'return', 'throw', 'case', 'class', 'interface',
        'enum', 'import', 'package', 'extends', 'implements',
    })

    methods = []
    for m in sig_pattern.finditer(src):
        name = m.group(1)
        if name in _SKIP:
            continue

        brace_start = m.end() - 1
        depth, pos  = 0, brace_start
        while pos < len(src):
            if src[pos] == '{':
                depth += 1
            elif src[pos] == '}':
                depth -= 1
                if depth == 0:
                    break
            pos += 1

        body       = src[m.start():pos + 1]
        start_line = src[:m.start()].count('\n') + 1
        end_line   = src[:pos + 1].count('\n') + 1
        summary    = _extract_javadoc(src, m.start())
        if not summary:
            summary = f"Method {name} in {Path(filepath).stem}"

        methods.append({
            'name':       name,
            'body':       body,
            'summary':    summary,
            'start_line': start_line,
            'end_line':   end_line,
            'path':       filepath,
        })

    return methods


# ---------------------------------------------------------------------------
# Commit history generation
# ---------------------------------------------------------------------------

def _build_commit_history(repo_dir: Path, commit: str, parent_commit: str) -> dict:
    """
    Run git log up to parent_commit and return the commit_history dict.
    Format: { "{commit}<sep>{parent_commit}": { hash: [files], ... } }
    """
    result = subprocess.run(
        ['git', 'log', '--name-only', '--format=%H', parent_commit],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr.strip()}")

    history      = {}
    current_hash = None
    current_files = []

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            if current_hash is not None and current_files:
                history[current_hash] = current_files
            current_hash  = None
            current_files = []
        elif len(line) == 40 and re.fullmatch(r'[0-9a-f]+', line):
            if current_hash is not None and current_files:
                history[current_hash] = current_files
            current_hash  = line
            current_files = []
        else:
            if current_hash is not None:
                current_files.append(line)

    if current_hash is not None and current_files:
        history[current_hash] = current_files

    key = f"{commit}<sep>{parent_commit}"
    return {key: history}


# ---------------------------------------------------------------------------
# Repo clone / checkout
# ---------------------------------------------------------------------------

def prepare_repo(repo_key: str, parent_commit: str, repos_folder: Path) -> Path:
    """
    Ensure the repo is cloned under repos_folder/<project_name> and
    checked out at parent_commit.  Returns the repo directory.
    """
    project_name = repo_key.split('/')[-1]
    repo_dir     = repos_folder / project_name

    if not repo_dir.exists():
        url = f"https://github.com/{repo_key}.git"
        print(f"    [clone] {url} → {repo_dir}", flush=True)
        subprocess.run(
            ['git', 'clone', '--quiet', url, str(repo_dir)],
            check=True,
        )
    else:
        # Fetch any missing objects (needed when switching to a different commit)
        subprocess.run(
            ['git', '-C', str(repo_dir), 'fetch', '--quiet', '--all'],
            check=True,
        )

    print(f"    [checkout] {parent_commit[:12]}... in {repo_dir.name}", flush=True)
    subprocess.run(
        ['git', '-C', str(repo_dir), 'checkout', '-q', '-f', parent_commit],
        check=True,
    )

    return repo_dir


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_for_instance(
    instance_id: str,
    inst_data: dict,
    repo_dir: Path,
    output_dir: Path,
) -> bool:
    """
    Generate issue.json, repo_structure.xml, and commit_history.json for one
    CIA instance.  Returns True on success, False if the seed method was not found.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    commit        = inst_data['commit']
    parent_commit = inst_data['parent-commit']
    seed_rel_path = inst_data['path']
    seed_name     = inst_data['name']

    # 1. Walk non-test Java files from the repo root
    def _is_test(p: Path) -> bool:
        parts_lower = [x.lower() for x in p.parts]
        return (
            'test' in parts_lower or 'tests' in parts_lower
            or p.stem.lower().endswith('test')
            or p.stem.lower().endswith('tests')
        )

    java_files = sorted(p for p in repo_dir.rglob("*.java") if not _is_test(p))
    print(f"    [extract] {len(java_files)} non-test Java files in {repo_dir.name}", flush=True)

    # 2. Extract methods from every file
    all_file_data    = []
    seed_method_body = None

    for jf in java_files:
        src        = jf.read_text(encoding='utf-8', errors='replace')
        class_name = _extract_class_name(src)
        methods    = _extract_methods(src, str(jf))
        if not methods:
            continue

        rel = str(jf.relative_to(repo_dir))
        all_file_data.append({
            'path':       rel,
            'class_name': class_name,
            'methods':    methods,
        })

        if rel == seed_rel_path:
            for meth in methods:
                if meth['name'] == seed_name:
                    seed_method_body = meth['body']
                    break

    total_methods = sum(len(fd['methods']) for fd in all_file_data)
    print(
        f"    [extract] {total_methods} methods across {len(all_file_data)} files",
        flush=True,
    )

    # 3. Write issue.json  (no ground-truth fields)
    issue = {
        'instance_id':        instance_id,
        'repo':               inst_data['repo'],
        'commit':             commit,
        'parent_commit':      parent_commit,
        'seed_file':          seed_rel_path,
        'seed_method':        seed_name,
        'focal_method_id':    inst_data['focal-method-id'],
        'issue_summary':      inst_data['issue-summary'],
        'issue_description':  inst_data['issue-description'],
        'seed_method_source': seed_method_body,
    }
    issue_path = output_dir / 'issue.json'
    issue_path.write_text(json.dumps(issue, indent=2), encoding='utf-8')
    print(f"    [wrote] {issue_path}", flush=True)

    # 4. Write repo_structure.xml
    xml_lines = ['<repository>']
    for fd in all_file_data:
        pkg = '.'.join(fd['path'].replace('.java', '').split('/')[:-1])
        xml_lines.append(f'  <package name="{pkg}">')
        xml_lines.append(f'    <class name="{fd["class_name"]}" file="{fd["path"]}">')
        for m in fd['methods']:
            xml_lines.append(f'      <method name="{m["name"]}">')
            xml_lines.append(f'        <summary>{m["summary"]}</summary>')
            xml_lines.append( '        <source><![CDATA[')
            xml_lines.append(m['body'])
            xml_lines.append( '        ]]></source>')
            xml_lines.append( '      </method>')
        xml_lines.append('    </class>')
        xml_lines.append('  </package>')
    xml_lines.append('</repository>')

    xml_str  = '\n'.join(xml_lines)
    xml_path = output_dir / 'repo_structure.xml'
    xml_path.write_text(xml_str, encoding='utf-8')
    print(f"    [wrote] {xml_path}  ({len(xml_str):,} chars)", flush=True)

    # 5. Write commit_history.json
    print(f"    [git log] building commit history ...", flush=True)
    history     = _build_commit_history(repo_dir, commit, parent_commit)
    ch_path     = output_dir / 'commit_history.json'
    ch_path.write_text(json.dumps(history, indent=2), encoding='utf-8')
    n_commits   = len(next(iter(history.values())))
    print(f"    [wrote] {ch_path}  ({n_commits} commits)", flush=True)

    if seed_method_body is None:
        print(
            f"    [warn] seed method '{seed_name}' not found in {seed_rel_path}",
            flush=True,
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 extract_methods.py <instance_id> <repo_dir> [output_dir]")
        sys.exit(1)

    instance_id = sys.argv[1]
    repo_dir    = Path(sys.argv[2])

    base_dir    = Path(__file__).parent
    output_dir  = (
        Path(sys.argv[3]) if len(sys.argv) >= 4
        else base_dir / "input" / instance_id
    )
    cia_path    = base_dir / "assets" / "cia-dataset.json"

    with open(cia_path) as f:
        raw = json.load(f)

    inst_data = None
    for repo_key, instances in raw.items():
        for inst in instances:
            if inst['id'] == instance_id:
                inst_data = {**inst, 'repo': repo_key}
                break
        if inst_data:
            break

    if inst_data is None:
        print(f"[!] Instance '{instance_id}' not found in {cia_path}")
        sys.exit(1)

    ok = extract_for_instance(instance_id, inst_data, repo_dir, output_dir)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
