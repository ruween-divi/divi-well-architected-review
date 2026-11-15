# Assessment Framework

How to reason about an architecture against the five AWS Well-Architected pillars, and how to turn observations into calibrated
findings. Primary reference: <https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html>

Contents: 1 Stance · 2 Component interrogation · 3 Pillar guides (Ops, Security, Reliability, Performance, Cost) ·
4 Availability and DR proportionality · 5 Severity (definitions, matrix, modifiers, calibration) · 6 Confidence · 7 Categories ·
8 Cross-pillar trade-offs · 9 Recommendation quality bar · 10 Roadmap prioritisation · 11 Well-Architected best-practice mapping

Scope: the five pillars below. **Sustainability**, the framework's sixth pillar, is out of scope unless the user asks; state that in
Assessment Limitations. Many cost recommendations (removing idle resources, rightsizing, Graviton, storage tiering) also reduce footprint;
you may note that without assessing the pillar. Reference: <https://docs.aws.amazon.com/wellarchitected/latest/sustainability-pillar/sustainability-pillar.html>

---

## 1. Stance

You are reviewing as a senior architect who has to defend every recommendation to the people who run the system.

- **Evidence over assumption.** If you did not observe it, you do not know it. "No alarms found" after a successful call is a finding; "alarm call denied" is a limitation.
- **Workload fit over generic best practice.** A 3-AZ, multi-region, Kubernetes-based design is *worse* than a single-AZ Fargate service if the workload is an internal tool with a 24-hour RTO.
- **Architecture over checklists.** The most valuable findings come from how resources interact (a Multi-AZ database behind a single-AZ app tier; five microservices sharing one database; a NAT gateway carrying S3 traffic).
- **Both directions of error.** Report *over-engineering* (cost and operational burden without a requirement) and *under-engineering* (risk without a mitigating requirement) with equal rigour.
- **Credit what is good.** Every pillar section lists positive observations. A review that finds nothing right is as unreliable as one that finds nothing wrong.
- **Challenge, don't presume.** An unusual choice may be deliberate. Ask before declaring it wrong; if unanswerable, say what you assumed and how that affects confidence.
- **Do not recommend change merely because an alternative exists.** A recommendation needs: the requirement or evidence that motivates it, a measurable or clearly-argued benefit, the operational implication, and the trade-off.

## 2. Component interrogation protocol

Run the ten questions below for every **major component** (each distinct compute platform, data store, network construct, integration service, and each security/ops control plane). Record answers briefly in the component table of the review's Service Selection section. "Unknown" is a legitimate answer and creates a question for the user.

| # | Question | Look at |
|---|---|---|
| 1 | Why was this service chosen? (stated or inferred reason; team skills, history, requirement) | tags, age, user input, sibling components |
| 2 | Is it the right service for the workload's characteristics? | `references/aws-service-selection.md` decision guide for the domain |
| 3 | Is the configuration right for the *actual* requirement (size, engine, storage, capacity mode, timeouts, retention)? | config vs metrics |
| 4 | Is it unnecessarily complex for what it does? | count of moving parts vs workload size; team size |
| 5 | Is there a simpler, more reliable, or cheaper alternative that still meets the requirement? | decision guide; only if benefit is quantifiable |
| 6 | Does it show an anti-pattern? | `references/architecture-anti-patterns.md` |
| 7 | **What happens when it fails?** (instance, AZ, dependency, region) Blast radius, detection, recovery path, who is paged. | dependency graph, health checks, alarms, backups |
| 8 | **What happens when demand rises 2×, 10×?** First bottleneck, scaling mechanism, quota ceiling, cost curve. | ASG/service scaling, quotas, metrics headroom |
| 9 | Is it over- or under-provisioned? | 14–30 day utilisation (avg and max), burstable credits, throttling, queue age |
| 10 | What operational overhead does it add (patching, upgrades, capacity management, on-call, expertise)? | managed vs self-managed, version currency, IaC coverage |

For the failure and scale questions (7, 8), trace the request path end to end and name the weakest link, rather than assessing each box in isolation.
Produce at least one *failure-path* statement per workload, e.g. "If `us-east-1a` is lost: web tier degrades to 1 of 2 instances (ASG replaces in ~N min — **Inferred**); the RDS primary is in `us-east-1a` and Multi-AZ is off, so the database is unavailable until restored from backup (**Confirmed**) — RTO is the restore time, never tested."

## 3. Pillar guides

Each guide lists: what to evaluate, evidence, weakness signals (candidate findings), strength signals (positive observations), and what *not* to flag. Weakness signals are prompts, not automatic findings: confirm with context before reporting.

### 3.1 Operational Excellence
<https://docs.aws.amazon.com/wellarchitected/latest/framework/operational-excellence.html>

Evaluate: infrastructure as code coverage and drift; deployment method (pipelines, blue/green, canary, rollback); configuration management and
environment parity; observability (metrics, logs, traces, alarms, dashboards, SLOs); centralised logging; incident response (alarm → action → on-call, runbooks, post-incident review);
change management; operational automation (patching, scaling, remediation); backup/recovery procedures; tagging/ownership; complexity and maintenance burden.

Weakness signals: resources with no IaC provenance (no CloudFormation/Terraform tags, `Name`-only tags) in production; stacks with `DRIFTED` status; prod and non-prod built differently;
alarms with no actions or only on low-value metrics (no alarms on error rate/latency/saturation); log groups without retention or without central aggregation; no alarm on backup failure;
no runbooks/SSM documents/automation; deployment by SSH/console; no rollback path; unmanaged AMI/patch lifecycle; deprecated runtimes, engine versions and Kubernetes versions; one-off snowflake resources; no tagging standard.

Strength signals: >80% of resources traceable to IaC; pipelines with approvals and automated rollback; alarms tied to symptoms and routed to an on-call tool; dashboards per workload;
SSM-managed fleet with patch baselines; consistent tags; automated remediation; documented and rehearsed recovery.

Do not flag: absence of a specific tool (CodePipeline vs GitHub Actions); IaC absent in a throwaway sandbox; evidence that lives outside AWS you cannot see (state "not visible from AWS APIs" and ask).

### 3.2 Security
<https://docs.aws.amazon.com/wellarchitected/latest/framework/security.html>

Evaluate: identity (human and machine; SSO/Identity Center; long-lived keys; MFA; root); least privilege and permission boundaries/SCPs; cross-account trust; account structure and
prod/non-prod separation; network exposure and segmentation; data protection (encryption at rest/in transit, KMS key policy, secret storage and rotation); detection (CloudTrail, Config, GuardDuty, Security Hub, alerting);
infrastructure protection (WAF/Shield where an internet-facing attack surface exists, egress control); vulnerability and patch management; incident response readiness.

Weakness signals: root with access keys or no MFA; IAM users with console + no MFA, or old/unused keys; `"Action":"*"`/`"Resource":"*"`/`iam:*`/`sts:AssumeRole` on `*` without conditions; trust policies for `*` or foreign accounts without `ExternalId`/org conditions;
public S3 (policy status `IsPublic`, ACL grants to AllUsers) or account-level Block Public Access off; RDS/OpenSearch/Redshift/ElastiCache publicly reachable; security groups open to the world on SSH/RDP/DB/management ports;
public IPs on instances that need none; IMDSv1 enabled; unencrypted EBS/RDS/S3/SNS/SQS holding sensitive data; hardcoded secrets (names of env vars like `*_PASSWORD`, `*_KEY` with literal values — report presence, never value);
no multi-region CloudTrail / no log file validation / trail bucket unprotected; Config or GuardDuty absent in active regions; shared credentials or shared roles across environments; production reachable from non-production network paths;
unrestricted egress (`0.0.0.0/0` all ports) from sensitive tiers; unpatched/unmanaged instances; CMKs with `*` principals or no rotation where policy demands it.

Strength signals: SSO with short-lived credentials; SCP guardrails; multi-account with separate prod; organisation trail to a locked-down log-archive account; GuardDuty/Security Hub/Config org-wide with a delegated admin; private subnets with endpoints; IMDSv2 enforced; default encryption; secret rotation.

Severity guidance: confirmed internet-exposed sensitive data or admin surface → CRITICAL; broad-but-internal privilege or missing detective control in production → HIGH; hygiene in non-production → LOW/MEDIUM.
Do not flag: public S3 buckets that are intentional static-website/CDN origins *with* the expected policy (note as INFO); security groups open on 80/443 to the world on an internet-facing load balancer.

### 3.3 Reliability
<https://docs.aws.amazon.com/wellarchitected/latest/framework/reliability.html>

Evaluate: foundations (quotas, network topology, IP space); workload architecture (service decomposition, dependency isolation, sync vs async); change management (scaling, deployments, capacity); failure management (backup, DR, fault isolation, testing).

Evaluate specifically: AZ distribution of *each tier*; single points of failure across the whole request path; Auto Scaling presence and correctness; load balancer health checks (path, depth, thresholds, grace periods);
database HA (Multi-AZ instance/cluster, Aurora replicas, failover time vs requirement); backup policy vs RPO, backup *restore tests*; DR strategy vs RTO/RPO; queue-based decoupling and DLQs; retry/timeout/backoff behaviour (unbounded retries, retry storms, missing jitter, missing timeouts);
circuit breaking and graceful degradation; blast radius (shared dependencies, shared databases, single account for everything); capacity headroom and service quota ceilings.

Weakness signals: single-instance production (no ASG or an ASG of size 1 with no self-healing meaning); stateful data on instance store or a single EBS volume without snapshots; app tier multi-AZ but DB single-AZ (or the reverse); ASG using EC2 health checks behind an ALB; health check pointing at a path that always returns 200 or one that fails when a downstream dependency is down (causing fleet-wide eviction);
ASG with minimum 1; scaling policy absent or tuned on the wrong metric; backups configured but retention shorter than RPO/recovery window or never restored; NAT gateway in one AZ serving all AZs; synchronous chains of 3+ services with no timeouts; SQS without DLQ or with visibility timeout shorter than the consumer's processing time; Lambda with no concurrency limits in front of a fragile database; RDS connections exhausted without a proxy;
region-pinned design with no stated RTO; DR region that exists but has no data replication, capacity or runbook; quotas at >80% of limit with growth; EKS/ECS cluster on a single AZ subnet.

Strength signals: stateless tiers behind health-checked load balancers across ≥2 AZs with scaling policies; managed multi-AZ data stores sized for failover; tested restore with measured RTO/RPO; DLQs with alarms; timeouts and bounded retries with jitter; deployment circuit breakers/rollback; documented, rehearsed DR proportionate to criticality.

**Do not automatically recommend Multi-AZ or Multi-Region.** Apply §4.

### 3.4 Performance Efficiency
<https://docs.aws.amazon.com/wellarchitected/latest/framework/performance-efficiency.html>

Evaluate: compute selection (instance family/generation/architecture, containers vs functions); storage (EBS type/IOPS/throughput vs measured I/O; S3 access patterns); database (engine, class, storage, IOPS, connection management, query performance via Performance Insights if enabled, caching);
network (placement, cross-AZ/region chatter, load balancer type, CDN, endpoints); scaling model (horizontal vs vertical, scaling latency vs traffic shape); data access patterns; Lambda memory/timeout/concurrency/cold starts; container sizing (requests vs usage); monitoring of latency and saturation; adoption of newer instance generations and Graviton where compatible.

Weakness signals: sustained CPU >70–80% average or frequent 90%+ on a single instance with no scaling; memory pressure (`SwapUsage`, low `FreeableMemory`); burstable instances with exhausted credits or surplus-credit charges; previous-generation families; EBS `VolumeQueueLength` high / `BurstBalance` depleting / IOPS near limit, or io1/io2 provisioned far above observed IOPS, or gp2 volumes whose burst model mismatches a steady workload; `ReadLatency`/`WriteLatency` elevated; connection counts near `max_connections`;
no cache in front of read-heavy, repetitive database queries; static assets served from the origin with no CDN; Lambda at default 128 MB with long duration (CPU-starved) or memory far above peak use; Lambda used as a long-running or high-throughput steady worker; large cross-AZ chatter between chatty services; ALB for pure TCP/TLS passthrough needing static IPs (NLB) or NLB where L7 routing is needed;
synchronous request chains where async would decouple; DynamoDB throttling or hot partitions; SQS consumers lagging (`ApproximateAgeOfOldestMessage`); under-requested pods causing noisy neighbours.

Strength signals: right-sized, current-generation (often Graviton) instances with headroom 30–50% at peak; gp3 with provisioned IOPS only where measured; caches with healthy hit rates; CDN with high cache-hit ratio; scaling policies tracking request or queue metrics; documented load tests.

Do not flag: underutilisation as a *performance* issue (it is a cost issue); a single large instance where licensing/stateful constraints demand it.

### 3.5 Cost Optimization
<https://docs.aws.amazon.com/wellarchitected/latest/framework/cost-optimization.html>

Evaluate: spend by service/account/region/tag; utilisation vs provisioned; pricing model coverage (Savings Plans/RIs/Spot); idle and orphaned resources; data transfer; storage tiers and retention; logging/monitoring spend; architecture choices with recurring cost (NAT, cross-AZ, per-AZ endpoints, always-on non-prod);
managed vs self-managed total cost; tagging for cost allocation; governance (budgets, anomaly detection).

Full method, thresholds and savings arithmetic are in `references/cost-optimization.md`. Every cost finding carries the seven required fields (resource, current configuration, observed utilisation, current spend, alternative, estimated saving, risks) with measured/estimated/not-quantified labels.

Do not flag: reserved capacity that is deliberate headroom for a documented peak; extra spend that buys a stated reliability or security requirement; savings that need a risky change to a critical workload for trivial gain.

## 4. Availability and DR proportionality

Never recommend redundancy without tying it to a requirement. Establish (from the user, tags, or explicit assumption):

- **Criticality tier**, **availability target**, **RTO**, **RPO**, **compliance constraints**, **budget sensitivity**.

Typical starting points (to be confirmed against the stated requirement, not applied blindly):

| Tier | Example | Compute | Data | Backup/DR (order of magnitude) |
|---|---|---|---|---|
| 0 · Dev/test/sandbox | feature branches, experiments | single AZ acceptable; schedule off-hours shutdown | single-AZ DB OK; IaC rebuild is the recovery | no DR; rebuild from code |
| 1 · Internal / low-impact | internal tools, batch reports | ≥2 AZ if cheap (ASG/Fargate); single instance + auto-recovery acceptable | Multi-AZ if downtime is disruptive; PITR backups | backup & restore: RTO hours, RPO ≤ backup interval |
| 2 · Business-important / customer-facing | production web/API | ≥2 AZ everywhere, health-checked, autoscaled | Multi-AZ/cluster; tested backups; cross-account/region copies for ransomware resilience | pilot light or warm standby only if RTO < hours |
| 3 · Mission-critical | revenue/regulatory critical | N+1 per AZ, 3 AZ where quorum matters; static stability | multi-AZ + cross-region replication where RPO demands | warm standby / active-active: RTO minutes, RPO seconds–minutes — justified by cost of downtime |

AWS DR strategies in increasing cost/complexity (<https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-workloads-on-aws.html>): backup & restore → pilot light → warm standby → multi-site active/active.
Match strategy to RTO/RPO. Report **mismatches in both directions**:

- *Under-built*: stated RTO of 15 minutes but the only recovery path is a manual snapshot restore.
- *Over-built*: a cross-region active/active stack for a tool with a two-day tolerable outage.

Remember what Multi-AZ does and does not provide: it protects against instance/AZ failure, not against data corruption, bad deployments, credential compromise, or deletion; those need backups, deployment safety, and access control.
Multi-Region adds data consistency, failover, testing and cost complexity; require an explicit requirement (regulatory, latency, RTO that AZ-level design cannot meet).

## 5. Severity

Assign severity from impact × likelihood × exposure, then adjust for environment and compensating controls. Do not inflate to make a report look important; a short list of correct HIGHs is worth more than 40 mislabelled ones.

| Severity | Definition | Typical examples (if confirmed) |
|---|---|---|
| **CRITICAL** | Immediate, significant security exposure, major outage risk or severe architectural failure that can plausibly cause serious harm *now*. | Internet-reachable database or admin port with sensitive data; public bucket with sensitive data; active root access keys; only copy of production data with no backup; `*:*` admin role assumable by an unknown/external principal. |
| **HIGH** | Significant security, reliability, performance or financial concern needing prompt action. | Production single point of failure with a real RTO requirement; untested backups for critical data; no CloudTrail/GuardDuty in a production account; broad IAM privilege escalation paths; cost waste that is a large share of account spend (e.g. idle resources ≥ ~10% of monthly spend). |
| **MEDIUM** | Meaningful improvement or moderate operational risk. | Missing alarms on key signals; outdated engine nearing end of support; gp2→gp3; no retention on high-volume log groups; moderate rightsizing (≈2–10% of spend); IMDSv1 on non-internet-facing hosts. |
| **LOW** | Minor optimisation or best-practice gap. | Tagging gaps; small idle resources; stale snapshots of small volumes; non-prod hygiene. |
| **INFORMATIONAL** | Awareness item; not necessarily a problem. | Intentional public bucket, deliberate single-AZ non-prod, observation needing user confirmation, positive context. |

### 5.1 Severity matrix (security, reliability, performance, operations)

Rate **impact** (what happens if the weakness is exploited or the failure occurs, for *this* workload's tier) and **likelihood** (how exposed and how
probable), then read the severity. Write both ratings into the finding ("Impact: Severe · Likelihood: Likely → CRITICAL").

| Impact ↓ / Likelihood → | **Likely** — exposed/exploitable now, or the failure is expected in normal operation (e.g. an AZ event, a deploy, a traffic peak) | **Possible** — needs one further condition (credential leak, unusual load, a second fault) | **Unlikely** — needs several conditions or privileged insider action |
|---|---|---|---|
| **Severe** — sensitive data breach, account takeover, prolonged outage or data loss of a Tier 2–3 workload, regulatory breach | CRITICAL | HIGH | MEDIUM |
| **Significant** — limited data exposure, outage of a Tier 1–2 component with recovery under RTO uncertainty, serious degradation | HIGH | MEDIUM | LOW |
| **Moderate** — short degradation, contained exposure, operational toil, inefficiency | MEDIUM | LOW | LOW |
| **Minor** — hygiene, best-practice gap with no realistic harm | LOW | LOW / INFORMATIONAL | INFORMATIONAL |

**Cost findings** use materiality instead of the matrix: HIGH when the waste/opportunity is a large share of account spend (default ≳10%) or clearly large in absolute terms for the account; MEDIUM ≈2–10%; LOW <2%. State the basis.

### 5.2 Modifiers

Apply and **state** the adjustment in the finding:
- Non-production environment: usually reduce one level (not for credentials or data that is real production data).
- Compensating control verified (e.g. security group open but NACL/WAF/private subnet blocks path): reduce one level and cite it.
- Exposure not verified (cannot determine reachability): do not exceed MEDIUM; mark confidence Low and say what would confirm.
- Unknown criticality: assess against the stated assumption and say so; avoid CRITICAL/HIGH for reliability gaps whose business impact is unknown.
- Percent-of-spend thresholds above are defaults; adapt to the user's scale and state the basis.
- Missing permission or missing data is never a finding by itself; it belongs in Limitations.
- Centrally managed controls (delegated-admin GuardDuty/Security Hub, organisation trail, SCPs) count as compensating controls once verified.

### 5.3 Calibration check (run in Phase 5)

- CRITICAL findings are rare in most reviews (typically zero to a handful). If CRITICAL + HIGH exceed roughly a third of all findings, re-examine each: is exposure actually verified, is criticality established or only assumed, is a compensating control being ignored?
- The **same condition gets the same severity** across accounts and regions unless context differs (and the difference is stated).
- Every CRITICAL/HIGH must have High or Medium confidence; a Low-confidence item is a *Potential concern* at most MEDIUM until verified.
- Re-read the five highest-severity findings as the account owner would: would they agree the impact and likelihood are fair?

## 6. Confidence

| Level | Meaning |
|---|---|
| **High** | Directly observed in AWS data, behaviour verified against current AWS documentation, and no material unknown about workload context. |
| **Medium** | Directly observed but the judgement depends on workload context you had to assume, or the metrics window was short/partial, or documentation was not re-verified. |
| **Low** | Inferred from indirect evidence, partial visibility (permissions), very short history, or an unverified assumption about intent. Present as "potential concern – verify". |

Separate **Confirmed issues** (evidence shows the problem) from **Potential concerns** (risk that depends on facts not yet known) in the report. Potential concerns should list the specific question or check that would resolve them.

## 7. Finding categories

Use one slug per finding in the `Category` field (add new slugs sparingly and consistently):

`iam-least-privilege` · `identity-and-access` · `account-structure` · `network-exposure` · `network-design` · `encryption` · `secrets-management` · `detective-controls` · `logging-and-audit` · `vulnerability-management` ·
`high-availability` · `fault-isolation` · `backup-and-recovery` · `disaster-recovery` · `scaling-and-capacity` · `health-checks` · `resilience-patterns` · `service-quotas` ·
`compute-sizing` · `storage-performance` · `database-performance` · `caching-and-delivery` · `network-performance` · `service-selection` · `architecture-anti-pattern` ·
`idle-resources` · `rightsizing` · `pricing-model` · `data-transfer-cost` · `storage-lifecycle` · `observability-cost` · `architecture-cost` ·
`iac-and-drift` · `deployment-and-release` · `monitoring-and-alerting` · `incident-response` · `runbooks-and-docs` · `config-management` · `operational-complexity` · `tagging-and-ownership` · `lifecycle-and-versions`

## 8. Cross-pillar trade-offs

Make trade-offs explicit in recommendations. Common tensions:

- **Cost ↔ Reliability**: Multi-AZ doubles database cost; single NAT saves money but is an AZ SPOF. Recommend what the tier requires, show the cost delta.
- **Security ↔ Operations**: tighter egress controls and per-service VPC endpoints add management and per-AZ endpoint cost.
- **Performance ↔ Cost**: caching and provisioned capacity cost money; justify with measured latency/throughput need.
- **Simplicity ↔ Resilience**: every added component is a new failure mode. Prefer managed, regional, multi-AZ-by-default services before building failover.
- **Cost ↔ Security**: GuardDuty/Config/flow logs have ingestion costs; do not recommend turning them off to save money unless coverage is demonstrably redundant.
- **Rightsizing ↔ Reliability**: do not right-size below observed peak plus failover headroom (N-1 AZ capacity).

## 9. Recommendation quality bar

Each recommendation must state: (1) the requirement or evidence it responds to, (2) the specific change, (3) the expected benefit (measured/estimated/qualitative, labelled), (4) implementation complexity (Low = config change, no downtime; Medium = planned change with testing; High = re-architecture or migration),
(5) risks, downtime and rollback, (6) prerequisites/dependencies on other findings, (7) how to verify success. If any of these cannot be filled honestly, say so rather than padding.
Recommendations are advice for humans to evaluate and implement; the skill never makes the change.
Distinguish **containment** (a quick, reversible step that removes most of the risk now, e.g. restrict a world-open security group) from the **fix**
(the durable change, e.g. move the host behind Session Manager). Critical exposures get a containment step in the Immediate horizon.

## 10. Roadmap prioritisation

Order the remediation roadmap reproducibly:

1. **Score** each finding: `priority = severity weight × confidence factor ÷ complexity`, with severity CRITICAL 5 · HIGH 4 · MEDIUM 3 · LOW 2 · INFORMATIONAL 1;
   confidence High 1.0 · Medium 0.8 · Low 0.5; complexity Low 1 · Medium 2 · High 3. Cost findings may add +1 when the estimated saving is material and Measured.
2. **Assign horizons**: *Immediate (0–7 days)* — every CRITICAL (at least its containment step) and HIGH findings with Low complexity;
   *Short term (1–4 weeks)* — remaining HIGH, plus MEDIUM quick wins (Low complexity); *Medium term (1–3 months)* — MEDIUM with Medium complexity and structural cost work;
   *Long term (3+ months)* — High-complexity re-architecture and migrations.
3. **Apply dependencies**: prerequisites move earlier (e.g. tagging and backups before rightsizing; IaC import before environment-consistency work; rightsizing before Savings Plans).
4. **Group** related actions into work packages owners can schedule (e.g. "network egress package": gateway endpoints + NAT consolidation + flow logs).
5. Within a horizon, sort by score; show the score so the order can be challenged.

## 11. Well-Architected best-practice mapping (optional)

Where you can verify it, record the official best-practice ID a finding relates to in the finding's *WA best practice* field (identifiers look like
`SEC02-BP04` or `REL10-BP01`; pillar code, question number, best-practice number). Take the ID from the framework pages you consulted; **never guess an
ID** — leave the field as "—" if unverified. The mapping lets owners track remediation as improvement items or milestones in the AWS Well-Architected Tool.
