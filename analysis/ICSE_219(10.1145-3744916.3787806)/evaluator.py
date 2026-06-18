import argparse
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
DATASET_NAMES = ["bp", "fsd", "lmc", "pure", "rac", "us"]
DEFAULT_THRESHOLD = 0.85
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

@dataclass
class Token:
    kind: str
    text: str = ""
    branch: str = ""

@dataclass
class Node:
    node_id: str
    kind: str
    label: str

@dataclass
class Edge:
    source: str
    target: str
    relation: str

@dataclass
class Fragment:
    entries: List[str] = field(default_factory=list)
    exits: List[str] = field(default_factory=list)

@dataclass
class ParsedModel:
    nodes: Dict[str, Node]
    edges: List[Edge]
    activities: List[str]
    relations: List[str]
    structural_valid: bool
    structural_errors: List[str]


def normalize_space(text: str) -> str:
    text = text.replace("\\n", " ").replace("\n", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t;:")


def extract_plantuml_from_raw(raw: str) -> str:
    raw = (raw or "").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and isinstance(obj.get("plantuml"), str):
            return obj["plantuml"]
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(1))
            if isinstance(obj, dict) and isinstance(obj.get("plantuml"), str):
                return obj["plantuml"]
        except json.JSONDecodeError:
            pass
    match = re.search(r"```(?:plantuml)?\s*(.*?)\s*```", raw, re.DOTALL)
    return match.group(1).strip() if match else raw


def get_plantuml(record: Dict[str, Any], field: str) -> str:
    obj = record.get(field, {})
    if isinstance(obj, dict) and isinstance(obj.get("plantuml"), str):
        return obj["plantuml"]
    if field == "prediction":
        return extract_plantuml_from_raw(record.get("raw_output", ""))
    return ""


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def tokenize_plantuml(code: str) -> List[Token]:
    tokens: List[Token] = []
    in_note = False
    activity_lines: List[str] = []
    for raw in code.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw.strip()
        lower = line.lower()
        if not line:
            continue
        if in_note:
            if lower.startswith("end note"):
                in_note = False
            continue
        if lower.startswith("note "):
            in_note = True
            continue
        if lower.startswith(("@startuml", "@enduml", "skinparam ", "title ", "caption ", "'")):
            continue
        if activity_lines:
            activity_lines.append(line)
            if ";" in line:
                text = " ".join(activity_lines)
                text = text[text.find(":") + 1:text.rfind(";")]
                tokens.append(Token("ACTION", normalize_space(text)))
                activity_lines = []
            continue
        if line.startswith(":"):
            if ";" in line:
                tokens.append(Token("ACTION", normalize_space(line[1:line.rfind(";")])))
            else:
                activity_lines = [line]
            continue
        if re.fullmatch(r"start", lower):
            tokens.append(Token("START", "start")); continue
        if re.fullmatch(r"stop|end|kill|detach", lower):
            tokens.append(Token("STOP", "stop")); continue
        m = re.match(r"^if\s*\((.*?)\)\s*then(?:\s*\((.*?)\))?", line, re.I)
        if m:
            tokens.append(Token("IF", normalize_space(m.group(1)), normalize_space(m.group(2) or "yes"))); continue
        m = re.match(r"^(?:else\s+if|elseif)\s*\((.*?)\)\s*then(?:\s*\((.*?)\))?", line, re.I)
        if m:
            tokens.append(Token("ELSEIF", normalize_space(m.group(1)), normalize_space(m.group(2) or "yes"))); continue
        m = re.match(r"^else(?:\s*\((.*?)\))?", line, re.I)
        if m:
            tokens.append(Token("ELSE", "", normalize_space(m.group(1) or "no"))); continue
        if re.fullmatch(r"endif|end\s+if", lower):
            tokens.append(Token("ENDIF")); continue
        m = re.match(r"^switch\s*\((.*?)\)", line, re.I)
        if m:
            tokens.append(Token("SWITCH", normalize_space(m.group(1)))); continue
        m = re.match(r"^case\s*\((.*?)\)", line, re.I)
        if m:
            tokens.append(Token("CASE", normalize_space(m.group(1)))); continue
        if re.fullmatch(r"endswitch|end\s+switch", lower):
            tokens.append(Token("ENDSWITCH")); continue
        m = re.match(r"^while\s*\((.*?)\)", line, re.I)
        if m:
            tokens.append(Token("WHILE", normalize_space(m.group(1)))); continue
        if re.match(r"^endwhile\b", line, re.I):
            tokens.append(Token("ENDWHILE")); continue
        if re.fullmatch(r"repeat", lower):
            tokens.append(Token("REPEAT")); continue
        m = re.match(r"^repeat\s+while\s*\((.*?)\)(?:\s+is\s+\((.*?)\))?", line, re.I)
        if m:
            tokens.append(Token("REPEAT_WHILE", normalize_space(m.group(1)), normalize_space(m.group(2) or "yes"))); continue
        if re.fullmatch(r"fork", lower):
            tokens.append(Token("FORK")); continue
        if re.match(r"^fork\s+again\b", lower):
            tokens.append(Token("FORK_AGAIN")); continue
        if re.fullmatch(r"end\s+fork|endfork", lower):
            tokens.append(Token("END_FORK")); continue
    if activity_lines:
        tokens.append(Token("ACTION", normalize_space(" ".join(activity_lines).lstrip(":"))))
    return tokens


class CFGParser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self.counter = 0
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self.errors: List[str] = []

    def new_node(self, kind: str, label: str) -> str:
        node_id = f"n{self.counter}"
        self.counter += 1
        self.nodes[node_id] = Node(node_id, kind, label)
        return node_id

    def add_edge(self, source: str, target: str, relation: str) -> None:
        self.edges.append(Edge(source, target, relation))

    def current(self) -> Optional[str]:
        return self.tokens[self.pos].kind if self.pos < len(self.tokens) else None

    def take(self) -> Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def join_sequence(self, left: Fragment, right: Fragment) -> Fragment:
        if not left.entries:
            return right
        if not right.entries:
            return left
        for source in left.exits:
            for target in right.entries:
                self.add_edge(source, target, "sequence")
        return Fragment(left.entries, right.exits)

    def parse(self) -> ParsedModel:
        self.parse_sequence(set())
        if self.pos < len(self.tokens):
            self.errors.append(f"unconsumed token {self.current()} at {self.pos}")
        valid, errors = self.structural_check()
        activities = [n.label for n in self.nodes.values() if n.kind == "activity"]
        relations = [self.edge_text(e) for e in self.edges]
        return ParsedModel(self.nodes, self.edges, activities, relations, valid, errors)

    def parse_sequence(self, stop: Set[str]) -> Fragment:
        result = Fragment()
        while self.pos < len(self.tokens) and self.current() not in stop:
            result = self.join_sequence(result, self.parse_element())
        return result

    def parse_element(self) -> Fragment:
        kind = self.current()
        if kind == "START":
            self.take(); n = self.new_node("start", "start"); return Fragment([n], [n])
        if kind == "STOP":
            self.take(); n = self.new_node("stop", "stop"); return Fragment([n], [])
        if kind == "ACTION":
            t = self.take(); n = self.new_node("activity", t.text); return Fragment([n], [n])
        if kind == "IF":
            return self.parse_if()
        if kind == "SWITCH":
            return self.parse_switch()
        if kind == "FORK":
            return self.parse_fork()
        if kind == "WHILE":
            return self.parse_while()
        if kind == "REPEAT":
            return self.parse_repeat()
        self.errors.append(f"unexpected token {kind}")
        self.take()
        return Fragment()

    def parse_if(self) -> Fragment:
        t = self.take()
        decision = self.new_node("control", f"condition {t.text}")
        merge: Optional[str] = None

        def ensure_merge() -> str:
            nonlocal merge
            if merge is None:
                merge = self.new_node("control", f"merge condition {t.text}")
            return merge

        then_branch = self.parse_sequence({"ELSEIF", "ELSE", "ENDIF"})
        if then_branch.entries:
            for n in then_branch.entries: self.add_edge(decision, n, f"condition {t.branch}")
            for n in then_branch.exits: self.add_edge(n, ensure_merge(), "merge")
        else:
            self.add_edge(decision, ensure_merge(), f"condition {t.branch}")
        while self.current() == "ELSEIF":
            e = self.take()
            branch = self.parse_sequence({"ELSEIF", "ELSE", "ENDIF"})
            if branch.entries:
                for n in branch.entries: self.add_edge(decision, n, f"condition {e.text}")
                for n in branch.exits: self.add_edge(n, ensure_merge(), "merge")
            else:
                self.add_edge(decision, ensure_merge(), f"condition {e.text}")
        if self.current() == "ELSE":
            e = self.take()
            else_branch = self.parse_sequence({"ENDIF"})
            if else_branch.entries:
                for n in else_branch.entries: self.add_edge(decision, n, f"condition {e.branch}")
                for n in else_branch.exits: self.add_edge(n, ensure_merge(), "merge")
            else:
                self.add_edge(decision, ensure_merge(), f"condition {e.branch}")
        else:
            self.add_edge(decision, ensure_merge(), "condition no")
        if self.current() == "ENDIF":
            self.take()
        else:
            self.errors.append(f"missing endif for {t.text}")
        return Fragment([decision], [merge] if merge else [])

    def parse_switch(self) -> Fragment:
        t = self.take()
        decision = self.new_node("control", f"switch {t.text}")
        merge: Optional[str] = None
        case_count = 0

        def ensure_merge() -> str:
            nonlocal merge
            if merge is None:
                merge = self.new_node("control", f"merge switch {t.text}")
            return merge

        while self.current() == "CASE":
            case = self.take()
            case_count += 1
            branch = self.parse_sequence({"CASE", "ENDSWITCH"})
            if branch.entries:
                for n in branch.entries: self.add_edge(decision, n, f"case {case.text}")
                for n in branch.exits: self.add_edge(n, ensure_merge(), "merge")
            else:
                self.add_edge(decision, ensure_merge(), f"case {case.text}")
        if self.current() == "ENDSWITCH":
            self.take()
        else:
            self.errors.append(f"missing endswitch for {t.text}")
        if case_count == 0:
            self.errors.append(f"switch has no cases for {t.text}")
        return Fragment([decision], [merge] if merge else [])

    def parse_fork(self) -> Fragment:
        self.take()
        split = self.new_node("control", "parallel split")
        join = self.new_node("control", "parallel join")
        index = 1
        while True:
            branch = self.parse_sequence({"FORK_AGAIN", "END_FORK"})
            if not branch.entries:
                self.errors.append("empty parallel branch")
            else:
                for n in branch.entries: self.add_edge(split, n, f"parallel branch {index}")
                for n in branch.exits: self.add_edge(n, join, "parallel join")
            if self.current() == "FORK_AGAIN":
                self.take(); index += 1; continue
            if self.current() == "END_FORK":
                self.take(); break
            self.errors.append("missing end fork")
            break
        if index < 2:
            self.errors.append("fork has fewer than two branches")
        return Fragment([split], [join])

    def parse_while(self) -> Fragment:
        t = self.take()
        guard = self.new_node("control", f"loop condition {t.text}")
        out = self.new_node("control", f"loop exit {t.text}")
        body = self.parse_sequence({"ENDWHILE"})
        if not body.entries:
            self.errors.append(f"empty while body for {t.text}")
        else:
            for n in body.entries: self.add_edge(guard, n, "loop body")
            for n in body.exits: self.add_edge(n, guard, "loop repeat")
        self.add_edge(guard, out, "loop exit")
        if self.current() == "ENDWHILE": self.take()
        else: self.errors.append(f"missing endwhile for {t.text}")
        return Fragment([guard], [out])

    def parse_repeat(self) -> Fragment:
        self.take()
        body = self.parse_sequence({"REPEAT_WHILE"})
        if self.current() != "REPEAT_WHILE":
            self.errors.append("missing repeat while")
            return body
        t = self.take()
        guard = self.new_node("control", f"loop condition {t.text}")
        out = self.new_node("control", f"loop exit {t.text}")
        if body.entries:
            for n in body.exits: self.add_edge(n, guard, "loop check")
            for n in body.entries: self.add_edge(guard, n, "loop repeat")
        else:
            self.errors.append(f"empty repeat body for {t.text}")
        self.add_edge(guard, out, "loop exit")
        return Fragment(body.entries or [guard], [out])

    def edge_text(self, e: Edge) -> str:
        return f"{self.nodes[e.source].label} --{e.relation}--> {self.nodes[e.target].label}"

    def structural_check(self) -> Tuple[bool, List[str]]:
        errors = list(self.errors)
        starts = [n.node_id for n in self.nodes.values() if n.kind == "start"]
        stops = [n.node_id for n in self.nodes.values() if n.kind == "stop"]
        if len(starts) != 1: errors.append(f"expected one start node, found {len(starts)}")
        if not stops: errors.append("expected at least one stop node")
        if len(starts) == 1:
            adjacency = {n: [] for n in self.nodes}
            for e in self.edges:
                if e.source not in self.nodes or e.target not in self.nodes:
                    errors.append(f"dangling edge {e.source}->{e.target}")
                else:
                    adjacency[e.source].append(e.target)
            seen, stack = set(), [starts[0]]
            while stack:
                n = stack.pop()
                if n in seen: continue
                seen.add(n); stack.extend(adjacency[n])
            missing = [self.nodes[n].label for n in self.nodes if n not in seen and self.nodes[n].kind != "stop"]
            if missing: errors.append("unreachable nodes: " + " | ".join(missing))
            if not any(s in seen for s in stops): errors.append("no reachable stop node")
        return not errors, errors


def parse_model(code: str) -> ParsedModel:
    return CFGParser(tokenize_plantuml(code)).parse()


def semantic_match(predicted: List[str], reference: List[str], model: SentenceTransformer, threshold: float) -> Dict[str, Any]:
    predicted = list(dict.fromkeys(predicted))
    reference = list(dict.fromkeys(reference))
    if not predicted or not reference:
        return {"matches": [], "count": 0, "predicted_count": len(predicted), "reference_count": len(reference)}
    embeddings = model.encode(predicted + reference, normalize_embeddings=True, show_progress_bar=False)
    sims = np.matmul(embeddings[:len(predicted)], embeddings[len(predicted):].T)
    choices: Dict[int, List[int]] = {}
    for i in range(len(predicted)):
        choices[i] = sorted([j for j in range(len(reference)) if float(sims[i, j]) >= threshold], key=lambda j: float(sims[i, j]), reverse=True)
    assigned: Dict[int, int] = {}
    def augment(i: int, seen: Set[int]) -> bool:
        for j in choices[i]:
            if j in seen: continue
            seen.add(j)
            if j not in assigned or augment(assigned[j], seen):
                assigned[j] = i; return True
        return False
    for i in sorted(range(len(predicted)), key=lambda x: max([float(sims[x, j]) for j in choices[x]], default=-1), reverse=True):
        augment(i, set())
    matches = [{"prediction": predicted[i], "reference": reference[j], "similarity": round(float(sims[i, j]), 4)} for j, i in assigned.items()]
    return {"matches": matches, "count": len(matches), "predicted_count": len(predicted), "reference_count": len(reference)}


def pr(matched: int, predicted: int, reference: int) -> Tuple[float, float]:
    p = matched / predicted if predicted else (1.0 if reference == 0 else 0.0)
    r = matched / reference if reference else (1.0 if predicted == 0 else 0.0)
    return p, r


def f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if p + r else 0.0


def wrap_plantuml(code: str) -> str:
    out = code.strip()
    if "@startuml" not in out.lower(): out = "@startuml\n" + out
    if "@enduml" not in out.lower(): out += "\n@enduml"
    return out


def syntax_check(code: str) -> Tuple[bool, str, str]:
    wrapped = wrap_plantuml(code)
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".puml", delete=False, encoding="utf-8") as f:
            f.write(wrapped); path = f.name
        result = subprocess.run(["plantuml", "-syntax", path], capture_output=True, text=True, timeout=20, check=False)
        return result.returncode == 0, (result.stdout + "\n" + result.stderr).strip(), "plantuml"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        errors = []
        lower = wrapped.lower()
        if not re.search(r"(?m)^\s*start\s*$", lower): errors.append("missing start")
        if not re.search(r"(?m)^\s*stop\s*$", lower): errors.append("missing stop")
        for name, opening, closing in [("if", r"(?m)^\s*if\s*\(", r"(?m)^\s*(?:endif|end\s+if)\s*$"), ("switch", r"(?m)^\s*switch\s*\(", r"(?m)^\s*(?:endswitch|end\s+switch)\s*$"), ("fork", r"(?m)^\s*fork\s*$", r"(?m)^\s*end\s+fork\s*$"), ("while", r"(?m)^\s*while\s*\(", r"(?m)^\s*endwhile\b"), ("repeat", r"(?m)^\s*repeat\s*$", r"(?m)^\s*repeat\s+while\s*\(")]:
            a, b = len(re.findall(opening, lower)), len(re.findall(closing, lower))
            if a != b: errors.append(f"unbalanced {name}: {a}/{b}")
        return not errors, "; ".join(errors), "simple"
    finally:
        if 'path' in locals() and os.path.exists(path): os.unlink(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt_type", choices=["A", "B"])
    ap.add_argument("dataset", choices=DATASET_NAMES)
    ap.add_argument("--inputs", default=None)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--embedding_model", default=DEFAULT_EMBEDDING_MODEL)
    ap.add_argument("--save_matches", action="store_true")
    args = ap.parse_args()
    outputs_dir = BASE_DIR / "outputs"
    results_dir = BASE_DIR / "results"; results_dir.mkdir(exist_ok=True)
    inputs = Path(args.inputs) if args.inputs else outputs_dir / f"outputs_{args.prompt_type}_{args.dataset}.jsonl"
    records = load_jsonl(inputs)
    model = SentenceTransformer(args.embedding_model)
    evaluated = []
    node_ps, node_rs, rel_ps, rel_rs = [], [], [], []
    for record in records:
        pred_code, ref_code = get_plantuml(record, "prediction"), get_plantuml(record, "reference")
        if not pred_code or not ref_code: continue
        pred, ref = parse_model(pred_code), parse_model(ref_code)
        nm = semantic_match(pred.activities, ref.activities, model, args.threshold)
        rm = semantic_match(pred.relations, ref.relations, model, args.threshold)
        np_, nr = pr(nm["count"], nm["predicted_count"], nm["reference_count"])
        rp, rr = pr(rm["count"], rm["predicted_count"], rm["reference_count"])
        syn_ok, syn_msg, syn_engine = syntax_check(pred_code)
        valid = syn_ok and pred.structural_valid
        row = {"task_id": record.get("task_id", ""), "syntax_pass": syn_ok, "syntax_checker": syn_engine, "syntax_message": syn_msg, "structural_pass": pred.structural_valid, "structural_errors": pred.structural_errors, "pass": valid, "node_precision": round(np_,4), "node_recall": round(nr,4), "node_f1": round(f1(np_,nr),4), "relation_precision": round(rp,4), "relation_recall": round(rr,4), "relation_f1": round(f1(rp,rr),4), "predicted_nodes": nm["predicted_count"], "reference_nodes": nm["reference_count"], "matched_nodes": nm["count"], "predicted_relations": rm["predicted_count"], "reference_relations": rm["reference_count"], "matched_relations": rm["count"]}
        if args.save_matches: row.update({"node_matches": nm["matches"], "relation_matches": rm["matches"], "predicted_relation_elements": pred.relations, "reference_relation_elements": ref.relations})
        evaluated.append(row); node_ps.append(np_); node_rs.append(nr); rel_ps.append(rp); rel_rs.append(rr)
    total = len(evaluated)
    avg = lambda xs: sum(xs)/len(xs) if xs else 0.0
    np_, nr, rp, rr = avg(node_ps), avg(node_rs), avg(rel_ps), avg(rel_rs)
    aggregate = {"total": total, "similarity_threshold": args.threshold, "syntax_pass_rate": round(sum(x["syntax_pass"] for x in evaluated)/total,4) if total else 0.0, "structural_pass_rate": round(sum(x["structural_pass"] for x in evaluated)/total,4) if total else 0.0, "pass_rate": round(sum(x["pass"] for x in evaluated)/total,4) if total else 0.0, "n_precision": round(np_,4), "n_recall": round(nr,4), "n_f1": round(f1(np_,nr),4), "r_precision": round(rp,4), "r_recall": round(rr,4), "r_f1": round(f1(rp,rr),4)}
    output = results_dir / f"results_{args.prompt_type}_{args.dataset}.jsonl"
    with output.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"aggregate": aggregate}, ensure_ascii=False) + "\n")
        for row in evaluated: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(aggregate, indent=2)); print(f"Results saved to {output}")

if __name__ == "__main__":
    main()
