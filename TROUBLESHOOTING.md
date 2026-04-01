# Troubleshooting

## Daily Log workflow not running on schedule

GitHub's scheduler can lose sync with cron workflows. To fix:

```bash
# 1. Disable and re-enable the workflow
gh workflow disable daily-log.yml
gh workflow enable daily-log.yml

# 2. Push a commit to main (even a no-op change to the workflow file works)
git commit --allow-empty -m "chore: resync workflow schedule"
git push
```

Both steps together force GitHub to re-register the cron schedule.
