"""Org / OU structure diagram (Divi-relevant OUs and accounts only) and the cross-account network topology diagram."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dg import D  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..")


def build_org():
    d = D("00-aws-organization-ou-structure", 2000, 1130, "AWS Organization — OU structure, Divi accounts and cross-account connections",
          "Divi-relevant OUs and accounts only (the organization has 20 accounts in total; other OUs and accounts are not shown) · snapshot 2026-11-15 from read-only AWS API calls")
    d.group("org", "AWS Organization o-o1h2b5d1fq · all features · management account 892166101996 · no SCPs attached (only the AWS-managed FullAWSAccess policy exists)",
            20, 80, 1960, 960, "org")
    d.node("root", "Root (r-r469)", 940, 118, "organizations", cat="mgmt", code="ROOT", sub="OUs shown: projects, management · other root-level accounts, OU sandbox and OU suspended (empty) not shown", ls="r", lw=330)

    # ---- management account card ----
    d.group("mgmt", "rb-main — management account · 892166101996", 40, 250, 470, 580, "account")
    d.node("orgsvc", "AWS Organizations", 60, 300, "organizations", cat="mgmt", code="ORG", sub="o-o1h2b5d1fq · trusted access: account, cloudtrail, iam, stacksets, sso, cost-optimization-hub", ls="r", lw=330)
    d.node("sso", "IAM Identity Center", 60, 395, "iam_identity_center", cat="sec", code="SSO", sub="ssoins-7223815176a971d1 · primary region us-east-1 · 8 permission sets (AdministrativeAccess, ReadOnlyAccess, PowerUser, ViewOnly, SecurityAudit, Billing, S3Only, SandboxReadOnly)", ls="r", lw=330)
    d.node("stackset", "CloudFormation StackSet", 60, 520, "cloudformation", cat="mgmt", code="CFN", sub="terraform-bootstrap · service-managed · auto-deploy to Root · creates terraform-state-<account-id> bucket + terraform-state-lock table (us-east-1) in each member account", ls="r", lw=330)
    d.node("trail", "CloudTrail org-trail", 60, 645, "cloudtrail", cat="mgmt", code="CT", sub="organization trail · multi-region · home us-east-1 · delivers to the security account bucket", ls="r", lw=330)
    d.text("mgmtnet", ["Network: default VPCs only (172.31.0.0/16), no workloads", "ap-southeast-2 vpc-07a7ff37cb5989c72 · us-east-1 vpc-0a081c601f65d8290", "Member accounts carry OrganizationAccountAccessRole trusting this account"],
           55, 735, 440, size=10, bold_first=True, box=True, h=80, lh=14)

    # ---- projects OU ----
    d.group("projects", "OU projects (ou-r469-hbkrb86z)", 600, 250, 730, 580, "ou", sub="14 accounts in this OU — only the two Divi accounts are shown")
    d.group("prodacct", "divi-ai-prod · 832569409513", 620, 320, 340, 400, "account")
    d.group("stgacct", "divi-ai-stg · 398437580121", 975, 320, 340, 400, "account")
    d.node("prodvpc", "VPC divi-prod", 640, 370, "vpc", cat="net", code="VPC", sub="10.30.0.0/16 · vpc-0bd28e628e263cb74", ls="r", lw=200)
    d.node("stgvpc", "VPC divi-stg", 995, 370, "vpc", cat="net", code="VPC", sub="10.20.0.0/16 · vpc-036f8752bf325cfcd", ls="r", lw=200)
    d.text("prodtxt", ["Region ap-southeast-2 (us-east-1: TF state, GuardKite)", "3 public /24 (10.30.1–3.0) + 3 private /24 (10.30.4–6.0)", "AZs 2a/2b/2c · IGW · 3 NAT instances (t3.nano)",
                       "VGW vgw-022094ced683ab16e → VPN → Nocelle", "  192.168.0.0/24 (static route)", "No VPC endpoints · no flow logs · no peering", "Default VPC 172.31.0.0/16 unused", "  (vpc-057d805d64b10952d)", "",
                       "Workload: ECS Fargate (cluster divi-prod), 7 Lambdas,", "RDS PostgreSQL, MSK + MSK Connect, ALB, Amplify"],
           630, 435, 320, size=10, bold_first=True, box=True, h=185, lh=15)
    d.text("stgtxt", ["Region ap-southeast-2 (us-east-1: TF state, GuardKite;", "  ap-southeast-1: 1 Lambda)", "3 public /24 (10.20.1–3.0) + 3 private /24 (10.20.4–6.0)", "AZs 2a/2b/2c · IGW · 3 NAT instances (t3.nano)",
                      "VGW vgw-0dcd38adec9339642 → VPN → Nocelle", "  192.168.0.0/24 (static route)", "VPC peering pcx-011e305428e123226 ↔ 10.40.0.0/16", "  (account 156358246875)", "No VPC endpoints · no flow logs",
                      "Default VPC 172.31.0.0/16 unused (vpc-069f67711034e5621)", "", "Workload: ECS Fargate (cluster divi-stg, 7 services),", "21 Lambdas, RDS, MSK, ALB, 7 Amplify apps"],
           985, 435, 320, size=10, bold_first=True, box=True, h=215, lh=15)

    # ---- management OU ----
    d.group("mgmtou", "OU management (ou-r469-qsgln0ox)", 1450, 250, 510, 580, "ou")
    d.group("sharedacct", "shared · 962705291721", 1470, 300, 470, 300, "account")
    d.node("ecr", "ECR — 6 repositories", 1490, 345, "ecr", cat="container", code="ECR", sub="divi-engine · divi-middleware · divi-byod-sync · divi-sink-connector · divi-reporting · divi-website (images 3–29 each) · pull + push allowed for prod and stg account roots", ls="r", lw=330)
    d.node("s3web", "S3 divi-web-contents", 1490, 450, "s3", cat="storage", code="S3", sub="logos and email-template images · versioned · public GetObject", ls="r", lw=330)
    d.node("oidc", "GitHub OIDC provider + roles", 1490, 520, "identity_and_access_management", cat="sec", code="IAM", sub="divi-ecr-role, divi-iac-shared-ecr-policy", ls="r", lw=330)
    d.text("sharednet", ["Network: default VPC 172.31.0.0/16 only (vpc-09eb020ae6ce094fb) — no workloads"], 1480, 568, 450, size=10, color="#5B6770", h=26)
    d.group("secacct", "security · 041558033420", 1470, 620, 470, 195, "account")
    d.node("trailbkt", "S3 org-trail-logs-041558033420", 1490, 665, "s3", cat="storage", code="S3", sub="organization CloudTrail log bucket", ls="r", lw=330)
    d.text("secnote", ["Delegated administrator for CloudTrail (since 2026-11-12).", "Not inspected (no profile in scope): VPC and other", "resources are not documented here."],
           1480, 725, 450, size=10, color="#5B6770", h=62, lh=14)

    # ---- external band ----
    d.group("extband", "", 600, 870, 1360, 160, "ghost")
    d.text("exttitle", ["External parties and peers"], 1560, 1000, 380, size=10, color="#7D8998", align="center", h=22)
    d.node("nocelle", "Nocelle network", 640, 910, "traditional_server", kind="plain", code="SQL", sub="192.168.0.0/24 (SQL Server ERP)", ls="r", lw=150)
    d.node("guard", "GuardKite", 940, 910, "client", kind="plain", code="GK", sub="external AWS account 782218477847", ls="r", lw=150)
    d.node("peer", "Peer VPC 10.40.0.0/16", 1206, 910, "vpc", cat="net", code="VPC", sub="account 156358246875 (achieve-erp-copernicus-stg)", ls="b", lw=190)
    d.node("gh", "GitHub Actions", 1620, 910, "client", kind="plain", code="GH", sub="org divi-global (OIDC federation)", ls="r", lw=150)

    # ---- tree edges ----
    d.edge("t1", "root", "b", "mgmt", "t", "", "ext", mid=215, sf=0.2, df=0.5, arrow=False)
    d.edge("t2", "root", "b", "projects", "t", "", "ext", mid=215, sf=0.5, df=0.5, arrow=False)
    d.edge("t3", "root", "b", "mgmtou", "t", "", "ext", mid=215, sf=0.8, df=0.5, arrow=False)
    # ---- cross-account connections ----
    n = iter(range(1, 20))
    d.edge("e_stackset", "mgmt", "r", "projects", "l", "StackSet", "ops", sf=0.8, df=0.8, num=next(n))
    d.edge("e_trail", "projects", "r", "secacct", "l", "org-trail logs", "ops", sf=0.9, df=(250 + 0.9 * 580 - 620) / 195, num=next(n))
    d.edge("e_ecr", "sharedacct", "l", "projects", "r", "ECR pull / push", "deploy", sf=0.3, df=0.22, num=next(n))
    d.edge("e_gh_ecr", "gh", "t", "mgmtou", "b", "OIDC → ECR push", "deploy", sf=0.5, df=0.82, num=next(n))
    d.edge("e_gh_iac", "gh", "l", "projects", "b", "OIDC → Terraform apply", "deploy", df=0.95, via=[(1292, 934)], lpos=(1450, 934), num=next(n))
    d.edge("e_guard", "guard", "t", "projects", "b", "AssumeRole GuardKite", "ext", df=0.55, num=next(n))
    d.edge("e_vpn_prod", "prodacct", "b", "nocelle", "t", "", "net", sf=0.2, df=0.25, mid=800, num=next(n))
    d.edge("e_vpn_stg", "stgacct", "b", "nocelle", "t", "Site-to-site VPN ×2", "net", sf=0.15, df=0.75, mid=845, lpos=(900, 845))
    d.edge("e_peer", "stgacct", "b", "peer", "t", "VPC peering", "net", sf=(1230 - 975) / 340, df=0.5, num=next(n))
    d.legend(40, 870, [("ext", "OU tree / external relationship"), ("ops", "Org-level service (StackSet, CloudTrail)"), ("deploy", "Image supply / CI-CD federation"), ("net", "VPN and VPC peering")],
             title="Legend", w=330)
    d.text("access", ["Access: engineers sign in through IAM Identity Center; every Divi account has an AdministrativeAccess and a ReadOnlyAccess role. Terraform state per account: S3 terraform-state-<account-id> + DynamoDB terraform-state-lock (us-east-1)."],
           40, 1050, 1920, size=10.5, color="#3F4A52", h=50, lh=14)
    return d


def panel(d, x0, cfg, vgw_side, igw_x):
    """Per-account VPC panel for the network diagram."""
    p = cfg["pfx"]
    ay, vy = 130, 175
    d.group(f"{p}acct", f"{cfg['acct']} · {cfg['acct_id']} · ap-southeast-2", x0, ay, 740, 725, "account")
    d.group(f"{p}vpc", f"VPC {p} · {cfg['cidr']}", x0 + 20, vy, 700, 635, "vpc", sub=cfg["vpc_id"])
    colx = [x0 + 40, x0 + 260, x0 + 480]
    azs = ["ap-southeast-2a", "ap-southeast-2b", "ap-southeast-2c"]
    for i in range(3):
        d.group(f"{p}az{i}", f"AZ {azs[i]}", colx[i], vy + 55, 210, 565, "az")
        d.group(f"{p}pub{i}", f"{p}-public-{i + 1} · {cfg['pub'][i]}", colx[i] + 8, vy + 85, 194, 235, "public", sub=f"{cfg['pubid'][i]} · {cfg['pubrt']} · 0.0.0.0/0 → IGW", lsize=10)
        d.group(f"{p}prv{i}", f"{p}-private-{i + 1} · {cfg['prv'][i]}", colx[i] + 8, vy + 335, 194, 270, "private", sub=f"{cfg['prvid'][i]} · {cfg['prvrt'][i]}", lsize=10)
        d.node(f"{p}nat{i}", f"{p}-nat-instance-{i + 1}", colx[i] + 25 + (115 if i == 0 else 40), vy + 212, "ec2", code="NAT", sub="t3.nano · EIP", lw=100, lines=2, size=36)
        d.text(f"{p}prvtxt{i}", cfg["resid"][i], colx[i] + 12, vy + 392, 186, size=9.5, h=205, lh=13)
    d.node(f"{p}vpn", f"{p}-vpn", colx[0] + 18, vy + 212, "ec2", code="VPN", sub="t3.micro · OpenVPN", lw=80, lines=2, size=36)
    d.group(f"{p}albbar", "", colx[0] + 8, vy + 165, 674, 34, "band")
    d.node(f"{p}alb", "", colx[0] + 12, vy + 167, "elastic_load_balancing", cat="net", code="ALB", size=30)
    d.text(f"{p}albtxt", [f"ALB {p}-public · internet-facing · spans the three public subnets · SG {p}-public-alb (80/443)"], colx[0] + 46, vy + 170, 620, size=10, h=24)
    d.node(f"{p}igw", "IGW", x0 + igw_x, vy - 20, "internet_gateway", cat="net", code="IGW", sub=cfg["igw"], ls="b", lw=170, size=40)
    vx = x0 + 20 + (700 - 20 if vgw_side == "r" else -20)
    d.node(f"{p}vgw", "VGW", vx, 470, "vpn_gateway", cat="net", code="VGW", sub=cfg["vgw"], ls="b", lw=100, size=40)
    d.text(f"{p}nets", [f"Private route tables: 0.0.0.0/0 → NAT instance ENI · 192.168.0.0/24 → VGW" + (" · 10.40.0.0/16 → pcx" if p == "divi-stg" else ""),
                        "No VPC endpoints · no VPC flow logs · security groups: see appendix"], x0 + 35, vy + 642, 690, size=10, color="#5B6770", h=30, lh=13)


def build_network():
    d = D("01-network-topology", 2420, 1170, "Network topology across the Divi AWS accounts — VPCs, CIDRs, VPN and peering",
          "VPC-level view of divi-ai-prod, divi-ai-stg, shared and rb-main · snapshot 2026-11-15 from read-only AWS API calls")
    prod = dict(pfx="divi-prod", acct="divi-ai-prod", acct_id="832569409513", cidr="10.30.0.0/16", vpc_id="vpc-0bd28e628e263cb74",
                pub=["10.30.1.0/24", "10.30.2.0/24", "10.30.3.0/24"], prv=["10.30.4.0/24", "10.30.5.0/24", "10.30.6.0/24"],
                pubid=["subnet-0f097393441c15e15", "subnet-0cfa112909a482264", "subnet-08a72b6b80d57cfc5"], pubrt="rtb-0a4f62a9605ee66c7",
                prvid=["subnet-0cc9970dfa27c43ea", "subnet-09b67f5903efcb403", "subnet-06e980d3bf83c96ec"],
                prvrt=["rtb-0497cc5794fb1490a", "rtb-0157cb29e296556ca", "rtb-0015edfb2bc8841ba"],
                igw="igw-01b6777db4ff253a0", vgw="vgw-022094ced683ab16e",
                resid=[["Residents:", "• divi-prod-bastion (t3.large)", "• divi-prod-socat (t3.medium)", "• MSK broker", "• ECS Fargate tasks", "• Lambda ENIs", "• MSK Connect worker"],
                       ["Residents:", "• RDS divi-prod-postgres", "  (single-AZ, db.m5.large)", "• MSK broker", "• ECS Fargate tasks", "• Lambda ENIs"],
                       ["Residents:", "• MSK broker", "• ECS Fargate tasks", "• Lambda ENIs"]])
    stg = dict(pfx="divi-stg", acct="divi-ai-stg", acct_id="398437580121", cidr="10.20.0.0/16", vpc_id="vpc-036f8752bf325cfcd",
               pub=["10.20.1.0/24", "10.20.2.0/24", "10.20.3.0/24"], prv=["10.20.4.0/24", "10.20.5.0/24", "10.20.6.0/24"],
               pubid=["subnet-0ae0d3be502ed959b", "subnet-064eb68fa2ff0199b", "subnet-0d8142a2adaa03050"], pubrt="rtb-0e0cd80aaac7dfec6",
               prvid=["subnet-001728a95ee8c833d", "subnet-09a556ef2beda6972", "subnet-0bf57ebf49ca7282c"],
               prvrt=["rtb-0c6aa3f7dc7c304b1", "rtb-0a796d061c660c90c", "rtb-0f6fb62002aee0cc6"],
               igw="igw-0740a4c4d4837588d", vgw="vgw-0dcd38adec9339642",
               resid=[["Residents:", "• divi-stg-bastion-manual", "• div-stg-socat (t3.medium)", "• divi-stg-testing (stopped)", "• MSK broker", "• ECS Fargate tasks", "• Lambda ENIs", "• MSK Connect workers (2)"],
                      ["Residents:", "• RDS divi-stg-postgres", "  (single-AZ, db.m5.large)", "• MSK broker", "• ECS Fargate tasks", "• Lambda ENIs"],
                      ["Residents:", "• MSK broker", "• ECS Fargate tasks", "• Lambda ENIs"]])
    panel(d, 30, prod, "r", 560)
    panel(d, 1290, stg, "l", 400)
    # centre
    d.node("inet", "Internet", 1030, 151, "internet", kind="plain", code="WWW", sub="HTTPS clients · Cloudflare DNS · OpenVPN · SaaS APIs", ls="b", lw=220, size=48)
    d.group("noc", "Nocelle customer network", 960, 470, 260, 210, "dc")
    d.node("nocsrv", "SQL Server ERP", 1066, 520, "traditional_server", kind="plain", code="SQL", sub="192.168.0.0/24", ls="b", lw=200)
    d.text("cgw", ["Customer gateways (BGP ASN 65000, static routing):", "cgw-045c852571155a6dd (prod)", "cgw-05a17bc4e25d65d19 (stg)"], 968, 600, 244, size=9, h=64, lh=12)
    d.group("peerg", "Peer VPC (not inspected)", 2110, 400, 280, 160, "ext")
    d.node("peerv", "10.40.0.0/16", 2130, 450, "vpc", cat="net", code="VPC", sub="vpc-0a60e962e0d688e5c · account 156358246875 (achieve-erp-copernicus-stg)", ls="r", lw=170)
    d.node("pcx", "pcx-011e305428e123226", 1990, 454, "vpc", cat="net", code="PCX", sub="", ls="t", lw=150, size=40)
    # edges
    d.edge("e_inet_pigw", "inet", "l", "divi-prodigw", "r", "", "app", sf=0.5)
    d.edge("e_inet_sigw", "inet", "r", "divi-stgigw", "l", "", "app")
    d.edge("e_pvpn", "divi-prodvgw", "r", "noc", "l", "vpn-099acf81a915f7c1b · 2 tunnels UP", "net", sf=0.5, df=(490 - 470) / 210)
    d.edge("e_svpn", "divi-stgvgw", "l", "noc", "r", "vpn-0be9465e2a7e430b7 · 2 tunnels UP", "net", sf=0.5, df=(490 - 470) / 210)
    d.edge("e_pcx", "pcx", "r", "peerv", "l", "peering · active", "net")
    # bottom strip
    by = 880
    d.group("mgmtg", "rb-main · 892166101996 (management)", 30, by, 520, 160, "account")
    d.text("mgmtt", ["Default VPCs only, 172.31.0.0/16 — no workloads", "ap-southeast-2: vpc-07a7ff37cb5989c72", "us-east-1: vpc-0a081c601f65d8290"], 40, by + 40, 500, size=10, h=60, lh=15)
    d.group("sharedg", "shared · 962705291721", 570, by, 520, 160, "account")
    d.text("sharedt", ["Default VPC only, 172.31.0.0/16 (vpc-09eb020ae6ce094fb):", "3 public /20 subnets, IGW igw-0356c44ff30c4454b — no workloads", "", "ECR is reached via its regional public endpoint: prod and stg", "tasks pull images through their NAT instances (no VPC endpoints)"],
           580, by + 40, 500, size=10, h=100, lh=14)
    d.group("secg", "security · 041558033420", 1110, by, 320, 160, "account")
    d.text("sect", ["Not inspected (no profile in scope)", "Holds org-trail-logs-041558033420"], 1120, by + 40, 300, size=10, h=50, lh=15)
    d.group("cidrg", "CIDR plan (as deployed)", 1450, by, 940, 255, "band")
    d.text("cidrt", ["10.20.0.0/16      divi-stg VPC (vpc-036f8752bf325cfcd) — 3 public + 3 private /24", "10.30.0.0/16      divi-prod VPC (vpc-0bd28e628e263cb74) — 3 public + 3 private /24",
                     "10.40.0.0/16      peer VPC in account 156358246875, peered to divi-stg only", "192.168.0.0/24    Nocelle customer network, reached over one site-to-site VPN per environment (static routes, 2 tunnels each)",
                     "172.31.0.0/16     default VPCs in prod (vpc-057d805d64b10952d), stg (vpc-069f67711034e5621), shared and rb-main (×2) — unused, overlapping, not connected", "",
                     "Egress: private subnets default-route to NAT *instances* (t3.nano, one per AZ), not NAT Gateways", "Ingress: single internet-facing ALB per VPC (public subnets) · OpenVPN on divi-<env>-vpn (UDP 1194, TCP 443)",
                     "Not present in any of the four accounts: Transit Gateway, VPC endpoints, Route 53 hosted zones/resolver endpoints, VPC flow logs"],
           1460, by + 36, 920, size=10.5, h=215, lh=17)
    return d


if __name__ == "__main__":
    for dd in (build_org(), build_network()):
        dd.save(OUT)
        print("saved", dd.name, dd.w, dd.h)
