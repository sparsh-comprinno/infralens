import boto3


class AWSScanner:
    def __init__(self, region: str):
        self.region = region
        self.ec2 = boto3.client('ec2', region_name=region)
        self.elbv2 = boto3.client('elbv2', region_name=region)
        self.rds = boto3.client('rds', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)

    # ------------------------------------------------------------------ helpers
    def _tags(self, resource):
        return {t['Key']: t['Value'] for t in resource.get('Tags', [])}

    def _name(self, resource, fallback=''):
        return self._tags(resource).get('Name', fallback)

    # ------------------------------------------------------------------ VPC
    def scan_vpc(self, vpc_name: str) -> dict:
        vpcs = self.ec2.describe_vpcs(
            Filters=[{'Name': 'tag:Name', 'Values': [vpc_name]}]
        )['Vpcs']
        if not vpcs:
            raise ValueError(f"No VPC found with Name tag: {vpc_name}")
        vpc = vpcs[0]
        return {
            'id': vpc['VpcId'],
            'cidr': vpc['CidrBlock'],
            'name': self._name(vpc, vpc['VpcId']),
            'tags': self._tags(vpc),
        }

    # ------------------------------------------------------------------ subnets
    def scan_subnets(self, vpc_id: str) -> list:
        subnets = self.ec2.describe_subnets(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
        )['Subnets']
        result = []
        for s in subnets:
            name = self._name(s, s['SubnetId'])
            tier = 'public' if 'public' in name.lower() else \
                   'db' if 'db' in name.lower() else 'private'
            result.append({
                'id': s['SubnetId'],
                'cidr': s['CidrBlock'],
                'az': s['AvailabilityZone'],
                'public': s.get('MapPublicIpOnLaunch', False),
                'name': name,
                'tier': tier,
                'tags': self._tags(s),
            })
        return result

    # ------------------------------------------------------------------ security groups
    def scan_security_groups(self, vpc_id: str) -> list:
        sgs = self.ec2.describe_security_groups(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
        )['SecurityGroups']
        result = []
        for sg in sgs:
            ingress = [{'from': r['FromPort'] if 'FromPort' in r else -1,
                        'to': r['ToPort'] if 'ToPort' in r else -1,
                        'protocol': r['IpProtocol'],
                        'cidrs': [c['CidrIp'] for c in r.get('IpRanges', [])]}
                       for r in sg.get('IpPermissions', [])]
            result.append({
                'id': sg['GroupId'],
                'name': sg['GroupName'],
                'description': sg['Description'],
                'ingress': ingress,
                'tags': self._tags(sg),
            })
        return result

    # ------------------------------------------------------------------ route tables
    def scan_route_tables(self, vpc_id: str) -> list:
        rts = self.ec2.describe_route_tables(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
        )['RouteTables']
        result = []
        for rt in rts:
            associations = [a['SubnetId'] for a in rt.get('Associations', [])
                            if 'SubnetId' in a]
            main = any(a.get('Main', False) for a in rt.get('Associations', []))
            routes = [{'cidr': r.get('DestinationCidrBlock', ''),
                       'gateway': r.get('GatewayId', r.get('NatGatewayId', r.get('TransitGatewayId', '')))}
                      for r in rt.get('Routes', [])]
            result.append({
                'id': rt['RouteTableId'],
                'name': self._name(rt, rt['RouteTableId']),
                'main': main,
                'subnet_associations': associations,
                'routes': routes,
                'tags': self._tags(rt),
            })
        return result

    # ------------------------------------------------------------------ IGW
    def scan_internet_gateways(self, vpc_id: str) -> list:
        igws = self.ec2.describe_internet_gateways(
            Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
        )['InternetGateways']
        return [{'id': igw['InternetGatewayId'],
                 'name': self._name(igw, igw['InternetGatewayId']),
                 'tags': self._tags(igw)} for igw in igws]

    # ------------------------------------------------------------------ NAT gateways
    def scan_nat_gateways(self, vpc_id: str) -> list:
        nats = self.ec2.describe_nat_gateways(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]},
                     {'Name': 'state', 'Values': ['available', 'pending']}]
        )['NatGateways']
        result = []
        for nat in nats:
            addr = nat.get('NatGatewayAddresses', [{}])[0]
            result.append({
                'id': nat['NatGatewayId'],
                'subnet_id': nat['SubnetId'],
                'name': self._name(nat, nat['NatGatewayId']),
                'eip_allocation_id': addr.get('AllocationId', ''),
                'tags': self._tags(nat),
            })
        return result

    # ------------------------------------------------------------------ EC2 instances
    def scan_ec2_instances(self, vpc_id: str) -> list:
        reservations = self.ec2.describe_instances(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]},
                     {'Name': 'instance-state-name', 'Values': ['running', 'stopped']}]
        )['Reservations']
        result = []
        for r in reservations:
            for i in r['Instances']:
                result.append({
                    'id': i['InstanceId'],
                    'name': self._name(i, i['InstanceId']),
                    'type': i['InstanceType'],
                    'subnet_id': i.get('SubnetId', ''),
                    'private_ip': i.get('PrivateIpAddress', ''),
                    'public_ip': i.get('PublicIpAddress', ''),
                    'ami': i['ImageId'],
                    'key_name': i.get('KeyName', ''),
                    'security_group_ids': [sg['GroupId'] for sg in i.get('SecurityGroups', [])],
                    'tags': self._tags(i),
                })
        return result

    # ------------------------------------------------------------------ RDS
    def scan_rds_instances(self, vpc_id: str) -> list:
        dbs = self.rds.describe_db_instances()['DBInstances']
        result = []
        for db in dbs:
            sg = db.get('DBSubnetGroup', {})
            if sg.get('VpcId') == vpc_id:
                subnet_ids = [s['SubnetIdentifier'] for s in sg.get('Subnets', [])]
                result.append({
                    'id': db['DBInstanceIdentifier'],
                    'engine': db['Engine'],
                    'engine_version': db['EngineVersion'],
                    'instance_class': db['DBInstanceClass'],
                    'multi_az': db['MultiAZ'],
                    'subnet_group': sg['DBSubnetGroupName'],
                    'subnet_ids': subnet_ids,
                    'security_group_ids': [s['VpcSecurityGroupId']
                                           for s in db.get('VpcSecurityGroups', [])],
                    'storage': db['AllocatedStorage'],
                    'tags': {t['Key']: t['Value'] for t in
                             self.rds.list_tags_for_resource(
                                 ResourceName=db['DBInstanceArn'])['TagList']},
                })
        return result

    # ------------------------------------------------------------------ Load Balancers
    def scan_load_balancers(self, vpc_id: str) -> list:
        lbs = self.elbv2.describe_load_balancers()['LoadBalancers']
        result = []
        for lb in lbs:
            if lb.get('VpcId') == vpc_id:
                listeners = self.elbv2.describe_listeners(
                    LoadBalancerArn=lb['LoadBalancerArn']
                ).get('Listeners', [])
                result.append({
                    'arn': lb['LoadBalancerArn'],
                    'name': lb['LoadBalancerName'],
                    'type': lb['Type'],
                    'scheme': lb['Scheme'],
                    'dns': lb['DNSName'],
                    'subnet_ids': [az['SubnetId'] for az in lb.get('AvailabilityZones', [])],
                    'security_group_ids': lb.get('SecurityGroups', []),
                    'listeners': [{'port': l['Port'], 'protocol': l['Protocol']} for l in listeners],
                })
        return result

    # ------------------------------------------------------------------ EKS
    def scan_eks_clusters(self, vpc_id: str) -> list:
        eks = boto3.client('eks', region_name=self.region)
        clusters = eks.list_clusters().get('clusters', [])
        result = []
        for name in clusters:
            desc = eks.describe_cluster(name=name)['cluster']
            resources_vpc = desc.get('resourcesVpcConfig', {})
            if resources_vpc.get('vpcId') == vpc_id:
                result.append({
                    'name': desc['name'],
                    'version': desc['version'],
                    'role_arn': desc['roleArn'],
                    'subnet_ids': resources_vpc.get('subnetIds', []),
                    'security_group_ids': resources_vpc.get('securityGroupIds', []),
                    'endpoint_public_access': resources_vpc.get('endpointPublicAccess', True),
                    'endpoint_private_access': resources_vpc.get('endpointPrivateAccess', False),
                    'tags': desc.get('tags', {}),
                })
        return result

    # ------------------------------------------------------------------ ECS
    def scan_ecs_clusters(self, vpc_id: str) -> list:
        ecs = boto3.client('ecs', region_name=self.region)
        arns = ecs.list_clusters().get('clusterArns', [])
        if not arns:
            return []

        # Get all subnet IDs belonging to this VPC for filtering
        vpc_subnet_ids = {s['SubnetId'] for s in self.ec2.describe_subnets(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
        )['Subnets']}

        clusters = ecs.describe_clusters(clusters=arns, include=['TAGS'])['clusters']
        result = []
        for cluster in clusters:
            svc_arns = ecs.list_services(cluster=cluster['clusterArn']).get('serviceArns', [])
            services = []
            if svc_arns:
                svcs = ecs.describe_services(cluster=cluster['clusterArn'], services=svc_arns)['services']
                for svc in svcs:
                    net = svc.get('networkConfiguration', {}).get('awsvpcConfiguration', {})
                    svc_subnets = net.get('subnets', [])
                    # Only include service if its subnets belong to this VPC
                    if not svc_subnets or not set(svc_subnets) & vpc_subnet_ids:
                        continue
                    services.append({
                        'name': svc['serviceName'],
                        'task_definition': svc['taskDefinition'],
                        'desired_count': svc['desiredCount'],
                        'launch_type': svc.get('launchType', 'FARGATE'),
                        'subnet_ids': svc_subnets,
                        'security_group_ids': net.get('securityGroups', []),
                        'assign_public_ip': net.get('assignPublicIp', 'DISABLED'),
                    })
            if services:
                result.append({
                    'name': cluster['clusterName'],
                    'arn': cluster['clusterArn'],
                    'tags': {t['key']: t['value'] for t in cluster.get('tags', [])},
                    'services': services,
                })
        return result
    def scan_client_vpn_endpoints(self, vpc_id: str) -> list:
        endpoints = self.ec2.describe_client_vpn_endpoints()['ClientVpnEndpoints']
        result = []
        for ep in endpoints:
            if ep.get('VpcId') == vpc_id:
                result.append({
                    'id': ep['ClientVpnEndpointId'],
                    'name': self._name(ep, ep['ClientVpnEndpointId']),
                    'client_cidr': ep['ClientCidrBlock'],
                    'transport_protocol': ep['TransportProtocol'],
                    'vpn_port': ep['VpnPort'],
                    'split_tunnel': ep.get('SplitTunnel', False),
                    'server_certificate_arn': ep['ServerCertificateArn'],
                    'security_group_ids': ep.get('SecurityGroupIds', []),
                    'tags': self._tags(ep),
                })
        return result

    # ------------------------------------------------------------------ S3 (regional)
    def scan_s3_buckets(self) -> list:
        buckets = self.s3.list_buckets()['Buckets']
        result = []
        for b in buckets:
            try:
                loc = self.s3.get_bucket_location(Bucket=b['Name'])['LocationConstraint']
                loc = loc or 'us-east-1'
                if loc == self.region:
                    result.append({'name': b['Name']})
            except Exception:
                continue
        return result

    # ------------------------------------------------------------------ full scan
    def scan_all(self, vpc_name: str) -> dict:
        vpc = self.scan_vpc(vpc_name)
        vpc_id = vpc['id']
        return {
            'vpc': vpc,
            'subnets': self.scan_subnets(vpc_id),
            'security_groups': self.scan_security_groups(vpc_id),
            'route_tables': self.scan_route_tables(vpc_id),
            'internet_gateways': self.scan_internet_gateways(vpc_id),
            'nat_gateways': self.scan_nat_gateways(vpc_id),
            'ec2_instances': self.scan_ec2_instances(vpc_id),
            'rds_instances': self.scan_rds_instances(vpc_id),
            'load_balancers': self.scan_load_balancers(vpc_id),
            'client_vpn_endpoints': self.scan_client_vpn_endpoints(vpc_id),
            'eks_clusters': self.scan_eks_clusters(vpc_id),
            'ecs_clusters': self.scan_ecs_clusters(vpc_id),
            's3_buckets': self.scan_s3_buckets(),
        }
