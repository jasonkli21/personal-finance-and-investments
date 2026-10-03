#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <region> <App Runner service ARN>" >&2
  exit 64
fi

region="$1"
service_arn="$2"
retention_days=30

if [[ ! "$region" =~ ^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$ ]]; then
  echo "invalid AWS region" >&2
  exit 64
fi
if [[ ! "$service_arn" =~ ^arn:[^:]+:apprunner:${region}:[0-9]{12}:service/[^/]+/[^/]+$ ]]; then
  echo "service ARN must name one App Runner service in the selected region" >&2
  exit 64
fi

service_id="$(aws apprunner describe-service \
  --region "$region" \
  --service-arn "$service_arn" \
  --query 'Service.ServiceId' \
  --output text)"
if [[ -z "$service_id" || "$service_id" == "None" ]]; then
  echo "App Runner did not return a service ID" >&2
  exit 1
fi

for stream in service application; do
  group="/aws/apprunner/$(basename "${service_arn%/*}")/${service_id}/${stream}"
  aws logs put-retention-policy \
    --region "$region" \
    --log-group-name "$group" \
    --retention-in-days "$retention_days"
  actual="$(aws logs describe-log-groups \
    --region "$region" \
    --log-group-name-prefix "$group" \
    --query "logGroups[?logGroupName=='${group}'].retentionInDays | [0]" \
    --output text)"
  if [[ "$actual" != "$retention_days" ]]; then
    echo "retention verification failed for generated App Runner log group" >&2
    exit 1
  fi
done

echo "Verified 30-day retention for the two App Runner log groups."
