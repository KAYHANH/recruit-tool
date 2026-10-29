"""
Talent Pool & Target-Company Mapping Module
Adapted from Recruiting-Skills-for-AI-Agents.

Enriches search planning by identifying relevant tech clusters,
competitor/adjacent organizations, and technical ecosystem signals
to expand candidate discovery without requiring paid enrichment APIs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TalentPoolCluster:
    domain_name: str
    target_companies: list[str]
    adjacent_titles: list[str]
    tech_ecosystems: list[str]
    sample_open_source_projects: list[str]


# Role family identifiers for JD-aware source selection and search planning
ROLE_FAMILY_AI_GENERALIST_OPERATIONS = "ai_generalist_operations"
ROLE_FAMILY_SOFTWARE_ENGINEERING = "software_engineering"
ROLE_FAMILY_AI_ML_RESEARCH = "ai_ml_research"
ROLE_FAMILY_DATA_SCIENCE_ANALYTICS = "data_science_analytics"
ROLE_FAMILY_PRODUCT_DESIGN = "product_design"
ROLE_FAMILY_CREATIVE_3D = "creative_3d"

# Curated, zero-budget domain knowledge maps for common engineering, AI and operations roles
DOMAIN_TALENT_MAPS: dict[str, TalentPoolCluster] = {
    "ai_generalist_operations": TalentPoolCluster(
        domain_name="AI Generalist, Evaluation & Digital Operations",
        target_companies=[
            "Scale AI", "Invisible Technologies", "Outlier.ai", "Remotasks",
            "DataAnnotation.tech", "Appen", "Turing", "Alignerr", "Mercor", "OneForma"
        ],
        adjacent_titles=[
            "AI Generalist", "AI Evaluator", "AI Training Specialist",
            "Model Evaluation Specialist", "RLHF Annotation Specialist",
            "Prompt Evaluation Specialist", "Content Quality Specialist", "Operations Generalist"
        ],
        tech_ecosystems=["ChatGPT", "Claude", "OpenAI Playground", "Google Workspace", "Notion", "Slack", "Spreadsheets"],
        sample_open_source_projects=["evals", "promptfoo", "guidelines", "rubrics"],
    ),
    "machine_learning_ai": TalentPoolCluster(
        domain_name="AI & Machine Learning",
        target_companies=[
            "Hugging Face", "Cohere", "Mistral", "DeepMind", "Meta AI",
            "OpenAI", "Databricks", "Anthropic", "Scale AI", "Weights & Biases"
        ],
        adjacent_titles=[
            "Research Engineer", "Applied Scientist", "NLP Engineer",
            "Computer Vision Engineer", "MLOps Engineer", "Algorithm Engineer"
        ],
        tech_ecosystems=["PyTorch", "Transformers", "JAX", "vLLM", "TensorRT", "LangChain"],
        sample_open_source_projects=["transformers", "diffusers", "vllm", "llama.cpp", "langchain"],
    ),
    "data_science": TalentPoolCluster(
        domain_name="Data Science & Analytics",
        target_companies=[
            "Databricks", "Snowflake", "Palantir", "Uber", "Spotify",
            "Stripe", "Airbnb", "DoorDash", "Target", "Capital One"
        ],
        adjacent_titles=[
            "Quantitative Analyst", "Decision Scientist", "Statistician",
            "Data Specialist", "Machine Learning Practitioner"
        ],
        tech_ecosystems=["Pandas", "Scikit-Learn", "XGBoost", "PySpark", "Polars", "DuckDB"],
        sample_open_source_projects=["scikit-learn", "pandas", "polars", "duckdb", "xgboost"],
    ),
    "backend_cloud": TalentPoolCluster(
        domain_name="Backend & Cloud Infrastructure",
        target_companies=[
            "AWS", "Google Cloud", "Microsoft Azure", "Cloudflare", "HashiCorp",
            "Twilio", "Datadog", "Confluent", "MongoDB", "Redis"
        ],
        adjacent_titles=[
            "Systems Engineer", "Platform Engineer", "Distributed Systems Engineer",
            "Site Reliability Engineer", "Infrastructure Developer"
        ],
        tech_ecosystems=["Go", "Rust", "Kubernetes", "gRPC", "Kafka", "PostgreSQL"],
        sample_open_source_projects=["kubernetes", "grpc-go", "tokio", "temporal", "cockroach"],
    ),
    "frontend_mobile": TalentPoolCluster(
        domain_name="Frontend & Cross-Platform Mobile",
        target_companies=[
            "Vercel", "Meta", "Shopify", "Netlify", "GitHub",
            "Figma", "Stripe", "Linear", "Supabase", "Retool"
        ],
        adjacent_titles=[
            "UI Engineer", "Web Developer", "React Developer",
            "Mobile Architect", "Design Engineer"
        ],
        tech_ecosystems=["React", "Next.js", "TypeScript", "Tailwind CSS", "Flutter", "React Native"],
        sample_open_source_projects=["next.js", "react", "tailwind", "flutter", "radix-ui"],
    ),
}


class TalentPoolMapper:
    """Discovers adjacent talent pools, target companies, and ecosystem projects
    for intelligent search query expansion and JD-aware source selection.
    """

    def detect_role_family(self, role_title: str, skills: list[str], jd_text: str = "") -> str:
        """Determines the overarching role family from title, skills, and full JD context."""
        text = f"{role_title} {' '.join(skills)} {jd_text}".lower()

        # 1. AI Generalist, Evaluation & Operations
        generalist_signals = [
            "generalist", "ai generalist", "evaluator", "evaluation", "annotation",
            "annotator", "rlhf", "chatgpt", "ai rater", "quality rater", "ai trainer",
            "prompt test", "digital literacy", "task execution"
        ]
        engineering_exclusions = [
            "machine learning engineer", "ml engineer", "research scientist",
            "software engineer", "backend developer", "systems architect", "deep learning engineer",
            "pytorch", "tensorflow", "cuda", "compiler"
        ]
        has_gen = any(w in text for w in generalist_signals)
        has_eng = any(w in text for w in engineering_exclusions)

        if has_gen and not has_eng:
            return ROLE_FAMILY_AI_GENERALIST_OPERATIONS

        # 2. AI & Machine Learning Research / Engineering
        if any(w in text for w in ["machine learning", "ml engineer", "deep learning", "nlp", "computer vision", "llm engineer", "pytorch", "transformers", "vllm", "jax"]):
            return ROLE_FAMILY_AI_ML_RESEARCH

        # 3. Data Science & Analytics
        if any(w in text for w in ["data science", "data scientist", "statistician", "analytics engineer", "econometric", "quant analyst"]):
            return ROLE_FAMILY_DATA_SCIENCE_ANALYTICS

        # 4. Creative / 3D
        if any(w in text for w in ["3d model", "blender", "maya", "texture artist", "animator", "zbrush"]):
            return ROLE_FAMILY_CREATIVE_3D

        # 5. Product & Design
        if any(w in text for w in ["product manager", "ui/ux", "ux designer", "figma", "product design"]):
            return ROLE_FAMILY_PRODUCT_DESIGN

        # Default: Software Engineering
        return ROLE_FAMILY_SOFTWARE_ENGINEERING

    def get_recommended_sources(self, role_family: str) -> list[str]:
        """Returns the optimal zero-budget candidate sourcing connectors for a given role family."""
        if role_family == ROLE_FAMILY_AI_GENERALIST_OPERATIONS:
            # Prioritize automated web/profile discovery & internal talent rediscovery
            # Code-hosting and developer-specific API sources are deprioritized
            return ["groq_browser", "local_db"]
        elif role_family == ROLE_FAMILY_AI_ML_RESEARCH:
            return ["huggingface", "github", "gitlab", "groq_browser", "local_db"]
        elif role_family == ROLE_FAMILY_DATA_SCIENCE_ANALYTICS:
            return ["github", "stackoverflow", "groq_browser", "local_db"]
        elif role_family in (ROLE_FAMILY_PRODUCT_DESIGN, ROLE_FAMILY_CREATIVE_3D):
            return ["groq_browser", "local_db"]
        else:
            # Software engineering default
            return ["github", "gitlab", "stackoverflow", "groq_browser", "local_db"]

    def filter_sources_for_role(self, sources: list[str], role_family: str) -> list[str]:
        """Ensures source selection aligns with role requirements.
        Prevents code-hosting sources from flooding non-technical operations/generalist runs.
        """
        recommended = self.get_recommended_sources(role_family)
        # If caller provided full default list, refine to role-appropriate sources
        default_all = {"github", "gitlab", "stackoverflow", "huggingface", "local_db", "groq_browser"}
        if set(sources) == default_all:
            return recommended
        # Otherwise respect caller selection, ensuring at least one recommended source is included
        return [s for s in sources if s in default_all]

    def get_role_source_policy(self, role_family: str) -> dict[str, Any]:
        """Provides metadata explaining source selection rationale."""
        if role_family == ROLE_FAMILY_AI_GENERALIST_OPERATIONS:
            return {
                "role_family": role_family,
                "display_name": "AI Generalist & Digital Operations",
                "priority_sources": ["groq_browser", "local_db"],
                "primary": ["groq_browser", "local_db"],
                "deprioritized_sources": ["github", "gitlab", "stackoverflow", "huggingface"],
                "excluded_or_low_priority": ["github", "gitlab", "stackoverflow", "huggingface"],
                "requires_code_portfolio": False,
                "rationale": "Generalist/operations roles require professional profile and workflow evidence; code-hosting repositories are deprioritized to avoid developer noise.",
            }
        elif role_family == ROLE_FAMILY_AI_ML_RESEARCH:
            return {
                "role_family": role_family,
                "display_name": "AI & Machine Learning Research",
                "priority_sources": ["huggingface", "github", "gitlab", "groq_browser", "local_db"],
                "primary": ["huggingface", "github", "gitlab", "groq_browser", "local_db"],
                "deprioritized_sources": [],
                "excluded_or_low_priority": [],
                "requires_code_portfolio": True,
                "rationale": "AI/ML roles benefit from model publishing metrics on Hugging Face Hub and open-source repos on GitHub.",
            }
        else:
            return {
                "role_family": role_family,
                "display_name": "Technical Engineering",
                "priority_sources": ["github", "gitlab", "stackoverflow", "groq_browser", "local_db"],
                "primary": ["github", "gitlab", "stackoverflow", "groq_browser", "local_db"],
                "deprioritized_sources": [],
                "excluded_or_low_priority": [],
                "requires_code_portfolio": True,
                "rationale": "Engineering roles require verifiable code stewardship and technical contribution evidence.",
            }

    def detect_domain(self, role_title: str, skills: list[str]) -> TalentPoolCluster:
        """Determines the closest domain cluster based on title and skill indicators."""
        text = f"{role_title} {' '.join(skills)}".lower()

        # Check AI Generalist / Operations before generic AI keywords
        if any(w in text for w in ["generalist", "ai generalist", "evaluator", "annotation", "rlhf", "chatgpt", "quality rater", "ai trainer"]):
            return DOMAIN_TALENT_MAPS["ai_generalist_operations"]
        elif any(w in text for w in ["machine learning", "ml", "ai", "deep learning", "nlp", "vision", "llm"]):
            return DOMAIN_TALENT_MAPS["machine_learning_ai"]
        elif any(w in text for w in ["data science", "data scientist", "statistic", "analytics", "econometric", "quant"]):
            return DOMAIN_TALENT_MAPS["data_science"]
        elif any(w in text for w in ["frontend", "ui", "ux", "react", "vue", "web", "flutter", "mobile"]):
            return DOMAIN_TALENT_MAPS["frontend_mobile"]
        else:
            return DOMAIN_TALENT_MAPS["backend_cloud"]

    def generate_expanded_search_queries(
        self,
        role_title: str,
        skills: list[str],
        location: str = "",
        max_queries: int = 4,
    ) -> list[dict[str, Any]]:
        """Generates role-specific search strategies incorporating target companies
        and ecosystem projects as high-recall query alternatives.
        """
        cluster = self.detect_domain(role_title, skills)
        queries: list[dict[str, Any]] = []

        # Strategy 1: Core skills + Title (Baseline Precision)
        core_skills_str = " ".join(skills[:3]) if skills else role_title
        queries.append({
            "strategy": "Precision Core Skills",
            "keywords": f"{role_title} {core_skills_str}".strip(),
            "target_location": location,
            "description": f"Direct matching on primary title '{role_title}' and core technical skills.",
        })

        # Strategy 2: Adjacent Title + Domain Tech Ecosystem
        if cluster.adjacent_titles and cluster.tech_ecosystems:
            adj_title = cluster.adjacent_titles[0]
            ecosystem = " ".join(cluster.tech_ecosystems[:2])
            queries.append({
                "strategy": "Adjacent Role & Technical Ecosystem",
                "keywords": f"{adj_title} {ecosystem}".strip(),
                "target_location": location,
                "description": f"Expands recall to similar engineering profiles ({adj_title}) proficient in {ecosystem}.",
            })

        # Strategy 3: Target Company Cluster (Peer organizations)
        if cluster.target_companies:
            top_orgs = cluster.target_companies[:3]
            org_str = " OR ".join([f'"{org}"' for org in top_orgs])
            primary_skill = skills[0] if skills else role_title
            queries.append({
                "strategy": "Target-Company Peer Mapping",
                "keywords": f"{primary_skill} ({org_str})".strip(),
                "target_location": location,
                "description": f"Discovers candidates with verified background in peer technology organizations ({', '.join(top_orgs)}).",
            })

        # Strategy 4: Open Source Repository Stewardship
        if cluster.sample_open_source_projects:
            top_repo = cluster.sample_open_source_projects[0]
            queries.append({
                "strategy": "Open Source Ecosystem Stewardship",
                "keywords": f"{top_repo} {skills[0] if skills else ''}".strip(),
                "target_location": location,
                "description": f"Discovers contributors and maintainers active in relevant open-source projects ({top_repo}).",
            })

        return queries[:max_queries]


talent_pool_mapper = TalentPoolMapper()

# Module-level aliases for direct function imports
detect_role_family = talent_pool_mapper.detect_role_family
get_recommended_sources = talent_pool_mapper.get_recommended_sources
filter_sources_for_role = talent_pool_mapper.filter_sources_for_role
get_role_source_policy = talent_pool_mapper.get_role_source_policy
