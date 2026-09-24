"""
SQLite Lexicon Repository for VerbaClear.
Implements high-performance local embedded lexicon store in WAL mode
with memory-mapped I/O for sub-millisecond retrieval of curated synonyms and definitions.
"""

import logging
import os
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_SEED_VOCABULARY = [
    {
        "headword": "labyrinthine",
        "part_of_speech": "adjective",
        "phonetic_ipa": "/ˌlæb.əˈrɪn.θaɪn/",
        "definition": "Extremely complex, irregular, or twisting, resembling a maze in structure.",
        "synonyms": [
            ("Highly Complex", 1),
            ("Maze-like", 2),
            ("Twisting", 3),
        ],
    },
    {
        "headword": "obfuscate",
        "part_of_speech": "verb",
        "phonetic_ipa": "/ˈɒb.fʌs.keɪt/",
        "definition": "To make something unclear, obscure, or confusing to understand.",
        "synonyms": [
            ("Confuse", 1),
            ("Make Unclear", 2),
            ("Cloud", 3),
        ],
    },
    {
        "headword": "esoteric",
        "part_of_speech": "adjective",
        "phonetic_ipa": "/ˌes.əˈter.ɪk/",
        "definition": "Intended for or likely to be understood by only a small number of people with specialized knowledge.",
        "synonyms": [
            ("Niche", 1),
            ("Specialized", 2),
            ("Obscure", 3),
        ],
    },
    {
        "headword": "plethora",
        "part_of_speech": "noun",
        "phonetic_ipa": "/ˈpleθ.ər.ə/",
        "definition": "A large or excessive amount of something.",
        "synonyms": [
            ("Abundance", 1),
            ("Excess", 2),
            ("Overload", 3),
        ],
    },
    {
        "headword": "ephemeral",
        "part_of_speech": "adjective",
        "phonetic_ipa": "/ɪˈfem.ər.əl/",
        "definition": "Lasting for a very short, fleeting period of time.",
        "synonyms": [
            ("Short-lived", 1),
            ("Fleeting", 2),
            ("Temporary", 3),
        ],
    },
    {
        "headword": "ubiquitous",
        "part_of_speech": "adjective",
        "phonetic_ipa": "/juːˈbɪk.wɪ.təs/",
        "definition": "Present, appearing, or found everywhere simultaneously.",
        "synonyms": [
            ("Everywhere", 1),
            ("Widespread", 2),
            ("Universal", 3),
        ],
    },
    {
        "headword": "ameliorate",
        "part_of_speech": "verb",
        "phonetic_ipa": "/əˈmiːl.jə.reɪt/",
        "definition": "To make something bad or unsatisfactory better or more tolerable.",
        "synonyms": [
            ("Improve", 1),
            ("Make Better", 2),
            ("Relieve", 3),
        ],
    },
    {
        "headword": "superfluous",
        "part_of_speech": "adjective",
        "phonetic_ipa": "/suːˈpɜː.flu.əs/",
        "definition": "Exceeding what is sufficient, necessary, or useful.",
        "synonyms": [
            ("Unnecessary", 1),
            ("Extra", 2),
            ("Redundant", 3),
        ],
    },
    {
        "headword": "paradigm",
        "part_of_speech": "noun",
        "phonetic_ipa": "/ˈpær.ə.daɪm/",
        "definition": "A typical example, standard model, or overall pattern of something.",
        "synonyms": [
            ("Standard Model", 1),
            ("Pattern", 2),
            ("Framework", 3),
        ],
    },
    {
        "headword": "synergy",
        "part_of_speech": "noun",
        "phonetic_ipa": "/ˈsɪn.ə.dʒi/",
        "definition": "The interaction of elements that when combined produce a total effect greater than the sum of the individual parts.",
        "synonyms": [
            ("Combined Effect", 1),
            ("Teamwork", 2),
            ("Cooperation", 3),
        ],
    },
    {
        "headword": "antithetical",
        "part_of_speech": "adjective",
        "phonetic_ipa": "/ˌæn.tɪˈθet.ɪ.kəl/",
        "definition": "Directly opposed or in stark contrast to something else.",
        "synonyms": [
            ("Direct Opposite", 1),
            ("Contrasting", 2),
            ("Conflicting", 3),
        ],
    },
    {
        "headword": "quintessential",
        "part_of_speech": "adjective",
        "phonetic_ipa": "/ˌkwɪn.tɪˈsen.ʃəl/",
        "definition": "Representing the most perfect or typical example of a quality or class.",
        "synonyms": [
            ("Classic Example", 1),
            ("Archetypal", 2),
            ("Pinnacle", 3),
        ],
    },
]


class SQLiteLexiconRepository:
    """
    Embedded SQLite database manager for vocabulary definitions, phonetics, and curated synonyms.
    Uses Write-Ahead Logging (WAL) and memory-mapped reads for sub-millisecond response times.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = Path.home() / ".cache" / "verbaclear" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(data_dir / "verbaclear_lexicon.db")
        else:
            self.db_path = db_path

        self._init_db()
        self._seed_default_vocabulary()

    def _get_connection(self) -> sqlite3.Connection:
        """Opens a connection with WAL and memory-mapped configuration."""
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA mmap_size = 67108864;")  # 64MB memory-mapped I/O
        return conn

    def _init_db(self) -> None:
        """Initializes relational schema."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS lexicon (
                    id TEXT PRIMARY KEY NOT NULL,
                    headword TEXT NOT NULL UNIQUE,
                    part_of_speech TEXT NOT NULL,
                    phonetic_ipa TEXT,
                    definition TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_lexicon_headword ON lexicon(headword);

                CREATE TABLE IF NOT EXISTS synonyms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lexicon_id TEXT NOT NULL REFERENCES lexicon(id) ON DELETE CASCADE,
                    synonym TEXT NOT NULL,
                    display_priority INTEGER NOT NULL DEFAULT 1,
                    max_words INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_synonyms_lexicon_id ON synonyms(lexicon_id);

                CREATE TABLE IF NOT EXISTS context_packs (
                    id TEXT PRIMARY KEY NOT NULL,
                    pack_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS context_pack_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pack_id TEXT NOT NULL REFERENCES context_packs(id) ON DELETE CASCADE,
                    term TEXT NOT NULL,
                    abbreviation TEXT,
                    domain_definition TEXT NOT NULL,
                    simplified_synonym TEXT NOT NULL,
                    phonetic_ipa TEXT,
                    part_of_speech TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_context_pack_lookup ON context_pack_entries(pack_id, term);
            """)

            # Gracefully apply columns if table already existed without them
            try:
                conn.execute("ALTER TABLE context_pack_entries ADD COLUMN phonetic_ipa TEXT;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE context_pack_entries ADD COLUMN part_of_speech TEXT;")
            except Exception:
                pass

    def _seed_default_vocabulary(self) -> None:
        """Seeds standard advanced vocabulary if not already populated."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for entry in DEFAULT_SEED_VOCABULARY:
                hw = entry["headword"].lower()
                cursor.execute("SELECT id FROM lexicon WHERE headword = ?", (hw,))
                row = cursor.fetchone()
                if not row:
                    lex_id = f"lex_{hw}"
                    cursor.execute(
                        "INSERT INTO lexicon (id, headword, part_of_speech, phonetic_ipa, definition) VALUES (?, ?, ?, ?, ?)",
                        (lex_id, hw, entry["part_of_speech"], entry.get("phonetic_ipa"), entry["definition"]),
                    )
                    for syn, priority in entry.get("synonyms", []):
                        cursor.execute(
                            "INSERT INTO synonyms (lexicon_id, synonym, display_priority, max_words) VALUES (?, ?, ?, ?)",
                            (lex_id, syn, priority, len(syn.split())),
                        )
            conn.commit()

    def get_entry(self, headword: str, active_pack_id: Optional[str] = None) -> Optional[Dict]:
        """
        Sub-millisecond retrieval of definition, phonetics, and punchy synonyms for a headword.
        Checks active domain context pack first, then master lexicon.
        """
        hw = headword.strip().lower()
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Check active context pack if enabled
            if active_pack_id:
                cursor.execute(
                    "SELECT domain_definition, simplified_synonym, phonetic_ipa, part_of_speech FROM context_pack_entries WHERE pack_id = ? AND LOWER(term) = ?",
                    (active_pack_id, hw),
                )
                pack_row = cursor.fetchone()
                if pack_row:
                    return {
                        "headword": hw,
                        "part_of_speech": pack_row["part_of_speech"] or "noun",
                        "phonetic_ipa": pack_row["phonetic_ipa"],
                        "definition": pack_row["domain_definition"],
                        "synonyms": [pack_row["simplified_synonym"]],
                        "source": "context_pack",
                    }

            # 2. Query master lexicon
            cursor.execute(
                "SELECT id, part_of_speech, phonetic_ipa, definition FROM lexicon WHERE headword = ?",
                (hw,),
            )
            lex_row = cursor.fetchone()
            if not lex_row:
                # Dynamic fallback: generate readable placeholder if word is genuinely rare
                return None

            lex_id = lex_row["id"]
            cursor.execute(
                "SELECT synonym FROM synonyms WHERE lexicon_id = ? ORDER BY display_priority ASC LIMIT 3",
                (lex_id,),
            )
            syn_rows = cursor.fetchall()
            synonyms = [r["synonym"] for r in syn_rows]

            return {
                "headword": hw,
                "part_of_speech": lex_row["part_of_speech"],
                "phonetic_ipa": lex_row["phonetic_ipa"],
                "definition": lex_row["definition"],
                "synonyms": synonyms,
                "source": "master_lexicon",
            }

    def resolve_synonyms(self, headword: str, active_pack_id: Optional[str] = None) -> List[str]:
        """Returns 1-3 punchy synonyms for a headword."""
        entry = self.get_entry(headword, active_pack_id)
        if entry and entry.get("synonyms"):
            return entry["synonyms"]
        # Fallback: title-cased capitalized form
        return [headword.replace("-", " ").title()]

    def resolve_definition_and_phonetics(
        self, headword: str, active_pack_id: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """Returns (phonetic_ipa, 1_sentence_definition)."""
        entry = self.get_entry(headword, active_pack_id)
        if entry:
            return entry.get("phonetic_ipa"), entry.get("definition")
        return None, f"Specialized vocabulary term: {headword}."
