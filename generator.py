import os
import re
import json
import uuid
import xml.etree.ElementTree as ET
from xml.dom import minidom
from jinja2 import Environment


def _id(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_]', '_', name).lstrip('_') or 'resource'


def _to_hcl(value, indent=4) -> str:
    """Convert a Python value to valid HCL literal syntax."""
    pad = ' ' * indent
    inner = ' ' * (indent + 2)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        if not value:
            return '[]'
        if all(isinstance(v, str) for v in value):
            items = ', '.join(f'"{v}"' for v in value)
            return f'[{items}]'
        items = ',\n'.join(f'{inner}{_to_hcl(v, indent + 2)}' for v in value)
        return f'[\n{items}\n{pad}]'
    if isinstance(value, dict):
        if not value:
            return '{}'
        lines = '\n'.join(f'{inner}{k} = {_to_hcl(v, indent + 2)}' for k, v in value.items())
        return f'{{\n{lines}\n{pad}}}'
    return str(value)


def _banner(title: str, char='=', width=103) -> str:
    pad = (width - len(title) - 2) // 2
    line = char * width
    return f"//{line}\\\\\n//  {' ' * pad}{title}{' ' * pad}  \\\\\n//{line}\\\\"


def _section(title: str) -> str:
    return _banner(title)


# ══════════════════════════════════════════════════════════════════════════════
# ROOT FILES
# ══════════════════════════════════════════════════════════════════════════════

_MAIN_TF = '''\
//====================================================================================\\\\
//                                   Terraform Provider                               \\\\
//====================================================================================\\\\

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      version = ">= 5.0"
    }
  }
}

//====================================================================================\\\\
//                                   Local Variables                                  \\\\
//====================================================================================\\\\

locals {
  vpc_id              = module.vpc.vpc_id
  public_subnets      = module.vpc.public_subnets_ids
  private_app_subnets = module.vpc.private_app_subnets_ids
  private_db_subnets  = module.vpc.private_db_subnets_ids
}

//====================================================================================\\\\
//                                   AWS Provider                                     \\\\
//====================================================================================\\\\

provider "aws" {
  region = var.region
}

//====================================================================================\\\\
//                                   VPC and Related Resources                        \\\\
//====================================================================================\\\\

module "vpc" {
  source      = "./modules/vpc"
  region      = var.region
  environment = var.environment
  vpc_conf    = var.vpc_conf
}
{% if security_groups %}

//====================================================================================\\\\
//                                   Security Groups                                  \\\\
//====================================================================================\\\\
{% for sg in security_groups if sg.name != 'default' %}
module "sg_{{ _id(sg.name) }}" {
  source      = "./modules/security-group"
  environment = var.environment
  sg_conf = {
    name        = "{{ sg.name }}"
    description = "{{ sg.description }}"
    vpc_id      = local.vpc_id
    ingress     = {{ sg.ingress | tohcl }}
  }
}
{% endfor %}
{% endif %}
{% if nat_gateways %}

//====================================================================================\\\\
//                                   NAT Gateways                                     \\\\
//====================================================================================\\\\
{% for nat in nat_gateways %}
module "nat_{{ _id(nat.name) }}" {
  source      = "./modules/nat-gateway"
  environment = var.environment
  nat_conf = {
    name      = "{{ nat.name }}"
    subnet_id = "{{ nat.subnet_id }}"
  }
}
{% endfor %}
{% endif %}
{% if ec2_instances %}

//====================================================================================\\\\
//                                   EC2 Instances                                    \\\\
//====================================================================================\\\\
{% for i in ec2_instances %}
module "ec2_{{ _id(i.name) }}" {
  source      = "./modules/ec2"
  environment = var.environment
  ec2_conf = {
    name               = "{{ i.name }}"
    ami                = "{{ i.ami }}"
    instance_type      = "{{ i.type }}"
    subnet_id          = "{{ i.subnet_id }}"
    key_name           = "{{ i.key_name }}"
    security_group_ids = {{ i.security_group_ids | tohcl }}
  }
}
{% endfor %}
{% endif %}
{% if rds_instances %}

//====================================================================================\\\\
//                                   RDS Instances                                    \\\\
//====================================================================================\\\\
{% for db in rds_instances %}
module "rds_{{ _id(db.id) }}" {
  source      = "./modules/rds"
  environment = var.environment
  rds_conf = {
    identifier         = "{{ db.id }}"
    engine             = "{{ db.engine }}"
    engine_version     = "{{ db.engine_version }}"
    instance_class     = "{{ db.instance_class }}"
    multi_az           = {{ db.multi_az | lower }}
    subnet_group_name  = "{{ db.subnet_group }}"
    subnet_ids         = {{ db.subnet_ids | tohcl }}
    security_group_ids = {{ db.security_group_ids | tohcl }}
    allocated_storage  = {{ db.storage }}
  }
}
{% endfor %}
{% endif %}
{% if load_balancers %}

//====================================================================================\\\\
//                                   Load Balancers                                   \\\\
//====================================================================================\\\\
{% for lb in load_balancers %}
module "alb_{{ _id(lb.name) }}" {
  source      = "./modules/alb"
  environment = var.environment
  alb_conf = {
    name               = "{{ lb.name }}"
    type               = "{{ lb.type }}"
    scheme             = "{{ lb.scheme }}"
    subnet_ids         = {{ lb.subnet_ids | tohcl }}
    security_group_ids = {{ lb.security_group_ids | tohcl }}
    listeners          = {{ lb.listeners | tohcl }}
  }
}
{% endfor %}
{% endif %}
{% if client_vpn_endpoints %}

//====================================================================================\\\\
//                                   Client VPN                                       \\\\
//====================================================================================\\\\
{% for ep in client_vpn_endpoints %}
module "client_vpn_{{ loop.index }}" {
  source      = "./modules/client-vpn"
  environment = var.environment
  vpc_id      = local.vpc_id
  vpc_cidr    = module.vpc.vpc_cidr
  subnet_ids  = toset(local.private_app_subnets)
  vpn_conf = {
    client_cidr_block      = "{{ ep.client_cidr }}"
    vpn_port               = {{ ep.vpn_port }}
    transport_protocol     = "{{ ep.transport_protocol }}"
    split_tunnel           = {{ ep.split_tunnel | lower }}
    server_certificate_arn = "{{ ep.server_certificate_arn }}"
    client_certificate_arn = "{{ ep.server_certificate_arn }}"
    log_enabled            = true
  }
}
{% endfor %}
{% endif %}
{% if eks_clusters %}

//====================================================================================\\\\
//                                   EKS Clusters                                     \\\\
//====================================================================================\\\\
{% for cluster in eks_clusters %}
module "eks_{{ _id(cluster.name) }}" {
  source      = "./modules/eks"
  environment = var.environment
  eks_conf = {
    name                     = "{{ cluster.name }}"
    version                  = "{{ cluster.version }}"
    role_arn                 = "{{ cluster.role_arn }}"
    subnet_ids               = {{ cluster.subnet_ids | tohcl }}
    security_group_ids       = {{ cluster.security_group_ids | tohcl }}
    endpoint_public_access   = {{ cluster.endpoint_public_access | lower }}
    endpoint_private_access  = {{ cluster.endpoint_private_access | lower }}
  }
}
{% endfor %}
{% endif %}
{% if ecs_clusters %}

//====================================================================================\\\\
//                                   ECS Clusters                                     \\\\
//====================================================================================\\\\
{% for cluster in ecs_clusters %}
module "ecs_{{ _id(cluster.name) }}" {
  source      = "./modules/ecs"
  environment = var.environment
  ecs_conf = {
    name     = "{{ cluster.name }}"
    services = {{ cluster.services | tohcl }}
  }
}
{% endfor %}
{% endif %}
{% if s3_buckets %}

//====================================================================================\\\\
//                                   S3 Buckets                                       \\\\
//====================================================================================\\\\
{% for b in s3_buckets %}
module "s3_{{ _id(b.name) }}" {
  source      = "./modules/s3"
  environment = var.environment
  s3_conf = {
    name            = "{{ b.name }}"
    additional_tags = {}
  }
}
{% endfor %}
{% endif %}
'''

_VARIABLES_TF = '''\
//====================================================================================\\\\
//                                    Variables                                       \\\\
//====================================================================================\\\\
#========== Common Variables ==========#

variable "region" {
  description = "AWS region to deploy the resources in"
}

variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

#========== VPC ==========#

variable "vpc_conf" {
  description = "All network related configurations such as: VPC CIDRs, Subnets, Internet Gateway, NAT configurations"
}
'''

_OUTPUTS_TF = '''\
//====================================================================================\\\\
//                                    Outputs                                         \\\\
//====================================================================================\\\\

output "vpc_id" {
  value = local.vpc_id
}

output "public_subnets" {
  value = local.public_subnets
}

output "private_app_subnets" {
  value = local.private_app_subnets
}

output "private_db_subnets" {
  value = local.private_db_subnets
}
{% for ep in client_vpn_endpoints %}
output "client_vpn_endpoint_id_{{ loop.index }}" {
  value = module.client_vpn_{{ loop.index }}.endpoint_id
}
{% endfor %}
{% for lb in load_balancers %}
output "lb_dns_{{ _id(lb.name) }}" {
  value = module.alb_{{ _id(lb.name) }}.dns_name
}
{% endfor %}
'''

_TFVARS = '''\
//========== Common Global Variables ===========//
region      = "{{ region }}"
environment = "{{ env }}"

vpc_conf = {
  vpc = {
    cidr_vpc = "{{ vpc.cidr }}"
    additional_tags = {
      Owner = "{{ env }}"
    }
  }

  nat_gateway = {
    additional_tags = {
      Owner = "{{ env }}"
    }
  }

  subnets = {
    public_subnets = {
      name = "public-subnet"
      cidr = {{ public_cidrs | tohcl }}
      additional_tags = {
        Owner = "{{ env }}"
        Tier  = "public-subnet"
      }
    }

    private_app_subnets = {
      name = "private-app-subnet"
      cidr = {{ private_cidrs | tohcl }}
      additional_tags = {
        Owner = "{{ env }}"
        Tier  = "private-app-subnet"
      }
    }

    private_db_subnets = {
      name = "private-db-subnet"
      cidr = {{ db_cidrs | tohcl }}
      additional_tags = {
        Owner = "{{ env }}"
        Tier  = "private-db-subnet"
      }
    }
  }
}
'''

# ══════════════════════════════════════════════════════════════════════════════
# MODULE: vpc  (copied verbatim from reference, generated dynamically)
# ══════════════════════════════════════════════════════════════════════════════

_MOD_VPC_VARIABLES = '''\
//============= All the variables will be populated by the calling function values =============//

variable "region" {
  description = "AWS region to deploy the resources in"
}

variable "vpc_conf" {
  description = "Network resources related configuration for the creation of VPC, Subnets, Internet Gateway, NAT gateway, Route table etc"
}

variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}
'''

_MOD_VPC_OUTPUTS = '''\
//============= Define and expose values or data produced by the resources using output =============//

output "vpc_id" {
  value = aws_vpc.vpc.id
}

output "vpc_cidr" {
  value = aws_vpc.vpc.cidr_block
}

output "public_subnets" {
  value = aws_subnet.public_subnets[*]
}

output "public_subnets_ids" {
  value = aws_subnet.public_subnets[*].id
}

output "private_app_subnets" {
  value = aws_subnet.private_app_subnets[*]
}

output "private_app_subnets_ids" {
  value = aws_subnet.private_app_subnets[*].id
}

output "private_db_subnets" {
  value = aws_subnet.private_db_subnets[*]
}

output "private_db_subnets_ids" {
  value = aws_subnet.private_db_subnets[*].id
}
'''

_MOD_VPC_VPC_TF = open("/home/sparsh/VPC code module/modules/vpc/vpc.tf").read()
_MOD_VPC_FLOWLOGS_TF = open("/home/sparsh/VPC code module/modules/vpc/vpc_flowlogs.tf").read()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE: nat-gateway  (Fix 1: generates its own EIP, no hardcoded allocation ID)
# ══════════════════════════════════════════════════════════════════════════════

_MOD_NAT_MAIN = '''\
//=======================================================================================================\\\\
//                                           Elastic IP for NAT                                          \\\\
//=======================================================================================================\\\\

resource "aws_eip" "this" {
  domain = "vpc"

  tags = merge(
    {
      Name        = "${var.nat_conf.name}-eip"
      Environment = var.environment
    },
    lookup(var.nat_conf, "additional_tags", {})
  )
}

//=======================================================================================================\\\\
//                                           NAT Gateway                                                 \\\\
//=======================================================================================================\\\\

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.this.id
  subnet_id     = var.nat_conf.subnet_id

  tags = merge(
    {
      Name        = var.nat_conf.name
      Environment = var.environment
    },
    lookup(var.nat_conf, "additional_tags", {})
  )

  depends_on = [aws_eip.this]
}
'''

_MOD_NAT_VARS = '''\
variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

variable "nat_conf" {
  description = "NAT gateway configuration including name and subnet_id"
}
'''

_MOD_NAT_OUTPUTS = '''\
output "id"            { value = aws_nat_gateway.this.id }
output "public_ip"     { value = aws_eip.this.public_ip }
output "allocation_id" { value = aws_eip.this.id }
'''

_MOD_SG_MAIN = '''\
//=======================================================================================================\\\\
//                                           Security Group                                              \\\\
//=======================================================================================================\\\\

resource "aws_security_group" "this" {
  name        = var.sg_conf.name
  description = var.sg_conf.description
  vpc_id      = var.sg_conf.vpc_id

  dynamic "ingress" {
    for_each = var.sg_conf.ingress
    content {
      from_port   = ingress.value.from
      to_port     = ingress.value.to
      protocol    = ingress.value.protocol
      cidr_blocks = ingress.value.cidrs
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = var.sg_conf.name
    Environment = var.environment
  }
}
'''

_MOD_SG_VARS = '''\
variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

variable "sg_conf" {
  description = "Security group configuration including name, description, vpc_id and ingress rules"
}
'''

_MOD_SG_OUTPUTS = 'output "id" { value = aws_security_group.this.id }\n'

# ══════════════════════════════════════════════════════════════════════════════
# MODULE: ec2
# ══════════════════════════════════════════════════════════════════════════════

_MOD_EC2_MAIN = '''\
//=======================================================================================================\\\\
//                                           EC2 Instance                                                \\\\
//=======================================================================================================\\\\

resource "aws_instance" "this" {
  ami                    = var.ec2_conf.ami
  instance_type          = var.ec2_conf.instance_type
  subnet_id              = var.ec2_conf.subnet_id
  key_name               = var.ec2_conf.key_name
  vpc_security_group_ids = var.ec2_conf.security_group_ids

  tags = merge(
    {
      Name        = var.ec2_conf.name
      Environment = var.environment
    },
    lookup(var.ec2_conf, "additional_tags", {})
  )
}
'''

_MOD_EC2_VARS = '''\
variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

variable "ec2_conf" {
  description = "EC2 instance configuration including ami, instance_type, subnet_id, key_name, security_group_ids"
}
'''

_MOD_EC2_OUTPUTS = '''\
output "id"         { value = aws_instance.this.id }
output "private_ip" { value = aws_instance.this.private_ip }
'''

# ══════════════════════════════════════════════════════════════════════════════
# MODULE: rds
# ══════════════════════════════════════════════════════════════════════════════

_MOD_RDS_MAIN = '''\
//=======================================================================================================\\\\
//                                           RDS Subnet Group                                            \\\\
//=======================================================================================================\\\\

resource "aws_db_subnet_group" "this" {
  name       = var.rds_conf.subnet_group_name
  subnet_ids = var.rds_conf.subnet_ids

  tags = merge(
    {
      Name        = var.rds_conf.subnet_group_name
      Environment = var.environment
    },
    lookup(var.rds_conf, "additional_tags", {})
  )
}

//=======================================================================================================\\\\
//                                           RDS Instance                                                \\\\
//=======================================================================================================\\\\

resource "aws_db_instance" "this" {
  identifier             = var.rds_conf.identifier
  engine                 = var.rds_conf.engine
  engine_version         = var.rds_conf.engine_version
  instance_class         = var.rds_conf.instance_class
  multi_az               = var.rds_conf.multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.rds_conf.security_group_ids
  allocated_storage      = var.rds_conf.allocated_storage
  skip_final_snapshot    = true

  tags = merge(
    {
      Name        = var.rds_conf.identifier
      Environment = var.environment
    },
    lookup(var.rds_conf, "additional_tags", {})
  )

  depends_on = [aws_db_subnet_group.this]
}
'''

_MOD_RDS_VARS = '''\
variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

variable "rds_conf" {
  description = "RDS instance configuration"
}
'''

_MOD_RDS_OUTPUTS = 'output "endpoint" { value = aws_db_instance.this.endpoint }\n'

# ══════════════════════════════════════════════════════════════════════════════
# MODULE: alb
# ══════════════════════════════════════════════════════════════════════════════

_MOD_ALB_MAIN = '''\
//=======================================================================================================\\\\
//                                           Load Balancer                                               \\\\
//=======================================================================================================\\\\

resource "aws_lb" "this" {
  name               = var.alb_conf.name
  load_balancer_type = var.alb_conf.type
  internal           = var.alb_conf.scheme == "internal"
  subnets            = var.alb_conf.subnet_ids
  security_groups    = var.alb_conf.security_group_ids

  tags = merge(
    {
      Name        = var.alb_conf.name
      Environment = var.environment
    },
    lookup(var.alb_conf, "additional_tags", {})
  )
}

//=======================================================================================================\\\\
//                                           Listeners                                                   \\\\
//=======================================================================================================\\\\

resource "aws_lb_listener" "this" {
  count             = length(var.alb_conf.listeners)
  load_balancer_arn = aws_lb.this.arn
  port              = var.alb_conf.listeners[count.index].port
  protocol          = var.alb_conf.listeners[count.index].protocol

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "OK"
      status_code  = "200"
    }
  }
}
'''

_MOD_ALB_VARS = '''\
variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

variable "alb_conf" {
  description = "Load balancer configuration including name, type, scheme, subnet_ids, security_group_ids"
}
'''

_MOD_ALB_OUTPUTS = '''\
output "arn"      { value = aws_lb.this.arn }
output "dns_name" { value = aws_lb.this.dns_name }
'''

_MOD_EKS_MAIN = '''\
//=======================================================================================================\\\\
//                                           EKS Cluster                                                 \\\\
//=======================================================================================================\\\\

resource "aws_eks_cluster" "this" {
  name     = var.eks_conf.name
  version  = var.eks_conf.version
  role_arn = var.eks_conf.role_arn

  vpc_config {
    subnet_ids              = var.eks_conf.subnet_ids
    security_group_ids      = var.eks_conf.security_group_ids
    endpoint_public_access  = var.eks_conf.endpoint_public_access
    endpoint_private_access = var.eks_conf.endpoint_private_access
  }

  tags = merge(
    {
      Name        = var.eks_conf.name
      Environment = var.environment
    },
    lookup(var.eks_conf, "additional_tags", {})
  )
}
'''

_MOD_EKS_VARS = '''\
variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

variable "eks_conf" {
  description = "EKS cluster configuration including name, version, role_arn, subnet_ids, security_group_ids"
}
'''

_MOD_EKS_OUTPUTS = '''\
output "id"       { value = aws_eks_cluster.this.id }
output "endpoint" { value = aws_eks_cluster.this.endpoint }
output "ca_data"  { value = aws_eks_cluster.this.certificate_authority[0].data }
'''

# ══════════════════════════════════════════════════════════════════════════════
# MODULE: ecs
# ══════════════════════════════════════════════════════════════════════════════

_MOD_ECS_MAIN = '''\
//=======================================================================================================\\\\
//                                           ECS Cluster                                                 \\\\
//=======================================================================================================\\\\

resource "aws_ecs_cluster" "this" {
  name = var.ecs_conf.name

  tags = merge(
    {
      Name        = var.ecs_conf.name
      Environment = var.environment
    },
    lookup(var.ecs_conf, "additional_tags", {})
  )
}

//=======================================================================================================\\\\
//                                           ECS Services                                                \\\\
//=======================================================================================================\\\\

resource "aws_ecs_service" "this" {
  count           = length(var.ecs_conf.services)
  name            = var.ecs_conf.services[count.index].name
  cluster         = aws_ecs_cluster.this.id
  task_definition = var.ecs_conf.services[count.index].task_definition
  desired_count   = var.ecs_conf.services[count.index].desired_count
  launch_type     = var.ecs_conf.services[count.index].launch_type

  network_configuration {
    subnets          = var.ecs_conf.services[count.index].subnet_ids
    security_groups  = var.ecs_conf.services[count.index].security_group_ids
    assign_public_ip = var.ecs_conf.services[count.index].assign_public_ip == "ENABLED"
  }

  depends_on = [aws_ecs_cluster.this]
}
'''

_MOD_ECS_VARS = '''\
variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

variable "ecs_conf" {
  description = "ECS cluster configuration including name and list of services"
}
'''

_MOD_ECS_OUTPUTS = '''\
output "id"   { value = aws_ecs_cluster.this.id }
output "name" { value = aws_ecs_cluster.this.name }
'''

# ══════════════════════════════════════════════════════════════════════════════
# MODULE: s3
# ══════════════════════════════════════════════════════════════════════════════

_MOD_S3_MAIN = '''\
//=======================================================================================================\\\\
//                                           S3 Bucket                                                   \\\\
//=======================================================================================================\\\\

resource "aws_s3_bucket" "this" {
  bucket = var.s3_conf.name

  tags = merge(
    {
      Name        = var.s3_conf.name
      Environment = var.environment
    },
    lookup(var.s3_conf, "additional_tags", {})
  )
}

//=======================================================================================================\\\\
//                                           S3 Public Access Block                                      \\\\
//=======================================================================================================\\\\

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
'''

_MOD_S3_VARS = '''\
variable "environment" {
  description = "Environment tag to be used. Ex: dev/qa/production"
}

variable "s3_conf" {
  description = "S3 bucket configuration including name and additional_tags"
}
'''

_MOD_S3_OUTPUTS = '''\
output "id"  { value = aws_s3_bucket.this.id }
output "arn" { value = aws_s3_bucket.this.arn }
'''

# ══════════════════════════════════════════════════════════════════════════════
# MODULE registry
# ══════════════════════════════════════════════════════════════════════════════

def _client_vpn_module():
    base = "/home/sparsh/terraform-client-vpn/modules/client-vpn"
    result = {}
    for fname in ("main.tf", "variables.tf", "outputs.tf"):
        with open(f"{base}/{fname}") as f:
            result[fname] = f.read()
    return result


MODULES = {
    "vpc": {
        "vpc.tf": _MOD_VPC_VPC_TF,
        "vpc_flowlogs.tf": _MOD_VPC_FLOWLOGS_TF,
        "variables.tf": _MOD_VPC_VARIABLES,
        "outputs.tf": _MOD_VPC_OUTPUTS,
    },
    "nat-gateway":    {"main.tf": _MOD_NAT_MAIN,  "variables.tf": _MOD_NAT_VARS,  "outputs.tf": _MOD_NAT_OUTPUTS},
    "security-group": {"main.tf": _MOD_SG_MAIN,   "variables.tf": _MOD_SG_VARS,   "outputs.tf": _MOD_SG_OUTPUTS},
    "ec2":            {"main.tf": _MOD_EC2_MAIN,   "variables.tf": _MOD_EC2_VARS,  "outputs.tf": _MOD_EC2_OUTPUTS},
    "rds":            {"main.tf": _MOD_RDS_MAIN,   "variables.tf": _MOD_RDS_VARS,  "outputs.tf": _MOD_RDS_OUTPUTS},
    "alb":            {"main.tf": _MOD_ALB_MAIN,   "variables.tf": _MOD_ALB_VARS,  "outputs.tf": _MOD_ALB_OUTPUTS},
    "eks":            {"main.tf": _MOD_EKS_MAIN,   "variables.tf": _MOD_EKS_VARS,  "outputs.tf": _MOD_EKS_OUTPUTS},
    "ecs":            {"main.tf": _MOD_ECS_MAIN,   "variables.tf": _MOD_ECS_VARS,  "outputs.tf": _MOD_ECS_OUTPUTS},
    "s3":             {"main.tf": _MOD_S3_MAIN,    "variables.tf": _MOD_S3_VARS,   "outputs.tf": _MOD_S3_OUTPUTS},
}


# ══════════════════════════════════════════════════════════════════════════════
# InfraGenerator
# ══════════════════════════════════════════════════════════════════════════════

class InfraGenerator:
    def __init__(self, region: str, env: str, data: dict):
        self.region = region
        self.env = env
        self.data = data
        self._jenv = Environment()
        self._jenv.filters['tohcl'] = _to_hcl
        self._jenv.filters['tojson'] = json.dumps
        self._jenv.filters['lower'] = lambda v: str(v).lower()
        self._jenv.globals['_id'] = _id

    def _render(self, tmpl: str, **extra) -> str:
        return self._jenv.from_string(tmpl).render(
            region=self.region, env=self.env, **self.data, **extra
        )

    # ── Terraform ─────────────────────────────────────────────────────────────
    def generate_terraform(self, output_dir="output"):
        os.makedirs(output_dir, exist_ok=True)

        # Bucket subnet CIDRs by tier for tfvars
        pub, priv, db = [], [], []
        for s in self.data['subnets']:
            {'public': pub, 'private': priv, 'db': db}[s['tier']].append(s['cidr'])

        root_files = {
            "main.tf":      _MAIN_TF,
            "variables.tf": _VARIABLES_TF,
            "outputs.tf":   _OUTPUTS_TF,
        }
        for fname, tmpl in root_files.items():
            with open(f"{output_dir}/{fname}", "w") as f:
                f.write(self._render(tmpl).strip() + "\n")

        with open(f"{output_dir}/examples.tfvars", "w") as f:
            f.write(self._render(_TFVARS, public_cidrs=pub, private_cidrs=priv, db_cidrs=db).strip() + "\n")

        # Modules
        all_modules = dict(MODULES)
        if self.data.get('client_vpn_endpoints'):
            all_modules['client-vpn'] = _client_vpn_module()

        for mod_name, mod_files in all_modules.items():
            mod_dir = f"{output_dir}/modules/{mod_name}"
            os.makedirs(mod_dir, exist_ok=True)
            for fname, content in mod_files.items():
                with open(f"{mod_dir}/{fname}", "w") as f:
                    f.write(content)

        print(f"✓ Modular Terraform written to {output_dir}/")

    # ── Draw.io XML Diagram ───────────────────────────────────────────────────
    def generate_drawio(self, output_filename="architecture.drawio"):
        d = self.data
        vpc = d['vpc']

        # Bucket subnets by tier and AZ
        tiers = {'public': [], 'private': [], 'db': []}
        for s in d['subnets']:
            tiers[s['tier']].append(s)
        az_list = sorted({s['az'] for s in d['subnets']})

        cells = []   # list of dicts
        edges = []
        _cid = [20]

        def nid():
            _cid[0] += 1
            return str(_cid[0])

        # ── style helpers ─────────────────────────────────────────────────────

        def _group_style(gr_icon, stroke, fill, font_color, dashed="0", sw="2"):
            return (
                f"points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],"
                f"[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];"
                f"outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=13;fontStyle=1;"
                f"container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
                f"shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr_icon};grStroke=0;"
                f"strokeColor={stroke};fillColor={fill};verticalAlign=top;align=left;"
                f"spacingLeft=32;fontColor={font_color};dashed={dashed};strokeWidth={sw};"
            )

        def _icon_style(res_icon, fill, gradient="none"):
            return (
                f"sketch=0;points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],"
                f"[0,1,0],[0.25,1,0],[0.5,1,0],[0.75,1,0],[1,1,0],"
                f"[0,0.25,0],[0,0.5,0],[0,0.75,0],[1,0.25,0],[1,0.5,0],[1,0.75,0]];"
                f"outlineConnect=0;fontColor=#232F3E;gradientColor={gradient};"
                f"gradientDirection=north;fillColor={fill};strokeColor=#ffffff;dashed=0;"
                f"verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
                f"fontSize=11;fontStyle=0;aspect=fixed;"
                f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res_icon};"
            )

        def _special_style(shape):
            return (
                f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;"
                f"fillColor=#8C4FFF;strokeColor=none;dashed=0;"
                f"verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
                f"fontSize=11;fontStyle=0;aspect=fixed;pointerEvents=1;"
                f"shape=mxgraph.aws4.{shape};"
            )

        def add_cell(id_, style, value, x, y, w, h, parent="1", vertex=True):
            cells.append({"id": id_, "style": style, "value": value,
                          "x": x, "y": y, "w": w, "h": h,
                          "parent": parent, "vertex": vertex})

        def add_edge(src, tgt):
            if src and tgt:
                eid = nid()
                edges.append({"id": eid, "src": src, "tgt": tgt})

        # ── Layout constants ──────────────────────────────────────────────────
        ICON_W, ICON_H = 78, 78
        ICON_LABEL_H   = 20          # space below icon for label
        ICON_TOTAL_H   = ICON_H + ICON_LABEL_H

        # Subnet box: holds icons in a row
        SUB_PAD_TOP  = 50            # space for subnet label
        SUB_PAD_SIDE = 20
        SUB_ICON_GAP = 15
        # We'll compute subnet width dynamically based on icon count

        # How many icons per subnet (worst case 1 for sizing)
        def icons_in_subnet(sub_id, tier):
            if tier == 'private':
                ec2s  = [i for i in d['ec2_instances']  if i['subnet_id'] == sub_id]
                ekss  = [c for c in d['eks_clusters']   if sub_id in c['subnet_ids']]
                ecss  = [c for c in d['ecs_clusters']
                         if sub_id in [s2 for sv in c['services'] for s2 in sv['subnet_ids']]]
                return max(1, len(ec2s) + len(ekss) + len(ecss))
            elif tier == 'db':
                rdss = [db for db in d['rds_instances'] if sub_id in db.get('subnet_ids', [])]
                return max(1, len(rdss))
            return 1  # public: NAT or ALB placed separately

        def subnet_w(n_icons):
            return SUB_PAD_SIDE * 2 + n_icons * ICON_W + max(0, n_icons - 1) * SUB_ICON_GAP

        def subnet_h():
            return SUB_PAD_TOP + ICON_TOTAL_H + SUB_PAD_SIDE

        # Column widths: max subnet width across all AZs per tier
        def max_sub_w(tier):
            subs = tiers[tier]
            if not subs:
                return subnet_w(1)
            return max(subnet_w(icons_in_subnet(s['id'], tier)) for s in subs)

        COL_W = {t: max_sub_w(t) + 30 for t in ('public', 'private', 'db')}
        SUB_H = subnet_h()

        # AZ row height: subnet + padding
        AZ_PAD_TOP  = 40
        AZ_PAD_BOT  = 20
        AZ_H = AZ_PAD_TOP + SUB_H + AZ_PAD_BOT
        AZ_GAP = 15

        # Column X positions (relative to VPC interior)
        VPC_PAD_LEFT  = 160   # room for IGW/VPN on the left
        VPC_PAD_RIGHT = 40
        VPC_PAD_TOP   = 50
        VPC_PAD_BOT   = 40

        COL_X = {
            'public':  VPC_PAD_LEFT,
            'private': VPC_PAD_LEFT + COL_W['public'],
            'db':      VPC_PAD_LEFT + COL_W['public'] + COL_W['private'],
        }

        VPC_W = VPC_PAD_LEFT + COL_W['public'] + COL_W['private'] + COL_W['db'] + VPC_PAD_RIGHT
        VPC_H = VPC_PAD_TOP + len(az_list) * AZ_H + max(0, len(az_list) - 1) * AZ_GAP + VPC_PAD_BOT

        # Absolute positions
        VPC_X, VPC_Y = 900, 700

        CLOUD_PAD = 120
        CLOUD_X = VPC_X - CLOUD_PAD - 80
        CLOUD_Y = VPC_Y - CLOUD_PAD - 160
        CLOUD_W = VPC_W + CLOUD_PAD * 2 + 80
        CLOUD_H = VPC_H + CLOUD_PAD * 2 + 200

        # ── AWS Cloud ─────────────────────────────────────────────────────────
        cloud_id = nid()
        add_cell(cloud_id,
            "outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=14;fontStyle=1;"
            "container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
            "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;grStroke=0;"
            "strokeColor=#232F3E;fillColor=none;verticalAlign=top;align=left;"
            "spacingLeft=32;fontColor=#232F3E;dashed=0;strokeWidth=3;",
            f"<b>AWS Cloud</b>",
            CLOUD_X, CLOUD_Y, CLOUD_W, CLOUD_H)

        # ── Region ────────────────────────────────────────────────────────────
        region_id = nid()
        add_cell(region_id,
            "outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=13;fontStyle=1;"
            "container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
            "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;grStroke=0;"
            "strokeColor=#147EBA;fillColor=none;verticalAlign=top;align=left;"
            "spacingLeft=32;fontColor=#147EBA;dashed=1;strokeWidth=2;",
            f"<b>Region: {self.region}</b>",
            CLOUD_X + 60, CLOUD_Y + 80, CLOUD_W - 120, CLOUD_H - 140,
            parent=cloud_id)

        # ── VPC ───────────────────────────────────────────────────────────────
        vpc_cell_id = nid()
        add_cell(vpc_cell_id,
            _group_style("group_vpc", "#248814", "none", "#000000", dashed="0", sw="3"),
            f"<b>VPC: {vpc['name']} ({vpc['cidr']})</b>",
            VPC_X, VPC_Y, VPC_W, VPC_H,
            parent=region_id)

        # ── IGW (left of VPC, absolute coords) ───────────────────────────────
        igw_node_id = None
        if d['internet_gateways']:
            igw = d['internet_gateways'][0]
            igw_node_id = nid()
            igw_x = VPC_X - 130
            igw_y = VPC_Y + VPC_H // 2 - ICON_H // 2
            add_cell(igw_node_id, _special_style("internet_gateway"),
                     f"<b>{igw['name']}</b>",
                     igw_x, igw_y, ICON_W, ICON_H, parent=region_id)

        # ── Client VPN (below IGW) ────────────────────────────────────────────
        vpn_node_ids = []
        for i, ep in enumerate(d['client_vpn_endpoints']):
            vpn_id = nid()
            vpn_node_ids.append(vpn_id)
            add_cell(vpn_id, _special_style("client_vpn"),
                     f"<b>{ep['name']}</b>",
                     VPC_X - 130,
                     VPC_Y + VPC_H // 2 + ICON_H + 40 + i * (ICON_TOTAL_H + 10),
                     ICON_W, ICON_H, parent=region_id)

        # ── S3 (top-right, outside VPC) ───────────────────────────────────────
        s3_node_ids = []
        for i, b in enumerate(d['s3_buckets']):
            s3_id = nid()
            s3_node_ids.append(s3_id)
            add_cell(s3_id, _icon_style("s3", "#277116", "#60A337"),
                     f"<b>{b['name']}</b>",
                     VPC_X + VPC_W + 60 + i * (ICON_W + 20),
                     VPC_Y + 20,
                     ICON_W, ICON_H, parent=region_id)

        # ── AZ rows + subnets + icons ─────────────────────────────────────────
        ec2_node_ids  = []
        rds_node_ids  = []
        eks_node_ids  = []
        ecs_node_ids  = []
        nat_node_ids  = []
        alb_node_ids  = []

        for az_idx, az in enumerate(az_list):
            az_abs_y = VPC_Y + VPC_PAD_TOP + az_idx * (AZ_H + AZ_GAP)
            az_abs_x = VPC_X + VPC_PAD_LEFT - 10

            # AZ group (absolute, inside region)
            az_id = nid()
            az_w = COL_W['public'] + COL_W['private'] + COL_W['db'] + 20
            add_cell(az_id,
                "sketch=0;outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
                "fontSize=12;fontStyle=1;container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
                "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_availability_zone;grStroke=0;"
                "strokeColor=#545B64;fillColor=none;verticalAlign=top;align=left;"
                "spacingLeft=32;fontColor=#545B64;dashed=1;strokeWidth=2;",
                f"<b>{az}</b>",
                az_abs_x, az_abs_y, az_w, AZ_H,
                parent=region_id)

            sub_y_in_az = AZ_PAD_TOP   # y inside AZ cell

            # ── Public subnets ────────────────────────────────────────────────
            pub_subs_az = [s for s in tiers['public'] if s['az'] == az]
            for si, sub in enumerate(pub_subs_az):
                sub_x = COL_X['public'] - (VPC_PAD_LEFT - 10) + si * (max_sub_w('public') + 10)
                sub_id = nid()
                sw = max_sub_w('public')
                add_cell(sub_id,
                    _group_style("group_security_group", "#248814", "#CCFFCC", "#248814"),
                    f"<b>{sub['name']}</b><br/>{sub['cidr']}",
                    sub_x, sub_y_in_az, sw, SUB_H,
                    parent=az_id)

                # NAT GW inside first public subnet of first AZ
                if az_idx == 0 and si == 0 and d['nat_gateways']:
                    nat = d['nat_gateways'][0]
                    nat_id = nid()
                    nat_node_ids.append(nat_id)
                    add_cell(nat_id, _special_style("nat_gateway"),
                             f"<b>{nat['name']}</b>",
                             (sw - ICON_W) // 2, SUB_PAD_TOP + 5,
                             ICON_W, ICON_H, parent=sub_id)

                # ALB inside second public subnet of first AZ (or same if only one)
                if az_idx == 0 and d['load_balancers']:
                    if si == min(1, len(pub_subs_az) - 1):
                        lb = d['load_balancers'][0]
                        alb_id = nid()
                        alb_node_ids.append(alb_id)
                        add_cell(alb_id, _special_style("application_load_balancer"),
                                 f"<b>{lb['name']}</b>",
                                 (sw - ICON_W) // 2, SUB_PAD_TOP + 5,
                                 ICON_W, ICON_H, parent=sub_id)

            # ── Private app subnets ───────────────────────────────────────────
            priv_subs_az = [s for s in tiers['private'] if s['az'] == az]
            for si, sub in enumerate(priv_subs_az):
                sub_x = COL_X['private'] - (VPC_PAD_LEFT - 10) + si * (max_sub_w('private') + 10)
                sw = max_sub_w('private')
                sub_id = nid()
                add_cell(sub_id,
                    _group_style("group_security_group", "#147EBA", "#E6F6F7", "#147EBA"),
                    f"<b>{sub['name']}</b><br/>{sub['cidr']}",
                    sub_x, sub_y_in_az, sw, SUB_H,
                    parent=az_id)

                icon_x = SUB_PAD_SIDE
                # EC2
                for inst in [i for i in d['ec2_instances'] if i['subnet_id'] == sub['id']]:
                    ec2_id = nid()
                    ec2_node_ids.append(ec2_id)
                    add_cell(ec2_id, _icon_style("ec2", "#ED7100"),
                             f"<b>{inst['name']}</b>",
                             icon_x, SUB_PAD_TOP + 5, ICON_W, ICON_H, parent=sub_id)
                    icon_x += ICON_W + SUB_ICON_GAP
                # EKS
                for cluster in [c for c in d['eks_clusters'] if sub['id'] in c['subnet_ids']]:
                    eks_id = nid()
                    eks_node_ids.append(eks_id)
                    add_cell(eks_id, _icon_style("eks", "#ED7100"),
                             f"<b>{cluster['name']}</b>",
                             icon_x, SUB_PAD_TOP + 5, ICON_W, ICON_H, parent=sub_id)
                    icon_x += ICON_W + SUB_ICON_GAP
                # ECS
                for cluster in d['ecs_clusters']:
                    svc_subs = [s2 for sv in cluster['services'] for s2 in sv['subnet_ids']]
                    if sub['id'] in svc_subs:
                        ecs_id = nid()
                        ecs_node_ids.append(ecs_id)
                        add_cell(ecs_id, _icon_style("ecs", "#ED7100"),
                                 f"<b>{cluster['name']}</b>",
                                 icon_x, SUB_PAD_TOP + 5, ICON_W, ICON_H, parent=sub_id)
                        icon_x += ICON_W + SUB_ICON_GAP

            # ── DB subnets ────────────────────────────────────────────────────
            db_subs_az = [s for s in tiers['db'] if s['az'] == az]
            for si, sub in enumerate(db_subs_az):
                sub_x = COL_X['db'] - (VPC_PAD_LEFT - 10) + si * (max_sub_w('db') + 10)
                sw = max_sub_w('db')
                sub_id = nid()
                add_cell(sub_id,
                    _group_style("group_security_group", "#147EBA", "#CCE5FF", "#147EBA"),
                    f"<b>{sub['name']}</b><br/>{sub['cidr']}",
                    sub_x, sub_y_in_az, sw, SUB_H,
                    parent=az_id)

                icon_x = SUB_PAD_SIDE
                for db in [db for db in d['rds_instances'] if sub['id'] in db.get('subnet_ids', [])]:
                    rds_id = nid()
                    rds_node_ids.append(rds_id)
                    add_cell(rds_id, _icon_style("rds", "#C925D1"),
                             f"<b>{db['id']}</b>",
                             icon_x, SUB_PAD_TOP + 5, ICON_W, ICON_H, parent=sub_id)
                    icon_x += ICON_W + SUB_ICON_GAP

        # ── Edges (all in root parent "1") ────────────────────────────────────
        for alb_id in alb_node_ids:
            add_edge(igw_node_id, alb_id)
        for nat_id in nat_node_ids:
            add_edge(igw_node_id, nat_id)
        for alb_id in alb_node_ids:
            for n in ec2_node_ids + eks_node_ids + ecs_node_ids:
                add_edge(alb_id, n)
        for ec2_id in ec2_node_ids:
            for rds_id in rds_node_ids:
                add_edge(ec2_id, rds_id)
        for vpn_id in vpn_node_ids:
            for ec2_id in ec2_node_ids:
                add_edge(vpn_id, ec2_id)

        # ── Build XML ─────────────────────────────────────────────────────────
        mxfile = ET.Element("mxfile", host="app.diagrams.net")
        diagram = ET.SubElement(mxfile, "diagram",
                                name=f"{vpc['name']}-architecture",
                                id=str(uuid.uuid4())[:16])
        model = ET.SubElement(diagram, "mxGraphModel",
                              dx="1200", dy="800", grid="1", gridSize="10",
                              guides="1", tooltips="1", connect="1", arrows="1",
                              fold="1", page="1", pageScale="1",
                              pageWidth="1654", pageHeight="1169",
                              math="0", shadow="0")
        root_el = ET.SubElement(model, "root")
        ET.SubElement(root_el, "mxCell", id="0")
        ET.SubElement(root_el, "mxCell", id="1", parent="0")

        for c in cells:
            mc = ET.SubElement(root_el, "mxCell",
                               id=c["id"], style=c["style"], value=c["value"],
                               vertex="1", parent=c["parent"])
            ET.SubElement(mc, "mxGeometry",
                          x=str(c["x"]), y=str(c["y"]),
                          width=str(c["w"]), height=str(c["h"]),
                          **{"as": "geometry"})

        for e in edges:
            mc = ET.SubElement(root_el, "mxCell",
                               id=e["id"], value="",
                               style=("edgeStyle=orthogonalEdgeStyle;rounded=0;"
                                      "orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;"),
                               edge="1", source=e["src"], target=e["tgt"], parent="1")
            ET.SubElement(mc, "mxGeometry", relative="1", **{"as": "geometry"})

        xml_str = minidom.parseString(
            ET.tostring(mxfile, encoding="unicode")
        ).toprettyxml(indent="  ")
        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + '\n'.join(xml_str.split('\n')[1:])

        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(xml_str)

        print(f"✓ Draw.io diagram saved as {output_filename}")
