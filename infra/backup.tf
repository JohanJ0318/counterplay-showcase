# Where Litestream keeps a live copy of the database (deploy/litestream.yml).
# The nightly backup sits on the same disk as the database; this does not.
#
# The bucket holds every account and every team's data, so it is private,
# encrypted, and refuses public access outright.

resource "aws_s3_bucket" "backup" {
  bucket = var.backup_bucket
}

resource "aws_s3_bucket_public_access_block" "backup" {
  bucket                  = aws_s3_bucket.backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# The box's credentials. A user that can touch this one bucket and nothing
# else, so a leaked key on the box exposes the replica and not the account.
# Its access key is made by hand in the console and goes straight onto the
# box (infra/README.md), so the secret never sits in Terraform state.
resource "aws_iam_user" "litestream" {
  name = "counterplay-litestream"
}

resource "aws_iam_user_policy" "litestream" {
  name = "counterplay-litestream"
  user = aws_iam_user.litestream.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = aws_s3_bucket.backup.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.backup.arn}/*"
      },
    ]
  })
}

output "backup_bucket" {
  value = aws_s3_bucket.backup.bucket
}
