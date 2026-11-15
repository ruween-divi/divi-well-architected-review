#!/usr/bin/env python3
"""Deterministic signal digest for evidence collected by collect.py (aws-well-architected-review skill).

    python3 -I digest.py EVIDENCE_DIR [--top 15]

Reads only local files; makes no AWS calls. Writes EVIDENCE_DIR/digest.md (compact, for the reviewer to read)
and EVIDENCE_DIR/digest.json (machine-readable), and prints a one-line summary.

Signals are FACTS extracted mechanically from read-only API output (counts, flags, cross-references such as
"public IP + world-open SSH" or "SQS visibility timeout shorter than 6x the consuming Lambda timeout").
They are NOT findings: every signal must be interpreted against workload context, criticality and intent,
and many will be legitimate. Signal IDs are stable so findings can cite them ("Detected by: SIG CMP-01").
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import base64  # noqa: E402
import csv  # noqa: E402
import datetime as dt  # noqa: E402
import glob  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import statistics  # noqa: E402
import urllib.parse  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)
SENSITIVE_PORTS = {20, 21, 22, 23, 25, 135, 137, 139, 445, 1433, 1521, 2049, 2375, 2376, 3306, 3389, 5432, 5439, 5601,
                   5900, 5984, 6379, 7001, 8020, 8080, 8443, 8888, 9000, 9042, 9092, 9200, 9300, 11211, 15672, 27017}
LAMBDA_DEPRECATED = {"python2.7", "python3.6", "python3.7", "python3.8", "nodejs", "nodejs4.3", "nodejs4.3-edge",
                     "nodejs6.10", "nodejs8.10", "nodejs10.x", "nodejs12.x", "nodejs14.x", "nodejs16.x", "ruby2.5",
                     "ruby2.7", "java8", "go1.x", "dotnetcore1.0", "dotnetcore2.0", "dotnetcore2.1", "dotnetcore3.1",
                     "dotnet6", "provided"}
LAMBDA_VERIFY = {"python3.9", "python3.10", "nodejs18.x", "ruby3.2", "dotnet8", "java8.al2", "java11", "provided.al2"}
SECRETISH_NAME = re.compile(r"PASS(WORD|WD)?|SECRET|TOKEN|API_?KEY|PRIVATE|CREDENTIAL|AUTH", re.I)
IAC_TAG = re.compile(r"^(aws:cloudformation:|aws:cdk|terraform|tf[_:-]|managed[-_]?by$|pulumi|crossplane|iac$)", re.I)
HIGH_IMPACT = {"SEC-01", "SEC-02", "S3-01", "IAM-01", "IAM-02", "IAM-04", "IAM-05", "NET-02", "DB-01", "DET-01",
               "DB-03", "BKP-01", "NET-07", "CMP-02", "INT-02", "EKS-02", "FN-03"}


def jload(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name))[:120]


def ptime(s):
    if not s or not isinstance(s, str) or s in ("N/A", "no_information", "not_supported"):
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
        if not m:
            return None
        t = dt.datetime.fromisoformat(m.group(1))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def utc_day(s, default=""):
    """UTC calendar date of a timestamp string (honours +hh:mm offsets; evidence from older collectors may be local time)."""
    t = ptime(s)
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d") if t else (default or (s or "")[:10])


def days_ago(s):
    t = ptime(s)
    return (NOW - t).days if t else None


def tags(lst):
    return {t.get("Key"): t.get("Value") for t in (lst or []) if isinstance(t, dict)}


def tag_like(tg, names):
    for k, v in tg.items():
        if k and k.lower() in names:
            return v
    return None


def env_of(tg):
    return tag_like(tg, {"environment", "env", "stage", "tier"})


def label(rid, tg):
    n = tg.get("Name")
    e = env_of(tg)
    return rid + (f" ({n})" if n else "") + (f" [env={e}]" if e else "")


def gib(n):
    return f"{n:,.0f} GiB"


def human_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1000:
            return f"{n:,.1f} {unit}"
        n /= 1000
    return f"{n:,.1f} EB"


def statements(doc):
    if isinstance(doc, str):
        try:
            doc = json.loads(urllib.parse.unquote(doc))
        except ValueError:
            return []
    st = (doc or {}).get("Statement", [])
    return st if isinstance(st, list) else [st]


def as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


class Evidence:
    def __init__(self, root):
        self.root = root
        self.manifest = jload(os.path.join(root, "manifest.json")) or {}
        self.ledger = jload(os.path.join(root, "ledger.json")) or []
        self.regions = self.manifest.get("regions") or sorted(
            d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and d != "global")
        self.account = self.manifest.get("account")

    def path(self, folder, svc, op, key=None):
        return os.path.join(self.root, folder, f"{svc}.{op}" + (f".{safe(key)}" if key else "") + ".json")

    def raw(self, folder, svc, op, key=None):
        return jload(self.path(folder, svc, op, key))

    def get(self, folder, svc, op, key=None):
        d = self.raw(folder, svc, op, key)
        if isinstance(d, dict) and ("_absent" in d or "_error" in d):
            return None
        return d

    def state(self, folder, svc, op, key=None):
        d = self.raw(folder, svc, op, key)
        if d is None and not os.path.exists(self.path(folder, svc, op, key)):
            return "missing"
        if isinstance(d, dict) and "_absent" in d:
            return "absent"
        if isinstance(d, dict) and "_error" in d:
            return d["_error"].get("status", "error")
        return "ok"

    def many(self, folder, svc, op):
        out = []
        for p in sorted(glob.glob(os.path.join(self.root, folder, f"{svc}.{op}.*.json"))):
            d = jload(p)
            if d is not None and not (isinstance(d, dict) and ("_absent" in d or "_error" in d)):
                out.append((os.path.basename(p)[len(svc) + len(op) + 2:-5], d))
        return out

    def lst(self, folder, svc, op):
        d = self.get(folder, svc, op)
        return d if isinstance(d, list) else []


class Digest:
    def __init__(self, ev, top):
        self.ev, self.top = ev, top
        self.signals, self.errors, self.tables = [], [], []
        self.ctx = {}

    def add(self, sid, pillar, title, items, check=None, see=None, count=None, total=None):
        n = count if count is not None else len(items)
        if not n:
            return
        self.signals.append({"id": sid, "pillar": pillar, "title": title, "count": n, "total": total,
                             "items": items, "check": check, "see": see})

    def table(self, title, header, rows):
        if rows:
            self.tables.append({"title": title, "header": header, "rows": rows})

    def run(self, fn):
        try:
            fn()
        except Exception as exc:  # keep going: one malformed file must not lose the rest of the digest
            self.errors.append(f"{fn.__name__}: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ coverage & inventory
    def coverage(self):
        per, denied = {}, {}
        for e in self.ev.ledger:
            row = per.setdefault(e["region"], {})
            row[e["status"]] = row.get(e["status"], 0) + 1
            if e["status"] in ("denied", "error", "auth"):
                k = (e["service"], e["op"], e.get("code") or e["status"])
                denied.setdefault(k, set()).add(e["region"])
        self.table("Collection coverage (calls by status)", ["Region", "ok", "absent", "denied", "error"],
                   [[r, v.get("ok", 0), v.get("absent", 0), v.get("denied", 0), v.get("error", 0) + v.get("auth", 0)]
                    for r, v in sorted(per.items())])
        self.table("Denied or failed APIs (→ access ledger; not misconfigurations)", ["API", "Result", "Regions"],
                   [[f"{s} {o}", c, ", ".join(sorted(rs))] for (s, o, c), rs in sorted(denied.items())])
        caps = self.ev.manifest.get("caps") or []
        self.table("Collection caps hit (coverage is partial for these)", ["Region", "What", "Total", "Collected"],
                   [[c["region"], c["what"], c["total"], c["collected"]] for c in caps])

    def inventory(self):
        ev = self.ev
        rows = []
        for r in ev.regions:
            inst = ev.lst(r, "ec2", "describe-instances")
            lbs = ev.lst(r, "elbv2", "describe-load-balancers")
            rows.append([r, sum(i.get("State") == "running" for i in inst), sum(i.get("State") == "stopped" for i in inst),
                         len(ev.lst(r, "autoscaling", "describe-auto-scaling-groups")),
                         len((ev.get(r, "ecs", "list-clusters") or {}).get("clusterArns") or []),
                         len((ev.get(r, "eks", "list-clusters") or {}).get("clusters") or []),
                         len(ev.lst(r, "lambda", "list-functions")),
                         len(ev.lst(r, "rds", "describe-db-instances")),
                         len((ev.get(r, "dynamodb", "list-tables") or {}).get("TableNames") or []),
                         len(ev.lst(r, "elasticache", "describe-cache-clusters")),
                         sum(lb.get("Type") == "application" for lb in lbs), sum(lb.get("Type") == "network" for lb in lbs),
                         len(ev.lst(r, "elb", "describe-load-balancers")),
                         len([n for n in ev.lst(r, "ec2", "describe-nat-gateways") if n.get("State") == "available"]),
                         len(ev.lst(r, "ec2", "describe-vpcs")),
                         len((ev.get(r, "sqs", "list-queues") or {}).get("QueueUrls") or []),
                         len(ev.lst(r, "ec2", "describe-volumes")), len(ev.lst(r, "ec2", "describe-snapshots"))])
        self.table("Inventory by region",
                   ["Region", "EC2 run", "EC2 stop", "ASG", "ECS cl", "EKS cl", "Lambda", "RDS", "DDB", "Cache",
                    "ALB", "NLB", "CLB", "NAT", "VPC", "SQS", "EBS vol", "Snaps"], rows)
        auth = ev.get("global", "iam", "get-account-authorization-details") or {}
        self.table("Global inventory", ["Item", "Count"], [
            ["S3 buckets", len(ev.lst("global", "s3api", "list-buckets"))],
            ["CloudFront distributions", len(ev.lst("global", "cloudfront", "list-distributions"))],
            ["Route 53 hosted zones", len(ev.lst("global", "route53", "list-hosted-zones"))],
            ["IAM users", len(auth.get("UserDetailList") or [])],
            ["IAM roles", len(auth.get("RoleDetailList") or [])],
            ["Customer managed policies", len(auth.get("Policies") or [])]])

    # ------------------------------------------------------------------ network
    def network(self):
        ev, t = self.ev, self.top
        world_sens, world_other, sg_world_sensitive = [], [], {}
        dflt, pub_inst, eips, enis_av, no_flow, nat_xaz, no_gwe, nat_inv = [], [], [], [], [], [], [], []
        for r in ev.regions:
            vpcs = ev.lst(r, "ec2", "describe-vpcs")
            subnets = {s["SubnetId"]: s for s in ev.lst(r, "ec2", "describe-subnets")}
            enis = ev.lst(r, "ec2", "describe-network-interfaces")
            attached = {}
            for e in enis:
                for g in e.get("Groups") or []:
                    attached[g] = attached.get(g, 0) + 1
            for sg in ev.lst(r, "ec2", "describe-security-groups"):
                for p in sg.get("In") or []:
                    srcs = [x.get("CidrIp") for x in p.get("IpRanges") or [] if x.get("CidrIp") == "0.0.0.0/0"] + \
                           [x.get("CidrIpv6") for x in p.get("Ipv6Ranges") or [] if x.get("CidrIpv6") == "::/0"]
                    if not srcs:
                        continue
                    proto, fp, tp = p.get("IpProtocol"), p.get("FromPort"), p.get("ToPort")
                    if proto in ("-1", "all"):
                        ports, sensitive, web = "all ports", True, False
                    elif proto in ("icmp", "icmpv6", "1", "58"):
                        continue
                    else:
                        fp, tp = int(fp if fp is not None else 0), int(tp if tp is not None else 65535)
                        ports = f"{proto}/{fp}" if fp == tp else f"{proto}/{fp}-{tp}"
                        sensitive = any(fp <= x <= tp for x in SENSITIVE_PORTS)
                        web = (fp, tp) in ((80, 80), (443, 443))
                    if web:
                        continue
                    line = f"{r} {sg['GroupId']} ({sg.get('Name')}) {ports} from {'/'.join(srcs)} · attached to {attached.get(sg['GroupId'], 0)} ENIs"
                    if sensitive:
                        world_sens.append(line)
                        sg_world_sensitive[(r, sg["GroupId"])] = ports
                    else:
                        world_other.append(line)
            default_ids = {v["VpcId"] for v in vpcs if v.get("IsDefault")}
            for vid in default_ids:
                n = sum(e.get("VpcId") == vid for e in enis)
                if n:
                    dflt.append(f"{r} {vid}: {n} network interfaces")
            for i in ev.lst(r, "ec2", "describe-instances"):
                if i.get("PublicIp") and i.get("State") == "running":
                    pub_inst.append(f"{r} {label(i['Id'], tags(i.get('Tags')))} {i.get('PublicIp')}")
            for a in ev.lst(r, "ec2", "describe-addresses"):
                if not a.get("Assoc"):
                    eips.append(f"{r} {a.get('Ip')} ({a.get('Alloc')})")
            for e in enis:
                if e.get("Status") == "available":
                    enis_av.append(f"{r} {e['Id']} {e.get('Desc') or ''}".strip())
            flow_res = {f.get("Res") for f in ev.lst(r, "ec2", "describe-flow-logs")}
            for v in vpcs:
                if v["VpcId"] not in flow_res:
                    partial = any(s.get("VpcId") == v["VpcId"] and sid in flow_res for sid, s in subnets.items())
                    no_flow.append(f"{r} {label(v['VpcId'], tags(v.get('Tags')))}" + (" (subnet-level only)" if partial else ""))
            nats = {n["Id"]: n for n in ev.lst(r, "ec2", "describe-nat-gateways") if n.get("State") == "available"}
            rts = ev.lst(r, "ec2", "describe-route-tables")
            explicit = {a.get("SubnetId") for rt in rts for a in rt.get("Assoc") or [] if a.get("SubnetId")}
            for n in nats.values():
                nat_inv.append(f"{r} {n['Id']} vpc={n.get('VpcId')} az={subnets.get(n.get('SubnetId'), {}).get('AZ')} "
                               f"mode={n.get('Mode') or 'zonal'} type={n.get('Type')} env={env_of(tags(n.get('Tags'))) or '?'}")
            served = {}
            for rt in rts:
                nat_ids = {x.get("Nat") for x in rt.get("Routes") or [] if x.get("Nat") and x.get("Dest") == "0.0.0.0/0"}
                if not nat_ids:
                    continue
                subs = [a.get("SubnetId") for a in rt.get("Assoc") or [] if a.get("SubnetId")]
                if any(a.get("Main") for a in rt.get("Assoc") or []):
                    subs += [sid for sid, s in subnets.items() if s.get("VpcId") == rt.get("VpcId") and sid not in explicit]
                for nid in nat_ids:
                    served.setdefault(nid, set()).update(subnets[s]["AZ"] for s in subs if s in subnets)
            for nid, azs in served.items():
                n = nats.get(nid)
                if not n or (n.get("Mode") or "").lower() == "regional":
                    continue
                naz = subnets.get(n.get("SubnetId"), {}).get("AZ")
                other = sorted(a for a in azs if a != naz)
                if other:
                    nat_xaz.append(f"{r} {nid} in {naz} is the default route for subnets in {', '.join(other)} (vpc {n.get('VpcId')})")
            gw = {(e.get("VpcId"), e.get("Service", "").rsplit(".", 1)[-1]) for e in ev.lst(r, "ec2", "describe-vpc-endpoints")
                  if e.get("Type") == "Gateway"}
            for vid in {n.get("VpcId") for n in nats.values()}:
                missing = [s for s in ("s3", "dynamodb") if (vid, s) not in gw]
                if missing:
                    no_gwe.append(f"{r} {vid}: no gateway endpoint for {', '.join(missing)}")
        self.ctx["sg_world_sensitive"] = sg_world_sensitive
        self.add("NET-02", "Security", "Security group ingress open to the internet on sensitive/admin ports", world_sens,
                 "Is the SG attached to anything reachable (public IP/subnet, internet-facing LB)? Compensating NACL/WAF?",
                 "framework §3.2")
        self.add("NET-03", "Security", "Security group ingress open to the internet on other non-web ports", world_other,
                 "Intended public service (e.g. VPN, SFTP)? Restrict sources if not.", "framework §3.2")
        self.add("NET-01", "Security", "Default VPC in use", dflt, "Default VPCs have public subnets by default; "
                 "is this intentional?", "AP-18")
        self.add("NET-04", "Security", "Running instances with public IPv4 addresses", pub_inst,
                 "Do they need direct inbound internet? Public IPv4 is also billed hourly.", "AP-18 · cost §5.5")
        self.add("NET-05", "Cost", "Unassociated Elastic IPs", eips, "Billed hourly while idle; confirm no DNS/IaC reference.", "cost §5.5")
        self.add("NET-06", "Cost", "Unattached (available) network interfaces", enis_av, "Leftovers vs. pre-provisioned ENIs?", "cost §5.5")
        self.add("NET-09", "Operational Excellence", "VPCs without VPC-level flow logs", no_flow,
                 "Needed for incident response in production VPCs; cost vs value in sandboxes.", "framework §3.2")
        self.add("NET-07", "Reliability", "Zonal NAT gateway serving subnets in other AZs (AZ dependency + cross-AZ charges)",
                 nat_xaz, "Tier 2+ production should not lose egress with one AZ; dev/test may accept it. "
                 "Regional-mode NAT gateways are excluded.", "AP-17 · AP-22")
        self.add("NET-08", "Cost", "VPCs with NAT gateways but no S3/DynamoDB gateway endpoint", no_gwe,
                 "Gateway endpoints are free; check NAT bytes and S3/DynamoDB usage first.", "AP-17")
        self.add("NET-10", "Cost", "NAT gateway inventory (check count vs environment and traffic)", nat_inv,
                 "Compare with NAT metrics/cost; per-AZ NAT in non-prod is often unnecessary.", "AP-17")

    # ------------------------------------------------------------------ compute, load balancing, containers, functions
    def compute(self):
        ev = self.ev
        prev = set(ev.lst("global", "ec2", "describe-instance-types"))
        imds, standalone, prevgen, older, burst, stopped, exposed = [], [], {}, {}, {}, [], []
        asg_1az, asg_hc, asg_single, asg_nopol, asg_lc = [], [], [], [], []
        arch = {}
        sgw = self.ctx.get("sg_world_sensitive", {})
        for r in ev.regions:
            md = (ev.get(r, "ec2", "get-instance-metadata-defaults") or {}).get("AccountLevel") or {}
            for i in ev.lst(r, "ec2", "describe-instances"):
                tg, st, typ = tags(i.get("Tags")), i.get("State"), i.get("Type") or ""
                if st == "stopped":
                    stopped.append(f"{r} {label(i['Id'], tg)} {typ} · {i.get('StateReason') or ''}".strip())
                if st != "running":
                    continue
                arch[i.get("Arch")] = arch.get(i.get("Arch"), 0) + 1
                if i.get("HttpTokens") == "optional":
                    imds.append(f"{r} {label(i['Id'], tg)}" + (" · account default requires IMDSv2" if md.get("HttpTokens") == "required" else ""))
                managed = any(k.startswith(("aws:autoscaling:groupName", "karpenter.sh/", "eks:", "aws:eks:")) for k in tg)
                if not managed:
                    standalone.append(f"{r} {label(i['Id'], tg)} {typ} {i.get('AZ')}")
                fam = typ.split(".")[0]
                m = re.match(r"^([a-z]+)(\d+)", fam)
                if typ in prev:
                    prevgen[typ] = prevgen.get(typ, 0) + 1
                elif m and not fam.startswith(("mac", "u-")) and \
                        (fam in ("t1", "t2") or (not fam.startswith("t") and int(m.group(2)) <= 4)):
                    older[fam] = older.get(fam, 0) + 1
                if fam.startswith("t"):
                    burst[typ] = burst.get(typ, 0) + 1
                ports = [sgw[(r, g)] for g in i.get("Groups") or [] if (r, g) in sgw]
                if i.get("PublicIp") and ports:
                    exposed.append(f"{r} {label(i['Id'], tg)} public {i['PublicIp']} with world-open {', '.join(sorted(set(ports)))}")
            pol = {p.get("Asg") for p in ev.lst(r, "autoscaling", "describe-policies")}
            for g in ev.lst(r, "autoscaling", "describe-auto-scaling-groups"):
                nm = f"{r} {g['Name']} (min {g.get('Min')}/max {g.get('Max')}/desired {g.get('Desired')})"
                if len(g.get("AZs") or []) == 1:
                    asg_1az.append(nm)
                if (g.get("TGs") or g.get("CLBs")) and g.get("HC") == "EC2":
                    asg_hc.append(nm)
                if (g.get("Max") or 0) <= 1:
                    asg_single.append(nm)
                if g["Name"] not in pol and (g.get("Max") or 0) > (g.get("Min") or 0):
                    asg_nopol.append(nm)
                if g.get("LC"):
                    asg_lc.append(f"{nm} uses launch configuration {g['LC']}")
        self.ctx["exposed_instances"] = exposed
        self.add("SEC-01", "Security", "Running instances with a public IP AND a world-open sensitive port", exposed,
                 "Highest-priority exposure candidate: confirm reachability (NACLs, host firewall) immediately.", "framework §3.2")
        self.add("CMP-01", "Security", "Running instances allowing IMDSv1 (HttpTokens=optional)", imds,
                 "Check application/SDK compatibility before enforcing IMDSv2.", "framework §3.2")
        self.add("CMP-02", "Reliability", "Running instances not managed by an Auto Scaling group / Karpenter", standalone,
                 "Single-instance production? Stateful? What is the recovery path and RTO?", "AP-07 · AP-22")
        self.add("CMP-03", "Performance Efficiency", "Previous-generation instance types (per AWS API)",
                 [f"{k} ×{v}" for k, v in sorted(prevgen.items(), key=lambda x: -x[1])], "Usually slower and costlier per unit.", "service-selection §2.9")
        self.add("CMP-04", "Performance Efficiency", "Older-generation families (gen ≤ 4, or t1/t2) still running",
                 [f"{k} ×{v}" for k, v in sorted(older.items(), key=lambda x: -x[1])], "Consider current generation / Graviton after testing.", "service-selection §2.9")
        self.add("CMP-05", "Performance Efficiency", "Burstable (T-family) instances running",
                 [f"{k} ×{v}" for k, v in sorted(burst.items(), key=lambda x: -x[1])],
                 "Fine for low sustained CPU; check CPUCreditBalance / surplus credits.", "service-selection §2.9")
        self.add("CMP-06", "Cost", "Stopped instances (EBS still billed)", stopped, "Long-stopped instances are often forgotten.", "cost §5.1")
        self.add("ASG-01", "Reliability", "Auto Scaling groups confined to one AZ", asg_1az, "Acceptable only for Tier 0/1.", "framework §4")
        self.add("ASG-02", "Reliability", "ASGs behind a load balancer using EC2 (not ELB) health checks", asg_hc,
                 "Unhealthy-but-running instances stay in service.", "AP-23")
        self.add("ASG-03", "Reliability", "ASGs with max size ≤ 1", asg_single, "Self-healing single instance only.", "AP-07")
        self.add("ASG-04", "Performance Efficiency", "ASGs with room to scale (max > min) but no scaling policy", asg_nopol,
                 "Scheduled actions or external scaling? Otherwise capacity is static.", "framework §3.3")
        self.add("ASG-05", "Operational Excellence", "ASGs using deprecated launch configurations", asg_lc,
                 "Migrate to launch templates.", "service-selection §3.1")
        self.table("Running instance architectures", ["Architecture", "Count"], [[k, v] for k, v in sorted(arch.items(), key=lambda x: str(x[0]))])

    def load_balancers(self):
        ev = self.ev
        clb, idle, no_waf, one_az = [], [], [], []
        for r in ev.regions:
            for c in ev.lst(r, "elb", "describe-load-balancers"):
                clb.append(f"{r} {c['Name']} ({c.get('Scheme')}, {len(c.get('Instances') or [])} instances)")
            tgs = ev.lst(r, "elbv2", "describe-target-groups")
            health = {k: d for k, d in ev.many(r, "elbv2", "describe-target-health")}
            protected = set()
            for _, d in ev.many(r, "wafv2", "list-resources-for-web-acl"):
                protected.update((d or {}).get("ResourceArns") or [])
            waf_known = ev.state(r, "wafv2", "list-web-acls") == "ok"
            for lb in ev.lst(r, "elbv2", "describe-load-balancers"):
                mine = [tg for tg in tgs if lb["Arn"] in (tg.get("LBs") or [])]
                targets = [x for tg in mine for x in (health.get(safe(tg["Name"])) or [])]
                if not mine:
                    idle.append(f"{r} {lb['Name']} ({lb.get('Type')}): no target groups")
                elif not targets:
                    idle.append(f"{r} {lb['Name']} ({lb.get('Type')}): no registered targets")
                elif not any(x.get("State") == "healthy" for x in targets):
                    idle.append(f"{r} {lb['Name']} ({lb.get('Type')}): no healthy targets")
                if lb.get("Type") == "application" and lb.get("Scheme") == "internet-facing" and waf_known and lb["Arn"] not in protected:
                    no_waf.append(f"{r} {lb['Name']}")
                if len(lb.get("AZs") or []) < 2:
                    one_az.append(f"{r} {lb['Name']}")
        self.add("LB-01", "Cost", "Load balancers without targets / healthy targets", idle,
                 "Idle LBs bill hourly; unhealthy-only LBs may be an outage.", "cost §5.5")
        self.add("LB-02", "Operational Excellence", "Classic Load Balancers still in use", clb, "Legacy; plan migration.", "service-selection §2.10")
        self.add("LB-03", "Security", "Internet-facing ALBs with no regional WAF web ACL", no_waf,
                 "WAF may sit on CloudFront in front instead; check before flagging.", "framework §3.2")
        self.add("LB-04", "Reliability", "Load balancers in a single AZ", one_az, "", "AP-22")

    def containers(self):
        ev = self.ev
        single, nocb, noci, eks_ver, eks_pub, ng_fixed = [], [], [], [], [], []
        for r in ev.regions:
            for _, lst in ev.many(r, "ecs", "describe-clusters"):
                for c in lst or []:
                    ci = {s.get("name"): s.get("value") for s in c.get("Settings") or []}.get("containerInsights")
                    if ci in (None, "disabled"):
                        noci.append(f"{r} {c.get('Name')}")
            for k, lst in ev.many(r, "ecs", "describe-services"):
                for s in lst or []:
                    nm = f"{r} {k.rsplit('.', 1)[0]}/{s.get('Name')} ({s.get('Launch') or ','.join(s.get('CPS') or []) or '?'})"
                    if (s.get("Desired") or 0) == 1:
                        single.append(nm)
                    if not ((s.get("CB") or {}).get("enable")):
                        nocb.append(nm)
            vers = {v.get("Version"): v for v in ev.lst(r, "eks", "describe-cluster-versions")}
            for _, c in ev.many(r, "eks", "describe-cluster"):
                if not isinstance(c, dict):
                    continue
                v = vers.get(c.get("Version")) or {}
                end = ptime(v.get("EndStandard"))
                if end and end < NOW:
                    eks_ver.append(f"{r} {c.get('Name')} v{c.get('Version')}: past end of standard support ({end.date()}); "
                                   f"support policy {c.get('Support') or '?'}")
                elif end and (end - NOW).days < 120:
                    eks_ver.append(f"{r} {c.get('Name')} v{c.get('Version')}: standard support ends {end.date()}")
                if c.get("Public") and "0.0.0.0/0" in (c.get("PublicCidrs") or []):
                    eks_pub.append(f"{r} {c.get('Name')}: public API endpoint open to 0.0.0.0/0")
            for k, ng in ev.many(r, "eks", "describe-nodegroup"):
                sc = (ng or {}).get("Scaling") or {}
                if sc and sc.get("minSize") == sc.get("maxSize"):
                    ng_fixed.append(f"{r} {k}: fixed size {sc.get('minSize')} ({','.join(ng.get('Types') or [])}, {ng.get('Capacity')})")
        self.add("CTR-01", "Reliability", "ECS services with desired count 1", single, "Tier? Deployment downtime?", "AP-22")
        self.add("CTR-02", "Operational Excellence", "ECS services without deployment circuit breaker", nocb,
                 "Failed deployments are not rolled back automatically.", "service-selection §3.5")
        self.add("CTR-03", "Operational Excellence", "ECS clusters without Container Insights", noci,
                 "Needed for task-level utilisation evidence; has a cost.", "service-selection §3.5")
        self.add("EKS-01", "Cost", "EKS clusters past or near end of standard Kubernetes support", eks_ver,
                 "Extended support has a higher hourly control-plane charge and upgrade risk.", "AP-01 · cost §5.7")
        self.add("EKS-02", "Security", "EKS public API endpoints open to the internet", eks_pub, "Restrict CIDRs or use private endpoint.", "framework §3.2")
        self.add("EKS-03", "Cost", "EKS nodegroups with fixed size (min = max)", ng_fixed, "Autoscaling via Karpenter/CA elsewhere?", "AP-08")

    def functions(self):
        ev = self.ev
        runtimes, dep, ver, t900, m128, envs, x86 = {}, [], [], [], [], [], 0
        for r in ev.regions:
            for f in ev.lst(r, "lambda", "list-functions"):
                rt = f.get("Runtime") or f"({f.get('Pkg')})"
                runtimes[rt] = runtimes.get(rt, 0) + 1
                if rt in LAMBDA_DEPRECATED:
                    dep.append(f"{r} {f['Name']} {rt}")
                elif rt in LAMBDA_VERIFY:
                    ver.append(f"{r} {f['Name']} {rt}")
                if f.get("Timeout") == 900:
                    t900.append(f"{r} {f['Name']}")
                if f.get("Mem") == 128:
                    m128.append(f"{r} {f['Name']}")
                if "x86_64" in (f.get("Arch") or ["x86_64"]):
                    x86 += 1
                hits = [k for k in f.get("EnvKeys") or [] if SECRETISH_NAME.search(k)]
                if hits:
                    envs.append(f"{r} {f['Name']}: {', '.join(hits)}")
        self.table("Lambda runtimes", ["Runtime", "Functions"], [[k, v] for k, v in sorted(runtimes.items(), key=lambda x: -x[1])])
        self.add("FN-01", "Security", "Lambda functions on deprecated runtimes", dep, "No security patches; plan upgrades.",
                 "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html")
        self.add("FN-02", "Operational Excellence", "Lambda runtimes at/near end of support (verify current dates)", ver,
                 "Check the Lambda runtimes page; list is a static snapshot.", "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html")
        self.add("FN-03", "Security", "Lambda environment variable NAMES that suggest secrets (values not collected)", envs,
                 "Values may be ARNs/SSM paths (fine) or literals (finding). Verify without printing values.", "methodology §2")
        self.add("FN-04", "Performance Efficiency", "Lambda functions with the maximum 900 s timeout", t900,
                 "Long-running work may belong on containers/Batch; timeouts should reflect expected duration.", "AP-06")
        self.add("FN-05", "Performance Efficiency", "Lambda functions at 128 MB (minimum CPU)", m128,
                 "Check duration; more memory can be faster and cheaper.", "service-selection §2.2")
        if x86:
            self.add("FN-06", "Cost", "Lambda functions on x86_64 (arm64 is usually cheaper per GB-second)", [], count=x86,
                     check="Only where dependencies support arm64.", see="cost §5.7")

    # ------------------------------------------------------------------ data & storage
    def databases(self):
        ev = self.ev
        pub, unenc, single, bkp, delp, stor, burst, nopi, life = [], [], [], [], [], [], [], [], []
        aur_single, ddb_pitr, ddb_bill, cache_ha, cache_enc, efs = [], [], {}, [], [], []
        sgw = self.ctx.get("sg_world_sensitive", {})
        sg_any_world = set(sgw)
        for r in ev.regions:
            lifes = {}
            for v in (ev.get(r, "rds", "describe-db-major-engine-versions") or {}).get("DBMajorEngineVersions") or []:
                for lc in v.get("SupportedEngineLifecycles") or []:
                    if lc.get("LifecycleSupportName") == "open-source-rds-standard-support":
                        lifes[(v.get("Engine"), v.get("MajorEngineVersion"))] = ptime(lc.get("LifecycleSupportEndDate"))

            def check_life(kind, ident, engine, ver, enrol):
                parts = (ver or "").split(".")
                major = parts[0] if "postgres" in (engine or "") else ".".join(parts[:2])
                end = lifes.get((engine, major))
                if end and end < NOW:
                    life.append(f"{r} {kind} {ident} {engine} {ver}: past end of standard support ({end.date()}); lifecycle={enrol}")
                elif end and (end - NOW).days < 180:
                    life.append(f"{r} {kind} {ident} {engine} {ver}: standard support ends {end.date()}")

            for d in ev.lst(r, "rds", "describe-db-instances"):
                tg = tags(d.get("Tags"))
                nm = f"{r} {label(d['Id'], tg)} {d.get('Engine')} {d.get('Class')}"
                if d.get("Public"):
                    open_sg = [g for g in d.get("SGs") or [] if (r, g) in sg_any_world]
                    pub.append(nm + (f" · SG {', '.join(open_sg)} world-open" if open_sg else ""))
                if d.get("Enc") is False:
                    unenc.append(nm)
                if not d.get("Cluster"):
                    if not d.get("MultiAZ"):
                        single.append(nm)
                    if (d.get("Backup") or 0) < 7:
                        bkp.append(f"{nm} retention {d.get('Backup')} days")
                    if not d.get("DelProt"):
                        delp.append(nm)
                    if d.get("Storage") in ("gp2", "io1", "standard"):
                        stor.append(f"{nm} {d.get('Storage')} {d.get('GiB')} GiB" + (f" {d.get('Iops')} IOPS" if d.get("Iops") else ""))
                    check_life("instance", d["Id"], d.get("Engine"), d.get("Ver"), d.get("Life"))
                if (d.get("Class") or "").startswith("db.t"):
                    burst.append(nm)
                if d.get("PI") is False:
                    nopi.append(nm)
            for c in ev.lst(r, "rds", "describe-db-clusters"):
                nm = f"{r} {label(c['Id'], tags(c.get('Tags')))} {c.get('Engine')}"
                if c.get("Engine", "").startswith("aurora") and len(c.get("Members") or []) == 1 and c.get("Mode") != "serverless":
                    aur_single.append(nm + " (single instance: failover means instance re-creation)")
                if (c.get("Backup") or 0) < 7:
                    bkp.append(f"{nm} retention {c.get('Backup')} days")
                if not c.get("DelProt"):
                    delp.append(nm)
                if c.get("Enc") is False:
                    unenc.append(nm)
                check_life("cluster", c["Id"], c.get("Engine"), c.get("Ver"), c.get("Life"))
            for k, t in ev.many(r, "dynamodb", "describe-table"):
                if isinstance(t, dict):
                    ddb_bill[t.get("Billing") or "PROVISIONED"] = ddb_bill.get(t.get("Billing") or "PROVISIONED", 0) + 1
            for k, st in ev.many(r, "dynamodb", "describe-continuous-backups"):
                if st == "DISABLED":
                    ddb_pitr.append(f"{r} {k}")
            for g in ev.lst(r, "elasticache", "describe-replication-groups"):
                if g.get("Failover") != "enabled" or g.get("MultiAZ") != "enabled":
                    cache_ha.append(f"{r} {g['Id']} failover={g.get('Failover')} multiaz={g.get('MultiAZ')}")
                if not g.get("AtRest") or not g.get("Transit"):
                    cache_enc.append(f"{r} {g['Id']} at-rest={g.get('AtRest')} in-transit={g.get('Transit')}")
            for c in ev.lst(r, "elasticache", "describe-cache-clusters"):
                if not c.get("Group") and c.get("Engine") in ("redis", "valkey"):
                    cache_ha.append(f"{r} {c['Id']} standalone {c.get('Engine')} node {c.get('Node')}")
            for f in ev.lst(r, "efs", "describe-file-systems"):
                notes = [x for x, cond in (("provisioned throughput", f.get("Tput") == "provisioned"),
                                           (f"One Zone ({f.get('OneZone')})", bool(f.get("OneZone"))),
                                           ("unencrypted", f.get("Enc") is False)) if cond]
                if notes:
                    efs.append(f"{r} {f['Id']} {human_bytes(f.get('Bytes'))}: {', '.join(notes)}")
        self.add("DB-01", "Security", "Publicly accessible RDS instances", pub, "Reachable from the internet if SG/NACL allow.", "framework §3.2")
        self.add("DB-02", "Security", "Unencrypted RDS/Aurora storage", unenc, "Encryption requires snapshot-restore migration.", "framework §3.2")
        self.add("DB-03", "Reliability", "Single-AZ RDS instances", single, "Required for Tier 2+ production; fine for dev/test.", "framework §4")
        self.add("DB-04", "Reliability", "Aurora clusters with a single instance", aur_single, "", "service-selection §2.3")
        self.add("DB-05", "Reliability", "Backup retention under 7 days", bkp, "Compare with stated RPO and detection window.", "AP-24")
        self.add("DB-06", "Reliability", "Deletion protection disabled", delp, "Cheap safeguard for production.", "framework §3.3")
        self.add("DB-07", "Cost", "RDS storage on gp2/io1/magnetic", stor, "gp3 is usually cheaper; check IOPS needs.", "service-selection §3.3")
        self.add("DB-08", "Cost", "RDS/Aurora engine versions past or near end of standard support (AWS lifecycle API)", life,
                 "Extended Support surcharges apply per vCPU-hour once standard support ends.", "service-selection §3.3")
        self.add("DB-09", "Performance Efficiency", "Burstable RDS classes (db.t*)", burst, "Check sustained CPU and credit balance.", "AP-09")
        self.add("DB-10", "Operational Excellence", "RDS without Performance Insights", nopi, "Limits query-level diagnosis.", "service-selection §3.3")
        self.add("DDB-01", "Reliability", "DynamoDB tables without point-in-time recovery", ddb_pitr, "Required where data is not reproducible.", "AP-24")
        self.add("CACHE-01", "Reliability", "ElastiCache without automatic failover / Multi-AZ", cache_ha, "OK for pure, rebuildable caches.", "service-selection §3.10")
        self.add("CACHE-02", "Security", "ElastiCache without at-rest or in-transit encryption", cache_enc, "", "service-selection §3.10")
        self.add("EFS-01", "Cost", "EFS settings to review", efs, "Provisioned throughput vs usage; One Zone resilience.", "service-selection §2.5")
        self.table("DynamoDB billing modes", ["Mode", "Tables"], [[k, v] for k, v in ddb_bill.items()])

    def storage(self):
        ev = self.ev
        unatt, gp2, io, unenc, enc_off, orphan, old_snap, old_ami = [], [], [], [], [], [], [], []
        tot = {"unatt": 0, "gp2": 0, "snap": 0, "orphan": 0}
        for r in ev.regions:
            vols = ev.lst(r, "ec2", "describe-volumes")
            vol_ids = {v["Id"] for v in vols}
            amis = ev.lst(r, "ec2", "describe-images")
            ami_snaps = {s for a in amis for s in a.get("Snaps") or [] if s}
            if (ev.get(r, "ec2", "get-ebs-encryption-by-default") or {}).get("EbsEncryptionByDefault") is False:
                enc_off.append(r)
            for v in sorted(vols, key=lambda x: -(x.get("GiB") or 0)):
                nm = f"{r} {label(v['Id'], tags(v.get('Tags')))} {v.get('Type')} {v.get('GiB')} GiB"
                if v.get("State") == "available":
                    unatt.append(nm + f" · created {utc_day(v.get('Created'))}")
                    tot["unatt"] += v.get("GiB") or 0
                if v.get("Type") == "gp2":
                    gp2.append(nm)
                    tot["gp2"] += v.get("GiB") or 0
                if v.get("Type") in ("io1", "io2"):
                    io.append(nm + f" {v.get('Iops')} IOPS")
                if v.get("Enc") is False:
                    unenc.append(nm)
            for s in ev.lst(r, "ec2", "describe-snapshots"):
                tot["snap"] += s.get("GiB") or 0
                age = days_ago(s.get("Start"))
                if s.get("Vol") not in vol_ids and s["Id"] not in ami_snaps:
                    orphan.append(f"{r} {s['Id']} {s.get('GiB')} GiB · {age} days old · {(s.get('Desc') or '')[:60]}")
                    tot["orphan"] += s.get("GiB") or 0
                elif age and age > 365:
                    old_snap.append(f"{r} {s['Id']} {s.get('GiB')} GiB · {age} days old")
            for a in amis:
                age = days_ago(a.get("Created"))
                if age and age > 365:
                    old_ami.append(f"{r} {a['Id']} {a.get('Name')} · {age} days old")
        self.add("STO-01", "Cost", f"Unattached EBS volumes ({gib(tot['unatt'])} provisioned)", unatt,
                 "Billed while detached; confirm owner and snapshot before any deletion.", "cost §5.3")
        self.add("STO-02", "Cost", f"gp2 volumes ({gib(tot['gp2'])})", gp2, "gp3 is usually cheaper; online modification.", "service-selection §3.2")
        self.add("STO-03", "Cost", "io1/io2 volumes (compare provisioned IOPS with observed)", io, "", "service-selection §3.2")
        self.add("STO-04", "Security", "Unencrypted EBS volumes", unenc, "", "framework §3.2")
        self.add("STO-05", "Security", "Regions where EBS encryption by default is off", enc_off, "", "framework §3.2")
        self.add("STO-06", "Cost", f"Snapshots whose source volume and AMI no longer exist ({gib(tot['orphan'])} source size)", orphan,
                 "Snapshots are incremental: freed storage may be lower than source size. Check retention policy.", "cost §5.3")
        self.add("STO-07", "Cost", "Snapshots older than 365 days (source volume or AMI still exists)", old_snap, "Retention policy?", "cost §5.3")
        self.add("STO-08", "Cost", "Owned AMIs older than 365 days", old_ami, "Each AMI keeps its snapshots billed.", "cost §5.3")

    def s3(self):
        ev = self.ev
        acct = ev.get("global", "s3control", "get-public-access-block") or {}
        cfg = acct.get("PublicAccessBlockConfiguration") or {}
        acct_full = bool(cfg) and all(cfg.get(k) for k in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"))
        if ev.state("global", "s3control", "get-public-access-block") in ("ok", "absent") and not acct_full:
            self.add("S3-02", "Security", "Account-level S3 Block Public Access not fully enabled", ["account " + str(ev.account)],
                     "Intentional public buckets? Prefer account-level BPA with exceptions handled via CloudFront OAC.", "framework §3.2")
        public, pab, nover, nolc, nolog = [], [], [], [], []
        buckets = ev.lst("global", "s3api", "list-buckets")
        for b in buckets:
            n = b.get("Name")
            ps = ev.get("global", "s3api", "get-bucket-policy-status", n) or {}
            if (ps.get("PolicyStatus") or {}).get("IsPublic"):
                public.append(f"{n} ({b.get('Region')})")
            bp = (ev.get("global", "s3api", "get-public-access-block", n) or {}).get("PublicAccessBlockConfiguration") or {}
            if not acct_full and not all(bp.get(k) for k in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")) \
                    and ev.state("global", "s3api", "get-public-access-block", n) in ("ok", "absent"):
                pab.append(n)
            if ev.state("global", "s3api", "get-bucket-versioning", n) == "ok" and \
                    (ev.get("global", "s3api", "get-bucket-versioning", n) or {}).get("Status") != "Enabled":
                nover.append(n)
            if ev.state("global", "s3api", "get-bucket-lifecycle-configuration", n) == "absent":
                nolc.append(n)
            if ev.state("global", "s3api", "get-bucket-logging", n) == "ok" and \
                    not (ev.get("global", "s3api", "get-bucket-logging", n) or {}).get("LoggingEnabled"):
                nolog.append(n)
        self.add("S3-01", "Security", "Buckets whose policy makes them PUBLIC", public,
                 "Intentional static website/CDN origin? Otherwise critical. Never list objects to check.", "framework §3.2")
        self.add("S3-03", "Security", "Buckets without full bucket-level Block Public Access (and no full account BPA)", pab, "", "framework §3.2")
        self.add("S3-04", "Reliability", "Buckets without versioning", nover, "Needed only where objects are not reproducible.", "framework §3.3", total=len(buckets))
        self.add("S3-05", "Cost", "Buckets without lifecycle rules", nolc,
                 "Expire noncurrent versions, abort incomplete uploads, tier cold data.", "cost §5.3", total=len(buckets))
        self.add("S3-06", "Operational Excellence", "Buckets without server access logging", nolog,
                 "Only needed for sensitive buckets (CloudTrail data events are an alternative).", "framework §3.2", total=len(buckets))

    # ------------------------------------------------------------------ integration
    def integration(self):
        ev = self.ev
        nodlq, short, vis, dlq_msgs, esm = [], [], [], [], []
        for r in ev.regions:
            fns = {f["Name"]: f for f in ev.lst(r, "lambda", "list-functions")}
            esms = ev.lst(r, "lambda", "list-event-source-mappings")
            queues = [(k, (d or {}).get("Attributes") or {}) for k, d in ev.many(r, "sqs", "get-queue-attributes")]
            targets = set()
            for _, a in queues:
                try:
                    targets.add(json.loads(a.get("RedrivePolicy") or "{}").get("deadLetterTargetArn"))
                except ValueError:
                    pass
            for k, a in queues:
                arn = a.get("QueueArn")
                is_dlq = arn in targets or re.search(r"(dlq|dead.?letter)", k, re.I)
                if is_dlq:
                    if int(a.get("ApproximateNumberOfMessages") or 0) > 0:
                        dlq_msgs.append(f"{r} {k}: {a.get('ApproximateNumberOfMessages')} messages waiting")
                    continue
                if not a.get("RedrivePolicy"):
                    nodlq.append(f"{r} {k}")
                if str(a.get("ReceiveMessageWaitTimeSeconds")) == "0":
                    short.append(f"{r} {k}")
                for m in esms:
                    if m.get("Src") == arn:
                        fn = fns.get((m.get("Fn") or "").split(":function:")[-1].split(":")[0])
                        if fn and int(a.get("VisibilityTimeout") or 0) < 6 * (fn.get("Timeout") or 0):
                            vis.append(f"{r} {k}: visibility {a.get('VisibilityTimeout')} s < 6 × {fn['Name']} timeout {fn.get('Timeout')} s")
            for m in esms:
                src = m.get("Src") or ""
                if (":kinesis:" in src or ":dynamodb:" in src) and m.get("Retries") in (None, -1) and not m.get("OnFailure"):
                    esm.append(f"{r} {(m.get('Fn') or '').split(':function:')[-1]} ← {src.split(':')[-1]}: unlimited retries, no on-failure destination")
        self.add("INT-01", "Reliability", "SQS queues (non-DLQ) without a dead-letter queue", nodlq, "Poison messages retry forever.", "AP-14 · AP-16")
        self.add("INT-02", "Reliability", "SQS visibility timeout shorter than 6× the consuming Lambda timeout", vis,
                 "Causes duplicate processing; AWS recommends ≥ 6× function timeout.", "AP-14")
        self.add("INT-03", "Operational Excellence", "Dead-letter queues with messages waiting", dlq_msgs, "Is anyone alerted and redriving?", "AP-16")
        self.add("INT-04", "Cost", "SQS queues using short polling", short, "Long polling (20 s) reduces empty receives.", "service-selection §3.12")
        self.add("INT-05", "Reliability", "Stream event source mappings with unlimited retries and no failure destination", esm,
                 "A poison record blocks the shard until it expires.", "AP-16")

    # ------------------------------------------------------------------ identity & detective controls
    def identity(self):
        ev = self.ev
        sm = (ev.get("global", "iam", "get-account-summary") or {}).get("SummaryMap") or {}
        root = []
        if sm.get("AccountMFAEnabled") == 0:
            root.append("root user has no MFA")
        if sm.get("AccountAccessKeysPresent") == 1:
            root.append("root user has access keys")
        self.add("SEC-02", "Security", "Root user exposure", root, "Root keys/MFA must be fixed by the account owner.", "framework §3.2")
        if ev.state("global", "iam", "get-account-password-policy") == "absent":
            self.add("IAM-08", "Security", "No IAM account password policy", ["default policy applies"],
                     "Relevant only if IAM users have console passwords.", "framework §3.2")
        rep = ev.get("global", "iam", "get-credential-report")
        if rep and rep.get("Content"):
            rows = list(csv.DictReader(io.StringIO(base64.b64decode(rep["Content"]).decode("utf-8", "replace"))))
            nomfa, oldkey, unused = [], [], []
            for u in rows:
                if u.get("user") == "<root_account>":
                    lu = days_ago(u.get("password_last_used"))
                    if lu is not None and lu <= 90:
                        root.append(f"root password used {lu} days ago")
                    continue
                if u.get("password_enabled") == "true" and u.get("mfa_active") == "false":
                    nomfa.append(f"{u['user']} (password last used {utc_day(u.get('password_last_used'), 'never')})")
                for n in ("1", "2"):
                    if u.get(f"access_key_{n}_active") != "true":
                        continue
                    age, used = days_ago(u.get(f"access_key_{n}_last_rotated")), days_ago(u.get(f"access_key_{n}_last_used_date"))
                    if age is not None and age > 90:
                        oldkey.append(f"{u['user']} key {n}: {age} days old")
                    if used is None or used > 90:
                        unused.append(f"{u['user']} key {n}: " + ("never used" if used is None else f"last used {used} days ago"))
            self.add("IAM-03", "Security", "IAM users with console password and no MFA", nomfa, "", "framework §3.2")
            self.add("IAM-06", "Security", "Active access keys older than 90 days", oldkey, "Prefer roles/SSO over long-lived keys.", "framework §3.2")
            self.add("IAM-07", "Security", "Active access keys unused for 90+ days (or never)", unused, "Deactivate after owner check.", "framework §3.2")
        elif ev.state("global", "iam", "get-credential-report") == "absent":
            self.table("Notes", ["Note"], [["No IAM credential report exists. Generating one is a write action: ask the user to run "
                                            "`aws iam generate-credential-report` if they want MFA/key-age evidence."]])
        auth = ev.get("global", "iam", "get-account-authorization-details") or {}
        own = ev.account
        admin_wild, svc_wild, passrole, admin_att, trust_any, trust_ext, oidc = [], [], [], [], [], [], []

        def scan(where, doc):
            for s in statements(doc):
                if s.get("Effect") != "Allow":
                    continue
                acts, res = [a.lower() for a in as_list(s.get("Action"))], as_list(s.get("Resource"))
                if "NotAction" in s:
                    svc_wild.append(f"{where}: Allow with NotAction (broad)")
                if "*" in res and ("*" in acts or "*:*" in acts):
                    admin_wild.append(where)
                elif "*" in res and any(a in ("iam:*", "sts:*", "kms:*", "organizations:*", "s3:*", "ec2:*") for a in acts):
                    svc_wild.append(f"{where}: {', '.join(a for a in acts if a.endswith(':*'))} on *")
                if "*" in res and "iam:passrole" in acts:
                    passrole.append(where)

        for p in auth.get("Policies") or []:
            for v in p.get("PolicyVersionList") or []:
                if v.get("IsDefaultVersion"):
                    scan(f"policy {p.get('PolicyName')} (attached {p.get('AttachmentCount')})", v.get("Document"))
        for kind, lst, inl in (("user", "UserDetailList", "UserPolicyList"), ("group", "GroupDetailList", "GroupPolicyList"),
                               ("role", "RoleDetailList", "RolePolicyList")):
            for e in auth.get(lst) or []:
                name = e.get(f"{kind.capitalize()}Name")
                for ip in e.get(inl) or []:
                    scan(f"{kind} {name} inline {ip.get('PolicyName')}", ip.get("PolicyDocument"))
                for ap in e.get("AttachedManagedPolicies") or []:
                    if ap.get("PolicyArn", "").endswith(":policy/AdministratorAccess"):
                        sso = (e.get("Path") or "").startswith("/aws-reserved/sso.amazonaws.com/")
                        admin_att.append(f"{kind} {name}" + (" (IAM Identity Center permission set)" if sso else ""))
        for role in auth.get("RoleDetailList") or []:
            if (role.get("Path") or "").startswith("/aws-service-role/"):
                continue
            for s in statements(role.get("AssumeRolePolicyDocument")):
                if s.get("Effect") != "Allow":
                    continue
                pr, cond = s.get("Principal"), s.get("Condition") or {}
                aws = as_list(pr.get("AWS")) if isinstance(pr, dict) else ([pr] if pr == "*" else [])
                if "*" in aws:
                    trust_any.append(f"{role.get('RoleName')}" + (" (has conditions)" if cond else " (NO conditions)"))
                for a in aws:
                    m = re.search(r"(\d{12})", str(a))
                    if m and own and m.group(1) != own:
                        has_guard = any(k in json.dumps(cond) for k in ("sts:ExternalId", "aws:PrincipalOrgID", "aws:SourceAccount"))
                        trust_ext.append(f"{role.get('RoleName')} ← account {m.group(1)}" + ("" if has_guard else " (no ExternalId/OrgID condition)"))
                fed = as_list(pr.get("Federated")) if isinstance(pr, dict) else []
                if any("token.actions.githubusercontent.com" in str(f) for f in fed) and ":sub" not in json.dumps(cond):
                    oidc.append(f"{role.get('RoleName')}: GitHub OIDC trust without a `sub` condition (any repo can assume)")
        self.add("IAM-01", "Security", "Policies granting Action * on Resource * (full admin)", admin_wild,
                 "Who can use them? Break-glass vs everyday use.", "framework §3.2")
        self.add("IAM-02", "Security", "Roles trusting ANY principal", trust_any, "", "framework §3.2")
        self.add("IAM-04", "Security", "Federated/OIDC trust without subject restriction", oidc, "", "framework §3.2")
        self.add("IAM-05", "Security", "Cross-account role trust (verify each partner account)", trust_ext,
                 "Expected org accounts vs third parties; third parties need ExternalId.", "framework §3.2")
        self.add("IAM-09", "Security", "Service-wide wildcards on sensitive services / NotAction allows", svc_wild, "", "framework §3.2")
        self.add("IAM-10", "Security", "iam:PassRole on Resource *", passrole, "Privilege-escalation path.", "framework §3.2")
        self.add("IAM-11", "Security", "AdministratorAccess attachments", admin_att, "Expected for a few break-glass/SSO admins only.", "framework §3.2")
        users = auth.get("UserDetailList") or []
        if users:
            direct = [u.get("UserName") for u in users if u.get("AttachedManagedPolicies") or u.get("UserPolicyList")]
            self.add("IAM-12", "Security", f"IAM users with directly attached/inline policies (of {len(users)} users)", direct,
                     "Prefer IAM Identity Center or groups/roles.", "framework §3.2")

    def detective(self):
        ev = self.ev
        trails = {}
        for r in ev.regions:
            for t in (ev.get(r, "cloudtrail", "describe-trails") or {}).get("trailList") or []:
                trails[t.get("TrailARN")] = t
        logging = {}
        for t in trails.values():
            st = ev.get(t.get("HomeRegion", ""), "cloudtrail", "get-trail-status", t.get("Name"))
            logging[t.get("TrailARN")] = (st or {}).get("IsLogging") if st else None   # None = unknown
        multi = [t for a, t in trails.items() if t.get("IsMultiRegionTrail") and logging.get(a)]
        unknown = [t for a, t in trails.items() if t.get("IsMultiRegionTrail") and logging.get(a) is None]
        gaps, rows = [], []
        if not multi and unknown:
            gaps.append("multi-region trail(s) " + ", ".join(t.get("Name", "?") for t in unknown) +
                        " found but logging status unknown (home region not assessed, organisation trail, or denied)")
        elif not multi and any(ev.state(r, "cloudtrail", "describe-trails") == "ok" for r in ev.regions):
            gaps.append("no logging multi-region CloudTrail trail found in assessed regions")
        for t in multi:
            if not t.get("LogFileValidationEnabled"):
                gaps.append(f"trail {t.get('Name')}: log file validation off")
        for r in ev.regions:
            def mark(state, ok):
                return {"ok": "yes" if ok else "NO", "absent": "NO", "denied": "denied", "error": "error"}.get(state, "?")
            rec = ev.get(r, "configservice", "describe-configuration-recorder-status") or {}
            cfg_ok = any(s.get("recording") for s in rec.get("ConfigurationRecordersStatus") or [])
            gd = [d for _, d in ev.many(r, "guardduty", "get-detector") if (d or {}).get("Status") == "ENABLED"]
            aa = [a for a in ev.lst(r, "accessanalyzer", "list-analyzers") if a.get("Status") == "ACTIVE"]
            row = [r, "yes" if multi else ("unknown" if unknown else mark(ev.state(r, "cloudtrail", "describe-trails"), False)),
                   mark(ev.state(r, "configservice", "describe-configuration-recorder-status"), cfg_ok),
                   mark(ev.state(r, "guardduty", "list-detectors"), bool(gd)),
                   mark(ev.state(r, "securityhub", "describe-hub"), ev.state(r, "securityhub", "describe-hub") == "ok"),
                   mark(ev.state(r, "accessanalyzer", "list-analyzers"), bool(aa))]
            rows.append(row)
            for name, v in zip(("CloudTrail", "AWS Config recording", "GuardDuty", "Security Hub", "IAM Access Analyzer"), row[1:]):
                if v == "NO" and name != "CloudTrail":      # CloudTrail is reported once, account-wide
                    gaps.append(f"{r}: {name} not enabled")
        self.table("Detective controls by region", ["Region", "CloudTrail (multi-region)", "Config", "GuardDuty", "Security Hub", "Access Analyzer"], rows)
        self.add("DET-01", "Security", "Detective-control gaps", gaps,
                 "Organisation-level/delegated-admin setups may cover these from another account: verify before flagging.", "framework §3.2")

    def secrets_keys(self):
        ev = self.ev
        norot, unused_sec, kms_norot, ssm_gap, certs = [], [], [], [], []
        for r in ev.regions:
            for s in ev.lst(r, "secretsmanager", "list-secrets"):
                if not s.get("Rotation") and not s.get("Owner"):
                    norot.append(f"{r} {s.get('Name')}")
                la = days_ago(s.get("LastAccessed"))
                if la is not None and la > 90:
                    unused_sec.append(f"{r} {s.get('Name')}: last accessed {la} days ago")
            for k, st in ev.many(r, "kms", "get-key-rotation-status"):
                if isinstance(st, dict) and st.get("KeyRotationEnabled") is False:
                    kms_norot.append(f"{r} {k}")
            if ev.state(r, "ssm", "describe-instance-information") == "ok":
                online = {i.get("Id") for i in ev.lst(r, "ssm", "describe-instance-information") if i.get("Ping") == "Online"}
                for i in ev.lst(r, "ec2", "describe-instances"):
                    if i.get("State") == "running" and i["Id"] not in online:
                        ssm_gap.append(f"{r} {label(i['Id'], tags(i.get('Tags')))}")
            for c in ev.lst(r, "acm", "list-certificates"):
                end = ptime(c.get("NotAfter"))
                if c.get("Status") == "EXPIRED" or (end and (end - NOW).days < 30 and c.get("InUse")):
                    certs.append(f"{r} {c.get('Domain')} {c.get('Status')} expires {end.date() if end else '?'} ({c.get('Type')})")
        self.add("SEC-03", "Security", "Secrets without rotation", norot, "Rotation may be handled elsewhere; check type of secret.", "framework §3.2")
        self.add("SEC-04", "Cost", "Secrets not accessed for 90+ days", unused_sec, "Billed per secret per month.", "cost §5.6")
        self.add("SEC-05", "Security", "Customer-managed KMS keys without automatic rotation", kms_norot, "Policy-dependent.", "framework §3.2")
        self.add("SEC-06", "Security", "Running instances not managed (online) in Systems Manager", ssm_gap,
                 "No patch/compliance visibility or Session Manager access.", "framework §3.2")
        self.add("SEC-07", "Operational Excellence", "In-use certificates expiring within 30 days or expired", certs,
                 "Imported certs do not auto-renew.", "framework §3.1")

    # ------------------------------------------------------------------ operations & recovery
    def operations(self):
        ev = self.ev
        noact, inalarm, zero, never, lg_rows, drift, failed, notag = [], [], [], [], [], [], [], []
        iac = total = 0
        never_bytes = 0
        for r in ev.regions:
            al = ev.get(r, "cloudwatch", "describe-alarms") or {}
            ms = (al.get("Metric") or []) + (al.get("Composite") or [])
            workload = len(ev.lst(r, "ec2", "describe-instances")) + len(ev.lst(r, "rds", "describe-db-instances")) + \
                len(ev.lst(r, "lambda", "list-functions")) + len(ev.lst(r, "elbv2", "describe-load-balancers"))
            if ev.state(r, "cloudwatch", "describe-alarms") == "ok" and not ms and workload:
                zero.append(f"{r}: {workload} workload resources, 0 alarms")
            for a in ms:
                if not a.get("Actions") or a.get("Enabled") is False:
                    noact.append(f"{r} {a.get('Name')}")
                if a.get("State") == "ALARM":
                    inalarm.append(f"{r} {a.get('Name')}")
            for g in ev.lst(r, "logs", "describe-log-groups"):
                if g.get("Retention") is None:
                    never.append((g.get("Bytes") or 0, f"{r} {g.get('Name')}"))
                    never_bytes += g.get("Bytes") or 0
            for s in ev.lst(r, "cloudformation", "list-stacks"):
                if s.get("Drift") == "DRIFTED":
                    drift.append(f"{r} {s.get('Name')}")
                if "FAILED" in (s.get("Status") or ""):
                    failed.append(f"{r} {s.get('Name')} {s.get('Status')}")
            for i in ev.lst(r, "ec2", "describe-instances") + ev.lst(r, "ec2", "describe-volumes"):
                tg = tags(i.get("Tags"))
                total += 1
                iac += any(IAC_TAG.match(k or "") for k in tg)
                if i.get("State") == "running" and not (env_of(tg) and tag_like(tg, {"owner", "team", "contact", "owner-email"})):
                    notag.append(f"{r} {label(i['Id'], tg)}")
        never.sort(reverse=True)
        self.add("OPS-01", "Operational Excellence", "Regions with workloads but no CloudWatch alarms", zero, "", "framework §3.1")
        self.add("OPS-02", "Operational Excellence", "Alarms with no actions (or actions disabled)", noact, "Nobody is notified.", "framework §3.1")
        self.add("OPS-03", "Operational Excellence", "Alarms currently in ALARM state", inalarm, "Ongoing issue or ignored alarm?", "framework §3.1")
        self.add("OPS-04", "Cost", f"Log groups with no retention ('never expire'), {human_bytes(never_bytes)} stored",
                 [f"{n} · {human_bytes(b)}" for b, n in never], "Set retention per data-retention policy.", "cost §5.6")
        self.add("OPS-05", "Operational Excellence", "CloudFormation stacks reporting drift", drift,
                 "Drift status reflects the last detection run, which may be old.", "AP-29")
        self.add("OPS-06", "Operational Excellence", "CloudFormation stacks in a FAILED state", failed, "", "framework §3.1")
        self.add("OPS-07", "Operational Excellence", "Running instances without environment + owner tags", notag, "", "framework §3.1")
        if total:
            self.table("IaC provenance proxy (EC2 instances + volumes with IaC-style tags)", ["Tagged by IaC", "Total", "Share"],
                       [[iac, total, f"{100 * iac / total:.0f}%"]])

    def backup(self):
        ev = self.ev
        plans, rows, unprot = 0, [], []
        for r in ev.regions:
            plans += len(ev.lst(r, "backup", "list-backup-plans"))
            prot = {p.get("Arn") for p in ev.lst(r, "backup", "list-protected-resources")}
            known = ev.state(r, "backup", "list-protected-resources") == "ok"
            acct = ev.account or "*"
            inv = [(f"arn:aws:ec2:{r}:{acct}:instance/{i['Id']}", "EC2", i) for i in ev.lst(r, "ec2", "describe-instances") if i.get("State") == "running"]
            inv += [(f"arn:aws:rds:{r}:{acct}:db:{d['Id']}", "RDS", d) for d in ev.lst(r, "rds", "describe-db-instances") if not d.get("Cluster")]
            inv += [(f"arn:aws:rds:{r}:{acct}:cluster:{c['Id']}", "Aurora", c) for c in ev.lst(r, "rds", "describe-db-clusters")]
            inv += [(f"arn:aws:dynamodb:{r}:{acct}:table/{t}", "DynamoDB", {}) for t in (ev.get(r, "dynamodb", "list-tables") or {}).get("TableNames") or []]
            inv += [(f"arn:aws:elasticfilesystem:{r}:{acct}:file-system/{f['Id']}", "EFS", f) for f in ev.lst(r, "efs", "describe-file-systems")]
            if not known:
                continue
            by = {}
            for arn, kind, _ in inv:
                tot, cov = by.get(kind, (0, 0))
                by[kind] = (tot + 1, cov + (arn in prot))
                if arn not in prot and kind in ("EC2", "EFS"):
                    unprot.append(f"{r} {kind} {arn.rsplit('/', 1)[-1]}")
            rows += [[r, k, t, c] for k, (t, c) in sorted(by.items())]
            locked = sum(1 for v in ev.lst(r, "backup", "list-backup-vaults") if v.get("Locked"))
            if locked:
                rows.append([r, "Vaults with Vault Lock", locked, ""])
        self.table("AWS Backup coverage (RDS automated backups and DynamoDB PITR are separate mechanisms)",
                   ["Region", "Type", "Resources", "Protected by AWS Backup"], rows)
        if plans == 0 and any(ev.state(r, "backup", "list-backup-plans") == "ok" for r in ev.regions):
            self.add("BKP-01", "Reliability", "No AWS Backup plans in assessed regions", ["0 plans"],
                     "Backups may be done another way (snapshots/DLM/scripts); ask how restores are tested.", "AP-24")
        self.add("BKP-02", "Reliability", "Running EC2 instances / EFS not protected by AWS Backup", unprot,
                 "Stateless instances rebuilt from IaC do not need backups.", "AP-24")

    # ------------------------------------------------------------------ metrics
    def metrics(self):
        ev = self.ev
        rows = {}
        window = None
        for r in ev.regions:
            mp = jload(os.path.join(ev.root, r, "metric-map.json"))
            if not mp:
                continue
            window = mp.get("days")
            for _, res in ev.many(r, "cloudwatch", "get-metric-data"):
                for m in res or []:
                    meta = mp["map"].get(m.get("Id"))
                    if not meta:
                        continue
                    vals = [float(v) for v in m.get("Values") or []]
                    rows[(r, meta["ns"], meta["resource"], meta["metric"], meta["stat"])] = vals
        if not rows:
            return
        fns = {(r, f["Name"]): f for r in ev.regions for f in ev.lst(r, "lambda", "list-functions")}

        def v(r, ns, res, metric, stat):
            return rows.get((r, ns, res, metric, stat))

        low, hot, rds_idle, rds_low, nat, nat_err, lb_idle, thr, near_to, unused_fn, nodata = ([] for _ in range(11))
        for (r, ns, res, metric, stat), vals in rows.items():
            if not vals:
                if stat in ("Average", "Sum"):
                    nodata.append(f"{r} {res} {metric}")
                continue
            if ns in ("AWS/EC2", "AWS/RDS", "AWS/ElastiCache") and metric == "CPUUtilization" and stat == "Average":
                mx = v(r, ns, res, metric, "Maximum") or []
                avg, peak = statistics.mean(vals), max(mx) if mx else max(vals)
                p95 = sorted(mx)[int(0.95 * (len(mx) - 1))] if mx else peak
                desc = f"{r} {res}: CPU avg {avg:.1f}% · max {peak:.1f}% · p95 daily max {p95:.1f}% ({len(vals)} days)"
                if len(vals) >= 14 and avg < 10 and peak < 40:
                    (rds_low if ns == "AWS/RDS" else low).append(desc)
                if avg >= 70 or p95 >= 90:
                    hot.append(desc)
            if ns == "AWS/RDS" and metric == "DatabaseConnections" and max(vals) == 0 and len(vals) >= 14:
                rds_idle.append(f"{r} {res}: 0 connections for {len(vals)} days")
            if ns == "AWS/NATGateway" and metric == "BytesInFromSource":
                total = sum(vals) + sum(v(r, ns, res, "BytesInFromDestination", "Sum") or [])
                nat.append((total, f"{r} {res}: {human_bytes(total)} processed in {len(vals)} days"))
            if ns == "AWS/NATGateway" and metric == "ErrorPortAllocation" and sum(vals) > 0:
                nat_err.append(f"{r} {res}: {sum(vals):.0f} port allocation errors")
            if ns in ("AWS/ApplicationELB", "AWS/NetworkELB") and sum(vals) == 0 and len(vals) >= 14:
                lb_idle.append(f"{r} {res}: zero {metric} for {len(vals)} days")
            if ns == "AWS/Lambda":
                if metric == "Throttles" and sum(vals) > 0:
                    thr.append(f"{r} {res}: {sum(vals):.0f} throttles")
                if metric == "Invocations" and sum(vals) == 0 and len(vals) >= 14:
                    unused_fn.append(f"{r} {res}")
                if metric == "Duration" and stat == "Maximum":
                    f = fns.get((r, res))
                    if f and f.get("Timeout") and max(vals) >= 0.8 * f["Timeout"] * 1000:
                        near_to.append(f"{r} {res}: max duration {max(vals) / 1000:.1f} s vs timeout {f['Timeout']} s")
        nat.sort(reverse=True)
        w = f"{window}-day window, daily statistics"
        self.add("MET-01", "Cost", f"Low-utilisation EC2/cache nodes (avg CPU < 10%, max < 40%; {w})", low,
                 "CPU only: memory needs the CloudWatch agent. Check headroom/failover role before rightsizing.", "cost §7")
        self.add("MET-02", "Performance Efficiency", f"Hot compute (avg CPU ≥ 70% or p95 daily max ≥ 90%; {w})", hot,
                 "Scaling policy? Burst credits? Is latency affected?", "framework §3.4")
        self.add("MET-03", "Cost", f"RDS instances with zero connections ({w})", rds_idle, "DR/standby? Monthly jobs?", "cost §5.4")
        self.add("MET-04", "Cost", f"Low-utilisation RDS (avg CPU < 10%, max < 40%; {w})", rds_low, "Memory/IOPS may still bind.", "cost §5.4")
        self.add("MET-05", "Cost", f"NAT gateway data processed ({w})", [d for _, d in nat],
                 "Per-GB processing charge applies; compare with endpoint options.", "AP-17")
        self.add("MET-06", "Reliability", "NAT gateways with port allocation errors", nat_err, "Connection exhaustion.", "service-selection §3.7")
        self.add("MET-07", "Cost", f"Load balancers with zero traffic ({w})", lb_idle, "", "cost §5.5")
        self.add("MET-08", "Reliability", "Lambda functions throttled", thr, "Concurrency limits vs. demand.", "framework §3.3")
        self.add("MET-09", "Reliability", "Lambda max duration ≥ 80% of timeout", near_to, "Timeouts likely under load.", "AP-06")
        self.add("MET-10", "Cost", f"Lambda functions with zero invocations ({w})", unused_fn, "Unused or rarely triggered?", "cost §5.7")
        self.add("MET-11", "Operational Excellence", "Metrics with no datapoints (absence ≠ idleness)", nodata, "", "cost §6")

    # ------------------------------------------------------------------ cost
    def cost(self):
        ev = self.ev
        bys = ev.get("global", "ce", "get-cost-and-usage", "by-service")
        if not bys:
            return
        months = []
        for p in bys.get("ResultsByTime") or []:
            total = sum(float(g["Metrics"]["UnblendedCost"]["Amount"]) for g in p.get("Groups") or [])
            unit = next((g["Metrics"]["UnblendedCost"]["Unit"] for g in p.get("Groups") or []), "USD")
            months.append((p["TimePeriod"]["Start"], total, unit, p.get("Groups") or []))
        self.table("Monthly spend [Measured · Cost Explorer UnblendedCost]", ["Month", "Total"],
                   [[m, f"{t:,.2f} {u}"] for m, t, u, _ in months])
        if months:
            _, total, unit, groups = months[-1]
            top = sorted(((float(g["Metrics"]["UnblendedCost"]["Amount"]), g["Keys"][0]) for g in groups), reverse=True)[:12]
            self.table(f"Top services, last full month ({months[-1][0]}) [Measured]", ["Service", "Cost", "Share"],
                       [[s, f"{a:,.2f} {unit}", f"{100 * a / total:.1f}%" if total else "-"] for a, s in top])
        ut = ev.get("global", "ce", "get-cost-and-usage", "by-usage-type")
        if ut:
            cats = [("NAT gateway", r"NatGateway"), ("Data transfer", r"DataTransfer|-Out-Bytes|-In-Bytes|Regional-Bytes"),
                    ("Public IPv4", r"PublicIPv4"), ("CloudWatch", r"CW:|-Logs|DataProcessing-Bytes|TimedStorage-ByteHrs"),
                    ("Extended support", r"ExtendedSupport"), ("EBS snapshots", r"EBS:Snapshot"),
                    ("VPC endpoints", r"VpcEndpoint"), ("Load balancers", r"LoadBalancerUsage|LCUUsage"), ("EKS control plane", r"EKS")]
            agg = {}
            for p in ut.get("ResultsByTime") or []:
                for g in p.get("Groups") or []:
                    k, amt = g["Keys"][0], float(g["Metrics"]["UnblendedCost"]["Amount"])
                    for name, rx in cats:
                        if re.search(rx, k):
                            a, ks = agg.get(name, (0.0, []))
                            agg[name] = (a + amt, ks + [(amt, k)])
                            break
            self.table("Hidden infrastructure cost drivers, last full month [Measured · by usage type]", ["Category", "Cost", "Top usage types"],
                       [[n, f"{a:,.2f}", ", ".join(k for _, k in sorted(ks, reverse=True)[:3])]
                        for n, (a, ks) in sorted(agg.items(), key=lambda x: -x[1][0]) if a > 0])
        rows = []
        spc = ev.get("global", "ce", "get-savings-plans-coverage") or {}
        for c in spc.get("SavingsPlansCoverages") or []:
            rows.append(["Savings Plans coverage", f"{float((c.get('Coverage') or {}).get('CoveragePercentage') or 0):.1f}%"])
        spu = ((ev.get("global", "ce", "get-savings-plans-utilization") or {}).get("Total") or {}).get("Utilization") or {}
        if spu:
            rows.append(["Savings Plans utilisation", f"{float(spu.get('UtilizationPercentage') or 0):.1f}%"])
        rc = (ev.get("global", "ce", "get-reservation-coverage") or {}).get("Total") or {}
        if rc:
            rows.append(["RI coverage (hours)", f"{float((rc.get('CoverageHours') or {}).get('CoverageHoursPercentage') or 0):.1f}%"])
        ru = (ev.get("global", "ce", "get-reservation-utilization") or {}).get("Total") or {}
        if ru:
            rows.append(["RI utilisation", f"{float(ru.get('UtilizationPercentage') or 0):.1f}%"])
        for k in ("get-savings-plans-coverage", "get-reservation-coverage"):
            if ev.state("global", "ce", k) == "absent":
                rows.append([k, "no data (no commitments or no usage)"])
        self.table("Commitments, last full month [Measured]", ["Metric", "Value"], rows)
        co, ta = [], []
        for r in ev.regions:
            for s in (ev.get(r, "compute-optimizer", "get-recommendation-summaries") or {}).get("recommendationSummaries") or []:
                counts = {x.get("name"): x.get("value") for x in s.get("summaries") or []}
                sav = ((s.get("savingsOpportunity") or {}).get("estimatedMonthlySavings") or {})
                co.append([r, s.get("recommendationResourceType"), counts.get("OVER_PROVISIONED", counts.get("NOT_OPTIMIZED", 0)),
                           counts.get("UNDER_PROVISIONED", 0), counts.get("OPTIMIZED", 0),
                           f"{float(sav.get('value') or 0):,.2f} {sav.get('currency') or ''}".strip()])
        self.table("Compute Optimizer summaries [AWS-estimated savings, validate before quoting]",
                   ["Region", "Type", "Over/not optimised", "Under", "Optimised", "Est. monthly savings"], co)
        for t in ev.lst("global", "trustedadvisor", "list-recommendations"):
            if "cost_optimizing" in (t.get("Pillars") or []) and t.get("Status") in ("warning", "error"):
                ta.append((float(t.get("Savings") or 0), f"{t.get('Name')}: est. {float(t.get('Savings') or 0):,.2f}/month ({t.get('Status')})"))
        self.add("COST-01", "Cost", "Trusted Advisor cost recommendations [AWS-estimated]", [d for _, d in sorted(ta, reverse=True)],
                 "Validate each against utilisation and context; do not copy totals.", "cost §4")

    # ------------------------------------------------------------------ render
    def render(self):
        ev, m = self.ev, self.ev.manifest
        L = [f"# Evidence digest — account {ev.account or '?'}",
             "",
             f"Collected {m.get('started', '?')} → {m.get('finished', '?')} · profile `{m.get('profile', '?')}` · regions "
             f"{', '.join(ev.regions)} · collector {m.get('collector', '?')} · status **{m.get('status', '?')}** · "
             f"digest generated {NOW.isoformat(timespec='seconds')}",
             "",
             "> **Signals are mechanical facts, not findings.** Interpret each against workload purpose, criticality, intent "
             "and compensating controls (SKILL.md Phase 4) before reporting; many will be legitimate. Absence of a signal is not "
             "proof of good configuration where coverage was partial (see coverage tables). Cite signal IDs in findings.",
             ""]
        first = [s for s in self.signals if s["id"] in HIGH_IMPACT]
        if first:
            L += ["## Examine first (high impact if confirmed)", ""]
            L += [f"- **{s['id']}** {s['title']} — {s['count']}" for s in sorted(first, key=lambda s: s["id"])]
            L.append("")
        for t in self.tables[:3]:
            L += self._table(t)
        by = {}
        for s in self.signals:
            by.setdefault(s["pillar"], []).append(s)
        L += ["## Signals by pillar", ""]
        for pillar in ("Security", "Reliability", "Performance Efficiency", "Cost", "Operational Excellence"):
            if pillar not in by:
                continue
            L += [f"### {pillar}", ""]
            for s in sorted(by[pillar], key=lambda s: s["id"]):
                tot = f" of {s['total']}" if s.get("total") else ""
                L.append(f"- **{s['id']} · {s['title']}** — {s['count']}{tot}"
                         + (f" · _check:_ {s['check']}" if s.get("check") else "")
                         + (f" · _see:_ {s['see']}" if s.get("see") else ""))
                for it in s["items"][:self.top]:
                    L.append(f"  - {it}")
                if len(s["items"]) > self.top:
                    L.append(f"  - … +{len(s['items']) - self.top} more (digest.json has all)")
            L.append("")
        if len(self.tables) > 3:
            L += ["## Context tables", ""]
            for t in self.tables[3:]:
                L += self._table(t)
        if self.errors:
            L += ["## Digest errors (some signals may be incomplete)", ""] + [f"- {e}" for e in self.errors] + [""]
        return "\n".join(L) + "\n"

    def _table(self, t):
        rows = t["rows"][:max(self.top * 3, 40)]
        out = [f"**{t['title']}**", "", "| " + " | ".join(map(str, t["header"])) + " |",
               "|" + "---|" * len(t["header"])]
        out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
        if len(t["rows"]) > len(rows):
            out.append(f"| … +{len(t['rows']) - len(rows)} more rows | " + " | " * (len(t["header"]) - 1))
        return out + [""]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Signal digest for collect.py evidence (local files only).")
    ap.add_argument("evidence")
    ap.add_argument("--top", type=int, default=15, help="items listed per signal in digest.md")
    a = ap.parse_args(argv)
    if not os.path.isfile(os.path.join(a.evidence, "manifest.json")):
        ap.error(f"{a.evidence} has no manifest.json (run collect.py first)")
    d = Digest(Evidence(a.evidence), a.top)
    for fn in (d.coverage, d.inventory, d.network, d.compute, d.load_balancers, d.containers, d.functions,
               d.databases, d.storage, d.s3, d.integration, d.identity, d.detective, d.secrets_keys, d.operations,
               d.backup, d.metrics, d.cost):
        d.run(fn)
    md = d.render()
    with open(os.path.join(a.evidence, "digest.md"), "w") as fh:
        fh.write(md)
    with open(os.path.join(a.evidence, "digest.json"), "w") as fh:
        json.dump({"account": d.ev.account, "generated": NOW.isoformat(), "signals": d.signals, "tables": d.tables,
                   "errors": d.errors}, fh, indent=1, default=str)
    print(f"[digest] {len(d.signals)} signals ({sum(s['id'] in HIGH_IMPACT for s in d.signals)} high-impact) · "
          f"{len(d.errors)} errors · {os.path.join(a.evidence, 'digest.md')}")
    return 1 if d.errors else 0


if __name__ == "__main__":
    sys.exit(main())
