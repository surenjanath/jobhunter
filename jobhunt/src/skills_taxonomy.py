"""
skills_taxonomy.py — canonical skills with aliases, used to read both resumes and job descriptions.

Matching the SAME taxonomy on both sides is what makes "you have 6 of the 9 skills this job asks for"
meaningful. Each entry: canonical name -> (category, [aliases]). Aliases are matched on word boundaries,
case-insensitively; `#`, `+` and `.` are handled (c#, c++, node.js).

Categories are deliberately broad (not only software) because the Trinidad market is mostly non-tech
and the same resume may target both.
"""

from __future__ import annotations

import re

_T: dict[str, tuple[str, list[str]]] = {}


def _add(category: str, *items: str) -> None:
    """items: 'canonical|alias1|alias2'"""
    for it in items:
        parts = [p.strip() for p in it.split("|") if p.strip()]
        _T[parts[0]] = (category, parts)


_add("Languages",
     "Python|python3", "SQL|t-sql|pl/sql|structured query language", "R|r language", "JavaScript|ecmascript",
     "TypeScript", "Java", "C#|c sharp", "C++|cpp", "Go|golang", "Rust", "PHP", "Ruby", "Scala", "Kotlin", "Swift",
     "Bash|shell scripting|shell script", "VBA|visual basic for applications", "HTML|html5", "CSS|css3|scss|sass")
_add("Web & Backend",
     "Django|django rest framework|drf", "Flask", "FastAPI", "Node.js|nodejs", "Express|express.js",
     "React|reactjs|react.js", "Vue|vue.js|vuejs", "Angular", "Next.js|nextjs", "REST APIs|rest api|restful|rest apis",
     "GraphQL", "Celery", "WebSockets|websocket", "Webhooks|webhook", "Spring Boot", ".NET|dotnet|asp.net",
     "Laravel", "Tailwind|tailwindcss", "Bootstrap")
_add("Data & Databases",
     "PostgreSQL|postgres|psql", "MySQL|mariadb", "SQLite", "MongoDB|mongo", "Redis", "SQL Server|mssql|microsoft sql server",
     "Oracle Database|oracle db", "Supabase", "Elasticsearch|opensearch", "Snowflake", "BigQuery", "Databricks",
     "ETL|elt|data pipelines|data pipeline", "Data Modeling|data modelling|database design|database architecture",
     "Pandas", "NumPy", "SQLAlchemy", "Airflow|apache airflow", "dbt", "Spark|pyspark|apache spark", "Kafka",
     "Data Warehousing|data warehouse", "Data Engineering", "Data Analysis|data analytics", "Web Scraping|scraping|web crawling|beautifulsoup|scrapy|selenium")
_add("AI & ML",
     "LLMs|llm|large language models|large language model", "RAG|retrieval augmented generation|retrieval-augmented generation",
     "Multi-Agent Systems|multi-agent|multi agent|agentic|ai agents|ai agent", "Prompt Engineering|prompt design|prompt engineer",
     "Ollama", "OpenAI API|openai|gpt", "Anthropic|claude", "LangChain", "LlamaIndex", "Embeddings|vector embeddings|embedding",
     "Vector Databases|vector database|pinecone|pgvector|chroma|weaviate|faiss", "Machine Learning|scikit-learn|sklearn",
     "Deep Learning", "PyTorch", "TensorFlow", "NLP|natural language processing", "Computer Vision", "LLM Evaluation|llm evals|evals|llm observability",
     "Fine-tuning|fine tuning|finetuning", "MLOps")
_add("Cloud & DevOps",
     "AWS|amazon web services", "GCP|google cloud", "Azure", "Docker", "Kubernetes|k8s", "Terraform", "CI/CD|cicd|continuous integration",
     "GitHub Actions", "Linux", "nginx", "SSL/TLS|ssl|tls", "DNS", "Vercel", "Git|github|gitlab|version control", "Serverless|lambda",
     "Microsoft Fabric", "Monitoring & Observability|observability|datadog|grafana|prometheus|application monitoring|apm", "Server Administration|sysadmin|server configuration")
_add("Automation & Tools",
     "n8n", "Zapier", "Power Automate", "Excel|microsoft excel|advanced excel", "Power BI|powerbi", "Tableau", "Google Sheets", "Jira",
     "Airtable", "Retool", "Process Automation|workflow automation|automation|rpa", "Microsoft Office|ms office|office 365|powerpoint",
     "Cursor|claude code|ai-assisted development|copilot", "Matplotlib", "Data Visualization|dashboards|dashboard")
_add("Engineering practice",
     "Software Architecture|system design|solution architecture", "API Integration|api integrations|third-party integrations|system integration",
     "Testing|unit testing|pytest|test automation|qa", "Agile|scrum|kanban", "Technical Documentation|documentation",
     "Code Review", "Production Support|on-call|on call|incident response|troubleshooting", "Requirements Gathering|requirements analysis|business analysis",
     "Solutions Engineering|solutions engineer|pre-sales|presales", "Customer Implementation|customer onboarding|client onboarding|implementation engineer", "Legacy Systems|legacy migration|reverse engineering")
_add("Insurance & Finance",
     "Insurance|insurtech|reinsurance", "Claims|claims processing|claims adjudication", "Underwriting", "Actuarial|actuarial science|actuary",
     "Policy Administration|policy management", "Regulatory Reporting|regulatory compliance|regulatory requirements", "Compliance|compliance|grc", "Risk Management",
     "Accounting|bookkeeping|general ledger|accounts payable|accounts receivable", "Financial Reporting|financial analysis|financial statements",
     "Auditing|audit", "Banking|retail banking|commercial banking", "Payroll", "Budgeting|forecasting|fp&a", "Reconciliation|bank reconciliation",
     "Treasury", "Credit Analysis", "Tax|taxation", "IFRS", "QuickBooks|sage|xero|sap", "Fintech|payments")
_add("Business & Operations",
     "Project Management|project manager|pmp|prince2", "Product Management|product manager", "Stakeholder Management|stakeholder",
     "Customer Service|customer support|client service|customer care", "Sales|business development|account management|account executive|sales executive",
     "Marketing|digital marketing|seo|social media|content creation", "Operations Management", "Supply Chain|logistics|procurement|purchasing|inventory",
     "Human Resources|hr|recruitment|talent acquisition", "Training|facilitation|learning and development", "Negotiation",
     "Leadership|team leadership|people management|supervision", "Communication|communication skills", "Management Reporting|management reporting|reporting dashboards",
     "Data Entry", "Administration|administrative|office administration|secretarial", "Quality Assurance|quality control|iso 9001", "Health and Safety|hse|osha")
_add("Engineering & Trades",
     "Mechanical Engineering", "Electrical Engineering", "Civil Engineering", "Chemical Engineering|process engineering",
     "AutoCAD|autocad|cad", "Maintenance|preventive maintenance|plant maintenance", "Instrumentation", "Welding", "HVAC", "Project Engineering")
_add("Healthcare & Education",
     "Nursing|nurse", "Pharmacy|pharmacist", "Laboratory|medical laboratory", "Teaching|lecturing|curriculum", "Research|research methods")
_add("Languages (spoken)", "English", "Spanish|espanol", "French", "Hindi")
_add("Domains",
     "Telecommunications|telecom", "Energy|oil and gas|petroleum|lng|upstream|downstream", "Government|public sector|public service",
     "Healthcare|health care", "Retail", "Hospitality|tourism|hotel", "Manufacturing", "Education", "Non-profit|ngo", "Real Estate",
     "Maritime|shipping|ports")

TAXONOMY: dict[str, tuple[str, list[str]]] = _T

# Soft / universal skills. Postings mention them constantly and resumes rarely list them, so their absence is not a
# gap worth reporting: they get neutral credit instead of counting as "missing".
SOFT = {"Communication", "English", "Leadership", "Negotiation", "Stakeholder Management", "Management Reporting",
        "Research", "Training", "Administration", "Data Entry", "Microsoft Office", "Education", "Quality Assurance",
        "Health and Safety", "Operations Management"}
CATEGORY: dict[str, str] = {k: v[0] for k, v in _T.items()}


def _pattern(alias: str) -> str:
    esc = re.escape(alias.lower()).replace(r"\ ", r"\s+")
    # word boundary that also works next to + # . (c++, c#, node.js)
    return rf"(?<![a-z0-9]){esc}(?![a-z0-9])"


_ALIAS_RE: list[tuple[str, re.Pattern]] = []
for _canon, (_cat, _aliases) in _T.items():
    _ALIAS_RE.append((_canon, re.compile("|".join(_pattern(a) for a in dict.fromkeys(_aliases + [_canon])), re.I)))

_STRICT_CASE = {"Go": r"\bGo\b(?!\s+(?:to|for|get|live|ahead))", "R": r"(?<![A-Za-z])R(?![A-Za-z'\.])(?=[,;)\s]|$)"}


# Speed: scanning ~195 regexes over every text is slow when a job is analysed many times. Each skill gets a cheap
# substring "gate" (the longest word of each alias); the real regex only runs when a gate matches. Results are cached.
from functools import lru_cache

_GATES: dict[str, tuple[str, ...]] = {}
for _canon, (_cat, _aliases) in _T.items():
    _GATES[_canon] = tuple(dict.fromkeys(max(re.split(r"[\s/]+", a.lower()), key=len) for a in dict.fromkeys(_aliases + [_canon])))
_STRICT_RE = {c: re.compile(p) for c, p in _STRICT_CASE.items()}


@lru_cache(maxsize=8192)
def _find(text: str) -> tuple:
    low = text.lower()
    out: dict[str, int] = {}
    for canon, rx in _ALIAS_RE:
        if canon in _STRICT_RE:
            n = len(_STRICT_RE[canon].findall(text))
        else:
            if not any(g in low for g in _GATES[canon]):
                continue
            n = len(rx.findall(text))
        if n:
            out[canon] = n
    return tuple(out.items())


def find_skills(text: str, *, min_count: int = 1) -> dict[str, int]:
    """{canonical skill: mention count} for every taxonomy skill found in `text`."""
    if not text:
        return {}
    return {k: v for k, v in _find(text) if v >= min_count}


def related(skill: str) -> set[str]:
    """Skills that count as partial evidence for `skill` (same family)."""
    fam = {
        "PostgreSQL": {"MySQL", "SQL", "SQLite", "SQL Server", "Oracle Database"},
        "MySQL": {"PostgreSQL", "SQL", "SQLite", "SQL Server"},
        "SQL Server": {"SQL", "PostgreSQL", "MySQL"},
        "Django": {"Flask", "FastAPI", "Python"},
        "Flask": {"Django", "FastAPI", "Python"},
        "FastAPI": {"Django", "Flask", "Python"},
        "React": {"Vue", "Angular", "JavaScript", "TypeScript"},
        "Vue": {"React", "Angular", "JavaScript"},
        "Angular": {"React", "Vue", "TypeScript"},
        "TypeScript": {"JavaScript"},
        "AWS": {"GCP", "Azure"}, "GCP": {"AWS", "Azure"}, "Azure": {"AWS", "GCP"},
        "Kubernetes": {"Docker"}, "Terraform": {"Docker", "AWS", "GCP"},
        "Airflow": {"ETL", "n8n"}, "dbt": {"SQL", "ETL"}, "Spark": {"Pandas", "ETL"},
        "Snowflake": {"PostgreSQL", "SQL", "BigQuery"}, "BigQuery": {"Snowflake", "SQL"},
        "Power BI": {"Tableau", "Data Visualization"}, "Tableau": {"Power BI", "Data Visualization"},
        "LangChain": {"RAG", "LLMs", "LlamaIndex"}, "LlamaIndex": {"RAG", "LLMs", "LangChain"},
        "Vector Databases": {"RAG", "Embeddings", "PostgreSQL"},
        "RAG": {"Embeddings", "Vector Databases", "LLMs", "LangChain", "LlamaIndex"},
        "Embeddings": {"RAG", "Vector Databases"},
        "LLMs": {"RAG", "LangChain", "LlamaIndex", "Prompt Engineering"},
        "Prompt Engineering": {"LLMs", "RAG"},
        "Machine Learning": {"Deep Learning", "NLP", "Pandas"}, "PyTorch": {"TensorFlow", "Deep Learning", "Machine Learning"},
        "TensorFlow": {"PyTorch", "Deep Learning", "Machine Learning"},
        "Java": {"C#", "Kotlin", "Spring Boot"}, "C#": {"Java", ".NET"}, ".NET": {"C#"},
        "Node.js": {"JavaScript", "Express"}, "Zapier": {"n8n", "Process Automation", "Power Automate"},
        "n8n": {"Zapier", "Process Automation", "Power Automate", "ETL"},
        "Accounting": {"Financial Reporting", "Reconciliation", "Auditing"},
        "Financial Reporting": {"Accounting", "Regulatory Reporting"},
        "Customer Service": {"Sales", "Communication"}, "Sales": {"Customer Service", "Business Development"},
        "Project Management": {"Stakeholder Management", "Operations Management"},
        "Insurance": {"Claims", "Underwriting", "Actuarial", "Policy Administration"},
        "Data Analysis": {"Pandas", "SQL", "Excel", "Data Visualization"},
        "Excel": {"Google Sheets", "Data Analysis", "VBA"},
    }
    return fam.get(skill, set())
