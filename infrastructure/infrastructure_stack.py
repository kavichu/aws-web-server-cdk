import os
from constructs import Construct
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ssm as ssm,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as elbv2_targets,
)


class InfrastructureStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create vpc with public and private subnets
        self.vpc = ec2.Vpc(
            self, "WebApplicationVPC",
            max_azs=3,
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            enable_dns_support=True,
            enable_dns_hostnames=True,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PUBLIC,
                    name="Public",
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name="Private",
                    cidr_mask=24
                ),
            ],
        )

        # Create load balancer security group
        load_balancer_security_group = ec2.SecurityGroup(self, "LoadBalancerSecurityGroup",
            vpc=self.vpc,
            description="Allow access to load balancer",
            allow_all_outbound=True,
            disable_inline_rules=True
        )
        # Add rule to allow connections on ports 80 and 443 from anywhere ipv4
        load_balancer_security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "Allow access to http")
        load_balancer_security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "Allow access to https")

        # Create security group for bastion server
        bastion_server_security_group = ec2.SecurityGroup(self, "BastionServerSecurityGroup",
            vpc=self.vpc,
            description="Allow access to bastion server",
            allow_all_outbound=True,
            disable_inline_rules=True
        )
        # Add rule to allow ssh connection from anywhere ipv4
        bastion_server_security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(22), "Allow access to ssh")

        # Create security group for web server
        web_server_security_group = ec2.SecurityGroup(self, "WebServerSecurityGroup",
            vpc=self.vpc,
            description="Allow access to web server",
            allow_all_outbound=True,
            disable_inline_rules=True
        )

        # Add rule to allow bastion server to connect to port 22 on web server
        web_server_security_group.add_ingress_rule(ec2.Peer.security_group_id(bastion_server_security_group.security_group_id), ec2.Port.tcp(22), "Allow access to ssh")
        
        # Add rules to allow load balancer to connect to ports 80 and 443 on web server
        web_server_security_group.add_ingress_rule(ec2.Peer.security_group_id(load_balancer_security_group.security_group_id), ec2.Port.tcp(80), "Allow access to http")
        web_server_security_group.add_ingress_rule(ec2.Peer.security_group_id(load_balancer_security_group.security_group_id), ec2.Port.tcp(443), "Allow access to https")

        # Web server instance
        web_server_instance = ec2.Instance(self, "WebServerInstance",
            vpc=self.vpc,
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE2, ec2.InstanceSize.SMALL),
            machine_image=ec2.AmazonLinuxImage(generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            key_name=os.environ["WEB_SSH_KEY_NAME"],
            security_group=web_server_security_group,
            user_data=ec2.UserData.custom(open("scripts/setup-server.sh", "r", encoding="utf-8").read()),
        )
        ssm.StringParameter(self, "InstanceWebServerParameter",
            parameter_name="/Instance/WebServer",
            string_value=web_server_instance.instance_private_dns_name
        )

        bastion_server_instance = ec2.Instance(self, "BastionServerInstance",
            vpc=self.vpc,
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE2, ec2.InstanceSize.MICRO),
            machine_image=ec2.AmazonLinuxImage(generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            key_name=os.environ["BASTION_SSH_KEY_NAME"],
            security_group=bastion_server_security_group,
        )

        # Create application load balancer
        load_balancer = elbv2.ApplicationLoadBalancer(self, "LoadBalancer",
            vpc=self.vpc,
            internet_facing=True,
            security_group=load_balancer_security_group,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # Create target group for http
        http_target_group = elbv2.ApplicationTargetGroup(
            self,
            'HttpTargetGroup',
            protocol=elbv2.ApplicationProtocol.HTTP,
            port=80,
            target_type=elbv2.TargetType.INSTANCE,
            vpc=self.vpc,
            health_check=elbv2.HealthCheck(
                healthy_http_codes='200',
                path="/health_check"
            ),
        )
        # Add instance web server to target group on http port
        http_target_group.add_target(elbv2_targets.InstanceTarget(web_server_instance, port=80))

        # Create target group for https
        https_target_group = elbv2.ApplicationTargetGroup(
            self,
            'HttpsTargetGroup',
            protocol=elbv2.ApplicationProtocol.HTTPS,
            port=443,
            target_type=elbv2.TargetType.INSTANCE,
            vpc=self.vpc,
            health_check=elbv2.HealthCheck(
                healthy_http_codes='200',
                path="/health_check"
            ),
        )
        # Add instance web server to target group on https port 
        https_target_group.add_target(elbv2_targets.InstanceTarget(web_server_instance, port=443))

        # Create http listener and add target group for http
        http_listener = load_balancer.add_listener("HttpListener", port=80)
        http_listener.add_target_groups("http", target_groups=[http_target_group])

        # Create https listener and add target group for http
        https_listener = load_balancer.add_listener("HttpsListener", port=443,
                                                    certificates=[elbv2.ListenerCertificate(certificate_arn=os.environ["CERTIFICATE_ARN"])])
        https_listener.add_target_groups("https", target_groups=[https_target_group])

