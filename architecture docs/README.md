# Divi — AWS architecture documentation

Descriptive architecture pack for the Divi product on AWS: the AWS Organization and OU structure, the network of each account, and detailed architecture (with actual deployed resource names) for **production** and **staging**. It records what is deployed and how the accounts connect. It is **not** a review: there are no risk ratings, health judgements or recommendations.

| | |
|---|---|
| **Snapshot** | 2026-11-15 (UTC) |
| **Method** | Read-only AWS API calls (list / describe / get) against four accounts using SSO ReadOnlyAccess profiles. No logs, data, secret values or database contents were read. |
| **Accounts covered** | `rb-main` 892166101996 (management) · `divi-ai-prod` 832569409513 · `divi-ai-stg` 398437580121 · `shared` 962705291721. `security` 041558033420 is described only from the outside (not inspected). |
| **Other context** | The platform overview document ("Divi platform overview") and the CDC data-sync sketch supplied by the platform lead. Statements taken only from those are marked *per overview*. |

## Contents

| File | What it is |
|---|---|
| [01-organization-and-network.md](01-organization-and-network.md) | OU tree, account IDs and roles, org-level services, VPC and subnet tables for prod / stg / shared / rb-main, CIDR plan, cross-account connections. |
| [02-divi-prod-architecture.md](02-divi-prod-architecture.md) | Production architecture diagram, numbered flows, full resource inventory (network, ECS, Lambda, Step Functions, RDS, MSK, Amplify, security), dependencies. |
| [03-divi-stg-architecture.md](03-divi-stg-architecture.md) | Staging architecture: same layout plus the `beta` / `v3` variants, the DUG connector, VPC peering, idle leftovers, and a prod-vs-stg comparison. |
| [04-appendix-security-groups.md](04-appendix-security-groups.md) | Security-group inbound rules per VPC, including rules open to `0.0.0.0/0`. Kept separate so it can be left out of wider documentation. |
| [05-drawio-prompts.md](05-drawio-prompts.md) | How to open the diagrams in draw.io / Confluence, a shared style prompt and one prompt per diagram, and the AWS icon names used. |
| `diagrams/` | Per diagram: `.drawio` (editable, AWS icons), `.svg` and `.png` (for embedding). `00` org/OU, `01` network, `02` prod, `03` staging. |
| `diagrams/source/` | The Python generator (`dg.py`, `build_account.py`, `build_org.py`), `render.sh` (SVG → PNG via Chrome) and `validate_drawio.py`. No AWS access needed to rebuild. |

## Suggested Confluence layout

```
Divi on AWS — architecture            (README text as the parent page)
├── Organization, OUs and network     ← 01 (+ images 00, 01)
├── Production architecture           ← 02 (+ image 02)
├── Staging architecture              ← 03 (+ image 03)
└── Appendix — security groups        ← 04 (publish only if your policy allows)
```

Notes for whoever publishes this:

1. Upload the PNGs from `diagrams/` as page attachments and replace the relative image links (`diagrams/<name>.png`) with the attachments. Attach the matching `.drawio` files so the diagrams stay editable (see 05).
2. The Markdown contains `mermaid` code blocks as a plain-text fallback of each diagram. Confluence does not render these without a Mermaid macro; drop them or keep them in a collapsed code block.
3. Internal links between pages (`[...](02-divi-prod-architecture.md#…)`) should be re-pointed to the Confluence pages.
4. Page 04 lists network exposure in detail; decide separately whether it is published.

## Conventions

- **Names:** accounts are `divi-ai-prod` / `divi-ai-stg`; resources use the Terraform prefix `divi-prod` / `divi-stg`.
- **Tags:** *per overview* = from the platform overview, not verifiable through AWS APIs; *inferred* = deduced from names, ports, tags or configuration.
- **What is deliberately left out:** account contact emails, customer VPN gateway IPs, secret names beyond their classes and all secret values, connector hosts and credentials, Elastic IP addresses, SNS endpoints.
- **Colour key in the diagrams:** orange = ERP data path, grey = application traffic, blue dashed = orchestration, purple dashed = VPN / peering / admin access, green dashed = deploy / image supply, dotted grey = external or inferred.

## Known limits of this pack

- The `.drawio` files could not be opened in draw.io by the author. Layout was verified through an SVG/PNG render of the same geometry; XML structure was validated programmatically. Open each once and check icons (see 05).
- Mermaid blocks were not render-tested.
- Per-client databases, the `source_sync` → `public` mapping layers, the three staging variants as described, OpenAI usage and the Opstimus ownership statement come from the overview and could not be checked through AWS APIs.
- The `security` account, the peer VPC account 156358246875 and the external account 782218477847 are described from our side only.
- Observed schedule difference: the overview describes the Intrim BYOD sync as running every two hours; the EventBridge Scheduler entries in both accounts are `cron(0 0 * * ? *)` in `Australia/Adelaide` (daily).

## Rebuilding the diagrams

```bash
cd "diagrams/source"
python3 build_account.py   # prod + staging
python3 build_org.py       # organization + network
./render.sh                # PNGs (needs Google Chrome)
python3 validate_drawio.py # structural check of the .drawio files
```
