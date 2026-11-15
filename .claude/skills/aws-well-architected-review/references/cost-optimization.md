# Cost Optimization Assessment

Method for a **real cost-efficiency assessment**: find what is running but unused, what is oversized, what is priced inefficiently, and which architectural
choices create recurring cost, then quantify it honestly. Primary reference: <https://docs.aws.amazon.com/wellarchitected/latest/framework/cost-optimization.html>

Contents: 1 Honesty rules · 2 Estimating savings · 3 Required finding fields · 4 Top-down cost analysis · 5 Detection catalogue ·
6 Read-only detection queries · 7 Heuristic thresholds · 8 Avoiding false savings · 9 Reporting

---

## 1. Honesty rules

1. **Never invent** prices, utilisation or savings. Every number is labelled **[Measured]**, **[Estimated]** or **[Not quantified]**.
   - **Measured**: read from AWS data (Cost Explorer, CloudWatch, Compute Optimizer, Trusted Advisor, a pricing API response) — cite source, filter, and period.
   - **Estimated**: derived by you — show the formula, price source and date, assumptions, and give a range when uncertain.
   - **Not quantified**: the finding stands without a number (e.g. cost permission denied, price unknown). Say why.
2. **Never present remembered prices as facts.** Prices differ by region, OS, tenancy, term, and change over time. Retrieve current prices
   (`pricing get-products`, the public pricing pages, or the Savings Plans/RI offerings APIs) or leave the saving unquantified.
3. **Savings are not additive by default.** Findings that touch the same resource overlap (delete vs rightsize vs commit). Compute totals on a *non-overlapping set* and say which findings were excluded.
4. **Sequence matters**: eliminate waste → right-size → change architecture → *then* commit (Savings Plans/RIs) on the remaining steady baseline. Recommending commitments before right-sizing locks in waste.
5. **State what reliability or security you would not trade away.** A saving that removes required resilience is not an optimisation.
6. Savings need an **owner decision**; recommend verification steps. The skill never deletes, stops or resizes anything.

## 2. Estimating savings

Method for each estimate:

```
monthly_saving ≈ (current_unit_price − proposed_unit_price) × quantity × hours_or_GB_per_month
```

- **Current spend**: prefer measured actuals (Cost Explorer, last full month(s), filtered to the resource/service/usage type). Otherwise estimate from price × quantity and label it.
- **Hours**: 730 h/month for always-on; use observed run-hours for scheduled workloads.
- **Prices**: record `service, region, SKU attributes (instance type, OS, tenancy, term/offering), price, unit, source, retrieved-on`. Use on-demand as the stated baseline unless commitments are observed; if Savings Plans/RIs cover the resource, the *marginal* saving from removing it may be lower (the commitment still bills) — check coverage/utilisation before claiming savings.
- **Range**: give low–high where uncertain (e.g. utilisation-dependent data transfer).
- **One-off costs**: migration effort, downtime risk, data-transfer or early-deletion fees (e.g. S3 minimum storage duration, RI/SP commitments, snapshot archive retrieval). Mention payback time when material.
- **Annualise** only by multiplying the monthly figure by 12 and say so; do not extrapolate from partial or atypical months.
- **Discounts/credits**: note whether figures are `UnblendedCost` (list-ish) or `NetAmortizedCost`/with private pricing (EDP). If unknown, say it.
- **Uncertainty beats false precision**: "≈$X–Y/month (Estimated)" is better than "$Z.12".

## 3. Required fields for every cost finding

Provide all seven; write "Not available — <reason>" rather than leaving any blank.

| Field | Content |
|---|---|
| Resource / service | IDs or group (count), account, region |
| Current configuration | type/size/storage/IOPS/capacity mode/retention/etc. |
| Observed utilisation | metric, statistic, window (e.g. CPU avg 4%, max 18% over 30 days **[Measured]**) |
| Current estimated spend | amount + basis (**[Measured]** CE filter/period, or **[Estimated]** formula) |
| Proposed alternative | specific change and target configuration |
| Estimated potential savings | amount/range + **[Estimated]**/**[Measured]**, assumptions, price source |
| Risks and trade-offs | performance, availability, security, effort, reversibility, commitments |

Also set the standard finding fields (severity, confidence, complexity, owner questions). Cost severity guide: HIGH when the item is a large share of account spend (default ≳10%) or clearly large in absolute terms for the account; MEDIUM ≈2–10%; LOW <2%; adjust to the customer's scale and say so.

## 4. Top-down cost analysis

Start from where the money goes, then drill down only where it matters (Cost Explorer calls are billed — keep them few and grouped).
`collect.py --with-cost` already gathers steps 1–5 (spend by service/region/account, last month by usage type, Savings Plans/RI coverage and
utilisation, Compute Optimizer summaries, Trusted Advisor recommendations) and `digest.py` summarises them in its cost tables, including a
"hidden infrastructure cost drivers" table built from usage types. Drill down by hand only for the top items.

1. **Baseline**: last 3 full months by `SERVICE`, `UnblendedCost` (and `NetAmortizedCost` if commitments exist). Identify the top services covering ~80% of spend, month-over-month trend, and anomalies.
2. **Drill-down** for the top services by `USAGE_TYPE` (separates instance hours, EBS, data transfer, NAT, requests…), by `REGION`, by `LINKED_ACCOUNT`, and by cost-allocation tag (`Environment`, `Application`).
3. **Hidden infrastructure costs** to look for explicitly in usage types: `NatGateway-Hours`/`NatGateway-Bytes`, `DataTransfer-Regional-Bytes` (inter-AZ), `*-DataTransfer-Out-Bytes`, `PublicIPv4:*`, `CW:*` logs ingestion/storage/custom metrics, `LoadBalancerUsage`/`LCUUsage`, `EBS:SnapshotUsage`, `TimedStorage-*` / `Requests-Tier*` for S3, `*-ExtendedSupport*`, `EKS` hours, `VpcEndpoint-Hours`.
4. **Commitment posture**: Savings Plans and RI coverage and utilisation, expiring commitments, on-demand spend on steady workloads, over-commitment (utilisation <~95–100%).
5. **Recommendation sources** (validate, don't copy): Compute Optimizer, Cost Explorer rightsizing, Trusted Advisor cost checks.
6. **Governance**: budgets, anomaly detection, tagging coverage for cost allocation, separate non-prod accounts.

If Cost Explorer is unavailable, say so, avoid spend-based severity, and rely on resource inventory × (retrieved) price with explicit estimates.

## 5. Detection catalogue

For each: *what to look for* → *evidence required* → *typical action*. Commands are in §6 and in `assessment-methodology.md`.

### 5.1 Compute
- **Idle or underused EC2**: sustained low CPU **and** low network/disk over ≥14 days, with memory checked if the CloudWatch agent exists. Evidence: avg/max CPU, network, memory if available, Compute Optimizer finding, tags/owner. Action: stop/terminate (owner confirms), downsize one or more sizes, move to scheduled/Spot, or consolidate.
- **Oversized instances**: peak utilisation well below capacity (e.g. max CPU <40% and memory <50%) with no stated headroom reason. Account for N-1 AZ headroom and bursts. Action: next smaller size/family; check IOPS/network caps.
- **Burstable misuse**: T-family at sustained high CPU with surplus-credit charges (`CPUSurplusCreditsCharged`) → move to M/C family; or non-burstable at near-zero use → T.
- **Previous-generation / x86 → Graviton**: newer generations and Graviton offer better price-performance for compatible workloads. Evidence: current family, software compatibility (ask). Action: pilot.
- **Spot suitability**: stateless/fault-tolerant ASG members, batch/CI workers, dev clusters, Fargate Spot for interruptible tasks. Do not recommend for single-instance stateful production.
- **Non-production always-on**: dev/test/staging running 24×7 with business-hours use. Evidence: tags + utilisation by hour. Action: scheduled scaling/Instance Scheduler/auto-stop.
- **Stopped instances** with attached volumes/EIPs for long periods; **unused AMIs/launch templates** referencing paid snapshots.
- **Windows/SQL licensing**: license-included Windows/SQL Server on oversized instances, Enterprise edition without feature use, Developer/Express opportunities in non-prod, BYOL or License Manager opportunities. Confirm licensing terms with the owner; do not assume entitlement.

### 5.2 Commitments
- Steady on-demand baseline with **no Savings Plan/RI coverage** → candidate for Compute Savings Plans (flexible across EC2 families/regions, Fargate, Lambda) or EC2 Instance Savings Plans / RIs (less flexible, higher discount) *after* right-sizing and with the user's risk appetite and horizon.
- **Under-utilised commitments** (utilisation well below 100%), commitments expiring soon, RIs for instance families being retired, commitments sized to pre-rightsizing usage. Savings Plans cannot be cancelled; recommendations must show the commitment level relative to the *minimum* steady hourly spend.
- Database and cache reserved capacity (RDS/Aurora/ElastiCache/OpenSearch/Redshift reserved nodes; check whether database Savings Plans are available in current AWS offerings).

### 5.3 Storage
- **Unattached EBS volumes** (`status=available`) and volumes on stopped/terminated instances. Check `CreateTime`, tags, last attachment (CloudTrail `lookup-events` for recent `DetachVolume`).
- **gp2 → gp3** (typically lower $/GiB with 3,000 IOPS/125 MiB/s baseline); over-provisioned io1/io2 IOPS vs observed; st1/sc1 mismatch; oversized volumes with low fill (needs OS metrics; otherwise "not assessable").
- **Snapshot accumulation**: snapshots whose source volume or AMI no longer exists, snapshots older than policy, no lifecycle (DLM/AWS Backup), duplicates. Snapshots are incremental, so deleting one may free less than its apparent size (shared blocks): estimate conservatively. Snapshot Archive tier for long-term retention (minimum-duration and restore costs apply).
- **S3**: no lifecycle rules; large noncurrent-version accumulation; incomplete multipart uploads (`list-multipart-uploads`); Standard class for cold data; Intelligent-Tiering where object sizes are tiny (<128 KB isn't tiered) or Standard-IA on tiny/short-lived objects (minimum billable size/duration); excessive request costs (many small objects / LIST patterns); replication to unnecessary destinations; unused buckets (no requests, empty). Use CloudWatch storage metrics per class and S3 Storage Lens if present.
- **EFS/FSx**: provisioned throughput well above usage, no IA lifecycle, idle file systems.
- **Backups**: retention beyond requirement; cross-region copies without a purpose; manual snapshots from years ago (RDS manual snapshots persist beyond instance deletion).

### 5.4 Databases and caches
- **Idle databases**: `DatabaseConnections` ≈ 0 and negligible IOPS for 30+ days (check for DR/standby purpose; check cron/monthly jobs).
- **Oversized instances**: low CPU and high `FreeableMemory` sustained; remember memory is used by buffer cache and can look "free".
- **Multi-AZ on non-critical/non-prod** (doubles instance cost); read replicas with no read traffic.
- **Storage/IOPS**: provisioned IOPS (io1/io2/gp3 above baseline) > need; gp2 → gp3; over-allocated storage (storage can't shrink easily — flag for new designs); long backup retention.
- **Aurora**: Standard vs I/O-Optimized (compare I/O share of Aurora spend: roughly ≳25% suggests I/O-Optimized, <~25% suggests Standard; verify in docs and with Cost Explorer usage types); Serverless v2 for spiky loads; idle clusters.
- **Extended Support**: old MySQL/PostgreSQL major versions incur per-vCPU-hour surcharges (`*ExtendedSupport*` usage types) → upgrade planning.
- **DynamoDB**: provisioned capacity ≫ consumption; on-demand for steady high load (provisioned + reserved can be cheaper); unused GSIs; Standard-IA table class for storage-heavy cold tables; excessive PITR/backups; large items.
- **ElastiCache/MemoryDB/OpenSearch/Redshift/MSK**: idle clusters, oversized nodes (low memory/CPU), extra replicas, always-on warehouses with sporadic use (Serverless/pause), reserved nodes for steady use, Valkey vs Redis OSS price differences.

### 5.5 Networking and data transfer
- **NAT Gateways**: count, idle gateways, bytes processed per gateway, AWS-service traffic avoidable via gateway/interface endpoints (S3/DynamoDB gateway endpoints are free), dev/test per-AZ NATs, one NAT per AZ where availability isn't needed, IPv6 egress-only alternatives. (AP-17)
- **Public IPv4**: unattached EIPs and unnecessary public IPs (hourly charge applies to in-use and idle public IPv4).
- **Load balancers**: ALB/NLB/CLB with no healthy targets or negligible `RequestCount`/`ProcessedBytes`; one-LB-per-service sprawl (AP-27).
- **VPC endpoints**: interface endpoints in many AZs/VPCs with little traffic.
- **Data transfer**: inter-AZ chatter (database clients, caches, NLB cross-zone, Kubernetes pod traffic), cross-region replication/copies, internet egress that CloudFront would reduce, NAT egress to third parties, large cross-account/region transfers. Evidence: `DataTransfer-*` usage types by service/region; flow logs only if the user provides summarised analysis.
- **Transit Gateway / PrivateLink / VPN / Direct Connect**: unused attachments, redundant paths, low-utilisation connections.

### 5.6 Observability and logging
- **CloudWatch Logs**: groups with "Never expire" retention; very high ingestion groups (debug logging in prod); duplicate log delivery; VPC Flow Logs to CloudWatch Logs at high volume (S3 destination is typically cheaper); infrequent-access log class for rarely queried logs; Lambda log verbosity.
- **Metrics/alarms/dashboards**: high-cardinality custom metrics, detailed monitoring on idle instances, Container Insights costs vs use, orphaned alarms/dashboards.
- **CloudTrail/Config/GuardDuty**: duplicate trails, Config recorders recording high-churn resource types in all regions, data events on busy buckets. Do not recommend disabling security controls to save money without confirming coverage elsewhere.

### 5.7 Containers and serverless
- **EKS**: number of clusters (control-plane hourly charge each), extended-support clusters, node utilisation (requests vs allocatable vs usage), over-provisioned nodegroup minimums, no Spot where tolerable, Fargate pod sizing, idle environments. **ECS/Fargate**: task size vs usage, always-on dev services, Fargate Spot, ARM.
- **ECR**: repositories without lifecycle policies accumulating images.
- **Lambda**: memory too high (cost) or too low (longer duration — sometimes more expensive); arm64; provisioned concurrency idle; very high invocation counts from loops/retries; functions in AP-06 profile (long/steady) that should move to containers. Use Compute Optimizer Lambda recommendations when enrolled.

### 5.8 Architectural cost drivers
Recurring costs created by design: AP-01 (EKS where ECS would do), AP-02 (per-service fixed costs), AP-05 (self-managed with high operations cost — count engineering time qualitatively), AP-09, AP-17, AP-21, AP-25, AP-27. Quantify the *recurring* delta, and the one-off migration cost.

## 6. Read-only detection queries

Most of these checks run automatically in `digest.py` (signals `STO-01…08`, `NET-04/05/06/08/10`, `LB-01`, `OPS-04`, `SEC-04`, `MET-01…10`, `COST-01`).
Use the commands below for targeted follow-up or when the collector could not run. Add `--profile` (required by the guard), `--region` and `--output json --no-cli-pager`. All are read-only.

```bash
# Unattached EBS volumes
aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[].{id:VolumeId,gb:Size,type:VolumeType,iops:Iops,created:CreateTime,tags:Tags}'

# gp2 volumes (candidates for gp3)
aws ec2 describe-volumes --filters Name=volume-type,Values=gp2 \
  --query 'Volumes[].{id:VolumeId,gb:Size,state:State,attached:Attachments[0].InstanceId}'

# Unassociated Elastic IPs
aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].{ip:PublicIp,alloc:AllocationId}'

# Available (unattached) network interfaces
aws ec2 describe-network-interfaces --filters Name=status,Values=available \
  --query 'NetworkInterfaces[].{id:NetworkInterfaceId,desc:Description,subnet:SubnetId}'

# Snapshots owned by the account (sample/size first with length(); compare with volumes and AMIs offline)
aws ec2 describe-snapshots --owner-ids self --query 'length(Snapshots)'
aws ec2 describe-snapshots --owner-ids self \
  --query 'Snapshots[].{id:SnapshotId,vol:VolumeId,gb:VolumeSize,start:StartTime,desc:Description}'
aws ec2 describe-images --owners self --query 'Images[].{id:ImageId,created:CreationDate,name:Name}'

# Stopped instances
aws ec2 describe-instances --filters Name=instance-state-name,Values=stopped \
  --query 'Reservations[].Instances[].{id:InstanceId,type:InstanceType,stopped:StateTransitionReason,tags:Tags}'

# NAT gateways and the subnets/route tables that reach them
aws ec2 describe-nat-gateways --query 'NatGateways[].{id:NatGatewayId,az:SubnetId,state:State,created:CreateTime}'
aws ec2 describe-route-tables --query 'RouteTables[?Routes[?NatGatewayId!=null]].{rt:RouteTableId,assoc:Associations[].SubnetId}'

# Load balancers and whether targets exist (then check RequestCount / ProcessedBytes in CloudWatch)
aws elbv2 describe-load-balancers --query 'LoadBalancers[].{arn:LoadBalancerArn,type:Type,scheme:Scheme,created:CreatedTime}'
aws elbv2 describe-target-groups --query 'TargetGroups[].{arn:TargetGroupArn,lbs:LoadBalancerArns}'

# CloudWatch log groups without retention, largest first
aws logs describe-log-groups --query 'sort_by(logGroups,&storedBytes)[?retentionInDays==null].{name:logGroupName,bytes:storedBytes,class:logGroupClass}'

# RDS: class, Multi-AZ, storage, engine lifecycle
aws rds describe-db-instances --query 'DBInstances[].{id:DBInstanceIdentifier,class:DBInstanceClass,engine:Engine,ver:EngineVersion,maz:MultiAZ,st:StorageType,gb:AllocatedStorage,iops:Iops,life:EngineLifecycleSupport,tags:TagList}'
aws rds describe-db-snapshots --snapshot-type manual --query 'DBSnapshots[].{id:DBSnapshotIdentifier,db:DBInstanceIdentifier,gb:AllocatedStorage,created:SnapshotCreateTime}'

# S3 lifecycle absent? (loop buckets; ignore NoSuchLifecycleConfiguration as "no rules")
aws s3api get-bucket-lifecycle-configuration --bucket BUCKET

# Compute Optimizer / Trusted Advisor / Cost Explorer (if available)
aws compute-optimizer get-ec2-instance-recommendations --query 'instanceRecommendations[].{id:instanceArn,finding:finding,cur:currentInstanceType,rec:recommendationOptions[0].instanceType,risk:recommendationOptions[0].performanceRisk}'
aws ce get-rightsizing-recommendation --service AmazonEC2 --configuration RecommendationTarget=SAME_INSTANCE_FAMILY,BenefitsConsidered=true
```

Utilisation queries (CloudWatch `get-metric-data` over 14–30 days, avg and max) are described in `assessment-methodology.md` §7.
For idle load balancers/NATs/databases, a metric of zero over the window is evidence; absence of metric data is **not** evidence of idleness (the resource may report only when active).

## 7. Heuristic thresholds

Starting points only. They are not AWS rules and not substitutes for workload context; state which you used and why.

| Resource | Possible waste signal (over ≥14, ideally 30 days) | Caveats before acting |
|---|---|---|
| EC2 | avg CPU <10% and max CPU <40%, low network, (memory <50% if known) | burst/seasonal use, memory/disk bound, licensing per core, N-1 headroom, DR standby |
| Idle EC2 | CPU, network and disk near zero all period | scheduled jobs, standby role, bastions, license servers |
| RDS | avg CPU <10–15% and `FreeableMemory` consistently high; connections ≈0 for idle | memory is cache, month-end jobs, failover headroom, IOPS-bound |
| EBS (IOPS) | provisioned IOPS ≫ p99 observed (e.g. >2–3×) | latency-sensitive spikes, future growth, instance caps |
| ALB/NLB | ~0 requests/processed bytes and no healthy targets | DR/maintenance pages, seasonal endpoints |
| NAT | ~0 `BytesOutToDestination` | routes in use for rare patch/update windows |
| Lambda | memory >2–3× peak usage (from `REPORT` lines or Powertools/Compute Optimizer data) | CPU needs, latency, may be cheaper at more memory |
| ElastiCache | memory use <30%, hit rate low, evictions 0 | burst, failover headroom |
| Commitments | utilisation <~95% persistently | planned migrations, ramping workloads |
| Snapshots/AMIs | source gone, older than retention standard | legal hold, AMI dependency, DR use |

## 8. Avoiding false savings

Before reporting, check whether the "waste" is actually:
- A **DR/standby** or **failover** resource (idle on purpose).
- A **periodic** workload (month-end, quarterly, annual, audit).
- **Headroom** required by a stated SLO or N-1 AZ design.
- **Dependency-bearing**: an EBS snapshot backing an AMI used by an ASG; an "unused" ENI/SG/EIP referenced by IaC or DNS; an "idle" LB with a DNS record.
- Covered by a **commitment** that would be wasted if removed (marginal saving small or zero until the commitment lapses).
- **Not measurable** from your data (e.g. no memory metrics): say "not assessable" instead of guessing.
- Part of **compliance retention** (logs, backups, snapshots).

If in doubt, classify as "Potential — owner confirmation required" with the exact question, confidence Low–Medium.

## 9. Reporting

In the review's Cost Optimization section include:

1. **Spend context** (if available): period, total, top services (table), trend, commitment coverage/utilisation — all **[Measured]** with source.
2. **Findings table**: ID · Category · Resource(s) · Current monthly (basis) · Proposed · Est. saving/month (range, label) · Risk · Complexity · Confidence.
3. **Quick wins vs structural changes** (waste removal, right-sizing, pricing model, architecture).
4. **Total opportunity** only over non-overlapping findings, stated as a labelled range with excluded overlaps listed; separate **Measured waste** (already visible in billing, e.g. unattached volumes) from **Estimated** savings.
5. **What was not assessed** (e.g. memory-based rightsizing, data-transfer attribution, other accounts) so the reader does not mistake absence for efficiency.
6. **Not-recommended optimisations** you considered and rejected because they would compromise reliability/security (this shows judgement).
