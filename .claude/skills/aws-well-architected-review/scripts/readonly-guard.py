#!/usr/bin/env python3
"""Read-only guard for the aws-well-architected-review skill.

Registered as a PreToolUse hook (matcher: Bash|Read|Grep|Glob) in the skill's SKILL.md frontmatter.
It reads the hook JSON on stdin and BLOCKS the call (exit code 2, reason on stderr) when it could

  * create, modify or delete cloud resources (any AWS CLI operation that is not a
    describe-/list-/get-/lookup-/batch-get- read),
  * mint or reveal credentials or secret values (credential APIs, --debug output, credential/SSO cache
    files, environment dumps),
  * read application data (data plane: table rows, queue messages, secret values, S3 objects other than log files).
    Logs are NOT blocked: CloudWatch Logs (events, filter, Logs Insights, tail), Step Functions execution history,
    RDS log files, EC2 console output, kubectl logs and AWS log files in S3 are readable for diagnosis,
  * inspect an ambient account (AWS calls must name --profile or an inline AWS_PROFILE=),
  * run infrastructure-as-code or cluster tooling that can change state.

Exit 0 with no output means "no objection" and the normal permission flow applies.

This is defence in depth, NOT a sandbox: it cannot see through a binary renamed into a variable or code
inside arbitrary scripts. The real boundary is a read-only IAM role (ReadOnlyAccess / ViewOnlyAccess /
SecurityAudit style). The collector (collect.py) imports this module and validates every call with
check_aws(), so there is one policy for interactive and scripted collection.

Run `python3 readonly-guard.py --self-test` to execute the built-in test table.
"""
import json
import os
import re
import shlex
import sys

# --------------------------------------------------------------------------- policy tables

READ_PREFIXES = ("describe-", "list-", "get-", "lookup-", "batch-get-")

# Read-only operations whose names do not start with a read prefix.
EXTRA_READ = {
    "ec2 search-transit-gateway-routes",
    "ec2 search-local-gateway-routes",
    "configservice select-resource-config",
    "configservice select-aggregate-resource-config",
    "resource-explorer-2 search",
    "iam simulate-principal-policy",
    "iam simulate-custom-policy",
    "accessanalyzer validate-policy",
    # Logs are evidence for architecture reviews (failure causes, error rates, access patterns).
    "logs filter-log-events",
    "logs start-query",            # Logs Insights; results via logs get-query-results (billed per GB scanned)
    "logs stop-query",
    "logs tail",
    "logs start-live-tail",
    "rds download-db-log-file-portion",
}

# AWS log files in S3 (ALB/NLB/CloudFront/S3 access logs, CloudTrail, VPC Flow Logs, Config) may be read: either the key
# is under AWS's standard delivery prefix "AWSLogs/", or the bucket name marks it as a log bucket (word-bounded, so
# "catalog" does not match). Other S3 objects are application data and stay blocked.
LOG_BUCKET = re.compile(r"(^|[-_.])(logs?|logging|cloudtrail|flowlogs?|accesslogs?)([-_.]|$)", re.I)

R_AUTH = ("authentication and credential operations are user-only. If credentials are expired, stop and "
          "ask the user to refresh their session in their own terminal (aws sso login --profile NAME).")
R_DATA = ("this reads application data (data plane). The review reads configuration, metrics, metadata and logs, "
          "not application data. Ask the user first if you genuinely need it.")
R_SECRET = "this returns secret or credential material, which must never enter the review."

DENY_SERVICES = {
    "sso": R_AUTH,
    "sso-oidc": R_AUTH,
    "login": R_AUTH,
    "logout": R_AUTH,
    "rds-data": R_DATA,
    "redshift-data": R_DATA,
    "dynamodbstreams": R_DATA,
}

DENY_OPS = {
    ("dynamodb", "get-item"): R_DATA,
    ("dynamodb", "batch-get-item"): R_DATA,
    ("kinesis", "get-records"): R_DATA,
    ("kinesis", "get-shard-iterator"): R_DATA,
    ("athena", "get-query-results"): R_DATA,
    ("stepfunctions", "get-activity-task"): "claims a pending activity task (a side effect), not a read.",
    ("ssm", "get-parameter"): R_SECRET,
    ("ssm", "get-parameters"): R_SECRET,
    ("ssm", "get-parameters-by-path"): R_SECRET,
    ("ssm", "get-parameter-history"): R_SECRET,
    ("ssm", "get-command-invocation"): R_DATA,
    ("ssm", "get-inventory"): R_DATA,
    ("secretsmanager", "get-secret-value"): R_SECRET,
    ("secretsmanager", "batch-get-secret-value"): R_SECRET,
    ("ec2", "get-console-screenshot"): R_DATA,
    ("cognito-idp", "list-users"): "returns end-user PII.",
    ("cognito-idp", "list-users-in-group"): "returns end-user PII.",
    ("macie2", "get-sensitive-data-occurrences"): R_DATA,
    ("ecr", "get-download-url-for-layer"): R_DATA,
}

# Generic catch for credential-returning operations that happen to start with "get-".
SECRETISH_OP = re.compile(r"(token|credential|password|secret-value|access-details|private-key)")
SECRETISH_OK = {
    "iam get-credential-report",
    "iam get-account-password-policy",
    "iam list-service-specific-credentials",
}

# Flags that make an otherwise-read call reveal secrets. --debug prints signed request headers,
# including the session token.
DENY_FLAGS = {"--with-decryption", "--include-value", "--include-values", "--debug"}

# Operations whose output carries environment variables / user data. A --query projection is
# required, and it may not select those values (keys(...) of environment maps is fine).
REQUIRE_QUERY = {
    ("lambda", "list-functions"), ("lambda", "get-function"), ("lambda", "get-function-configuration"),
    ("ecs", "describe-task-definition"), ("autoscaling", "describe-launch-configurations"),
    ("ec2", "describe-launch-template-versions"), ("ec2", "get-launch-template-data"),
    ("codebuild", "batch-get-projects"), ("elasticbeanstalk", "describe-configuration-settings"),
    ("apprunner", "describe-service"), ("batch", "describe-job-definitions"),
}

S3API_READ_EXACT = {"list-buckets", "head-bucket", "list-multipart-uploads", "get-public-access-block",
                    "get-object-lock-configuration", "list-directory-buckets"}
STS_READ = {"get-caller-identity", "get-access-key-info", "decode-authorization-message"}
CONFIGURE_GET_OK = {"region", "output", "sso_start_url", "sso_region", "sso_account_id", "sso_role_name",
                    "sso_session", "role_arn", "source_profile", "role_session_name", "mfa_serial"}
NO_PROFILE_OK = {("configure", "list-profiles"), ("configure", "list"), ("configure", "get")}

GLOBAL_VALUE_OPTS = {"--profile", "--region", "--output", "--query", "--endpoint-url", "--ca-bundle",
                     "--color", "--cli-read-timeout", "--cli-connect-timeout", "--cli-binary-format"}

SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "eval", "source", "."}
WRAPPERS = {"env", "time", "sudo", "doas", "nohup", "timeout", "gtimeout", "xargs", "command", "exec", "builtin",
            "watch", "parallel", "nice", "ionice", "stdbuf", "setsid", "unbuffer", "aws-vault", "granted",
            "assume", "leapp"}
# Commands that only display or search text: an "aws" token in their arguments is data, not an invocation.
TEXT_COMMANDS = {"echo", "printf", "grep", "egrep", "fgrep", "rg", "ag", "ack", "cat", "bat", "less", "more", "head",
                 "tail", "sed", "awk", "gawk", "jq", "yq", "ls", "find", "fd", "which", "type", "whereis", "man",
                 "wc", "sort", "uniq", "cut", "tr", "diff", "file", "stat", "basename", "dirname", "realpath",
                 "readlink", "test", "[", "[[", "git", "column", "fold", "nl", "comm"}
SKIP_WORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "time"}
IAC_TOOLS = {"terraform", "tofu", "terragrunt"}
IAC_READ = {"version", "validate", "fmt", "providers", "graph", "help"}
DEPLOY_TOOLS = {"cdk", "sam", "eksctl", "pulumi", "serverless", "sls", "copilot", "amplify", "sst", "awscurl"}
KUBECTL_READ = {"get", "describe", "top", "version", "api-resources", "api-versions", "cluster-info", "explain",
                "events", "logs"}
HELM_READ = {"list", "ls", "status", "history", "version"}
OTHER_TOOLS = IAC_TOOLS | DEPLOY_TOOLS | {"kubectl", "helm"}

# Credential material on disk and in the environment.
CRED_PATH = re.compile(r"(^|[/~\s=\"'])\.aws/(credentials|sso/cache|cli/cache|login/cache)\b|"
                       r"(^|[/~])\.aws/?$")
CRED_ENV = re.compile(r"AWS_(SECRET_ACCESS_KEY|SESSION_TOKEN|SECURITY_TOKEN)")
DYNAMIC = re.compile(r"[$`*?{}\[\]()]")

SEPARATOR_CHARS = set(";&|()\n")
PUNCT = ";&|()<>\n"


# --------------------------------------------------------------------------- helpers

def basename(tok):
    return os.path.basename(tok.rstrip("/")) if tok else ""


def strip_heredocs(cmd, depth, problems):
    """Remove heredoc bodies (documentation text must not trigger the guard) but inspect bodies that are
    fed to a shell or python, since those execute."""
    pat = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?:\n|$)", re.S)

    def repl(m):
        head = cmd[cmd.rfind("\n", 0, m.start()) + 1:m.start()]
        body = m.group(3)
        if re.search(r"(^|[\s;&|(])(ba|z|da|k)?sh(\s|$)", head):
            problems.extend(check_command(body, depth + 1))
        elif re.search(r"\bpython[0-9.]*\b", head) and re.search(r"\b(boto3|botocore)\b", body):
            problems.append("python with boto3/botocore: use the AWS CLI (or scripts/collect.py) so every call "
                            "can be checked.")
        return "<<HEREDOC\n"

    return pat.sub(repl, cmd)


def tokenize(cmd):
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=PUNCT)
    lex.whitespace_split = True
    lex.whitespace = " \t\r"
    lex.commenters = ""
    return list(lex)


def split_segments(tokens):
    segs, cur = [], []
    for t in tokens:
        if t and all(c in PUNCT for c in t) and any(c in SEPARATOR_CHARS for c in t):
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    return segs


def strip_leading(seg):
    """Drop shell keywords and leading VAR=value assignments; return (remaining tokens, assignments)."""
    i, assigns = 0, []
    while i < len(seg) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]) or seg[i] in SKIP_WORDS):
        if "=" in seg[i]:
            assigns.append(seg[i])
        i += 1
    return seg[i:], assigns


# --------------------------------------------------------------------------- checks

def argval(args, name):
    """Value of `--name value` or `--name=value` in an argument list (None if absent)."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return str(args[i + 1])
        if str(a).startswith(name + "="):
            return str(a).split("=", 1)[1]
    return None


def split_s3(uri):
    rest = str(uri)[5:]
    bucket, _, key = rest.partition("/")
    return bucket, key


def is_log_location(bucket, key=""):
    """True for AWS log files: standard AWSLogs/ delivery prefix, or a bucket whose name marks it as a log bucket."""
    return bool(bucket) and ("AWSLogs/" in str(key) or str(key).startswith("AWSLogs") or bool(LOG_BUCKET.search(bucket)))


def check_aws(args, inline_profile=False):
    """Validate the arguments that follow `aws`. Returns a list of problems (empty = allowed)."""
    opts, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("--") and len(a) > 2:
            if "=" in a:
                k, v = a.split("=", 1)
                opts.setdefault(k, []).append(v)
            elif a in GLOBAL_VALUE_OPTS and i + 1 < len(args):
                opts.setdefault(a, []).append(args[i + 1])
                i += 1
            else:
                opts.setdefault(a, []).append(True)
        elif a.startswith("-") and len(a) > 1:
            pass
        else:
            pos.append(a)
        i += 1
    if not pos:
        return []                                   # e.g. `aws --version`
    svc = pos[0]
    op = pos[1] if len(pos) > 1 else None
    if svc == "help" or op == "help":
        return []
    if DYNAMIC.search(svc) or (op and DYNAMIC.search(op)):
        return [f"aws {svc} {op or ''}: service/operation given through a variable, glob or substitution cannot be "
                "verified. Write the literal service and operation."]
    if op is None:
        return [f"aws {svc}: incomplete command (no operation). Write the full read-only operation, or `aws {svc} help`."]
    problems = []
    if "--debug" in opts:
        problems.append("aws --debug prints signed request headers including the session token.")
    if not (inline_profile or "--profile" in opts or (svc, op) in NO_PROFILE_OK):
        problems.append(f"aws {svc} {op}: pass --profile NAME explicitly (or an inline AWS_PROFILE=NAME) so the "
                        "inspected account is never ambient.")
    if svc.startswith("!") or op.startswith("!"):
        return problems + ["AWS CLI alias execution (!) is not allowed."]
    if svc == "configure":
        if op in ("list-profiles", "list"):
            return problems
        if op == "get" and len(pos) > 2 and pos[2] in CONFIGURE_GET_OK:
            return problems
        return problems + ["aws configure: only list-profiles, list and `get` of non-secret keys (region, output, "
                           "sso_*, role_arn, source_profile) are allowed; never read or write credentials."]
    if svc in DENY_SERVICES:
        return problems + [f"aws {svc}: {DENY_SERVICES[svc]}"]
    if svc == "sts":
        if op not in STS_READ:
            problems.append(f"aws sts {op}: only {', '.join(sorted(STS_READ))} are allowed. {R_AUTH}")
        return problems
    if svc == "s3":
        uris = [p for p in pos[2:] if str(p).startswith("s3://")]
        if op == "ls":
            if "--recursive" in opts and not (uris and is_log_location(*split_s3(uris[0]))):
                problems.append("aws s3 ls --recursive lists object keys across a bucket; allowed only for log locations "
                                "(AWSLogs/ prefix or a log bucket). Use storage metrics and bucket configuration otherwise.")
            return problems
        if op in ("cp", "sync"):
            dest = [p for p in pos[2:] if not str(p).startswith("s3://")]
            if len(uris) == 1 and str(pos[2]).startswith("s3://") and dest and is_log_location(*split_s3(uris[0])):
                return problems                    # download of AWS log files to a local path or stdout
            return problems + [f"aws s3 {op}: only downloads of log files (from an AWSLogs/ prefix or a log bucket) to a "
                               "local path are allowed; other object transfers and any write to S3 are not."]
        return problems + [f"aws s3 {op}: only `aws s3 ls` and log-file downloads are allowed. Uploads, moves, presign "
                           "and deletion are not part of a read-only review."]
    if svc == "s3api":
        if op in S3API_READ_EXACT or op.startswith(("get-bucket-", "list-bucket-")):
            return problems
        if op in ("get-object", "head-object", "list-objects", "list-objects-v2", "list-object-versions"):
            where = argval(args, "--key") or argval(args, "--prefix") or ""
            if is_log_location(argval(args, "--bucket") or "", where):
                return problems
            return problems + [f"aws s3api {op}: object reads and listings are allowed only for log locations "
                               "(AWSLogs/ prefix or a log bucket); other objects are application data."]
        return problems + [f"aws s3api {op}: object-level and write operations are not allowed. Bucket configuration "
                           "(get-bucket-*, list-bucket-*, get-public-access-block, list-buckets) and log files are."]
    key = f"{svc} {op}"
    if (svc, op) in DENY_OPS:
        problems.append(f"aws {key}: {DENY_OPS[(svc, op)]}")
    elif SECRETISH_OP.search(op) and key not in SECRETISH_OK:
        problems.append(f"aws {key}: {R_SECRET}")
    elif not (op.startswith(READ_PREFIXES) or key in EXTRA_READ):
        problems.append(f"aws {key}: not a recognised read-only operation (allowed prefixes: "
                        f"{', '.join(READ_PREFIXES)}). This skill never creates, modifies, deletes, starts, stops, "
                        "invokes or otherwise changes anything.")
    for flag in sorted((DENY_FLAGS - {"--debug"}) & set(opts)):
        problems.append(f"aws {key} {flag}: reveals secret values.")
    if key == "ec2 describe-instance-attribute" and re.search(r"user-?data", " ".join(map(str, args)), re.I):
        problems.append("aws ec2 describe-instance-attribute userData: user data frequently contains secrets.")
    if key in ("glue get-connection", "glue get-connections") and "--hide-password" not in opts:
        problems.append(f"aws {key}: add --hide-password.")
    if (svc, op) in REQUIRE_QUERY:
        queries = [str(q) for q in opts.get("--query", []) if q is not True]
        if not queries:
            problems.append(f"aws {key}: output can contain environment variables or user data. Add a --query "
                            "projection that selects names/settings only (never Environment.Variables values, "
                            "environment[].value or UserData).")
        for q in queries:
            rest = re.sub(r"keys\([^()]*\)", "", q).lower()      # keys(...) of a map is allowed
            if "userdata" in rest or "environment" in rest or "variables" in rest:
                problems.append(f"aws {key}: --query selects environment variables or user data; project "
                                "keys(...) of the map or other non-secret fields instead.")
    return problems


def check_other_tool(name, args):
    non_opt = [a for a in args if not a.startswith("-")]
    sub = non_opt[0] if non_opt else None
    if name in IAC_TOOLS:
        if sub is None or sub in IAC_READ or any(a in ("-version", "--version", "-help", "-h", "--help") for a in args):
            return []
        return [f"{name} {sub}: infrastructure-as-code commands can lock/refresh/modify state or infrastructure. "
                "Read the .tf/.hcl source with the Read tool instead, or ask the user for plan output."]
    if name in DEPLOY_TOOLS:
        if any(a in ("--version", "-v", "version", "--help", "-h", "help") for a in args):
            return []
        return [f"{name}: deployment/provisioning tooling is not allowed in a read-only review."]
    if name == "kubectl":
        if sub in KUBECTL_READ:
            return ["kubectl: reading Secrets is not allowed."] if any("secret" in a.lower() for a in args) else []
        if sub == "config" and len(non_opt) > 1 and non_opt[1] in ("current-context", "get-contexts"):
            return []
        return [f"kubectl {sub}: only read verbs ({', '.join(sorted(KUBECTL_READ))}) are allowed; no exec, "
                "port-forward or mutations."]
    if name == "helm":
        return [] if sub is None or sub in HELM_READ else [f"helm {sub}: only {', '.join(sorted(HELM_READ))} are allowed."]
    return []


def check_credentials(seg, assigns, cw):
    problems = []
    if any(CRED_PATH.search(t) for t in seg):
        problems.append("credential, SSO-token or CLI-cache files under ~/.aws must not be read or listed.")
    if any(CRED_ENV.search(t) for t in seg + assigns):
        problems.append("AWS secret/session environment variables must not be read, printed or set.")
    rest = [t for t in seg[1:] if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)]
    if (cw in ("env", "printenv") and not [t for t in rest if not t.startswith("-")]) or \
            (cw == "export" and (not rest or rest == ["-p"])) or (cw == "set" and not rest) or \
            (cw == "declare" and rest and set(rest) <= {"-p", "-x", "-px", "-xp"}):
        problems.append(f"`{cw}` without arguments dumps the environment, which can contain AWS credentials.")
    return problems


def check_segment(seg, depth):
    seg, assigns = strip_leading(seg)
    if not seg:
        return []
    cw = basename(seg[0])
    problems = check_credentials(seg, assigns, cw)
    if cw.startswith("python") and re.search(r"\b(boto3|botocore)\b", " ".join(seg)):
        problems.append("python with boto3/botocore: use the AWS CLI (or scripts/collect.py) so every call can be "
                        "checked.")
    if cw in SHELLS or cw.endswith(".sh"):
        for tok in seg[1:]:
            if re.search(r"\s", tok):
                problems.extend(check_command(tok, depth + 1))
        cand = seg[0] if cw.endswith(".sh") else next((t for t in seg[1:] if not t.startswith("-")), None)
        if cand and cw != "eval" and os.path.isfile(cand) and os.path.getsize(cand) < 200_000:
            try:
                with open(cand, "r", errors="replace") as fh:
                    problems.extend(check_command(fh.read(), depth + 1))
            except OSError:
                pass
        if cw == "eval":
            problems.extend(check_command(" ".join(seg[1:]), depth + 1))
    if cw in TEXT_COMMANDS:
        return problems
    # An `aws` (or IaC/cluster tool) token anywhere in a non-text command is an invocation: this covers wrappers
    # (env, xargs, aws-vault exec) and shell functions (`run out.json aws ec2 ...`).
    for j, tok in enumerate(seg):
        b = basename(tok)
        if b == "aws":
            inline = any(re.match(r"^AWS_PROFILE=\S+", t) for t in assigns + seg[:j])
            return problems + check_aws(seg[j + 1:], inline_profile=inline)
        if b in OTHER_TOOLS:
            return problems + check_other_tool(b, seg[j + 1:])
    return problems


def check_command(cmd, depth=0):
    if depth > 4:
        return ["command nesting is too deep to verify."]
    problems = []
    cmd = cmd.replace("\\\n", " ")
    cmd = strip_heredocs(cmd, depth, problems)
    for sub in re.findall(r"\$\(([^()]*)\)", cmd) + re.findall(r"`([^`]*)`", cmd):
        problems.extend(check_command(sub, depth + 1))
    try:
        segments = split_segments(tokenize(cmd))
    except ValueError:
        if re.search(r"(^|[\s;&|(`])aws(\s|$)", cmd):
            problems.append("could not parse this command safely (unbalanced quotes?). Simplify it.")
        return problems
    for seg in segments:
        problems.extend(check_segment(seg, depth))
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def check_file_tool(tool_input):
    """Read/Grep/Glob: block credential and token caches; ~/.aws/config stays readable."""
    for k in ("file_path", "path", "pattern", "glob"):
        v = tool_input.get(k)
        if isinstance(v, str) and CRED_PATH.search(v):
            return ["credential, SSO-token or CLI-cache files under ~/.aws must not be read or searched "
                    "(~/.aws/config is fine)."]
    return []


# --------------------------------------------------------------------------- entry points

P = "--profile p"
SELF_TESTS = [
    # (command, should_block)
    ("aws configure list-profiles", False),
    (f"aws sts get-caller-identity {P}", False),
    (f"aws ec2 describe-instances {P} --region us-east-1 --output json > out.json", False),
    ("aws --profile p --region eu-west-1 rds describe-db-instances", False),
    ("aws --profile=p ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-11-01 --granularity MONTHLY --metrics UnblendedCost", False),
    ("AWS_PROFILE=p aws ec2 describe-vpcs", False),
    ("TZ=UTC aws ecs describe-services --cluster c --services s --profile p --region r", False),
    ("TZ=UTC aws ec2 stop-instances --instance-ids i-1 --profile p", True),
    ("env AWS_PROFILE=p aws ec2 describe-vpcs", False),
    (f"aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization {P}", False),
    (f"aws s3api get-bucket-policy --bucket b {P}", False),
    (f"aws s3 ls {P}", False),
    (f"aws iam get-credential-report {P}", False),
    (f"aws iam get-account-password-policy {P}", False),
    (f"aws lambda list-functions {P} --query 'Functions[].{{N:FunctionName,M:MemorySize}}'", False),
    (f"aws lambda list-functions {P} --query 'Functions[].{{N:FunctionName,K:keys(Environment.Variables || `{{}}`)}}'", False),
    (f"aws lambda get-function-configuration --function-name f {P} --query 'keys(Environment.Variables)'", False),
    ("aws configure get region --profile p", False),
    ("aws ec2 help", False),
    ("aws --version", False),
    (f"for r in us-east-1 eu-west-1; do aws ec2 describe-instances --region $r {P}; done", False),
    ("for p in $(aws configure list-profiles); do aws sts get-caller-identity --profile $p; done", False),
    (f"aws ec2 describe-regions {P} | jq '.Regions[].RegionName'", False),
    (f"aws configservice select-resource-config --expression 'SELECT resourceId' {P}", False),
    ("grep -rn aws reports/ docs/", False),
    ("grep -n aws a.md b.md", False),
    ("cat ~/.aws/config", False),
    ("ls -la && git status", False),
    ("cat > f.md <<'EOF'\naws ec2 terminate-instances --instance-ids i-1\nEOF", False),
    ("terraform validate", False),
    ("kubectl get nodes -o wide", False),
    ("echo hello", False),
    ("python3 -I .claude/skills/aws-well-architected-review/scripts/collect.py --profile p --regions eu-west-1", False),
    (f"aws stepfunctions describe-state-machine --state-machine-arn x {P}", False),
    # --- logs are readable (architecture reviews need them)
    (f"aws logs get-log-events --log-group-name g --log-stream-name s {P}", False),
    (f"aws logs tail /aws/lambda/x --since 1h {P}", False),
    (f"aws logs filter-log-events --log-group-name g --filter-pattern ERROR --start-time 1 {P}", False),
    (f"aws logs start-query --log-group-name g --start-time 1 --end-time 2 --query-string 'fields @message' {P}", False),
    (f"aws logs get-query-results --query-id q {P}", False),
    (f"TZ=UTC aws logs filter-log-events --log-group-name /msk/x --log-stream-names s --filter-pattern '\"ERROR\"' {P}", False),
    (f"aws stepfunctions get-execution-history --execution-arn x {P}", False),
    (f"aws stepfunctions describe-execution --execution-arn x {P}", False),
    (f"aws rds download-db-log-file-portion --db-instance-identifier d --log-file-name error/postgresql.log {P}", False),
    (f"aws ec2 get-console-output --instance-id i-1 {P}", False),
    ("kubectl logs deploy/api -n prod --since=1h", False),
    (f"aws s3 ls s3://acme-alb-logs/AWSLogs/123456789012/ --recursive {P}", False),
    (f"aws s3 cp s3://acme-data/AWSLogs/123456789012/elasticloadbalancing/x.log.gz . {P}", False),
    (f"aws s3 cp s3://company-cloudtrail/AWSLogs/1/CloudTrail/a.json.gz - {P}", False),
    (f"aws s3api get-object --bucket acme-access-logs --key 2026/11/12/x.log out.log {P}", False),
    (f"aws s3api list-objects-v2 --bucket b --prefix AWSLogs/1/vpcflowlogs/ {P}", False),
    # --- must be blocked
    (f"aws ec2 get-console-screenshot --instance-id i-1 {P}", True),
    (f"aws logs delete-log-group --log-group-name g {P}", True),
    (f"aws logs put-retention-policy --log-group-name g --retention-in-days 1 {P}", True),
    (f"aws s3 cp s3://product-catalog/data.csv . {P}", True),     # "catalog" is not a log bucket
    (f"aws s3 cp s3://acme-logs/AWSLogs/x.gz s3://other/x.gz {P}", True),
    (f"aws s3 cp ./x.log s3://acme-logs/AWSLogs/x.log {P}", True),
    (f"aws s3 rm s3://acme-logs/AWSLogs/x.log {P}", True),
    (f"aws s3api get-object --bucket tenant-data --key exports/a.csv out {P}", True),
    (f"aws s3api list-objects-v2 --bucket tenant-data {P}", True),
    (f"aws s3api put-object --bucket acme-logs --key AWSLogs/x {P}", True),
    (f"aws ec2 terminate-instances --instance-ids i-123 {P}", True),
    (f"aws ec2 stop-instances --instance-ids i-123 {P}", True),
    ("aws ec2 describe-instances", True),                       # no --profile
    ("aws sts get-caller-identity", True),                      # no --profile
    (f"aws --debug ec2 describe-vpcs {P}", True),
    ("aws login", True),
    (f"aws login {P}", True),
    (f"aws ec2 {P}", True),                                     # incomplete
    (f"SVC=ec2; aws $SVC delete-vpc {P}", True),                # dynamic service
    (f"aws ec2 $OP {P}", True),                                 # dynamic operation
    (f"run() {{ \"$@\"; }}; run out.json aws ec2 delete-vpc --vpc-id v {P}", True),
    (f"aws s3 rm s3://bucket --recursive {P}", True),
    (f"aws s3 cp s3://a/b . {P}", True),
    (f"aws s3 ls s3://bucket --recursive {P}", True),
    (f"aws s3api get-object --bucket b --key k out {P}", True),
    (f"aws s3api put-bucket-policy --bucket b --policy file://p.json {P}", True),
    (f"aws iam attach-role-policy --role-name r --policy-arn x {P}", True),
    (f"aws iam generate-credential-report {P}", True),
    (f"aws sts assume-role --role-arn x --role-session-name s {P}", True),
    (f"aws sts get-session-token {P}", True),
    ("aws sso login --profile p", True),
    (f"aws secretsmanager get-secret-value --secret-id s {P}", True),
    (f"aws ssm get-parameter --name /x --with-decryption {P}", True),
    (f"aws ssm start-session --target i-1 {P}", True),
    (f"aws ec2 get-password-data --instance-id i-1 {P}", True),
    (f"aws ecr get-login-password {P}", True),
    (f"aws eks get-token --cluster-name c {P}", True),
    (f"aws eks update-kubeconfig --name c {P}", True),
    (f"aws dynamodb scan --table-name t {P}", True),
    (f"aws dynamodb get-item --table-name t --key '{{}}' {P}", True),
    (f"aws lambda invoke --function-name f out.json {P}", True),
    (f"aws lambda list-functions {P}", True),
    (f"aws lambda get-function-configuration --function-name f {P} --query 'Environment.Variables'", True),
    (f"aws lambda list-functions {P} --query '{{a:keys(Environment.Variables),b:Functions[].Environment.Variables}}'", True),
    (f"aws ecs describe-task-definition --task-definition t {P}", True),
    (f"aws ec2 get-launch-template-data --instance-id i-1 {P}", True),
    (f"aws stepfunctions get-activity-task --activity-arn x {P}", True),
    (f"aws sqs receive-message --queue-url q {P}", True),
    (f"aws apigateway get-api-keys --include-values {P}", True),
    (f"aws cloudformation delete-stack --stack-name s {P}", True),
    (f"aws cloudformation detect-stack-drift --stack-name s {P}", True),
    ("aws configure set aws_access_key_id AKIA --profile p", True),
    ("aws configure get aws_secret_access_key --profile p", True),
    ("aws configure", True),
    ("terraform apply -auto-approve", True),
    ("tofu destroy", True),
    ("cdk deploy", True),
    ("kubectl delete pod x", True),
    ("kubectl get secrets -A", True),
    (f"aws ec2 describe-instances {P} && aws ec2 delete-vpc --vpc-id v {P}", True),
    (f"x=$(aws ec2 delete-vpc --vpc-id v {P})", True),
    (f"echo \"$(aws ec2 delete-vpc --vpc-id v {P})\"", True),
    (f"bash -c 'aws ec2 delete-vpc --vpc-id v {P}'", True),
    ("env AWS_PROFILE=p aws ec2 delete-vpc --vpc-id v", True),
    ("aws-vault exec p -- aws ec2 delete-vpc --vpc-id v --profile p", True),
    (f"for r in a b; do aws ec2 delete-vpc --region $r {P}; done", True),
    (f"aws ec2 describe-instances {P} | xargs -n1 aws ec2 terminate-instances {P} --instance-ids", True),
    (f"bash <<EOF\naws ec2 delete-vpc --vpc-id v {P}\nEOF", True),
    ("python3 -c 'import boto3; boto3.client(\"ec2\").terminate_instances(InstanceIds=[])'", True),
    (f"aws ec2 describe-instances {P}\naws ec2 delete-vpc --vpc-id v {P}", True),
    ("cat ~/.aws/credentials", True),
    ("ls ~/.aws/sso/cache", True),
    ("grep -r token /home/u/.aws/cli/cache", True),
    ("env", True),
    ("printenv", True),
    ("env | grep AWS", True),
    ("echo $AWS_SECRET_ACCESS_KEY", True),
    ("printenv AWS_SESSION_TOKEN", True),
]

SELF_TESTS_FILE_TOOLS = [
    ({"file_path": "/home/u/.aws/config"}, False),
    ({"file_path": "/home/u/project/README.md"}, False),
    ({"file_path": "/home/u/.aws/credentials"}, True),
    ({"path": "/home/u/.aws/sso/cache"}, True),
    ({"path": "/home/u/.aws", "pattern": "aws_secret"}, True),
    ({"pattern": "~/.aws/cli/cache/*.json"}, True),
]


def self_test():
    failures, total = 0, 0
    for cmd, should_block in SELF_TESTS:
        blocked = bool(check_command(cmd))
        ok = blocked == should_block
        failures += not ok
        total += 1
        print(f"{'PASS' if ok else 'FAIL'}  {'BLOCK' if blocked else 'allow'}  {cmd!r}")
    for ti, should_block in SELF_TESTS_FILE_TOOLS:
        blocked = bool(check_file_tool(ti))
        ok = blocked == should_block
        failures += not ok
        total += 1
        print(f"{'PASS' if ok else 'FAIL'}  {'BLOCK' if blocked else 'allow'}  file-tool {ti!r}")
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    try:
        data = json.load(sys.stdin)
        tool = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
        if tool == "Bash":
            problems = check_command(tool_input.get("command") or "")
        elif tool in ("Read", "Grep", "Glob"):
            problems = check_file_tool(tool_input)
        else:
            return 0
    except Exception as exc:  # fail closed: a broken guard must not silently allow
        sys.stderr.write(f"BLOCKED by aws-well-architected-review read-only guard: guard error ({exc}).\n")
        return 2
    if problems:
        sys.stderr.write("BLOCKED by aws-well-architected-review read-only guard. This skill is strictly read-only.\n")
        for p in problems:
            sys.stderr.write(f"  - {p}\n")
        sys.stderr.write("Do not retry a variant of this command. If the information is essential, tell the user "
                         "what you need and why, and let them decide or run it themselves.\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
