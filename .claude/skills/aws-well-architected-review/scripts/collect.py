#!/usr/bin/env python3
"""Read-only AWS evidence collector for the aws-well-architected-review skill.

Runs a fixed, reviewed set of read-only AWS CLI calls for ONE account (profile) across the given regions and
writes the JSON output to an evidence directory, together with an access ledger and a manifest. Every call is
validated with the same policy as the PreToolUse guard (readonly-guard.py: check_aws) before it runs; a call the
policy rejects aborts the run as a bug. Secret-bearing fields are never requested (see the --query projections).

    python3 -I collect.py --profile NAME --expect-account 123456789012 \
        --regions eu-west-1,us-east-1 --out /path/to/scratchpad/aws-wa/2026-11-12-prod \
        [--with-metrics] [--metrics-days 30] [--with-cost] [--cost-months 3] \
        [--global-region us-east-1] [--workers 4] [--max-per-type 200] [--max-buckets 300] [--dry-run]

Output layout (<out>/):
    manifest.json       identity (session name redacted), options, timings, counts, caps hit
    ledger.json         one entry per call: status ok | absent | denied | error | auth, error code, file
    global/*.json       IAM, Organizations, S3 (account + per bucket), CloudFront, Route 53, WAF (CloudFront), cost
    <region>/*.json     regional inventory, per-resource follow-ups, metric queries and results
Files that hold an expected "not configured" answer contain {"_absent": "<ErrorCode>"}; denied/failed calls
contain {"_error": {...}}. Run digest.py on the directory next.

Exit codes: 0 done (some calls may be denied — see ledger) · 2 usage · 3 account mismatch ·
4 credentials expired/missing (ask the user to refresh their session) · 5 internal policy violation.
Contains no write operations. Never pass credentials to it; it uses the named profile only.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import concurrent.futures as cf  # noqa: E402
import datetime as dt  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.0.0"


def _load_policy():
    spec = importlib.util.spec_from_file_location("wa_readonly_guard", os.path.join(HERE, "readonly-guard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


POLICY = _load_policy()

# --------------------------------------------------------------------------- call plan
# (service, operation, extra args, --query projection or None). Projections keep output small and exclude
# secret-bearing fields (environment variable values, user data, policy documents where not needed).

ACTIVE_STACK_STATUSES = ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "ROLLBACK_COMPLETE",
                         "IMPORT_COMPLETE", "IMPORT_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED", "ROLLBACK_FAILED",
                         "CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"]

GLOBAL_CALLS = [
    ("iam", "list-account-aliases", [], None),
    ("iam", "get-account-summary", [], None),
    ("iam", "get-account-password-policy", [], None),
    ("iam", "get-credential-report", [], None),
    ("iam", "get-account-authorization-details", ["--filter", "User", "Role", "Group", "LocalManagedPolicy"], None),
    ("iam", "list-open-id-connect-providers", [], None),
    ("iam", "list-saml-providers", [], None),
    ("organizations", "describe-organization", [], "Organization.{Id:Id,Management:MasterAccountId,FeatureSet:FeatureSet}"),
    # --page-size makes the request paginated; S3 only returns BucketRegion on paginated ListBuckets calls.
    ("s3api", "list-buckets", ["--page-size", "1000"], "Buckets[].{Name:Name,Region:BucketRegion,Created:CreationDate}"),
    ("cloudfront", "list-distributions", [],
     "DistributionList.Items[].{Id:Id,Domain:DomainName,Aliases:Aliases.Items,Origins:Origins.Items[].DomainName,"
     "WebACL:WebACLId,Price:PriceClass,Enabled:Enabled,MinTls:ViewerCertificate.MinimumProtocolVersion}"),
    ("route53", "list-hosted-zones", [], "HostedZones[].{Id:Id,Name:Name,Private:Config.PrivateZone,Records:ResourceRecordSetCount}"),
    ("route53", "list-health-checks", [], "HealthChecks[].{Id:Id,Type:HealthCheckConfig.Type}"),
    ("wafv2", "list-web-acls", ["--scope", "CLOUDFRONT"], None),
    ("ec2", "describe-instance-types", ["--filters", "Name=current-generation,Values=false"], "InstanceTypes[].InstanceType"),
]

BUCKET_CALLS = ["get-public-access-block", "get-bucket-policy-status", "get-bucket-versioning",
                "get-bucket-lifecycle-configuration", "get-bucket-encryption", "get-bucket-logging"]

REGIONAL_CALLS = [
    # networking
    ("ec2", "describe-vpcs", [], "Vpcs[].{VpcId:VpcId,Cidr:CidrBlock,IsDefault:IsDefault,Tags:Tags}"),
    ("ec2", "describe-subnets", [], "Subnets[].{SubnetId:SubnetId,VpcId:VpcId,AZ:AvailabilityZone,Cidr:CidrBlock,"
                                    "PublicOnLaunch:MapPublicIpOnLaunch,FreeIps:AvailableIpAddressCount,Tags:Tags}"),
    ("ec2", "describe-route-tables", [], "RouteTables[].{RouteTableId:RouteTableId,VpcId:VpcId,"
                                         "Assoc:Associations[].{SubnetId:SubnetId,Main:Main},"
                                         "Routes:Routes[].{Dest:DestinationCidrBlock,Dest6:DestinationIpv6CidrBlock,"
                                         "Nat:NatGatewayId,Gw:GatewayId,Tgw:TransitGatewayId,"
                                         "Pcx:VpcPeeringConnectionId,Eni:NetworkInterfaceId}}"),
    ("ec2", "describe-internet-gateways", [], "InternetGateways[].{Id:InternetGatewayId,Vpcs:Attachments[].VpcId}"),
    ("ec2", "describe-nat-gateways", [], "NatGateways[].{Id:NatGatewayId,VpcId:VpcId,SubnetId:SubnetId,State:State,"
                                         "Type:ConnectivityType,Mode:AvailabilityMode,Created:CreateTime,Tags:Tags}"),
    ("ec2", "describe-vpc-endpoints", [], "VpcEndpoints[].{Id:VpcEndpointId,VpcId:VpcId,Service:ServiceName,"
                                          "Type:VpcEndpointType,State:State,Subnets:SubnetIds}"),
    ("ec2", "describe-vpc-peering-connections", [],
     "VpcPeeringConnections[].{Id:VpcPeeringConnectionId,Status:Status.Code,"
     "Req:RequesterVpcInfo.{Vpc:VpcId,Acct:OwnerId,Region:Region},Acc:AccepterVpcInfo.{Vpc:VpcId,Acct:OwnerId,Region:Region}}"),
    ("ec2", "describe-transit-gateway-attachments", [],
     "TransitGatewayAttachments[].{Id:TransitGatewayAttachmentId,Tgw:TransitGatewayId,Type:ResourceType,"
     "Res:ResourceId,Owner:ResourceOwnerId,State:State}"),
    ("ec2", "describe-security-groups", [], "SecurityGroups[].{GroupId:GroupId,Name:GroupName,VpcId:VpcId,"
                                            "In:IpPermissions,Out:IpPermissionsEgress}"),
    ("ec2", "describe-network-interfaces", [],
     "NetworkInterfaces[].{Id:NetworkInterfaceId,Status:Status,Type:InterfaceType,Desc:Description,VpcId:VpcId,"
     "SubnetId:SubnetId,AZ:AvailabilityZone,PublicIp:Association.PublicIp,Groups:Groups[].GroupId,"
     "Instance:Attachment.InstanceId,Requester:RequesterId}"),
    ("ec2", "describe-addresses", [], "Addresses[].{Ip:PublicIp,Alloc:AllocationId,Assoc:AssociationId,"
                                      "Instance:InstanceId,Eni:NetworkInterfaceId,Tags:Tags}"),
    ("ec2", "describe-flow-logs", [], "FlowLogs[].{Id:FlowLogId,Res:ResourceId,Dest:LogDestinationType,Status:FlowLogStatus}"),
    # compute
    ("ec2", "describe-instances", [],
     "Reservations[].Instances[].{Id:InstanceId,Type:InstanceType,State:State.Name,AZ:Placement.AvailabilityZone,"
     "SubnetId:SubnetId,VpcId:VpcId,PublicIp:PublicIpAddress,HttpTokens:MetadataOptions.HttpTokens,"
     "Profile:IamInstanceProfile.Arn,Platform:PlatformDetails,Arch:Architecture,Launched:LaunchTime,"
     "StateReason:StateTransitionReason,Lifecycle:InstanceLifecycle,Groups:SecurityGroups[].GroupId,"
     "Volumes:BlockDeviceMappings[].Ebs.VolumeId,Tags:Tags}"),
    ("ec2", "describe-volumes", [], "Volumes[].{Id:VolumeId,GiB:Size,Type:VolumeType,Iops:Iops,Tput:Throughput,"
                                    "State:State,Enc:Encrypted,AZ:AvailabilityZone,Attached:Attachments[].InstanceId,"
                                    "Created:CreateTime,Tags:Tags}"),
    ("ec2", "describe-snapshots", ["--owner-ids", "self"],
     "Snapshots[].{Id:SnapshotId,Vol:VolumeId,GiB:VolumeSize,Start:StartTime,Tier:StorageTier,Desc:Description}"),
    ("ec2", "describe-images", ["--owners", "self"], "Images[].{Id:ImageId,Name:Name,Created:CreationDate,"
                                                     "Snaps:BlockDeviceMappings[].Ebs.SnapshotId}"),
    ("ec2", "get-ebs-encryption-by-default", [], None),
    ("ec2", "get-instance-metadata-defaults", [], None),
    ("autoscaling", "describe-auto-scaling-groups", [],
     "AutoScalingGroups[].{Name:AutoScalingGroupName,Min:MinSize,Max:MaxSize,Desired:DesiredCapacity,"
     "AZs:AvailabilityZones,HC:HealthCheckType,Grace:HealthCheckGracePeriod,TGs:TargetGroupARNs,"
     "CLBs:LoadBalancerNames,LC:LaunchConfigurationName,LT:LaunchTemplate.LaunchTemplateName,"
     "MixedLT:MixedInstancesPolicy.LaunchTemplate.LaunchTemplateSpecification.LaunchTemplateName,"
     "Instances:Instances[].InstanceId,Tags:Tags[].{Key:Key,Value:Value}}"),
    ("autoscaling", "describe-launch-configurations", [],
     "LaunchConfigurations[].{Name:LaunchConfigurationName,Type:InstanceType,Created:CreatedTime}"),
    ("autoscaling", "describe-policies", [], "ScalingPolicies[].{Asg:AutoScalingGroupName,Name:PolicyName,Type:PolicyType}"),
    ("elbv2", "describe-load-balancers", [], "LoadBalancers[].{Arn:LoadBalancerArn,Name:LoadBalancerName,Type:Type,"
                                             "Scheme:Scheme,State:State.Code,AZs:AvailabilityZones[].ZoneName,"
                                             "VpcId:VpcId,Created:CreatedTime}"),
    ("elbv2", "describe-target-groups", [], "TargetGroups[].{Arn:TargetGroupArn,Name:TargetGroupName,LBs:LoadBalancerArns,"
                                            "Type:TargetType,Proto:Protocol,Port:Port,HCPath:HealthCheckPath}"),
    ("elb", "describe-load-balancers", [], "LoadBalancerDescriptions[].{Name:LoadBalancerName,Scheme:Scheme,"
                                           "Instances:Instances[].InstanceId,AZs:AvailabilityZones,Created:CreatedTime}"),
    ("wafv2", "list-web-acls", ["--scope", "REGIONAL"], None),
    ("ecs", "list-clusters", [], None),
    ("eks", "list-clusters", [], None),
    ("lambda", "list-functions", [],
     "Functions[].{Name:FunctionName,Runtime:Runtime,Mem:MemorySize,Timeout:Timeout,Arch:Architectures,"
     "Pkg:PackageType,Modified:LastModified,Vpc:VpcConfig.VpcId,DLQ:DeadLetterConfig.TargetArn,"
     "EnvKeys:keys(Environment.Variables || `{}`)}"),
    ("lambda", "list-event-source-mappings", [],
     "EventSourceMappings[].{Fn:FunctionArn,Src:EventSourceArn,Batch:BatchSize,State:State,"
     "Retries:MaximumRetryAttempts,OnFailure:DestinationConfig.OnFailure.Destination,Partial:FunctionResponseTypes}"),
    ("lambda", "get-account-settings", [], "AccountLimit"),
    # data
    ("rds", "describe-db-instances", [],
     "DBInstances[].{Id:DBInstanceIdentifier,Class:DBInstanceClass,Engine:Engine,Ver:EngineVersion,"
     "Life:EngineLifecycleSupport,MultiAZ:MultiAZ,AZ:AvailabilityZone,Storage:StorageType,GiB:AllocatedStorage,"
     "MaxGiB:MaxAllocatedStorage,Iops:Iops,Tput:StorageThroughput,Enc:StorageEncrypted,Public:PubliclyAccessible,"
     "Backup:BackupRetentionPeriod,DelProt:DeletionProtection,PI:PerformanceInsightsEnabled,Mon:MonitoringInterval,"
     "Cluster:DBClusterIdentifier,Source:ReadReplicaSourceDBInstanceIdentifier,"
     "Replicas:ReadReplicaDBInstanceIdentifiers,Status:DBInstanceStatus,Created:InstanceCreateTime,"
     "SGs:VpcSecurityGroups[].VpcSecurityGroupId,Tags:TagList}"),
    ("rds", "describe-db-clusters", [],
     "DBClusters[].{Id:DBClusterIdentifier,Engine:Engine,Ver:EngineVersion,Mode:EngineMode,MultiAZ:MultiAZ,"
     "Storage:StorageType,Members:DBClusterMembers[].{Id:DBInstanceIdentifier,Writer:IsClusterWriter},"
     "Backup:BackupRetentionPeriod,DelProt:DeletionProtection,Enc:StorageEncrypted,"
     "Sv2:ServerlessV2ScalingConfiguration,AZs:AvailabilityZones,Life:EngineLifecycleSupport,Tags:TagList}"),
    ("rds", "describe-db-snapshots", ["--snapshot-type", "manual"],
     "DBSnapshots[].{Id:DBSnapshotIdentifier,Db:DBInstanceIdentifier,GiB:AllocatedStorage,Created:SnapshotCreateTime,"
     "Enc:Encrypted}"),
    ("rds", "describe-db-major-engine-versions", [], None),
    ("dynamodb", "list-tables", [], None),
    ("elasticache", "describe-replication-groups", [],
     "ReplicationGroups[].{Id:ReplicationGroupId,Status:Status,MultiAZ:MultiAZ,Failover:AutomaticFailover,"
     "Node:CacheNodeType,Members:MemberClusters,AtRest:AtRestEncryptionEnabled,Transit:TransitEncryptionEnabled,"
     "Engine:Engine}"),
    ("elasticache", "describe-cache-clusters", [],
     "CacheClusters[].{Id:CacheClusterId,Engine:Engine,Ver:EngineVersion,Node:CacheNodeType,Nodes:NumCacheNodes,"
     "Group:ReplicationGroupId,AZ:PreferredAvailabilityZone}"),
    ("elasticache", "describe-serverless-caches", [], "ServerlessCaches[].{Name:ServerlessCacheName,Engine:Engine,Status:Status}"),
    ("opensearch", "list-domain-names", [], None),
    ("efs", "describe-file-systems", [], "FileSystems[].{Id:FileSystemId,Tput:ThroughputMode,Perf:PerformanceMode,"
                                         "Enc:Encrypted,Bytes:SizeInBytes.Value,OneZone:AvailabilityZoneName,"
                                         "MountTargets:NumberOfMountTargets}"),
    # integration
    ("sqs", "list-queues", [], None),
    ("sns", "list-topics", [], None),
    ("events", "list-rules", [], "Rules[].{Name:Name,State:State,Bus:EventBusName,Schedule:ScheduleExpression}"),
    ("apigateway", "get-rest-apis", [], "items[].{Id:id,Name:name,Types:endpointConfiguration.types}"),
    ("apigatewayv2", "get-apis", [], "Items[].{Id:ApiId,Name:Name,Proto:ProtocolType}"),
    # security & governance
    ("cloudtrail", "describe-trails", [], None),
    ("configservice", "describe-configuration-recorders", [], None),
    ("configservice", "describe-configuration-recorder-status", [], None),
    ("guardduty", "list-detectors", [], None),
    ("securityhub", "describe-hub", [], "{HubArn:HubArn,Subscribed:SubscribedAt}"),
    ("accessanalyzer", "list-analyzers", [], "analyzers[].{Name:name,Type:type,Status:status}"),
    ("kms", "list-keys", [], None),
    ("secretsmanager", "list-secrets", [], "SecretList[].{Name:Name,Rotation:RotationEnabled,LastRotated:LastRotatedDate,"
                                           "LastAccessed:LastAccessedDate,Kms:KmsKeyId,Owner:OwningService}"),
    ("ssm", "describe-instance-information", [], "InstanceInformationList[].{Id:InstanceId,Ping:PingStatus,"
                                                 "Platform:PlatformName,Agent:AgentVersion}"),
    ("acm", "list-certificates", [], "CertificateSummaryList[].{Arn:CertificateArn,Domain:DomainName,Status:Status,"
                                     "NotAfter:NotAfter,InUse:InUse,Type:Type}"),
    # operations & recovery
    ("cloudwatch", "describe-alarms", [],
     "{Metric:MetricAlarms[].{Name:AlarmName,State:StateValue,Enabled:ActionsEnabled,Actions:AlarmActions,"
     "Ns:Namespace,Metric:MetricName},Composite:CompositeAlarms[].{Name:AlarmName,State:StateValue,Actions:AlarmActions}}"),
    ("logs", "describe-log-groups", [], "logGroups[].{Name:logGroupName,Retention:retentionInDays,Bytes:storedBytes,"
                                        "Class:logGroupClass}"),
    ("backup", "list-backup-plans", [], "BackupPlansList[].{Name:BackupPlanName,Id:BackupPlanId}"),
    ("backup", "list-protected-resources", [], "Results[].{Arn:ResourceArn,Type:ResourceType,Last:LastBackupTime}"),
    ("backup", "list-backup-vaults", [], "BackupVaultList[].{Name:BackupVaultName,Locked:Locked,Points:NumberOfRecoveryPoints}"),
    ("cloudformation", "list-stacks", ["--stack-status-filter", *ACTIVE_STACK_STATUSES],
     "StackSummaries[].{Name:StackName,Status:StackStatus,Drift:DriftInformation.StackDriftStatus,"
     "Updated:LastUpdatedTime,Created:CreationTime}"),
]

COST_REGIONAL_CALLS = [("compute-optimizer", "get-recommendation-summaries", [], None)]

# Expected answers that mean "not configured" rather than "not allowed".
ABSENT_CODES = {"NoSuchEntity", "NoSuchLifecycleConfiguration", "ServerSideEncryptionConfigurationNotFoundError",
                "NoSuchPublicAccessBlockConfiguration", "NoSuchBucketPolicy", "ReportNotPresent", "ReportExpired",
                "ReportInProgress", "AWSOrganizationsNotInUseException", "ResourceNotFoundException",
                "DataUnavailableException", "OptInRequiredException", "NoSuchConfigurationRecorderException",
                "NotFoundException", "InvalidAccessException", "NoSuchTagSet"}
DENIED_CODES = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "AuthorizationError",
                "UnauthorizedException", "Forbidden", "AuthFailure", "UnrecognizedClientException", "OptInRequired",
                "SubscriptionRequiredException", "InvalidClientTokenId"}
THROTTLE_CODES = {"Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequestsException", "SlowDown",
                  "RequestThrottled", "RequestThrottledException", "LimitExceededException"}
AUTH_FAILURE = re.compile(r"ExpiredToken|token has expired|SSO session .*(expired|invalid)|Error loading SSO Token|"
                          r"refresh failed|Unable to locate credentials|profile \(.*\) could not be found", re.I)
ERR_CODE = re.compile(r"An error occurred \(([A-Za-z0-9_.]+)\)")
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d+$")


def redact(text):
    """Remove role session names (often e-mail addresses) and access key IDs from text."""
    text = re.sub(r"(assumed-role/[^/\s:\"']+/)[^\s\"',]+", r"\1<session>", text)
    text = re.sub(r"\b(AROA[A-Z0-9]{12,}):[^\s\"',]+", r"\1:<session>", text)
    return re.sub(r"\b(A[SK]IA[A-Z0-9]{16})\b", "<access-key-id>", text)


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name))[:120]


def chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + y, month=m + 1, day=1)


class PolicyViolation(RuntimeError):
    pass


class Collector:
    def __init__(self, a):
        self.a = a
        self.lock = threading.Lock()
        self.ledger, self.caps, self.planned = [], [], []
        self.abort = None
        self.account = None
        # TZ=UTC: the AWS CLI renders epoch timestamps (CloudWatch, ECS, Secrets Manager, ...) in the machine's local time zone;
        # forcing UTC keeps every saved timestamp comparable and hour-of-day analysis correct.
        self.env = dict(os.environ, AWS_PAGER="", AWS_CLI_AUTO_PROMPT="off", TZ="UTC")

    # ---- primitives
    def call(self, region, service, op, *args, query=None, key=None, folder=None, redact_output=False):
        argv = [service, op, *map(str, args), "--profile", self.a.profile, "--region", region,
                "--output", "json", "--no-cli-pager"]
        if query:
            argv += ["--query", query]
        problems = POLICY.check_aws(argv)
        if problems:
            raise PolicyViolation(f"aws {' '.join(argv)} -> {problems}")
        folder = folder or region
        rel = os.path.join(folder, f"{service}.{op}" + (f".{safe(key)}" if key else "") + ".json")
        if self.a.dry_run:
            with self.lock:
                self.planned.append("aws " + " ".join(a if " " not in a else repr(a) for a in argv))
            return None
        if self.abort:
            return None
        delay = 1.0
        for attempt in range(6):
            t0 = time.monotonic()
            try:
                p = subprocess.run(["aws", *argv], capture_output=True, text=True, timeout=self.a.timeout, env=self.env)
            except subprocess.TimeoutExpired:
                return self._fail(region, service, op, key, rel, "error", "Timeout", f"timed out after {self.a.timeout}s", t0)
            except FileNotFoundError:
                self.abort = "AWS CLI not found on PATH"
                return None
            if p.returncode == 0:
                out = p.stdout
                if redact_output:
                    out = redact(out)
                try:
                    data = json.loads(out) if out.strip() else None
                except json.JSONDecodeError:
                    return self._fail(region, service, op, key, rel, "error", "BadJSON", out[:200], t0)
                self._write(rel, data)
                self._log(region, service, op, key, rel, "ok", None, None, t0)
                return data
            err = p.stderr.strip()
            m = ERR_CODE.search(err)
            code = m.group(1) if m else None
            if (code in THROTTLE_CODES or "Rate exceeded" in err) and attempt < 5:
                time.sleep(delay + random.random())
                delay = min(delay * 2, 20)
                continue
            if code not in DENIED_CODES and AUTH_FAILURE.search(err):
                self.abort = redact(err.splitlines()[-1] if err else "authentication failure")
                return self._fail(region, service, op, key, rel, "auth", code, err, t0)
            if code in ABSENT_CODES:
                self._write(rel, {"_absent": code})
                self._log(region, service, op, key, rel, "absent", code, None, t0)
                return None
            status = "denied" if code in DENIED_CODES else "error"
            return self._fail(region, service, op, key, rel, status, code, err, t0)
        return None

    def _fail(self, region, service, op, key, rel, status, code, msg, t0):
        self._write(rel, {"_error": {"status": status, "code": code}})
        self._log(region, service, op, key, rel, status, code, msg, t0)
        return None

    def _write(self, rel, data):
        path = os.path.join(self.a.out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh, default=str, separators=(",", ":"))

    def _log(self, region, service, op, key, rel, status, code, msg, t0):
        entry = {"region": region, "service": service, "op": op, "key": key, "status": status, "code": code,
                 "file": rel, "seconds": round(time.monotonic() - t0, 2)}
        if msg:
            entry["message"] = redact(" ".join(msg.split()))[:300]
        with self.lock:
            self.ledger.append(entry)

    def cap(self, items, what, region, limit=None):
        items = list(items or [])
        limit = limit or self.a.max_per_type
        if len(items) > limit:
            with self.lock:
                self.caps.append({"region": region, "what": what, "total": len(items), "collected": limit})
        return items[:limit]

    # ---- stages
    def identity(self):
        data = self.call(self.a.global_region, "sts", "get-caller-identity", folder="global", redact_output=True)
        if self.a.dry_run:
            return True
        if not data:
            return False
        self.account = data.get("Account")
        return True

    def global_stage(self):
        g = self.a.global_region
        res = {}
        for svc, op, args, query in GLOBAL_CALLS:
            res[(svc, op)] = self.call(g, svc, op, *args, query=query, folder="global")
        acct = self.account or "123456789012"
        self.call(g, "s3control", "get-public-access-block", "--account-id", acct, folder="global")
        buckets = self.cap(res.get(("s3api", "list-buckets")), "s3 buckets", "global", self.a.max_buckets)
        jobs = [(b.get("Region") or "us-east-1", b["Name"], op) for b in buckets if b.get("Name") for op in BUCKET_CALLS]
        with cf.ThreadPoolExecutor(max_workers=max(1, self.a.workers * 2)) as pool:
            list(pool.map(lambda j: self.call(j[0], "s3api", j[2], "--bucket", j[1], key=j[1], folder="global"), jobs))

    def region_stage(self, r):
        res = {}
        for svc, op, args, query in REGIONAL_CALLS:
            res[(svc, op)] = self.call(r, svc, op, *args, query=query)
        if self.a.dry_run or self.abort:
            return
        c = lambda *a, **k: self.call(r, *a, **k)  # noqa: E731
        for tg in self.cap(res.get(("elbv2", "describe-target-groups")), "target groups", r):
            c("elbv2", "describe-target-health", "--target-group-arn", tg["Arn"], key=tg["Name"],
              query="TargetHealthDescriptions[].{Id:Target.Id,State:TargetHealth.State}")
        for acl in self.cap((res.get(("wafv2", "list-web-acls")) or {}).get("WebACLs"), "regional web ACLs", r):
            c("wafv2", "list-resources-for-web-acl", "--web-acl-arn", acl["ARN"], key=acl["Name"])
        clusters = self.cap((res.get(("ecs", "list-clusters")) or {}).get("clusterArns"), "ecs clusters", r)
        for i, chunk in enumerate(chunks(clusters, 100)):
            c("ecs", "describe-clusters", "--clusters", *chunk, "--include", "SETTINGS", key=str(i),
              query="clusters[].{Name:clusterName,Status:status,Instances:registeredContainerInstancesCount,"
                    "Running:runningTasksCount,Services:activeServicesCount,CPs:capacityProviders,Settings:settings}")
        for arn in clusters:
            name = arn.rsplit("/", 1)[-1]
            sarns = (c("ecs", "list-services", "--cluster", arn, key=name) or {}).get("serviceArns") or []
            for i, chunk in enumerate(chunks(self.cap(sarns, f"ecs services in {name}", r), 10)):
                c("ecs", "describe-services", "--cluster", arn, "--services", *chunk, key=f"{name}.{i}",
                  query="services[].{Name:serviceName,Desired:desiredCount,Running:runningCount,Launch:launchType,"
                        "CPS:capacityProviderStrategy[].capacityProvider,CB:deploymentConfiguration.deploymentCircuitBreaker,"
                        "Subnets:networkConfiguration.awsvpcConfiguration.subnets,TD:taskDefinition,"
                        "Grace:healthCheckGracePeriodSeconds,LBs:length(loadBalancers),PV:platformVersion}")
        eks = self.cap((res.get(("eks", "list-clusters")) or {}).get("clusters"), "eks clusters", r)
        if eks:
            c("eks", "describe-cluster-versions", "--include-all",
              query="clusterVersions[].{Version:clusterVersion,Status:versionStatus,"
                    "EndStandard:endOfStandardSupportDate,EndExtended:endOfExtendedSupportDate}")
        for name in eks:
            c("eks", "describe-cluster", "--name", name, key=name,
              query="cluster.{Name:name,Version:version,Status:status,Platform:platformVersion,"
                    "Subnets:resourcesVpcConfig.subnetIds,Public:resourcesVpcConfig.endpointPublicAccess,"
                    "Private:resourcesVpcConfig.endpointPrivateAccess,PublicCidrs:resourcesVpcConfig.publicAccessCidrs,"
                    "Logging:logging.clusterLogging,Support:upgradePolicy.supportType,Created:createdAt}")
            ngs = (c("eks", "list-nodegroups", "--cluster-name", name, key=name) or {}).get("nodegroups") or []
            for ng in self.cap(ngs, f"nodegroups in {name}", r):
                c("eks", "describe-nodegroup", "--cluster-name", name, "--nodegroup-name", ng, key=f"{name}.{ng}",
                  query="nodegroup.{Name:nodegroupName,Types:instanceTypes,Capacity:capacityType,Scaling:scalingConfig,"
                        "Subnets:subnets,Ami:amiType,Version:version,Status:status}")
        for t in self.cap((res.get(("dynamodb", "list-tables")) or {}).get("TableNames"), "dynamodb tables", r):
            c("dynamodb", "describe-table", "--table-name", t, key=t,
              query="Table.{Name:TableName,Billing:BillingModeSummary.BillingMode,"
                    "RCU:ProvisionedThroughput.ReadCapacityUnits,WCU:ProvisionedThroughput.WriteCapacityUnits,"
                    "Bytes:TableSizeBytes,Items:ItemCount,GSIs:length(GlobalSecondaryIndexes || `[]`),"
                    "Class:TableClassSummary.TableClass,DelProt:DeletionProtectionEnabled,"
                    "Stream:StreamSpecification.StreamEnabled,Replicas:length(Replicas || `[]`)}")
            c("dynamodb", "describe-continuous-backups", "--table-name", t, key=t,
              query="ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus")
        for q in self.cap((res.get(("sqs", "list-queues")) or {}).get("QueueUrls"), "sqs queues", r):
            c("sqs", "get-queue-attributes", "--queue-url", q, "--attribute-names", "QueueArn", "VisibilityTimeout",
              "MessageRetentionPeriod", "RedrivePolicy", "ReceiveMessageWaitTimeSeconds", "SqsManagedSseEnabled",
              "KmsMasterKeyId", "FifoQueue", "ApproximateNumberOfMessages", key=q.rsplit("/", 1)[-1])
        for t in (res.get(("cloudtrail", "describe-trails")) or {}).get("trailList") or []:
            if t.get("HomeRegion") == r:
                c("cloudtrail", "get-trail-status", "--name", t["TrailARN"], key=t.get("Name"),
                  query="{IsLogging:IsLogging,LatestDeliveryError:LatestDeliveryError,LatestDeliveryTime:LatestDeliveryTime}")
        for d in (res.get(("guardduty", "list-detectors")) or {}).get("DetectorIds") or []:
            c("guardduty", "get-detector", "--detector-id", d, key=d, query="{Status:Status,Updated:UpdatedAt}")
        for k in self.cap((res.get(("kms", "list-keys")) or {}).get("Keys"), "kms keys", r):
            md = c("kms", "describe-key", "--key-id", k["KeyId"], key=k["KeyId"],
                   query="KeyMetadata.{Id:KeyId,Manager:KeyManager,State:KeyState,Spec:KeySpec,Usage:KeyUsage,"
                         "Origin:Origin,MultiRegion:MultiRegion}")
            if md and md.get("Manager") == "CUSTOMER" and md.get("State") == "Enabled" \
                    and md.get("Spec") == "SYMMETRIC_DEFAULT" and md.get("Origin") == "AWS_KMS":
                c("kms", "get-key-rotation-status", "--key-id", k["KeyId"], key=k["KeyId"])
        if self.a.with_cost:
            for svc, op, args, query in COST_REGIONAL_CALLS:
                c(svc, op, *args, query=query)
        if self.a.with_metrics:
            self.metrics(r, res)

    def metrics(self, r, res):
        specs = []  # (namespace, metric, [(dim, value)], stat, resource label)
        for i in res.get(("ec2", "describe-instances")) or []:
            if i.get("State") == "running":
                for st in ("Average", "Maximum"):
                    specs.append(("AWS/EC2", "CPUUtilization", [("InstanceId", i["Id"])], st, i["Id"]))
        for d in res.get(("rds", "describe-db-instances")) or []:
            dim = [("DBInstanceIdentifier", d["Id"])]
            specs += [("AWS/RDS", "CPUUtilization", dim, "Average", d["Id"]), ("AWS/RDS", "CPUUtilization", dim, "Maximum", d["Id"]),
                      ("AWS/RDS", "DatabaseConnections", dim, "Maximum", d["Id"]), ("AWS/RDS", "FreeableMemory", dim, "Minimum", d["Id"]),
                      ("AWS/RDS", "ReadIOPS", dim, "Maximum", d["Id"]), ("AWS/RDS", "WriteIOPS", dim, "Maximum", d["Id"])]
        for n in res.get(("ec2", "describe-nat-gateways")) or []:
            if n.get("State") == "available":
                for m in ("BytesInFromSource", "BytesInFromDestination", "ErrorPortAllocation"):
                    specs.append(("AWS/NATGateway", m, [("NatGatewayId", n["Id"])], "Sum", n["Id"]))
        for lb in res.get(("elbv2", "describe-load-balancers")) or []:
            suffix = lb["Arn"].split(":loadbalancer/", 1)[-1]
            if lb.get("Type") == "application":
                specs.append(("AWS/ApplicationELB", "RequestCount", [("LoadBalancer", suffix)], "Sum", lb["Name"]))
            elif lb.get("Type") == "network":
                specs.append(("AWS/NetworkELB", "ProcessedBytes", [("LoadBalancer", suffix)], "Sum", lb["Name"]))
        for f in self.cap(res.get(("lambda", "list-functions")), "lambda functions (metrics)", r):
            dim = [("FunctionName", f["Name"])]
            specs += [("AWS/Lambda", "Invocations", dim, "Sum", f["Name"]), ("AWS/Lambda", "Errors", dim, "Sum", f["Name"]),
                      ("AWS/Lambda", "Throttles", dim, "Sum", f["Name"]), ("AWS/Lambda", "Duration", dim, "Maximum", f["Name"]),
                      ("AWS/Lambda", "ConcurrentExecutions", dim, "Maximum", f["Name"])]
        for cc in res.get(("elasticache", "describe-cache-clusters")) or []:
            dim = [("CacheClusterId", cc["Id"])]
            specs += [("AWS/ElastiCache", "CPUUtilization", dim, "Average", cc["Id"]),
                      ("AWS/ElastiCache", "CPUUtilization", dim, "Maximum", cc["Id"]),
                      ("AWS/ElastiCache", "Evictions", dim, "Sum", cc["Id"])]
        if not specs:
            return
        specs = self.cap(specs, "metric queries", r, limit=4000)
        end = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - dt.timedelta(days=self.a.metrics_days)
        mapping = {}
        for b, batch in enumerate(chunks(specs, 500)):
            queries = []
            for j, (ns, metric, dims, stat, label) in enumerate(batch):
                qid = f"m{b}_{j}"
                mapping[qid] = {"ns": ns, "metric": metric, "stat": stat, "resource": label}
                queries.append({"Id": qid, "ReturnData": True, "MetricStat": {
                    "Metric": {"Namespace": ns, "MetricName": metric,
                               "Dimensions": [{"Name": k, "Value": v} for k, v in dims]},
                    "Period": 86400, "Stat": stat}})
            qpath = os.path.join(self.a.out, r, f"metric-queries.{b}.json")
            os.makedirs(os.path.dirname(qpath), exist_ok=True)
            with open(qpath, "w") as fh:
                json.dump(queries, fh)
            self.call(r, "cloudwatch", "get-metric-data", "--metric-data-queries", f"file://{qpath}",
                      "--start-time", start.isoformat(), "--end-time", end.isoformat(), key=str(b),
                      query="MetricDataResults[].{Id:Id,Values:Values,Status:StatusCode}")
        self._write(os.path.join(r, "metric-map.json"), {"days": self.a.metrics_days, "period": 86400,
                                                          "start": start.isoformat(), "end": end.isoformat(), "map": mapping})

    def cost_stage(self):
        ce = "us-east-1"
        first = dt.datetime.now(dt.timezone.utc).date().replace(day=1)
        start, last = add_months(first, -self.a.cost_months), add_months(first, -1)
        span, month = f"Start={start},End={first}", f"Start={last},End={first}"
        for key, dim in (("by-service", "SERVICE"), ("by-region", "REGION"), ("by-account", "LINKED_ACCOUNT")):
            self.call(ce, "ce", "get-cost-and-usage", "--time-period", span, "--granularity", "MONTHLY",
                      "--metrics", "UnblendedCost", "NetAmortizedCost", "--group-by", f"Type=DIMENSION,Key={dim}",
                      key=key, folder="global")
        self.call(ce, "ce", "get-cost-and-usage", "--time-period", month, "--granularity", "MONTHLY",
                  "--metrics", "UnblendedCost", "--group-by", "Type=DIMENSION,Key=USAGE_TYPE",
                  key="by-usage-type", folder="global")
        for op in ("get-savings-plans-coverage", "get-savings-plans-utilization", "get-reservation-coverage",
                   "get-reservation-utilization"):
            self.call(ce, "ce", op, "--time-period", month, "--granularity", "MONTHLY", folder="global")
        self.call(self.a.global_region, "compute-optimizer", "get-enrollment-status", folder="global")
        self.call(ce, "trustedadvisor", "list-recommendations", folder="global",
                  query="recommendationSummaries[].{Name:name,Pillars:pillars,Status:status,Source:source,"
                        "Savings:pillarSpecificAggregates.costOptimizing.estimatedMonthlySavings,"
                        "Resources:resourcesAggregates}")


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Read-only AWS evidence collector (aws-well-architected-review).")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--expect-account", help="abort unless the profile resolves to this 12-digit account ID")
    ap.add_argument("--regions", required=True, help="comma-separated region list confirmed with the user")
    ap.add_argument("--out", required=True, help="evidence directory (use the session scratchpad, not reports/)")
    ap.add_argument("--global-region", default="us-east-1")
    ap.add_argument("--with-metrics", action="store_true", help="CloudWatch daily avg/max/sum for key resources")
    ap.add_argument("--metrics-days", type=int, default=30)
    ap.add_argument("--with-cost", action="store_true",
                    help="Cost Explorer (billed per request, ~10 calls), Compute Optimizer, Trusted Advisor")
    ap.add_argument("--cost-months", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-per-type", type=int, default=200, help="cap for per-resource follow-up calls")
    ap.add_argument("--max-buckets", type=int, default=300)
    ap.add_argument("--timeout", type=int, default=300, help="seconds per AWS CLI call")
    ap.add_argument("--dry-run", action="store_true", help="print and policy-check the base call plan; call nothing")
    a = ap.parse_args(argv)
    a.regions = [r.strip() for r in a.regions.split(",") if r.strip()]
    bad = [r for r in a.regions + [a.global_region] if not REGION_RE.match(r)]
    if bad or not a.regions:
        ap.error(f"invalid region(s): {bad or 'none given'}")
    if a.expect_account and not re.fullmatch(r"\d{12}", a.expect_account):
        ap.error("--expect-account must be a 12-digit account ID")
    if not 1 <= a.metrics_days <= 455 or not 1 <= a.cost_months <= 12:
        ap.error("--metrics-days must be 1..455 and --cost-months 1..12")
    a.out = os.path.abspath(a.out)
    return a


def main(argv=None):
    a = parse_args(argv if argv is not None else sys.argv[1:])
    col = Collector(a)
    started = dt.datetime.now(dt.timezone.utc)
    status, code = "complete", 0
    try:
        if not col.identity():
            status, code = f"aborted: identity check failed ({col.abort or 'see ledger'})", 4
        elif not a.dry_run and a.expect_account and col.account != a.expect_account:
            status, code = f"aborted: profile resolves to account {col.account}, expected {a.expect_account}", 3
        else:
            print(f"[collect] account {col.account or '(dry-run)'} · regions {', '.join(a.regions)}", file=sys.stderr, flush=True)
            col.global_stage()
            with cf.ThreadPoolExecutor(max_workers=max(1, min(a.workers, len(a.regions)))) as pool:
                for r, fut in [(r, pool.submit(col.region_stage, r)) for r in a.regions]:
                    fut.result()
                    print(f"[collect] {r} done", file=sys.stderr, flush=True)
            if a.with_cost:
                col.cost_stage()
            if col.abort:
                status, code = f"aborted: {col.abort}", 4
    except PolicyViolation as exc:
        status, code = f"aborted: internal policy violation: {exc}", 5
    if a.dry_run:
        print("\n".join(col.planned))
        print(f"\n[dry-run] {len(col.planned)} base calls planned and policy-checked "
              "(+ per-resource follow-ups at run time). Nothing was called.", file=sys.stderr)
        return code
    counts = {}
    for e in col.ledger:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    manifest = {
        "collector": VERSION, "status": status, "profile": a.profile, "account": col.account,
        "started": started.isoformat(), "finished": dt.datetime.now(dt.timezone.utc).isoformat(),
        "regions": a.regions, "global_region": a.global_region, "timestamps": "UTC (AWS CLI run with TZ=UTC)",
        "options": {"with_metrics": a.with_metrics, "metrics_days": a.metrics_days, "with_cost": a.with_cost,
                    "cost_months": a.cost_months, "max_per_type": a.max_per_type, "max_buckets": a.max_buckets},
        "counts": counts, "caps": col.caps,
    }
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "ledger.json"), "w") as fh:
        json.dump(sorted(col.ledger, key=lambda e: (e["region"], e["service"], e["op"], str(e["key"]))), fh, indent=1)
    with open(os.path.join(a.out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"[collect] {status} · {counts} · evidence: {a.out}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
