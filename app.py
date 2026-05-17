import sys
import boto3
from scanner import AWSScanner
from generator import InfraGenerator


def main():
    try:
        session = boto3.Session()
        default_region = session.region_name or "us-east-1"
    except Exception as e:
        print(f"❌ Error initializing AWS session: {e}")
        sys.exit(1)

    vpc_name = input("Enter VPC name: ").strip()
    env = input("Enter environment (default: prod): ").strip() or "prod"
    region = input(f"Enter AWS region (default: {default_region}): ").strip() or default_region

    print(f"🚀 Scanning VPC '{vpc_name}' in region '{region}'...")

    try:
        scanner = AWSScanner(region=region)
        data = scanner.scan_all(vpc_name)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ AWS error: {e}")
        print("Ensure your AWS credentials are configured correctly.")
        sys.exit(1)

    vpc = data['vpc']
    print(f"✨ Scan complete for VPC: {vpc['name']} ({vpc['id']}, {vpc['cidr']})")
    print(f"   Subnets: {len(data['subnets'])}  |  SGs: {len(data['security_groups'])}  |  "
          f"Route Tables: {len(data['route_tables'])}  |  IGWs: {len(data['internet_gateways'])}")
    print(f"   NAT GWs: {len(data['nat_gateways'])}  |  EC2: {len(data['ec2_instances'])}  |  "
          f"RDS: {len(data['rds_instances'])}  |  LBs: {len(data['load_balancers'])}  |  "
          f"EKS: {len(data['eks_clusters'])}  |  ECS: {len(data['ecs_clusters'])}  |  "
          f"VPN Endpoints: {len(data['client_vpn_endpoints'])}  |  S3: {len(data['s3_buckets'])}")

    generator = InfraGenerator(region=region, env=env, data=data)

    print("\n🛠️  Generating modular Terraform code...")
    generator.generate_terraform()

    print("🎨 Generating draw.io architecture diagram...")
    generator.generate_drawio()

    print("\n🎉 Done! Check the 'output/' folder and 'architecture.drawio'.")


if __name__ == "__main__":
    main()
