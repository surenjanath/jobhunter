# Scheduling scans

The web app itself never schedules scans — a background timer inside Django would fire once per worker process
(gunicorn, docker-compose can run more than one), running duplicate scans against the same job boards. Instead,
schedule `scripts/scan-cron.sh` with the OS's own scheduler. It does what `make scan` does (fetch, score, store —
no Google Sheets write unless `SHEET_ID` is set), plus a lock so an overlapping run is skipped rather than doubled
up, and a log line with a timestamp for each run.

Pick an interval that respects the boards you scan — every 30–60 minutes is plenty; job postings don't change
by the minute, and frequent polling is inconsiderate to the sites being read.

## cron (Linux, or macOS if you prefer it to launchd)

```bash
crontab -e
```
```cron
# JobHunter: scan every 30 minutes
*/30 * * * * /full/path/to/JobHunter/scripts/scan-cron.sh >> /full/path/to/JobHunter/jobhunt/output/scan-cron.log 2>&1
```
Use `make scan-cron` once first to confirm the script runs cleanly before you schedule it.

## launchd (macOS)

Copy `docs/com.jobhunter.scan.plist.example` to `~/Library/LaunchAgents/com.jobhunter.scan.plist`, edit the two
`/full/path/to/JobHunter` placeholders, then:

```bash
launchctl load ~/Library/LaunchAgents/com.jobhunter.scan.plist
launchctl start com.jobhunter.scan     # run once now, to check it works
tail -f jobhunt/output/scan-cron.log
```
`StartInterval` in the plist is in seconds (1800 = 30 minutes). To stop: `launchctl unload ~/Library/LaunchAgents/com.jobhunter.scan.plist`.

## Digest after each scan

Set `SCAN_DIGEST=1` in the repo's `.env` (or export it before the scheduler runs) to have each scan print what's
new and worth your time — it lands in `scan-cron.log` alongside the run.

## Google Sheets sync

Unset by default (`--dry-run`, same as `make scan`). Set `SHEET_ID` in `.env` to have scheduled scans also write
to your configured Google Sheet.

## Windows

There's no worked example here, but the same idea applies: use Task Scheduler to run `scripts/scan-cron.sh`
under WSL or Git Bash on the interval you want. The lock and log behave the same way.
