#!/usr/bin/env python3
"""
Housing Market Intelligence Platform - Deployment Script
Complete deployment automation for AWS infrastructure

Usage:
    python deploy.py --environment dev --action deploy
    python deploy.py --environment prod --action deploy --skip-confirmation
    python deploy.py --environment dev --action status

Author: Housing Market Intelligence Platform
Version: 1.0.0
"""

import argparse
import boto3
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import subprocess


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(message: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 60}{Colors.ENDC}\n")


def print_success(message: str):
    print(f"{Colors.GREEN}✓ {message}{Colors.ENDC}")


def print_warning(message: str):
    print(f"{Colors.WARNING}⚠ {message}{Colors.ENDC}")


def print_error(message: str):
    print(f"{Colors.FAIL}✗ {message}{Colors.ENDC}")


def print_info(message: str):
    print(f"{Colors.CYAN}ℹ {message}{Colors.ENDC}")


class DeploymentConfig:
    """Deployment configuration management"""
    
    def __init__(self, environment: str, region: str = 'us-east-1'):
        self.environment = environment
        self.region = region
        self.project_name = 'housing-market-intel'
        self.account_id = self._get_account_id()
        
        # Stack names
        self.main_stack_name = f'{self.project_name}-{environment}-main'
        self.appflow_stack_name = f'{self.project_name}-{environment}-appflow'
        
        # S3 paths
        self.artifact_bucket = f'{self.project_name}-{environment}-artifacts-{self.account_id}'
        
        # Local paths
        self.project_root = Path(__file__).parent.parent
        self.cloudformation_dir = self.project_root / 'cloudformation'
        self.src_dir = self.project_root / 'src'
    
    def _get_account_id(self) -> str:
        """Get AWS account ID"""
        sts = boto3.client('sts', region_name=self.region)
        return sts.get_caller_identity()['Account']


class ArtifactBuilder:
    """Build and package deployment artifacts"""
    
    def __init__(self, config: DeploymentConfig):
        self.config = config
        self.build_dir = config.project_root / 'build'
    
    def build_lambda_package(self, function_name: str, source_file: Path) -> Path:
        """Package Lambda function with dependencies"""
        print_info(f"Building Lambda package: {function_name}")
        
        # Create build directory
        lambda_build_dir = self.build_dir / 'lambda' / function_name
        lambda_build_dir.mkdir(parents=True, exist_ok=True)
        
        # Install dependencies
        requirements = [
            'opensearch-py>=2.4.0',
            'requests-aws4auth>=1.2.0',
            'boto3>=1.34.0'
        ]
        
        subprocess.run([
            sys.executable, '-m', 'pip', 'install',
            '--target', str(lambda_build_dir),
            '--quiet'
        ] + requirements, check=True)
        
        # Copy source file
        import shutil
        shutil.copy(source_file, lambda_build_dir / source_file.name)
        
        # Create ZIP
        zip_path = self.build_dir / f'{function_name}.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in lambda_build_dir.rglob('*'):
                if file.is_file():
                    arcname = file.relative_to(lambda_build_dir)
                    zf.write(file, arcname)
        
        print_success(f"Lambda package created: {zip_path}")
        return zip_path
    
    def build_glue_scripts(self) -> Path:
        """Prepare Glue ETL scripts"""
        print_info("Building Glue scripts package")
        
        glue_build_dir = self.build_dir / 'glue'
        glue_build_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy Glue scripts
        glue_src = self.config.src_dir / 'glue'
        if glue_src.exists():
            import shutil
            for script in glue_src.glob('*.py'):
                shutil.copy(script, glue_build_dir / script.name)
        
        print_success(f"Glue scripts prepared: {glue_build_dir}")
        return glue_build_dir
    
    def clean_build(self):
        """Clean build directory"""
        import shutil
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        print_success("Build directory cleaned")


class S3Manager:
    """S3 operations for deployment artifacts"""
    
    def __init__(self, config: DeploymentConfig):
        self.config = config
        self.s3 = boto3.client('s3', region_name=config.region)
    
    def create_artifact_bucket(self):
        """Create S3 bucket for deployment artifacts"""
        bucket_name = self.config.artifact_bucket
        
        try:
            if self.config.region == 'us-east-1':
                self.s3.create_bucket(Bucket=bucket_name)
            else:
                self.s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={
                        'LocationConstraint': self.config.region
                    }
                )
            print_success(f"Created artifact bucket: {bucket_name}")
        except self.s3.exceptions.BucketAlreadyOwnedByYou:
            print_info(f"Artifact bucket already exists: {bucket_name}")
        except Exception as e:
            print_warning(f"Could not create bucket: {str(e)}")
    
    def upload_artifact(self, local_path: Path, s3_key: str) -> str:
        """Upload artifact to S3"""
        bucket = self.config.artifact_bucket
        
        self.s3.upload_file(
            str(local_path),
            bucket,
            s3_key
        )
        
        s3_uri = f"s3://{bucket}/{s3_key}"
        print_success(f"Uploaded: {s3_uri}")
        return s3_uri
    
    def upload_directory(self, local_dir: Path, s3_prefix: str):
        """Upload entire directory to S3"""
        for file_path in local_dir.rglob('*'):
            if file_path.is_file():
                s3_key = f"{s3_prefix}/{file_path.relative_to(local_dir)}"
                self.upload_artifact(file_path, s3_key)


class CloudFormationDeployer:
    """CloudFormation stack deployment"""
    
    def __init__(self, config: DeploymentConfig):
        self.config = config
        self.cfn = boto3.client('cloudformation', region_name=config.region)
    
    def deploy_stack(
        self,
        stack_name: str,
        template_path: Path,
        parameters: Dict[str, str],
        capabilities: List[str] = None
    ) -> bool:
        """Deploy or update CloudFormation stack"""
        
        print_info(f"Deploying stack: {stack_name}")
        
        # Read template
        with open(template_path, 'r') as f:
            template_body = f.read()
        
        # Format parameters
        cfn_parameters = [
            {'ParameterKey': k, 'ParameterValue': v}
            for k, v in parameters.items()
        ]
        
        capabilities = capabilities or ['CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND']
        
        try:
            # Check if stack exists
            try:
                self.cfn.describe_stacks(StackName=stack_name)
                stack_exists = True
            except self.cfn.exceptions.ClientError:
                stack_exists = False
            
            if stack_exists:
                # Update existing stack
                print_info(f"Updating existing stack: {stack_name}")
                self.cfn.update_stack(
                    StackName=stack_name,
                    TemplateBody=template_body,
                    Parameters=cfn_parameters,
                    Capabilities=capabilities
                )
                waiter = self.cfn.get_waiter('stack_update_complete')
            else:
                # Create new stack
                print_info(f"Creating new stack: {stack_name}")
                self.cfn.create_stack(
                    StackName=stack_name,
                    TemplateBody=template_body,
                    Parameters=cfn_parameters,
                    Capabilities=capabilities,
                    OnFailure='ROLLBACK'
                )
                waiter = self.cfn.get_waiter('stack_create_complete')
            
            # Wait for completion
            print_info("Waiting for stack operation to complete...")
            waiter.wait(
                StackName=stack_name,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 60}
            )
            
            print_success(f"Stack {stack_name} deployed successfully")
            return True
            
        except self.cfn.exceptions.ClientError as e:
            error_message = str(e)
            if 'No updates are to be performed' in error_message:
                print_info(f"No updates needed for stack: {stack_name}")
                return True
            else:
                print_error(f"Stack deployment failed: {error_message}")
                return False
    
    def get_stack_outputs(self, stack_name: str) -> Dict[str, str]:
        """Get outputs from deployed stack"""
        try:
            response = self.cfn.describe_stacks(StackName=stack_name)
            outputs = response['Stacks'][0].get('Outputs', [])
            return {o['OutputKey']: o['OutputValue'] for o in outputs}
        except Exception as e:
            print_warning(f"Could not get stack outputs: {str(e)}")
            return {}
    
    def get_stack_status(self, stack_name: str) -> Optional[str]:
        """Get current stack status"""
        try:
            response = self.cfn.describe_stacks(StackName=stack_name)
            return response['Stacks'][0]['StackStatus']
        except self.cfn.exceptions.ClientError:
            return None


class HousingMarketDeployer:
    """Main deployment orchestrator"""
    
    def __init__(self, environment: str, region: str = 'us-east-1'):
        self.config = DeploymentConfig(environment, region)
        self.builder = ArtifactBuilder(self.config)
        self.s3 = S3Manager(self.config)
        self.cfn = CloudFormationDeployer(self.config)
    
    def deploy(self, skip_confirmation: bool = False):
        """Execute full deployment"""
        
        print_header(f"HOUSING MARKET INTELLIGENCE PLATFORM DEPLOYMENT")
        print(f"Environment: {self.config.environment}")
        print(f"Region: {self.config.region}")
        print(f"Account: {self.config.account_id}")
        print(f"Timestamp: {datetime.utcnow().isoformat()}")
        
        if not skip_confirmation:
            confirm = input(f"\nProceed with deployment to {self.config.environment}? (y/N): ")
            if confirm.lower() != 'y':
                print_warning("Deployment cancelled")
                return
        
        try:
            # Phase 1: Build Artifacts
            print_header("PHASE 1: Building Artifacts")
            self.builder.clean_build()
            
            lambda_zip = self.builder.build_lambda_package(
                'rag-query-handler',
                self.config.src_dir / 'lambda' / 'rag_query_handler.py'
            )
            
            glue_dir = self.builder.build_glue_scripts()
            
            # Phase 2: Upload Artifacts
            print_header("PHASE 2: Uploading Artifacts to S3")
            self.s3.create_artifact_bucket()
            
            timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
            
            self.s3.upload_artifact(
                lambda_zip,
                f'lambda/rag_query_handler-{timestamp}.zip'
            )
            
            self.s3.upload_directory(glue_dir, 'glue/scripts')
            
            # Upload CloudFormation templates
            for template in self.config.cloudformation_dir.glob('*.yaml'):
                self.s3.upload_artifact(
                    template,
                    f'cloudformation/{template.name}'
                )
            
            # Phase 3: Deploy Main Infrastructure
            print_header("PHASE 3: Deploying Main Infrastructure")
            
            main_success = self.cfn.deploy_stack(
                stack_name=self.config.main_stack_name,
                template_path=self.config.cloudformation_dir / 'main-infrastructure.yaml',
                parameters={
                    'Environment': self.config.environment,
                    'ProjectName': self.config.project_name
                }
            )
            
            if not main_success:
                print_error("Main infrastructure deployment failed")
                return
            
            # Get outputs for dependent stacks
            main_outputs = self.cfn.get_stack_outputs(self.config.main_stack_name)
            
            # Phase 4: Deploy AppFlow Configuration
            print_header("PHASE 4: Deploying AppFlow Data Ingestion")
            
            appflow_success = self.cfn.deploy_stack(
                stack_name=self.config.appflow_stack_name,
                template_path=self.config.cloudformation_dir / 'appflow-data-ingestion.yaml',
                parameters={
                    'Environment': self.config.environment,
                    'ProjectName': self.config.project_name,
                    'RawDataBucketName': main_outputs.get('RawDataBucketName', ''),
                    'KMSKeyArn': main_outputs.get('KMSKeyArn', '')
                }
            )
            
            # Phase 5: Post-Deployment Configuration
            print_header("PHASE 5: Post-Deployment Configuration")
            
            self._upload_glue_scripts_to_bucket(main_outputs)
            self._upload_lambda_code_to_bucket(main_outputs, lambda_zip)
            
            # Print summary
            print_header("DEPLOYMENT COMPLETE")
            self._print_summary(main_outputs)
            
        except Exception as e:
            print_error(f"Deployment failed: {str(e)}")
            raise
    
    def _upload_glue_scripts_to_bucket(self, outputs: Dict[str, str]):
        """Upload Glue scripts to the scripts bucket"""
        scripts_bucket = outputs.get('ProcessedDataBucketName', '').replace('processed', 'glue-scripts')
        if scripts_bucket:
            glue_dir = self.builder.build_dir / 'glue'
            if glue_dir.exists():
                for script in glue_dir.glob('*.py'):
                    self.s3.s3.upload_file(
                        str(script),
                        scripts_bucket.split('/')[-1] if '/' in scripts_bucket else scripts_bucket,
                        f'scripts/{script.name}'
                    )
                print_success("Glue scripts uploaded to scripts bucket")
    
    def _upload_lambda_code_to_bucket(self, outputs: Dict[str, str], lambda_zip: Path):
        """Upload Lambda code to deployment bucket"""
        scripts_bucket = outputs.get('ProcessedDataBucketName', '').replace('processed', 'glue-scripts')
        if scripts_bucket:
            bucket_name = scripts_bucket.split('/')[-1] if '/' in scripts_bucket else scripts_bucket
            self.s3.s3.upload_file(
                str(lambda_zip),
                bucket_name,
                'lambda/rag_query_handler.zip'
            )
            print_success("Lambda code uploaded")
    
    def _print_summary(self, outputs: Dict[str, str]):
        """Print deployment summary"""
        print(f"\n{Colors.BOLD}Deployment Outputs:{Colors.ENDC}")
        print("-" * 40)
        
        for key, value in outputs.items():
            print(f"  {key}: {value}")
        
        print(f"\n{Colors.BOLD}Next Steps:{Colors.ENDC}")
        print("  1. Configure MLS/Property Tax API credentials in Secrets Manager")
        print("  2. Upload sample data to raw data bucket")
        print("  3. Run initial Glue crawler")
        print("  4. Execute Glue ETL job")
        print("  5. Test API endpoint")
    
    def status(self):
        """Check deployment status"""
        print_header("DEPLOYMENT STATUS")
        
        stacks = [
            self.config.main_stack_name,
            self.config.appflow_stack_name
        ]
        
        for stack_name in stacks:
            status = self.cfn.get_stack_status(stack_name)
            if status:
                color = Colors.GREEN if 'COMPLETE' in status else Colors.WARNING
                print(f"  {stack_name}: {color}{status}{Colors.ENDC}")
            else:
                print(f"  {stack_name}: {Colors.FAIL}NOT DEPLOYED{Colors.ENDC}")


def main():
    parser = argparse.ArgumentParser(
        description='Housing Market Intelligence Platform Deployment'
    )
    parser.add_argument(
        '--environment', '-e',
        required=True,
        choices=['dev', 'staging', 'prod'],
        help='Deployment environment'
    )
    parser.add_argument(
        '--action', '-a',
        default='deploy',
        choices=['deploy', 'status'],
        help='Action to perform'
    )
    parser.add_argument(
        '--region', '-r',
        default='us-east-1',
        help='AWS region'
    )
    parser.add_argument(
        '--skip-confirmation',
        action='store_true',
        help='Skip deployment confirmation'
    )
    
    args = parser.parse_args()
    
    deployer = HousingMarketDeployer(
        environment=args.environment,
        region=args.region
    )
    
    if args.action == 'deploy':
        deployer.deploy(skip_confirmation=args.skip_confirmation)
    elif args.action == 'status':
        deployer.status()


if __name__ == '__main__':
    main()
