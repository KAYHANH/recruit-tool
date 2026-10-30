"""
CV Parser Module — Local, zero-budget, streaming extraction for PDF, DOCX, and TXT resumes.

Supports:
- Local text extraction via PyMuPDF (PDF), python-docx (DOCX), and clean text (TXT/MD).
- Detection of scanned or image-only PDFs requiring OCR without throwing unhandled exceptions.
- Rule-based extraction of name, normalized email, phone, location, skills, languages, and experience.
- SHA-256 file hashing for deduplication.
- Memory-bounded stream processing suitable for batches of 500-1,000 CVs.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Optional

try:
    import fitz  # PyMuPDF
except Exception:
    try:
        import pymupdf as fitz
    except Exception:
        fitz = None

try:
    from docx import Document
except Exception:
    Document = None

from jd_parser import clean_text

logger = logging.getLogger("cv_parser")

MAX_CV_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB max per CV file

# Standard tech, AI/ML, operations, and generalist taxonomy for deterministic matching
CORE_SKILLS_TAXONOMY = {
    # Programming Languages
    "python", "javascript", "typescript", "golang", "go", "java", "c++", "c#", "ruby", "rust",
    "php", "swift", "kotlin", "scala", "r", "julia", "sql", "bash", "shell", "dart",
    # AI / Machine Learning
    "machine learning", "deep learning", "nlp", "natural language processing", "computer vision",
    "llm", "large language models", "prompt engineering", "langchain", "llamaindex", "transformers",
    "hugging face", "pytorch", "tensorflow", "keras", "scikit-learn", "fine-tuning", "rag",
    "vector database", "pinecone", "weaviate", "qdrant", "chromadb", "ai evaluation",
    # Frontend / Mobile
    "react", "react.js", "next.js", "vue", "vue.js", "angular", "svelte", "sveltekit",
    "html5", "css3", "tailwind", "tailwind css", "redux", "zustand", "flutter", "react native",
    # Backend / Frameworks
    "fastapi", "django", "flask", "node.js", "express", "express.js", "nest.js", "spring boot",
    "asp.net", "graphql", "rest api", "grpc", "microservices",
    # Data & Databases
    "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis", "elasticsearch",
    "snowflake", "bigquery", "databricks", "pandas", "numpy", "spark", "kafka", "dbt",
    # Cloud & DevOps
    "aws", "amazon web services", "gcp", "google cloud", "azure", "docker", "kubernetes",
    "ci/cd", "github actions", "gitlab ci", "terraform", "ansible", "helm", "linux",
    # Operations & Generalist Skills
    "project management", "product management", "agile", "scrum", "data analysis",
    "technical writing", "problem solving", "attention to detail", "communication",
    "documentation", "workflow automation", "qa testing", "unit testing", "quality assurance"
}

LANGUAGES_TAXONOMY = {
    "english", "spanish", "french", "german", "mandarin", "chinese", "hindi", "arabic",
    "portuguese", "russian", "japanese", "korean", "italian", "dutch", "bengali", "urdu"
}


@dataclass
class ParsedCV:
    file_name: str
    file_path: str = ""
    file_hash: str = ""
    file_size: int = 0
    file_type: str = "unknown"
    raw_text: str = ""
    cleaned_text: str = ""
    name: str = ""
    email: str = ""
    normalized_email: str = ""
    phone: str = ""
    location: str = ""
    skills: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    years_of_experience: int = 0
    headline: str = ""
    confidence_score: float = 0.0
    parsing_status: str = "SUCCESS"  # SUCCESS, OCR_REQUIRED, FAILED
    error_message: str = ""


def compute_sha256(data: bytes) -> str:
    """Computes SHA-256 checksum of raw file bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(path: Path | str) -> str:
    """Computes SHA-256 checksum of a file on disk incrementally."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class CVParser:
    """Zero-budget, offline resume and CV extraction engine."""

    def parse_bytes(self, content: bytes, filename: str, file_path: str = "") -> ParsedCV:
        """Parses raw document bytes into a structured ParsedCV."""
        file_size = len(content)
        file_hash = compute_sha256(content)
        file_ext = Path(filename).suffix.lower().lstrip(".")

        res = ParsedCV(
            file_name=filename,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            file_type=file_ext or "unknown",
        )

        if file_size == 0:
            res.parsing_status = "FAILED"
            res.error_message = "File is empty (0 bytes)."
            return res

        if file_size > MAX_CV_FILE_SIZE_BYTES:
            res.parsing_status = "FAILED"
            res.error_message = f"File size exceeds maximum limit of 25MB ({file_size / (1024*1024):.1f}MB)."
            return res

        # Extract raw text depending on file format
        try:
            if file_ext == "pdf":
                raw_text, is_scanned = self._extract_pdf_text(content)
                if is_scanned:
                    res.parsing_status = "OCR_REQUIRED"
                    res.error_message = "Scanned or image-only PDF detected. No extractable text layer found."
                    return res
            elif file_ext == "docx":
                raw_text = self._extract_docx_text(content)
            elif file_ext in ("txt", "md", "text", "markdown"):
                raw_text = self._extract_txt_text(content)
            else:
                res.parsing_status = "FAILED"
                res.error_message = f"Unsupported file extension: .{file_ext}. Supported formats: PDF, DOCX, TXT."
                return res
        except Exception as exc:
            logger.warning("Extraction error for file %s: %s", filename, exc)
            res.parsing_status = "FAILED"
            res.error_message = f"Document extraction failed: {str(exc)}"
            return res

        cleaned = clean_text(raw_text)
        res.raw_text = raw_text
        res.cleaned_text = cleaned

        if not cleaned or len(cleaned.strip()) < 20:
            res.parsing_status = "FAILED"
            res.error_message = "Document contains insufficient text."
            return res

        # Rule-based field extraction
        res.email, res.normalized_email = self.extract_email(cleaned)
        res.phone = self.extract_phone(cleaned)
        res.name = self.extract_name(cleaned, filename)
        res.skills = self.extract_skills(cleaned)
        res.languages = self.extract_languages(cleaned)
        res.years_of_experience = self.extract_years_of_experience(cleaned)
        res.location = self.extract_location(cleaned)

        primary_role = res.skills[0].title() if res.skills else "Professional"
        exp_str = f"{res.years_of_experience} yrs exp" if res.years_of_experience > 0 else "Experience documented"
        res.headline = f"{primary_role} | {exp_str}"

        res.confidence_score = self.compute_confidence(res)
        res.parsing_status = "SUCCESS"
        return res

    def parse_file(self, file_path: Path | str) -> ParsedCV:
        """Parses a local CV file from disk."""
        p = Path(file_path).resolve()
        if not p.exists() or not p.is_file():
            res = ParsedCV(file_name=p.name, file_path=str(p))
            res.parsing_status = "FAILED"
            res.error_message = f"File not found on disk: {p}"
            return res

        with open(p, "rb") as f:
            content = f.read()

        return self.parse_bytes(content, filename=p.name, file_path=str(p))

    def _extract_pdf_text(self, content: bytes) -> tuple[str, bool]:
        """Extracts text from PDF bytes and detects scanned PDFs."""
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) is not installed.")

        doc = fitz.open(stream=content, filetype="pdf")
        page_texts: list[str] = []
        for page in doc:
            t = page.get_text("text") or ""
            page_texts.append(t)

        combined = "\n".join(page_texts)
        # Check if text is essentially empty (scanned image)
        meaningful_chars = re.sub(r"[\s\d\W_]+", "", combined)
        if len(meaningful_chars) < 25:
            return "", True
        return combined, False

    def _extract_docx_text(self, content: bytes) -> str:
        """Extracts text from DOCX bytes including tables."""
        if Document is None:
            raise RuntimeError("python-docx is not installed.")

        doc = Document(io.BytesIO(content))
        lines: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    lines.append(" | ".join(cells))
        return "\n".join(lines)

    def _extract_txt_text(self, content: bytes) -> str:
        """Extracts text from plain text bytes with charset fallbacks."""
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                return content.decode(enc)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    @staticmethod
    def extract_email(text: str) -> tuple[str, str]:
        """Extracts the first valid email address and returns (raw, normalized)."""
        pattern = r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"
        matches = re.findall(pattern, text)
        for m in matches:
            cleaned = m.strip().rstrip(".")
            lower = cleaned.lower()
            # Ignore common dummy or template emails
            if any(dummy in lower for dummy in ["example.com", "domain.com", "email.com", "yourname@", "test@"]):
                continue
            return cleaned, lower
        return "", ""

    @staticmethod
    def extract_phone(text: str) -> str:
        """Extracts plausible phone numbers from resume header."""
        pattern = r"(?:(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4})"
        matches = re.findall(pattern, text[:1500])
        for m in matches:
            digits = re.sub(r"\D", "", m)
            if 8 <= len(digits) <= 15:
                return m.strip()
        return ""

    @staticmethod
    def extract_name(text: str, filename: str) -> str:
        """Extracts candidate name from the top section of the CV or filename."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        header_lines = lines[:10]

        # Ignore obvious section titles and non-name strings
        disallowed_keywords = {
            "curriculum vitae", "resume", "cv", "profile", "contact", "experience",
            "education", "skills", "summary", "email", "phone", "address", "portfolio",
            "page", "github", "linkedin", "developer", "engineer", "designer", "consultant"
        }

        for line in header_lines:
            if len(line) < 3 or len(line) > 50:
                continue
            if "@" in line or "http" in line or ".com" in line:
                continue
            if re.search(r"\d", line):
                continue
            lower_line = line.lower()
            if any(dk == lower_line or lower_line.startswith(dk + ":") for dk in disallowed_keywords):
                continue

            words = line.split()
            if 2 <= len(words) <= 4:
                # Check that words look like capitalized name tokens
                if all(w[0].isupper() or w.isalpha() for w in words):
                    return line.strip()

        # Fallback: Derive plausible name from filename (e.g. "John_Doe_CV.pdf" -> "John Doe")
        stem = Path(filename).stem
        cleaned_stem = re.sub(r"(?i)[-_]?(cv|resume|profile|updated|202[0-9])", "", stem)
        cleaned_stem = re.sub(r"[-_.]+", " ", cleaned_stem).strip()
        words = cleaned_stem.split()
        if 2 <= len(words) <= 4 and all(w.isalpha() for w in words):
            return " ".join(w.capitalize() for w in words)

        return lines[0][:40] if lines else "Candidate"

    @staticmethod
    def extract_skills(text: str) -> list[str]:
        """Detects presence of skills from the core skills taxonomy."""
        lower_text = " " + text.lower() + " "
        found_skills: set[str] = set()

        for skill in CORE_SKILLS_TAXONOMY:
            # Word boundary check
            escaped = re.escape(skill)
            if re.search(r"\b" + escaped + r"\b", lower_text):
                found_skills.add(skill)

        # Sort alphabetically for consistency
        return sorted(list(found_skills))

    @staticmethod
    def extract_languages(text: str) -> list[str]:
        """Detects spoken / written languages mentioned in resume."""
        lower_text = " " + text.lower() + " "
        found: set[str] = set()
        for lang in LANGUAGES_TAXONOMY:
            if re.search(r"\b" + re.escape(lang) + r"\b", lower_text):
                found.add(lang.capitalize())
        return sorted(list(found))

    @staticmethod
    def extract_years_of_experience(text: str) -> int:
        """Extracts explicitly stated years of experience."""
        # e.g., "5+ years of experience", "8 years experience"
        match = re.search(r"\b(\d{1,2})\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)\b", text, re.IGNORECASE)
        if match:
            try:
                val = int(match.group(1))
                if 1 <= val <= 40:
                    return val
            except ValueError:
                pass

        # Alternatively, count explicit 4-digit employment date intervals
        years = [int(y) for y in re.findall(r"\b(19\d{2}|20[0-2]\d)\b", text)]
        if len(years) >= 2:
            span = max(years) - min(years)
            if 1 <= span <= 35:
                return span
        return 0

    @staticmethod
    def extract_location(text: str) -> str:
        """Extracts common location indicators or remote tags."""
        patterns = [
            r"\b(Remote|Hybrid|On-site)\b",
            r"\b(United States|USA|US|Canada|United Kingdom|UK|Germany|India|Brazil|Poland|Ukraine|France|Spain|Australia)\b",
            r"\b(San Francisco|New York|Austin|Seattle|London|Berlin|Toronto|Bangalore|Bengaluru)\b"
        ]
        for p in patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return "Unknown"

    @staticmethod
    def compute_confidence(res: ParsedCV) -> float:
        """Calculates deterministic parsing confidence score between 0.0 and 1.0."""
        score = 0.0
        if res.email:
            score += 0.35
        if res.name and res.name != "Candidate":
            score += 0.25
        if len(res.skills) >= 3:
            score += 0.20
        elif len(res.skills) >= 1:
            score += 0.10
        if res.years_of_experience > 0:
            score += 0.10
        if res.phone:
            score += 0.10
        return min(1.0, round(score, 2))


cv_parser = CVParser()
