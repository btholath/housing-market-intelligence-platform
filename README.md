# Real-Time Global Housing Market Intelligence Platform

A GenAI-powered real estate analytics solution built on AWS services that provides real-time valuation insights through a RAG (Retrieval-Augmented Generation) system.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Data Sources                                     │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │
│   │  MLS API    │  │ Price Hist  │  │ Property Tax│  │ Economic    │   │
│   │  (Hourly)   │  │ (6-hourly)  │  │  (Daily)    │  │  (Daily)    │   │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘   │
└──────────┼────────────────┼────────────────┼────────────────┼──────────┘
           │                │                │                │
           ▼                ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Amazon AppFlow (Secure Ingestion)                    │
│   • Field-level filtering (excludes PII: owner_name, owner_ssn, etc.)   │
│   • TLS 1.2+ encryption in transit                                       │
│   • Parquet output with date-based partitioning                          │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Amazon S3 (Raw Data)                            │
│   • KMS encryption at rest                                               │
│   • Versioning enabled                                                   │
│   • Lifecycle policies for cost optimization                             │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    AWS Glue ETL (with Job Bookmarks)                     │
│   • Incremental processing (only new/modified records)                   │
│   • Deduplication via SHA256 document IDs                                │
│   • Context enrichment (price history, tax data, economic indicators)    │
│   • Vector embedding generation via Bedrock Titan                        │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
┌───────────────────────────────┐   ┌───────────────────────────────────┐
│   Amazon S3 (Processed Data)  │   │     Amazon OpenSearch Service     │
│   • Parquet format            │   │   • k-NN index (HNSW algorithm)   │
│   • State/city partitioning   │   │   • 1536-dim vectors (Titan)      │
│   • Analytics-ready           │   │   • Filtered semantic search      │
└───────────────────────────────┘   └───────────────────┬───────────────┘
                                                        │
                                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         AWS Lambda (RAG Handler)                         │
│   1. Query → Titan Embedding                                             │
│   2. OpenSearch k-NN Search (with filters)                               │
│   3. Context Assembly                                                    │
│   4. Claude 3 Sonnet Response Generation                                 │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Amazon API Gateway                                │
│   • REST API with IAM authentication                                     │
│   • HTTPS-only with TLS 1.2                                              │
│   • Rate limiting and throttling                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
housing-market-intelligence/
├── cloudformation/                    # Infrastructure as Code
│   ├── main-infrastructure.yaml       # Core: VPC, S3, IAM, KMS, Glue, OpenSearch
│   ├── appflow-data-ingestion.yaml    # AppFlow flows for data sources
│   ├── 01-core-infrastructure.yaml    # Modular: VPC and networking
│   ├── 02-appflow-ingestion.yaml      # Modular: AppFlow configuration
│   ├── 03-glue-etl.yaml               # Modular: Glue jobs and crawlers
│   ├── 04-bedrock-genai.yaml          # Modular: Bedrock configuration
│   ├── 05-api-layer.yaml              # Modular: Lambda and API Gateway
│   └── 06-monitoring.yaml             # Modular: CloudWatch alarms
│
├── src/
│   ├── glue/                          # ETL processing
│   │   ├── housing_etl_job.py         # Main ETL with job bookmarks
│   │   ├── data_quality_check.py      # Data validation
│   │   └── incremental_mls_etl.py     # MLS-specific processing
│   └── lambda/
│       └── rag_query_handler.py       # RAG query Lambda function
│
├── scripts/
│   ├── deploy.py                      # Automated deployment
│   ├── cleanup.py                     # Safe resource cleanup
│   └── cost_estimator.py              # Cost analysis tool
│
├── tests/
│   └── test_platform.py               # Comprehensive test suite
│
└── docs/
    └── Housing_Market_Intelligence_Platform_Guide.docx
```

## Key Features

### Selective Ingestion
- AppFlow field-level mapping excludes PII (owner_name, owner_ssn, etc.)
- Only property attributes ingested: price, sqft, location, amenities

### Incremental Processing
- Glue Job Bookmarks track processed records
- Only new/modified data processed on each run
- 80-95% cost reduction vs. full scans

### Deduplication
- SHA256-based deterministic document IDs
- OpenSearch upserts prevent duplicate vectors
- Clean vector index despite daily price updates

### Security
- KMS encryption at rest (S3, OpenSearch, CloudWatch)
- TLS 1.2+ in transit (AppFlow, API Gateway)
- VPC isolation with private subnets
- IAM least-privilege roles

## Deployment

### Prerequisites
- AWS CLI configured with appropriate permissions
- Python 3.9+
- boto3 library

### Deploy

```bash
# Install dependencies
pip install boto3

# Deploy to development
python scripts/deploy.py --environment dev --action deploy

# Deploy to production
python scripts/deploy.py --environment prod --action deploy
```

### Post-Deployment

```bash
# Configure API credentials
aws secretsmanager put-secret-value \
    --secret-id housing-market-intel-dev/mls-api \
    --secret-string '{"api_key":"your_key","api_secret":"your_secret"}'

# Run initial crawler
aws glue start-crawler --name housing-market-intel-dev-raw-crawler

# Execute first ETL job
aws glue start-job-run --job-name housing-market-intel-dev-housing-etl
```

## Usage

### Query API

```bash
curl -X POST https://{api-id}.execute-api.{region}.amazonaws.com/prod/query \
    -H "Content-Type: application/json" \
    -d '{
        "query": "Find homes in Austin under $500k with 3 bedrooms",
        "filters": {
            "city": "Austin",
            "max_price": 500000,
            "min_bedrooms": 3
        }
    }'
```

### Response Format

```json
{
    "response": "Based on the current listings, I found 5 properties...",
    "sources": [
        {
            "listing_id": "MLS123456",
            "address": "123 Main St, Austin, TX",
            "relevance_score": 0.92
        }
    ],
    "metadata": {
        "query_time_ms": 850,
        "results_found": 5
    }
}
```

## Cost Estimates (Monthly)

| Environment | Estimate |
|------------|----------|
| Development | ~$130-150 |
| Staging | ~$400-450 |
| Production | ~$1,500-2,000 |

**Major cost drivers:**
- Amazon Bedrock (embedding + generation): 40-60%
- Amazon OpenSearch: 20-30%
- AWS Glue ETL: 10-15%

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run integration tests (requires AWS)
SKIP_INTEGRATION=false pytest tests/ -v -m integration
```

## Cleanup

```bash
# Preview (dry run)
python scripts/cleanup.py --environment dev --dry-run

# Execute cleanup
python scripts/cleanup.py --environment dev
```

## Documentation

See `docs/Housing_Market_Intelligence_Platform_Guide.docx` for the complete technical guide covering:

1. Executive Summary
2. Architecture Overview
3. Data Ingestion with AppFlow
4. ETL Processing with Glue Job Bookmarks
5. Vector Database with OpenSearch
6. RAG Implementation with Bedrock
7. Security Implementation
8. Cost Analysis
9. Testing Strategy
10. Deployment Process
11. Cleanup Procedures
12. Key Learnings

## License

Internal use only.
