# draw.io — import guide and regeneration prompts

Ready-made diagrams already exist in `diagrams/` (`*.drawio` for editing, `*.png` / `*.svg` for embedding). Use this page when you want to **open and tidy** them in draw.io, or **regenerate** them from scratch with draw.io's AI feature or any LLM that can emit draw.io XML.

## 1. Use the ready-made files (recommended)

| File | Open in draw.io | Embed |
|---|---|---|
| `diagrams/00-aws-organization-ou-structure.drawio` | File → Open from → Device (or drag the file into the editor) | `…ou-structure.png` |
| `diagrams/01-network-topology.drawio` | same | `…network-topology.png` |
| `diagrams/02-divi-prod-architecture.drawio` | same | `…prod-architecture.png` |
| `diagrams/03-divi-stg-architecture.drawio` | same | `…stg-architecture.png` |

**In Confluence (draw.io app):** create a page, Insert → draw.io Diagram, then in the editor use File → Import from → Device and pick the `.drawio` file; or insert the PNG as an image and attach the `.drawio` file to the page so others can edit it. Page-level images are 2000–2440 px wide: set the image width to full page width and use the "expand" view for reading.

**Important caveats**

1. The `.drawio` files were generated programmatically and were **not opened in draw.io** by the author (the tool was not available). Their layout was verified by rendering the same geometry to SVG/PNG, and the XML was checked for well-formedness, unique ids and valid edge endpoints. Please open each one once and look for problems.
2. If an icon renders as a plain coloured square, its AWS-icon name is not in your draw.io library version. Select the shape → Edit Style → change `resIcon=mxgraph.aws4.<name>` (the names used are in section 4).
3. Each group (account, region, VPC, AZ, subnet, band) is a container: dragging it moves its children. Edges are anchored to shapes, so moving a shape drags its connectors.
4. Regenerating from the scripts is also possible: `python3 diagrams/source/build_account.py` and `build_org.py` rewrite all four diagrams (SVG + `.drawio`); `diagrams/source/render.sh` produces PNGs (needs Google Chrome). Edit values in the scripts rather than in the generated files if you want the change to survive a rebuild.

## 2. Shared style prompt (paste before any diagram prompt)

```text
You are drawing an AWS architecture diagram in draw.io (diagrams.net) using the AWS Architecture Icons 2023 library (shapes named mxgraph.aws4.*).

Rules:
- Canvas: landscape, about 2400 x 1500 px, grid 10, white background.
- Use real AWS group containers, nested in this order: AWS Cloud (one per account) > Region > VPC > Availability Zone columns > public / private subnets. Services that span subnets (ALB, ECS services, Lambda, MSK, RDS subnet group) are drawn as a wide bar or band across the subnets they live in, not repeated per subnet.
- Regional services that are not in the VPC (Amplify, S3, Step Functions, EventBridge, SNS, CloudWatch, Secrets Manager, SSM, KMS, IAM) go in labelled bands inside the Region but outside the VPC.
- Things outside AWS (customer networks, SaaS, GitHub, users) go outside the AWS Cloud box on the left or right, in dashed grey containers.
- Icons 48x48 with the label under the icon: first line = exact resource name in bold, second line = one short detail in small grey text. Use the exact resource names given in the prompt.
- Connections: orthogonal lines, at most two bends, arrowhead at the target, no line crossing a label. Put a small dark numbered circle at the start of each numbered flow. Add a legend.
- Line colours: ERP data path orange #C2570C 3px solid; application traffic grey #5B6770 2px solid; orchestration blue #147EB4 2px dashed; VPN / peering / admin access purple #8C4FFF 2px dashed; deploy / image supply green #3B7D23 2px dashed; external or inferred #8A949E 1.5px dotted.
- Icon colours follow the AWS category: compute/containers #ED7100, database #C925D1, networking and Kafka #8C4FFF, storage #7AA116, application integration and management #E7157B, security #DD344C, front end #DD344C.
- Group colours: AWS Cloud #232F3E solid; Region #147EB4 dashed; VPC #8C4FFF solid; AZ #147EB4 dashed; public subnet #7AA116 with fill #F2F6E8; private subnet #147EB4 with fill #E6F2F8; AWS account #CD2264.
- Mark anything that is not verifiable through AWS APIs as "per overview" or "inferred" in its small grey text.
- Output a single draw.io file (mxfile XML) that opens without errors. Do not invent resources that are not listed.
```

## 3. Diagram prompts

### 3.1 Organization and OU structure — `00`

```text
Title: "AWS Organization — OU structure, Divi accounts and cross-account connections". Subtitle: Divi-relevant OUs/accounts only; organization has 20 accounts in total.

Outer container: AWS Organization o-o1h2b5d1fq (management account 892166101996, no SCPs attached). Under it a Root node "Root (r-r469)" with three tree lines to:

1. Account card "rb-main — management account · 892166101996" containing: AWS Organizations; IAM Identity Center (ssoins-7223815176a971d1, primary region us-east-1, 8 permission sets); CloudFormation StackSet "terraform-bootstrap" (service-managed, creates terraform-state-<account-id> bucket + terraform-state-lock table in us-east-1 of every member account); CloudTrail "org-trail" (organization, multi-region). Text box: default VPCs only 172.31.0.0/16 (ap-southeast-2 vpc-07a7ff37cb5989c72, us-east-1 vpc-0a081c601f65d8290), no workloads.
2. OU "projects" (ou-r469-hbkrb86z; note: 14 accounts, only two shown) containing two account cards side by side:
   - "divi-ai-prod · 832569409513" with VPC icon "VPC divi-prod 10.30.0.0/16 vpc-0bd28e628e263cb74" and text: 3 public /24 (10.30.1-3.0) + 3 private /24 (10.30.4-6.0), AZs 2a/2b/2c, IGW, 3 NAT instances (t3.nano), VGW vgw-022094ced683ab16e -> VPN -> Nocelle 192.168.0.0/24, no VPC endpoints, no flow logs, no peering, default VPC 172.31.0.0/16 unused (vpc-057d805d64b10952d), workload summary.
   - "divi-ai-stg · 398437580121" with VPC icon "VPC divi-stg 10.20.0.0/16 vpc-036f8752bf325cfcd" and similar text plus VGW vgw-0dcd38adec9339642 and VPC peering pcx-011e305428e123226 to 10.40.0.0/16 (account 156358246875); default VPC vpc-069f67711034e5621 unused.
3. OU "management" (ou-r469-qsgln0ox) containing:
   - "shared · 962705291721": ECR icon "ECR — 6 repositories" (divi-engine, divi-middleware, divi-byod-sync, divi-sink-connector, divi-reporting, divi-website; pull + push allowed for prod and stg account roots), S3 "divi-web-contents" (logos, email images, public GetObject), IAM "GitHub OIDC provider + roles" (divi-ecr-role, divi-iac-shared-ecr-policy), text: default VPC 172.31.0.0/16 vpc-09eb020ae6ce094fb only, no workloads.
   - "security · 041558033420": S3 "org-trail-logs-041558033420"; text: delegated administrator for CloudTrail; not inspected.

External band at the bottom (dashed): "Nocelle network 192.168.0.0/24 (SQL Server ERP)", "GuardKite — external AWS account 782218477847", "Peer VPC 10.40.0.0/16 — account 156358246875 (achieve-erp-copernicus-stg) vpc-0a60e962e0d688e5c", "GitHub Actions — org divi-global (OIDC)".

Numbered connections:
1 StackSet: rb-main -> OU projects (blue dashed)
2 org-trail logs: OU projects -> security (blue dashed)
3 ECR pull/push: shared <-> OU projects (green dashed)
4 OIDC ECR push: GitHub -> OU management (green dashed)
5 OIDC Terraform apply: GitHub -> OU projects (green dashed)
6 AssumeRole GuardKite: GuardKite -> OU projects (grey dotted)
7 Site-to-site VPN: divi-ai-prod -> Nocelle (purple dashed); also divi-ai-stg -> Nocelle (unnumbered)
8 VPC peering: divi-ai-stg -> Peer VPC (purple dashed)
Footer text: engineers sign in through IAM Identity Center; each Divi account has AdministrativeAccess and ReadOnlyAccess roles; Terraform state per account in S3 terraform-state-<account-id> + DynamoDB terraform-state-lock (us-east-1).
```

### 3.2 Network topology — `01`

```text
Title: "Network topology across the Divi AWS accounts — VPCs, CIDRs, VPN and peering". Landscape, 2400 x 1170.

Left panel: AWS account "divi-ai-prod · 832569409513 · ap-southeast-2" > VPC "divi-prod 10.30.0.0/16 vpc-0bd28e628e263cb74". Three AZ columns (ap-southeast-2a/b/c). Per AZ: public subnet (divi-prod-public-1..3, 10.30.1.0/24, 10.30.2.0/24, 10.30.3.0/24; ids subnet-0f097393441c15e15, subnet-0cfa112909a482264, subnet-08a72b6b80d57cfc5; shared route table rtb-0a4f62a9605ee66c7, 0.0.0.0/0 -> IGW) holding an EC2 NAT instance icon (divi-prod-nat-instance-1..3, t3.nano, EIP); public-1 also holds EC2 "divi-prod-vpn" (t3.micro, OpenVPN). A wide ALB bar "ALB divi-prod-public — internet-facing — spans the three public subnets" across the public subnets. Private subnets (divi-prod-private-1..3, 10.30.4.0/24, 10.30.5.0/24, 10.30.6.0/24; ids subnet-0cc9970dfa27c43ea, subnet-09b67f5903efcb403, subnet-06e980d3bf83c96ec; route tables rtb-0497cc5794fb1490a, rtb-0157cb29e296556ca, rtb-0015edfb2bc8841ba) each with a bullet list of residents: private-1: divi-prod-bastion, divi-prod-socat, MSK broker, ECS Fargate tasks, Lambda ENIs, MSK Connect worker; private-2: RDS divi-prod-postgres (single-AZ), MSK broker, ECS tasks, Lambda ENIs; private-3: MSK broker, ECS tasks, Lambda ENIs.
IGW icon igw-01b6777db4ff253a0 on the VPC top edge; VGW icon vgw-022094ced683ab16e on the VPC right edge.
Footer text: private route tables: 0.0.0.0/0 -> NAT instance ENI, 192.168.0.0/24 -> VGW; no VPC endpoints, no flow logs.

Right panel: the same for "divi-ai-stg · 398437580121", VPC "divi-stg 10.20.0.0/16 vpc-036f8752bf325cfcd", subnets 10.20.1-3.0/24 public (subnet-0ae0d3be502ed959b, subnet-064eb68fa2ff0199b, subnet-0d8142a2adaa03050; rtb-0e0cd80aaac7dfec6) and 10.20.4-6.0/24 private (subnet-001728a95ee8c833d, subnet-09a556ef2beda6972, subnet-0bf57ebf49ca7282c; rtb-0c6aa3f7dc7c304b1, rtb-0a796d061c660c90c, rtb-0f6fb62002aee0cc6), IGW igw-0740a4c4d4837588d, VGW vgw-0dcd38adec9339642 on the LEFT edge, extra route 10.40.0.0/16 -> pcx; private-1 residents: divi-stg-bastion-manual, div-stg-socat, divi-stg-testing (stopped), MSK broker, ECS tasks, Lambda ENIs, MSK Connect workers (2); private-2: RDS divi-stg-postgres.

Centre: "Internet" icon with edges to both IGWs; dashed container "Nocelle customer network" with "SQL Server ERP 192.168.0.0/24" and text "customer gateways cgw-045c852571155a6dd (prod), cgw-05a17bc4e25d65d19 (stg), BGP ASN 65000, static routing". Purple dashed VPN edges from each VGW to the Nocelle container labelled "vpn-099acf81a915f7c1b · 2 tunnels UP" (prod) and "vpn-0be9465e2a7e430b7 · 2 tunnels UP" (stg).
Far right: dashed "Peer VPC (not inspected)" 10.40.0.0/16 vpc-0a60e962e0d688e5c, account 156358246875 (achieve-erp-copernicus-stg), connected to a VPC-peering icon pcx-011e305428e123226 on the stg VPC right edge ("peering · active").
Bottom strip: account boxes "rb-main 892166101996: default VPCs only 172.31.0.0/16 — ap-southeast-2 vpc-07a7ff37cb5989c72, us-east-1 vpc-0a081c601f65d8290", "shared 962705291721: default VPC vpc-09eb020ae6ce094fb 172.31.0.0/16, IGW igw-0356c44ff30c4454b, no workloads; ECR reached via public endpoint through NAT", "security 041558033420: not inspected", and a "CIDR plan" text box: 10.20.0.0/16 divi-stg; 10.30.0.0/16 divi-prod; 10.40.0.0/16 peer VPC (peered to divi-stg only); 192.168.0.0/24 Nocelle (both VPNs); 172.31.0.0/16 default VPCs (unused, overlapping). Egress via NAT instances (not NAT Gateways). Not present: Transit Gateway, VPC endpoints, Route 53 zones/resolver, flow logs.
```

### 3.3 Production architecture — `02`

```text
Title: "Divi production — high-level AWS architecture". Account divi-ai-prod (832569409513), region ap-southeast-2.

OUTSIDE AWS, left column: Client users (browsers); Engineers (OpenVPN client); dashed container "Customer networks": Nocelle (SQL Server ERP, 192.168.0.0/24) and Intrim (D365 F&O, BYOD Azure SQL); dashed container "Shared account 962705291721" with ECR "6 repos" (divi-engine, divi-middleware, divi-byod-sync, divi-sink-connector, divi-reporting, divi-website); dashed container "GitHub (org divi-global)" with GitHub Actions (OIDC).
OUTSIDE AWS, right column: PostHog, Cloudflare DNS, HubSpot / Amazon SES, PagerDuty, OpenAI API.

AWS Cloud "divi-ai-prod (832569409513)" > Region ap-southeast-2:
Top band "Front end and object storage": Amplify "divi-prod-mt-ui" (domains intrim/nocelle.diviglobal.ai), Amplify "divi-prod-admin-portal" (divi-admin.diviglobal.ai), S3 "7 buckets" (hosting, data, cdc, engine-state, audit, alert-excel-exports, glue-assets).
VPC "divi-prod 10.30.0.0/16 (vpc-0bd28e628e263cb74)" with IGW (igw-01b6777db4ff253a0) at the left edge and VGW "divi-prod-nocelle" (vgw-022094ced683ab16e) at the left edge lower down. Three AZ columns:
 - public subnets divi-prod-public-1/2/3 (10.30.1.0/24, 10.30.2.0/24, 10.30.3.0/24). A wide ALB bar "ALB divi-prod-public, internet-facing, HTTP 80 -> 301 -> HTTPS 443, ACM cert, 11 host-header rules, hosts divi-prod-<service>.diviglobal.ai". Under it EC2 "divi-prod-vpn" (t3.micro, OpenVPN, EIP) in public-1 and EC2 NAT instances divi-prod-nat-instance-1/2/3 (t3.nano, EIP), one per AZ.
 - private subnets divi-prod-private-1/2/3 (10.30.4.0/24, 10.30.5.0/24, 10.30.6.0/24). Three wide bands across them, top to bottom:
   a) "AWS Lambda — VPC-attached": 7 icons: divi-prod-admin-portal-backend, divi-prod-mt-auth, divi-prod-mt-config, divi-prod-mt-financials, divi-prod-mt-perf-track, divi-prod-mt-report-generator (Python 3.13), divi-prod-mt-tracker (Java 21 unless noted).
   b) "Data and streaming": EC2 divi-prod-socat (TCP relay :1433, inferred), MSK Connect "debezium-connector" (Debezium SQL Server, outside Terraform per overview), MSK "divi-prod-cdc" (Kafka 3.9.x, 3 x kafka.m5.large, 350 GiB, TLS + IAM), RDS "divi-prod-postgres" (PostgreSQL 17.9, db.m5.large, 1000 GiB gp3, single-AZ 2b), EC2 divi-prod-bastion.
   c) "ECS cluster divi-prod — Fargate + Fargate Spot": services divi-prod-website, divi-prod-mt-reporting, divi-prod-nocelle-engine-v2-job-worker, divi-prod-sink-connector (2 tasks); and two text boxes "Batch tasks — intrim (9 task defs): middleware (= sync_to_public), byod-sync, engine-v2 runall / daily-forecast / model-6 / model6-preview / morning-pass / refresh-materialized / select-forecast-champions" and "Batch tasks — nocelle (8 task defs): middleware + the same seven engine tasks".
Bottom band "Orchestration and observability": IAM OIDC + roles, EventBridge Scheduler (3 schedules), Step Functions (7 state machines), EventBridge rules (3), SNS divi-prod-cloudwatch, CloudWatch (18 alarms, 36 log groups), Secrets Manager (14), SSM Parameter Store (15), KMS (alias/divi-prod-postgres).

Numbered flows:
1 Users -> Amplify (HTTPS, SPA)
2 Users -> IGW -> ALB bar (HTTPS API calls, JWT + client subdomain)
3 ALB bar -> Lambda band (host-header)
4 ALB bar -> ECS band (host-header -> IP target groups), routed down the right edge of the VPC
5 Lambda band -> RDS
6 Nocelle -> VGW (site-to-site VPN, 2 tunnels, static 192.168.0.0/24) [purple]
7 socat -> MSK Connect (TCP 1433) [orange]; VGW -> socat [purple]
8 MSK Connect -> MSK (topic per table mssql.*) [orange]
9 MSK -> sink-connector service (consume) [orange]
10 sink-connector -> RDS (writes source_sync) [orange]
11 Intrim -> ECS band (byod-sync, SQL login via NAT) [orange]
12 ECS band -> RDS (batch tasks, job-worker, reporting)
13 EventBridge Scheduler -> Step Functions (daily cron, Australia/Adelaide) [blue]; EventBridge rules -> Step Functions [blue]
14 Step Functions -> ECS band (ecs:RunTask.sync) [blue]
15 ECS band -> OpenAI (LLM calls via NAT instances)
16 CloudWatch -> SNS (alarm) [blue]
17 Engineers -> divi-prod-vpn (OpenVPN) [purple]
18 ECR -> ECS band (image pull, cross-account) [green]
19 GitHub Actions -> ECR (push images, OIDC) [green]
20 GitHub Actions -> IAM OIDC + roles (Terraform apply) [green]
Add a legend and a footer: "items marked 'per overview' or 'inferred' are not verifiable through AWS APIs".
```

### 3.4 Staging architecture — `03`

```text
Use the production prompt (3.3) with these changes. Title "Divi staging — high-level AWS architecture"; account divi-ai-stg (398437580121); VPC "divi-stg 10.20.0.0/16 (vpc-036f8752bf325cfcd)"; subnets 10.20.1.0/24 ... 10.20.6.0/24; IGW igw-0740a4c4d4837588d; VGW vgw-0dcd38adec9339642; resource names use the prefix divi-stg-.

- Top band: 7 Amplify apps (divi-stg-mt-ui [stg branch, 6 domains], divi-stg-beta-ui, divi-stg-v3-ui, divi-stg-admin-portal, divi-stg-demo-test, divi-stg-demo-ui-concept, demo) and S3 "9 buckets".
- ALB divi-stg-public: 30 host-header rules, hosts under achieve-erp.com (sink connectors on diviglobal.ai), ACM certificate achieve-erp.com.
- Lambda band (19 VPC-attached functions in 5 groups): divi-stg-mt-* (6), divi-stg-beta-* (5), divi-stg-v3-* (6), divi-stg-admin-portal-backend, divi-stg-alert (Python 3.12); note: not VPC-attached: divi-stg-client-onboarding, divi-stg-resource-scheduler.
- Data band: EC2 div-stg-socat, MSK Connect "debezium-connector" (Nocelle, via socat) AND a second MSK Connect "debezium-dug" (SQL Server on RDS in ap-southeast-1, reached over the internet via NAT; plugin debezium-sqlserver-3-5-2-updated), MSK "divi-stg-cdc" (3 x kafka.m5.large, 200 GiB), RDS "divi-stg-postgres" (PostgreSQL 17.9, db.m5.large, 1250 GiB, single-AZ 2b), EC2 divi-stg-bastion-manual, EC2 divi-stg-testing (r5a.2xlarge, stopped).
- Customer networks add "DUG — Achieve ERP, SQL Server on RDS in ap-southeast-1 (outside this account)" with an orange line (flow 21) to the debezium-dug connector.
- ECS cluster divi-stg: 7 services — divi-stg-website, divi-stg-mt-reporting, divi-stg-intrim-engine-v2-job-worker, divi-stg-nocelle-engine-v2-job-worker, divi-stg-v3-engine-v2-job-worker, divi-stg-sink-connector (2 tasks), divi-stg-dug-sink-connector (3 tasks). Text box with batch task definitions per client/variant: intrim 9, nocelle 8, dug 8 (schedule disabled), beta 6, v3 6.
- Orchestration band: EventBridge Scheduler (4 schedules, dug-pipeline disabled), Step Functions (14), EventBridge rules (6), SNS divi-stg-cloudwatch (email + https), CloudWatch (30 alarms, 77 log groups), Secrets Manager (15), SSM (15), KMS alias/divi-stg-postgres.
- Right side: a VPC-peering icon "pcx-011e305428e123226" on the VPC edge connected by a purple dashed line to a dashed container "Peer VPC (not inspected) 10.40.0.0/16, account 156358246875 (achieve-erp-copernicus-stg)"; a dashed grey container "Present but idle": ALB target groups achieve-* / nocelle-achieve-* / ai-data-sync-dev / aipartner-mapping-* (0 targets), Lambda Achieve-AI-User-Lambda (ap-southeast-1), EC2 divi-stg-testing (stopped), security groups/roles for Airbyte, Bladepipe, DMS, Glue, GuardKite role trusted by external account 782218477847.
```

## 4. AWS icon names used in the generated files

| Service | `resIcon` / shape | Colour |
|---|---|---|
| ECS Fargate service | `fargate` | #ED7100 |
| Lambda | `lambda` | #ED7100 |
| EC2 (NAT, VPN, socat, bastion) | `ec2` | #ED7100 |
| ECR | `ecr` | #ED7100 |
| RDS | `rds` | #C925D1 |
| MSK / MSK Connect | `managed_streaming_for_kafka` | #8C4FFF |
| ALB | `elastic_load_balancing` | #8C4FFF |
| Internet gateway / VPN gateway | `internet_gateway` / `vpn_gateway` | #8C4FFF |
| VPC (peer VPC, peering) | `vpc` | #8C4FFF |
| Amplify | `amplify` | #DD344C |
| S3 | `s3` | #7AA116 |
| Step Functions | `step_functions` | #E7157B |
| EventBridge | `eventbridge` | #E7157B |
| SNS | `sns` | #E7157B |
| CloudWatch | `cloudwatch_2` | #E7157B |
| Systems Manager Parameter Store | `systems_manager_parameter_store` | #E7157B |
| CloudFormation, CloudTrail, Organizations | `cloudformation`, `cloudtrail`, `organizations` | #E7157B |
| Secrets Manager, KMS, IAM, IAM Identity Center | `secrets_manager`, `key_management_service`, `identity_and_access_management`, `iam_identity_center` | #DD344C |
| Users, engineers, servers, SaaS | `users`, `user`, `traditional_server`, `client`, `internet` (plain shapes, dark fill) | #232F3D |

Group shapes used: `group_aws_cloud_alt`, `group_region`, `group_vpc2`, `group_security_group` (subnets), `group_account`, `group_corporate_data_center`.
