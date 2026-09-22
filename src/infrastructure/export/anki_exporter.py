"""
Anki (.apkg), TSV, and CSV Export Engine for VerbaClear.
Generates compliant Anki 2.0/2.1 decks, Anki text files, and CSV files
using Python standard library (sqlite3, zipfile, csv) with zero external dependencies.
"""

import csv
import hashlib
import io
import json
import logging
import os
import sqlite3
import tempfile
import time
from typing import Any, Dict, List, Union
import uuid
import zipfile

from src.domain.models import AudienceCompanionCard

logger = logging.getLogger(__name__)


def _sanitize_card(card: Union[AudienceCompanionCard, Dict[str, Any]]) -> Dict[str, Any]:
    """Normalizes AudienceCompanionCard dataclass or dictionary to a uniform dictionary."""
    if isinstance(card, AudienceCompanionCard):
        return {
            "cardId": card.card_id,
            "word": card.word.title(),
            "partOfSpeech": card.part_of_speech.value if hasattr(card.part_of_speech, "value") else str(card.part_of_speech),
            "phoneticIpa": card.phonetic_ipa or "",
            "synonyms": card.synonyms,
            "definition": card.definition,
            "contextSentence": card.context_sentence,
            "spokenTimeFormatted": card.spoken_time_formatted,
            "domainBadge": card.domain_badge,
        }
    return {
        "cardId": card.get("cardId") or card.get("card_id") or uuid.uuid4().hex[:8],
        "word": str(card.get("word", "")).title(),
        "partOfSpeech": str(card.get("partOfSpeech") or card.get("part_of_speech") or "general"),
        "phoneticIpa": str(card.get("phoneticIpa") or card.get("phonetic_ipa") or ""),
        "synonyms": card.get("synonyms") or [],
        "definition": str(card.get("definition", "")),
        "contextSentence": str(card.get("contextSentence") or card.get("context_sentence") or ""),
        "spokenTimeFormatted": str(card.get("spokenTimeFormatted") or card.get("spoken_time_formatted") or ""),
        "domainBadge": str(card.get("domainBadge") or card.get("domain_badge") or "General"),
    }


def generate_anki_apkg(
    cards: List[Union[AudienceCompanionCard, Dict[str, Any]]],
    deck_name: str = "VerbaClear Event Vocabulary",
) -> bytes:
    """
    Builds a fully compliant Anki package (.apkg) containing collection.anki2
    and media index, loadable directly into Anki Desktop, AnkiDroid, and AnkiMobile.
    """
    normalized_cards = [_sanitize_card(c) for c in cards]
    base_time_s = int(time.time())
    base_time_ms = base_time_s * 1000

    deck_id = 1720000000000 + (base_time_s % 1000000)
    model_id = 1720000000100 + (base_time_s % 1000000)

    # Anki card styling CSS
    card_css = (
        ".card { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "font-size: 19px; text-align: left; color: #0f172a; background-color: #f8fafc; padding: 24px; max-width: 580px; margin: 0 auto; }\n"
        ".word-title { font-size: 32px; font-weight: 800; color: #0284c7; margin-bottom: 6px; }\n"
        ".pos-badge { display: inline-block; font-size: 12px; font-weight: 700; background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; margin-right: 8px; }\n"
        ".phonetic { font-size: 16px; color: #64748b; font-style: italic; }\n"
        ".section-title { font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 16px; margin-bottom: 4px; }\n"
        ".definition-text { font-size: 18px; line-height: 1.5; color: #1e293b; }\n"
        ".synonyms-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }\n"
        ".synonym-item { font-size: 15px; font-weight: 600; color: #0284c7; background: #f0f9ff; border: 1px solid #bae6fd; padding: 2px 10px; border-radius: 6px; }\n"
        ".context-box { font-size: 15px; color: #334155; font-style: italic; background: #e2e8f0; padding: 12px; border-radius: 8px; margin-top: 6px; border-left: 3px solid #0284c7; }\n"
        ".footer { font-size: 11px; color: #94a3b8; margin-top: 20px; border-top: 1px solid #e2e8f0; padding-top: 8px; text-align: right; }"
    )

    models = {
        str(model_id): {
            "id": model_id,
            "name": "VerbaClear Vocabulary Model",
            "type": 0,
            "mod": base_time_s,
            "usn": -1,
            "sortf": 0,
            "did": deck_id,
            "tmpls": [
                {
                    "name": "VerbaClear Prompt",
                    "ord": 0,
                    "qfmt": "{{Front}}",
                    "afmt": "{{FrontSide}}<hr id=\"answer\">{{Back}}",
                    "did": None,
                    "bqfmt": "",
                    "bafmt": "",
                }
            ],
            "flds": [
                {"name": "Front", "ord": 0, "sticky": False, "rtl": False, "font": "Arial", "size": 20, "media": []},
                {"name": "Back", "ord": 1, "sticky": False, "rtl": False, "font": "Arial", "size": 18, "media": []},
            ],
            "css": card_css,
            "latexPre": "\\documentclass[12pt]{article}\n\\special{papersize=3in,5in}\n\\usepackage[utf8]{inputenc}\n\\usepackage{amssymb,amsmath}\n\\pagestyle{empty}\n\\setlength{\\parindent}{0in}\n\\begin{document}\n",
            "latexPost": "\\end{document}",
            "latexsvg": False,
            "req": [[0, "all", [0]]],
        }
    }

    decks = {
        "1": {
            "id": 1,
            "mod": base_time_s,
            "name": "Default",
            "usn": 0,
            "maxTaken": 60,
            "collapsed": False,
            "browserCollapsed": False,
            "desc": "",
            "dyn": 0,
            "conf": 1,
            "extendNew": 10,
            "extendRev": 50,
        },
        str(deck_id): {
            "id": deck_id,
            "mod": base_time_s,
            "name": deck_name,
            "usn": -1,
            "maxTaken": 60,
            "collapsed": False,
            "browserCollapsed": False,
            "desc": f"Vocabulary captured live by VerbaClear during {deck_name}.",
            "dyn": 0,
            "conf": 1,
            "extendNew": 10,
            "extendRev": 50,
        },
    }

    dconf = {
        "1": {
            "id": 1,
            "mod": base_time_s,
            "name": "Default",
            "usn": 0,
            "maxTaken": 60,
            "autoplay": True,
            "timer": 0,
            "replayq": True,
            "new": {"bury": False, "delays": [1, 10], "initialFactor": 2500, "ints": [1, 4, 7], "order": 1, "perDay": 20},
            "rev": {"bury": False, "ease4": 1.3, "ivlFct": 1.0, "maxIvl": 36500, "perDay": 200, "minSpace": 1},
            "lapse": {"delays": [10], "leechAction": 0, "leechFails": 8, "minInt": 1, "mult": 0.0},
        }
    }

    conf = {
        "nextPos": 1,
        "estTimes": True,
        "activeDecks": [1],
        "sortType": "noteFld",
        "timeLim": 0,
        "sortBackwards": False,
        "addToCur": True,
        "curDeck": 1,
        "curModel": model_id,
        "collapseTime": 1200,
    }

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        db_path = tmp_db.name

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # DDL Schema for Anki 2.0/2.1 database
        cur.execute("""
        CREATE TABLE col (
            id integer primary key,
            crt integer,
            mod integer,
            scm integer,
            ver integer,
            dty integer,
            usn integer,
            ls integer,
            conf text,
            models text,
            decks text,
            dconf text,
            tags text
        );
        """)
        cur.execute("""
        CREATE TABLE notes (
            id integer primary key,
            guid text,
            mid integer,
            mod integer,
            usn integer,
            tags text,
            flds text,
            sfld text,
            csum integer,
            flags integer,
            data text
        );
        """)
        cur.execute("""
        CREATE TABLE cards (
            id integer primary key,
            nid integer,
            did integer,
            ord integer,
            mod integer,
            usn integer,
            type integer,
            queue integer,
            due integer,
            ivl integer,
            factor integer,
            reps integer,
            lapses integer,
            left integer,
            odue integer,
            odid integer,
            flags integer,
            data text
        );
        """)
        cur.execute("CREATE TABLE graves (usn integer, oid integer, type integer);")
        cur.execute("CREATE TABLE revlog (id integer primary key, cid integer, usn integer, ease integer, ivl integer, lastIvl integer, factor integer, time integer, type integer);")

        cur.execute(
            "INSERT INTO col VALUES (1, ?, ?, ?, 11, 0, 0, 0, ?, ?, ?, ?, ?)",
            (
                base_time_s,
                base_time_ms,
                base_time_ms,
                json.dumps(conf),
                json.dumps(models),
                json.dumps(decks),
                json.dumps(dconf),
                json.dumps({}),
            ),
        )

        # Insert notes and cards
        for idx, card in enumerate(normalized_cards):
            note_id = base_time_ms + idx
            card_record_id = base_time_ms + 100000 + idx
            guid = uuid.uuid4().hex[:10]

            # Front: Word, Part of speech badge, Phonetic IPA
            phonetic_html = f"<div class=\"phonetic\">{card['phoneticIpa']}</div>" if card["phoneticIpa"] else ""
            pos_html = f"<span class=\"pos-badge\">{card['partOfSpeech']}</span>" if card["partOfSpeech"] else ""
            front_html = (
                f"<div class=\"word-title\">{card['word']}</div>\n"
                f"{pos_html}{phonetic_html}"
            )

            # Back: Synonyms, Definition, Spoken Context Sentence
            synonyms_items = "".join([f"<span class=\"synonym-item\">{syn}</span>" for syn in card["synonyms"]])
            synonyms_html = (
                f"<div class=\"section-title\">Synonyms</div>\n"
                f"<div class=\"synonyms-list\">{synonyms_items}</div>\n"
                if card["synonyms"]
                else ""
            )

            context_html = (
                f"<div class=\"section-title\">Heard in Context</div>\n"
                f"<div class=\"context-box\">\"{card['contextSentence']}\"</div>\n"
                if card["contextSentence"]
                else ""
            )

            back_html = (
                f"<div class=\"section-title\">Definition</div>\n"
                f"<div class=\"definition-text\">{card['definition']}</div>\n"
                f"{synonyms_html}"
                f"{context_html}"
                f"<div class=\"footer\">Captured live by VerbaClear • {card['spokenTimeFormatted']}</div>"
            )

            flds = f"{front_html}\x1f{back_html}"
            csum = int(hashlib.sha1(card["word"].encode("utf-8")).hexdigest()[:8], 16)
            tags = " VerbaClear Event "

            cur.execute(
                "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (note_id, guid, model_id, base_time_s, -1, tags, flds, card["word"], csum, 0, ""),
            )

            cur.execute(
                "INSERT INTO cards VALUES (?, ?, ?, 0, ?, -1, 0, 0, ?, 0, 0, 0, 0, 0, 0, 0, 0, ?)",
                (card_record_id, note_id, deck_id, base_time_s, idx + 1, ""),
            )

        conn.commit()
        conn.close()

        # Archive into .apkg ZIP
        apkg_buffer = io.BytesIO()
        with zipfile.ZipFile(apkg_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_path, "collection.anki2")
            zf.writestr("media", "{}")

        return apkg_buffer.getvalue()

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def generate_anki_tsv(
    cards: List[Union[AudienceCompanionCard, Dict[str, Any]]],
    deck_name: str = "VerbaClear Event Vocabulary",
) -> str:
    """
    Generates standard Anki tab-separated text format with deck directives.
    Imports directly with 1-click in any Anki desktop or mobile app.
    """
    lines = [
        "#separator:Tab",
        "#html:true",
        f"#deck:{deck_name}",
        "#tags column:4",
    ]

    for c in cards:
        item = _sanitize_card(c)
        front = (
            f"<b>{item['word']}</b> "
            f"<small style='color: #64748b;'>[{item['partOfSpeech']}] {item['phoneticIpa']}</small>"
        )

        synonyms_str = ", ".join(item["synonyms"])
        back = f"<b>Definition:</b> {item['definition']}"
        if synonyms_str:
            back += f"<br><b>Synonyms:</b> {synonyms_str}"
        if item["contextSentence"]:
            back += f"<br><i>Context: \"{item['contextSentence']}\"</i>"

        tags = "VerbaClear EventVocabulary"
        lines.append(f"{front}\t{back}\t{item['phoneticIpa']}\t{tags}")

    return "\n".join(lines)


def generate_csv(cards: List[Union[AudienceCompanionCard, Dict[str, Any]]]) -> str:
    """Generates standard RFC 4180 CSV for spreadsheets and flashcard platforms."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "Word",
        "Part of Speech",
        "Phonetic IPA",
        "Definition",
        "Synonyms",
        "Context Sentence",
        "Spoken Time",
        "Domain Badge",
    ])

    for c in cards:
        item = _sanitize_card(c)
        writer.writerow([
            item["word"],
            item["partOfSpeech"],
            item["phoneticIpa"],
            item["definition"],
            "; ".join(item["synonyms"]),
            item["contextSentence"],
            item["spokenTimeFormatted"],
            item["domainBadge"],
        ])

    return output.getvalue()


def generate_json(cards: List[Union[AudienceCompanionCard, Dict[str, Any]]]) -> str:
    """Generates formatted JSON export."""
    items = [_sanitize_card(c) for c in cards]
    return json.dumps(items, indent=2)
