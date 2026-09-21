# VerbaClear: Data Dictionary & Protocol Specification

**Document Classification:** Data Architecture, Schemas & Wire Protocols  
**Author:** Joshua Maina ([mainajoshua713@gmail.com](mailto:mainajoshua713@gmail.com))  
**Version:** 2.0.0-PROD  
**Status:** Approved for Implementation  

---

## 1. Embedded SQLite Database Schema (DDL)

The local SQLite database (`verbaclear_lexicon.db`) stores pre-compiled linguistic data, curated synonyms, context packs, and session ledgers.

```sql
-- Pragmas for ultra-fast embedded read-heavy performance
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456; -- 256MB memory-mapped I/O

-- 1. Frequency Index (NGSL 1.2 + NAWL + BNC)
CREATE TABLE IF NOT EXISTS word_frequency (
    lemma TEXT PRIMARY KEY NOT NULL,
    frequency_rank INTEGER NOT NULL, -- 1 to 50000+
    corpus_source TEXT NOT NULL,     -- 'NGSL', 'NAWL', 'COCA'
    is_common_filter BOOLEAN NOT NULL DEFAULT 1 -- 1 = Common (ignore), 0 = Uncommon (evaluate)
);

CREATE INDEX IF NOT EXISTS idx_word_frequency_rank ON word_frequency(frequency_rank);

-- 2. Master Lexicon Store
CREATE TABLE IF NOT EXISTS lexicon (
    id TEXT PRIMARY KEY NOT NULL,          -- ULID or UUIDv4
    headword TEXT NOT NULL UNIQUE,         -- Base lemma (e.g. 'labyrinthine')
    part_of_speech TEXT NOT NULL,          -- 'adj', 'noun', 'verb', 'adv'
    phonetic_ipa TEXT,                     -- '/ˌlæb.əˈrɪn.θaɪn/'
    definition TEXT NOT NULL,              -- 1-sentence accessible definition
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lexicon_headword ON lexicon(headword);

-- 3. Synonyms (Punchy, stage-friendly simplified alternatives)
CREATE TABLE IF NOT EXISTS synonyms (
    id TEXT PRIMARY KEY NOT NULL,
    lexicon_id TEXT NOT NULL REFERENCES lexicon(id) ON DELETE CASCADE,
    synonym TEXT NOT NULL,                 -- e.g. 'Highly Complex'
    display_priority INTEGER NOT NULL,     -- 1 = primary, 2 = secondary, 3 = tertiary
    max_words INTEGER NOT NULL DEFAULT 1   -- Count of words in synonym (enforces brevity)
);

CREATE INDEX IF NOT EXISTS idx_synonyms_lexicon_id ON synonyms(lexicon_id);

-- 4. Domain Context Packs (Tier 2/3 Custom Glossaries)
CREATE TABLE IF NOT EXISTS context_packs (
    id TEXT PRIMARY KEY NOT NULL,          -- 'pack_fintech', 'pack_legal', 'pack_med'
    pack_name TEXT NOT NULL,               -- 'FinTech & Capital Markets'
    version TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS context_pack_entries (
    id TEXT PRIMARY KEY NOT NULL,
    pack_id TEXT NOT NULL REFERENCES context_packs(id) ON DELETE CASCADE,
    term TEXT NOT NULL,                    -- e.g. 'Collateralized Debt Obligation'
    abbreviation TEXT,                     -- 'CDO'
    domain_definition TEXT NOT NULL,
    simplified_synonym TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_pack_entries_lookup ON context_pack_entries(pack_id, term);

-- 5. Session Event Ledger (Audit log & export)
CREATE TABLE IF NOT EXISTS session_vocabulary_events (
    id TEXT PRIMARY KEY NOT NULL,          -- ULID
    session_id TEXT NOT NULL,
    timestamp_epoch_ms INTEGER NOT NULL,
    word TEXT NOT NULL,
    synonyms_json TEXT NOT NULL,           -- JSON array ['Highly Complex', 'Maze-like']
    context_sentence TEXT NOT NULL,
    stage_displayed BOOLEAN NOT NULL DEFAULT 1,
    saved_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_session_events ON session_vocabulary_events(session_id, timestamp_epoch_ms);
```

---

## 2. Real-Time WebSocket Wire Protocol

All real-time messages are framed as compact JSON payloads adhering to RFC 6455.

### 2.1. Stage Presentation Payload (`/ws/stage`)
*Dispatched to the primary stage overlay window with minimal footprint to conserve render budget.*

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "eventId": "evt_01HZX87Y9M1N98QZ4B2P5W1",
  "topic": "STAGE_DISPLAY_POP",
  "timestamp": 1726920450123,
  "data": {
    "cardId": "crd_01HZX87Y",
    "word": "Labyrinthine",
    "synonyms": [
      "Highly Complex",
      "Maze-like"
    ],
    "displayDurationSeconds": 7.0,
    "theme": {
      "accentColor": "#0284c7",
      "position": "bottom-right",
      "fontScale": "large"
    }
  }
}
```

### 2.2. Audience Companion Payload (`/ws/audience`)
*Dispatched to all connected mobile browsers for the rich attendee notebook.*

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "eventId": "evt_01HZX87Y9M1N98QZ4B2P5W1",
  "topic": "AUDIENCE_VOCABULARY_CARD",
  "timestamp": 1726920450123,
  "data": {
    "cardId": "crd_01HZX87Y",
    "word": "Labyrinthine",
    "partOfSpeech": "adjective",
    "phoneticIpa": "/ˌlæb.əˈrɪn.θaɪn/",
    "synonyms": [
      "Highly Complex",
      "Maze-like",
      "Twisting"
    ],
    "definition": "Complicated, irregular, or twisting; resembling a maze in structure.",
    "contextSentence": "The regulatory architecture governing cross-border payments remains labyrinthine.",
    "spokenTimeFormatted": "14:22:15",
    "domainBadge": "General"
  }
}
```

### 2.3. System Heartbeat & AV Telemetry (`/ws/admin` or Broadcast)
*Broadcast every 5 seconds to verify appliance health and audio gain levels.*

```json
{
  "topic": "SYSTEM_TELEMETRY",
  "timestamp": 1726920455000,
  "data": {
    "audioStreamActive": true,
    "inputPeakRmsDb": -14.2,
    "speechActivityDetected": true,
    "asrInferenceLatencyMs": 134,
    "connectedStageClients": 1,
    "connectedAudienceClients": 142,
    "activeSessionId": "sess_keynote_hall_a"
  }
}
```

---

## 3. TypeScript Interfaces for Frontend Clients

```typescript
// Shared Types for Stage Display and Companion App

export type MessageTopic = 
  | 'STAGE_DISPLAY_POP'
  | 'AUDIENCE_VOCABULARY_CARD'
  | 'SYSTEM_TELEMETRY';

export interface BaseSocketMessage<T> {
  eventId: string;
  topic: MessageTopic;
  timestamp: number;
  data: T;
}

export interface StageCardData {
  cardId: string;
  word: string;
  synonyms: string[];
  displayDurationSeconds: number;
  theme?: {
    accentColor?: string;
    position?: 'bottom-left' | 'bottom-right' | 'bottom-center';
    fontScale?: 'normal' | 'large' | 'extra-large';
  };
}

export interface AudienceCardData {
  cardId: string;
  word: string;
  partOfSpeech: 'noun' | 'verb' | 'adjective' | 'adverb' | 'idiom';
  phoneticIpa: string;
  synonyms: string[];
  definition: string;
  contextSentence: string;
  spokenTimeFormatted: string;
  domainBadge?: string;
  isBookmarked?: boolean;
}

export interface SystemTelemetryData {
  audioStreamActive: boolean;
  inputPeakRmsDb: number;
  speechActivityDetected: boolean;
  asrInferenceLatencyMs: number;
  connectedStageClients: number;
  connectedAudienceClients: number;
  activeSessionId: string;
}
```
