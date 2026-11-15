"""Builds the per-environment architecture diagrams (prod + staging) from one layout function.

Facts come from live read-only AWS API calls on 2026-11-15 (see docs); items marked 'per overview' come from the
platform overview document and cannot be verified through AWS APIs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dg import D  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..")

PROD = dict(
    env="prod", name="02-divi-prod-architecture", acct="divi-ai-prod", acct_id="832569409513", pfx="divi-prod",
    vpc_id="vpc-0bd28e628e263cb74", vpc_cidr="10.30.0.0/16",
    pub=["10.30.1.0/24", "10.30.2.0/24", "10.30.3.0/24"], prv=["10.30.4.0/24", "10.30.5.0/24", "10.30.6.0/24"],
    igw="igw-01b6777db4ff253a0", vgw="vgw-022094ced683ab16e",
)
STG = dict(
    env="stg", name="03-divi-stg-architecture", acct="divi-ai-stg", acct_id="398437580121", pfx="divi-stg",
    vpc_id="vpc-036f8752bf325cfcd", vpc_cidr="10.20.0.0/16",
    pub=["10.20.1.0/24", "10.20.2.0/24", "10.20.3.0/24"], prv=["10.20.4.0/24", "10.20.5.0/24", "10.20.6.0/24"],
    igw="igw-0740a4c4d4837588d", vgw="vgw-0dcd38adec9339642",
)


def build(c):
    stg = c["env"] == "stg"
    p = c["pfx"]
    sub = (f"Account {c['acct']} ({c['acct_id']}) · ap-southeast-2 · snapshot 2026-11-15 from read-only AWS API calls · "
           "items tagged 'per overview' or 'inferred' cannot be verified through AWS APIs")
    d = D(c["name"], 2440, 1500, f"Divi {'staging' if stg else 'production'} — high-level AWS architecture", sub)

    # ---------------- vertical plan ----------------
    cloud_y, region_y = 80, 120
    top_y, top_h = 160, 125
    vpc_y, az_y = 305, 345
    pub_y, pub_h = 375, 215
    prv_y = pub_y + pub_h + 20
    lam_y, lam_h = prv_y + 35, (155 if stg else 135)
    data_y, data_h = lam_y + lam_h + 20, (250 if stg else 150)
    ecs_y, ecs_h = data_y + data_h + 20, (305 if stg else 150)
    prv_bottom = ecs_y + ecs_h + 15
    az_bottom = prv_bottom + 10
    vpc_bottom = az_bottom + 20
    ops_y, ops_h = vpc_bottom + 25, 200
    region_bottom = ops_y + ops_h + 25
    cloud_bottom = region_bottom + 25
    d.h = cloud_bottom + 45
    gap_y = data_y + data_h + 10          # corridor between data band and ECS band

    az_x, az_w = [520, 1000, 1480], 470
    band_x, band_w = 530, 1410
    chan_x, ext_x = 2025, 2140

    # ---------------- groups ----------------
    d.group("cloud", f"AWS Cloud — account {c['acct']} ({c['acct_id']})", 340, cloud_y, 1760, cloud_bottom - cloud_y, "aws_cloud")
    d.group("region", "Region ap-southeast-2 (Sydney) — all workload resources", 360, region_y, 1720, region_bottom - region_y, "region")
    d.group("topband", "Front end and object storage (regional, outside the VPC)", 380, top_y, 1680, top_h, "band")
    d.group("vpc", f"VPC {p} — {c['vpc_cidr']} ({c['vpc_id']})", 380, vpc_y, 1680, vpc_bottom - vpc_y, "vpc")
    for i, az in enumerate(["ap-southeast-2a", "ap-southeast-2b", "ap-southeast-2c"]):
        d.group(f"az{i}", f"Availability Zone {az}", az_x[i], az_y, az_w, az_bottom - az_y, "az")
        d.group(f"pub{i}", f"{p}-public-{i + 1} · {c['pub'][i]}", az_x[i] + 10, pub_y, az_w - 20, pub_h, "public")
        d.group(f"prv{i}", f"{p}-private-{i + 1} · {c['prv'][i]}", az_x[i] + 10, prv_y, az_w - 20, prv_bottom - prv_y, "private")
    d.group("lam", "AWS Lambda — VPC-attached (3 AZs), invoked by the ALB" + (" · 19 of 21 functions" if stg else ""), band_x, lam_y, band_w, lam_h, "band",
            sub=("Not VPC-attached: divi-stg-client-onboarding, divi-stg-resource-scheduler" if stg else None))
    d.group("data", "Data and streaming (private subnets)", band_x, data_y, band_w, data_h, "band_data")
    d.group("ecs", f"ECS cluster {p} — Fargate + Fargate Spot · Container Insights on", band_x, ecs_y, band_w, ecs_h, "band_ecs")
    d.group("ops", "Orchestration and observability (regional)", 380, ops_y, 1680, ops_h, "band_ops")

    # ---------------- left column ----------------
    d.node("users", "Client users (browsers)", 60, 190, "users", kind="plain", code="USR", sub="React app + API calls · <client>.diviglobal.ai", ls="t", lw=200)
    d.node("eng", "Engineers", 210, 300, "user", kind="plain", code="ENG", sub="OpenVPN client", ls="b", lw=100)
    cust_y, cust_h = 500, (470 if stg else 330)
    d.group("cust", "Customer networks (outside AWS)", 20, cust_y, 280, cust_h, "dc")
    d.node("nocelle", "Nocelle — SQL Server ERP", 100, cust_y + 50, "traditional_server", kind="plain", code="SQL", sub="192.168.0.0/24 · txn log via VPN", ls="b", lw=200)
    d.node("intrim", "Intrim — D365 F&O", 100, cust_y + 190, "traditional_server", kind="plain", code="D365", sub="BYOD Azure SQL · SQL login", ls="b", lw=200)
    if stg:
        d.node("dug", "DUG — Achieve ERP", 100, cust_y + 330, "traditional_server", kind="plain", code="SQL", sub="SQL Server on RDS in ap-southeast-1 (outside this account)", ls="b", lw=200)
    sh_y = max(ecs_y - 40, cust_y + cust_h + 25)
    d.group("shared", "Shared account 962705291721", 20, sh_y, 280, 150, "account")
    d.node("ecr", "ECR — 6 repos", 200, sh_y + 45, "ecr", cat="container", code="ECR", sub="divi-engine · middleware · byod-sync · sink-connector · reporting · website", ls="b", lw=130)
    gh_y = ops_y + 70
    d.group("ghg", "GitHub (org divi-global)", 20, gh_y - 70, 280, 170, "ext", lalign="center")
    d.node("gh", "GitHub Actions", 60, gh_y, "client", kind="plain", code="GH", sub=("OIDC · tag vX.Y.Z → prod" if not stg else "OIDC · push to main → staging"), ls="b", lw=150)

    # ---------------- top band ----------------
    ax = 560
    d.node("amp_ui", f"{p}-mt-ui", ax, 190, "amplify", cat="front", code="AMP", sub=("Amplify · prod branch · intrim + nocelle domains" if not stg else "Amplify · stg branch · 6 domains"), lw=150)
    if not stg:
        d.node("amp_admin", f"{p}-admin-portal", ax + 200, 190, "amplify", cat="front", code="AMP", sub="Amplify · divi-admin.diviglobal.ai", lw=150)
        d.node("s3", "S3 — 7 buckets", ax + 400, 190, "s3", cat="storage", code="S3", sub="hosting · data · cdc · engine-state · audit · alert-excel-exports · glue-assets (+ TF state)", lw=240)
    else:
        for i, (nm, sb) in enumerate([("divi-stg-beta-ui", "betastaging.diviglobal.ai"), ("divi-stg-v3-ui", "v3staging.diviglobal.ai"), ("divi-stg-admin-portal", "divi-stg-admin.diviglobal.ai"),
                                      ("divi-stg-demo-test", "demo-test.diviglobal.ai"), ("divi-stg-demo-ui-concept", "demov1.diviglobal.ai"), ("demo", "branch demo · autobuild")]):
            d.node(f"amp{i}", nm, ax + 190 * (i + 1), 190, "amplify", cat="front", code="AMP", sub=sb, lw=170)
        d.node("s3", "S3 — 9 buckets", ax + 190 * 7, 190, "s3", cat="storage", code="S3", sub="hosting · data · cdc · engine-state · audit · alert exports · tracker-v2 · strategy-map · glue-assets (+ TF state)", lw=250)

    # ---------------- network plumbing ----------------
    bar_y, bar_h = pub_y + 28, 60
    d.node("igw", "IGW", 400, bar_y + 6, "internet_gateway", cat="net", code="IGW", sub=c["igw"][:12] + "…", lw=110)
    dy = data_y + 38
    d.node("vgw", "VGW", 400, dy, "vpn_gateway", cat="net", code="VGW", sub=f"{p}-nocelle · {c['vgw'][:12]}…", lw=110)
    d.group("albbar", "", band_x, bar_y, band_w, bar_h, "band")
    d.node("alb", "", band_x + 10, bar_y + 10, "elastic_load_balancing", cat="net", code="ALB", size=40)
    n_rules = 30 if stg else 11
    d.text("albtxt", [f"ALB {p}-public (internet-facing) · HTTP :80 → 301 → HTTPS :443 · ACM cert · {n_rules} host-header rules",
                      (f"hosts: {p}-<service>.achieve-erp.com · sink connectors on diviglobal.ai · default action: fixed 200 'Invalid Request'" if stg
                       else f"hosts: {p}-<service>.diviglobal.ai · default action: fixed 200 'Invalid Request'")],
           band_x + 58, bar_y + 6, 1300, size=11, bold_first=True, h=46)
    ny = pub_y + 110
    d.node("ovpn", f"{p}-vpn", az_x[0] + 90, ny, "ec2", code="VPN", sub="t3.micro · OpenVPN :1194/udp + :443 · EIP", lw=190)
    d.node("nat1", f"{p}-nat-instance-1", az_x[0] + 320, ny, "ec2", code="NAT", sub="t3.nano · EIP · private-1 default route", lw=150)
    d.node("nat2", f"{p}-nat-instance-2", az_x[1] + 60, ny, "ec2", code="NAT", sub="t3.nano · EIP · private-2 default route", lw=150)
    d.node("nat3", f"{p}-nat-instance-3", az_x[2] + 60, ny, "ec2", code="NAT", sub="t3.nano · EIP · private-3 default route", lw=150)

    # ---------------- Lambda band ----------------
    if not stg:
        ly = lam_y + 36
        fns = [("admin-portal-backend", "Java 21 · 512 MB"), ("mt-auth", "Java 21 · 512 MB"), ("mt-config", "Java 21 · 512 MB"), ("mt-financials", "Java 21 · 2048 MB · 300 s"),
               ("mt-perf-track", "Java 21 · 512 MB"), ("mt-report-generator", "Python 3.13 · 1024 MB"), ("mt-tracker", "Java 21 · 512 MB")]
        for i, (f, sb) in enumerate(fns):
            d.node(f"fn{i}", f"{p}-{f}", band_x + 100 + 195 * i, ly, "lambda", code="λ", sub=sb, lw=170, lines=2)
    else:
        ly = lam_y + 52
        groups = [("mt-* (6)", "auth · config · financials · perf-track · report-generator · tracker"), ("beta-* (5)", "auth · financials · perf-track · report-generator · tracker"),
                  ("v3-* (6)", "auth · config · financials · perf-track · report-generator · tracker"), ("admin-portal-backend", "Java 21 · 512 MB"), ("alert", "Python 3.12 · ALB host divi-stg-alert")]
        for i, (f, sb) in enumerate(groups):
            d.node(f"fn{i}", f"{p}-{f}", band_x + 130 + 270 * i, ly, "lambda", code="λ", sub=sb, lw=230, lines=2)

    # ---------------- Data band ----------------
    d.node("socat", ("div-stg-socat" if stg else f"{p}-socat"), band_x + 20, dy, "ec2", code="SOC", sub="t3.medium · TCP relay :1433 (inferred) · private-1", lw=150)
    d.node("mskc", "MSK Connect", band_x + 270, dy, "managed_streaming_for_kafka", cat="net", code="MSK", sub="debezium-connector · Debezium SQL Server · 1 MCU · outside Terraform (per overview)", lw=170, lines=1)
    d.node("msk", f"MSK {p}-cdc", band_x + 520, dy, "managed_streaming_for_kafka", cat="net", code="MSK",
           sub=f"Kafka 3.9.x · 3 × kafka.m5.large · {'200' if stg else '350'} GiB · TLS + IAM · brokers in 3 AZs", ls="r", lw=200)
    d.node("rds", f"RDS {p}-postgres", band_x + 790, dy, "rds", cat="db", code="RDS",
           sub=f"PostgreSQL 17.9 · db.m5.large · {'1250' if stg else '1000'} GiB gp3 · single-AZ (2b) · KMS · Performance Insights · 7-day backup · per-client DBs + divi_router (per overview)", ls="r", lw=270)
    d.node("bastion", f"{p}-bastion" + ("-manual" if stg else ""), band_x + 1130, dy, "ec2", code="BAS", sub="t3.large · RDP :3389 (inferred) · private-1", ls="r", lw=130)
    if stg:
        d.node("mskc2", "MSK Connect", band_x + 270, dy + 100, "managed_streaming_for_kafka", cat="net", code="MSK", sub="debezium-dug · SQL Server in ap-southeast-1 · outside Terraform (per overview)", lw=170, lines=1)
        d.node("testing", f"{p}-testing", band_x + 1130, dy + 100, "ec2", code="EC2", sub="r5a.2xlarge · stopped", ls="r", lw=130)

    # ---------------- ECS band ----------------
    ey = ecs_y + 35
    if not stg:
        for i, (s_, sb, off) in enumerate([("website", "1 task · :3000", 60), ("mt-reporting", "1 task · :8000 · reporting agent", 210), ("nocelle-engine-v2-job-worker", "desired 1 · health :80", 360)]):
            d.node(f"svc{i}", f"{p}-{s_}", band_x + off, ey, "fargate", cat="container", code="FG", sub=sb, lw=140, lines=2)
        d.node("sink", f"{p}-sink-connector", band_x + 520, ey, "fargate", cat="container", code="FG", sub="2 tasks · nginx :80 sidecar", lw=150, lines=2)
        d.text("b_intrim", ["Batch tasks — intrim (9 task defs)", "middleware (= sync_to_public) · byod-sync", "engine-v2: runall · daily-forecast · model-6 ·", "model6-preview · morning-pass · refresh-materialized ·", "select-forecast-champions"],
               band_x + 880, ecs_y + 18, 250, size=10, bold_first=True, box=True, h=84)
        d.text("b_nocelle", ["Batch tasks — nocelle (8 task defs)", "middleware (= sync_to_public)", "engine-v2: runall · daily-forecast · model-6 ·", "model6-preview · morning-pass · refresh-materialized ·", "select-forecast-champions"],
               band_x + 1145, ecs_y + 18, 250, size=10, bold_first=True, box=True, h=84)
        d.text("b_note", ["Run by Step Functions (ecs:RunTask.sync) · images from shared ECR:", "engine v1.5.0 · middleware v1.0.1 · byod-sync v1.0.0 · sink-connector v1.1.2 · reporting v1.4.0 · website v1.9.1"],
               band_x + 880, ecs_y + 106, 520, size=9, color="#5B6770", h=34, lh=11)
    else:
        for i, (s_, sb, off) in enumerate([("website", "1 task · :3000", 40), ("mt-reporting", "1 task · :8000", 190), ("intrim-engine-v2-job-worker", "desired 1", 340)]):
            d.node(f"svc{i}", f"{p}-{s_}", band_x + off, ey, "fargate", cat="container", code="FG", sub=sb, lw=135, lines=2)
        d.node("sink", f"{p}-sink-connector", band_x + 520, ey, "fargate", cat="container", code="FG", sub="2 tasks · nginx sidecar", lw=145, lines=2)
        d.node("sink2", f"{p}-dug-sink-connector", band_x + 690, ey, "fargate", cat="container", code="FG", sub="3 tasks · nginx sidecar", lw=145, lines=2)
        d.node("svc3", f"{p}-nocelle-engine-v2-job-worker", band_x + 860, ey, "fargate", cat="container", code="FG", sub="desired 1", lw=135, lines=2)
        d.node("svc4", f"{p}-v3-engine-v2-job-worker", band_x + 1030, ey, "fargate", cat="container", code="FG", sub="desired 1", lw=135, lines=2)
        rows = ["intrim (9 task defs): middleware · byod-sync · engine-v2 ×7 (runall, daily-forecast, model-6, model6-preview, morning-pass, refresh-materialized, select-forecast-champions)",
                "nocelle (8): middleware · engine-v2 ×7       dug (8): same set — pipeline schedule DISABLED",
                "beta (6): engine-v2 ×6 (feature-branch variant, no service)       v3 (6): engine-v2 ×6 + job-worker service (variant, intrim-test image)",
                "Run by Step Functions (ecs:RunTask.sync); engine image tags differ per variant (main-*, nocelle-test-stg-*, intrim-test-stg-*) · images from shared ECR"]
        d.text("b_all", ["Batch task definitions per client / variant"] + rows, band_x + 20, ecs_y + 165, band_w - 40, size=10, bold_first=True, box=True, h=125, lh=16)

    # ---------------- ops band ----------------
    oy = ops_y + 70
    ops_nodes = [
        ("iam", "IAM OIDC + roles", "identity_and_access_management", "sec", "IAM", f"GitHub OIDC provider · {p}-iac-base / -iac-service"),
        ("sched", "EventBridge Scheduler", "eventbridge", "integ", "SCH", ("4 schedules (dug-pipeline DISABLED) · Australia/Adelaide" if stg else "3 schedules · 00:00 byod-sync, 01:00 pipelines · Australia/Adelaide")),
        ("sfn", "Step Functions", "step_functions", "integ", "SFN", ("14 state machines (pipelines, morning-pass, previews, byod-sync, beta, v3)" if stg else "7 state machines (pipelines, morning-pass, previews, byod-sync)")),
        ("evb", "EventBridge rules", "eventbridge", "integ", "EVB", ("6 rules: ECS task state change + 5 morning-pass triggers" if stg else "3 rules: ECS task state change + 2 morning-pass triggers")),
        ("sns", "SNS", "sns", "integ", "SNS", f"{p}-cloudwatch · " + ("email + https" if stg else "email")),
        ("cw", "CloudWatch", "cloudwatch_2", "mgmt", "CW", ("30 alarms · 77 log groups · Container Insights" if stg else "18 alarms (RDS + 4 ECS services) · 36 log groups · Container Insights")),
        ("sec", "Secrets Manager", "secrets_manager", "sec", "SEC", ("15 secrets (DB, JWT, OpenAI, PagerDuty, Cloudflare, HubSpot, SES, per-tenant, GitHub app)" if stg else "14 secrets (DB, JWT, OpenAI, PagerDuty, Cloudflare, HubSpot, SES, per-tenant)")),
        ("ssm", "SSM Parameter Store", "systems_manager_parameter_store", "mgmt", "SSM", f"15 params under /divi/{c['env']}/ (VPC, ECS, RDS, MSK outputs)"),
        ("kms", "KMS", "key_management_service", "sec", "KMS", f"alias/{p}-postgres (customer-managed) · MSK uses AWS-managed aws/kafka"),
    ]
    for i, (id_, lab, ic, cat, code, sb) in enumerate(ops_nodes):
        d.node(id_, lab, 410 + 180 * i, oy, ic, cat=cat, code=code, sub=sb, lw=165, lines=2)

    # ---------------- external column ----------------
    d.group("extcol", "External services (outside AWS)", ext_x, 150, 280, 400, "ext")
    d.node("posthog", "PostHog", ext_x + 20, 190, "client", kind="plain", code="PH", sub="Amplify rewrites /ingest/* → us.i.posthog.com", ls="r", lw=150)
    d.node("cf", "Cloudflare DNS", ext_x + 20, 265, "client", kind="plain", code="CF", sub="diviglobal.ai zone (no Route 53 zones in account)", ls="r", lw=150)
    d.node("hub", "HubSpot · Amazon SES", ext_x + 20, 340, "client", kind="plain", code="HS", sub="website forms and email (secrets present)", ls="r", lw=150)
    d.node("pd", "PagerDuty", ext_x + 20, 440, "client", kind="plain", code="PD", sub="routing key in Secrets Manager", ls="r", lw=150)
    oa_y = ecs_y + (110 if stg else 55)
    d.node("openai", "OpenAI API", ext_x + 70, oa_y, "client", kind="plain", code="AI", sub="LLM calls (gpt-4o default, per overview)", ls="b", lw=170)
    if stg:
        d.node("pcx", "VPC peering", 1962, data_y + 60, "vpc", cat="net", code="PCX", sub="pcx-011e305428e1…", ls="b", lw=110)
        d.group("peer", "Peer VPC (not inspected)", ext_x, data_y + 30, 280, 120, "ext")
        d.node("peerv", "10.40.0.0/16", ext_x + 20, data_y + 70, "vpc", cat="net", code="VPC", sub="account 156358246875 (achieve-erp-copernicus-stg)", ls="r", lw=150)
        d.group("legacy", "Present but idle (no running workload)", ext_x, data_y + 170, 280, 215, "ghost")
        d.text("legacytxt", ["• ALB target groups achieve-*, nocelle-achieve-*,", "  ai-data-sync-dev, aipartner-mapping-* (0 targets)", "• Lambda Achieve-AI-User-Lambda (ap-southeast-1)",
                             "• EC2 divi-stg-testing r5a.2xlarge (stopped)", "• SGs / roles for Airbyte, Bladepipe, DMS, Glue", "• GuardKite role trusted by external acct 782218477847"],
               ext_x + 4, data_y + 202, 272, size=9.5, color="#5B6770", h=130)

    # ---------------- edges ----------------
    n = iter(range(1, 40))
    d.edge("e_users_amp", "users", "r", "amp_ui", "l", "HTTPS — loads React SPA", "app", num=next(n))
    d.edge("e_users_igw", "users", "b", "igw", "l", "HTTPS — API calls (JWT + client subdomain)", "app", via=[(84, bar_y + 30)], num=next(n))
    d.edge("e_igw_alb", "igw", "r", "albbar", "l", "", "app")
    d.edge("e_alb_lam", "albbar", "b", "lam", "t", "host-header → Lambda target groups", "app", lpos=(1345, pub_y + 150), num=next(n))
    d.edge("e_alb_ecs", "albbar", "r", "ecs", "r", "host-header → IP target groups", "app", sf=0.3, df=0.15, lpos=(chan_x, 640),
           via=[(chan_x, bar_y + 18), (chan_x, ecs_y + ecs_h * 0.15)], num=next(n))
    d.edge("e_lam_rds", "lam", "b", "rds", "t", "per-request SQL (per overview: divi_router)", "app", sf=(790 + 24) / band_w, lpos=(1344 + 95, lam_y + lam_h + 10), num=next(n))
    vgw_cy = dy + 24
    d.edge("e_noc_vgw", "nocelle", "r", "vgw", "l", "Site-to-site VPN · 2 tunnels UP · static 192.168.0.0/24", "net", via=[(322, cust_y + 74), (322, vgw_cy)], lpos=(322, cust_y + 190), num=next(n))
    d.edge("e_vgw_socat", "vgw", "r", "socat", "l", "", "net")
    d.edge("e_socat_mskc", "socat", "r", "mskc", "l", "TCP 1433 relay", "erp", num=next(n))
    d.edge("e_mskc_msk", "mskc", "r", "msk", "l", "topic per table (mssql.*)", "erp", num=next(n))
    d.edge("e_msk_sink", "msk", "b", "sink", "t", "consume", "erp", sf=0.3, df=0.3, num=next(n))
    d.edge("e_sink_rds", "sink", "t", "rds", "b", "writes source_sync (near real time)", "erp", sf=0.95, df=0.25, via=[(band_x + 520 + 0.95 * 48, gap_y - 4), (band_x + 790 + 12, gap_y - 4)],
           lpos=(band_x + 700, gap_y - 4), num=next(n))
    d.edge("e_intrim_ecs", "intrim", "r", "ecs", "l", "SQL login via NAT → internet (byod-sync task)", "erp", df=0.62, via=[(312, cust_y + 214), (312, ecs_y + ecs_h * 0.62)], lpos=(312, cust_y + 262), num=next(n))
    d.edge("e_ecs_rds", "ecs", "t", "rds", "b", "batch tasks, job-workers, reporting → SQL", "app", sf=(790 + 36) / band_w, df=0.75, lpos=(band_x + 790 + 36 + 105, gap_y + 4), num=next(n))
    d.edge("e_sched_sfn", "sched", "r", "sfn", "l", "daily cron", "ops", num=next(n))
    d.edge("e_evb_sfn", "evb", "l", "sfn", "r", "", "ops")
    d.edge("e_sfn_ecs", "sfn", "t", "ecs", "b", "ecs:RunTask.sync (pipeline steps)", "ops", sf=0.5, df=(410 + 180 * 2 + 24 - band_x) / band_w, lpos=(410 + 360 + 24 + 110, ecs_y + ecs_h + 40), num=next(n))
    d.edge("e_ecs_openai", "ecs", "r", "openai", "l", "LLM calls (egress via NAT instances)", "app", sf=0.86, df=0.5,
           via=[(chan_x + 40, ecs_y + ecs_h * 0.86), (chan_x + 40, oa_y + 24)], lpos=(chan_x + 40, oa_y + 24 + 42), num=next(n))
    d.edge("e_cw_sns", "cw", "l", "sns", "r", "alarm", "ops", num=next(n))
    d.edge("e_eng_vpn", "eng", "r", "ovpn", "l", "OpenVPN", "net", via=[(334, 324), (334, ny + 24)], lpos=(334, 400), num=next(n))
    ecr_cy = sh_y + 45 + 24
    d.edge("e_ecr_ecs", "ecr", "r", "ecs", "l", "image pull (cross-account ECR policy)", "deploy", df=min(max((ecr_cy - ecs_y) / ecs_h, 0.06), 0.94), num=next(n))
    d.edge("e_gh_ecr", "gh", "t", "ecr", "l", "push images (OIDC role divi-ecr-role)", "deploy", via=[(84, ecr_cy)], lpos=(84, (ecr_cy + gh_y) / 2 + 20), num=next(n))
    d.edge("e_gh_iam", "gh", "r", "iam", "l", "Terraform apply via OIDC roles", "deploy", num=next(n))
    if stg:
        d.edge("e_dug_mskc2", "dug", "r", "mskc2", "l", "SQL Server CDC (internet via NAT)", "erp", via=[(304, cust_y + 354), (304, dy + 124)], lpos=(560, dy + 124), num=next(n))
        d.edge("e_mskc2_msk", "mskc2", "r", "msk", "l", "", "erp", df=0.85, mid=band_x + 470)
        d.edge("e_msk_sink2", "msk", "b", "sink2", "t", "consume (dug)", "erp", sf=0.6, mid=gap_y + 6, lpos=(band_x + 690 + 24 + 55, gap_y + 6))
        d.edge("e_pcx", "pcx", "r", "peerv", "l", "route to 10.40.0.0/16", "net", lpos=(2070, data_y + 40))
    d.legend(ext_x, ops_y - 10, [("erp", "ERP data path (CDC / BYOD)"), ("app", "Application traffic"), ("ops", "Orchestration / alarms"), ("net", "VPN / peering / admin access"),
                                 ("deploy", "Deploy / image supply"), ("ext", "External, outside Terraform or inferred")], title="Legend (numbers = flow order in the doc)", w=290)
    return d


if __name__ == "__main__":
    for cfg in (PROD, STG):
        dd = build(cfg)
        dd.save(OUT)
        print("saved", dd.name, dd.w, dd.h)
