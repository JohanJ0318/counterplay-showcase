# The uptime check. monitor/check.py fetches the homepage, the sample report
# and /health every five minutes and publishes how many failed; the alarm
# below turns that into one email when the site goes down and one when it
# comes back.

data "archive_file" "check" {
  type        = "zip"
  source_file = "${path.module}/monitor/check.py"
  output_path = "${path.module}/.build/check.zip"
}

resource "aws_iam_role" "check" {
  name = "counterplay-uptime"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Write its own logs and publish one metric. Nothing else.
resource "aws_iam_role_policy" "check" {
  name = "counterplay-uptime"
  role = aws_iam_role.check.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.check.arn}:*"
      },
      {
        Effect    = "Allow"
        Action    = "cloudwatch:PutMetricData"
        Resource  = "*"
        Condition = { StringEquals = { "cloudwatch:namespace" = "Counterplay" } }
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "check" {
  name              = "/aws/lambda/counterplay-uptime"
  retention_in_days = 14
}

resource "aws_lambda_function" "check" {
  function_name    = "counterplay-uptime"
  role             = aws_iam_role.check.arn
  runtime          = "python3.12"
  handler          = "check.handler"
  filename         = data.archive_file.check.output_path
  source_code_hash = data.archive_file.check.output_base64sha256
  timeout          = 45 # three pages at up to 10 seconds each, plus margin
  memory_size      = 128
  depends_on       = [aws_cloudwatch_log_group.check]
}

resource "aws_cloudwatch_event_rule" "every_5_min" {
  name                = "counterplay-uptime"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "check" {
  rule = aws_cloudwatch_event_rule.every_5_min.name
  arn  = aws_lambda_function.check.arn
}

resource "aws_lambda_permission" "schedule" {
  statement_id  = "every-5-min"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.check.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_5_min.arn
}

resource "aws_sns_topic" "alerts" {
  name = "counterplay-alerts"
}

# AWS emails a confirmation link first. Until it is clicked, no alert arrives.
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Two bad five-minute periods out of three, so a restart during a deploy (a
# few seconds) emails nobody, and neither does one period the schedule's
# jitter left empty. Missing data is a failure: if the function stops running
# or crashes, nothing is published, and that must not read as fine.
resource "aws_cloudwatch_metric_alarm" "down" {
  alarm_name          = "counterplay-down"
  alarm_description   = "counterplaycs.com, the sample report or the worker failed in two of the last three checks. Which one: CloudWatch Logs, /aws/lambda/counterplay-uptime."
  namespace           = "Counterplay"
  metric_name         = "FailedChecks"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
