#!/usr/bin/env python3
"""
Usage:
    python3 evaluator.py          # evaluate both prompts
    python3 evaluator.py A        # evaluate prompt A only
    python3 evaluator.py B        # evaluate prompt B only
"""

import json
import random
import re
import statistics
import subprocess
import sys
import zipfile
from pathlib import Path

BASE_DIR     = Path(__file__).parent
ASSETS_DIR   = BASE_DIR / 'assets'
OUTPUTS_DIR  = BASE_DIR / 'outputs'
RESULTS_DIR  = BASE_DIR / 'results'
REPOS_FOLDER = BASE_DIR / 'repos'
CIA_DATASET  = ASSETS_DIR / 'cia-dataset.json'

PROMPTS         = ['A', 'B']
ALL_OUTPUTS_ZIP = ASSETS_DIR / 'all-outputs.zip'
ORIG_MODELS     = ['claude', 'gpt', 'gemini']

# ─── Metrics (inlined from ripple/ripple/utils.py; avoids networkx dependency) ─

def _compute_metrics_for_pair(pred, gold):
    pred_set, gold_set = set(pred), set(gold)
    inter     = pred_set & gold_set
    precision = len(inter) / len(pred_set) if pred_set else 0.0
    recall    = len(inter) / len(gold_set) if gold_set else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
    return {'precision': precision, 'recall': recall, 'f1-score': f1}


def _compute_hit_k(predicted, true, k, n, seed):
    random.seed(seed)
    runs = []
    for _ in range(n):
        hits = 0
        for inst_pred, inst_true in zip(predicted, true):
            inst_pred = sorted(list(inst_pred))
            inst_true = sorted(list(inst_true))
            sample = random.sample(inst_pred, k) if len(inst_pred) > k else inst_pred
            if set(sample) & set(inst_true):
                hits += 1
        runs.append(hits / len(predicted))
    return statistics.mean(runs)


def _compute_hit_custom(predicted, true, n, seed):
    random.seed(seed)
    runs = []
    for _ in range(n):
        hits = 0
        for inst_pred, inst_true in zip(predicted, true):
            k         = len(inst_pred)
            inst_pred = sorted(list(inst_pred))
            inst_true = sorted(list(inst_true))
            sample = random.sample(inst_pred, k) if len(inst_pred) > k else inst_pred
            if set(sample) & set(inst_true):
                hits += 1
        runs.append(hits / len(predicted))
    return statistics.mean(runs)


def _compute_micro(predicted, true):
    prec_parts, rec_parts = [], []
    for pred, gold in zip(predicted, true):
        pred_set, gold_set = set(pred), set(gold)
        inter = pred_set & gold_set
        prec_parts.append((len(inter), len(pred_set) if pred_set else 1))
        rec_parts.append((len(inter),  len(gold_set) if gold_set else 1))
    micro_p = sum(x[0] for x in prec_parts) / sum(x[1] for x in prec_parts)
    micro_r = sum(x[0] for x in rec_parts)  / sum(x[1] for x in rec_parts)
    return {'micro-precision': micro_p, 'micro-recall': micro_r}


def compute_metrics(predicted, true, n=100, seed=42):
    """Replicate ripple/ripple/utils.py:compute_metrics exactly."""
    precision, recall, f1 = [], [], []
    for inst_pred, inst_true in zip(predicted, true):
        m = _compute_metrics_for_pair(inst_pred, inst_true)
        precision.append(m['precision'])
        recall.append(m['recall'])
        f1.append(m['f1-score'])
    micro = _compute_micro(predicted, true)
    return {
        'precision':       statistics.mean(precision),
        'recall':          statistics.mean(recall),
        'f1-score':        statistics.mean(f1),
        'micro-precision': micro['micro-precision'],
        'micro-recall':    micro['micro-recall'],
        'hit@5':           _compute_hit_k(predicted, true, 5,  n, seed),
        'hit@10':          _compute_hit_k(predicted, true, 10, n, seed),
        'hit@custom':      _compute_hit_custom(predicted, true, n, seed),
    }


# ─── Java method parsing (for repo-based fallback) ────────────────────────────

_SIG_RE_BODY = re.compile(
    r'(?:(?:public|protected|private|static|final|synchronized|abstract|native|'
    r'default|strictfp)\s+)*'
    r'(?!if\b|for\b|while\b|switch\b|catch\b|return\b|new\b)'
    r'(?:(?:<[^>]+>\s+)?)'
    r'(?:[\w][\w\[\]<>,\s]*\s+)'
    r'(\w+)'
    r'\s*\([^)]*\)'
    r'(?:\s*throws\s+[\w\s,]+)?'
    r'\s*\{',
    re.MULTILINE,
)

_SKIP_NAMES = frozenset({
    'if', 'for', 'while', 'switch', 'catch', 'try', 'else', 'new',
    'return', 'throw', 'case', 'class', 'interface', 'enum', 'import',
    'package', 'extends', 'implements', 'super', 'this', 'assert', 'do',
    'break', 'continue', 'finally', 'instanceof', 'synchronized',
})


def _parse_methods_with_lines(src: str) -> list:
    """
    Return list of {name, start_line, end_line} for all methods found via
    brace-walking.  Same logic as extract_methods.py:_extract_methods but
    only keeps the fields needed for line-range lookup.
    """
    methods = []
    for m in _SIG_RE_BODY.finditer(src):
        name = m.group(1)
        if name in _SKIP_NAMES:
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
        start_line = src[:m.start()].count('\n') + 1
        end_line   = src[:pos + 1].count('\n') + 1
        methods.append({'name': name, 'start_line': start_line, 'end_line': end_line})
    return methods


# ─── GT extraction ────────────────────────────────────────────────────────────

# Signature regex for diff lines (optional trailing [{;] — handles Allman style
# and interface declarations; return type must start with a word character to
# prevent whitespace-only "return types" from matching method calls).
_SIG_RE_DIFF = re.compile(
    r'(?:(?:public|protected|private|static|final|synchronized|abstract|native|'
    r'default|strictfp)\s+)*'
    r'(?!if\b|for\b|while\b|switch\b|catch\b|return\b|new\b)'
    r'(?:(?:<[^>]+>\s+)?)'
    r'(?:[\w][\w\[\]<>,\s]*\s+)'
    r'(\w+)'
    r'\s*\([^)]*\)'
    r'(?:\s*throws\s+[\w\s,]+)?'
    r'\s*[{;]?',
    re.MULTILINE,
)


def _is_valid(name: str) -> bool:
    return name not in _SKIP_NAMES and len(name) > 1 and name[0].islower()


def _names_from_line(content: str) -> set:
    return {m.group(1) for m in _SIG_RE_DIFF.finditer(content) if _is_valid(m.group(1))}


def _hunk_old_line_ranges(diff_section: str) -> list:
    """
    Parse @@ headers and return (start, end) line-number ranges in the OLD file
    for every hunk that has actual removals or changes (old_count > 0).
    Pure insertions (old_count == 0) use start as an anchor line.
    """
    ranges = []
    for line in diff_section.splitlines():
        if not line.startswith('@@'):
            continue
        m = re.match(r'^@@ -(\d+)(?:,(\d+))? \+', line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        if count > 0:
            ranges.append((start, start + count - 1))
        elif start > 0:
            # Pure insertion: anchor to the line just before the insertion point
            ranges.append((start, start))
    return ranges


def _repo_gt_for_file(repo_dir: Path, parent_commit: str,
                      file_path: str, changed_ranges: list) -> set:
    """
    Check out parent_commit in repo_dir, read file_path, and return the names
    of methods whose body overlaps any of the changed_ranges line pairs.
    Returns an empty set if the repo or file is unavailable.
    """
    r = subprocess.run(
        ['git', '-C', str(repo_dir), 'checkout', '-q', '-f', parent_commit],
        capture_output=True,
    )
    if r.returncode != 0:
        return set()

    src_path = repo_dir / file_path
    if not src_path.exists():
        return set()

    src     = src_path.read_text(encoding='utf-8', errors='replace')
    methods = _parse_methods_with_lines(src)

    names = set()
    for method in methods:
        for s, e in changed_ranges:
            if method['start_line'] <= e and method['end_line'] >= s:
                names.add(method['name'])
                break
    return names


def extract_gt_methods(diff: str, impact_files: list,
                       parent_commit: str = None,
                       repo_dir: Path = None) -> dict:
    """
    Parse the commit diff to find which methods changed in each impact file.

    Primary path  — scan changed lines (+/-) and @@ context for method signatures.
    Fallback path — when a file yields no methods (body-only change, no signature
                    in any changed line), check out the source from repos/ and map
                    @@ hunk line numbers to the enclosing method.

    Returns: {file_path -> set of method_name strings}
    """
    impact_set    = set(impact_files)
    file_methods  = {f: set() for f in impact_files if f.endswith('.java')}
    file_sections = {}

    sections = re.split(r'(?=^diff --git )', diff, flags=re.MULTILINE)
    for section in sections:
        hdr = re.match(r'diff --git a/(.*?) b/', section)
        if not hdr:
            continue
        fpath = hdr.group(1)
        if fpath not in impact_set or not fpath.endswith('.java'):
            continue
        file_sections[fpath] = section

        names = set()
        for line in section.splitlines():
            if line.startswith(('---', '+++', 'diff ', 'index ',
                                 'new file', 'old file', 'Binary')):
                continue
            if line.startswith('@@'):
                ctx = re.sub(r'^@@[^@]*@@\s*', '', line).strip()
                if ctx and not re.search(r'\b(?:class|interface|enum)\b', ctx):
                    names |= _names_from_line(ctx)
                continue
            if line.startswith(('+', '-')):
                names |= _names_from_line(line[1:])
        file_methods[fpath] = names

    # Fallback: repo-based line-range lookup for files that yielded nothing
    use_repo = parent_commit and repo_dir and repo_dir.exists()
    for fpath in list(file_methods):
        if file_methods[fpath]:
            continue  # already resolved
        section = file_sections.get(fpath)
        if not section:
            continue
        changed_ranges = _hunk_old_line_ranges(section)
        if not changed_ranges:
            continue
        if use_repo:
            names = _repo_gt_for_file(repo_dir, parent_commit, fpath, changed_ranges)
            file_methods[fpath] = names
        # If repo unavailable, file_methods[fpath] stays empty

    return file_methods


def build_gt_set(file_methods: dict) -> set:
    """Flatten {file_path -> method_names} to a set of 'ClassName.methodName'."""
    gt = set()
    for fpath, methods in file_methods.items():
        cls = Path(fpath).stem
        for m in methods:
            gt.add(f'{cls}.{m}')
    return gt


# ─── Prediction helpers ───────────────────────────────────────────────────────

def normalize_predictions(raw: list, seed_class: str, seed_method: str) -> set:
    """
    Convert LLM output to 'ClassName.methodName' and remove the seed method.
    LLM format: 'ClassName,methodName' (comma as separator).
    """
    seed_key = f'{seed_class}.{seed_method}'
    pred = set()
    for entry in raw:
        if isinstance(entry, str):
            normalized = entry.replace(',', '.', 1)
            if normalized != seed_key:
                pred.add(normalized)
    return pred


# ─── Per-instance evaluation ─────────────────────────────────────────────────

def evaluate_instance(inst_data: dict, output_entry: dict) -> dict:
    instance_id  = inst_data['id']
    repo         = inst_data['repo']
    seed_file    = inst_data['path']
    seed_method  = inst_data['name']
    seed_class   = Path(seed_file).stem

    impact_files   = inst_data['impact-set-files']
    n_impact_files = len(impact_files)
    complexity     = 'leq_5_files' if n_impact_files <= 5 else 'gt_5_files'

    project_name = repo.split('/')[-1]
    repo_dir     = REPOS_FOLDER / project_name
    repo_dir     = repo_dir if repo_dir.exists() else None

    file_methods = extract_gt_methods(
        inst_data['diff'],
        impact_files,
        parent_commit=inst_data.get('parent-commit'),
        repo_dir=repo_dir,
    )
    gt_methods = build_gt_set(file_methods)

    parse_failed = output_entry.get('parse_failed', False)
    if parse_failed:
        pred_methods = set()
    else:
        pred_methods = normalize_predictions(
            output_entry.get('impacted_methods', []),
            seed_class,
            seed_method,
        )

    inter     = pred_methods & gt_methods
    precision = len(inter) / len(pred_methods) if pred_methods else 0.0
    recall    = len(inter) / len(gt_methods)   if gt_methods   else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0

    return {
        'type':           'instance',
        'instance_id':    instance_id,
        'repo':           repo,
        'seed_method':    f'{seed_class}.{seed_method}',
        'n_gt_files':     n_impact_files,
        'complexity':     complexity,
        'gt_methods':     sorted(gt_methods),
        'pred_methods':   sorted(pred_methods),
        'n_gt_methods':   len(gt_methods),
        'n_pred_methods': len(pred_methods),
        'precision':      round(precision, 6),
        'recall':         round(recall, 6),
        'f1':             round(f1, 6),
        'parse_failed':   parse_failed,
    }


# ─── Aggregate metrics ────────────────────────────────────────────────────────

def _micro_f1(micro_p: float, micro_r: float) -> float:
    return (2 * micro_p * micro_r) / (micro_p + micro_r) if (micro_p + micro_r) else 0.0


def compute_table1(instance_results: list) -> dict:
    """Table 1: macro mean P/R/F1 + Hit@5 + Hit@10 + Hit@custom."""
    predicted = [set(r['pred_methods']) for r in instance_results]
    true      = [set(r['gt_methods'])   for r in instance_results]
    m         = compute_metrics(predicted, true, n=100, seed=42)
    return {
        'mean_precision': round(m['precision'], 6),
        'mean_recall':    round(m['recall'], 6),
        'mean_f1':        round(m['f1-score'], 6),
        'hit_at_5':       round(m['hit@5'], 6),
        'hit_at_10':      round(m['hit@10'], 6),
        'hit_at_custom':  round(m['hit@custom'], 6),
    }


def compute_table5(instance_results: list) -> dict:
    """Table 5: stratify by len(impact-set-files) <= 5 vs > 5; micro + macro P/R/F1."""
    leq5 = [r for r in instance_results if r['complexity'] == 'leq_5_files']
    gt5  = [r for r in instance_results if r['complexity'] == 'gt_5_files']

    result = {}
    for key, subset in [('leq_5_files', leq5), ('gt_5_files', gt5), ('full', instance_results)]:
        if not subset:
            result[key] = {'n': 0, 'note': 'no instances in this stratum'}
            continue
        predicted = [set(r['pred_methods']) for r in subset]
        true      = [set(r['gt_methods'])   for r in subset]
        m         = compute_metrics(predicted, true, n=100, seed=42)
        micro_p, micro_r = m['micro-precision'], m['micro-recall']
        result[key] = {
            'n':               len(subset),
            'micro_precision': round(micro_p, 6),
            'micro_recall':    round(micro_r, 6),
            'micro_f1':        round(_micro_f1(micro_p, micro_r), 6),
            'macro_precision': round(m['precision'], 6),
            'macro_recall':    round(m['recall'], 6),
            'macro_f1':        round(m['f1-score'], 6),
        }
    return result


# ─── Original-pipeline evaluation (ID-space) ─────────────────────────────────

def _aggregate_original(data: dict) -> set:
    """
    Replicate the paper's aggregation: set.intersection across the 5 candidates
    within each component, then set.union across all 6 components.
    Returns a set of numeric method-ID strings.
    """
    result = set()
    for comp in data.get('impact-analysis', []):
        cands = comp.get('components', {})
        if not isinstance(cands, dict):
            continue
        sets = [set(v.get('impact-set-predicted', []))
                for v in cands.values() if isinstance(v, dict)]
        if sets:
            inter = sets[0].copy()
            for s in sets[1:]:
                inter &= s
            result |= inter
    return result


def _orig_stratum(subset: list) -> dict:
    if not subset:
        return {'n': 0, 'note': 'no instances in this stratum'}
    predicted = [set(r['pred']) for r in subset]
    true      = [set(r['gt'])   for r in subset]
    m         = compute_metrics(predicted, true, n=100, seed=42)
    micro_p, micro_r = m['micro-precision'], m['micro-recall']
    return {
        'n':               len(subset),
        'micro_precision': round(micro_p, 6),
        'micro_recall':    round(micro_r, 6),
        'micro_f1':        round(_micro_f1(micro_p, micro_r), 6),
        'macro_precision': round(m['precision'], 6),
        'macro_recall':    round(m['recall'], 6),
        'macro_f1':        round(m['f1-score'], 6),
    }


def evaluate_original_pipeline(instance_ids: list, cia_data: dict) -> dict:
    """
    For each model in ORIG_MODELS, compute Table 1 and Table 5 on the given
    instance_ids using the original pipeline's outputs from all-outputs.zip.
    GT is taken from cia-dataset.json 'impact-set-methods' (numeric IDs).
    Returns: {model: {'table1': ..., 'table5': ..., 'per_instance': [...]}}
    """
    if not ALL_OUTPUTS_ZIP.exists():
        return {}

    results_by_model = {}
    with zipfile.ZipFile(ALL_OUTPUTS_ZIP) as z:
        for model in ORIG_MODELS:
            per_inst = []
            for inst_id in instance_ids:
                inst      = cia_data.get(inst_id, {})
                gt        = set(inst.get('impact-set-methods', []))
                n_files   = len(inst.get('impact-set-files', []))
                complexity = 'leq_5_files' if n_files <= 5 else 'gt_5_files'
                try:
                    with z.open(f'all-outputs/{model}/{inst_id}.json') as f:
                        pred = _aggregate_original(json.load(f))
                except KeyError:
                    pred = set()
                inter = pred & gt
                p  = len(inter) / len(pred) if pred else 0.0
                r  = len(inter) / len(gt)   if gt   else 0.0
                f1 = 2 * p * r / (p + r)    if (p + r) > 0 else 0.0
                per_inst.append({
                    'instance_id': inst_id,
                    'complexity':  complexity,
                    'gt':          sorted(gt),
                    'pred':        sorted(pred),
                    'precision':   round(p,  6),
                    'recall':      round(r,  6),
                    'f1':          round(f1, 6),
                })

            predicted = [set(r['pred']) for r in per_inst]
            true      = [set(r['gt'])   for r in per_inst]
            m         = compute_metrics(predicted, true, n=100, seed=42)
            table1 = {
                'mean_precision': round(m['precision'],  6),
                'mean_recall':    round(m['recall'],     6),
                'mean_f1':        round(m['f1-score'],   6),
                'hit_at_5':       round(m['hit@5'],      6),
                'hit_at_10':      round(m['hit@10'],     6),
                'hit_at_custom':  round(m['hit@custom'], 6),
            }
            leq5 = [r for r in per_inst if r['complexity'] == 'leq_5_files']
            gt5  = [r for r in per_inst if r['complexity'] == 'gt_5_files']
            table5 = {
                'leq_5_files': _orig_stratum(leq5),
                'gt_5_files':  _orig_stratum(gt5),
                'full':        _orig_stratum(per_inst),
            }
            results_by_model[model] = {
                'table1':       table1,
                'table5':       table5,
                'per_instance': per_inst,
            }

    return results_by_model


# ─── Per-prompt evaluation ────────────────────────────────────────────────────

def evaluate_prompt(letter: str, cia_data: dict) -> None:
    outputs_path = OUTPUTS_DIR / f'outputs_{letter}.jsonl'
    results_path = RESULTS_DIR / f'results_{letter}.jsonl'

    if not outputs_path.exists():
        print(f'[!] {outputs_path} does not exist — skipping prompt {letter}.')
        return

    print(f'\n[*] Evaluating prompt {letter} ...')

    output_entries = [
        json.loads(line)
        for line in outputs_path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]

    if not output_entries:
        print(f'  [!] outputs_{letter}.jsonl is empty.')
        return

    instance_results = []
    for entry in output_entries:
        instance_id = entry.get('instance_id', '')
        inst_data   = cia_data.get(instance_id)
        if inst_data is None:
            print(f'  [!] {instance_id}: not found in cia-dataset.json — skipping.')
            continue

        result = evaluate_instance(inst_data, entry)
        instance_results.append(result)

        gt_src = 'repo' if result['n_gt_methods'] > 0 else 'diff'
        status = 'FAIL' if result['parse_failed'] else 'OK  '
        print(
            f'  [{status}] {instance_id}  '
            f'P={result["precision"]:.3f}  R={result["recall"]:.3f}  '
            f'F1={result["f1"]:.3f}  '
            f'gt={result["n_gt_methods"]}  pred={result["n_pred_methods"]}'
        )

    if not instance_results:
        print(f'  [!] No valid instances to aggregate.')
        return

    table1 = compute_table1(instance_results)
    table5 = compute_table5(instance_results)

    instance_ids = [r['instance_id'] for r in instance_results]
    original     = evaluate_original_pipeline(instance_ids, cia_data)

    aggregate = {
        'type':              'aggregate',
        'prompt':            letter,
        'n_instances':       len(instance_results),
        'table1':            table1,
        'table5':            table5,
        'original_pipeline': original,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(results_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(aggregate) + '\n')
        for r in instance_results:
            f.write(json.dumps(r) + '\n')

    print(f'\n  Table 1 (prompt {letter}):')
    print(f'    Mean Precision : {table1["mean_precision"]:.4f}')
    print(f'    Mean Recall    : {table1["mean_recall"]:.4f}')
    print(f'    Mean F1        : {table1["mean_f1"]:.4f}')
    print(f'    Hit@custom     : {table1["hit_at_custom"]:.4f}')
    print(f'    Hit@5          : {table1["hit_at_5"]:.4f}')
    print(f'    Hit@10         : {table1["hit_at_10"]:.4f}')
    print(f'\n  Table 5 (prompt {letter}):')
    for stratum, vals in table5.items():
        n = vals.get('n', 0)
        if n == 0:
            print(f'    {stratum}: (no instances)')
            continue
        print(f'    {stratum} (n={n}):')
        print(f'      Micro P/R/F1 : {vals["micro_precision"]:.4f} / '
              f'{vals["micro_recall"]:.4f} / {vals["micro_f1"]:.4f}')
        print(f'      Macro P/R/F1 : {vals["macro_precision"]:.4f} / '
              f'{vals["macro_recall"]:.4f} / {vals["macro_f1"]:.4f}')

    if original:
        print(f'\n  Original pipeline (same {len(instance_ids)} instances, ID-space GT):')
        for model, res in original.items():
            t1 = res['table1']
            print(f'    [{model}]  '
                  f'P={t1["mean_precision"]:.4f}  R={t1["mean_recall"]:.4f}  '
                  f'F1={t1["mean_f1"]:.4f}  '
                  f'Hit@custom={t1["hit_at_custom"]:.4f}  '
                  f'Hit@5={t1["hit_at_5"]:.4f}  '
                  f'Hit@10={t1["hit_at_10"]:.4f}')

    print(f'\n  Saved: {results_path}')


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        letters = [a.upper() for a in sys.argv[1:] if a.upper() in PROMPTS]
        if not letters:
            print('Usage: python3 evaluator.py [A] [B]')
            sys.exit(1)
    else:
        letters = PROMPTS

    with open(CIA_DATASET, encoding='utf-8') as f:
        raw = json.load(f)

    cia_data: dict[str, dict] = {}
    for repo_key, instances in raw.items():
        for inst in instances:
            cia_data[inst['id']] = {**inst, 'repo': repo_key}

    for letter in letters:
        evaluate_prompt(letter, cia_data)


if __name__ == '__main__':
    main()
