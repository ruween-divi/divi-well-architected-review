# AWS Service Selection and Configuration Review

Use this file to judge whether each service in the environment is the **right tool for its workload** and whether it is **configured for the actual requirement**.
It is a reasoning aid, not a rule set: AWS features, limits and prices change, so verify anything that drives a recommendation against current documentation
(see `assessment-methodology.md` §11). Do not assume the existing choice is correct; do not assume the "modern" alternative is better.

Contents: 1 Method · 2 Domain decision guides · 3 Configuration review checklists · 4 Multi-database / multi-service justification

---

## 1. Method

For each major component:

1. State the **workload requirement** (throughput, latency, state, consistency, durability, burstiness, team skill, compliance). If unknown, ask or record the assumption.
2. State the **chosen service/configuration** and the likely reason for it.
3. Ask: *what would have to be true for this to be the right choice?* Check whether those conditions hold using metrics and configuration.
4. Name the realistic alternatives (at most two or three) and compare on: fit to requirement, operational burden, failure behaviour, scaling model, cost at **observed** scale, migration effort and risk.
5. Recommend a change only when the alternative wins on at least one dimension that matters to this workload **by a stated margin**, without violating another requirement. Otherwise record "appropriate" (that is a valid, useful conclusion).
6. **Check service lifecycle** for both the current choice and any alternative: is the service open to new customers, in maintenance mode, or announced for end of support? AWS has closed several services to new customers in recent years. An existing dependency on such a service is a long-term risk (usually LOW/MEDIUM or INFORMATIONAL with a migration horizon), and you must never recommend migrating *to* one. Verify on the service documentation or AWS announcements; do not rely on memory. Version lifecycles (RDS engines, EKS, Lambda runtimes) come from the APIs and digest signals `DB-08`, `EKS-01`, `FN-01/02`.

## 2. Domain decision guides

### 2.1 Container workloads

| Option | Choose when | Be cautious / misfit signals |
|---|---|---|
| **ECS on Fargate** | Stateless services/tasks; small team; variable load; no node management wanted; Fargate Spot/arm64 for cost | Very large steady fleets where dense EC2 packing is much cheaper; need for privileged containers, GPUs, or host-level control; tasks sized far above usage |
| **ECS on EC2** | Steady, dense workloads; need specific instance types/GPUs/large local storage; Reserved/Savings Plan coverage; cost at scale | Low utilisation (idle capacity), team does not want OS patching, capacity-provider misconfiguration |
| **EKS** (managed nodegroups / Karpenter / Fargate / Auto Mode) | Kubernetes API/ecosystem is a requirement (operators, Helm charts, portability, platform teams, multi-tenant clusters) | A few simple services; one cluster per app; small team; lagging versions; low node utilisation. See AP-01 |
| **App Runner** | Simple HTTP web apps/APIs from image or source with minimal ops | Needs VPC-heavy networking, non-HTTP protocols, fine control |
| **Lambda (zip/container)** | Event-driven, short-lived, bursty, idle-heavy | Long-running, steady high concurrency, heavy start-up, many DB connections. See AP-06 |
| **Plain EC2 (ASG)** | Legacy/stateful software, licensing, OS-level control, lift-and-shift | Greenfield stateless services that could be containerised or run serverless |

Review: Kubernetes/ECS platform version currency; task/pod CPU and memory vs p95 usage; autoscaling metric and bounds; health checks and deployment strategy; AZ spread of subnets; IAM roles per task/service account; image scanning and ECR lifecycle policies.

### 2.2 Serverless and API workloads

| Option | Choose when | Be cautious |
|---|---|---|
| **Lambda** | Spiky/unpredictable traffic; glue/ETL triggers; event processing | Cold-start-sensitive paths without provisioned concurrency/SnapStart; 15-minute ceiling; steady heavy compute |
| **API Gateway HTTP API** | Simple JWT/IAM auth, proxying to Lambda/HTTP; lower cost/latency | Needs REST-only features (usage plans/API keys, request validation, caching, WAF integration differences) |
| **API Gateway REST API** | Usage plans, API keys, request validation/transformation, caching, private APIs | Using none of those features; high request volume where cost matters |
| **ALB → Lambda / ECS** | Already have ALB; need path routing and WAF; steady traffic | Need per-client throttling or API keys |
| **Lambda Function URLs** | Simple single-function endpoint, no gateway features | Needs throttling, WAF, custom domain management |
| **Step Functions** (Standard/Express) | Orchestration with retries/branching, long-running workflows (Standard), high-volume short workflows (Express) | Trivial two-step flows; high-volume, low-value steps billed per transition (Standard) |
| **EventBridge** (bus / Pipes / Scheduler) | Event routing/filtering, SaaS and AWS-service events, scheduled tasks, point-to-point enrichment | High-throughput data streaming (use Kinesis/MSK); latency-critical paths |

Review Lambda: runtime support status, memory vs measured peak and duration (CPU scales with memory; ~1,769 MB ≈ 1 vCPU), timeout (set just above realistic max, not 15 min "to be safe"), architecture (arm64 where compatible), reserved/provisioned concurrency, `Throttles`/`Errors`, async retry/DLQ/destinations, VPC attachment need, event source mapping batch size and partial-batch handling, SQS visibility timeout ≥ 6× function timeout, layers/package size, X-Ray/Powertools instrumentation.

### 2.3 Relational databases

| Option | Choose when | Be cautious |
|---|---|---|
| **RDS MySQL/PostgreSQL/MariaDB** | Standard OLTP, moderate scale, cost-sensitive, simple HA | High write scale, many read replicas, very fast failover or cross-region DR needs |
| **Aurora (provisioned)** | Higher scale and availability needs: fast failover, up to 15 replicas, shared storage, Global Database, Backtrack (MySQL) | Small/low-traffic databases (instance + I/O costs); extended Aurora I/O charges (evaluate I/O-Optimized when I/O ≳25% of spend) |
| **Aurora Serverless v2** | Variable or unpredictable load; dev/test; many intermittent databases | Constant high load (provisioned + commitments usually cheaper); check minimum capacity/auto-pause behaviour in current docs |
| **RDS SQL Server / Oracle** | Required by the application; licensing in place | License-included cost vs BYOL, edition right-sizing, Multi-AZ licensing cost, unneeded Enterprise features |
| **RDS Custom** | Need OS/DB customisation unavailable on RDS | Taking on patching/HA responsibilities without need |
| **Self-managed on EC2** | Unsupported engine/extension/feature | See AP-05 |

Multi-AZ options: *Multi-AZ DB instance* (synchronous standby, not readable, failover typically 60–120 s); *Multi-AZ DB cluster* (two readable standbys; MySQL/PostgreSQL; faster failover); Aurora (replicas in other AZs act as failover targets; a cluster with a single instance has no fast failover). Multi-AZ is for availability, not backup or read scaling.
Read replicas are for read scaling/cross-region DR, with replica lag; they are not a backup. RDS Proxy for connection-heavy or Lambda clients.

### 2.4 NoSQL and specialised data stores

| Need | Typical choice | Cautions |
|---|---|---|
| Key-value / document at scale with predictable access patterns | **DynamoDB** (provisioned+autoscaling for steady; on-demand for spiky/unknown; Standard-IA table class for cold bulk) | Needs access-pattern-first modelling (AP-10); not for ad hoc relational queries |
| Sub-ms cache or ephemeral store | **ElastiCache** (Valkey/Redis OSS/Memcached; Serverless option) | Not a system of record unless using MemoryDB |
| Durable Redis-compatible primary store | **MemoryDB** | Higher cost than ElastiCache |
| MongoDB-compatible documents | **DocumentDB** | Compatibility gaps; check driver/feature use |
| Graph | **Neptune** | Only when graph traversals are the core query pattern |
| Search / log analytics | **OpenSearch Service** (managed or Serverless) | Over-used as primary store or for simple lookups; sizing/shard mistakes |
| Time series | **Timestream** (check current availability/guidance) or purpose-fit alternatives | Verify feature availability for new accounts |
| Data warehouse | **Redshift** (provisioned/Serverless), **Athena** over S3 for ad hoc | Always-on clusters with sporadic use |

### 2.5 Storage

| Need | Choose | Notes |
|---|---|---|
| Objects, backups, data lake, static assets | **S3** | Pick storage class by access pattern (below); lifecycle rules for expiry, noncurrent versions and incomplete multipart uploads |
| Shared POSIX file system (Linux) | **EFS** (Elastic throughput; IA/Archive tiers; One Zone for non-critical) | Check throughput mode vs usage; lifecycle to IA |
| Windows/SMB, Lustre, NetApp ONTAP, OpenZFS | **FSx** | Match to protocol/performance requirement |
| Block storage for one instance | **EBS** | See §3.2 |
| Ephemeral high-IOPS scratch | **Instance store** (NVMe `d` instances) | Data lost on stop/terminate/failure; never primary storage without replication |

S3 classes: Standard (frequent) · Intelligent-Tiering (unknown/changing patterns; per-object monitoring fee; objects <128 KB are not auto-tiered) · Standard-IA / One Zone-IA (infrequent, ≥128 KB, 30-day minimum duration; One Zone is single-AZ) · Glacier Instant Retrieval (rare, ms access, 90-day minimum) · Glacier Flexible Retrieval (90-day minimum) · Glacier Deep Archive (180-day minimum) · Express One Zone (directory buckets, single-digit-ms, single AZ). Lifecycle transitions have per-request cost and minimum-duration charges; moving short-lived or tiny objects can *increase* cost.

### 2.6 Caching and delivery

| Layer | Use for | Misfit signals |
|---|---|---|
| **CloudFront** | Cacheable HTTP content, global users, S3/ALB origin protection (OAC, origin restrictions), reducing origin egress, WAF at edge | No cache behaviours effective (hit ratio low), everything `no-store`, internal-only apps |
| **ElastiCache / MemoryDB** | Hot reads, sessions, rate limits, leaderboards | Cache-aside without TTL/invalidation; single node without failover for critical use |
| **DAX** | DynamoDB read-heavy hot items needing µs reads | Write-heavy or strongly-consistent reads |
| **API Gateway cache / application cache** | Small response caches | Large cost for small benefit |

### 2.7 Messaging and integration

| Need | Choose | Misfit signals |
|---|---|---|
| Work queue, buffering, decoupling with retry | **SQS** (Standard; FIFO only for ordering/dedup needs) + DLQ + long polling | FIFO where unneeded; no DLQ; short polling at scale |
| Pub/sub fan-out | **SNS** (+ SQS subscribers) | SNS to HTTP without retries/DLQ; one SQS for many consumers |
| Event routing, filtering, schedules, SaaS/AWS events | **EventBridge** | High-volume streaming; ordering guarantees |
| Ordered, replayable stream, multiple consumers | **Kinesis Data Streams** (on-demand/provisioned) | Simple queueing (SQS is simpler); idle shards |
| Kafka API / ecosystem required | **MSK** (provisioned/Serverless) | Small/low-volume loads that SQS/Kinesis would handle |
| Broker protocols (AMQP, MQTT, JMS, STOMP) / lift-and-shift | **Amazon MQ** | New cloud-native designs |
| Orchestration | **Step Functions** | Overly granular states |

### 2.8 Networking

| Need | Choose | Notes |
|---|---|---|
| Few VPCs, simple connectivity | **VPC peering** | No hourly charge; non-transitive; CIDRs must not overlap |
| Many VPCs/accounts/on-prem | **Transit Gateway** (or Cloud WAN) | Hourly per attachment + per-GB processing; route-table design matters |
| Expose a service privately across accounts/VPCs | **PrivateLink** (endpoint services) | Interface endpoints are per-AZ hourly + per-GB |
| Reach AWS services privately | **Gateway endpoints** (S3, DynamoDB; free) and **interface endpoints** (others) | Add interface endpoints where NAT/data volume justifies |
| Outbound internet from private subnets | **NAT Gateway** (zonal, one per AZ; or regional availability mode, which spans AZs) / egress-only IGW for IPv6 | See AP-17; regional mode removes the per-AZ placement problem but check its constraints (e.g. no private NAT); IPv6 egress avoids NAT processing charges where workloads support it |
| Hybrid | **Site-to-Site VPN**, **Direct Connect** (+ redundancy) | Single VPN tunnel or single DX connection = SPOF |
| Global entry/performance | **CloudFront**, **Global Accelerator** (TCP/UDP static anycast IPs) | Layering both rarely needed |
| DNS | **Route 53** (health checks, failover/latency/weighted) | TTLs vs failover time; health check on the right thing |

Public IPv4 addresses incur an hourly charge since Feb 2024 (in use or idle): look for needless public IPs and EIPs.

### 2.9 Compute and instance selection

- **Family by bottleneck**: general purpose `m` (balanced), compute `c`, memory `r`/`x`, storage `i`/`d`, burstable `t`, accelerated `g`/`p`/`inf`/`trn`. Evidence: CPU vs memory vs network vs EBS vs local I/O.
- **Generation**: prefer current-generation families (check `ec2 describe-instance-types --filters Name=current-generation,Values=true`); older generations are typically both slower and less cost-effective per unit.
- **Architecture**: Graviton (arm64, `g` suffix) usually offers better price-performance for compatible workloads (needs arm64 builds/images and testing); AMD (`a`) and Intel (`i`) alternatives; verify licensing and binaries.
- **Burstable (T)**: appropriate only for workloads whose *sustained* CPU is below baseline; check `CPUCreditBalance` and (unlimited mode) `CPUSurplusCreditsCharged`. A T instance running 24×7 near/above baseline is both slow and often more expensive than an M/C instance.
- **Size**: right-size to observed p95/peak with headroom (typically 30–50% at peak for latency-sensitive tiers, more for N-1 AZ failover), considering memory (needs CloudWatch agent data).
- **Scaling model**: horizontal (ASG) for stateless tiers; vertical for stateful/licensed software; scheduled scaling for predictable cycles.
- **Spot**: stateless, interruptible, flexible across many instance types/AZs (ASG mixed-instances, capacity-optimized allocation). Not for single-instance stateful production.
- **Tenancy/licensing**: Dedicated Hosts/Instances only for a stated licensing/compliance need.

### 2.10 Load balancing

| Need | Choose | Notes |
|---|---|---|
| HTTP/HTTPS/gRPC/WebSocket, path/host routing, WAF, OIDC auth | **ALB** | LCU pricing; cross-zone on by default |
| TCP/UDP/TLS, extreme throughput/low latency, static IP per AZ, PrivateLink provider | **NLB** | Cross-zone off by default; enabling it incurs inter-AZ data charges |
| Third-party network appliances | **GWLB** | Specialised |
| Legacy | **Classic LB** | Candidate for migration (features, cost, support) |
| Global static content/edge | **CloudFront** | Not a replacement for regional LB |

Review: AZ coverage, listeners/TLS policies, health-check path/interval/thresholds/timeouts, deregistration delay (default 300 s: often too long for fast deployments), idle timeout vs backend keep-alive, access logs, WAF association, stickiness need, unused LBs (no healthy targets, near-zero `RequestCount`/`ProcessedBytes`).

## 3. Configuration review checklists

Each item: check → what "appropriate" looks like → typical issue. Derive "appropriate" from metrics and requirement, not from a generic rule.

### 3.1 EC2 and Auto Scaling
- Instance type vs 14–30 day CPU (avg/max), network, EBS throughput, memory (if agent) → sustained avg <10–20% and max <40% suggests oversize (verify memory); sustained >70–80% suggests undersize or missing scaling.
- Current generation, architecture, T-family credits.
- ASG: min/max/desired vs demand; ≥2 AZs for Tier 2+; ELB health check type with grace period that exceeds boot time; target-tracking policy on an appropriate metric; instance refresh/rollout strategy; scale-in protection use; mixed-instances/Spot policy; launch template (not launch configuration); warm pools if boot time long.
- IMDSv2 enforced (`HttpTokens=required`), hop limit; IAM instance profile least privilege; SSM-managed; no public IP unless required; EBS encrypted; detailed monitoring where scaling needs 1-minute data.
- Stopped instances with attached volumes; instances without owner tags.

### 3.2 EBS
- **gp3 vs gp2**: gp3 includes 3,000 IOPS and 125 MiB/s baseline independent of size and is priced lower per GiB than gp2; gp2 volumes are usually migration candidates (online `modify-volume` change, a write action the user performs) unless a large gp2 volume's IOPS-by-size exceeds what gp3 provisioning would cost. Verify against measured IOPS/throughput.
- **io1/io2**: justified only when sustained IOPS/latency needs exceed gp3 limits; provisioned IOPS far above observed `VolumeReadOps+VolumeWriteOps` is waste; io2 is preferred over io1 for durability/price.
- **st1/sc1** for large sequential throughput; not for boot or random I/O.
- **Instance-level caps**: each instance type has maximum EBS bandwidth/IOPS; a volume provisioned beyond the instance cap cannot deliver it.
- Check `VolumeQueueLength`, `BurstBalance` (gp2/st1/sc1), idle time, encryption, snapshot policy, `DeleteOnTermination`, unattached volumes.

### 3.3 RDS / Aurora
- Instance class vs CPU/memory (`FreeableMemory`, `SwapUsage`), connections vs `max_connections`, IOPS and throughput vs provisioned, latency, storage growth/fill, storage autoscaling, burst balance.
- Class family: `db.t*` for dev/low steady; `db.m*`/`db.r*` for production; Graviton (`g`) where supported; current-generation.
- Multi-AZ per tier; read replicas used and healthy (`ReplicaLag`); backup retention ≥ RPO/PITR window; deletion protection; encryption; public accessibility off; subnet group spans ≥2 AZs; maintenance windows and auto minor upgrades.
- Engine version support status (RDS Extended Support surcharge applies to old major versions: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/extended-support.html>); parameter group customisation; Performance Insights/Enhanced Monitoring; CA certificate currency.
- Aurora: instance count/roles, I/O mode, serverless v2 min/max ACU, backtrack, global database need.

### 3.4 Lambda
Memory/duration/cost curve, timeout, concurrency (account and reserved), architecture, runtime support, DLQ/destinations, error and throttle rates, VPC need, log retention, provisioned concurrency use vs cold-start requirement, package size, env var secrets (names only), IAM breadth, function URL auth.

### 3.5 ECS / Fargate
Task CPU/memory vs usage; ARM; Spot; desired/min/max; service autoscaling policy and metrics; deployment circuit breaker/rollback; health check grace; capacity providers; `awsvpc` subnets across AZs; task role vs execution role; log retention; image tag immutability and lifecycle; Container Insights cost vs value.

### 3.6 EKS
Kubernetes version vs support window; nodegroup types, instance mix, Spot use; autoscaler (Karpenter/Cluster Autoscaler/Auto Mode) config; node utilisation (requests vs allocatable vs usage); pod IP capacity; add-on versions; control-plane logging; private/public endpoint access; IRSA/Pod Identity; number of clusters; managed-add-on coverage.

### 3.7 NAT Gateways
Availability mode (zonal vs regional); count vs private subnets/AZs; routes pointing at each (digest `NET-07` flags zonal gateways serving other AZs); bytes processed per gateway (`MET-05`); share of spend; AWS-service traffic that endpoints would remove (`NET-08`); idle gateways; AZ-failure story (see AP-17).

### 3.8 S3
Storage class vs access; lifecycle (expire noncurrent versions, abort incomplete uploads, transitions with minimum-size/duration awareness); versioning vs backup need; replication necessity; Block Public Access (bucket and account); default encryption (SSE-KMS bucket keys if KMS); access logging need; request-pattern costs; many small objects; bucket-per-tenant sprawl.

### 3.9 DynamoDB
Billing mode vs traffic shape; capacity vs consumed; throttling; GSI count and utilisation; hot keys; TTL; PITR; backups; table class; streams consumers; global tables justification; item size.

### 3.10 ElastiCache / MemoryDB
Engine and version, node type vs memory use (`DatabaseMemoryUsagePercentage`), hit rate, evictions, replication/Multi-AZ and automatic failover, cluster mode, backup, in-transit/at-rest encryption, auth, reserved nodes for steady use, idle clusters.

### 3.11 CloudFront
Cache hit ratio, behaviours/TTLs, compression, origin protection (OAC / custom header / security group for ALB), price class vs audience, WAF, logging cost, HTTP/3, origin shield need.

### 3.12 SQS / SNS / EventBridge / Kinesis
DLQ and redrive policy, `maxReceiveCount`, visibility timeout vs processing time, retention, long polling (`ReceiveMessageWaitTimeSeconds`), encryption, age-of-oldest-message alarm, FIFO justification, Kinesis shard/iterator age and mode, EventBridge rule DLQs and retry policy, archive/replay need.

## 4. Multi-database and multi-service justification

When several data stores or services of the same kind exist, ask for the justification of each, one by one:

- **Why more than one engine?** Legitimate: different access patterns (OLTP vs search vs cache vs analytics), vendor-supplied software requirement, acquired system. Not legitimate on its own: "each team picked its favourite", "was a demo".
- **Why more than one instance of the same engine?** Isolation (compliance, blast radius), differing criticality or maintenance windows are valid; tiny underused instances duplicated per environment/service are cost and ops overhead (AP-11).
- **Who owns each?** An unowned database or cluster with no connections in 30 days is a retirement candidate (confirm with owner first).
- **Which are authoritative?** Duplicate copies of the same data without a defined source of truth are a consistency risk.
- Apply the same questions to multiple load balancers, queues, clusters, VPCs, NAT gateways and accounts.

Outcome options per item: **Appropriate** · **Appropriate but misconfigured** (list the specific attributes) · **Questionable (needs owner input)** · **Inappropriate** (give the better-fit service and the migration effort).
