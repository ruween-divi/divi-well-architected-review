# Assessment Methodology

How to inspect an AWS environment safely and gather evidence. `SKILL.md` defines the workflow; this file holds the
detail: command contract, discovery commands, inventory catalogue, metric collection, cost data sources, permission
handling and evidence rules.

Contents: 0 Automated collection · 1 Command contract · 2 Sensitive data · 3 Account & region discovery · 4 Permission handling ·
5 Workload discovery · 6 Inventory catalogue · 7 Metrics · 8 Cost & advisory data · 9 Staging large environments ·
9a Multi-account acceleration · 10 Evidence records · 11 Validating against AWS documentation · 12 Documentation index

---

## 0. Automated collection (`collect.py` → `digest.py`)

Broad inventory is collected by a script, not by hundreds of hand-typed calls: it is faster, cheaper in context, identical between runs
(so reviews are comparable over time), and it produces the access ledger automatically. Hand-written calls are for **targeted** follow-up (§6, Phase 3).

### 0.1 What the collector does
- One **profile per run**. First `sts get-caller-identity`; with `--expect-account` it aborts (exit 3) if the profile resolves to another account; expired/missing credentials abort (exit 4).
- **Global stage** (IAM summary, password policy, existing credential report, authorization details, OIDC/SAML providers, Organizations, S3 account + per-bucket configuration, CloudFront, Route 53, CloudFront-scope WAF, previous-generation instance types), then a **regional stage** per region in parallel: networking, compute, ASG, load balancers + target health, ECS/EKS (+ version lifecycle), Lambda (+ event source mappings), RDS/Aurora (+ engine lifecycle dates), DynamoDB, ElastiCache, EFS, SQS (attributes), SNS, EventBridge, API Gateway, CloudTrail (+ status), Config, GuardDuty, Security Hub, Access Analyzer, KMS (+ rotation), Secrets Manager metadata, SSM fleet, ACM, alarms, log groups, AWS Backup, CloudFormation stacks.
- `--with-metrics`: CloudWatch `get-metric-data`, **daily** Average/Maximum/Sum over `--metrics-days` (default 30) for EC2, RDS, NAT, ALB/NLB, Lambda, ElastiCache. `--with-cost`: Cost Explorer (by service/region/account/usage type, Savings Plans/RI coverage and utilisation — about 10 billed requests), Compute Optimizer summaries, Trusted Advisor recommendations.
- **Every call is validated with the guard's `check_aws()` policy before it runs**; secret-bearing APIs use projections (e.g. Lambda environment *keys* only); role session names (often e-mail addresses) and access key IDs are redacted from saved output and the ledger. Throttling is retried with backoff. Per-resource follow-ups are capped (`--max-per-type`, `--max-buckets`) and caps are recorded.

### 0.2 Running it
```bash
python3 -I .claude/skills/aws-well-architected-review/scripts/collect.py --profile NAME --expect-account 123456789012 \
  --regions eu-west-1,us-east-1 --out <scratchpad>/aws-wa/<YYYY-MM-DD>-<alias> --with-metrics --with-cost
python3 -I .claude/skills/aws-well-architected-review/scripts/collect.py ... --dry-run     # print + policy-check the plan; calls nothing
python3 -I .claude/skills/aws-well-architected-review/scripts/digest.py <evidence-dir>    # writes digest.md / digest.json
```
Use the session scratchpad (or `${TMPDIR:-/tmp}/aws-wa-…`) for `--out`, never `reports/`. A run takes from under a minute (small account, two regions) to tens of minutes (hundreds of resources, many regions): use a long tool timeout or run in the background. Run once per account; re-run instead of patching evidence by hand.
Layout: `manifest.json` (identity, options, counts, caps), `ledger.json` (status per call: ok · absent = "not configured" · denied · error · auth), `global/*.json`, `<region>/*.json` (`<service>.<operation>[.<resource>].json`). Absent/denied files contain `{"_absent": code}` / `{"_error": {...}}`.

### 0.3 Reading the digest
`digest.md` lists coverage (calls by status, denied APIs, caps), inventory, **"Examine first"** signals, signals by pillar with a *check* hint and a reference, and context tables (detective-control matrix, backup coverage, spend, commitments, Compute Optimizer).
Signals are **mechanical facts** (e.g. `SEC-01` public IP + world-open SSH; `NET-07` zonal NAT serving other AZs; `INT-02` SQS visibility < 6× consumer timeout; `DB-08` engine past end of standard support per the RDS lifecycle API).
They are not findings: interpret each against workload context and intent, and cite the signal ID in the finding's *Detected by* field. Drill into raw files when needed, e.g.
`jq '.[] | select(.Public==true)' <dir>/eu-west-1/rds.describe-db-instances.json`. Absence of a signal where coverage was partial proves nothing.

### 0.4 Not covered by the collector (inspect manually in Phase 3 when relevant)
Route 53 record sets and failover/health-check wiring · CloudFront behaviours, cache policies, origin access control · ALB listener rules and TLS policies · API Gateway stages, throttling, authorizers · Step Functions, EventBridge targets, SNS subscriptions ·
Kinesis, MSK, Amazon MQ, OpenSearch, Redshift detail · ECS task definitions (projected!) and EKS in-cluster state (`kubectl` read verbs, only with a user-confirmed context) · RDS parameter groups and proxies · DynamoDB auto scaling and capacity metrics · EBS per-volume metrics ·
S3 storage metrics and Storage Lens · VPC endpoint policies, Transit Gateway route tables, VPN/Direct Connect · SCPs and delegated administrators · Security Hub/GuardDuty/Access Analyzer/Inspector **findings** and Config rule compliance · WAF rules, Shield · Backup/restore **jobs** (restore-test evidence) ·
Service Quotas · Health events · X-Ray service graph · Well-Architected Tool workloads · CloudTrail event history · ECR, CodePipeline/CodeBuild · memory/disk metrics (CloudWatch agent `CWAgent` namespace) · IAM last-accessed data (requires a *generate* call: the user's decision).

### 0.5 Extending it
Add a tuple to `GLOBAL_CALLS`/`REGIONAL_CALLS` (or a follow-up in `region_stage`) and a signal in `digest.py`. The policy check rejects anything that is not read-only; secret-bearing APIs must have a projection (the guard's `REQUIRE_QUERY`). Re-run `--dry-run` and `readonly-guard.py --self-test`.

## 1. Command contract

Every AWS call must satisfy all of these.

1. **Read-only operations only.** The operation name starts with `describe-`, `list-`, `get-`, `lookup-` or
   `batch-get-`, or is on the short extra-read list in `scripts/readonly-guard.py` (e.g. `configservice select-resource-config`; note the CLI names AWS Config `configservice` and CodeDeploy `deploy`).
   If you are unsure whether an operation is read-only, do not run it: check `aws <service> <operation> help` (offline) and
   the API reference first. "Harmless" writes (tagging, starting a report, refreshing a check, invoking a function,
   generating a credential report) are still writes.
2. **Explicit identity on every call.** Always pass `--profile NAME` and `--region REGION` (global services: see §3).
   Never rely on ambient `AWS_PROFILE` or default region, which is how the wrong account gets inspected. The guard rejects
   AWS calls without `--profile` (or an inline `AWS_PROFILE=NAME`), and rejects service/operation names passed through variables.
3. **Predictable output.** Add `--output json --no-cli-pager`. Use `--query` (JMESPath) to project only the fields you need;
   this keeps context small and avoids pulling secrets (§2).
4. **Raw output stays out of the project.** Save large raw output to the session scratchpad (or
   `${TMPDIR:-/tmp}/aws-wa-review-<timestamp>/` if none), never into `reports/`. Reports contain conclusions and
   minimal, redacted evidence only.
5. **Be gentle with the API.** Loop over regions/resources sequentially; on `Throttling`/`RequestLimitExceeded`
   back off (sleep, then retry once or twice) and reduce the page size (`--page-size`) rather than hammering.
   Cost Explorer calls are billed per request: plan a small number of well-grouped queries.
6. **Metadata, metrics and logs, not application data.** Inspect configuration, tags, metrics, relationships and logs. Do not
   read table rows, queue messages, parameter values, secrets, or S3 objects other than log files. Logs are in scope (§2.1).
7. **No credential handling.** Never ask for, print, store or transmit keys, tokens or session credentials. Never run
   `aws sso login`, `aws login`, `sts assume-role`, `sts get-session-token` or `aws configure set`; never use `--debug` (it prints
   signed headers including the session token); never read `~/.aws/credentials`, `~/.aws/sso/cache`, `~/.aws/cli/cache` or dump the
   environment (`env`, `printenv`). `~/.aws/config` is fine. Expired session → stop and ask the user to refresh it.
8. **UTC timestamps.** The AWS CLI prints epoch-based timestamps (CloudWatch, ECS, Lambda, Secrets Manager, …) in the machine's *local* time
   zone, for example `2026-10-29T05:30:00+05:30`, while query-protocol services such as RDS print UTC. Prefix ad-hoc commands with `TZ=UTC`
   (`TZ=UTC aws cloudwatch get-metric-data … --profile NAME --region R`; `collect.py` already does this). When parsing saved output, honour the
   offset and convert to UTC; never take the hour from the string's digits. Day-level dates are rarely affected; hour-of-day analysis always is.

The `PreToolUse` guard in `scripts/readonly-guard.py` enforces most of this mechanically and blocks the rest of the
unsafe set (IaC `apply`/`destroy`, `kubectl` mutations, `terraform`/`cdk`/`sam` etc.). If it blocks a command, do not
rephrase it to get around the block: either choose a read-only alternative, or tell the user what you need and why.

Cross-account note: if a profile uses a role chain (`role_arn` + `source_profile`), the CLI assumes the role for you;
that is fine, but never call `sts assume-role` directly.

## 2. Sensitive data handling

Some read APIs return secrets as part of ordinary configuration. Assume any of the following may contain credentials
and **never print them into the report, the findings register or your summaries**. Record only that a secret appears
to be hardcoded (name, location, type), with the value redacted.

| Source | Risk | Safe way to inspect |
|---|---|---|
| Lambda `list-functions` / `get-function-configuration` | `Environment.Variables` values | `--query` with `keys(Environment.Variables)` or omit environment |
| ECS `describe-task-definition` | `containerDefinitions[].environment[].value` | project `name`, `valueFrom` presence, and `environment[].name` only |
| EC2 launch templates / launch configurations / `describe-instance-attribute` | `UserData` | project `LaunchTemplateData.{InstanceType,ImageId,...}` without `UserData`; never decode user data |
| CodeBuild, Elastic Beanstalk, App Runner, Batch job definitions | environment variables | project names only |
| CloudFormation `get-template`, `describe-stacks` | hardcoded secrets in templates, parameters | read structure only; flag, do not quote |
| SSM Parameter Store | plaintext `String` parameters holding secrets | `ssm describe-parameters` (name, type, tier); never `get-parameter*` |
| Secrets Manager | secret values | `list-secrets` / `describe-secret` (rotation, KMS key, last accessed) only |
| API Gateway API keys | key values | never `--include-values` |
| Cognito, Identity Store | end-user PII | pool/store configuration only |
| CloudWatch Logs / X-Ray / VPC Flow Logs / S3 access logs | request payloads, PII, occasionally credentials | readable (§2.1); keep raw output in the scratchpad, quote redacted excerpts only |
| Reports in `reports/` | account IDs, ARNs, topology | treat as confidential; redact before sharing outside the team |

IAM credential report and account authorization details contain user names and key ages but no secrets; they are fine to read.
Keep personal data (employee names, e-mail addresses) out of the report unless essential to a finding.

### 2.1 Reading logs

Logs are primary evidence in an architecture review: why a task stopped, why a pipeline failed, what errors users hit, who
calls what. Read them whenever metrics and configuration cannot answer the question; no separate approval is needed.

| Source | Read-only command (always `--profile`, `--region`, and `TZ=UTC`) |
|---|---|
| CloudWatch Logs, targeted | `aws logs filter-log-events --log-group-name G [--log-stream-names S] --start-time MS --end-time MS --filter-pattern '"ERROR"'` |
| CloudWatch Logs Insights | `aws logs start-query --log-group-name G --start-time S --end-time E --query-string 'fields @timestamp, @message \| filter @message like /ERROR/ \| limit 50'`, then `aws logs get-query-results --query-id ID` (billed per GB scanned: keep the window tight) |
| Recent events | `aws logs tail G --since 1h [--filter-pattern P]`; `aws logs get-log-events` for one stream |
| Step Functions failures | `aws stepfunctions list-executions --status-filter FAILED`, then `get-execution-history --execution-arn A --reverse-order --max-items 20` (error and cause) |
| ECS task failures | `aws ecs describe-tasks` (stoppedReason, exit codes), then the task's awslogs group |
| RDS engine logs | `aws rds describe-db-log-files`, then `download-db-log-file-portion --log-file-name F --starting-token 0` |
| EC2 boot / system log | `aws ec2 get-console-output --instance-id I --latest` |
| EKS workloads | `kubectl logs deploy/NAME -n NS --since=1h` |
| S3-delivered logs (ALB, CloudFront, S3 access, CloudTrail, VPC Flow Logs) | `aws s3 ls s3://BUCKET/AWSLogs/ACCOUNT/ --recursive`, then `aws s3 cp s3://BUCKET/AWSLogs/…/file.gz SCRATCHPAD/` (the guard allows objects under `AWSLogs/` or in a bucket whose name marks it as a log bucket) |

**Handling:**
- **Narrow first:** filter patterns, short windows, one stream. Widen only if the cause is not in view.
- **Raw output** goes to the scratchpad.
- **Reports and chat** quote only the lines a finding needs: timestamps in UTC, exception headlines, status codes, counts.
- **Redact** credentials, tokens, connection strings, personal data (names, e-mail addresses, customer identifiers) and record payloads before quoting.
- **Appendix B** records each source, window and filter, so the read can be repeated.
- If a log shows a **credential in plain text**, report its location and type as a finding (never the value) and recommend rotation.

## 3. Account and region discovery

### 3.1 Profiles and identity

```bash
aws configure list-profiles
aws configure get region --profile NAME                  # default region of the profile (not the full region list)
aws sts get-caller-identity --profile NAME --output json
aws iam list-account-aliases --profile NAME --output json
aws organizations describe-account --account-id ACCOUNT_ID --profile NAME   # name, email domain, status; org member accounts only
aws organizations list-parents --child-id ACCOUNT_ID --profile NAME         # OU/root placement, hints at environment
```

Record in the review: account ID, alias (or `none`), profile, identity ARN and type (SSO permission set / assumed role /
IAM user), the role's apparent privilege level, default region, UTC inspection timestamp (`date -u +%Y-%m-%dT%H:%M:%SZ`),
and environment (from the user; otherwise OU name / tags, marked **inferred**).

Privilege-level hint from the ARN: `AWSReservedSSO_<PermissionSet>_*` → permission set name. Names such as
`AdministratorAccess`, `PowerUser`, `*Admin*` mean the session *can* write. Warn the user once, recommend a
`ReadOnlyAccess`/`ViewOnlyAccess`/`SecurityAudit`-style role, and proceed read-only only if they accept. A root or IAM-user
identity with long-lived keys is itself a finding to note, not to act on.

**Expired credentials.** Error text such as `Token has expired`, `ExpiredToken`, `ExpiredTokenException`,
`The SSO session associated with this profile has expired or is invalid`, `Error loading SSO Token`, or
`InvalidClientTokenId`: stop. Tell the user to run `aws sso login --profile NAME` in their own terminal and say when done.
Do not attempt the login yourself and do not continue with other profiles' data as a substitute.

### 3.2 Regions

Never assume one region. Build the region list in this order and state which method you used:

1. **Ask the user** which regions are in scope (and note regions known to be unused or prohibited by policy).
2. **Enabled regions**: `aws account list-regions --region-opt-status-contains ENABLED ENABLED_BY_DEFAULT --profile NAME`
   (needs `account:ListRegions`), or `aws ec2 describe-regions --profile NAME --region <home-region>` (returns enabled regions by default).
3. **Where is spend/activity?** One Cost Explorer call grouped by region over the last 30–60 days is the cheapest reliable breadth signal:
   ```bash
   aws ce get-cost-and-usage --profile NAME --region us-east-1 \
     --time-period Start=YYYY-MM-01,End=YYYY-MM-DD --granularity MONTHLY --metrics UnblendedCost \
     --group-by Type=DIMENSION,Key=REGION
   ```
4. **Cross-check with resource probes** for regions that show spend or that the user listed (e.g. instance, RDS, EKS, Lambda, NAT counts).
   Optionally use AWS Resource Explorer (`resource-explorer-2 search`) or tagged resources
   (`resourcegroupstaggingapi get-resources`) if enabled; both miss untagged/unindexed resources, so treat them as hints.
5. Regions with Config recorders, GuardDuty detectors or CloudTrail trails but no workloads are still in scope for the **security/governance** checks.

Regions with unexpected activity in a region the organisation does not use is a security observation (possible shadow IT or
compromise); report as MEDIUM/INFO pending explanation, not as confirmed misuse.

Global/home-region services are queried once, in their home region: IAM, Organizations, Route 53, CloudFront, Global Accelerator
(us-west-2), WAF for CloudFront (`--scope CLOUDFRONT --region us-east-1`), ACM certificates for CloudFront (us-east-1),
Cost Explorer / Budgets / Pricing / Trusted Advisor / Health (us-east-1 endpoints), S3 bucket listing (global) with per-bucket
region from `get-bucket-location`.

## 4. Permission handling

Missing permission or an un-enabled service is **not** a misconfiguration. Maintain a running **access ledger**
(kept in the draft review under "Assessment Limitations"):

| Area | API / call | Result (AccessDenied / OptInRequired / NotSubscribed / Throttled / NotEnabled) | Assessment impact |
|---|---|---|---|

Typical signals: `AccessDenied`, `AccessDeniedException`, `UnauthorizedOperation`, `AuthorizationError`,
`OptInRequired`, `SubscriptionRequiredException` (e.g. Trusted Advisor needs a qualifying support plan), `AuthFailure`
for a disabled region, `Compute Optimizer is not enrolled`. An explicit-deny SCP looks the same as a missing permission.

Rules: record it once per area (not once per region), say which findings/pillar coverage are affected, continue with other
sources, mark dependent conclusions as **Low confidence** or "not assessed", and list the exact permission (e.g.
`ce:GetCostAndUsage`) that would close the gap. Never infer "no GuardDuty" from AccessDenied; infer it only from a successful
call that returns no detectors.

## 5. Workload discovery

Goal: understand *what the system is for* before judging its parts. Build a resource graph and label every edge
**Confirmed** (an API field or runtime signal says so) or **Inferred** (naming, tags or co-location suggest it).

| Question | Evidence sources |
|---|---|
| What are the workloads / applications? | tags (`Application`, `Project`, `Service`, `Environment`, `Owner`, `CostCenter`), CloudFormation stack names and tags (`aws:cloudformation:stack-name`), Terraform-style tags, resource name prefixes, ECS services, EKS namespaces (if kubectl context supplied), Lambda names, Route 53 record names, CloudFront aliases |
| How does traffic enter? | Route 53 alias targets → CloudFront (`list-distributions`, origins) → ALB/NLB (`describe-listeners`, `describe-rules`) → target groups (`describe-target-health`) → instances/IPs/Lambda/ECS tasks; API Gateway integrations; public IPs and ENIs with associations (`describe-network-interfaces`) |
| What runs the code? | ASGs + launch templates, EC2 tags, ECS services/tasks and capacity providers, EKS nodegroups/Fargate profiles, Lambda event source mappings, App Runner, Batch |
| What data stores exist? | RDS/Aurora, DynamoDB, ElastiCache, OpenSearch, Redshift, S3 buckets (with replication/notification targets), EFS/FSx, EBS |
| What connects to what? | security group references (`UserIdGroupPairs`), subnet placement, DB subnet groups, event source mappings, EventBridge rule targets (`list-targets-by-rule`), SNS subscriptions, SQS redrive/DLQ links, S3 event notifications, API Gateway/Step Functions integrations, VPC endpoints, peering/TGW routes; **X-Ray service graph** if tracing is on (`xray get-service-graph`) is the best *runtime-confirmed* dependency evidence |
| How is it deployed? | CloudFormation stacks and drift status, CodePipeline/CodeBuild/CodeDeploy projects, ECR repositories and lifecycle policies, presence of IaC-style tags, AMI build pipelines, SSM associations |
| How critical is it? | tags, environment, traffic metrics, user statement. **Do not infer criticality from architecture alone.** |
| Is owner-provided context already recorded? | Well-Architected Tool (`wellarchitected list-workloads`, `get-workload`, `list-lens-reviews`, `list-milestones`: business context, previously recorded risks and improvement plans), Service Catalog AppRegistry (`servicecatalog-appregistry list-applications`), cost-allocation tags, runbooks/SSM documents |
| What are the traffic/scale characteristics? | CloudWatch request counts, connections, queue depth, Lambda invocations, ALB `RequestCount`/`TargetResponseTime`, ASG scaling activity history (14–30+ days) |

### 5.1 Questions to ask the user (only what could not be discovered)

Ask in **one** batched message, as a table the user can answer quickly: one row per discovered workload with your proposed values pre-filled
(marked "assumed"), so the user only corrects what is wrong. Example columns: *Workload · what it does (your understanding) · tier 0–3 · availability
target · RTO · RPO · traffic pattern · compliance · notes*. Then a short list of yes/no questions (e.g. "Is `i-0abc` (bastion) intentionally public?").
Typical gaps:

- Business purpose and criticality of each workload (tier: revenue-critical / internal / dev-test).
- Availability target (SLA/SLO) and tolerable downtime; **RTO / RPO** per data store; last DR or restore test.
- Expected traffic pattern: steady, daily/weekly peaks, seasonal, event-driven; growth expectations.
- Compliance or data-residency constraints (PCI, HIPAA, GDPR, sovereignty) that restrict region/service choices.
- Team size and skills (is Kubernetes operationally justified?), on-call model, change windows.
- Which accounts/regions are production vs non-production; known deliberate exceptions and accepted risks.
- Budget constraints, existing commitments (Savings Plans/RIs, EDP/private pricing), planned migrations.
- Out-of-scope items.

If the user cannot answer, record the assumption explicitly and lower confidence on findings that depend on it.

## 6. Inventory catalogue

Run in stages (§9). Use `--query` projections; the lists below name the calls, not every flag. All are read-only.
Where a table says *project*, omit sensitive fields per §2.

### 6.1 Networking
`ec2`: `describe-vpcs`, `describe-subnets`, `describe-route-tables`, `describe-internet-gateways`,
`describe-egress-only-internet-gateways`, `describe-nat-gateways`, `describe-vpc-endpoints`, `describe-vpc-peering-connections`,
`describe-transit-gateways`, `describe-transit-gateway-attachments`, `describe-network-acls`, `describe-security-groups`,
`describe-network-interfaces`, `describe-addresses`, `describe-flow-logs`, `describe-vpn-connections`.
`elbv2`: `describe-load-balancers`, `describe-listeners`, `describe-rules`, `describe-target-groups`, `describe-target-health`,
`describe-load-balancer-attributes`, `describe-target-group-attributes`; classic `elb describe-load-balancers`.
Also `route53 list-hosted-zones` / `list-resource-record-sets` / `list-health-checks`, `cloudfront list-distributions`,
`apigateway get-rest-apis`, `apigatewayv2 get-apis`, `wafv2 list-web-acls`, `globalaccelerator list-accelerators`.

Look for: subnet tiering (public/private/isolated) vs route tables; AZ spread of subnets; NAT gateway count/AZ placement
vs the private subnets' routes; missing gateway endpoints for S3/DynamoDB; public IPs on non-edge resources; security
group `0.0.0.0/0` and `::/0` ingress (project `IpPermissions`), especially SSH/RDP/DB ports; default VPC use; overlapping CIDRs;
flow log coverage; peering mesh vs Transit Gateway.

### 6.2 Compute
`ec2`: `describe-instances` (project `InstanceId, InstanceType, State.Name, Placement.AvailabilityZone, SubnetId, IamInstanceProfile.Arn, MetadataOptions.HttpTokens, PublicIpAddress, Platform, Tags, LaunchTime`),
`describe-instance-status`, `describe-volumes`, `describe-launch-templates`, `describe-launch-template-versions` (project, no UserData),
`describe-reserved-instances`, `describe-spot-instance-requests`, `describe-capacity-reservations`, `describe-instance-types` (to compare candidate sizes).
`autoscaling`: `describe-auto-scaling-groups`, `describe-policies`, `describe-scheduled-actions`, `describe-scaling-activities`,
`describe-launch-configurations` (project; legacy), `describe-lifecycle-hooks`; `application-autoscaling describe-scalable-targets` / `describe-scaling-policies` (`--service-namespace ecs|dynamodb|lambda|...`).
`ecs`: `list-clusters`, `describe-clusters --include SETTINGS STATISTICS`, `list-services`, `describe-services`, `list-tasks`, `describe-tasks`,
`describe-task-definition` (project), `describe-capacity-providers`, `list-container-instances`, `describe-container-instances`.
`eks`: `list-clusters`, `describe-cluster`, `list-nodegroups`, `describe-nodegroup`, `list-fargate-profiles`, `list-addons`, `describe-addon`, `list-insights`.
`lambda`: `list-functions` (project), `list-event-source-mappings`, `get-function-concurrency`, `get-account-settings`, `list-function-url-configs`.

Look for: single-instance production workloads (no ASG/ELB); ASG min/max/desired and subnets (AZ spread); ASG health check type
(ELB vs EC2) and grace period; scaling policy presence and type; launch configurations (deprecated; migrate to launch templates);
IMDSv1 allowed (`HttpTokens=optional`); instance family/generation and architecture (x86 vs Graviton); T-family credit mode;
Kubernetes version vs standard support window; ECS service desired count, deployment circuit breaker, health check grace;
Lambda runtime deprecation, memory, timeout, architecture, reserved/provisioned concurrency, DLQ/destinations.

### 6.3 Databases
`rds`: `describe-db-instances` (note `DBInstanceClass, Engine, EngineVersion, EngineLifecycleSupport, MultiAZ, StorageType, AllocatedStorage, MaxAllocatedStorage, Iops, StorageThroughput, StorageEncrypted, PubliclyAccessible, BackupRetentionPeriod, DeletionProtection, PerformanceInsightsEnabled, MonitoringInterval, AutoMinorVersionUpgrade, DBSubnetGroup, ReadReplicaSourceDBInstanceIdentifier`),
`describe-db-clusters`, `describe-db-snapshots --snapshot-type manual`, `describe-db-cluster-snapshots --snapshot-type manual`,
`describe-db-subnet-groups`, `describe-reserved-db-instances`, `describe-pending-maintenance-actions`, `describe-db-proxies`,
`describe-db-instance-automated-backups`.
`dynamodb`: `list-tables`, `describe-table` (billing mode, GSIs, TTL, stream, table class), `describe-continuous-backups`, `describe-time-to-live`, `list-global-tables`.
`elasticache`: `describe-cache-clusters`, `describe-replication-groups`, `describe-serverless-caches`, `describe-reserved-cache-nodes`.
Other: `opensearch list-domain-names` + `describe-domains`; `redshift describe-clusters`; `docdb`/`neptune` via `rds describe-db-clusters`;
`kafka list-clusters-v2`; `mq list-brokers`; `dms describe-replication-instances`.

Look for: Multi-AZ vs workload criticality; public accessibility; backup retention and deletion protection; engine versions
approaching or in extended support; storage type/IOPS vs measured IOPS; burstable classes on sustained load; many small databases
that could share a cluster; read replicas with no reads; unencrypted storage; Aurora I/O configuration vs I/O spend.

### 6.4 Storage
S3 (global listing, per-bucket calls): `s3api list-buckets`, `get-bucket-location`, `get-bucket-versioning`, `get-bucket-encryption`,
`get-public-access-block`, `get-bucket-policy-status`, `get-bucket-policy` (read for wildcard principals; do not paste in full),
`get-bucket-lifecycle-configuration`, `get-bucket-logging`, `get-bucket-replication`, `get-bucket-tagging`,
`get-bucket-ownership-controls`, `list-bucket-intelligent-tiering-configurations`, `list-bucket-metrics-configurations`,
`list-multipart-uploads`; account level `s3control get-public-access-block --account-id ID`, `s3control list-storage-lens-configurations --account-id ID`.
Size/object count come from CloudWatch (`AWS/S3` `BucketSizeBytes` per `StorageType` dimension, `NumberOfObjects`; daily metrics, use a 2-day window), **not** from listing objects.
EBS: `ec2 describe-volumes`, `describe-snapshots --owner-ids self`, `describe-images --owners self`, `get-ebs-encryption-by-default`,
`describe-volumes-modifications`; Data Lifecycle Manager `dlm get-lifecycle-policies`.
Other: `efs describe-file-systems` / `describe-lifecycle-configuration` / `describe-backup-policy`, `fsx describe-file-systems`.

### 6.5 Security and governance
`iam`: `get-account-summary` (root MFA, root access keys, counts), `get-account-password-policy`, `get-credential-report` (only if one already exists; do not generate),
`list-users`, `list-access-keys`, `get-access-key-last-used`, `list-mfa-devices`, `list-roles`, `get-role` (trust policy), `list-attached-role-policies`,
`list-role-policies`, `get-role-policy`, `list-policies --scope Local --only-attached`, `get-policy-version`, `get-account-authorization-details`
(single bulk call; analyse offline), `list-open-id-connect-providers`, `list-saml-providers`, `list-instance-profiles`.
`accessanalyzer`: `list-analyzers`, `list-findings-v2`. `organizations`: `describe-organization`, `list-roots`, `list-accounts`, `list-policies --filter SERVICE_CONTROL_POLICY`, `list-delegated-administrators`.
IAM Identity Center: `sso-admin list-instances`, `list-permission-sets` (avoid listing end users).
Detective/preventive: `cloudtrail describe-trails` + `get-trail-status` + `get-event-selectors`, `configservice describe-configuration-recorders` +
`describe-configuration-recorder-status` + `describe-config-rules` + `describe-compliance-by-config-rule`, `guardduty list-detectors` + `get-detector`,
`securityhub describe-hub` + `get-enabled-standards`, `inspector2 batch-get-account-status`, `macie2 get-macie-session`, `shield get-subscription-state`,
`wafv2 list-web-acls` + `list-resources-for-web-acl`, `kms list-keys` + `describe-key` + `get-key-rotation-status` + `get-key-policy` + `list-aliases`,
`secretsmanager list-secrets` (rotation fields), `ssm describe-parameters`, `acm list-certificates` + `describe-certificate`,
`ssm describe-instance-information` + `describe-instance-patch-states` + `describe-patch-baselines` + `describe-maintenance-windows`.

Look for: root MFA/keys; IAM users with console access and no MFA; access keys older than the organisation's rotation standard or unused;
wildcard `Action`/`Resource`/`Principal` and `iam:PassRole`/`sts:AssumeRole` paths; trust policies with external or `*` principals and no
`ExternalId`/conditions; multi-region organisation trail with log file validation, KMS and a protected bucket; Config/GuardDuty/Security Hub
coverage across *all* used regions and delegated-admin setup; SCP guardrails; S3 account-level Block Public Access; RDS/EBS/S3 encryption;
KMS key rotation and key policy breadth; patch compliance; separation of prod and non-prod (accounts, roles, VPCs, shared credentials).

### 6.6 Operations and observability
`cloudwatch describe-alarms` (state, actions configured, `TreatMissingData`), `list-dashboards`, `describe-anomaly-detectors`;
`logs describe-log-groups` (retention, `storedBytes`, KMS, log class), `describe-metric-filters`, `describe-subscription-filters`;
`events list-rules` / `list-targets-by-rule`, `sns list-topics` / `get-topic-attributes` / `list-subscriptions`,
`sqs list-queues` / `get-queue-attributes --attribute-names All`;
`cloudformation list-stacks`, `describe-stacks` (project `StackName, StackStatus, DriftInformation, Tags, LastUpdatedTime`; no parameters),
`list-stack-resources`; pipelines: `codepipeline list-pipelines`/`get-pipeline`, `codebuild list-projects`/`batch-get-projects` (project), `deploy list-applications`;
`ecr describe-repositories` + `get-lifecycle-policy`; `ssm list-documents --filters Key=Owner,Values=Self` (runbooks/automation), `ssm list-associations`;
`xray get-sampling-rules`, `xray get-service-graph`; `health describe-events` (us-east-1, requires a qualifying support plan);
`resourcegroupstaggingapi get-tag-keys` (tagging maturity).

### 6.7 Backup and DR
`backup list-backup-plans` + `get-backup-plan`, `list-backup-selections`, `list-backup-vaults`, `describe-backup-vault` (lock, KMS),
`list-protected-resources`, `list-backup-jobs`, `list-restore-jobs` (evidence that restores are *tested*), `list-copy-jobs`, `list-recovery-points-by-resource`;
RDS automated backup retention and snapshots (§6.3); EBS snapshot policies (`dlm`); S3 versioning/replication (§6.4);
cross-region copies; `drs describe-source-servers` if Elastic Disaster Recovery is used; Route 53 health checks / failover records.

Look for: resources with no backup coverage; retention not matching stated RPO; backups in the same account/region/KMS key as the source
with no isolation; no evidence of restore tests; DR plan that exists only as infrastructure (a replica region) with no runbook or test.

### 6.8 Quotas
`service-quotas list-service-quotas --service-code ec2|vpc|lambda|rds|elasticloadbalancing|...` and `get-service-quota`;
usage via CloudWatch `AWS/Usage` metrics where available; `ec2 describe-account-attributes`; `lambda get-account-settings`.
Flag only quotas where utilisation is high relative to observed growth or where a quota will constrain the scaling story (e.g. Lambda concurrency, ENIs per VPC, EIPs, ASG size, RDS instances).

## 7. Metrics collection

Utilisation claims must be backed by CloudWatch data. Define the window up front and state it in the finding.

- **Window**: at least 14 days; prefer 30 days for steady workloads; use 60+ days for weekly/monthly cycles when available.
  Always note month-end/seasonal risk. Short-lived or recently-launched resources get a "insufficient history" note rather than a rightsizing claim.
- **Statistics**: collect both `Average` and `Maximum` (and p95/p99 via `ExtendedStatistics` where meaningful, e.g. latency). Averages hide
  bursts; maximums hide sustained idleness. Use 1-hour periods (`3600`) for 14–30 day windows; 5-minute periods only for short windows.
- **Batch** with `cloudwatch get-metric-data --metric-data-queries file://queries.json` (write the JSON to scratchpad; up to 500 queries per call)
  rather than hundreds of `get-metric-statistics` calls.
- **Time zones** (§1.8): run metric calls with `TZ=UTC`, bucket hours in UTC, and only then translate to the workload's business time zone
  (state both, e.g. "14:00–16:59 UTC (00:30–03:30 Adelaide)"). Before claiming that two events overlap (a batch peak and the backup window,
  which RDS reports in UTC), check both are in UTC. Hourly maxima can be brief spikes: report the hourly average alongside.
- **Memory is not a default EC2 metric.** Check `cloudwatch list-metrics --namespace CWAgent`. If the CloudWatch agent is absent, memory/disk
  rightsizing is *not assessable*: say so, lower confidence, and avoid recommending a smaller instance on CPU alone for memory-bound software
  (databases, JVMs, caches). Compute Optimizer needs the agent for memory-based recommendations too.

Core metrics by service:

| Service | Namespace · metrics (dimension) |
|---|---|
| EC2 | `AWS/EC2` · `CPUUtilization`, `NetworkIn/Out`, `EBSReadOps/WriteOps`, `EBSReadBytes/WriteBytes`, `CPUCreditBalance`, `CPUSurplusCreditsCharged` (T-family), `StatusCheckFailed` (InstanceId) |
| EBS | `AWS/EBS` · `VolumeReadOps`, `VolumeWriteOps`, `VolumeThroughputPercentage`, `VolumeQueueLength`, `BurstBalance` (gp2/st1/sc1), `VolumeIdleTime` (VolumeId) |
| ALB/NLB | `AWS/ApplicationELB` · `RequestCount`, `ProcessedBytes`, `TargetResponseTime`, `HTTPCode_Target_5XX_Count`, `HTTPCode_ELB_5XX_Count`, `HealthyHostCount`, `UnHealthyHostCount`, `ActiveConnectionCount`; `AWS/NetworkELB` · `ProcessedBytes`, `ActiveFlowCount` (LoadBalancer, TargetGroup) |
| NAT Gateway | `AWS/NATGateway` · `BytesOutToDestination`, `BytesInFromSource`, `BytesOutToSource`, `BytesInFromDestination`, `ActiveConnectionCount`, `ErrorPortAllocation`, `PacketsDropCount` (NatGatewayId) |
| RDS/Aurora | `AWS/RDS` · `CPUUtilization`, `FreeableMemory`, `DatabaseConnections`, `ReadIOPS`, `WriteIOPS`, `ReadLatency`, `WriteLatency`, `FreeStorageSpace`, `DiskQueueDepth`, `ReplicaLag`/`AuroraReplicaLag`, `BurstBalance`, `EBSIOBalance%`, `SwapUsage`, `VolumeReadIOPs`/`VolumeWriteIOPs` (Aurora) |
| ElastiCache | `AWS/ElastiCache` · `CPUUtilization`, `EngineCPUUtilization`, `DatabaseMemoryUsagePercentage`, `CacheHitRate`, `Evictions`, `CurrConnections`, `NetworkBytesIn/Out` |
| DynamoDB | `AWS/DynamoDB` · `ConsumedReadCapacityUnits`, `ConsumedWriteCapacityUnits`, `ProvisionedRead/WriteCapacityUnits`, `ReadThrottleEvents`, `WriteThrottleEvents`, `ThrottledRequests`, `SuccessfulRequestLatency` (TableName) |
| Lambda | `AWS/Lambda` · `Invocations`, `Errors`, `Throttles`, `Duration`, `ConcurrentExecutions`, `IteratorAge`, `DeadLetterErrors` (FunctionName) |
| SQS/SNS | `AWS/SQS` · `ApproximateNumberOfMessagesVisible`, `ApproximateAgeOfOldestMessage`, `NumberOfMessagesSent`; DLQ depth; `AWS/SNS` · `NumberOfNotificationsFailed` |
| ECS/EKS | `AWS/ECS` · `CPUUtilization`, `MemoryUtilization` (ClusterName, ServiceName); Container Insights (`ECS/ContainerInsights`, `ContainerInsights`) if enabled, for node/pod allocation vs usage |
| S3 | `AWS/S3` · `BucketSizeBytes` (StorageType), `NumberOfObjects` (daily); request metrics only if a metrics configuration exists |
| CloudFront | `AWS/CloudFront` (us-east-1) · `Requests`, `BytesDownloaded`, `4xxErrorRate`, `5xxErrorRate`, `CacheHitRate` (if additional metrics enabled) |
| API Gateway | `AWS/ApiGateway` · `Count`, `4XXError`, `5XXError`, `Latency`, `IntegrationLatency` |

## 8. Cost and advisory data

All optional; availability depends on permissions, account type and support plan. Record availability in the access ledger.

- **Cost Explorer** (`ce:*`; management or member account with Cost Explorer enabled; each API request is billed, so batch):
  `get-cost-and-usage` grouped by `SERVICE`, then drill into the top services by `USAGE_TYPE` / `REGION` / `LINKED_ACCOUNT` / tag;
  `get-savings-plans-coverage`, `get-savings-plans-utilization`, `get-reservation-coverage`, `get-reservation-utilization`,
  `get-rightsizing-recommendation`, `get-savings-plans-purchase-recommendation`, `get-reservation-purchase-recommendation`, `get-cost-forecast`, `get-anomalies`.
  `get-cost-and-usage-with-resources` gives resource-level cost for the last 14 days only and must be enabled in settings.
  Use a full recent calendar month (or 3) for baselines; note credits/refunds/discounts treatment (`UnblendedCost` vs `NetAmortizedCost`) in the finding.
- **Compute Optimizer** (must be opted in): `get-enrollment-status`, `get-ec2-instance-recommendations`, `get-ebs-volume-recommendations`,
  `get-lambda-function-recommendations`, `get-auto-scaling-group-recommendations`, `get-ecs-service-recommendations`,
  `get-rds-database-recommendations`, `get-idle-recommendations`, `get-recommendation-summaries`. Treat as evidence to validate, not as a verdict:
  check the look-back window, whether memory metrics were available, and the performance-risk rating.
- **Trusted Advisor**: `support describe-trusted-advisor-checks --language en` + `describe-trusted-advisor-check-summaries` / `describe-trusted-advisor-check-result`
  (us-east-1; Business/Enterprise support plans for the full set), or the newer `trustedadvisor list-recommendations`.
  Never call `refresh-trusted-advisor-check` (a write).
- **Pricing**: `pricing get-products --service-code AmazonEC2 --filters ...` (endpoint region us-east-1; large responses, so filter tightly and project) or the
  public price pages. Do not quote prices from memory in a finding. See `references/cost-optimization.md` §2.
- **Commitments**: `ec2 describe-reserved-instances`, `rds describe-reserved-db-instances`, `elasticache describe-reserved-cache-nodes`,
  `savingsplans describe-savings-plans`; `budgets describe-budgets --account-id ID`.

## 9. Staging large environments

Work in this order and update the **Progress tracker** at the top of the draft review after each stage, so work survives context loss and the
user can see what is done, partial or pending. Do not skip a stage silently.

1. Scope confirmation (identity, regions, depth, cost) and register check
2. Collector run(s) — one per account (§0); copy denied APIs and caps into the access ledger
3. Digest read; workload map and dependency graph; questionnaire
4. Re-verification of open register findings (their *Re-check* commands)
5. Targeted deep dives in risk order — production, internet-facing, largest spend, "Examine first" signals — plus §0.4 gaps that matter
6. Analysis (pillars, anti-patterns, service selection, reliability/performance, cost)
7. Validation (Phase 5 quality gate)
8. Reporting (review + register; `register.py rebuild/check/lint-review`)

For very large estates run the collector with `depth=quick` settings first (no metrics/cost), decide where to go deep, then re-run with
`--with-metrics` for the regions that matter. Keep `--max-per-type` / `--max-buckets` caps and report them as coverage limits.

Per account, then per region, loop sequentially. For an environment with hundreds of instances or buckets, **sample by risk**
(production first, largest spend first, public-facing first), state the sampling basis and coverage ("assessed 40 of 212 buckets,
all production-tagged") and do not generalise beyond what was examined. Use `--max-items` / `--page-size` and `--query` `length()` counts to size things up first.

Tracker states: `Not started · In progress · Done · Partial (why) · Blocked (permission) · Skipped (user)`.

## 9a. Multi-account acceleration

In an AWS Organization, aggregated read-only sources often answer org-wide questions in a few calls. Ask the user whether a profile exists for the
**management**, **security tooling / delegated administrator** or **log archive** account, and use it (same scope confirmation rules) before
collecting each workload account:

| Question | Aggregated source (read-only) |
|---|---|
| Account structure, OUs, guardrails | `organizations list-accounts`, `list-organizational-units-for-parent`, `list-policies --filter SERVICE_CONTROL_POLICY`, `describe-policy`, `list-delegated-administrators` |
| Org-wide resource inventory | AWS Config aggregator: `configservice describe-configuration-aggregators`, `configservice select-aggregate-resource-config --configuration-aggregator-name NAME --expression "SELECT accountId, awsRegion, resourceType, COUNT(*) GROUP BY accountId, awsRegion, resourceType"`; Resource Explorer aggregator index (`resource-explorer-2 search`) |
| Security posture across accounts | Security Hub delegated admin (`securityhub get-findings` with filters, `get-enabled-standards`), GuardDuty delegated admin (`guardduty list-members`), IAM Access Analyzer organization analyzer (`accessanalyzer list-findings-v2`) |
| Audit trail coverage | organization trail (`cloudtrail describe-trails` in the management/log-archive account) |
| Spend by account | Cost Explorer at the management (payer) account grouped by `LINKED_ACCOUNT` (`collect.py --with-cost` in the payer account) |
| Shared resources | AWS RAM (`ram list-resources --resource-owner SELF` / `OTHER-ACCOUNTS`), cross-account trust (digest `IAM-05`), peering/TGW attachment owner IDs |

Then run the collector for each in-scope workload account. Write one review per account and a `YYYY-MM-DDTHHMMZ-cross-account-review.md` covering
account structure, guardrails, shared networking, identity federation, centralised logging/security tooling and cross-account blast radius.
Delegated-admin coverage changes how per-account gaps read: "GuardDuty not enabled" in a member account may be managed centrally — verify before reporting.

## 10. Evidence records

Each finding needs verifiable evidence that someone else can reproduce:

- **What** was observed (field and value), **where** (account, region, resource ID/ARN), **when** (UTC timestamp), **how** (the read-only command or API,
  without secrets), and for metrics: namespace, metric, statistic, period and window.
- Mark each architectural statement **[Confirmed]** (directly observed) or **[Inferred]** (reasoned from indirect evidence, with the reasoning).
- Mark each number **[Measured]** (from AWS data, with source and period) or **[Estimated]** (with method, price source and assumptions) or **[Not quantified]**.
- Never fill a gap with a plausible number. "Not available: `ce:GetCostAndUsage` denied" is a valid, valuable entry.
- Keep resource IDs and counts, not full API dumps, in the report. Group repeated instances ("14 volumes, listed in Appendix").
- Cite **where the evidence came from**: the digest signal ID (`Detected by: SIG NET-07`) and/or the evidence file (`eu-west-1/ec2.describe-route-tables.json`), plus the collection timestamp from `manifest.json`.
- Give every finding a **read-only re-check**: the single command (or digest signal) that shows whether the condition still exists. The next review runs it first.

## 11. Validating against AWS documentation

Before a finding is reported at MEDIUM or above (and for any recommendation that depends on a service limit, default, price model or feature
availability), check the current official documentation, because limits, defaults and features change.

1. Use any docs tool available in the session (web fetch/search, or an AWS documentation MCP server). Prefer `docs.aws.amazon.com`, AWS
   Well-Architected pages, AWS Prescriptive Guidance, and the AWS Builders' Library; fall back to AWS blogs only for announcements.
2. Record the URL (and what it confirms) in the finding's *References*.
3. If no documentation tool is available, cite a canonical URL from the documentation index (§12) but mark the recommendation "documentation not re-verified in this session"
   and set confidence no higher than Medium.
4. Where documentation and the observed behaviour disagree, report the observation and flag the discrepancy rather than choosing silently.

## 12. Documentation index

Starting points to cite (existence verified 2026-11-12). Pages move and change: re-check content before relying on a specific limit, default or price, and cite the deeper page you actually used.
Note: `docs.aws.amazon.com` answers HTTP 200 for non-existent paths by redirecting to a service landing page, so a 200 status does not prove a link is valid.

| Topic | URL |
|---|---|
| Framework (overview) | https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html |
| Pillars | https://docs.aws.amazon.com/wellarchitected/latest/framework/operational-excellence.html · https://docs.aws.amazon.com/wellarchitected/latest/framework/security.html · https://docs.aws.amazon.com/wellarchitected/latest/framework/reliability.html · https://docs.aws.amazon.com/wellarchitected/latest/framework/performance-efficiency.html · https://docs.aws.amazon.com/wellarchitected/latest/framework/cost-optimization.html |
| Disaster recovery strategies | https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-workloads-on-aws.html |
| Multi-account organisation | https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/organizing-your-aws-environment.html |
| Security Reference Architecture | https://docs.aws.amazon.com/prescriptive-guidance/latest/security-reference-architecture/introduction.html |
| Tagging | https://docs.aws.amazon.com/whitepapers/latest/tagging-best-practices/tagging-best-practices.html |
| IAM best practices | https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html |
| KMS (overview, key policies) | https://docs.aws.amazon.com/kms/latest/developerguide/overview.html · https://docs.aws.amazon.com/kms/latest/developerguide/key-policies.html |
| CloudTrail security practices | https://docs.aws.amazon.com/awscloudtrail/latest/userguide/best-practices-security.html |
| GuardDuty · Security Hub · Config | https://docs.aws.amazon.com/guardduty/latest/ug/what-is-guardduty.html · https://docs.aws.amazon.com/securityhub/latest/userguide/what-is-securityhub.html · https://docs.aws.amazon.com/config/latest/developerguide/WhatIsConfig.html |
| EC2 IMDS (IMDSv2) | https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html |
| S3 Block Public Access · lifecycle · storage classes | https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html · https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html · https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html |
| EBS volume types | https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volume-types.html |
| RDS Multi-AZ · Extended Support · Proxy | https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html · https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/extended-support.html · https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html |
| Aurora storage (Standard vs I/O-Optimized) | https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Overview.StorageReliability.html |
| DynamoDB best practices | https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html |
| ElastiCache · CloudFront | https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/WhatIs.html · https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html |
| Lambda memory · SQS event source · operator guide | https://docs.aws.amazon.com/lambda/latest/dg/configuration-memory.html · https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html · https://docs.aws.amazon.com/lambda/latest/operatorguide/intro.html |
| ECS · EKS best practices · EKS versions | https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/intro.html · https://docs.aws.amazon.com/eks/latest/best-practices/introduction.html · https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html |
| Decision guides: containers; SNS vs SQS vs EventBridge | https://docs.aws.amazon.com/decision-guides/latest/containers-on-aws-how-to-choose/choosing-aws-container-service.html · https://docs.aws.amazon.com/decision-guides/latest/sns-or-sqs-or-eventbridge/sns-or-sqs-or-eventbridge.html |
| ALB health checks · ASG health checks | https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html · https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-health-checks.html |
| NAT gateway · NAT pricing · gateway endpoints | https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html · https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-pricing.html · https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html |
| Service Quotas | https://docs.aws.amazon.com/servicequotas/latest/userguide/intro.html |
| CloudWatch Logs groups and retention | https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Working-with-log-groups-and-streams.html |
| AWS Backup | https://docs.aws.amazon.com/aws-backup/latest/devguide/whatisbackup.html |
| Compute Optimizer · Trusted Advisor | https://docs.aws.amazon.com/compute-optimizer/latest/ug/what-is-compute-optimizer.html · https://docs.aws.amazon.com/awssupport/latest/user/trusted-advisor.html |
| Cost Explorer API · rightsizing · Savings Plans | https://docs.aws.amazon.com/cost-management/latest/userguide/ce-api.html · https://docs.aws.amazon.com/cost-management/latest/userguide/ce-rightsizing.html · https://docs.aws.amazon.com/savingsplans/latest/userguide/what-is-savings-plans.html |
| Data transfer costs · public IPv4 charge | https://aws.amazon.com/blogs/architecture/overview-of-data-transfer-costs-for-common-architectures/ · https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/ |
| Builders' Library | https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/ · https://aws.amazon.com/builders-library/avoiding-fallback-in-distributed-systems/ · https://aws.amazon.com/builders-library/static-stability-using-availability-zones/ |
| AWS CLI (SSO config, command reference) | https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html · https://docs.aws.amazon.com/cli/latest/reference/ |
| Lambda runtime support / deprecation | https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html |
| Regional NAT gateways (availability mode) | https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateways-regional.html |
| RDS upgrades and maintenance | https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.Maintenance.html |
| Sustainability pillar (if in scope) | https://docs.aws.amazon.com/wellarchitected/latest/sustainability-pillar/sustainability-pillar.html |
| Well-Architected Tool workloads | https://docs.aws.amazon.com/wellarchitected/latest/userguide/workloads.html |
| Config aggregators · Security Hub / GuardDuty delegated admin | https://docs.aws.amazon.com/config/latest/developerguide/aggregate-data.html · https://docs.aws.amazon.com/securityhub/latest/userguide/designate-orgs-admin-account.html · https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_organizations.html |
| Resource Explorer · X-Ray service map | https://docs.aws.amazon.com/resource-explorer/latest/userguide/welcome.html · https://docs.aws.amazon.com/xray/latest/devguide/xray-console-servicemap.html |
