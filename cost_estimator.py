"""
Housing Market Intelligence Platform - AWS Cost Estimator
Detailed cost breakdown and estimation for all AWS services

Usage:
    python cost_estimator.py --environment dev
    python cost_estimator.py --environment prod --data-volume high

Author: Housing Market Intelligence Platform
Version: 1.0.0
"""

import argparse
from dataclasses import dataclass
from enum import Enum
from typing import Dict


class DataVolume(Enum):
    LOW = "low"  # ~100K records/month
    MEDIUM = "medium"  # ~1M records/month
    HIGH = "high"  # ~10M records/month


@dataclass
class ServiceCost:
    """Represents cost for a single AWS service"""
    service_name: str
    description: str
    hourly_cost: float
    daily_cost: float
    monthly_cost: float
    cost_components: Dict[str, float]
    notes: str = ""


class CostEstimator:
    """
    AWS Cost Estimator for Housing Market Intelligence Platform
    
    Pricing based on us-east-1 region (January 2025)
    Actual costs may vary based on region and usage patterns
    """

    def __init__(self, environment: str, data_volume: DataVolume = DataVolume.MEDIUM):
        self.environment = environment
        self.data_volume = data_volume

        # Environment-specific multipliers
        self.env_multipliers = {
            'dev': 1.0,
            'staging': 1.5,
            'prod': 3.0
        }

        # Data volume configurations
        self.volume_config = {
            DataVolume.LOW: {
                'records_per_month': 100_000,
                'glue_dpu_hours': 10,
                'embedding_requests': 100_000,
                'rag_queries_per_day': 100,
                'storage_gb': 10
            },
            DataVolume.MEDIUM: {
                'records_per_month': 1_000_000,
                'glue_dpu_hours': 50,
                'embedding_requests': 1_000_000,
                'rag_queries_per_day': 1_000,
                'storage_gb': 100
            },
            DataVolume.HIGH: {
                'records_per_month': 10_000_000,
                'glue_dpu_hours': 200,
                'embedding_requests': 10_000_000,
                'rag_queries_per_day': 10_000,
                'storage_gb': 1000
            }
        }

    def calculate_all_costs(self) -> Dict[str, ServiceCost]:
        """Calculate costs for all services"""
        return {
            'vpc': self._calculate_vpc_costs(),
            'nat_gateway': self._calculate_nat_gateway_costs(),
            's3': self._calculate_s3_costs(),
            'kms': self._calculate_kms_costs(),
            'glue': self._calculate_glue_costs(),
            'appflow': self._calculate_appflow_costs(),
            'opensearch': self._calculate_opensearch_costs(),
            'lambda': self._calculate_lambda_costs(),
            'api_gateway': self._calculate_api_gateway_costs(),
            'bedrock': self._calculate_bedrock_costs(),
            'cloudwatch': self._calculate_cloudwatch_costs(),
            'secrets_manager': self._calculate_secrets_manager_costs()
        }

    def _calculate_vpc_costs(self) -> ServiceCost:
        """VPC itself is free, but NAT Gateway is not"""
        return ServiceCost(
            service_name="Amazon VPC",
            description="Virtual Private Cloud networking",
            hourly_cost=0.0,
            daily_cost=0.0,
            monthly_cost=0.0,
            cost_components={
                'vpc': 0.0,
                'subnets': 0.0,
                'route_tables': 0.0,
                'security_groups': 0.0
            },
            notes="VPC, subnets, route tables, and security groups are free"
        )

    def _calculate_nat_gateway_costs(self) -> ServiceCost:
        """NAT Gateway costs - significant cost driver"""
        hourly_rate = 0.045  # $0.045/hour
        data_processed_per_hour_gb = 0.5  # Estimate
        data_rate = 0.045  # $0.045/GB

        hourly = hourly_rate + (data_processed_per_hour_gb * data_rate)
        daily = hourly * 24
        monthly = daily * 30

        multiplier = self.env_multipliers[self.environment]
        if self.environment == 'prod':
            # Production might have 2 NAT gateways for HA
            multiplier = 2.0

        return ServiceCost(
            service_name="NAT Gateway",
            description="Network Address Translation for private subnets",
            hourly_cost=hourly * multiplier,
            daily_cost=daily * multiplier,
            monthly_cost=monthly * multiplier,
            cost_components={
                'hourly_charge': 0.045 * multiplier,
                'data_processing': data_processed_per_hour_gb * data_rate * multiplier
            },
            notes="NAT Gateway is a significant cost; consider NAT instances for dev"
        )

    def _calculate_s3_costs(self) -> ServiceCost:
        """S3 storage and request costs"""
        config = self.volume_config[self.data_volume]
        storage_gb = config['storage_gb']

        # S3 Standard pricing
        storage_cost_per_gb = 0.023  # First 50TB
        put_requests = config['records_per_month'] * 2  # Writes
        get_requests = config['records_per_month'] * 5  # Reads

        put_cost = (put_requests / 1000) * 0.005  # $0.005 per 1000 PUT
        get_cost = (get_requests / 1000) * 0.0004  # $0.0004 per 1000 GET

        monthly = (storage_gb * storage_cost_per_gb) + put_cost + get_cost

        return ServiceCost(
            service_name="Amazon S3",
            description="Object storage for raw and processed data",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'storage': storage_gb * storage_cost_per_gb,
                'put_requests': put_cost,
                'get_requests': get_cost
            },
            notes=f"Based on {storage_gb}GB storage, {put_requests:,} PUT, {get_requests:,} GET requests"
        )

    def _calculate_kms_costs(self) -> ServiceCost:
        """KMS key and request costs"""
        config = self.volume_config[self.data_volume]

        key_cost = 1.0  # $1/month per key
        num_keys = 1

        # Cryptographic requests
        requests = config['records_per_month'] * 3  # encrypt/decrypt operations
        request_cost = (requests / 10000) * 0.03  # $0.03 per 10,000 requests

        monthly = (key_cost * num_keys) + request_cost

        return ServiceCost(
            service_name="AWS KMS",
            description="Key Management Service for encryption",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'key_storage': key_cost * num_keys,
                'requests': request_cost
            },
            notes=f"Based on {requests:,} cryptographic requests/month"
        )

    def _calculate_glue_costs(self) -> ServiceCost:
        """AWS Glue costs for ETL"""
        config = self.volume_config[self.data_volume]

        # Glue ETL job costs
        dpu_hour_cost = 0.44  # $0.44 per DPU-hour
        dpu_hours = config['glue_dpu_hours']

        # Crawler costs
        crawler_dpu_hour_cost = 0.44
        crawler_hours = 2  # Estimate 2 DPU-hours per day for crawlers

        # Data Catalog
        catalog_storage = 0.0  # First 1M objects free

        monthly_etl = dpu_hours * dpu_hour_cost
        monthly_crawler = crawler_hours * 30 * crawler_dpu_hour_cost
        monthly = monthly_etl + monthly_crawler

        return ServiceCost(
            service_name="AWS Glue",
            description="ETL jobs and data catalog",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'etl_jobs': monthly_etl,
                'crawlers': monthly_crawler,
                'data_catalog': catalog_storage
            },
            notes=f"Based on {dpu_hours} DPU-hours/month for ETL"
        )

    def _calculate_appflow_costs(self) -> ServiceCost:
        """Amazon AppFlow costs"""
        config = self.volume_config[self.data_volume]

        # Flow run costs
        flow_run_cost = 0.001  # $0.001 per flow run
        runs_per_month = 30 * 24  # Hourly runs

        # Data processing
        gb_processed = config['storage_gb'] / 10  # Estimate GB per month
        processing_cost = gb_processed * 0.02  # $0.02 per GB

        monthly = (flow_run_cost * runs_per_month) + processing_cost

        return ServiceCost(
            service_name="Amazon AppFlow",
            description="SaaS data integration",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'flow_runs': flow_run_cost * runs_per_month,
                'data_processing': processing_cost
            },
            notes=f"Based on {runs_per_month} flow runs and {gb_processed}GB processed"
        )

    def _calculate_opensearch_costs(self) -> ServiceCost:
        """Amazon OpenSearch costs"""
        # Instance pricing varies by environment
        instance_configs = {
            'dev': {'type': 't3.small.search', 'hourly': 0.036, 'count': 1},
            'staging': {'type': 't3.medium.search', 'hourly': 0.073, 'count': 2},
            'prod': {'type': 'r6g.large.search', 'hourly': 0.167, 'count': 3}
        }

        config = instance_configs[self.environment]

        # Instance costs
        instance_monthly = config['hourly'] * 720 * config['count']

        # EBS storage
        storage_gb = self.volume_config[self.data_volume]['storage_gb']
        ebs_cost = storage_gb * 0.135  # gp3 pricing

        monthly = instance_monthly + ebs_cost

        return ServiceCost(
            service_name="Amazon OpenSearch",
            description="Vector database for semantic search",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'instances': instance_monthly,
                'ebs_storage': ebs_cost
            },
            notes=f"Using {config['count']}x {config['type']} instances"
        )

    def _calculate_lambda_costs(self) -> ServiceCost:
        """AWS Lambda costs"""
        config = self.volume_config[self.data_volume]

        # Lambda pricing
        requests_per_month = config['rag_queries_per_day'] * 30
        avg_duration_ms = 2000  # 2 second average
        memory_mb = 1024

        # Compute cost
        gb_seconds = (requests_per_month * avg_duration_ms / 1000) * (memory_mb / 1024)
        compute_cost = gb_seconds * 0.0000166667

        # Request cost
        request_cost = (requests_per_month / 1_000_000) * 0.20

        monthly = compute_cost + request_cost

        return ServiceCost(
            service_name="AWS Lambda",
            description="Serverless compute for RAG queries",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'compute': compute_cost,
                'requests': request_cost
            },
            notes=f"Based on {requests_per_month:,} requests at {avg_duration_ms}ms average"
        )

    def _calculate_api_gateway_costs(self) -> ServiceCost:
        """API Gateway costs"""
        config = self.volume_config[self.data_volume]

        requests_per_month = config['rag_queries_per_day'] * 30

        # REST API pricing
        api_cost = (requests_per_month / 1_000_000) * 3.50  # $3.50 per million

        return ServiceCost(
            service_name="Amazon API Gateway",
            description="REST API endpoint",
            hourly_cost=api_cost / 720,
            daily_cost=api_cost / 30,
            monthly_cost=api_cost,
            cost_components={
                'api_calls': api_cost
            },
            notes=f"Based on {requests_per_month:,} API calls"
        )

    def _calculate_bedrock_costs(self) -> ServiceCost:
        """Amazon Bedrock costs - SIGNIFICANT cost driver"""
        config = self.volume_config[self.data_volume]

        # Embedding costs (Titan)
        embedding_requests = config['embedding_requests']
        embedding_tokens = embedding_requests * 500  # avg 500 tokens per doc
        embedding_cost = (embedding_tokens / 1000) * 0.0001  # $0.0001 per 1K tokens

        # Claude generation costs
        queries_per_month = config['rag_queries_per_day'] * 30
        input_tokens = queries_per_month * 3000  # context + query
        output_tokens = queries_per_month * 500  # response

        # Claude 3 Sonnet pricing
        input_cost = (input_tokens / 1000) * 0.003  # $3 per 1M input
        output_cost = (output_tokens / 1000) * 0.015  # $15 per 1M output

        monthly = embedding_cost + input_cost + output_cost

        return ServiceCost(
            service_name="Amazon Bedrock",
            description="GenAI embeddings and text generation",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'embeddings': embedding_cost,
                'claude_input': input_cost,
                'claude_output': output_cost
            },
            notes="Bedrock is typically the largest cost component for RAG systems"
        )

    def _calculate_cloudwatch_costs(self) -> ServiceCost:
        """CloudWatch monitoring costs"""
        # Logs
        log_ingestion_gb = 5  # Estimate
        log_storage_gb = 20  # Estimate

        ingestion_cost = log_ingestion_gb * 0.50  # $0.50/GB
        storage_cost = log_storage_gb * 0.03  # $0.03/GB

        # Metrics (custom)
        custom_metrics = 20
        metrics_cost = custom_metrics * 0.30  # $0.30 per metric

        # Alarms
        alarms = 5
        alarm_cost = alarms * 0.10

        monthly = ingestion_cost + storage_cost + metrics_cost + alarm_cost

        return ServiceCost(
            service_name="Amazon CloudWatch",
            description="Monitoring and logging",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'log_ingestion': ingestion_cost,
                'log_storage': storage_cost,
                'metrics': metrics_cost,
                'alarms': alarm_cost
            },
            notes="Costs scale with log volume and retention"
        )

    def _calculate_secrets_manager_costs(self) -> ServiceCost:
        """Secrets Manager costs"""
        num_secrets = 5
        api_calls = 10000  # per month

        secret_cost = num_secrets * 0.40  # $0.40 per secret
        api_cost = (api_calls / 10000) * 0.05

        monthly = secret_cost + api_cost

        return ServiceCost(
            service_name="AWS Secrets Manager",
            description="Secure credential storage",
            hourly_cost=monthly / 720,
            daily_cost=monthly / 30,
            monthly_cost=monthly,
            cost_components={
                'secrets': secret_cost,
                'api_calls': api_cost
            },
            notes=f"Based on {num_secrets} secrets"
        )

    def generate_report(self) -> str:
        """Generate comprehensive cost report"""
        costs = self.calculate_all_costs()

        total_hourly = sum(c.hourly_cost for c in costs.values())
        total_daily = sum(c.daily_cost for c in costs.values())
        total_monthly = sum(c.monthly_cost for c in costs.values())

        report = []
        report.append("=" * 80)
        report.append("HOUSING MARKET INTELLIGENCE PLATFORM - AWS COST ESTIMATE")
        report.append("=" * 80)
        report.append(f"\nEnvironment: {self.environment.upper()}")
        report.append(f"Data Volume: {self.data_volume.value.upper()}")
        report.append(f"Region: us-east-1")
        report.append("")
        report.append("-" * 80)
        report.append(f"{'Service':<25} {'Hourly':>12} {'Daily':>12} {'Monthly':>12}")
        report.append("-" * 80)

        for service_cost in costs.values():
            report.append(
                f"{service_cost.service_name:<25} "
                f"${service_cost.hourly_cost:>10.4f} "
                f"${service_cost.daily_cost:>10.2f} "
                f"${service_cost.monthly_cost:>10.2f}"
            )

        report.append("-" * 80)
        report.append(
            f"{'TOTAL':<25} "
            f"${total_hourly:>10.4f} "
            f"${total_daily:>10.2f} "
            f"${total_monthly:>10.2f}"
        )
        report.append("=" * 80)

        # Cost breakdown by category
        report.append("\n\nCOST BREAKDOWN BY CATEGORY")
        report.append("-" * 40)

        categories = {
            'Compute': ['glue', 'lambda', 'opensearch'],
            'AI/ML': ['bedrock'],
            'Storage': ['s3'],
            'Networking': ['nat_gateway', 'vpc'],
            'Integration': ['appflow', 'api_gateway'],
            'Security': ['kms', 'secrets_manager'],
            'Monitoring': ['cloudwatch']
        }

        for category, services in categories.items():
            category_cost = sum(costs[s].monthly_cost for s in services if s in costs)
            percentage = (category_cost / total_monthly * 100) if total_monthly > 0 else 0
            report.append(f"{category:<20} ${category_cost:>10.2f} ({percentage:>5.1f}%)")

        # Cost optimization recommendations
        report.append("\n\nCOST OPTIMIZATION RECOMMENDATIONS")
        report.append("-" * 40)

        if self.environment == 'dev':
            report.append("• Consider using NAT instances instead of NAT Gateway ($0.04/hr vs $0.045/hr)")
            report.append("• Use t3.small OpenSearch for development")
            report.append("• Reduce Glue DPU hours by optimizing job efficiency")

        if costs['bedrock'].monthly_cost > total_monthly * 0.3:
            report.append("• Bedrock costs are high - consider caching frequent queries")
            report.append("• Evaluate batch processing for embeddings vs real-time")

        if costs['opensearch'].monthly_cost > total_monthly * 0.2:
            report.append("• Consider OpenSearch Serverless for variable workloads")
            report.append("• Optimize index mapping to reduce storage")

        report.append("\n\nNOTES")
        report.append("-" * 40)
        report.append("• Costs are estimates based on January 2025 pricing")
        report.append("• Actual costs may vary based on usage patterns")
        report.append("• Free tier benefits not included in calculations")
        report.append("• Data transfer costs not included (typically < 5% of total)")

        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(description='AWS Cost Estimator')
    parser.add_argument('--environment', '-e', default='dev',
                        choices=['dev', 'staging', 'prod'])
    parser.add_argument('--data-volume', '-d', default='medium',
                        choices=['low', 'medium', 'high'])
    parser.add_argument('--output', '-o', help='Output file path')

    args = parser.parse_args()

    estimator = CostEstimator(
        environment=args.environment,
        data_volume=DataVolume(args.data_volume)
    )

    report = estimator.generate_report()

    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)


if __name__ == '__main__':
    main()
