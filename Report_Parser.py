"""
report_parser.py

Splits the CPG market intelligence agent's markdown response into named
sections (Executive Summary, Portfolio Comparison, Market Trends, etc.),
detects whether it's a single-brand or multi-brand (portfolio) report, and
renders it in Streamlit as tabs -- with the portfolio ranking table (if
present) parsed into a real, sortable dataframe instead of raw markdown.

This is intentionally a best-effort TEXT parser, not a strict schema: the
underlying agent is an LLM writing markdown, not a structured API, so
headers can vary in exact wording/formatting between runs. The parser is
lenient (case-insensitive, tolerates "##", "**", "1.", or a bare line as a
heading style) and always falls back gracefully -- if it can't confidently
identify sections, it just shows the raw markdown rather than guessing
wrong. Same idea for the ranking table: if no clean markdown table is
found, the Portfolio Comparison text still displays, just without the
dataframe.

If your reporting_agent's actual output headings drift from the ones in
KNOWN_SECTIONS below (e.g. you edit its instructions later), add the new
wording as an alias in KNOWN_SECTIONS rather than changing calling code.
"""

import io
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

# Canonical section name -> list of header phrasings the LLM might use for it.
# Matching is case-insensitive and tolerant of leading numbers/markdown
# markup (see _normalize_heading_candidate below).
KNOWN_SECTIONS: Dict[str, List[str]] = {
    "Executive Summary": ["executive summary", "summary"],
    "Portfolio Comparison": ["portfolio comparison", "portfolio-level comparison", "brand comparison"],
    "Market Trends": ["market trends", "market trend analysis"],
    "Customer Feedback": ["customer feedback", "feedback analysis", "customer sentiment"],
    "Competitive Landscape": ["competitive landscape", "competitive intelligence", "competitor activity"],
    "Per-Brand Sections": ["per-brand sections", "per brand sections", "brand-by-brand", "per-brand analysis"],
    "Recommended Actions": ["recommended actions", "recommendations"],
}

# Order sections should appear in the UI, regardless of the order the LLM
# happened to write them in.
SECTION_ORDER = [
    "Executive Summary",
    "Portfolio Comparison",
    "Per-Brand Sections",
    "Market Trends",
    "Customer Feedback",
    "Competitive Landscape",
    "Recommended Actions",
]

# A line is considered a potential heading if it's short and matches one of
# these structural patterns (markdown heading, bold text, or a numbered
# list item), OR is a bare line whose normalized text exactly matches a
# known section alias.
_HEADING_PATTERNS = [
    re.compile(r"^\s{0,3}#{1,3}\s*(.+?)\s*#*\s*$"),          # "## Executive Summary"
    re.compile(r"^\s{0,3}\*\*(.+?)\*\*\s*:?\s*$"),            # "**Executive Summary**"
    re.compile(r"^\s{0,3}\d+[\.\)]\s*\*{0,2}(.+?)\*{0,2}\s*:?\s*$"),  # "1. Executive Summary"
]


def _normalize_heading_candidate(line: str) -> Optional[str]:
    """Extracts the heading text from a line if it looks like a heading."""
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return None
    for pattern in _HEADING_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return match.group(1).strip()
    return None


def _match_known_section(candidate: str) -> Optional[str]:
    """Maps a heading candidate string to a canonical section name, if it matches."""
    normalized = candidate.strip().lower().rstrip(":")
    for canonical, aliases in KNOWN_SECTIONS.items():
        if normalized in aliases:
            return canonical
    return None


def parse_report_sections(text: str) -> Tuple[Dict[str, str], str]:
    """
    Splits `text` into {canonical_section_name: content}. Any text before
    the first recognized heading is returned separately as `preamble`.
    Sections not found in the text simply won't be keys in the result --
    callers should check membership, not assume all of SECTION_ORDER exists.
    """
    lines = text.splitlines()
    sections: Dict[str, List[str]] = {}
    preamble_lines: List[str] = []
    current_section: Optional[str] = None

    for line in lines:
        candidate = _normalize_heading_candidate(line)
        matched = _match_known_section(candidate) if candidate else None

        if matched:
            current_section = matched
            sections.setdefault(current_section, [])
            continue

        if current_section is None:
            preamble_lines.append(line)
        else:
            sections[current_section].append(line)

    joined_sections = {k: "\n".join(v).strip() for k, v in sections.items()}
    preamble = "\n".join(preamble_lines).strip()
    return joined_sections, preamble


def extract_markdown_table(text: str) -> Optional[pd.DataFrame]:
    """
    Finds the first GitHub-flavored markdown pipe table in `text` and
    parses it into a DataFrame. Returns None if no clean table is found --
    callers should fall back to displaying the raw text in that case.
    """
    lines = text.splitlines()
    table_lines: List[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        is_table_row = stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3
        is_separator_row = bool(re.match(r"^\|?[\s:\-|]+\|?$", stripped)) and "-" in stripped

        if is_table_row or (in_table and is_separator_row):
            table_lines.append(stripped)
            in_table = True
        elif in_table:
            # First non-table line after a table started -- table has ended.
            break

    if len(table_lines) < 2:
        return None

    try:
        # Drop the markdown separator row (the "---|---|---" line).
        data_rows = [row for row in table_lines if not re.match(r"^\|?[\s:\-|]+\|?$", row)]
        csv_text = "\n".join(
            "|".join(cell.strip() for cell in row.strip("|").split("|")) for row in data_rows
        )
        df = pd.read_csv(io.StringIO(csv_text), sep="|")
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception:
        return None


def detect_report_type(sections: Dict[str, str]) -> str:
    """Returns 'portfolio' if a Portfolio Comparison section was found, else 'single'."""
    return "portfolio" if sections.get("Portfolio Comparison") else "single"


def split_per_brand_subsections(text: str, known_brands: Optional[List[str]] = None) -> Dict[str, str]:
    """
    Best-effort split of the "Per-Brand Sections" block into one chunk per
    brand, using `known_brands` (if provided) to recognize where each
    brand's subsection starts. If no brand names are provided or none are
    found as headings, returns {"All Brands": text} so the caller can still
    render *something* rather than nothing.
    """
    if not known_brands:
        return {"All Brands": text} if text else {}

    lines = text.splitlines()
    chunks: Dict[str, List[str]] = {}
    current_brand: Optional[str] = None

    brand_lookup = {b.strip().lower(): b.strip() for b in known_brands}

    for line in lines:
        candidate = _normalize_heading_candidate(line) or line.strip().rstrip(":")
        normalized = candidate.strip().lower() if candidate else ""
        if normalized in brand_lookup:
            current_brand = brand_lookup[normalized]
            chunks.setdefault(current_brand, [])
            continue
        if current_brand:
            chunks[current_brand].append(line)
        # Lines before any recognized brand heading are dropped silently --
        # typically just blank lines between the section title and the
        # first brand.

    joined = {k: "\n".join(v).strip() for k, v in chunks.items() if "\n".join(v).strip()}
    return joined if joined else {"All Brands": text}


def render_structured_report(text: str, known_brands: Optional[List[str]] = None) -> None:
    """
    Main entry point: parses `text` and renders it in Streamlit as tabs.
    Always also offers a "Raw report text" expander as a safety net, in
    case the parser missed something the user needs to see verbatim.
    """
    sections, preamble = parse_report_sections(text)

    if not sections:
        # Parsing didn't recognize any known section headings at all --
        # don't guess, just show the plain response.
        st.markdown(text)
        return

    report_type = detect_report_type(sections)
    tab_titles = [preamble and "Overview" or None]
    tab_titles = [t for t in tab_titles if t]  # drop None if no preamble
    ordered_present_sections = [s for s in SECTION_ORDER if s in sections]
    tab_titles += ordered_present_sections

    if not tab_titles:
        st.markdown(text)
        return

    badge = "📊 Portfolio report" if report_type == "portfolio" else "🏷️ Single-brand report"
    st.caption(badge)

    tabs = st.tabs(tab_titles)
    tab_index = 0

    if preamble:
        with tabs[tab_index]:
            st.markdown(preamble)
        tab_index += 1

    for section_name in ordered_present_sections:
        with tabs[tab_index]:
            content = sections[section_name]

            if section_name == "Portfolio Comparison":
                table_df = extract_markdown_table(content)
                if table_df is not None:
                    st.dataframe(table_df, use_container_width=True, hide_index=True)
                    st.caption(
                        "Rankings are based on search-interest and social-volume proxies, "
                        "not verified market-share figures, unless certified data was supplied."
                    )
                    # Show any narrative text that isn't part of the table too.
                    remainder = _strip_table_lines(content)
                    if remainder:
                        st.markdown(remainder)
                else:
                    st.markdown(content)

            elif section_name == "Per-Brand Sections":
                per_brand = split_per_brand_subsections(content, known_brands)
                if len(per_brand) > 1:
                    brand_tabs = st.tabs(list(per_brand.keys()))
                    for brand_tab, (brand_name, brand_text) in zip(brand_tabs, per_brand.items()):
                        with brand_tab:
                            st.markdown(brand_text)
                else:
                    st.markdown(content)

            else:
                st.markdown(content)
        tab_index += 1

    with st.expander("Raw report text"):
        st.markdown(text)


def _strip_table_lines(text: str) -> str:
    """Removes markdown table lines from `text`, leaving any surrounding narrative."""
    lines = text.splitlines()
    kept = [
        line for line in lines
        if not (line.strip().startswith("|") or re.match(r"^\|?[\s:\-|]+\|?$", line.strip()))
    ]
    return "\n".join(kept).strip()