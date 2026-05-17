# InfraLens

InfraLens automatically discovers AWS VPC infrastructure, maps resource relationships, generates production-grade Terraform code, and creates architecture diagrams to simplify cloud migration, documentation, and Infrastructure-as-Code adoption.

---

## Features

- 🔍 Scan AWS VPC infrastructure
- 🏗️ Generate modular production-grade Terraform
- 🎨 Generate Draw.io architecture diagrams
- ☁️ Discover AWS resources automatically
- 📦 Infrastructure reverse engineering
- ⚡ Multi-service AWS support

---

## Supported AWS Resources

- VPCs
- Subnets
- Route Tables
- Internet Gateways
- NAT Gateways
- Security Groups
- EC2 Instances
- RDS Instances
- Load Balancers (ALB/NLB)
- EKS Clusters
- ECS Clusters & Services
- Client VPN Endpoints
- S3 Buckets

---

## Project Structure

```bash
.
├── app.py
├── scanner.py
├── generator.py
├── output/
└── architecture.drawio
```

---

## Prerequisites

- Python 3.10+
- AWS CLI configured
- Terraform installed
- AWS IAM permissions for resource discovery

---

## Installation

```bash
git clone https://github.com/sparsh-comprinno/infralens.git

cd infralens

python3 -m venv venv
source venv/bin/activate

pip install boto3 jinja2
```

---

## Configure AWS Credentials

```bash
aws configure
```

Or use IAM roles/environment variables.

---

## Usage

Run the application:

```bash
python3 app.py
```

Example:

```bash
Enter VPC name: prod-vpc
Enter environment (default: prod): prod
Enter AWS region (default: us-east-1): us-east-1
```

---

## Output

The tool generates:

### Terraform Code

```bash
output/
├── main.tf
├── variables.tf
├── outputs.tf
├── examples.tfvars
└── modules/
```

### Architecture Diagram

```bash
architecture.drawio
```

Import the `.drawio` file into Draw.io / diagrams.net.

---

## Example Workflow

1. Scan an existing AWS VPC
2. Discover connected infrastructure
3. Generate reusable Terraform modules
4. Generate architecture diagrams
5. Reuse generated IaC for migration or standardization

---

## Roadmap

- Terraform import support
- Multi-account scanning
- Drift detection
- CloudFormation export
- Kubernetes manifest generation
- Web UI
- CI/CD integration

---

## License

MIT License

---

## Author

**Sparsh Khandelwal**