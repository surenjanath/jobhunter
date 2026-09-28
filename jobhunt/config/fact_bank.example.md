# Fact Bank — Your Name

This is the **only** source of truth for cover letters. The generator is
instructed to use nothing outside this file. If a claim isn't here, it doesn't
go in a letter. Replace everything below with your own facts (this file is
copied to `config/fact_bank.md`, which is git-ignored, the first time you run
JobHunter).

Write it flat and unembellished. The evidence is good enough on its own;
overselling it is what makes people stop believing the rest.

---

## Ground truth

- 5 years professional experience, 2021 to present, at one company (Example
  Insurance Ltd).
- BSc Computer Science, Example University, 2016 to 2020.
- Based in Trinidad & Tobago, UTC-4. Not authorised to work in the US or EU.
- Learned most of my engineering on the job.

---

## What I have actually built

### Claims triage assistant, Example Insurance, 2025
LLM agents that summarise and route incoming claims, with a deterministic rules
engine holding binding authority over every decision.

- **Status: built and currently in testing. It has not gone to production.**
  Say this plainly. Do not imply it is live.
- What I have not done: no formal eval harness, no tracing, no production
  observability. I know these are gaps.

### Policy administration portal, Example Insurance
- Python/Django application handling 12,000+ policies, with a REST API for
  internal and third-party integrations.
- Live and in production. Replaced an undocumented legacy system, so the core
  logic was reverse-engineered rather than specified.

### Regulatory reporting automation, Example Insurance
- Consolidates data from 6 territories for the regulator's quarterly returns.
  Cut the finance team's reporting time by roughly 70%. That figure is the
  team's own estimate, not a measured benchmark. Say so if pressed.

### Bank reconciliation tool, Example Insurance
- Custom matching algorithm. Removed roughly 60 hours of manual work a month.

### Personal projects (public on GitHub)
- **Price Tracker**: GitHub Actions pipeline scraping a retailer daily into a
  SQL database and committing a refreshed report.
- **Formula Helper**: desktop app running a local LLM through Ollama to turn
  plain English into spreadsheet formulas.

---

## The distinctive things about me

Use one or two of these per letter, not all of them.

1. **I have been the entire engineering function.** Development, deployment,
   server configuration, and production support. When something broke at 11pm
   there was no one else.
2. **I understand insurance from the inside.** Claims, policy administration,
   renewals, reconciliation, and regulatory reporting.
3. **I ship into organisations, not just repos.** Everything above had to be
   adopted by finance teams and agents who did not ask for it.

---

## Honest weaknesses: say these plainly if asked

- **No LLM eval or observability practice yet.**
- **No modern data stack.** No dbt, Airflow or Snowflake; my ETL is Python,
  pandas and GitHub Actions.
- **No frontend framework depth.** Django templates and HTML/CSS only.
- **Never worked on a team of engineers.** No code review culture or shared
  on-call.

---

## Rules for anything written in my voice

1. Never claim a system is in production if it is in testing or pilot.
2. Never inflate a metric or drop a currency.
3. Never claim a technology I haven't used. Name the closest thing I have done.
4. No "passionate", "rockstar", "10x", "obsessed with", "thrilled".
5. Short sentences. Plain words.
6. Lead with the most relevant concrete thing I built, not with adjectives.
7. It is fine, better actually, to name one thing I'd have to learn in the role.
8. Under 300 words. Four paragraphs at most.
