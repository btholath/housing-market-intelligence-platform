#!/usr/bin/env python3
"""
Housing Market Intelligence Platform - Cleanup Script
Safely removes all AWS resources created by the platform

Usage:
    python cleanup.py --environment dev
    python cleanup.py --environment prod --force
    python cleanup.py --environment dev --dry-run

Author: Housing Market Intelligence Platform
Version: 1.0.0
"""

import argparse
import boto3
import sys
import time
from typing import List, Dict, Optional
from datetime import datetime


class Colors:
    """ANSI color codes"""
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


class ResourceCleaner:
    """Cleans up AWS resources for the Housing Market Intelligence Platform"""
    
    def __init__(self, environment: str, region: str = 'us-east-1', dry_run: bool = False):
        self.environment = environment
        self.region = region
        self.dry_run = dry_run
        self.project_name = 'housing-market-intel'
        
        # Initialize AWS clients
        self.cfn = boto3.client('cloudformation', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)
        self.s3_resource = boto3.resource('s3', region_name=region)
        self.glue = boto3.client('glue', region_name=region)
        self.opensearch = boto3.client('opensearch', region_name=region)
        self.logs = boto3.client('logs', region_name=region)
        
        # Get account ID
        sts = boto3.client('sts', region_name=region)
        self.account_id = sts.get_caller_identity()['Account']
        
        # Stack names
        self.stack_names = [
            f'{self.project_name}-{environment}-appflow',
            f'{self.project_name}-{environment}-main'
        ]
        
        # Resources to clean
        self.cleanup_summary = {
            'stacks_deleted': [],
            'buckets_emptied': [],
            'log_groups_deleted': [],
            'errors': []
        }
    
    def cleanup(self, force: bool = False):
        """Execute full cleanup"""
        
        print_header("HOUSING MARKET INTELLIGENCE PLATFORM CLEANUP")
        print(f"Environment: {self.environment}")
        print(f"Region: {self.region}")
        print(f"Account: {self.account_id}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"Timestamp: {datetime.utcnow().isoformat()}")
        
        if not force and not self.dry_run:
            print(f"\n{Colors.WARNING}WARNING: This will DELETE all resources in {self.environment}!{Colors.ENDC}")
            print("This includes:")
            print("  - CloudFormation stacks and all resources")
            print("  - S3 buckets and all data")
            print("  - OpenSearch domain and indexes")
            print("  - Glue jobs, databases, and crawlers")
            print("  - CloudWatch log groups")
            
            confirm = input(f"\nType '{self.environment}' to confirm deletion: ")
            if confirm != self.environment:
                print_warning("Cleanup cancelled")
                return
        
        try:
            # Phase 1: List resources to be deleted
            print_header("PHASE 1: Resource Discovery")
            self._discover_resources()
            
            # Phase 2: Empty S3 buckets (required before stack deletion)
            print_header("PHASE 2: Empty S3 Buckets")
            self._empty_s3_buckets()
            
            # Phase 3: Delete Glue resources (may need manual cleanup)
            print_header("PHASE 3: Clean Glue Resources")
            self._cleanup_glue_resources()
            
            # Phase 4: Delete CloudFormation stacks
            print_header("PHASE 4: Delete CloudFormation Stacks")
            self._delete_stacks()
            
            # Phase 5: Cleanup orphaned resources
            print_header("PHASE 5: Cleanup Orphaned Resources")
            self._cleanup_orphaned_resources()
            
            # Print summary
            print_header("CLEANUP SUMMARY")
            self._print_summary()
            
        except Exception as e:
            print_error(f"Cleanup failed: {str(e)}")
            raise
    
    def _discover_resources(self):
        """Discover resources to be cleaned up"""
        
        # Find S3 buckets
        print_info("Discovering S3 buckets...")
        try:
            response = self.s3.list_buckets()
            prefix = f"{self.project_name}-{self.environment}"
            self.buckets_to_delete = [
                b['Name'] for b in response['Buckets']
                if b['Name'].startswith(prefix)
            ]
            print(f"  Found {len(self.buckets_to_delete)} buckets to delete")
            for bucket in self.buckets_to_delete:
                print(f"    - {bucket}")
        except Exception as e:
            print_warning(f"Could not list buckets: {str(e)}")
            self.buckets_to_delete = []
        
        # Find CloudWatch log groups
        print_info("Discovering CloudWatch log groups...")
        try:
            paginator = self.logs.get_paginator('describe_log_groups')
            self.log_groups_to_delete = []
            
            prefixes = [
                f"/aws/glue/{self.project_name}",
                f"/aws/lambda/{self.project_name}",
                f"/aws/opensearch/{self.project_name}"
            ]
            
            for prefix in prefixes:
                for page in paginator.paginate(logGroupNamePrefix=prefix):
                    for lg in page.get('logGroups', []):
                        if self.environment in lg['logGroupName']:
                            self.log_groups_to_delete.append(lg['logGroupName'])
            
            print(f"  Found {len(self.log_groups_to_delete)} log groups to delete")
        except Exception as e:
            print_warning(f"Could not list log groups: {str(e)}")
            self.log_groups_to_delete = []
        
        # Check stack status
        print_info("Checking CloudFormation stacks...")
        for stack_name in self.stack_names:
            try:
                response = self.cfn.describe_stacks(StackName=stack_name)
                status = response['Stacks'][0]['StackStatus']
                print(f"  {stack_name}: {status}")
            except self.cfn.exceptions.ClientError:
                print(f"  {stack_name}: NOT FOUND")
    
    def _empty_s3_buckets(self):
        """Empty S3 buckets to allow deletion"""
        
        for bucket_name in self.buckets_to_delete:
            print_info(f"Emptying bucket: {bucket_name}")
            
            if self.dry_run:
                print(f"  [DRY RUN] Would empty bucket: {bucket_name}")
                continue
            
            try:
                bucket = self.s3_resource.Bucket(bucket_name)
                
                # Delete all object versions
                bucket.object_versions.delete()
                print_success(f"  Emptied bucket: {bucket_name}")
                self.cleanup_summary['buckets_emptied'].append(bucket_name)
                
            except Exception as e:
                error_msg = f"Could not empty bucket {bucket_name}: {str(e)}"
                print_error(f"  {error_msg}")
                self.cleanup_summary['errors'].append(error_msg)
    
    def _cleanup_glue_resources(self):
        """Clean up Glue resources"""
        
        db_name = f"{self.project_name}_{self.environment}_db"
        job_prefix = f"{self.project_name}-{self.environment}"
        
        # Delete Glue jobs
        print_info("Deleting Glue jobs...")
        try:
            response = self.glue.get_jobs()
            for job in response.get('Jobs', []):
                if job['Name'].startswith(job_prefix):
                    if self.dry_run:
                        print(f"  [DRY RUN] Would delete job: {job['Name']}")
                    else:
                        self.glue.delete_job(JobName=job['Name'])
                        print_success(f"  Deleted job: {job['Name']}")
        except Exception as e:
            print_warning(f"Could not clean Glue jobs: {str(e)}")
        
        # Delete Glue crawlers
        print_info("Deleting Glue crawlers...")
        try:
            response = self.glue.get_crawlers()
            for crawler in response.get('Crawlers', []):
                if crawler['Name'].startswith(job_prefix):
                    if self.dry_run:
                        print(f"  [DRY RUN] Would delete crawler: {crawler['Name']}")
                    else:
                        # Stop crawler if running
                        try:
                            self.glue.stop_crawler(Name=crawler['Name'])
                            time.sleep(5)
                        except:
                            pass
                        self.glue.delete_crawler(Name=crawler['Name'])
                        print_success(f"  Deleted crawler: {crawler['Name']}")
        except Exception as e:
            print_warning(f"Could not clean Glue crawlers: {str(e)}")
        
        # Delete Glue database
        print_info(f"Deleting Glue database: {db_name}")
        try:
            if self.dry_run:
                print(f"  [DRY RUN] Would delete database: {db_name}")
            else:
                # First delete all tables
                try:
                    tables = self.glue.get_tables(DatabaseName=db_name)
                    for table in tables.get('TableList', []):
                        self.glue.delete_table(
                            DatabaseName=db_name,
                            Name=table['Name']
                        )
                except:
                    pass
                
                self.glue.delete_database(Name=db_name)
                print_success(f"  Deleted database: {db_name}")
        except self.glue.exceptions.EntityNotFoundException:
            print_info(f"  Database not found: {db_name}")
        except Exception as e:
            print_warning(f"Could not delete database: {str(e)}")
    
    def _delete_stacks(self):
        """Delete CloudFormation stacks"""
        
        for stack_name in self.stack_names:
            print_info(f"Deleting stack: {stack_name}")
            
            if self.dry_run:
                print(f"  [DRY RUN] Would delete stack: {stack_name}")
                continue
            
            try:
                # Check if stack exists
                try:
                    self.cfn.describe_stacks(StackName=stack_name)
                except self.cfn.exceptions.ClientError:
                    print_info(f"  Stack not found: {stack_name}")
                    continue
                
                # Delete stack
                self.cfn.delete_stack(StackName=stack_name)
                
                # Wait for deletion
                print_info(f"  Waiting for stack deletion: {stack_name}")
                waiter = self.cfn.get_waiter('stack_delete_complete')
                waiter.wait(
                    StackName=stack_name,
                    WaiterConfig={'Delay': 30, 'MaxAttempts': 60}
                )
                
                print_success(f"  Deleted stack: {stack_name}")
                self.cleanup_summary['stacks_deleted'].append(stack_name)
                
            except Exception as e:
                error_msg = f"Could not delete stack {stack_name}: {str(e)}"
                print_error(f"  {error_msg}")
                self.cleanup_summary['errors'].append(error_msg)
    
    def _cleanup_orphaned_resources(self):
        """Clean up any orphaned resources"""
        
        # Delete CloudWatch log groups
        print_info("Deleting CloudWatch log groups...")
        for log_group in self.log_groups_to_delete:
            if self.dry_run:
                print(f"  [DRY RUN] Would delete log group: {log_group}")
            else:
                try:
                    self.logs.delete_log_group(logGroupName=log_group)
                    print_success(f"  Deleted log group: {log_group}")
                    self.cleanup_summary['log_groups_deleted'].append(log_group)
                except Exception as e:
                    print_warning(f"  Could not delete log group {log_group}: {str(e)}")
        
        # Delete orphaned S3 buckets (those not deleted by CFN)
        print_info("Cleaning orphaned S3 buckets...")
        for bucket_name in self.buckets_to_delete:
            if self.dry_run:
                print(f"  [DRY RUN] Would delete bucket: {bucket_name}")
            else:
                try:
                    self.s3.delete_bucket(Bucket=bucket_name)
                    print_success(f"  Deleted bucket: {bucket_name}")
                except self.s3.exceptions.NoSuchBucket:
                    print_info(f"  Bucket already deleted: {bucket_name}")
                except Exception as e:
                    print_warning(f"  Could not delete bucket {bucket_name}: {str(e)}")
    
    def _print_summary(self):
        """Print cleanup summary"""
        
        print(f"\n{Colors.BOLD}Cleanup Results:{Colors.ENDC}")
        print("-" * 40)
        
        print(f"\nStacks Deleted ({len(self.cleanup_summary['stacks_deleted'])}):")
        for stack in self.cleanup_summary['stacks_deleted']:
            print(f"  ✓ {stack}")
        
        print(f"\nBuckets Emptied ({len(self.cleanup_summary['buckets_emptied'])}):")
        for bucket in self.cleanup_summary['buckets_emptied']:
            print(f"  ✓ {bucket}")
        
        print(f"\nLog Groups Deleted ({len(self.cleanup_summary['log_groups_deleted'])}):")
        for lg in self.cleanup_summary['log_groups_deleted']:
            print(f"  ✓ {lg}")
        
        if self.cleanup_summary['errors']:
            print(f"\n{Colors.FAIL}Errors ({len(self.cleanup_summary['errors'])}):{Colors.ENDC}")
            for error in self.cleanup_summary['errors']:
                print(f"  ✗ {error}")
        
        if self.dry_run:
            print(f"\n{Colors.WARNING}This was a DRY RUN - no resources were actually deleted{Colors.ENDC}")
        else:
            print(f"\n{Colors.GREEN}Cleanup complete!{Colors.ENDC}")


def main():
    parser = argparse.ArgumentParser(
        description='Housing Market Intelligence Platform Cleanup'
    )
    parser.add_argument(
        '--environment', '-e',
        required=True,
        choices=['dev', 'staging', 'prod'],
        help='Environment to clean up'
    )
    parser.add_argument(
        '--region', '-r',
        default='us-east-1',
        help='AWS region'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Skip confirmation prompt'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    
    args = parser.parse_args()
    
    cleaner = ResourceCleaner(
        environment=args.environment,
        region=args.region,
        dry_run=args.dry_run
    )
    
    cleaner.cleanup(force=args.force)


if __name__ == '__main__':
    main()
