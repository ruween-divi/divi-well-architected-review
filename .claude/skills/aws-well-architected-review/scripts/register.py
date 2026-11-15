#!/usr/bin/env python3
"""Findings-register and review-report tooling for the aws-well-architected-review skill (local files only).

    python3 -I register.py check   reports/aws-well-architected/findings.md
    python3 -I register.py rebuild reports/aws-well-architected/findings.md      # regenerate summary + register table
    python3 -I register.py next-id reports/aws-well-architected/findings.md
    python3 -I register.py lint-review reports/aws-well-architected/reviews/FILE.md \
                                       [--register reports/aws-well-architected/findings.md]

The finding records under "## Finding details" (template Part A) are the source of truth. `rebuild` rewrites
only the blocks between the BEGIN/END markers and the Next ID / Last updated rows, so hand-written content
elsewhere is preserved. `check` and `lint-review` exit 1 when they find errors.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import re  # noqa: E402

SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
STATUSES = ["Open", "In Progress", "Resolved", "Accepted Risk", "False Positive", "Superseded"]
PILLARS = {"Operational Excellence", "Security", "Reliability", "Performance Efficiency", "Cost Optimization"}
TYPES = {"Confirmed issue", "Potential concern"}
REQUIRED = ["ID", "Severity", "Type", "Confidence", "Severity rationale", "Pillar", "Category", "Account", "Region",
            "Workload", "AWS service", "Resource(s)", "Status", "First seen", "Last seen", "Fingerprint",
            "Re-check (read-only)"]
SECTIONS = ["**Description**", "**Evidence**", "**Business impact**", "**Technical impact**",
            "**Recommended remediation**", "**History**"]
REVIEW_HEADINGS = ["Executive Summary", "Architecture Overview", "Five-Pillar Assessment", "Architecture Anti-Patterns",
                   "Service Selection and Configuration Review", "Reliability and Performance Assessment",
                   "Cost Optimization Assessment", "Consolidated Findings Register", "Prioritized Remediation Roadmap",
                   "Assessment Limitations", "Sources and References", "Overall Conclusion"]
SECRET_PATTERNS = [
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "AWS access key ID"),
    (re.compile(r"aws_secret_access_key|aws_session_token|x-amz-security-token", re.I), "credential keyword"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    # A value after a secret-ish word that looks like key material (contains both a digit and a letter);
    # plain names such as TENANT_DB_ADMIN_PASSWORD or divi-stg-openai-api-key do not match.
    (re.compile(r"(?i)(secret|password|passwd|token|api[_-]?key)\W{1,5}(?=[A-Za-z0-9/+=_\-]*\d)(?=[A-Za-z0-9/+=_\-]*[A-Za-z])"
                r"[A-Za-z0-9/+=_\-]{24,}"), "secret-like value"),
]
PLACEHOLDERS = [
    (re.compile(r"<(?!redacted>|session>|access-key-id>|br>|br/>|details>|/details>|summary>|/summary>)[A-Za-z][^<>\n]{1,100}>"),
     "template placeholder <...>"),
    (re.compile(r"\bYYYY-MM-DD\b"), "date placeholder"),
    (re.compile(r"AWS-WA-NNN|AWS-WA-0NN"), "ID placeholder"),
    (re.compile(r"In progress \\\| Final|Strong \\\| Adequate|CRITICAL \\\| HIGH|Confirmed issue \\\| Potential|"
                r"High \\\| Medium \\\| Low|Open \\\| In Progress"), "unselected template option list"),
    (re.compile(r"<!--"), "template instruction comment"),
]
ROW = re.compile(r"^\|\s*\*\*(.+?)\*\*\s*\|(.*)\|\s*$")


def split_row(s):
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def parse(text):
    """Return (records, problems). Records come from '### AWS-WA-NNN — title' blocks under '## Finding details'."""
    problems, records = [], []
    start = text.find("## Finding details")
    if start < 0:
        return [], ["missing '## Finding details' section"]
    body = text[start:]
    blocks = re.split(r"^(?=### AWS-WA-\d{3,}\b)", body, flags=re.M)[1:]
    for b in blocks:
        head = b.splitlines()[0]
        m = re.match(r"### (AWS-WA-\d{3,})\s*[—-]+\s*(.+)$", head)
        if not m:
            problems.append(f"malformed heading: {head!r}")
            continue
        fid, title = m.groups()
        fields = {}
        for line in b.splitlines():
            r = ROW.match(line)
            if r and r.group(1) not in fields:
                fields[r.group(1).strip()] = split_row(r.group(2))[0]
        hist = re.search(r"\*\*History\*\*\s*\n\s*\|.*\|\s*\n\s*\|[-| ]+\|\s*\n((?:\s*\|.*\|\s*\n?)+)", b)
        records.append({"id": fid, "title": title.strip(), "fields": fields, "block": b,
                        "history_rows": len(hist.group(1).strip().splitlines()) if hist else 0})
    return records, problems


def num(fid):
    return int(fid.split("-")[-1])


def validate(text):
    recs, problems = parse(text)
    seen, fps = {}, {}
    for r in recs:
        f, fid = r["fields"], r["id"]
        if fid in seen:
            problems.append(f"{fid}: duplicate ID")
        seen[fid] = r
        for k in REQUIRED:
            if not f.get(k):
                problems.append(f"{fid}: missing field '{k}'")
        if f.get("ID") and f["ID"] != fid:
            problems.append(f"{fid}: ID field says {f['ID']}")
        if f.get("Severity") and f["Severity"] not in SEVERITIES:
            problems.append(f"{fid}: invalid severity {f['Severity']!r}")
        if f.get("Status") and f["Status"] not in STATUSES:
            problems.append(f"{fid}: invalid status {f['Status']!r}")
        if f.get("Pillar") and f["Pillar"] not in PILLARS:
            problems.append(f"{fid}: invalid pillar {f['Pillar']!r}")
        if f.get("Type") and f["Type"] not in TYPES:
            problems.append(f"{fid}: invalid type {f['Type']!r}")
        if f.get("Confidence") and not re.match(r"^(High|Medium|Low)\b", f["Confidence"]):
            problems.append(f"{fid}: confidence must start with High/Medium/Low")
        dates = [re.match(r"^(\d{4}-\d{2}-\d{2})", f.get(k, "")) for k in ("First seen", "Last seen")]
        if not all(dates):
            problems.append(f"{fid}: First/Last seen must start with YYYY-MM-DD")
        elif dates[1].group(1) < dates[0].group(1):
            problems.append(f"{fid}: Last seen precedes First seen")
        if f.get("Status") == "Superseded" and not re.search(r"AWS-WA-\d{3,}", f.get("Related", "")):
            problems.append(f"{fid}: Superseded findings must name the surviving ID in 'Related'")
        if f.get("Status") == "Accepted Risk" and "Accepted" not in r["block"].split("**History**")[-1]:
            problems.append(f"{fid}: Accepted Risk needs a history row recording who accepted it and when")
        fp = (f.get("Fingerprint") or "").strip("` ")
        if fp and f.get("Status") not in ("Superseded", "False Positive"):
            if fp in fps:
                problems.append(f"{fid}: same fingerprint as {fps[fp]} (duplicate finding?)")
            fps[fp] = fid
        for s in SECTIONS:
            if s not in r["block"]:
                problems.append(f"{fid}: missing section {s}")
        if r["history_rows"] < 1:
            problems.append(f"{fid}: history table has no rows")
        for rx, what in PLACEHOLDERS[:4]:
            if rx.search(r["block"]):
                problems.append(f"{fid}: {what} left in record")
    for rx, what in SECRET_PATTERNS:
        for m in rx.finditer(text):
            problems.append(f"possible {what} at offset {m.start()}: {m.group(0)[:12]}…")
    nm = re.search(r"\*\*Next ID\*\*\s*\|\s*`?(AWS-WA-\d{3,})`?", text)
    if not nm:
        problems.append("missing '| **Next ID** | `AWS-WA-NNN` |' row")
    elif recs and num(nm.group(1)) <= max(num(r["id"]) for r in recs):
        problems.append(f"Next ID {nm.group(1)} is not greater than the highest existing ID")
    return recs, problems


def replace_block(text, name, content):
    pat = re.compile(rf"(<!-- BEGIN:{name}[^>]*-->\n).*?(\n<!-- END:{name} -->)", re.S)
    if not pat.search(text):
        raise SystemExit(f"marker <!-- BEGIN:{name} --> ... <!-- END:{name} --> not found")
    return pat.sub(lambda m: m.group(1) + content + m.group(2), text)


def rebuild(path):
    text = open(path).read()
    recs, problems = parse(text)
    if problems:
        raise SystemExit("cannot rebuild: " + "; ".join(problems))
    cols = ["Open", "In Progress", "Resolved", "Accepted Risk", "False Positive / Superseded"]
    counts = {s: dict.fromkeys(cols, 0) for s in SEVERITIES}
    for r in recs:
        sev, st = r["fields"].get("Severity"), r["fields"].get("Status")
        if sev in counts:
            col = "False Positive / Superseded" if st in ("False Positive", "Superseded") else st
            if col in counts[sev]:
                counts[sev][col] += 1
    summary = ["| Severity | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    summary += [f"| {s} | " + " | ".join(str(counts[s][c]) for c in cols) + " |" for s in SEVERITIES]
    order = {s: i for i, s in enumerate(SEVERITIES)}
    reg = ["| ID | Severity | Pillar | Account | Region | Service | Finding | Status | First seen | Last seen |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(recs, key=lambda r: (order.get(r["fields"].get("Severity"), 9), num(r["id"]))):
        f = r["fields"]
        cells = [f"[{r['id']}](#{r['id'].lower()})", f.get("Severity"), f.get("Pillar"),
                 (f.get("Account") or "").split(" · ")[0], f.get("Region"), f.get("AWS service"), r["title"],
                 f.get("Status"), (f.get("First seen") or "")[:10], (f.get("Last seen") or "")[:10]]
        reg.append("| " + " | ".join(str(c or "").replace("|", "\\|") for c in cells) + " |")
    text = replace_block(text, "SUMMARY", "\n".join(summary))
    text = replace_block(text, "REGISTER", "\n".join(reg))
    nxt = f"AWS-WA-{(max([num(r['id']) for r in recs] or [0]) + 1):03d}"
    cur = re.search(r"(\|\s*\*\*Next ID\*\*\s*\|\s*)`?(AWS-WA-\d{3,})`?(\s*\|)", text)
    if cur and num(cur.group(2)) < num(nxt):
        text = text[:cur.start()] + f"{cur.group(1)}`{nxt}`{cur.group(3)}" + text[cur.end():]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    text = re.sub(r"(\|\s*\*\*Last updated \(UTC\)\*\*\s*\|).*?\|", rf"\1 {now} |", text, count=1)
    with open(path, "w") as fh:
        fh.write(text)
    final = cur.group(2) if cur and num(cur.group(2)) >= num(nxt) else nxt
    print(f"[register] rebuilt {len(recs)} findings; next ID {final}")


def lint_review(path, register=None):
    text = open(path).read()
    errors, warnings = [], []
    pos = -1
    for i, h in enumerate(REVIEW_HEADINGS, 1):
        m = re.search(rf"^## {i}\.\s+{re.escape(h)}", text, re.M)
        if not m:
            errors.append(f"missing section '## {i}. {h}'")
        elif m.start() < pos:
            errors.append(f"section {i} out of order")
        else:
            pos = m.start()
    if not re.search(r"\*\*Report status\*\*\s*\|\s*Final\s*\|", text):
        errors.append("report status is not 'Final'")
    for rx, what in PLACEHOLDERS:
        for m in list(rx.finditer(text))[:5]:
            line = text.count("\n", 0, m.start()) + 1
            errors.append(f"line {line}: {what}: {m.group(0)[:50]!r}")
    for rx, what in SECRET_PATTERNS:
        for m in rx.finditer(text):
            errors.append(f"line {text.count(chr(10), 0, m.start()) + 1}: possible {what}")
    if "```mermaid" not in text:
        warnings.append("no Mermaid diagram in the Architecture Overview")
    if "Sustainability" not in text:
        warnings.append("no statement on the Sustainability pillar (out of scope or assessed?)")
    if register:
        ids = {r["id"] for r in parse(open(register).read())[0]}
        for fid in sorted(set(re.findall(r"AWS-WA-\d{3,}", text))):
            if fid not in ids:
                errors.append(f"{fid} is cited in the review but not in the register")
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    print(f"[lint-review] {len(errors)} errors, {len(warnings)} warnings · {path}")
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["check", "rebuild", "next-id", "lint-review"])
    ap.add_argument("file")
    ap.add_argument("--register", help="findings.md, for lint-review cross-checks")
    a = ap.parse_args(argv)
    if a.command == "lint-review":
        return lint_review(a.file, a.register)
    text = open(a.file).read()
    recs, problems = validate(text)
    if a.command == "next-id":
        nm = re.search(r"\*\*Next ID\*\*\s*\|\s*`?(AWS-WA-\d{3,})`?", text)
        computed = f"AWS-WA-{(max([num(r['id']) for r in recs] or [0]) + 1):03d}"
        print(nm.group(1) if nm and num(nm.group(1)) >= num(computed) else computed)
        return 0
    if a.command == "rebuild":
        rebuild(a.file)
        recs, problems = validate(open(a.file).read())
    for p in problems:
        print(f"error: {p}")
    print(f"[register] {len(recs)} findings, {len(problems)} problems · {a.file}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
