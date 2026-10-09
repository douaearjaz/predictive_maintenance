"""
academic_corpus_collector.py

Phase 1 : Corpus scientifique structuré via APIs académiques légitimes
    - OpenAlex API (pas de clé requise, "polite pool" via email)
    - Semantic Scholar API (pas de clé requise pour usage léger)
    - arXiv API (flux Atom/XML, pas de clé requise)

Phase 2 : Documents métier (manuels, FMEA, rapports de défaillance)
    - Recherche ciblée + FILTRE DE PERTINENCE : un document n'est gardé que
      s'il contient réellement le vocabulaire de panne recherché (bearing,
      wear, vibration, etc.). Objectif = quelques documents riches, pas un
      volume. Un PDF de 50 pages qui ne mentionne aucun de ces termes est
      rejeté automatiquement, même s'il a été trouvé par la recherche.

Sortie : knowledge_base/papers_metadata.json et knowledge_base/phase2_metadata.json
avec titre / résumé / auteurs / DOI / chemin PDF / source pour chaque document.
"""

import hashlib
import json
import logging
import random
import re
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

try:
    from pypdf import PdfReader
except ImportError:
    from PyPDF2 import PdfReader  # fallback selon l'environnement

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("academic_collector")


# =====================================================================
# CONFIGURATION
# =====================================================================

@dataclass
class Config:
    base_dir: Path = Path("knowledge_base")
    contact_email: str = "your_email@example.com"  # pour le "polite pool" OpenAlex

    # Phase 1 : peu de résultats par topic et par source -> qualité > volume
    papers_per_topic_per_source: int = 5

    # Phase 2
    max_results_per_query: int = 10
    max_documents_kept_per_category: int = 6   # objectif : quelques docs RICHES
    min_keyword_hits_to_keep: int = 3           # filtre de pertinence
    respect_robots_txt: bool = True

    request_timeout: int = 30
    max_retries: int = 3
    min_pdf_size_bytes: int = 5_000
    max_pdf_size_bytes: int = 60_000_000
    delay_between_requests: tuple = (1.5, 3.0)

    user_agent: str = "Mozilla/5.0 (compatible; ResearchCollectorBot/1.0; academic research)"


TOPICS = [
    # Bearings
    "bearing failure analysis",
    "bearing wear mechanisms",
    "bearing lubrication failure",
    "bearing fault diagnosis",

    # Rotating machinery
    "rotating machinery failure analysis",
    "rotating equipment maintenance",
    "shaft misalignment",
    "rotor imbalance",

    # Gearbox
    "gearbox failure analysis",
    "gear wear mechanisms",

    # Electric motors
    "electric motor failure analysis",
    "motor overheating",
    "motor vibration analysis",
    "motor insulation degradation",

    # Reliability
    "root cause failure analysis",
    "equipment reliability analysis",

    # FMEA
    "FMEA bearing failure",
    "FMEA electric motor",
    "failure mode effect analysis maintenance"
]

CATEGORY_RULES = {
    "bearings": ["bearing"],
    "motors": ["motor", "electric motor", "induction motor"],
    "gearboxes": ["gearbox", "gear"],
    "fmea": ["fmea", "failure mode effect analysis"],
    "reliability": ["reliability", "root cause"],
    "ontology": ["ontology", "knowledge graph"]
}

# Phase 2 : requêtes volontairement ciblées et peu nombreuses
PHASE2_QUERIES = {
    "manuals": [
        "industrial motor maintenance manual filetype:pdf",
        "compressor maintenance manual bearing lubrication filetype:pdf",
    ],
    "fmea": [
        "bearing FMEA failure mode effects analysis filetype:pdf",
        "rotating machinery FMEA vibration filetype:pdf",
    ],
    "failure_reports": [
        "bearing failure analysis report vibration misalignment filetype:pdf",
        "motor failure root cause analysis overheating filetype:pdf",
    ],
}

# Vocabulaire cible : un document n'est gardé que s'il en contient assez.
# C'est ce qui garantit "peu mais riche" plutôt qu'un volume de PDFs vagues.
RELEVANCE_KEYWORDS = [
    "bearing", "wear", "vibration", "overheating", "lubrication",
    "misalignment", "failure mode", "root cause", "corrective action",
    "corrosion", "fatigue", "crack", "imbalance", "backlash",
    "seal", "gasket", "friction", "degradation",
]


# =====================================================================
# UTILITAIRES PARTAGÉS
# =====================================================================

_robots_cache: dict = {}


def can_fetch(url: str, user_agent: str) -> bool:
    domain = urlparse(url).netloc
    if domain not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"https://{domain}/robots.txt")
        try:
            rp.read()
            _robots_cache[domain] = rp
        except Exception:
            _robots_cache[domain] = None
            return True
    rp = _robots_cache[domain]
    if rp is None:
        return True
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


def clean_filename(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\s]+', '_', text)
    return text[:150] or "document"


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_valid_pdf(content: bytes) -> bool:
    return content[:5] == b"%PDF-"


def normalize_title(title: str) -> str:
    """Pour dédupliquer les papiers trouvés via plusieurs APIs (pas toujours de DOI commun)."""
    t = re.sub(r'[^a-z0-9\s]', '', title.lower())
    return re.sub(r'\s+', ' ', t).strip()


def detect_category(title: str) -> str:
    title = title.lower()
    for category, keywords in CATEGORY_RULES.items():
        for kw in keywords:
            if kw in title:
                return category
    return "misc"


def download_pdf(session: requests.Session, url: str, save_path: Path, cfg: Config) -> Optional[str]:
    """Télécharge + valide un PDF. Retourne le hash SHA256 si succès."""
    if cfg.respect_robots_txt and not can_fetch(url, cfg.user_agent):
        logger.info(f"robots.txt interdit: {url}")
        return None

    for attempt in range(1, cfg.max_retries + 1):
        try:
            resp = requests.get(url, timeout=cfg.request_timeout,
                                headers={"User-Agent": cfg.user_agent}, stream=True)
            if resp.status_code == 429:
                wait = 2 ** attempt + random.uniform(0, 2)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                return None

            content = resp.content
            if not (cfg.min_pdf_size_bytes <= len(content) <= cfg.max_pdf_size_bytes):
                return None
            if not is_valid_pdf(content):
                return None

            save_path.write_bytes(content)
            return sha256_of_bytes(content)

        except requests.exceptions.RequestException as e:
            wait = (2 ** attempt) + random.uniform(0, 1.5)
            logger.warning(f"Tentative {attempt}/{cfg.max_retries} échouée pour {url}: {e}")
            time.sleep(wait)

    return None


def score_pdf_relevance(pdf_path: Path, keywords: list) -> tuple:
    """Extrait le texte et compte combien de mots-clés DISTINCTS du vocabulaire
    de panne apparaissent. C'est le filtre qui garantit qu'on garde seulement
    des documents réellement riches en connaissance métier exploitable."""
    try:
        reader = PdfReader(str(pdf_path))
        text = ""
        for page in reader.pages[:20]:  # limite pour la vitesse sur gros PDFs
            text += (page.extract_text() or "")
        text_lower = text.lower()
    except Exception as e:
        logger.warning(f"Extraction texte échouée pour {pdf_path.name}: {e}")
        return 0, []

    hits = [kw for kw in keywords if kw.lower() in text_lower]
    return len(hits), hits


# =====================================================================
# PHASE 1a : OpenAlex API
# =====================================================================

def openalex_search(topic: str, cfg: Config) -> list:
    url = "https://api.openalex.org/works"
    params = {
        "search": topic,
        "per_page": cfg.papers_per_topic_per_source,
        "sort": "relevance_score:desc",
        "mailto": cfg.contact_email,
    }
    try:
        resp = requests.get(url, params=params, timeout=cfg.request_timeout)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        logger.error(f"OpenAlex échec pour '{topic}': {e}")
        return []


def reconstruct_abstract_from_inverted_index(inverted_index: Optional[dict]) -> str:
    """OpenAlex ne fournit pas l'abstract en texte brut mais en index inversé
    {mot: [positions]} pour des raisons de droits d'auteur sur les résumés.
    On doit le reconstruire."""
    if not inverted_index:
        return ""
    position_word = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_word[pos] = word
    return " ".join(position_word[i] for i in sorted(position_word))


def parse_openalex_record(record: dict, topic: str) -> dict:
    authors = [
        a.get("author", {}).get("display_name", "")
        for a in record.get("authorships", [])
    ]
    pdf_url = None
    best_oa = record.get("best_oa_location") or {}
    if best_oa.get("pdf_url"):
        pdf_url = best_oa["pdf_url"]
    elif record.get("open_access", {}).get("oa_url"):
        pdf_url = record["open_access"]["oa_url"]

    return {
        "source": "openalex",
        "topic": topic,
        "title": record.get("title") or "",
        "abstract": reconstruct_abstract_from_inverted_index(record.get("abstract_inverted_index")),
        "authors": authors,
        "doi": record.get("doi"),
        "year": record.get("publication_year"),
        "pdf_url": pdf_url,
    }


# =====================================================================
# PHASE 1b : Semantic Scholar API
# =====================================================================

def semantic_scholar_search(topic: str, cfg: Config) -> list:
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": topic,
        "limit": cfg.papers_per_topic_per_source,
        "fields": "title,abstract,authors,externalIds,openAccessPdf,year",
    }
    try:
        resp = requests.get(url, params=params, timeout=cfg.request_timeout)
        if resp.status_code == 429:
            logger.warning("Semantic Scholar rate-limited, pause 10s")
            time.sleep(10)
            resp = requests.get(url, params=params, timeout=cfg.request_timeout)
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        logger.error(f"Semantic Scholar échec pour '{topic}': {e}")
        return []


def parse_semantic_scholar_record(record: dict, topic: str) -> dict:
    oa_pdf = record.get("openAccessPdf") or {}
    return {
        "source": "semantic_scholar",
        "topic": topic,
        "title": record.get("title") or "",
        "abstract": record.get("abstract") or "",
        "authors": [a.get("name", "") for a in record.get("authors", [])],
        "doi": (record.get("externalIds") or {}).get("DOI"),
        "year": record.get("year"),
        "pdf_url": oa_pdf.get("url"),
    }


# =====================================================================
# PHASE 1c : arXiv API
# =====================================================================

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def arxiv_search(topic: str, cfg: Config) -> str:
    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f'all:"{topic}"',
        "start": 0,
        "max_results": cfg.papers_per_topic_per_source,
    }
    try:
        resp = requests.get(url, params=params, timeout=cfg.request_timeout)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.error(f"arXiv échec pour '{topic}': {e}")
        return ""


def parse_arxiv_response(xml_text: str, topic: str) -> list:
    if not xml_text:
        return []
    results = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"XML arXiv invalide: {e}")
        return []

    for entry in root.findall("atom:entry", ARXIV_NS):
        title_el = entry.find("atom:title", ARXIV_NS)
        summary_el = entry.find("atom:summary", ARXIV_NS)
        authors = [
            a.findtext("atom:name", default="", namespaces=ARXIV_NS)
            for a in entry.findall("atom:author", ARXIV_NS)
        ]
        pdf_url = None
        for link in entry.findall("atom:link", ARXIV_NS):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href")
                break

        doi_el = entry.find("arxiv:doi", ARXIV_NS)

        results.append({
            "source": "arxiv",
            "topic": topic,
            "title": (title_el.text or "").strip().replace("\n", " ") if title_el is not None else "",
            "abstract": (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else "",
            "authors": authors,
            "doi": doi_el.text if doi_el is not None else None,
            "year": None,
            "pdf_url": pdf_url,
        })
    return results


# =====================================================================
# DÉDUPLICATION ET FUSION DES 3 SOURCES
# =====================================================================

def dedup_papers(papers: list) -> list:
    seen_dois, seen_titles, deduped = set(), set(), []
    for p in papers:
        doi = (p.get("doi") or "").lower().strip()
        norm_title = normalize_title(p.get("title", ""))

        if doi and doi in seen_dois:
            continue
        if not doi and norm_title in seen_titles:
            continue

        if doi:
            seen_dois.add(doi)
        seen_titles.add(norm_title)
        deduped.append(p)
    return deduped


# =====================================================================
# ORCHESTRATION PHASE 1
# =====================================================================
CATEGORY_RULES = {
    "bearings": [
        "bearing"
    ],

    "motors": [
        "motor",
        "electric motor",
        "induction motor"
    ],

    "gearboxes": [
        "gearbox",
        "gear"
    ],

    "fmea": [
        "fmea",
        "failure mode effect analysis"
    ],

    "reliability": [
        "reliability",
        "root cause"
    ],

    "ontology": [
        "ontology",
        "knowledge graph"
    ]
}


def detect_category(title: str) -> str:

    title = title.lower()

    for category, keywords in CATEGORY_RULES.items():

        for kw in keywords:

            if kw in title:
                return category

    return "misc"

def run_phase1(cfg: Config) -> list:

    papers_root = cfg.base_dir / "papers"
    papers_root.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    all_papers = []

    for topic in TOPICS:

        logger.info(f"--- Topic: {topic} ---")

        oa_records = [
            parse_openalex_record(r, topic)
            for r in openalex_search(topic, cfg)
        ]

        time.sleep(random.uniform(*cfg.delay_between_requests))

        ss_records = [
            parse_semantic_scholar_record(r, topic)
            for r in semantic_scholar_search(topic, cfg)
        ]

        time.sleep(random.uniform(*cfg.delay_between_requests))

        arxiv_records = parse_arxiv_response(
            arxiv_search(topic, cfg),
            topic
        )

        time.sleep(random.uniform(*cfg.delay_between_requests))

        all_papers.extend(
            oa_records +
            ss_records +
            arxiv_records
        )

    all_papers = dedup_papers(all_papers)

    logger.info(
        f"Total après déduplication: {len(all_papers)} papiers uniques."
    )

    for paper in all_papers:

        if not paper.get("pdf_url"):
            paper["pdf_path"] = None
            continue

        category = detect_category(
            paper["title"]
        )

        paper["category"] = category

        save_dir = papers_root / category

        save_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        filename = (
            clean_filename(
                paper["title"][:80]
            ) + ".pdf"
        )

        save_path = save_dir / filename

        counter = 1

        while save_path.exists():

            save_path = (
                save_dir /
                f"{filename[:-4]}_{counter}.pdf"
            )

            counter += 1

        file_hash = download_pdf(
            session,
            paper["pdf_url"],
            save_path,
            cfg
        )

        if file_hash:

            paper["pdf_path"] = str(save_path)

            paper["sha256"] = file_hash

            logger.info(
                f"PDF téléchargé: {save_path.name}"
            )

        else:

            paper["pdf_path"] = None

        time.sleep(
            random.uniform(
                *cfg.delay_between_requests
            )
        )

    metadata_path = (
        cfg.base_dir /
        "papers_metadata.json"
    )

    metadata_path.write_text(
        json.dumps(
            all_papers,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    logger.info(
        f"Métadonnées Phase 1 sauvegardées: {metadata_path}"
    )

    return all_papers
    papers_root = cfg.base_dir / "papers"
    papers_root.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    all_papers = []
    for topic in TOPICS:
        logger.info(f"--- Topic: {topic} ---")

        oa_records = [parse_openalex_record(r, topic) for r in openalex_search(topic, cfg)]
        time.sleep(random.uniform(*cfg.delay_between_requests))

        ss_records = [parse_semantic_scholar_record(r, topic) for r in semantic_scholar_search(topic, cfg)]
        time.sleep(random.uniform(*cfg.delay_between_requests))

        arxiv_records = parse_arxiv_response(arxiv_search(topic, cfg), topic)
        time.sleep(random.uniform(*cfg.delay_between_requests))

        all_papers.extend(oa_records + ss_records + arxiv_records)

    all_papers = dedup_papers(all_papers)
    logger.info(f"Total après déduplication: {len(all_papers)} papiers uniques.")

    for paper in all_papers:
        if not paper.get("pdf_url"):
            paper["pdf_path"] = None
            continue

        # Détection de catégorie
        category = detect_category(paper["title"])
        paper["category"] = category

        save_dir = papers_root / category
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = clean_filename(paper["title"][:80]) + ".pdf"
        save_path = save_dir / filename

        # Gestion des doublons de noms de fichiers
        counter = 1
        while save_path.exists():
            save_path = save_dir / f"{filename[:-4]}_{counter}.pdf"
            counter += 1

        file_hash = download_pdf(session, paper["pdf_url"], save_path, cfg)
        if file_hash:
            paper["pdf_path"] = str(save_path)
            paper["sha256"] = file_hash
            logger.info(f"PDF téléchargé: {save_path.name}")
        else:
            paper["pdf_path"] = None
        time.sleep(random.uniform(*cfg.delay_between_requests))

    metadata_path = cfg.base_dir / "papers_metadata.json"
    metadata_path.write_text(json.dumps(all_papers, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Métadonnées Phase 1 sauvegardées: {metadata_path}")
    return all_papers


# =====================================================================
# ORCHESTRATION PHASE 2 (avec filtre de pertinence)
# =====================================================================

def run_phase2(cfg: Config) -> list:
    try:
        from googlesearch import search
    except ImportError:
        logger.error("La bibliothèque 'googlesearch-python' n'est pas installée. Phase 2 ignorée.")
        return []

    metadata = []
    session = requests.Session()

    for category, queries in PHASE2_QUERIES.items():
        category_dir = cfg.base_dir / "phase2" / category
        category_dir.mkdir(parents=True, exist_ok=True)
        kept_count = 0

        logger.info(f"=== Phase 2 catégorie: {category} ===")

        for query in queries:
            if kept_count >= cfg.max_documents_kept_per_category:
                break
            try:
                urls = list(search(query, num_results=cfg.max_results_per_query))
            except Exception as e:
                logger.error(f"Recherche échouée pour '{query}': {e}")
                continue

            for url in urls:
                if kept_count >= cfg.max_documents_kept_per_category:
                    break
                if ".pdf" not in url.lower():
                    continue

                tmp_path = category_dir / f"_tmp_{clean_filename(url.split('/')[-1])}"
                if not tmp_path.name.endswith(".pdf"):
                    tmp_path = tmp_path.with_suffix(".pdf")

                file_hash = download_pdf(session, url, tmp_path, cfg)
                if file_hash is None:
                    continue

                # --- FILTRE DE PERTINENCE : le coeur de la demande ---
                # On ne garde le document QUE s'il contient vraiment le
                # vocabulaire de panne recherché.
                n_hits, hits = score_pdf_relevance(tmp_path, RELEVANCE_KEYWORDS)
                if n_hits < cfg.min_keyword_hits_to_keep:
                    logger.info(f"Rejeté (seulement {n_hits} mots-clés trouvés): {url}")
                    tmp_path.unlink(missing_ok=True)
                    continue

                final_path = category_dir / tmp_path.name.replace("_tmp_", "")
                tmp_path.rename(final_path)

                metadata.append({
                    "category": category,
                    "query": query,
                    "url": url,
                    "file": str(final_path),
                    "sha256": file_hash,
                    "relevance_score": n_hits,
                    "matched_keywords": hits,
                })
                kept_count += 1
                logger.info(f"GARDÉ ({n_hits} mots-clés: {hits}): {final_path.name}")

                time.sleep(random.uniform(*cfg.delay_between_requests))

    metadata_path = cfg.base_dir / "phase2_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Métadonnées Phase 2 sauvegardées: {metadata_path} ({len(metadata)} documents riches retenus)")
    return metadata


# =====================================================================
# MAIN
# =====================================================================

def main(run_phase_1: bool = True, run_phase_2: bool = True):
    cfg = Config()
    cfg.base_dir.mkdir(parents=True, exist_ok=True)

    if run_phase_1:
        logger.info("########## PHASE 1 : Corpus scientifique ##########")
        run_phase1(cfg)

    if run_phase_2:
        logger.info("########## PHASE 2 : Documents métier ##########")
        run_phase2(cfg)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["1", "2", "all"], default="all")
    args = parser.parse_args()

    main(
        run_phase_1=args.phase in ("1", "all"),
        run_phase_2=args.phase in ("2", "all"),
    )