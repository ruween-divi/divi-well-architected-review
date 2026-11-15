# Appendix — Security groups (as deployed)

| | |
|---|---|
| **Snapshot** | 2026-11-15 (UTC), read-only AWS API calls |
| **Scope** | Security groups in VPC `divi-prod` (divi-ai-prod) and VPC `divi-stg` (divi-ai-stg). The `shared` and `rb-main` accounts have only the default VPC security group and no attached workloads. |
| **Nature** | Descriptive. Lists inbound rules exactly as configured. No assessment. |
| **Handling** | This page lists which ports are reachable from which sources. Share it according to your internal policy; it is kept in a separate file so it can be left out of wider documentation. |

Related pages: [Organization and network](01-organization-and-network.md) · [Production](02-divi-prod-architecture.md) · [Staging](03-divi-stg-architecture.md)

## 1. Rules whose source is `0.0.0.0/0`

"Public IP" is whether the instance, or the load balancer, has a public address at snapshot. A rule on a resource without a public address is reachable only from inside the VPC, over the VPN, or over the peering.

| Account | Security group | Port(s) | Attached to | Public IP at snapshot |
|---|---|---|---|---|
| prod | `divi-prod-public-alb` | 80, 443/tcp | ALB `divi-prod-public` (internet-facing) | yes (ALB) |
| prod | `divi-prod-vpn` | 1194/udp, 443/tcp | `divi-prod-vpn` (OpenVPN, Elastic IP) | yes |
| prod | `divi-prod-bastion` | 3389/tcp | `divi-prod-bastion` | no |
| prod | `divi-prod-socat` | 1433/tcp, 22/tcp | `divi-prod-socat` | no |
| stg | `divi-stg-public-alb` | 80, 443/tcp | ALB `divi-stg-public` | yes (ALB) |
| stg | `divi-stg-vpn` | 1194/udp, 443/tcp | `divi-stg-vpn` (OpenVPN, Elastic IP) | yes |
| stg | `divi-stg-socat` | 1433/tcp, 22/tcp | `div-stg-socat` | no |
| stg | `divi-stg-testing` | 22/tcp | `divi-stg-testing` (stopped) | no |
| stg | `tempec2` | 3389/tcp | `divi-stg-bastion-manual` | no |
| stg | `airbyte`, `divi-stg-airbyte`, `bladepipe` | 22, 80, 443, 8000, 8001, 8111/tcp (varies) | no ENIs attached | — |
| stg | `manual-glue-secuirty-group` | all traffic | no ENIs attached | — |

Other sources worth noting: both `*-vpn` groups allow SSH (22/tcp) from `13.239.158.0/29` (an AWS-owned range that appears to be the EC2 Instance Connect range for ap-southeast-2; not verified); `aws-dms` (stg) allows 1433/tcp from `10.20.0.0/16` and `192.168.0.0/24`.

## 2. Security groups per VPC

### 2.1 `divi-ai-prod` — VPC `divi-prod` (`vpc-0bd28e628e263cb74`)

| Security group | ID | Inbound (port ← source) | Attached to (ENIs at snapshot) |
|---|---|---|---|
| `default` | `sg-0edc5769f627d106f` | all traffic ← default | — |
| `divi-prod-bastion` | `sg-044d67e82a39dbbfd` | 3389/tcp ← 0.0.0.0/0 | EC2 instance ×1 |
| `divi-prod-cdc-msk` | `sg-04dec75deaa558fd9` | 9098/tcp ← 10.30.0.0/16<br>9094/tcp ← 10.30.0.0/16 | MSK / MSK Connect ENI ×7 |
| `divi-prod-ecs-cluster` | `sg-06647fdabc9f4df22` | 0–65535/tcp ← 10.30.0.0/16 | ECS task ENI ×6 |
| `divi-prod-nat-instance` | `sg-0c62e9a076809cd77` | all traffic ← 10.30.0.0/16 | EC2 instance ×3 |
| `divi-prod-postgres-db` | `sg-0b2ae666d80c30632` | 5432/tcp ← 10.30.0.0/16 | Lambda ENI ×3, RDS ×1 |
| `divi-prod-public-alb` | `sg-091f8b505a2cd3b69` | 80/tcp ← 0.0.0.0/0<br>443/tcp ← 0.0.0.0/0 | ALB node ×3 |
| `divi-prod-socat` | `sg-0076dda377b5a0083` | 1433/tcp ← 0.0.0.0/0<br>22/tcp ← 0.0.0.0/0 | EC2 instance ×1 |
| `divi-prod-vpn` | `sg-096afe68d699b5642` | 1194/udp ← 0.0.0.0/0<br>22/tcp ← 13.239.158.0/29<br>443/tcp ← 0.0.0.0/0 | EC2 instance ×1 |

Egress: all groups allow all outbound traffic.

### 2.2 `divi-ai-stg` — VPC `divi-stg` (`vpc-036f8752bf325cfcd`)

| Security group | ID | Inbound (port ← source) | Attached to (ENIs at snapshot) |
|---|---|---|---|
| `airbyte` | `sg-0c7a9eeee711fc33a` | 8000/tcp ← 0.0.0.0/0<br>22/tcp ← 0.0.0.0/0 | — |
| `aws-dms` | `sg-0a008b053774e0812` | 1433/tcp ← 10.20.0.0/16, 192.168.0.0/24 | — |
| `bladepipe` | `sg-05a86bcb127a4563b` | 22/tcp ← 0.0.0.0/0<br>8111/tcp ← 0.0.0.0/0 | — |
| `default` | `sg-006c16050b4ac2ef2` | all traffic ← default | — |
| `divi-stg-airbyte` | `sg-09563ed7b82e525a6` | 80/tcp ← 0.0.0.0/0<br>8001/tcp ← 0.0.0.0/0<br>8000/tcp ← 0.0.0.0/0<br>22/tcp ← 0.0.0.0/0<br>443/tcp ← 0.0.0.0/0 | — |
| `divi-stg-cdc-msk` | `sg-0cad331e6c876a460` | 1433/tcp ← 10.20.0.0/16<br>9098/tcp ← 10.20.0.0/16<br>9094/tcp ← 10.20.0.0/16 | MSK / MSK Connect ENI ×8 |
| `divi-stg-ecs-cluster` | `sg-0708a3df30d1c1651` | 0–65535/tcp ← 10.20.0.0/16 | ECS task ENI ×10 |
| `divi-stg-nat-instance` | `sg-09f39acc12d489e89` | all traffic ← 10.20.0.0/16 | EC2 instance ×3 |
| `divi-stg-postgres-db` | `sg-0a7b93be64df76c3d` | 5432/tcp ← 10.20.0.0/16 | Lambda ENI ×3, RDS ×1 |
| `divi-stg-public-alb` | `sg-07e835531781fcf88` | 80/tcp ← 0.0.0.0/0<br>443/tcp ← 0.0.0.0/0 | ALB node ×3 |
| `divi-stg-socat` | `sg-04dfb7beb9305b769` | 1433/tcp ← 0.0.0.0/0<br>22/tcp ← 0.0.0.0/0 | EC2 instance ×1 |
| `divi-stg-testing` | `sg-0b8f7c6fd3a03d803` | 22/tcp ← 0.0.0.0/0 | EC2 instance ×1 |
| `divi-stg-vpn` | `sg-01b19333b6393fe60` | 1194/udp ← 0.0.0.0/0<br>22/tcp ← 13.239.158.0/29<br>443/tcp ← 0.0.0.0/0 | EC2 instance ×1 |
| `manual-glue-secuirty-group` | `sg-0852b418b99c692ed` | all traffic ← 0.0.0.0/0 | — |
| `tempec2` | `sg-071206ec91cb67d08` | 3389/tcp ← 0.0.0.0/0 | EC2 instance ×1 |

Egress: all groups allow all outbound traffic.


## 3. Security-group chain (who may talk to whom)

The workload groups use CIDR-based rules rather than group-to-group references: the ECS group, the database group, the MSK group and the NAT instance group all admit the whole VPC CIDR (`10.30.0.0/16` or `10.20.0.0/16`) on their service ports. Lambda ENIs use the database security group (`divi-*-postgres-db`), ECS tasks use `divi-*-ecs-cluster`, and the MSK brokers and MSK Connect workers use `divi-*-cdc-msk`.

| Port | Group that admits it | Admitted from |
|---|---|---|
| 5432/tcp | `divi-*-postgres-db` | whole VPC CIDR |
| 9098, 9094/tcp (and 1433/tcp in stg) | `divi-*-cdc-msk` | whole VPC CIDR |
| 0–65535/tcp | `divi-*-ecs-cluster` | whole VPC CIDR |
| all traffic | `divi-*-nat-instance` | whole VPC CIDR |
| 80, 443/tcp | `divi-*-public-alb` | `0.0.0.0/0` |
