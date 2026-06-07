"""
SecureReviewer evaluator.
Reads outputs JSONL from main.py and computes SecureBLEU, BLEU-4, and issue-detection metrics.

Usage:
  python evaluator.py [--prompt A|B|both] [--n N]

Input:  outputs/outputs_{P}.jsonl
Output: results/results_{P}.jsonl
"""

import argparse
import json
import math
import re
import sys
import xml.sax.saxutils
from pathlib import Path
from typing import Optional

# ── BLEU utilities ────────────────────────────────────────────────────────────

_preserve_case = False
_normalize1 = [
    (re.compile(r'<skipped>'), ''),
    (re.compile(r'-\n'), ''),
    (re.compile(r'\n'), ' '),
]
_normalize2 = [
    (re.compile(r'([\{-\~\[-\` -\&\(-\+\:-\@\/])'), r' \1 '),
    (re.compile(r'([^0-9])([\.,])'), r'\1 \2 '),
    (re.compile(r'([\.,])([^0-9])'), r' \1 \2'),
    (re.compile(r'([0-9])(-)'), r'\1 \2 '),
]


def _normalize(s):
    if type(s) is not str:
        s = " ".join(s)
    for pat, rep in _normalize1:
        s = re.sub(pat, rep, s)
    s = xml.sax.saxutils.unescape(s, {'&quot;': '"'})
    if not _preserve_case:
        s = s.lower()
    for pat, rep in _normalize2:
        s = re.sub(pat, rep, s)
    return s.split()


def _count_ngrams(words, n=4):
    counts = {}
    for k in range(1, n + 1):
        for i in range(len(words) - k + 1):
            ngram = tuple(words[i:i + k])
            counts[ngram] = counts.get(ngram, 0) + 1
    return counts


def _cook_refs(refs, n=4):
    refs = [_normalize(r) for r in refs]
    maxcounts = {}
    for ref in refs:
        for ngram, cnt in _count_ngrams(ref, n).items():
            maxcounts[ngram] = max(maxcounts.get(ngram, 0), cnt)
    return ([len(r) for r in refs], maxcounts)


def _cook_test(test, item, n=4):
    reflens, refmaxcounts = item
    test = _normalize(test)
    result = {"testlen": len(test), "reflen": min(reflens)}
    result["guess"] = [max(len(test) - k + 1, 0) for k in range(1, n + 1)]
    result["correct"] = [0] * n
    for ngram, cnt in _count_ngrams(test, n).items():
        result["correct"][len(ngram) - 1] += min(refmaxcounts.get(ngram, 0), cnt)
    return result


def _score_cooked(allcomps, n=4, smooth=1):
    total = {"testlen": 0, "reflen": 0, "guess": [0] * n, "correct": [0] * n}
    for c in allcomps:
        total["testlen"] += c["testlen"]
        total["reflen"] += c["reflen"]
        for k in range(n):
            total["guess"][k] += c["guess"][k]
            total["correct"][k] += c["correct"][k]
    logbleu = 0.0
    for k in range(n):
        addsmooth = 1 if smooth == 1 and k > 0 else 0
        logbleu += (math.log(total["correct"][k] + addsmooth + sys.float_info.min)
                    - math.log(total["guess"][k] + addsmooth + sys.float_info.min))
    logbleu /= float(n)
    bp = min(0, 1 - float(total["reflen"] + 1) / (total["testlen"] + 1))
    return math.exp(logbleu + bp)


def _splitpuncts(line):
    return ' '.join(re.findall(r"[\w]+|[^\s\w]", line))


def _bleu_fromstr(predictions: list, references: list) -> float:
    """Mirrors the original SecureReviewer bleu_fromstr/bleuFromMaps: tokenize with
    wordpunct_tokenize, re-split on word/punct boundaries and lowercase, then compute
    BLEU per sample and average the per-sample scores (not a corpus-level BLEU)."""
    import nltk
    preds_tok = [" ".join(nltk.wordpunct_tokenize(p)) for p in predictions]
    refs_tok  = [" ".join(nltk.wordpunct_tokenize(r)) for r in references]
    pred_map = {str(i): [_splitpuncts(p.strip().lower())] for i, p in enumerate(preds_tok)}
    gold_map = {}
    for i, r in enumerate(refs_tok):
        key = str(i)
        if key in pred_map:
            gold_map.setdefault(key, []).append(_splitpuncts(r.strip().lower()))
    if not gold_map:
        return 0.0
    total, num = 0.0, 0
    for key, refs in gold_map.items():
        cooked = _cook_refs(refs)
        total += _score_cooked([_cook_test(pred_map[key][0], cooked)])
        num += 1
    return round(total * 100.0 / num, 2)


def _bleu_single(ref_text: str, hyp_text: str) -> float:
    if not ref_text.strip() or not hyp_text.strip():
        return 0.0
    return _bleu_fromstr([hyp_text], [ref_text])

# ── Security keyword dictionary ───────────────────────────────────────────────

_SECURITY_KEYWORDS: dict = {
    "Input Validation": [
        "CSS", "XSS", "malform", "htmlspecialchars", "SQL", "SQLI", "input",
        "validation", "command", "exec", "unauthorized", "null",
        "request forgery", "CSRF", "XSRF", "forged", "cookie", "xhttp",
        "sanitize", "escape", "filter", "whitelist", "blacklist", "regex",
        "pattern", "injection",
    ],
    "Exception Handling": [
        "try", "catch", "finally", "throw", "panic", "assert", "crash",
        "exception", "error", "handle", "handing", "null", "logging",
        "stack trace", "recover",
    ],
    "State Management": [
        "denial service", "dos", "ddos", "state", "behavior", "error",
        "fallback", "recover", "resilience", "consistency", "failure",
        "incorrect", "inconsistent", "expose",
    ],
    "Type and Data Handling": [
        "integer", "overflow", "signedness", "widthness", "underflow",
        "type", "convert", "string", "value", "casting", "serialization",
        "deserialization", "parsing", "byte", "precision",
    ],
    "Resource Management": [
        "memory", "resource", "file descriptor", "leak", "double free",
        "use after free", "allocation", "deallocation", "cleanup", "release",
        "buffer", "overflow", "stack", "strcpy", "strcat", "strtok", "gets",
        "makepath", "splitpath", "heap", "strlen", "out of memory", "dynamic",
        "finalize", "dispose",
    ],
    "Concurrency": [
        "race", "racy", "deadlock", "concurrent", "multiple", "threads",
        "lock", "condition", "synchronization", "inconsistent", "mutex",
        "atomic", "semaphore", "critical section", "thread safety", "parallel",
        "volatile",
    ],
    "Access Control and Information Security": [
        "improper", "unauthenticated", "access", "permission", "sensitive",
        "information", "protected", "hijack", "authenticate", "privilege",
        "forensic", "hacker", "root", "URL", "form", "field", "leak",
        "unauthorized", "encrypt", "decrypt", "password", "cipher", "trust",
        "checksum", "nonce", "salt", "crypto", "mismatch", "expose",
        "authorization", "authentication", "role-based", "RBAC", "credential",
        "session", "token", "patch", "SSL", "TLS", "certificate",
    ],
    "Common Keywords": [
        "security", "vulnerability", "vulnerable", "hole", "exploit",
        "malicious", "attack", "bypass", "backdoor", "threat", "expose",
        "breach", "violate", "fatal", "blacklist", "overrun", "insecure",
        "lead", "scare", "scary", "conflict", "trojan", "firewall", "spyware",
        "empty", "adware", "virus", "ransom", "malware", "dangling", "unsafe",
        "worm", "phishing", "cve", "cwe", "injection", "collusion", "covert",
        "mitm", "sniffer", "quarantine", "risk", "error", "spam", "spoof",
        "tamper", "zombie", "cast", "xml", "concern", "sensitive", "exposure",
        "undefined",
    ],
}

_NON_ISSUE = "Non-Issue"


def _normalize_label(label: str) -> str:
    if label.lower().replace("-", " ").replace("_", " ").strip() in ("no issue", "non issue"):
        return _NON_ISSUE
    return label


def _ensure_nltk():
    import nltk
    for pkg in ("wordnet", "averaged_perceptron_tagger", "averaged_perceptron_tagger_eng", "omw-1.4"):
        try:
            nltk.data.find(f"corpora/{pkg}" if pkg != "averaged_perceptron_tagger" else f"taggers/{pkg}")
        except LookupError:
            nltk.download(pkg, quiet=True)


def _extract_code_words(text: str) -> list:
    return ["`" + m + "`" for m in re.findall(r'`([^`]+)`', text)]


def _get_synonyms(word: str) -> list:
    from nltk.corpus import wordnet
    syns = set()
    for syn in wordnet.synsets(word):
        for lemma in syn.lemmas():
            syns.add(lemma.name())
    return list(syns)


def _get_wordnet_pos(tag: str):
    from nltk.corpus import wordnet as wn
    if tag.startswith('J'):
        return wn.ADJ
    if tag.startswith('V'):
        return wn.VERB
    if tag.startswith('R'):
        return wn.ADV
    return wn.NOUN


def _find_matches(text: str, keywords: list) -> tuple:
    from nltk.stem import WordNetLemmatizer
    from nltk import pos_tag
    lemmatizer = WordNetLemmatizer()
    text = text.replace(',', '').replace('.', '')
    text_words = text.split()
    kw_lower = [k.lower() for k in keywords]
    matches = []
    for word in text_words:
        tag = pos_tag([word])[0][1]
        lemma = lemmatizer.lemmatize(word, pos=_get_wordnet_pos(tag)).lower()
        if lemma in kw_lower and lemma not in matches:
            matches.append(lemma)
    code_words = _extract_code_words(text)
    return matches, code_words


def _find_overlapping_matches(text: str, ref_keywords: list, ref_code: list) -> tuple:
    matches = []
    for kw in ref_keywords:
        all_forms = [kw] + _get_synonyms(kw)
        for form in all_forms:
            if re.search(r'\b' + re.escape(form) + r'\b', text, re.IGNORECASE):
                matches.append(kw)
                break
    code_matches = []
    for cw in ref_code:
        clean = cw.replace('`', '')
        for tw in _extract_code_words(text):
            if clean in tw or tw in clean:
                code_matches.append(cw)
                break
    return matches, code_matches


_FIELD_WEIGHTS = {"security_type": 0.3, "description": 0.3, "impact": 0.2, "advice": 0.2}


def _calc_weighted_bleu(pred: dict, ref: dict) -> float:
    scores = {}
    scores["security_type"] = (
        100.0 if pred["security_type"].strip().lower() == ref["security_type"].strip().lower() else 0.0
    )
    for key in ("description", "impact", "advice"):
        scores[key] = _bleu_single(ref[key].strip(), pred[key].strip())
    return sum(scores[k] * _FIELD_WEIGHTS[k] for k in _FIELD_WEIGHTS)


def _calc_keyword_overlap(pred: dict, ref: dict, ref_st: str) -> float:
    pred_st = pred["security_type"]
    if pred_st == ref_st:
        keywords = _SECURITY_KEYWORDS.get(ref_st, []) + _SECURITY_KEYWORDS["Common Keywords"]
    else:
        keywords = _SECURITY_KEYWORDS["Common Keywords"]

    def field_ratio(ref_text, pred_text):
        ref_kws, ref_code = _find_matches(ref_text, keywords)
        ref_kws, ref_code = list(set(ref_kws)), list(set(ref_code))
        pred_kws, pred_code = _find_overlapping_matches(pred_text, ref_kws, ref_code)
        pred_kws, pred_code = list(set(pred_kws)), list(set(pred_code))
        r  = len(pred_kws)  / len(ref_kws)  if ref_kws  else 0.0
        rc = len(pred_code) / len(ref_code) if ref_code else 0.0
        return r, rc

    rd, rdk = field_ratio(ref["description"], pred["description"])
    ri, rik = field_ratio(ref["impact"],      pred["impact"])
    ra, rak = field_ratio(ref["advice"],      pred["advice"])
    return 0.2 * (rd + rdk) + 0.15 * (ri + rik) + 0.15 * (ra + rak)


def _securebleu_sample(record: dict) -> float:
    pred_st = _normalize_label(record["predicted"].get("Security Type", _NON_ISSUE))
    if pred_st == _NON_ISSUE:
        return 0.0
    ref = record["reference"]
    ref_st = ref.get("security_type", "")
    pred_d = {"security_type": pred_st,
              "description": record["predicted"].get("Description", ""),
              "impact":      record["predicted"].get("Impact", ""),
              "advice":      record["predicted"].get("Advice", "")}
    ref_d  = {"security_type": ref_st,
              "description": ref.get("description", ""),
              "impact":      ref.get("impact", ""),
              "advice":      ref.get("advice", "")}
    score_bleu    = _calc_weighted_bleu(pred_d, ref_d)
    keyword_ratio = _calc_keyword_overlap(pred_d, ref_d, ref_st)
    return score_bleu * 0.5 + keyword_ratio * 50.0


def compute_bleu4(records: list) -> float:
    preds, refs = [], []
    for r in records:
        if _normalize_label(r["reference"].get("security_type", "")) == _NON_ISSUE:
            continue
        pred_text = " ".join([r["predicted"].get("Description", ""),
                               r["predicted"].get("Impact", ""),
                               r["predicted"].get("Advice", "")]).strip()
        ref_text  = " ".join([r["reference"].get("description", ""),
                               r["reference"].get("impact", ""),
                               r["reference"].get("advice", "")]).strip()
        preds.append(pred_text)
        refs.append(ref_text)
    if not preds:
        return 0.0
    return _bleu_fromstr(preds, refs)


def compute_securebleu(records: list) -> float:
    _ensure_nltk()
    scores = []
    for r in records:
        if _normalize_label(r["reference"].get("security_type", "")) == _NON_ISSUE:
            continue
        scores.append(_securebleu_sample(r))
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 2)


def compute_issue_detection(records: list) -> dict:
    try:
        from sklearn.metrics import precision_recall_fscore_support, accuracy_score
    except ImportError:
        print("  WARNING: scikit-learn not available; skipping issue-detection metrics.")
        return {}
    y_true = [_normalize_label(r["reference"].get("security_type", "")) for r in records]
    y_pred = [_normalize_label(r["predicted"].get("Security Type", _NON_ISSUE)) for r in records]
    acc = accuracy_score(y_true, y_pred)
    p, rec, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", zero_division=0)
    return {
        "accuracy":        round(float(acc) * 100, 2),
        "precision_macro": round(float(p)   * 100, 2),
        "recall_macro":    round(float(rec) * 100, 2),
        "f1_macro":        round(float(f1)  * 100, 2),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def evaluate_prompt(prompt_label: str, n: int):
    outputs_path = Path(__file__).parent / "outputs" / f"outputs_{prompt_label}.jsonl"
    if not outputs_path.exists():
        print(f"ERROR: outputs file not found: {outputs_path}")
        print("Run main.py first.")
        return

    records = []
    with open(outputs_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    print(f"Computing metrics for {len(records)} records (prompt {prompt_label})...")
    print("  Computing issue-detection metrics...")
    issue = compute_issue_detection(records)
    print("  Computing BLEU-4...")
    b4 = compute_bleu4(records)
    print("  Computing SecureBLEU (keyword matching may be slow)...")
    sb = compute_securebleu(records)

    non_issue_refs = sum(
        1 for r in records
        if _normalize_label(r["reference"].get("security_type", "")) == _NON_ISSUE
    )
    gen_n = len(records) - non_issue_refs

    print(f"\n{'='*50}")
    print(f"SUMMARY — Prompt {prompt_label} — {len(records)} examples")
    print(f"\n  Issue Detection (all {len(records)} samples):")
    if issue:
        print(f"    Accuracy  : {issue.get('accuracy', 'N/A'):.2f}")
        print(f"    Precision : {issue.get('precision_macro', 'N/A'):.2f}")
        print(f"    Recall    : {issue.get('recall_macro', 'N/A'):.2f}")
        print(f"    F1        : {issue.get('f1_macro', 'N/A'):.2f}")
    print(f"\n  Comment Generation ({gen_n} samples, Non-Issue refs excluded):")
    print(f"    BLEU-4      : {b4:.2f}")
    print(f"    SecureBLEU  : {sb:.2f}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"results_{prompt_label}.jsonl"
    aggregate = {**issue, "bleu4": b4, "securebleu": sb, "total": len(records), "total_llm_time": round(sum(r.get("llm_response_time", 0.0) for r in records), 3)}
    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": aggregate}) + "\n")
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nResults saved to: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=["A", "B", "both"], default="both")
    parser.add_argument("--n",      type=int, default=5)
    args = parser.parse_args()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]
    for pl in prompt_labels:
        evaluate_prompt(pl, args.n)


if __name__ == "__main__":
    main()
