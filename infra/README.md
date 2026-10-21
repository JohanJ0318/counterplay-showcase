# infra/: uptime monitoring and a live database replica on AWS

The site itself runs on one Linux server. AWS runs two small things beside it,
all defined in Terraform in this folder:

* **An uptime and worker monitor.** A Lambda function (`monitor/check.py`,
  Python 3.12, standard library plus boto3) fetches the homepage, the sample
  report and `/health` every 5 minutes on an EventBridge schedule. `/health`
  answers 503 when the background parse worker has not looped for 30 minutes,
  something no page shows: the worker can die while every page still loads.
  The function publishes one CloudWatch metric, the number of failed checks.
  An alarm on that metric (2 bad periods out of 3, and missing data counts as
  failure, so a broken monitor also alerts) sends one email through SNS when
  the site goes down and one when it recovers.
* **A live copy of the database.** Litestream on the server replicates the
  SQLite database continuously to a private S3 bucket: public access blocked,
  SSE-S3 encryption, bucket-owner-enforced ownership. The nightly backups stay
  as they are.

| file | what it defines |
|---|---|
| `main.tf` | provider, variables, and a $5 AWS Budgets alert (actual and forecast) |
| `monitor.tf` | the Lambda, its IAM role, log group, schedule, alarm and SNS email |
| `backup.tf` | the replica bucket and a one-bucket IAM user for Litestream |
| `monitor/check.py` | the check itself |
| `terraform.tfvars.example` | the two values a deployment supplies |

## Design choices

* **Least privilege.** The Lambda role may write only its own logs and publish
  metrics only to its own namespace. The Litestream user can touch one bucket
  and nothing else, so a leaked key on the server exposes the replica, not the
  account.
* **One email per outage, not one per check.** The metric plus alarm turns a
  two-hour outage into two emails instead of twenty-four.
* **No stored keys on the operator's PC.** Terraform authenticates through the
  AWS CLI's browser sign-in. State and `terraform.tfvars` are gitignored: they
  name the account, the bucket and the alert address.
* **A spending alarm, because AWS has no spending cap.** Everything here fits in
  the free allowances or costs cents a month; the budget email is the safeguard
  if that is ever wrong.

## Using it

```bash
cp terraform.tfvars.example terraform.tfvars   # alert email, bucket name
terraform init
terraform plan
terraform apply
```

AWS emails a confirmation link for the alert subscription; no alert arrives
until it is clicked. `terraform destroy` removes everything and refuses to
delete the bucket while it holds backups.
