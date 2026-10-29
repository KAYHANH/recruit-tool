from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from title_extractor import ROLE_KEYWORDS, extract_job_title

# Comprehensive recruitment stopwords & boilerplate words
RECRUITMENT_STOPWORDS = {
    # Standard English function words
    "a", "about", "above", "across", "after", "again", "against", "all", "almost", "along",
    "also", "although", "always", "am", "among", "an", "and", "another", "any", "are",
    "around", "as", "at", "be", "became", "because", "become", "been", "before", "being",
    "between", "both", "but", "by", "can", "cannot", "could", "did", "do", "does", "doing",
    "down", "during", "each", "either", "else", "etc", "even", "ever", "every", "for",
    "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers",
    "him", "himself", "his", "how", "however", "i", "if", "in", "into", "is", "it",
    "its", "itself", "just", "may", "maybe", "me", "might", "mine", "more", "most",
    "must", "my", "myself", "neither", "no", "nor", "not", "now", "of", "off", "on",
    "once", "one", "only", "onto", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "per", "same", "she", "should", "so", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these",
    "they", "this", "those", "through", "to", "too", "under", "until", "up", "upon",
    "us", "very", "was", "we", "were", "what", "whatever", "when", "where", "which",
    "while", "who", "whom", "whose", "why", "will", "with", "within", "without", "would",
    "you", "your", "yours", "yourself", "yourselves",

    # Recruitment & Job Description boilerplate words
    "ability", "able", "action", "active", "activities", "addition", "additional",
    "advancement", "allowed", "allow", "allows", "analyze", "analyzed", "analyzing",
    "applicant", "applicants", "application", "apply", "applying", "approach",
    "approaches", "appropriate", "approximate", "approximately", "approval", "approvals", "approve",
    "approved", "approving", "assessment", "assessments", "assigned", "assignment",
    "assume", "assumed", "assumption", "assumptions", "asterisk", "attention", "availability", "available", "average",
    "background", "based", "basis", "begins", "benefit", "benefits", "bonus", "brief",
    "briefs", "candidate", "candidates", "career", "careers", "carolina", "check",
    "checked", "clear", "collaborate", "collaborating", "collaboration", "combines",
    "come", "company", "compare", "comparing", "comparison", "compensation",
    "competition", "competitions", "competitive", "complete", "completed", "completing", "completion", "confirm",
    "confirming", "contract", "contracts", "country", "countries", "create", "creates",
    "creating", "creation", "criteria", "criterion", "cross-functional", "build",
    "building", "builds", "dakota", "data", "develop", "developer", "developers", "developing",
    "development", "daily", "date", "dates", "day", "days", "defined", "define",
    "defining", "definition", "definitions", "depending", "description", "detail",
    "details", "distinguish", "distinguishing", "document", "documents", "documentation", "documented", "documenting",
    "duration", "duty", "duties", "early", "earn", "earning", "earnings", "effort",
    "eligible", "eligibility", "employment", "engagement", "ensure", "ensuring",
    "entry", "environment", "equal", "equipment", "error", "errors", "estimate", "estimated", "etc",
    "evaluate", "evaluating", "evaluation", "evaluations", "excellent", "expectation",
    "expectations", "experience", "experienced", "explore", "exploration", "familiar",
    "familiarity", "fast", "feedback", "final", "finding", "findings", "flaw", "flawed", "flaws", "flexibility",
    "flexible", "form", "forms", "fresher", "freshers", "full", "full-time", "future",
    "futurejobs", "futurejobs.ai", "watermark", "watermarks", "general", "geo", "generic", "give", "given", "giving", "goal",
    "goals", "good", "great", "grow", "growth", "guideline", "guidelines", "hampshire",
    "hand", "hands", "help", "helping", "high", "highly", "hire", "hired", "hiring",
    "hour", "hours", "immediate", "immediately", "impact", "implement", "implementing", "implementation", "include", "includes",
    "including", "inclusive", "incomplete", "incorporate", "individual", "individuals", "industry",
    "initiative", "interest", "interested", "internal", "interpret", "interpretation",
    "interview", "interviews", "involving", "island", "jersey", "job", "jobs", "join", "joining", "key", "knowledge",
    "leakage", "level", "levels", "like", "link", "links", "listed", "location", "locations",
    "looking", "maintain", "maintaining", "make", "makes", "making", "manner", "match",
    "matching", "matter", "meet", "meeting", "meets", "member", "members", "method",
    "methods", "minimum", "minute", "minutes", "month", "months", "multiple", "must",
    "needed", "needs", "new", "next", "north", "note", "notes", "notice", "objective",
    "objectives", "offer", "offering", "offers", "onboard", "onboarding", "ongoing",
    "open", "opening", "openings", "opportunity", "opportunities", "option", "options",
    "order", "oriented", "outputs", "overlap", "overview", "paid", "part", "part-time",
    "participant", "participate", "pay", "payment", "payments", "people", "perform",
    "performance", "performing", "period", "perks", "person", "personal", "plausible", "platform", "platforms", "plus", "pluses",
    "point", "points", "position", "positions", "potential", "potentially", "practice",
    "practices", "practitioner", "practitioners", "prefer", "preference", "preferred", "prepare", "present", "presenting",
    "procedure", "procedures", "proceeding", "process", "produce", "producing", "productive",
    "productivity", "professional", "professionals", "proficiency", "proficient", "reproducible", "reasoning",
    "program", "project", "projects", "prospective", "provide", "provided", "providing",
    "qualification", "qualifications", "qualified", "quality", "rate", "rates", "raters",
    "rater", "rating", "ready", "receive", "recruitment", "reference", "references",
    "relevant", "remote", "remotely", "report", "reporting", "required", "requirement",
    "requirements", "response", "responses", "responsibility", "responsibilities",
    "resume", "review", "reviewed", "reviewing", "reward", "rewards", "right", "rights",
    "role", "roles", "schedule", "science", "scope", "seek", "seeking", "select", "selected",
    "selection", "send", "sending", "senior", "service", "services", "session", "sheet",
    "short-term", "shortlist", "shortlisted", "showcase", "showcasing", "similar",
    "skill", "skills", "skilled", "snapshot", "solution", "solutions", "source",
    "south", "standard", "standards", "start", "starting", "state", "states", "status", "strong", "structured", "submit",
    "submitting", "submission", "successful", "suitable", "support", "supporting",
    "talent", "task", "tasks", "team", "teams", "term", "terms", "time", "times",
    "today", "tofu", "topic", "track", "tracking", "training", "understand",
    "understanding", "unit", "units", "upon", "use", "using", "vacancy", "vacancies",
    "value", "values", "variety", "various", "week", "weeks", "weekdays", "weekends",
    "welcome", "willing", "work", "worker", "workers", "working", "workplace", "year",
    "years",
}

# Supported geographical countries, regions, and major cities
KNOWN_COUNTRIES_AND_REGIONS = {
    # Global / Remote
    "global": "Global",
    "worldwide": "Worldwide",
    "international": "International",

    # Countries
    "india": "India",
    "united states": "United States",
    "usa": "United States",
    "us": "United States",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "canada": "Canada",
    "germany": "Germany",
    "france": "France",
    "australia": "Australia",
    "brazil": "Brazil",
    "colombia": "Colombia",
    "philippines": "Philippines",
    "singapore": "Singapore",
    "japan": "Japan",
    "netherlands": "Netherlands",
    "ireland": "Ireland",
    "spain": "Spain",
    "poland": "Poland",
    "mexico": "Mexico",
    "argentina": "Argentina",
    "italy": "Italy",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "denmark": "Denmark",
    "norway": "Norway",
    "finland": "Finland",
    "new zealand": "New Zealand",
    "south africa": "South Africa",
    "nigeria": "Nigeria",
    "kenya": "Kenya",
    "egypt": "Egypt",
    "uae": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
    "dubai": "Dubai",
    "israel": "Israel",
    "pakistan": "Pakistan",
    "bangladesh": "Bangladesh",
    "vietnam": "Vietnam",
    "indonesia": "Indonesia",
    "malaysia": "Malaysia",

    # Major Cities
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "mumbai": "Mumbai",
    "delhi": "Delhi",
    "hyderabad": "Hyderabad",
    "pune": "Pune",
    "chennai": "Chennai",
    "london": "London",
    "new york": "New York",
    "san francisco": "San Francisco",
    "toronto": "Toronto",
    "vancouver": "Vancouver",
    "berlin": "Berlin",
    "paris": "Paris",
    "sydney": "Sydney",
    "melbourne": "Melbourne",
    "sao paulo": "Sao Paulo",
    "bogota": "Bogota",
    "tokyo": "Tokyo",

    # US States & Territories
    "alabama": "Alabama",
    "alaska": "Alaska",
    "arizona": "Arizona",
    "arkansas": "Arkansas",
    "california": "California",
    "colorado": "Colorado",
    "connecticut": "Connecticut",
    "delaware": "Delaware",
    "florida": "Florida",
    "georgia": "Georgia",
    "hawaii": "Hawaii",
    "idaho": "Idaho",
    "illinois": "Illinois",
    "indiana": "Indiana",
    "iowa": "Iowa",
    "kansas": "Kansas",
    "kentucky": "Kentucky",
    "louisiana": "Louisiana",
    "maine": "Maine",
    "maryland": "Maryland",
    "massachusetts": "Massachusetts",
    "michigan": "Michigan",
    "minnesota": "Minnesota",
    "mississippi": "Mississippi",
    "missouri": "Missouri",
    "montana": "Montana",
    "nebraska": "Nebraska",
    "nevada": "Nevada",
    "new hampshire": "New Hampshire",
    "new jersey": "New Jersey",
    "new mexico": "New Mexico",
    "north carolina": "North Carolina",
    "north dakota": "North Dakota",
    "ohio": "Ohio",
    "oklahoma": "Oklahoma",
    "oregon": "Oregon",
    "pennsylvania": "Pennsylvania",
    "rhode island": "Rhode Island",
    "south carolina": "South Carolina",
    "south dakota": "South Dakota",
    "tennessee": "Tennessee",
    "texas": "Texas",
    "utah": "Utah",
    "vermont": "Vermont",
    "virginia": "Virginia",
    "washington": "Washington",
    "west virginia": "West Virginia",
    "wisconsin": "Wisconsin",
    "wyoming": "Wyoming",
    "puerto rico": "Puerto Rico",
}

DISQUALIFIED_LOCATION_WORDS = {
    "are", "is", "were", "was", "approved", "assume", "needed", "details", "must",
    "check", "checked", "confirm", "proceeding", "applicable", "interpretation",
    "eligible", "eligibility", "status", "source", "sheet", "note", "notes", "do",
    "not", "all", "project", "listed", "before", "after", "between", "within", "without"
}

# Domain taxonomies with canonical names and alias variations
KNOWN_SKILLS = {
    # 3D, Creative, Animation, Game Art
    "3d modeling": ["3d modeling", "3d modeler", "3d assets", "3d meshes", "mesh modeling", "3d art"],
    "texturing": ["texturing", "texture painting", "texture mapping", "materials and textures"],
    "lighting": ["lighting", "scene lighting", "3d lighting"],
    "shading": ["shading", "shader", "shaders", "pbr shaders"],
    "rendering": ["rendering", "render engine", "3d rendering", "cycles", "eevee", "arnold"],
    "material creation": ["material creation", "pbr materials", "procedural materials", "material exploration"],
    "uv mapping": ["uv mapping", "uv unwrapping", "uvs"],
    "topology": ["topology", "retopology", "clean topology", "edge flow"],
    "low-poly": ["low-poly", "low poly", "lowpoly", "stylized low-poly"],
    "voxel": ["voxel", "voxels", "voxel art"],
    "asset optimization": ["asset optimization", "game asset optimization", "asset prep"],
    "npr workflows": ["npr workflows", "npr", "non-photorealistic rendering", "stylized rendering"],
    "visual storytelling": ["visual storytelling", "concept art", "visual narrative"],
    "rigging": ["rigging", "character rigging", "skeletal animation"],
    "animation": ["animation", "3d animation", "keyframe animation"],
    "compositing": ["compositing", "vfx compositing"],
    "graphic design": ["graphic design", "visual design"],
    "illustration": ["illustration", "digital illustration", "digital painting"],
    "vector illustration": ["vector illustration", "vector art", "vector graphics", "vectors"],
    "character design": ["character design", "character art", "character concept"],
    "concept art": ["concept art", "visual development", "visdev"],
    "color theory": ["color theory", "color and composition"],

    # Software Engineering / Web / Backend / Fullstack
    "python": ["python", "python3"],
    "javascript": ["javascript", "js", "ecmascript"],
    "typescript": ["typescript", "ts"],
    "react": ["react", "react.js", "reactjs"],
    "node.js": ["node.js", "nodejs", "node"],
    "fastapi": ["fastapi", "fast api"],
    "django": ["django", "django rest framework", "drf"],
    "flask": ["flask"],
    "rest apis": ["rest apis", "rest api", "restful api", "restful apis", "api design"],
    "graphql": ["graphql"],
    "sql": ["sql", "relational databases"],
    "postgresql": ["postgresql", "postgres"],
    "mysql": ["mysql"],
    "sqlite": ["sqlite"],
    "mongodb": ["mongodb", "mongo"],
    "redis": ["redis", "in-memory cache"],
    "docker": ["docker", "containerization", "containers"],
    "kubernetes": ["kubernetes", "k8s"],
    "aws": ["aws", "amazon web services"],
    "azure": ["azure", "microsoft azure"],
    "gcp": ["gcp", "google cloud", "google cloud platform"],
    "ci/cd": ["ci/cd", "continuous integration", "continuous delivery", "github actions", "gitlab ci"],
    "git": ["git", "github", "version control"],
    "linux": ["linux", "unix", "bash"],
    "microservices": ["microservices", "microservice architecture"],
    "test-driven development": ["tdd", "test-driven development", "unit testing", "automated testing"],

    # Data / ML / AI & Competitive Data Science
    "ml engineering": ["ml engineering", "machine learning engineering", "ml engineer"],
    "data science": ["data science", "datascience"],
    "mathematics": ["mathematics", "applied mathematics", "math", "quantitative modeling"],
    "coding": ["coding", "programming", "practical programming"],
    "testing": ["testing", "unit testing", "develop tests", "automated testing"],
    "debugging": ["debugging", "debug", "troubleshooting code"],
    "working with unfamiliar code": ["working with unfamiliar code", "unfamiliar code"],
    "machine learning": ["machine learning", "ml", "predictive modeling"],
    "deep learning": ["deep learning", "neural networks"],
    "data analysis": ["data analysis", "data analytics", "eda", "exploratory data analysis", "analytical skills"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "pytorch": ["pytorch"],
    "tensorflow": ["tensorflow"],
    "natural language processing": ["nlp", "natural language processing"],
    "computer vision": ["computer vision", "opencv"],

    # Business Analysis, Strategy & Project Management
    "business analysis": ["business analysis", "business analyst", "business systems analysis"],
    "requirements gathering": [
        "requirements gathering", "gather business requirements", "gathering requirements",
        "requirements elicitation", "requirements analysis", "business requirements"
    ],
    "process mapping": [
        "process mapping", "process-mapping", "process maps", "business process modeling",
        "bpmn", "workflow analysis", "workflows, processes"
    ],
    "functional specifications": [
        "functional specifications", "functional spec", "functional requirements", "brd", "frd"
    ],
    "user acceptance testing": [
        "user acceptance testing", "uat", "acceptance testing"
    ],
    "stakeholder management": [
        "stakeholder management", "stakeholder collaboration", "stakeholder engagement",
        "collaborate with stakeholders"
    ],
    "gap analysis": ["gap analysis", "identify gaps", "gap assessment"],
    "kpi tracking": ["kpi tracking", "kpis", "key performance indicators"],
    "agile": ["agile", "agile methodologies", "agile methodology"],
    "scrum": ["scrum", "scrum methodology", "sprint planning"],

    # AI Generalist, Evaluation & Digital Operations
    "generalist": ["generalist", "ai generalist", "operations generalist", "digital generalist", "multi-disciplinary", "generalist expert"],
    "chatgpt proficiency": ["chatgpt proficiency", "chatgpt", "chat gpt", "openai", "claude", "prompt engineering", "ai tools", "generative ai", "llm prompting", "large language models"],
    "problem solving": ["problem solving", "problem-solving", "analytical thinking", "critical thinking", "troubleshooting", "solution-oriented", "problem solver"],
    "attention to detail": ["attention to detail", "detail-oriented", "detail oriented", "high accuracy", "meticulous", "quality assurance", "error detection", "accuracy", "rigorous"],
    "communication": ["communication", "written communication", "verbal communication", "interpersonal skills", "clear communication", "reporting", "presentation"],
    "task execution": ["task execution", "task management", "workflow execution", "project execution", "deliverables", "independent work", "operational tasks", "task delivery"],
    "documentation": ["documentation", "technical writing", "documenting", "process documentation", "guidelines", "rubrics", "rubric creation", "knowledge base"],
    "digital literacy": ["digital literacy", "digital tools", "saas tools", "google workspace", "slack", "notion", "productivity tools", "web research"],
    "ai training": ["ai training", "model evaluation", "rlhf", "sft", "human feedback", "data annotation", "data labeling", "prompt evaluation", "model rating", "rater"],
}

KNOWN_TOOLS = {
    # 3D & Digital Art Tools
    "blender": ["blender", "blender 3d"],
    "zbrush": ["zbrush", "pixologic zbrush"],
    "adobe creative suite": ["adobe creative suite", "creative cloud", "adobe cc"],
    "after effects": ["after effects", "adobe after effects"],
    "photoshop": ["photoshop", "adobe photoshop"],
    "illustrator": ["illustrator", "adobe illustrator"],
    "procreate": ["procreate"],
    "substance painter": ["substance painter", "adobe substance 3d painter", "substance 3d"],
    "substance designer": ["substance designer"],
    "3ds max": ["3ds max", "3dsmax", "autodesk 3ds max"],
    "cinema 4d": ["cinema 4d", "c4d", "maxon cinema 4d"],
    "maya": ["maya", "autodesk maya"],
    "houdini": ["houdini", "sidefx houdini"],
    "unity": ["unity", "unity engine", "unity3d"],
    "unreal engine": ["unreal engine", "unreal", "ue4", "ue5"],
    "figma": ["figma"],

    # Software Engineering Tools
    "postman": ["postman"],
    "swagger": ["swagger", "openapi"],
    "jira": ["jira"],
    "confluence": ["confluence"],
    "terraform": ["terraform"],
    "ansible": ["ansible"],
    "jenkins": ["jenkins"],
    "grafana": ["grafana"],
    "prometheus": ["prometheus"],

    # Business Intelligence, Analytics & Productivity Tools
    "excel": ["excel", "ms excel", "microsoft excel", "spreadsheets"],
    "sql": ["sql", "relational databases"],
    "power bi": ["power bi", "powerbi", "microsoft power bi"],
    "tableau": ["tableau", "tableau desktop"],
    "visio": ["visio", "ms visio", "microsoft visio"],
    "lucidchart": ["lucidchart"],
    "google sheets": ["google sheets"],

    # Competition Platforms & Data Science Portals
    "kaggle": ["kaggle"],
    "drivendata": ["drivendata", "driven data"],
    "zindi": ["zindi"],
    "aicrowd": ["aicrowd", "ai crowd"],
    "numerai": ["numerai"],
    "datasource.ai": ["datasource.ai", "datasource"],
    "codalab/codabench": ["codalab/codabench", "codalab", "codabench"],

    # AI Tools & Operational Workspaces
    "chatgpt": ["chatgpt", "chat gpt", "openai", "chatgpt plus", "gpt-4", "gpt-3.5"],
    "claude": ["claude", "anthropic claude", "anthropic"],
    "notion": ["notion", "notion workspace"],
    "slack": ["slack"],
    "google workspace": ["google workspace", "google docs", "google drive", "google sheets", "g suite"],
}


@dataclass
class JobRequirements:
    job_title: str
    alternative_titles: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    tools_and_tech: list[str] = field(default_factory=list)
    qualifications: list[str] = field(default_factory=list)
    education_or_certifications: list[str] = field(default_factory=list)
    experience_level: str = ""
    location: str = ""
    employment_type: str = ""
    portfolio_required: bool = False
    mandatory_constraints: list[str] = field(default_factory=list)
    inferred_keywords: list[str] = field(default_factory=list)
    uncertainty_flags: list[str] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> JobRequirements:
        return cls(
            job_title=data.get("job_title", "Candidate Search"),
            alternative_titles=data.get("alternative_titles", []),
            required_skills=data.get("required_skills", []),
            preferred_skills=data.get("preferred_skills", []),
            tools_and_tech=data.get("tools_and_tech", []),
            qualifications=data.get("qualifications", []),
            education_or_certifications=data.get("education_or_certifications", []),
            experience_level=data.get("experience_level", ""),
            location=data.get("location", ""),
            employment_type=data.get("employment_type", ""),
            portfolio_required=bool(data.get("portfolio_required", False)),
            mandatory_constraints=data.get("mandatory_constraints", []),
            inferred_keywords=data.get("inferred_keywords", []),
            uncertainty_flags=data.get("uncertainty_flags", []),
            evidence=data.get("evidence", {}),
        )


def _split_into_sections(jd_text: str) -> dict[str, str]:
    """Splits job description into recognized semantic sections."""
    sections: dict[str, list[str]] = {
        "overview": [],
        "responsibilities": [],
        "requirements": [],
        "preferred": [],
        "tools": [],
        "metadata": [],
    }

    current_section = "overview"
    for line in jd_text.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        lower = line_clean.lower()

        # Section header matchers
        if re.search(r"^(?:requirements?|required(?:\s+skills?|\s+qualifications?|\s+experience|\s+competencies)?|what\s+you\s+need|qualifications?|must\s+haves?|minimum\s+requirements?|what\s+you\s+bring|basic\s+qualifications?)\b", lower):
            current_section = "requirements"
            continue
        elif re.search(r"^(?:huge\s+plus(?:es)?|huge\s+bonus|preferred(?:\s+skills?|\s+qualifications?|\s+requirements?)?|nice\s+to\s+have|good\s+to\s+have|bonus(?:\s+skills?)?|plus(?:es)?|what\s+would\s+make\s+you\s+stand\s+out)\b", lower):
            current_section = "preferred"
            continue
        elif re.search(r"^(?:(?:relevant\s+)?competition\s+platforms?|tools?\s*(?:&|and)\s*technolog(?:y|ies)|technologies|tools?|tech\s+stack)\b", lower):
            current_section = "tools"
            continue
        elif re.search(r"^(?:responsibilities|scope\s+of\s+work|what\s+you(?:'ll|\s+will)\s+do|duties|role\s+responsibilities|about\s+the\s+job)\b", lower):
            current_section = "responsibilities"
            continue
        elif re.search(r"^(?:general\s+contract\s+details|project\s+snapshot|role\s+overview|overview|about\s+the\s+role)\b", lower):
            current_section = "overview"
            continue
        elif re.search(r"^(?:role\s*id|positions?|locations?|duration|start\s*date|rate|est(?:\.|\s*)earnings?|task\s*time|availability|experience|employment\s+type|role\s+type|contract\s+type)\b", lower):
            current_section = "metadata"
            sections["metadata"].append(line_clean)
            continue

        # Route inline preferred/bonus qualifiers (e.g. 'is an advantage', 'nice to have') to preferred
        if current_section == "requirements" and re.search(
            r"\b(?:is\s+an?\s+advantage|is\s+a\s+plus|nice\s+to\s+have|preferred|optional|bonus)\b", lower
        ):
            sections["preferred"].append(line_clean)
            continue

        sections[current_section].append(line_clean)

    return {k: "\n".join(v) for k, v in sections.items()}


def _extract_taxonomy_matches(text: str, taxonomy: dict[str, list[str]]) -> list[str]:
    """Finds canonical taxonomy entries in text by inspecting all synonyms with word boundaries."""
    lower = text.lower()
    matches = []
    for canonical, aliases in taxonomy.items():
        found = False
        for alias in aliases:
            pattern = rf"(?<!\w){re.escape(alias.lower())}(?!\w)"
            if re.search(pattern, lower):
                found = True
                break
        if found:
            matches.append(canonical)
    return matches


def extract_location(text: str) -> str:
    """Extracts target location or remote status from JD text.
    Recognizes line-anchored location headers and supported countries/cities.
    Never treats ordinary prose, punctuation, or approval status phrases as locations.
    """
    locations = []
    # Check remote indicators
    if re.search(r"\bremote\b", text, re.I):
        locations.append("Remote")
    elif re.search(r"\bhybrid\b", text, re.I):
        locations.append("Hybrid")
    elif re.search(r"\bon-?site\b", text, re.I):
        locations.append("On-site")

    # Line-anchored headers with colon/dash delimiter or standalone newline
    header_patterns = [
        re.compile(
            r"^(?:locations?|geography|preferred\s+locations?|eligible\s+locations?|place\s+of\s+work|work\s+locations?)\s*[:\-–—]\s*([^\n\r]+)",
            re.I | re.MULTILINE,
        ),
        re.compile(
            r"^(?:locations?|geography|place\s+of\s+work)\s*\n\s*([^\n\r]+)",
            re.I | re.MULTILINE,
        ),
    ]

    found_locs = []
    for pat in header_patterns:
        for m in pat.finditer(text):
            line_val = m.group(1).strip()
            tokens = re.split(r"[,;/|\(\)]|\band\b", line_val)
            for raw_tok in tokens:
                tok = re.sub(
                    r"^(?:the|preferred|eligible|listed|all)\s+", "", raw_tok.strip(), flags=re.I
                ).strip(" .:,;-")
                if not tok or len(tok) < 2:
                    continue
                words = set(re.findall(r"\b[a-zA-Z]+\b", tok.lower()))
                # Reject if token contains disqualified prose words unless it's a known country
                if words & DISQUALIFIED_LOCATION_WORDS and tok.lower() not in KNOWN_COUNTRIES_AND_REGIONS:
                    continue

                # Check for known country / region / city match
                matched = None
                for k, v in KNOWN_COUNTRIES_AND_REGIONS.items():
                    if re.search(rf"\b{re.escape(k)}\b", tok, re.I):
                        matched = v
                        break

                if matched:
                    if matched not in found_locs and matched not in locations:
                        found_locs.append(matched)
                elif not (words & DISQUALIFIED_LOCATION_WORDS) and len(tok) <= 30 and tok.istitle():
                    if tok not in found_locs and tok not in locations:
                        found_locs.append(tok)

    locations.extend(found_locs)
    return "; ".join(locations) if locations else "Remote"


def extract_experience(text: str) -> str:
    """Extracts experience requirements (e.g. '3+ years', 'Freshers welcome', 'No experience required')."""
    if re.search(r"\b(?:no\s+professional\s+experience\s+required|freshers?\s+(?:are\s+)?welcome|no\s+experience\s+required)\b", text, re.I):
        return "Freshers / No professional experience required"

    # 1. Explicit labeled field (e.g. "Experience: 5+ years...")
    label_match = re.search(r"^(?:experience|years\s+of\s+experience|required\s+experience)\s*[:\-–—]\s*([^\n\r]+)", text, re.I | re.MULTILINE)
    if label_match:
        val = label_match.group(1).strip()
        if val and not re.search(r"^(?:level|none|n/a)$", val, re.I):
            return val

    # 2. Match patterns with optional words between years of and experience: "5+ years of professional illustration experience"
    match = re.search(r"\b(\d+\s*(?:[-–+to]+\s*\d+)?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+[\w\s]{1,30})?\s+experience)\b", text, re.I)
    if match:
        return match.group(1).strip()

    # 3. Simple "3+ years", "3-5 years"
    simple_match = re.search(r"\b(\d+\s*(?:[-–+to]+\s*\d+)?\s*(?:years?|yrs?))\b", text, re.I)
    if simple_match:
        return simple_match.group(1).strip()

    return ""


def extract_employment_type(text: str) -> str:
    """Extracts contract/employment type (e.g. 'Contractor', 'Short-term contract', 'Full-time', 'Pay per task')."""
    # 1. Check explicit labeled headers
    header_match = re.search(
        r"^(?:role\s+type|employment\s+type|contract\s+type)\s*[:\n\-–—]\s*([^\n\r]+)",
        text,
        re.I | re.MULTILINE,
    )
    if header_match:
        val = header_match.group(1).strip()
        if re.search(r"\bcontractor\b", val, re.I):
            return "Contractor"
        if re.search(r"\bshort-term\s+contract\b", val, re.I):
            return "Short-term contract"
        if re.search(r"\bcontract\b", val, re.I):
            return "Contract"
        if re.search(r"\bfull-time\b", val, re.I):
            return "Full-time"
        if re.search(r"\bpart-time\b", val, re.I):
            return "Part-time"
        if re.search(r"\bpay\s+per\s+task\b", val, re.I):
            return "Pay per task"
        if len(val.split()) <= 3:
            return val.capitalize()

    # 2. Body search
    types = []
    if re.search(r"\bcontractor\b", text, re.I):
        types.append("Contractor")
    elif re.search(r"\bshort-term\s+contract\b", text, re.I):
        types.append("Short-term contract")
    elif re.search(r"\bcontract\b", text, re.I):
        types.append("Contract")
    elif re.search(r"\bfull-time\b", text, re.I):
        types.append("Full-time")
    elif re.search(r"\bpart-time\b", text, re.I):
        types.append("Part-time")

    if re.search(r"\bpay\s+per\s+task\b", text, re.I):
        types.append("Pay per task")

    return ", ".join(types) if types else "Full-time"


def extract_education_or_certifications(text: str) -> list[str]:
    """Extracts explicit education degrees or professional certifications if present in JD."""
    results: list[str] = []
    deg_patterns = [
        r"\b(?:bachelor(?:'s)?(?:\s+degree)?(?:\s+in\s+[a-zA-Z\s/]+)?)\b",
        r"\b(?:master(?:'s)?(?:\s+degree)?(?:\s+in\s+[a-zA-Z\s/]+)?)\b",
        r"\b(?:b\.?s\.?c?|b\.?e\.?|b\.?tech|b\.?a\.?|m\.?s\.?c?|m\.?tech|m\.?b\.?a\.?|ph\.?d\.?)\b",
        r"\b(?:degree\s+in\s+[a-zA-Z\s/]+)\b",
        r"\b(?:diploma\s+in\s+[a-zA-Z\s/]+)\b",
    ]
    for pat in deg_patterns:
        for m in re.finditer(pat, text, re.I):
            val = m.group(0).strip()
            val = re.sub(r"\s+or\s+(?:equivalent|related\s+(?:field|discipline)|similar)\b.*$", "", val, flags=re.I).strip()
            val = re.sub(r"[\s,;]+$", "", val)
            if len(val) > 3 and val.lower() not in [r.lower() for r in results]:
                results.append(val)

    cert_patterns = [
        r"\b(?:aws\s+certified[^\n,;]*)\b",
        r"\b(?:google\s+cloud\s+certified[^\n,;]*)\b",
        r"\b(?:azure\s+certified[^\n,;]*)\b",
        r"\b(?:pmp\s+certified|pmp\s+certification)\b",
        r"\b(?:scrum\s+master\s+certified|csm)\b",
        r"\b(?:cissp)\b",
    ]
    for pat in cert_patterns:
        for m in re.finditer(pat, text, re.I):
            val = m.group(0).strip()
            val = re.sub(r"[\s,;]+$", "", val)
            if len(val) > 2 and val.lower() not in [r.lower() for r in results]:
                results.append(val)

    # Deduplicate: if an item is a substring of a longer item, keep only the longer one
    filtered: list[str] = []
    for r in results:
        if any(r.lower() in other.lower() and len(other) > len(r) for other in results):
            continue
        filtered.append(r)

    return filtered


def extract_mandatory_constraints(text: str) -> list[str]:
    """Extracts explicit non-negotiable constraints (e.g. location, age, legal eligibility, work permits)."""
    constraints: list[str] = []
    patterns = [
        r"\b(?:must\s+be\s+(?:located|based|living|resident)\s+(?:in|within)\s+[^\n.,;]+)",
        r"\b(?:must\s+have\s+(?:valid\s+)?(?:work\s+authorization|work\s+permit|visa|legal\s+authorization|right\s+to\s+work)[^\n.,;]*)",
        r"\b(?:must\s+be\s+(?:at\s+least\s+)?18\s+years\s+(?:of\s+age|old)?)",
        r"\b(?:must\s+be\s+available\s+(?:immediately|full-time|to\s+start)[^\n.,;]*)",
        r"\b(?:security\s+clearance\s+required[^\n.,;]*)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            val = m.group(0).strip()
            val = re.sub(r"[\s,;]+$", "", val)
            if len(val) > 5 and val.lower() not in [c.lower() for c in constraints]:
                constraints.append(val)
    return constraints


def extract_inferred_keywords(text: str, existing_skills: set[str], existing_tools: set[str]) -> list[str]:
    """Finds salient technical / domain phrases in text without dumping noise words."""
    # Tokenize words of 3+ letters
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9+#.\-/]{2,}\b", text.lower())

    # Build word-level lookup for existing skills, tools, and locations
    skill_and_tool_tokens: set[str] = set()
    for item in list(existing_skills) + list(existing_tools):
        for tok in re.findall(r"\b[a-zA-Z]+\b", item.lower()):
            skill_and_tool_tokens.add(tok)

    geo_tokens = {tok for k in KNOWN_COUNTRIES_AND_REGIONS.keys() for tok in re.findall(r"\b[a-zA-Z]+\b", k.lower())}

    filtered_counts: dict[str, int] = {}
    for w in words:
        # Filter out web domains, URLs, watermarks, file extensions (e.g. futurejobs.ai, test.pdf, example.com)
        if "." in w or re.search(r"\.(ai|com|org|net|io|co|pdf|docx|txt|html|gov|edu)\b", w, re.I):
            continue

        # Check subcomponents if word contains slashes, hyphens, or dots (e.g. "hours/week", "futurejobs.ai")
        subparts = [p.strip() for p in re.split(r"[/\\.\-]", w) if p.strip()]
        if any(p in RECRUITMENT_STOPWORDS or p in KNOWN_COUNTRIES_AND_REGIONS or p in geo_tokens for p in subparts):
            continue

        if w in RECRUITMENT_STOPWORDS or w in KNOWN_COUNTRIES_AND_REGIONS or w in geo_tokens:
            continue
        if w in skill_and_tool_tokens:
            continue
        if any(w in s for s in existing_skills) or any(w in t for t in existing_tools):
            continue
        # Avoid pure numbers, dates, website codes
        if re.match(r"^[\d\W_]+$", w) or len(w) < 4:
            continue
        if w in ROLE_KEYWORDS:
            continue

        # Singular deduplication: normalize plural words ending in 's' (unless ending in ss, us, is)
        norm_w = w
        if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 4:
            norm_w = w[:-1]
            if norm_w in RECRUITMENT_STOPWORDS or norm_w in skill_and_tool_tokens:
                continue

        filtered_counts[norm_w] = filtered_counts.get(norm_w, 0) + 1

    # Keep only domain words occurring multiple times
    salient = [
        w for w, count in sorted(filtered_counts.items(), key=lambda x: (-x[1], x[0]))
        if count >= 2
    ]
    return salient[:8]


def extract_requirements(jd_text: str) -> JobRequirements:
    """Extracts structured recruitment requirements from a job description."""
    title_res = extract_job_title(jd_text)
    sections = _split_into_sections(jd_text)

    # Required section skills vs responsibilities vs preferred
    req_text = sections["requirements"]
    pref_text = sections["preferred"]
    resp_text = sections["responsibilities"]
    all_text = jd_text

    # Extract taxonomy matches
    skills_in_req = _extract_taxonomy_matches(req_text, KNOWN_SKILLS)
    skills_in_resp = _extract_taxonomy_matches(resp_text, KNOWN_SKILLS)
    skills_in_all = _extract_taxonomy_matches(all_text, KNOWN_SKILLS)

    tools_in_req = _extract_taxonomy_matches(req_text, KNOWN_TOOLS)
    tools_in_tools_sec = _extract_taxonomy_matches(sections.get("tools", ""), KNOWN_TOOLS)
    tools_in_resp = _extract_taxonomy_matches(resp_text, KNOWN_TOOLS)
    tools_in_all = _extract_taxonomy_matches(all_text, KNOWN_TOOLS)

    pref_skills = _extract_taxonomy_matches(pref_text, KNOWN_SKILLS)
    pref_tools = _extract_taxonomy_matches(pref_text, KNOWN_TOOLS)

    # Tools: prioritize explicit tools section and requirement tools first, then remaining body tools, then preferred tools
    all_tools = []
    for t in tools_in_tools_sec + tools_in_req + tools_in_resp:
        if t not in all_tools and t not in pref_tools:
            all_tools.append(t)
    for t in tools_in_all:
        if t not in all_tools and t not in pref_tools:
            all_tools.append(t)
    for t in pref_tools:
        if t not in all_tools:
            all_tools.append(t)

    # Core required skills: items found in explicit requirements
    required_skills = []
    for s in skills_in_req:
        if s not in required_skills and s not in all_tools:
            required_skills.append(s)

    # Ensure preferred skills do not duplicate core required skills
    pref_skills = [s for s in pref_skills if s not in required_skills]

    # Additional core skills from responsibilities (excluding preferred and tools)
    for s in skills_in_resp:
        if s not in required_skills and s not in pref_skills and s not in all_tools:
            required_skills.append(s)

    # Deduplicate redundant generic parent concepts if specific specialization exists
    if "ml engineering" in required_skills and "machine learning" in required_skills:
        required_skills.remove("machine learning")

    # If no explicit requirements section was demarcated, use skills found in body
    if not required_skills and skills_in_all:
        required_skills = [s for s in skills_in_all if s not in pref_skills and s not in all_tools][:8]

    # Check portfolio requirement
    portfolio_required = bool(re.search(r"\bportfolio\b", all_text, re.I))

    # Inferred keywords
    existing_skills = set(required_skills + pref_skills)
    existing_tools = set(all_tools)
    inferred = extract_inferred_keywords(all_text, existing_skills, existing_tools)

    # Qualifications & experience
    exp = extract_experience(all_text)
    loc = extract_location(all_text)
    emp_type = extract_employment_type(all_text)
    edu_certs = extract_education_or_certifications(all_text)
    constraints = extract_mandatory_constraints(all_text)

    qualifications = []
    if exp:
        qualifications.append(exp)
    if portfolio_required:
        qualifications.append("Portfolio / Work samples required")
    for ec in edu_certs:
        qualifications.append(ec)

    return JobRequirements(
        job_title=title_res.title,
        alternative_titles=title_res.alternative_titles,
        required_skills=required_skills,
        preferred_skills=pref_skills,
        tools_and_tech=all_tools,
        qualifications=qualifications,
        education_or_certifications=edu_certs,
        experience_level=exp,
        location=loc,
        employment_type=emp_type,
        portfolio_required=portfolio_required,
        mandatory_constraints=constraints,
        inferred_keywords=inferred,
    )
