#!/usr/bin/env python3
"""assert_linter — a mechanical honesty gate for harvested pattern tests.

Catches GUTTED asserts (the wave 16/17/18 failure mode): a test that "passes" without
actually testing its claim. Static AST analysis, stdlib-only, zero-dependency.

Per-assert tiers:
  HOLLOW   — can never test correctness:
             assert True/<constant> · isinstance(...) · isfinite/isnan/isinf(...) ·
             bare name (assert x) · len(...)==k / len(...)>k (shape only) ·
             x in [literal, ...] (membership) · all(...)/any(...) over a hollow call.
  RECOVERY — pins a computed quantity to a PLANTED TRUTH:
             abs(X - TARGET) < tol · X == TARGET · comparison against a
             *_true/truth/target/expected/analytic/exact/planted-named variable ·
             equality/closeness to a non-trivial numeric literal.
  WEAK     — directional / sign-only / they-differ (abs(a-b)>eps): may be the real
             claim, may be gutting — a human must read it.

File verdict:
  REJECT — every assert is HOLLOW (or the file has no assert)  → hard block.
  WARN   — no RECOVERY assert, only WEAK (+maybe HOLLOW)       → needs read-pass.
  PASS   — has >=1 RECOVERY assert.

HONEST LIMIT: this catches SYNTACTIC gutting, not SEMANTIC tautology. A test that
compares a quantity to itself (e.g. a "VI" output equal to the analytic formula it
copies) PASSES the linter and is still wrong — the human read-pass remains necessary.
This tool raises the floor; it does not replace the reader.

Exit: 1 if any REJECT (with --strict, also on WARN); else 0.
CLI: assert_linter.py [--strict] [--quiet] [--selftest] FILE [FILE ...]
"""
import ast
import sys

TRUTH_WORDS = ("true", "truth", "target", "expected", "analytic", "exact", "planted", "known")
FINITE_FUNCS = ("isfinite", "isnan", "isinf")


def _call_name(node):
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
    return None


def _num_const(node):
    return (isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool))


def _is_truth_name(node):
    return isinstance(node, ast.Name) and any(w in node.id.lower() for w in TRUTH_WORDS)


def classify(test):
    """Classify one assert test node → (tier, tag). tier ∈ {hollow, recovery, weak}."""
    if isinstance(test, ast.Constant):
        return "hollow", "assert-constant"
    if isinstance(test, ast.Name):
        return "hollow", "bare-name"

    cn = _call_name(test)
    if cn == "isinstance":
        return "hollow", "isinstance"
    if cn in FINITE_FUNCS:
        return "hollow", "finiteness"
    if cn in ("all", "any") and getattr(test, "args", None):
        elt = getattr(test.args[0], "elt", None)  # genexp / listcomp element
        if elt is not None and classify(elt)[0] == "hollow":
            return "hollow", f"{cn}-hollow"

    if isinstance(test, ast.Compare):
        op = test.ops[0]
        left = test.left
        right = test.comparators[0]

        if isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, (ast.List, ast.Tuple, ast.Set)):
            return "hollow", "membership"
        if _call_name(left) == "len" and _num_const(right):
            return "hollow", "len-shape"

        # abs(A - B) < tol  → recovery when B (or A) is a literal target / truth-var.
        if _call_name(left) == "abs" and isinstance(op, (ast.Lt, ast.LtE)) and left.args:
            inner = left.args[0]
            if isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.Sub):
                if (_num_const(inner.right) or _is_truth_name(inner.right)
                        or _num_const(inner.left) or _is_truth_name(inner.left)):
                    return "recovery", "abs-recovery"
        # abs(A - B) > tol  → they-differ (weak)
        if _call_name(left) == "abs" and isinstance(op, (ast.Gt, ast.GtE)):
            return "weak", "they-differ"

        if _is_truth_name(left) or _is_truth_name(right):
            return "recovery", "vs-truth-var"
        if isinstance(op, ast.Eq) and _num_const(right) and right.value not in (0, 1):
            return "recovery", "eq-target"
        if _num_const(right) and right.value == 0:
            return "weak", "sign-only"
        return "weak", "directional"

    if isinstance(test, ast.BoolOp):
        tiers = [classify(v)[0] for v in test.values]
        if isinstance(test.op, ast.And):
            # AND: every conjunct must hold → the strongest is enforced.
            if "recovery" in tiers:
                return "recovery", "and-recovery"
            if all(t == "hollow" for t in tiers):
                return "hollow", "and-hollow"
            return "weak", "and-weak"
        # OR: the assert passes via the WEAKEST branch → an escape route.
        # `assert <recovery> or <trivial-escape>` is the banned widen-to-fake pattern.
        if "hollow" in tiers:
            return "hollow", "or-escape"
        if "weak" in tiers:
            return "weak", "or-escape"
        return "recovery", "or-recovery"

    return "weak", "unknown"


def lint_source(src):
    tree = ast.parse(src)
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    if not asserts:
        return "REJECT", [("hollow", "no-asserts")]
    detail = [classify(a.test) for a in asserts]
    tiers = [t for t, _ in detail]
    if "recovery" in tiers:
        return "PASS", detail
    if all(t == "hollow" for t in tiers):
        return "REJECT", detail
    return "WARN", detail


def lint_file(path):
    with open(path) as fh:
        return lint_source(fh.read())


def _selftest():
    cases = [
        ("assert True", "hollow"), ("assert ok", "hollow"),
        ("assert isinstance(r, float)", "hollow"),
        ("assert math.isfinite(e)", "hollow"),
        ("assert all(math.isfinite(e) for e in seq)", "hollow"),
        ("assert len(r) == 2", "hollow"), ("assert len(r) > 1", "hollow"),
        ("assert best in [1, 2, 3]", "hollow"),
        ("assert abs(x - 2.0) < 0.5", "recovery"),
        ("assert abs(mean - theta_true) < 1.0", "recovery"),
        ("assert k_est == 3", "recovery"),
        ("assert vi_mean == mu_true", "recovery"),
        ("assert abs(a - b) > 0.1", "weak"),
        ("assert abs(x - 2.0) < 0.5 or n < 100", "weak"),  # or-escape: recovery OR trivial escape
        ("assert abs(x - 2.0) < 0.5 and finite", "recovery"),   # and: strongest enforced
        ("assert mse > 0", "weak"),
        ("assert bf_h1 > 1.0", "weak"),
        ("assert ipw_result != naive", "weak"),
    ]
    ok = 0
    for src, want in cases:
        got, tag = classify(ast.parse(src).body[0].test)
        flag = "ok" if got == want else "FAIL"
        ok += (got == want)
        print(f"  [{flag}] {src!r} → {got} ({tag}); want {want}")
    print(f"selftest {ok}/{len(cases)}")
    # File-level checks.
    hollow_file = "if 1:\n assert True\n assert len(x)==2\n"
    good_file = "if 1:\n assert abs(x - 2.0) < 0.1\n assert len(x)==2\n"
    weak_file = "if 1:\n assert a > 0\n assert abs(a-b) > 1e-6\n"
    fv = [(lint_source(hollow_file)[0], "REJECT"), (lint_source(good_file)[0], "PASS"), (lint_source(weak_file)[0], "WARN")]
    for got, want in fv:
        print(f"  [{'ok' if got==want else 'FAIL'}] file → {got}; want {want}")
        ok += (got == want)
    total = len(cases) + 3
    return 0 if ok == total else 1


def main(argv):
    strict = "--strict" in argv
    quiet = "--quiet" in argv
    files = [a for a in argv if not a.startswith("--")]
    counts = {"PASS": 0, "WARN": 0, "REJECT": 0}
    worst = 0
    for f in files:
        verdict, detail = lint_file(f)
        counts[verdict] += 1
        if verdict == "REJECT" or (strict and verdict == "WARN"):
            worst = 1
        if not (quiet and verdict == "PASS"):
            tags = ", ".join(sorted({tag for _, tag in detail}))
            print(f"{verdict:6}  {f}  [{tags}]")
    print(f"--- PASS {counts['PASS']} · WARN {counts['WARN']} · REJECT {counts['REJECT']} ---")
    return worst


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
