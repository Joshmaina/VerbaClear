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

    BUILTIN_PACK_IDS = {"pack_fintech", "pack_medical", "pack_legal", "pack_ai"}

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
                "isCustom": pack_id not in self.BUILTIN_PACK_IDS,
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

    def create_custom_pack(self, pack_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates, persists to disk as JSON, and seeds a new context pack into SQLite.
        """
        raw_id = pack_data.get("id", "").strip().lower()
        if not raw_id:
            raw_id = pack_data.get("name", "custom").strip().lower()

        # Sanitize ID
        clean_id = "".join(c if c.isalnum() or c == "_" else "_" for c in raw_id)
        while "__" in clean_id:
            clean_id = clean_id.replace("__", "_")
        clean_id = clean_id.strip("_")
        if not clean_id.startswith("pack_"):
            clean_id = f"pack_{clean_id}"

        name = pack_data.get("name", "").strip() or clean_id.replace("pack_", "").title()
        badge = pack_data.get("badge", "").strip() or clean_id.replace("pack_", "").title()[:12]
        description = pack_data.get("description", "").strip()
        version = pack_data.get("version", "1.0.0")
        entries = pack_data.get("entries", [])

        if not entries:
            raise ValueError("Context pack must contain at least 1 vocabulary entry.")

        # Ensure directory exists
        self.packs_dir.mkdir(parents=True, exist_ok=True)

        final_pack = {
            "id": clean_id,
            "name": name,
            "version": version,
            "badge": badge,
            "description": description,
            "entries": entries,
        }

        # Write to JSON file
        json_path = self.packs_dir / f"{clean_id.replace('pack_', '')}.json"
        json_path.write_text(json.dumps(final_pack, indent=2, ensure_ascii=False), encoding="utf-8")

        # Register in memory and database
        self._packs[clean_id] = final_pack
        self._seed_pack_to_db(final_pack)

        logger.info("Successfully created custom context pack: %s (%d entries)", clean_id, len(entries))
        return {
            "id": clean_id,
            "name": name,
            "badge": badge,
            "version": version,
            "description": description,
            "entryCount": len(entries),
            "isActive": (self._active_pack_id == clean_id),
            "isCustom": True,
        }

    def import_from_csv(
        self,
        csv_content: str,
        pack_id: str,
        name: str,
        badge: str,
        description: str = "",
    ) -> Dict[str, Any]:
        """
        Parses CSV/TSV tabular glossary into a structured context pack.
        Supports columns: term, simplified_synonym, domain_definition, [phonetic_ipa], [part_of_speech]
        """
        import csv
        import io

        lines = [line.strip() for line in csv_content.splitlines() if line.strip()]
        if not lines:
            raise ValueError("CSV content is empty")

        sample = "\n".join(lines[:5])
        delimiter = "\t" if "\t" in sample and "," not in sample else ","

        reader = csv.reader(io.StringIO(csv_content), delimiter=delimiter)
        rows = [r for r in reader if r and any(cell.strip() for cell in r)]
        if not rows:
            raise ValueError("No valid rows found in CSV")

        # Check for header
        first_row = [c.strip().lower() for c in rows[0]]
        has_header = False
        term_idx, syn_idx, def_idx, ipa_idx, pos_idx = 0, 1, 2, -1, -1

        if any(h in first_row for h in ("term", "word", "headword")):
            has_header = True
            for i, raw_col in enumerate(first_row):
                col = raw_col.replace(" ", "_").replace("-", "_")
                if col in ("term", "word", "headword"):
                    term_idx = i
                elif col in ("synonym", "synonyms", "simplified_synonym", "simplified"):
                    syn_idx = i
                elif col in ("definition", "domain_definition", "meaning"):
                    def_idx = i
                elif col in ("phonetic", "phonetic_ipa", "ipa", "pronunciation"):
                    ipa_idx = i
                elif col in ("pos", "part_of_speech", "type"):
                    pos_idx = i

        data_rows = rows[1:] if has_header else rows
        entries = []
        for r in data_rows:
            if len(r) <= max(term_idx, syn_idx, def_idx):
                continue
            term = r[term_idx].strip()
            syn = r[syn_idx].strip()
            definition = r[def_idx].strip()
            if not term or not syn or not definition:
                continue

            ipa = r[ipa_idx].strip() if ipa_idx != -1 and len(r) > ipa_idx else None
            pos = r[pos_idx].strip().lower() if pos_idx != -1 and len(r) > pos_idx else "noun"

            entries.append({
                "term": term,
                "abbreviation": None,
                "domain_definition": definition,
                "simplified_synonym": syn,
                "phonetic_ipa": ipa or None,
                "part_of_speech": pos or "noun",
            })

        if not entries:
            raise ValueError("Could not extract valid entries from CSV. Expected columns: Term, Simplified Synonym, Definition.")

        pack_dict = {
            "id": pack_id,
            "name": name,
            "version": "1.0.0",
            "badge": badge,
            "description": description,
            "entries": entries,
        }
        return self.create_custom_pack(pack_dict)

    def delete_pack(self, pack_id: str) -> bool:
        """
        Deletes a custom context pack from disk and SQLite.
        Built-in system packs cannot be deleted.
        """
        if pack_id in self.BUILTIN_PACK_IDS:
            logger.warning("Attempted to delete built-in system pack: %s", pack_id)
            return False

        if pack_id not in self._packs:
            logger.warning("Context pack not found for deletion: %s", pack_id)
            return False

        # Deactivate first if currently active
        if self._active_pack_id == pack_id:
            self.activate_pack(None)

        # Remove from database
        with self.repo._get_connection() as conn:
            conn.execute("DELETE FROM context_pack_entries WHERE pack_id = ?", (pack_id,))
            conn.execute("DELETE FROM context_packs WHERE id = ?", (pack_id,))
            conn.commit()

        # Remove JSON file from disk if present
        for json_file in self.packs_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if data.get("id") == pack_id:
                    json_file.unlink(missing_ok=True)
                    break
            except Exception:
                pass

        self._packs.pop(pack_id, None)
        logger.info("Deleted context pack: %s", pack_id)
        return True
