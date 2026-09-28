"""
fixtures.py — realistic API payloads for each job board.

Shapes copied from each board's public documentation / observed responses.
These let us exercise the real parsers without hitting the network, which is
what actually breaks: field renames, nested objects, and date formats.
"""

REMOTIVE = {
    "0-legal-notice": "Remotive API legal notice",
    "job-count": 2,
    "jobs": [
        {
            "id": 1908745,
            "url": "https://remotive.com/remote-jobs/software-dev/senior-python-engineer-1908745",
            "title": "Senior Python Engineer",
            "company_name": "Kalepa",
            "category": "Software Development",
            "tags": ["python", "django", "postgresql", "insurance"],
            "job_type": "full_time",
            "publication_date": "2026-09-20T09:12:41",
            "candidate_required_location": "USA, LATAM",
            "salary": "$120,000 - $160,000",
            "description": "<div><p>We're building AI underwriting for commercial "
            "<b>insurance</b>. You'll work on Python and Django services, ETL "
            "pipelines and REST APIs. Fully remote, we hire across LATAM via "
            "an employer of record.</p></div>",
        },
        {
            "id": 1908999,
            "url": "https://remotive.com/remote-jobs/devops/sre-1908999",
            "title": "Site Reliability Engineer",
            "company_name": "ScaleCorp",
            "category": "DevOps",
            "tags": ["kubernetes", "terraform", "go"],
            "job_type": "full_time",
            "publication_date": "2026-09-19T11:00:00",
            "candidate_required_location": "USA Only",
            "salary": "",
            "description": "<p>Kubernetes, Terraform and Golang at scale. "
            "Must be a US citizen. 10+ years experience required.</p>",
        },
    ],
}

# RemoteOK returns a list whose FIRST element is a legal-notice object with no
# "position" key. Parsers that don't skip it produce a junk row.
REMOTEOK = [
    {
        "legal": "RemoteOK API legal notice: to use this data you must link back."
    },
    {
        "slug": "forward-deployed-engineer-sierra",
        "id": "1099234",
        "epoch": 1789862400,
        "date": "2026-09-22T00:00:00+00:00",
        "company": "Sierra",
        "company_logo": "https://remoteok.com/logo.png",
        "position": "Forward Deployed Engineer",
        "tags": ["python", "llm", "agent", "remote"],
        "description": "<p>Deploy conversational <strong>AI agents</strong> into "
        "customer environments. You will own end-to-end delivery. Python, RAG, "
        "multi-agent orchestration. Remote, work from anywhere.</p>",
        "location": "Worldwide",
        "salary_min": 150000,
        "salary_max": 220000,
        "url": "https://remoteok.com/remote-jobs/1099234",
        "apply_url": "https://remoteok.com/l/1099234",
    },
]

ARBEITNOW = {
    "data": [
        {
            "slug": "backend-engineer-python-berlin-123",
            "company_name": "Wefox",
            "title": "Backend Engineer (Python)",
            "description": "<p>Join our <em>insurance</em> platform team. "
            "Django, PostgreSQL, REST APIs, ETL pipelines.</p>",
            "remote": True,
            "url": "https://www.arbeitnow.com/jobs/companies/wefox/backend-engineer-python-123",
            "tags": ["python", "django"],
            "job_types": ["full-time"],
            "location": "Berlin",
            "created_at": 1789862400,
            "visa_sponsorship": True,
        }
    ],
    "links": {"first": "...", "last": None, "prev": None, "next": "..."},
    "meta": {"current_page": 1, "path": "..."},
}

HIMALAYAS = {
    "jobs": [
        {
            "guid": "himalayas-88213",
            "title": "Founding Engineer",
            "companyName": "Federato",
            "description": "<p>Seed stage, small team, wear many hats. Python, "
            "Django, Postgres, Docker. Full ownership from database to nginx. "
            "LLM features on the roadmap. We hire globally as contractors.</p>",
            "pubDate": "2026-09-22T14:00:00Z",
            "applicationLink": "https://himalayas.app/companies/federato/jobs/founding-engineer",
            "locationRestrictions": ["Americas", "Remote"],
            "salary": "$130,000 - $180,000",
        }
    ]
}

# RECORDED FROM THE LIVE ALGOLIA API, 2026-08-10.
# search_by_date + tags=story,author_whoishiring returns newest first.
# The plain /search endpoint returns the MARCH 2020 thread at hits[0], which is
# the bug this fixture exists to lock down.
HN_SEARCH = {
    "hits": [
        {"objectID": "49156683", "title": "Ask HN: Who is hiring? (September 2026)",
         "author": "whoishiring", "created_at": "2026-09-22T15:00:54Z", "num_comments": 321},
        {"objectID": "48747976", "title": "Ask HN: Who is hiring? (August 2026)",
         "author": "whoishiring", "created_at": "2026-08-22T15:01:21Z", "num_comments": 433},
        {"objectID": "48357725", "title": "Ask HN: Who is hiring? (July 2026)",
         "author": "whoishiring", "created_at": "2026-07-22T15:00:48Z", "num_comments": 495},
    ],
    "nbHits": 185,
}

# What the OLD (broken) call returned live — relevance-ranked, six years stale.
HN_SEARCH_RELEVANCE_STALE = {
    "hits": [
        {"objectID": "22665398", "title": "Ask HN: Who is hiring right now?",
         "created_at": "2020-03-23T16:13:49Z"},
        {"objectID": "12846216", "title": "Ask HN: Who is hiring? (November 2016)",
         "created_at": "2016-11-01T15:04:46Z"},
    ]
}

HN_ITEM = {
    "id": 44120000,
    "children": [
        {
            "id": 44120555,
            "created_at": "2026-09-20T13:02:11.000Z",
            "text": "Sixfold | Solutions Engineer | Remote (Americas) | "
            "FULL-TIME<p>We build AI for insurance underwriting. Python, "
            "Django, RAG pipelines. We hire contractors internationally "
            "through Deel. Reply with your GitHub.</p>",
        },
        {"id": 44120556, "created_at": "2026-09-20T13:05:00.000Z", "text": "too short"},
    ],
}

# RECORDED FROM THE LIVE GREENHOUSE API, 2026-08-10 (boards/anthropic/jobs).
# Critical: the LIST endpoint returns NO `content` field, even with
# ?content=true. Descriptions require a separate per-job call. Scoring on the
# list alone means scoring on the title only.
GREENHOUSE = {
    "jobs": [
        {
            "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/4461450008",
            "data_compliance": [{"type": "gdpr", "requires_consent": False}],
            "internal_job_id": 4147866008,
            "location": {"name": "Remote - Americas"},
            "metadata": [
                {"id": 4036944008, "name": "Location Type",
                 "value": "Remote", "value_type": "single_select"}
            ],
            "id": 4461450008,
            "updated_at": "2026-09-22T18:22:04-04:00",
            "requisition_id": "3356",
            "title": "Forward Deployed Engineer",
            "company_name": "Anthropic",
            "first_published": "2026-04-07T16:10:24-04:00",
            "language": "en",
            "application_deadline": None,
        },
        {
            "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/9999",
            "internal_job_id": 9999,
            "location": {"name": "San Francisco, CA"},
            "metadata": [],
            "id": 9999,
            "updated_at": "2026-09-19T10:00:00-04:00",
            "title": "Office Manager",
            "company_name": "Anthropic",
            "first_published": "2026-07-01T10:00:00-04:00",
        },
    ]
}

# Per-job detail. Content is TRIPLE-encoded in the live API: the JSON carries
# &lt;div which decodes to &lt;div which decodes to <div. strip_html
# unescapes twice, which is why that fix matters.
GREENHOUSE_DETAIL = {
    "id": 4461450008,
    "title": "Forward Deployed Engineer",
    "company_name": "Anthropic",
    "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/4461450008",
    "location": {"name": "Remote - Americas"},
    "updated_at": "2026-09-22T18:22:04-04:00",
    "content": "&lt;div class=&quot;content-intro&quot;&gt;&lt;p&gt;Work directly "
    "with enterprise customers deploying LLM systems into production. You will "
    "write Python, build RAG and agentic workflows, and own end-to-end "
    "delivery.&lt;/p&gt;&lt;/div&gt;&lt;ul&gt;&lt;li&gt;5+ years of engineering "
    "experience&lt;/li&gt;&lt;li&gt;Comfortable with data pipelines and REST "
    "APIs&lt;/li&gt;&lt;/ul&gt;&lt;p&gt;&lt;strong&gt;Visa sponsorship:&lt;/strong&gt; "
    "We do sponsor visas!&lt;/p&gt;",
}

# Lever returns createdAt as epoch MILLISECONDS, not seconds.
LEVER = [
    {
        "id": "abc-123-def",
        "text": "Solutions Architect, Insurance",
        "categories": {
            "location": "Remote - US",
            "commitment": "Full-time",
            "team": "Field Engineering",
        },
        "descriptionPlain": "Deploy our platform into insurance carriers. "
        "Python, SQL, ETL, claims data models.",
        "lists": [
            {
                "text": "Requirements",
                "content": "<li>5+ years engineering</li><li>Insurance domain a plus</li>",
            }
        ],
        "hostedUrl": "https://jobs.lever.co/palantir/abc-123-def",
        "createdAt": 1789862400000,  # 2026-08-07 in MILLISECONDS
    },
    {
        "id": "stale-999",
        "text": "Solutions Engineer, Legacy",
        "categories": {"location": "Remote", "commitment": "Full-time"},
        "descriptionPlain": "Python, Django, ETL, insurance claims platform. "
        "Remote and we hire contractors globally.",
        "lists": [],
        "hostedUrl": "https://jobs.lever.co/palantir/stale-999",
        # A year old. Scores well on keywords but must be filtered by age.
        "createdAt": 1754524800000,  # 2025-08-07
    },
]

ASHBY = {
    "jobs": [
        {
            "id": "ash-789",
            "title": "Applied AI Engineer",
            "location": "Remote",
            "isRemote": True,
            "descriptionHtml": "<p>Build and ship LLM agent systems. Python, "
            "RAG, evals and observability. We care about eval design.</p>",
            "jobUrl": "https://jobs.ashbyhq.com/baseten/ash-789",
            "publishedAt": "2026-09-20T10:00:00.000Z",
            "organizationName": "Baseten",
            "compensation": {"compensationTierSummary": "$180K - $240K"},
        }
    ]
}


ROUTES = {
    "remotive.com/api/remote-jobs": REMOTIVE,
    "greenhouse.io/v1/boards/anthropic/jobs/": GREENHOUSE_DETAIL,
    "remoteok.com/api": REMOTEOK,
    "arbeitnow.com/api/job-board-api": ARBEITNOW,
    "himalayas.app/jobs/api": HIMALAYAS,
    "hn.algolia.com/api/v1/search_by_date": HN_SEARCH,
    "hn.algolia.com/api/v1/search": HN_SEARCH_RELEVANCE_STALE,
    "hn.algolia.com/api/v1/items": HN_ITEM,
    "boards-api.greenhouse.io": GREENHOUSE,
    "api.lever.co": LEVER,
    "api.ashbyhq.com": ASHBY,
}
