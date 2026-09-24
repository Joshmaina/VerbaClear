"""
Domain Context Pack Manager for VerbaClear.
Loads, validates, and seeds specialized glossaries (FinTech, Biomedical, Legal, AI)
into the embedded SQLite WAL lexicon for real-time vocabulary overrides.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.infrastructure.storage.sqlite_lexicon import SQLiteLexiconRepository

logger = logging.getLogger(__name__)

DEFAULT_PACKS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "packs"


class ContextPackManager:
    """
    Manages Tier 2/3 domain glossaries.
    Provides sub-millisecond retrieval and on-the-fly pack switching during live events.
    """

    def __init__(
        self,
        repo: Optional[SQLiteLexiconRepository] = None,
        packs_dir: Optional[Path] = None,
    ):
        self.repo = repo or SQLiteLexiconRepository()
        self.packs_dir = packs_dir or DEFAULT_PACKS_DIR
        self._packs: Dict[str, Dict[str, Any]] = {}
        self._active_pack_id: Optional[str] = None

        self.reload_and_seed()

    def reload_and_seed(self) -> None:
        """Discovers JSON pack files on disk and seeds them into SQLite."""
        self._packs.clear()

        if not self.packs_dir.exists():
            logger.warning("Packs directory does not exist: %s", self.packs_dir)
            return

        for json_file in sorted(self.packs_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                pack_id = data.get("id")
                if not pack_id:
                    continue

                self._packs[pack_id] = data
                self._seed_pack_to_db(data)
                logger.info(
                    "Loaded context pack '%s' (%s) with %d entries.",
                    data.get("name"),
                    pack_id,
                    len(data.get("entries", [])),
                )
            except Exception as e:
                logger.error("Failed to parse pack file %s: %s", json_file.name, e)

    def _seed_pack_to_db(self, pack: Dict[str, Any]) -> None:
        """Inserts or replaces pack records in SQLite context_packs & context_pack_entries."""
        pack_id = pack["id"]
        pack_name = pack.get("name", pack_id)
        version = pack.get("version", "1.0.0")

        with self.repo._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO context_packs (id, pack_name, version, is_active)
                VALUES (?, ?, ?, COALESCE((SELECT is_active FROM context_packs WHERE id = ?), 0))
                """,
                (pack_id, pack_name, version, pack_id),
            )

            # Insert/replace entries
            for entry in pack.get("entries", []):
                term = entry["term"].strip().lower()
                abbrev = entry.get("abbreviation")
                definition = entry["domain_definition"]
                synonym = entry["simplified_synonym"]
                phonetic = entry.get("phonetic_ipa")
                pos = entry.get("part_of_speech", "noun")

                # Ensure entry exists
                cursor.execute(
                    """
                    SELECT id FROM context_pack_entries
                    WHERE pack_id = ? AND LOWER(term) = ?
                    """,
                    (pack_id, term),
                )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """
                        UPDATE context_pack_entries
                        SET abbreviation = ?, domain_definition = ?, simplified_synonym = ?,
                            phonetic_ipa = ?, part_of_speech = ?
                        WHERE id = ?
                        """,
                        (abbrev, definition, synonym, phonetic, pos, existing["id"]),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO context_pack_entries (
                            pack_id, term, abbreviation, domain_definition, simplified_synonym,
                            phonetic_ipa, part_of_speech
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (pack_id, term, abbrev, definition, synonym, phonetic, pos),
                    )

            conn.commit()

    def list_packs(self) -> List[Dict[str, Any]]:
        """Returns metadata for all available context packs."""
        pack_list = []
        for pack_id, pack in self._packs.items():
            pack_list.append({
                "id": pack_id,
                "name": pack.get("name", pack_id),
                "badge": pack.get("badge", "Domain"),
                "version": pack.get("version", "1.0.0"),
                "description": pack.get("description", ""),
                "entryCount": len(pack.get("entries", [])),
                "isActive": (self._active_pack_id == pack_id),
            })
        return pack_list

    def get_pack(self, pack_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves raw pack data by ID."""
        return self._packs.get(pack_id)

    @property
    def active_pack_id(self) -> Optional[str]:
        return self._active_pack_id

    @property
    def active_pack_badge(self) -> str:
        if not self._active_pack_id or self._active_pack_id not in self._packs:
            return "General"
        return self._packs[self._active_pack_id].get("badge", "Domain")

    def activate_pack(self, pack_id: Optional[str]) -> bool:
        """
        Activates a context pack by ID. If pack_id is None or empty, deactivates active pack.
        Returns True if successful, False if pack_id not found.
        """
        if not pack_id or pack_id.lower() in ["none", "general", ""]:
            self._active_pack_id = None
            with self.repo._get_connection() as conn:
                conn.execute("UPDATE context_packs SET is_active = 0")
                conn.commit()
            logger.info("Deactivated all domain context packs (reverted to General).")
            return True

        # Find matching pack (exact ID or name/substring match)
        target_id = None
        for pid, pdata in self._packs.items():
            if pid == pack_id or pid.lower() == pack_id.lower() or pack_id.lower() in pdata.get("name", "").lower():
                target_id = pid
                break

        if not target_id:
            logger.warning("Attempted to activate unknown pack: %s", pack_id)
            return False

        self._active_pack_id = target_id

        with self.repo._get_connection() as conn:
            conn.execute("UPDATE context_packs SET is_active = 0")
            conn.execute("UPDATE context_packs SET is_active = 1 WHERE id = ?", (target_id,))
            conn.commit()

        logger.info("Activated context pack: %s (%s)", target_id, self._packs[target_id].get("name"))
        return True
