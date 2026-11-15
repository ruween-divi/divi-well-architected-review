# Architecture Anti-Pattern Catalogue

Anti-patterns are found by looking at **how resources interact**, not at single resources. Use this catalogue after workload discovery
(the dependency graph exists) and before writing pillar conclusions. Each entry gives detection signals, why it hurts, when it is *not* an
anti-pattern, the improvement and its trade-offs.

## How to use

1. **Match on evidence, not on names.** A signal is a prompt to investigate, never a verdict.
2. **Check the "Not an anti-pattern when" line first.** If a counter-signal holds, drop the finding or downgrade it to INFORMATIONAL.
3. **Quantify** the impact with measured data where possible (spend, utilisation, error rates). Where you can't, say so.
4. **Recommend the smallest change that removes the problem.** Re-architecture is the last resort; configuration changes come first.
5. Include **both over- and under-engineering**. The same system can show both (a service mesh for three services *and* no backups).
6. Group related symptoms into one finding (ID `AWS-WA-NNN`, category `architecture-anti-pattern`) and link the underlying resource-level findings.
7. Digest signals (`scripts/digest.py`) point at these entries in their *see* field (e.g. `NET-07` → AP-17/AP-22, `INT-02` → AP-14). A signal is where to look; the anti-pattern is your conclusion after checking the counter-signals.

### Report format for each anti-pattern (Section 4 of the review)

```markdown
### AP: <Anti-pattern name> — <short title for this environment>   (Finding AWS-WA-0NN · Severity · Confidence)
1. **What it is** — one or two sentences.
2. **Where it exists** — account / region / resources / workload; mark [Confirmed] or [Inferred].
3. **Why it is a problem** — specific to this workload, with evidence.
4. **Impact** — operational · reliability · performance · financial (measured / estimated / not quantified).
5. **Recommended improvement** — the target design, in plain terms, plus what *not* to do.
6. **Implementation complexity** — Low / Medium / High, with the main work items and downtime.
7. **Trade-offs and risks** — what you give up, when the current design is actually the better choice.
```

---

## A. Compute and platform choice

### AP-01 Premature or unnecessary Kubernetes (EKS)
- **Signals**: EKS cluster(s) running a handful of stateless services; one small nodegroup; no use of CRDs/operators/Helm ecosystem/custom schedulers/multi-cloud portability; team of a few engineers; cluster per environment or per service; Kubernetes version lagging standard support; add-ons managed by hand; node utilisation low.
- **Why**: control-plane fee per cluster (and extended-support surcharge on old versions), node and add-on patching, upgrade cadence (~3 releases/year), RBAC/networking/ingress/CNI complexity, cluster-level blast radius, specialised skills and on-call burden.
- **Not an anti-pattern when**: workloads depend on the Kubernetes API/ecosystem (operators, service mesh with justification, GPU scheduling, custom controllers), a portability requirement is real, the organisation already runs a platform team and many teams share clusters efficiently, or the user states Kubernetes is strategic.
- **Improvement**: for simple container workloads consider ECS on Fargate (or ECS on EC2 for steady, dense workloads), App Runner for simple web services, or Lambda for event-driven pieces; if staying on EKS, consolidate clusters, use managed nodegroups/Karpenter or EKS Auto Mode, upgrade to supported versions, right-size requests.
- **Complexity / trade-offs**: Medium–High migration (deployment tooling, IAM for service accounts → task roles, ingress, observability). Lose Kubernetes portability and ecosystem. Don't migrate for its own sake; weigh against running cost and team skill.

### AP-02 Microservices where a modular monolith would do (excessive fragmentation)
- **Signals**: many tiny services/functions/queues for one small product; one deployable per CRUD entity; services always deployed together; a shared release train; high ratio of services to engineers; each service with its own ALB/ECS cluster/NAT/log group; most inter-service calls synchronous; versioned shared libraries to keep in lockstep.
- **Why**: network hops add latency and failure modes; operational overhead (pipelines, dashboards, alarms, IAM, networking) multiplies; per-service fixed costs (load balancers, endpoints, minimum capacity) dominate; debugging requires distributed tracing.
- **Not an anti-pattern when**: services have independent scaling profiles, teams, release cadence, data ownership, or technology needs; compliance requires isolation.
- **Improvement**: merge tightly-coupled services into a modular monolith (clear internal module boundaries) behind one deployable and one load balancer; keep separation only where scaling/ownership differs. Share infrastructure (cluster, ALB with path/host rules).
- **Complexity / trade-offs**: Medium–High (code merge). Lose independent deploys and blast-radius isolation.

### AP-03 Distributed monolith
- **Signals**: services call each other synchronously in chains (A→B→C→D) to serve one request; one shared relational database/schema across services; lockstep deployments; one service outage cascades; shared mutable libraries; X-Ray graph showing deep call depth.
- **Why**: all the cost of distribution with none of the independence; availability multiplies (four 99.9% hops ≈ 99.6%); latency stacks; schema changes become cross-team events.
- **Not an anti-pattern when**: the chain is short, critical-path calls have timeouts/fallbacks, and the shared database is a deliberate transitional state with a plan.
- **Improvement**: collapse the chain into one service, or decouple with events/queues so non-critical work is async; give each service ownership of its data or merge them; add timeouts, bulkheads and circuit breakers on remaining sync calls.
- **Complexity / trade-offs**: High. Eventual consistency and idempotency work is required when going async.

### AP-04 Monolith that blocks scaling or safe deployment
- **Signals**: one huge instance/ASG running everything; deployments cause downtime or require full-fleet restarts; one hot component forces scaling the entire app (CPU-heavy job runs next to the web tier); background jobs on web servers; no horizontal scaling because state is on-instance.
- **Why**: scaling granularity is too coarse (cost), failures are all-or-nothing, releases are risky.
- **Not an anti-pattern when**: scale is modest and deploys are safe (blue/green or rolling with health checks); a modular monolith meets the SLO. Monoliths are fine.
- **Improvement**: externalise state (sessions → ElastiCache/DynamoDB, files → S3), peel off background/batch work to queues + workers, add rolling/blue-green deployment; split out only the component whose scaling or release profile differs.
- **Complexity / trade-offs**: Medium. Avoid jumping straight to many services.

### AP-05 EC2 running what a managed service should
- **Signals**: self-managed MySQL/PostgreSQL/Redis/RabbitMQ/Elasticsearch/Kafka/NGINX-as-ALB/Jump host/NAT instances on EC2; hand-run backups; cron on a single instance; manual OS patching; custom bastion with long-lived SSH keys.
- **Why**: patching, HA, backup, failover and scaling become the team's job; data-loss and security risk grows; engineers spend time on undifferentiated work.
- **Not an anti-pattern when**: a required engine/version/extension/OS-level control is not available as managed, licensing mandates it, or measured cost at scale clearly favours self-managed *including* engineering time.
- **Improvement**: RDS/Aurora, ElastiCache/MemoryDB, Amazon MQ/SQS/MSK, OpenSearch Service, ALB/NLB, SSM Session Manager or EC2 Instance Connect Endpoint instead of bastions, EventBridge Scheduler instead of cron.
- **Complexity / trade-offs**: Medium (migration, parameter compatibility, cutover). Managed services cost more per unit but reduce operations; some tuning knobs are unavailable.

### AP-06 Lambda used for unsuitable workloads
- **Signals**: functions at or near the 15-minute timeout; functions that poll or sleep; steady, high, constant concurrency (always-on) with high memory settings; large dependency payloads causing slow cold starts on latency-sensitive paths; Lambda holding persistent connections; recursion between Lambda ↔ SQS/S3 triggers; Lambda as a fixed-rate "server".
- **Why**: per-ms billing at sustained load can exceed container/EC2 cost; timeouts truncate work; cold starts hurt latency; connection pressure on databases.
- **Not an anti-pattern when**: traffic is spiky/idle-heavy, execution is short, and operational simplicity outweighs unit cost; provisioned concurrency is justified by latency SLOs.
- **Improvement**: move long/steady workloads to Fargate/ECS/EC2 (with Spot where tolerant), Step Functions for orchestration, AWS Batch for batch; keep Lambda for event-driven bursts. For genuine Lambda use: tune memory with measurements (power-tuning), arm64, reserved concurrency to protect downstreams.
- **Complexity / trade-offs**: Medium. Loses scale-to-zero.

### AP-07 Pet instances and single-instance production
- **Signals**: production on one instance (no ASG or ASG size 1 without a meaningful self-healing story); manually configured; unique AMI; state on the instance; Elastic IP as the only addressing; "do not reboot" tribal knowledge.
- **Why**: any host/AZ failure is an outage; recovery is manual and slow; no repeatable build.
- **Not an anti-pattern when**: the workload is Tier 0/1, an ASG-of-one with automatic replacement and externalised state meets the RTO, or the system is truly singleton by nature (documented), with tested rebuild.
- **Improvement**: ASG (min 1–2, ≥2 AZs where the tier justifies it) + launch template + externalised state; EC2 auto recovery as a minimum; AMI/user-data via pipeline; backups of state.
- **Complexity / trade-offs**: Low–Medium. Licensing or stateful software may limit horizontal scale.

### AP-08 Over-provisioned or fragmented container capacity
- **Signals**: ECS/EKS clusters with low allocation vs usage (CPU/memory reservation ≫ utilisation); tasks sized at 4 vCPU/8 GB using <10%; a cluster per team/service; idle nodes kept for "headroom" without need; min capacity far above steady demand; no scheduled scale-down for non-prod; cluster autoscaling absent.
- **Why**: paying for unused capacity; bin-packing inefficiency; larger blast radius for cluster-wide events.
- **Not an anti-pattern when**: documented N+1/AZ-loss headroom, bursty traffic with slow scale-out, licensing or data-locality constraints.
- **Improvement**: right-size task/pod requests from measured usage (p95/p99), consolidate clusters, capacity providers/Karpenter, Fargate Spot / EC2 Spot for fault-tolerant work, schedule non-prod down.
- **Complexity / trade-offs**: Low–Medium. Keep failover headroom and watch for OOM/throttle after downsizing.

## B. Data

### AP-09 Database configuration that does not match the workload
- **Signals**: burstable (`db.t*`) instances with sustained CPU or exhausted credits; `io1/io2` or high provisioned IOPS far above observed `ReadIOPS+WriteIOPS`; gp2 volumes sized for IOPS instead of gp3; storage autoscaling disabled with high fill; Multi-AZ off for a Tier 2+ production DB (or on for dev); read replicas with no read traffic; oversized instance (low CPU, high `FreeableMemory` over 30 days); previous-generation or extended-support engine versions; Aurora Standard with I/O charges ≳25% of Aurora spend (I/O-Optimized candidate), or I/O-Optimized with trivial I/O; no Performance Insights; default parameter groups on a tuned workload; connection counts near limit.
- **Why**: either performance incidents or recurring waste; extended support surcharges; failover surprises.
- **Not an anti-pattern when**: headroom is for a known peak, failover capacity, or compliance; burstable is fine for genuinely idle/dev databases.
- **Improvement**: match class/storage to measured CPU, memory, IOPS and throughput; gp3 with explicit IOPS only when needed; Multi-AZ per tier; Aurora Serverless v2 for spiky/variable load; engine upgrades; RDS Proxy for connection-heavy clients; consolidate underused DBs.
- **Complexity / trade-offs**: Low (modify instance class, brief failover) to Medium (engine upgrade, testing). Resize windows and rollback plan required.

### AP-10 DynamoDB without access-pattern design
- **Signals**: frequent `Scan` in hot paths (check via application code if available, or sustained consumed read capacity ≫ item-level reads); relational-style schema with many tables and client-side joins; low-cardinality partition keys / hot partitions (`ThrottleEvents` while table-level capacity is available); GSIs created ad hoc (many GSIs, low selectivity, each duplicating write cost); provisioned capacity set far above/below consumption with no auto scaling; on-demand for steady predictable high throughput; large items near the 400 KB limit; no TTL for expiring data; Standard table class for rarely-accessed bulk data.
- **Why**: throttling, cost explosion (scans bill by data scanned), complexity of workarounds.
- **Not an anti-pattern when**: small tables, admin/analytics scans off the hot path, deliberate on-demand for unpredictable traffic.
- **Improvement**: design the keys from access patterns (single-table or a few well-modelled tables), add targeted GSIs, write sharding for hot keys, choose billing mode from traffic shape (provisioned + autoscaling or reserved capacity when steady), TTL, Standard-IA table class where storage dominates, or move relational/ad-hoc query needs to Aurora/RDS.
- **Complexity / trade-offs**: Medium–High (data model rework, migration). If access patterns are genuinely relational/ad hoc, DynamoDB may be the wrong store.

### AP-11 Database sprawl, or one database to rule them all
- **Signals (sprawl)**: dozens of small RDS instances (many `db.t3.micro/small`) each Multi-AZ, with low utilisation; separate engines per service with no stated need; multiple Redis clusters with low memory use. **Signals (shared)**: many services writing to the same schema; cross-service joins; one database whose failure stops everything.
- **Why**: sprawl multiplies fixed cost, patching and backups; shared DBs couple release cycles and failure.
- **Not an anti-pattern when**: isolation is required (compliance, noisy-neighbour risk, differing engines for genuine reasons).
- **Improvement**: consolidate small tenants onto fewer instances/clusters (separate schemas/users) where isolation allows; for shared DBs, define ownership boundaries and move toward per-domain schemas or databases only when teams/scale need it.
- **Complexity / trade-offs**: Medium. Consolidation trades isolation for efficiency; unbundling a shared DB is a major effort.

### AP-12 Missing caching strategy
- **Signals**: read-heavy database with high `ReadIOPS`/CPU and repetitive queries; static assets or APIs served from origin with no CloudFront; no `Cache-Control`; ALB returning static content; session or reference data fetched from the DB per request; DynamoDB with hot, read-mostly items and no DAX/application cache.
- **Why**: unnecessary database load and latency, over-provisioned DB, higher egress cost.
- **Not an anti-pattern when**: data must be strongly consistent and uncacheable; read volume is low; the cache would be a new SPOF without benefit.
- **Improvement**: CloudFront for cacheable HTTP, ElastiCache (Valkey/Redis OSS/Memcached) or MemoryDB for hot data, DAX for DynamoDB read hot spots, application-level caching with explicit TTL/invalidation strategy.
- **Complexity / trade-offs**: Medium. Consistency/invalidation complexity; cache stampede and cold-start behaviour must be designed.

### AP-13 Connection storms (Lambda/containers directly to RDS)
- **Signals**: Lambda functions or auto-scaled tasks connecting directly to RDS/Aurora; `DatabaseConnections` spikes near `max_connections`; failovers or deploys followed by connection errors; no RDS Proxy; no reserved concurrency to cap fan-out.
- **Why**: scale-out exhausts connections, making the database the outage trigger.
- **Not an anti-pattern when**: concurrency is bounded and connections pooled, or the database is small with predictable clients.
- **Improvement**: RDS Proxy (or pooled connections via the app), reserved concurrency / max tasks, Data API for Aurora Serverless where suitable.
- **Complexity / trade-offs**: Low–Medium. Proxy adds cost and a hop; pinning behaviours can limit multiplexing.

## C. Integration and messaging

### AP-14 Misused messaging and eventing services
- **Signals**: polling loops where events would do; SQS used for pub/sub fan-out (multiple consumers fighting for one queue) or SNS used where durable work queueing with retry is needed; SNS→HTTP(S) endpoints without DLQ; EventBridge used as a high-throughput data pipe (cost/quotas) or Kinesis/MSK deployed for modest queue-like loads; FIFO queues without need for ordering/dedup (throughput limits, cost); no DLQs; visibility timeout shorter than processing time (duplicate processing) or Lambda event source with visibility < 6× function timeout; MSK clusters with tiny traffic; many point-to-point integrations with custom glue code.
- **Why**: lost or duplicated messages, throttling, runaway cost, operational burden of self-run brokers.
- **Not an anti-pattern when**: Kafka compatibility, replay/ordering semantics or ecosystem tooling is a stated requirement; FIFO ordering is truly needed.
- **Improvement**: choose by semantics — SQS for work queues with DLQ and backoff; SNS (+SQS) for fan-out; EventBridge for routing/filtering/SaaS/AWS service events and schedules; Kinesis for ordered, replayable streams with multiple consumers; MSK when Kafka API/ecosystem is required; always DLQs + alarms on age/depth.
- **Complexity / trade-offs**: Low–Medium. Migrating producers/consumers needs idempotency review.

### AP-15 Excessive synchronous dependency chains and missing timeouts
- **Signals**: request path crossing many services synchronously; no client timeouts (defaults of minutes), no connection pool limits; ALB idle timeout/target timeouts inconsistent with downstream; X-Ray latency stacking; user-facing request waits for non-essential work (email, analytics, audit) to complete.
- **Why**: latency and availability multiply, slow dependencies exhaust threads/connections and cascade.
- **Not an anti-pattern when**: a short, necessary chain with strict timeouts and fallbacks.
- **Improvement**: move non-critical work async (SQS/EventBridge/Step Functions), set explicit timeouts shorter than callers' timeouts, bulkheads, circuit breakers, caching of dependency results, graceful degradation.
- **Complexity / trade-offs**: Medium. Introduces eventual consistency and at-least-once handling.

### AP-16 Unbounded retries and retry storms
- **Signals**: SDK/clients with infinite or aggressive retries, no jitter; Lambda async with default retries re-driving a broken downstream; SQS redrive with `maxReceiveCount` very high or no DLQ; Step Functions with unlimited `Retry`; no backoff in consumers; alarms firing only after queues are hours deep.
- **Why**: retries amplify load on an already-failing dependency (metastable failure) and inflate cost.
- **Not an anti-pattern when**: retries are bounded, backed off with jitter, idempotent, and budgeted.
- **Improvement**: exponential backoff with jitter, retry budgets/limits, DLQs and redrive procedure, idempotency keys, load shedding. See Builders' Library: <https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/>
- **Complexity / trade-offs**: Low–Medium.

## D. Network

### AP-17 NAT Gateway misuse
- **Signals**: NAT gateway data processing a large share of the bill (Cost Explorer `NatGateway-Bytes` usage types, CloudWatch `BytesOutToDestination`); AWS service traffic (S3, DynamoDB, ECR, CloudWatch, STS, SSM) routed via NAT with no VPC endpoints; one NAT per AZ in dev/test VPCs with trivial traffic; NAT in a VPC whose private subnets host nothing needing internet; conversely a **single zonal** NAT serving multiple AZs (AZ-failure SPOF and cross-AZ traffic charges) in a Tier 2+ production VPC; unused/idle NAT gateways; forgotten EIPs.
- **Why**: NAT is billed hourly **and** per GB processed; S3/DynamoDB gateway endpoints are free; cross-AZ routing adds transfer cost; the single-NAT pattern is a hidden SPOF.
- **Not an anti-pattern when**: traffic genuinely needs internet egress and volumes are modest; per-AZ NAT is required for AZ independence in production; an egress-inspection design is deliberate; the gateway runs in **regional availability mode** (`AvailabilityMode=regional`), which expands across AZs automatically, so the single-NAT SPOF concern does not apply (processing-cost concerns still do). See <https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateways-regional.html>.
- **Improvement**: gateway endpoints for S3/DynamoDB; interface endpoints only where traffic volume justifies hourly per-AZ cost; consolidate dev/test egress (single NAT or egress VPC) where availability is not required; for Tier 2+ prod either one zonal NAT per AZ or a regional-mode NAT gateway (check its current constraints, e.g. no private NAT); evaluate NAT instances only for tiny, tolerant workloads; remove idle NATs.
- **Complexity / trade-offs**: Low–Medium. Endpoint policies and DNS; per-AZ interface endpoints have their own cost.

### AP-18 Poor VPC and subnet architecture
- **Signals**: workload in the default VPC; all subnets public; databases in public subnets; tiny CIDR blocks with exhaustion risk (EKS/Lambda ENIs, IP-per-pod); overlapping CIDRs blocking peering/TGW; single subnet per tier or all subnets in one AZ; one flat security group for everything; no NACL/segment strategy; flow logs absent; route tables copied inconsistently.
- **Why**: weak segmentation, scaling limits, hard-to-fix connectivity later, harder incident response.
- **Not an anti-pattern when**: a small workload with public-only subnets behind security groups and no sensitive data, deliberately simple (document it).
- **Improvement**: tiered subnets (public / private app / isolated data) across ≥2 AZs sized for growth (secondary CIDR or prefix delegation for containers), non-overlapping CIDR plan (IPAM), least-privilege SGs referencing SGs, flow logs to central storage.
- **Complexity / trade-offs**: High if retrofitting (re-IPing); plan a new VPC and migrate rather than editing in place.

### AP-19 Overcomplicated networking
- **Signals**: Transit Gateway + VPC peering + PrivateLink + VPNs for a few VPCs; multiple layers of load balancers (CloudFront → ALB → NLB → ALB); proxies/NAT instances re-implementing managed features; many route-table exceptions; interface endpoints for services used rarely in every VPC and AZ; custom DNS forwarding chains.
- **Why**: harder to reason about, more failure points, hourly and per-GB charges at every hop, slower troubleshooting.
- **Not an anti-pattern when**: complexity buys documented isolation, inspection, or multi-account scale.
- **Improvement**: simplify to the fewest hops that satisfy requirements; TGW for many-to-many, peering for few-to-few, PrivateLink for service exposure; shared endpoints in a hub where appropriate.
- **Complexity / trade-offs**: Medium–High; re-routing risks outages—stage carefully.

### AP-20 Cross-region dependencies without business justification
- **Signals**: application in one region calling a database, queue or API in another; S3 buckets or secrets in a different region from their only consumer; replication or backup copies to a region that no requirement mentions; DR region with live cross-region replication costs but no recovery plan.
- **Why**: latency, inter-region transfer charges, reduced availability (dependency on a second region), compliance/data residency questions.
- **Not an anti-pattern when**: required by residency, DR design, or latency to users; global services (IAM, CloudFront, Route 53) are naturally global.
- **Improvement**: co-locate runtime dependencies; keep cross-region only for DR/replication with an owner and a tested plan.
- **Complexity / trade-offs**: Medium (data migration). 

### AP-21 Excessive data movement (cross-AZ, cross-service, internet egress)
- **Signals**: chatty services in different AZs; NLB with cross-zone enabled across heavy traffic; database replicas/clients in different AZs from heavy readers; logs/metrics shipped through NAT to third parties; S3 traffic via public endpoints from private subnets; large CloudFront-less downloads from origin; cross-AZ replication of ephemeral data; inter-region replication of everything.
- **Why**: per-GB transfer charges (inter-AZ, internet egress, inter-region, NAT processing) scale with traffic and are often invisible in architecture diagrams.
- **Not an anti-pattern when**: cross-AZ is the price of required availability (replicas, Multi-AZ writes) and is small relative to value.
- **Improvement**: zone-aware routing (topology-aware routing in Kubernetes, AZ-affinity where it doesn't hurt resilience), gateway endpoints, CloudFront for egress, compression, regional consolidation, caching.
- **Complexity / trade-offs**: Medium. Don't trade away AZ resilience to save transfer fees for critical tiers.

## E. Resilience

### AP-22 Single point of failure in the request path
- **Signals**: a tier in one AZ (EC2 app, single NAT, single AZ subnets for EKS nodes), a single instance/bastion/proxy, a single-AZ DB, single mount target for EFS, a single DNS/Route 53 record without health checks, a unique SaaS/on-prem dependency with no fallback, single account/region as the only recovery location for backups.
- **Why**: failure of one component is a total outage; recovery time is whatever manual processes take.
- **Not an anti-pattern when**: the tier permits it (§4 of the framework) and rebuild/restore meets RTO/RPO.
- **Improvement**: remove the SPOF at the cost-appropriate level (second AZ, managed HA, auto-recovery); document accepted SPOFs.
- **Complexity / trade-offs**: Low–Medium; cost increases (often roughly 2× for the component).

### AP-23 Failure propagation and no graceful degradation (including bad health checks)
- **Signals**: health check that depends on downstream systems (database down → every instance unhealthy → total outage), or health check that always returns 200 (never evicts); ASG health check type EC2 behind ALB; aggressive health thresholds causing flapping or too-lenient ones delaying detection; no bulkheads between tenants/features; one noisy consumer can exhaust a shared queue/DB; error pages instead of degraded modes; retry storms; missing deregistration delay causing dropped requests during deploys.
- **Why**: partial failures become full outages; recovery loops and thundering herds.
- **Not an anti-pattern when**: deep health checks are used deliberately in a *separate* control-plane path (e.g. Route 53 failover) with safeguards.
- **Improvement**: shallow (local readiness) health checks for instance/task eviction, deeper checks for failover decisions only; ELB health checks in ASG; separate queues/pools per criticality; serve stale/cached data when dependencies fail; load shedding.
- **Complexity / trade-offs**: Medium. Requires application changes.

### AP-24 No tested recovery (backups never restored, DR in name only)
- **Signals**: backups exist but no `list-restore-jobs`/restore evidence; retention shorter than RPO or detection window; backups in the same account and KMS key as source (ransomware/credential-compromise blast radius); DR region with partial infrastructure and no runbook; RDS automated backups retention 0–1 days on production; EBS snapshots with no lifecycle or with unknown ownership; no Vault Lock/cross-account copy where threat model demands.
- **Why**: untested backups are hope, not recovery; RTO is unknown and probably wrong.
- **Not an anti-pattern when**: data is reproducible from source (derived/cache data) and that rebuild is itself tested.
- **Improvement**: centralise on AWS Backup plans with cross-account/region copy where warranted; scheduled restore tests with measured RTO/RPO recorded; runbooks; game days.
- **Complexity / trade-offs**: Low (policy) to Medium (restore automation, DR rehearsal). Storage cost for retention/copies.

## F. Structure, governance and consistency

### AP-25 Over-engineering
- **Signals**: multi-region active/active for a tool with low criticality; service mesh, API gateway, event bus, Step Functions and Kubernetes all present for a three-endpoint app; three layers of caching; custom control planes; platform built for 50 teams used by 2; premature abstraction of IaC (modules for single resources).
- **Why**: cost, cognitive load, slower delivery, more failure modes than the requirement justifies.
- **Not an anti-pattern when**: a documented requirement (SLA, regulation, scale forecast) drives it.
- **Improvement**: retire components that do not serve a requirement; adopt the simplest architecture that meets targets.
- **Complexity / trade-offs**: Low–Medium. Document decisions so the simplification isn't reversed by default.

### AP-26 Under-engineering
- **Signals**: no IaC, no CI/CD, no alarms, no backups, single account for everything, root-level shared credentials, no tagging, no DR plan, manual operations for a Tier 2+ workload.
- **Why**: fragile, insecure, unrecoverable, un-auditable.
- **Not an anti-pattern when**: Tier 0/prototype by design and time-boxed.
- **Improvement**: introduce foundational controls first (identity, logging, backup, IaC for the critical path, alarms on symptoms), then iterate.
- **Complexity / trade-offs**: Medium. Sequence by risk; don't import enterprise ceremony into small teams.

### AP-27 Resource fragmentation and unnecessary duplication
- **Signals**: an ALB per microservice with trivial traffic (hourly + LCU floor), many near-identical VPCs/NATs/endpoints, separate log buckets/KMS keys per tiny workload, duplicate environments nobody uses, copies of the same data in multiple stores/regions, many accounts with a handful of resources each and no shared services.
- **Why**: fixed costs and operational overhead multiply with little benefit.
- **Not an anti-pattern when**: separation is for blast-radius, compliance, or cost allocation requirements.
- **Improvement**: consolidate where isolation isn't needed (shared ALB with listener rules, shared VPC endpoints, central log archive), decommission unused environments after confirming owners.
- **Complexity / trade-offs**: Medium. Confirm ownership before removal; consolidation reduces blast-radius isolation.

### AP-28 Poor separation of responsibilities and environments
- **Signals**: production and non-production in the same account and VPC; same IAM roles or credentials used across environments; developers with production write access; shared database between prod and staging; CI/CD role with admin in all accounts; one account for workloads, logs, and security tooling; no SCPs.
- **Why**: blast radius, privilege creep, accidental production changes, weak audit separation.
- **Not an anti-pattern when**: very small team/early stage with compensating controls and a plan; INFO then.
- **Improvement**: multi-account structure (workload accounts per environment, log archive, security tooling), per-environment roles, least-privilege deployment roles, SCP guardrails, break-glass access. See <https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/organizing-your-aws-environment.html>
- **Complexity / trade-offs**: High (account migration). Do incrementally: new workloads first.

### AP-29 Environment inconsistency and configuration drift
- **Signals**: staging/dev differ structurally from prod (single instance vs ASG, different engines/versions, different network topology); stacks reporting drift; resources created by console with similar names; per-environment snowflake parameters; different AMIs or runtime versions; tests passing in staging but failing in prod due to differences.
- **Why**: staging isn't a faithful predictor; manual fixes can't be reproduced; recovery is slower.
- **Not an anti-pattern when**: differences are deliberate scale-downs of identical topology (smaller instance sizes, fewer replicas).
- **Improvement**: define all environments from the same IaC modules with parameterised sizes; drift detection in CI; import or recreate console-created resources; promote artifacts, not rebuilds.
- **Complexity / trade-offs**: Medium. Importing existing resources into IaC takes care; don't `apply` against production without review (this skill never does).

### AP-30 Unnecessary managed-service complexity
- **Signals**: Step Functions/EventBridge Pipes/AppSync/API Gateway chains wrapping a trivial operation; OpenSearch for simple key lookups; Glue/EMR for small ETL that a script or Athena would do; Cognito + custom auth + IAM Identity Center for a single internal app; separate Lambda per HTTP verb; WAF/Shield Advanced/Firewall Manager on an internal service; API Gateway in front of an ALB for no feature (throttling, auth, usage plans) in use.
- **Why**: each service adds configuration surface, IAM, quotas, and cost; debugging crosses more consoles.
- **Not an anti-pattern when**: the managed service removes real operational burden or provides a feature in use.
- **Improvement**: replace with the simpler service that covers the used features (ALB → Lambda/ECS directly; Athena over S3; a single Lambda/handler; Aurora for relational search).
- **Complexity / trade-offs**: Low–Medium. Check for hidden uses (auth, throttling, logging) before removing.
