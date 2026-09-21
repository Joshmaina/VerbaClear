# VerbaClear: Ambient Real-Time AI Vocabulary Simplification Platform

**Target Developer/Creative:** Joshua Maina ([mainajoshua713@gmail.com](mailto:mainajoshua713@gmail.com))  
**System Classification:** B2B Live Event Accessibility & Cognitive Augmentation Appliance  
**Engineering Architecture:** Hexagonal / Clean Architecture (Hard Real-Time Streaming)  

---

## 1. Executive Summary & Core Vision

**VerbaClear** is an ambient, AI-powered real-time vocabulary assistant designed as a B2B event technology solution. The platform targets a deep psychological pain point: the public anxiety, cognitive overload, and loss of focus experienced by audience members when speakers use intense, advanced vocabulary or niche industry jargon.

Unlike traditional translation frameworks that output heavy, scrolling lines of raw text, VerbaClear works as an educational intelligence filter within the same language (English-to-Simple-English). It processes live speech invisibly, extracting only uncommon vocabulary and serving instantaneous, low-distraction synonyms to the entire room, preserving audience engagement and speaker flow.

---

## 2. Engineering Documentation Suite

The system is fully documented following professional Computer Science and enterprise software engineering standards:

| Document | Purpose & Scope | Link |
| :--- | :--- | :--- |
| **System Architecture (SAD)** | Signal processing theory, Bloom filter math, C4 models, ADRs, latency budget, and STRIDE security analysis. | [`Docs/ARCHITECTURE.md`](Docs/ARCHITECTURE.md) |
| **Software Requirements (SRS)** | Formal Functional (FR-1 to FR-6) and Non-Functional Requirements (NFR-1 to NFR-4) with acceptance test matrices. | [`Docs/SPECIFICATION.md`](Docs/SPECIFICATION.md) |
| **Data Dictionary & Protocols** | SQLite DDL schemas (WAL mode), JSON Schema contracts, and TypeScript wire protocols for WebSockets. | [`Docs/DATA_DICTIONARY.md`](Docs/DATA_DICTIONARY.md) |
| **Phased Execution Blueprint** | End-to-end processing pipeline flowcharts and strict sequential build verification gates. | [`Docs/SYSTEM_SPECIFICATION.md`](Docs/SYSTEM_SPECIFICATION.md) |
| **Original Spec PDF** | Archived reference documentation from project inception. | [`Docs/VerbaClear_Project_Documentation.pdf`](Docs/VerbaClear_Project_Documentation.pdf) |

---

## 3. System Architecture & Latency Budget

```
[Live Presenter Audio] (16kHz PCM)
          │
          ▼
[Silero VAD v5] ── (Noise / Silence Gating) ──► Dropped (<1ms)
          │ (Speech Detected, 250ms trailing pause)
          ▼
[faster-whisper Engine] (CTranslate2, distil-large-v3) ──► Latency: ~150ms
          │ (Transcribed Text + Word Timestamps)
          ▼
[Lexical Brain] (NGSL Bloom Filter + spaCy Lemmatizer) ──► Latency: ~5ms
          │ (Uncommon Terms Filtered: Rank > 3,500)
          ▼
[SQLite Lexicon Store] (Curated Synonyms + Phonetics) ──► Latency: ~2ms
          │
          ▼
[FastAPI WebSocket Hub] ──► Dispatch: ~3ms
     ├──► /ws/stage     ──► Stage Lower-Third Overlay (7s Spring Decay Card)
     └──► /ws/audience  ──► Mobile Companion PWA (Definitions + Anki Export)

TOTAL END-TO-END LATENCY: ~460ms - 600ms (P99 < 800ms)
```

---

## 4. Dual-Output UI Strategy

To optimize comprehension without causing visual distraction, VerbaClear segments data presentation into two specific tiers:

| Feature Component | Primary Stage Presentation Screen | Audience QR Companion Portal |
| :--- | :--- | :--- |
| **Target Intent** | Subtle, split-second ambient glance. | Deep-dive contextual look and bookmarking. |
| **Format Layout** | Isolated lower-third overlay card featuring 1-3 punchy synonyms (e.g., *Labyrinthine → Highly Complex*). Fades out in 7 seconds. | Full mobile web environment displaying synonym + 1-sentence dictionary definition + phonetics. |
| **Interaction** | Zero interaction. Completely passive. | Active. Attendees tap to save words to a personal spaced-repetition deck (e.g., Anki, CSV, flashcards). |

---

## 5. Sequential Phase-by-Phase Build Roadmap

Development progresses consecutively across 6 discrete phases with hard exit gates:

1. **Phase 1: The Auditory Ear (Audio & Speech Pipeline)**: 16kHz PortAudio ring buffer + Silero-VAD v5 + `faster-whisper` CTranslate2.  
   *Exit Gate: Live mic speech transcribes to console in < 800ms with zero silence hallucinations.*
2. **Phase 2: The Semantic Brain (Lexical Intelligence)**: NGSL/NAWL in-memory Bloom filter + spaCy lemmatizer + SQLite curated lexicon.  
   *Exit Gate: Complex words in live speech output punchy synonyms, ignoring top 3,500 words.*
3. **Phase 3: The Nervous System (Event Hub & Gateway)**: FastAPI async server hosting background audio thread + `/ws/stage` & `/ws/audience` WebSockets.  
   *Exit Gate: Real-time speech triggers synchronized JSON payloads to connected WebSocket clients within 50ms.*
4. **Phase 4: The Ambient Eye (Stage Lower-Third Display)**: Next.js / React 19 + Framer Motion chroma-key overlay with 7s decay.  
   *Exit Gate: Spoken rare words appear on second monitor / OBS lower-third and auto-fade cleanly.*
5. **Phase 5: The Attendee Notebook (Audience QR Companion)**: Mobile PWA with live feed, IndexedDB local persistence, and Anki (`.apkg`) / CSV export.  
   *Exit Gate: QR scan on smartphone shows live feed; bookmarking exports importable Anki deck.*
6. **Phase 6: Production Hardening (AV & Venue Release)**: Physical mixer audio testing, 100% offline network verification, and Docker CLI orchestrator.  
   *Exit Gate: 30-minute keynote test with 50 connected mobile devices, zero dropped frames, < 1.2s latency.*

---

## 6. Repository Layout (Clean Architecture)

```
VerbaClear/
├── Docs/                              # Comprehensive engineering specifications
│   ├── ARCHITECTURE.md                # System design, C4 diagrams, ADRs, latency budget
│   ├── SPECIFICATION.md               # SRS with functional & non-functional requirements
│   ├── DATA_DICTIONARY.md             # SQLite DDL, WebSocket schemas & TypeScript types
│   ├── SYSTEM_SPECIFICATION.md        # Technical pipeline & sequential execution plan
│   └── VerbaClear_Project_Documentation.pdf
├── src/
│   ├── domain/                        # Pure business models & abstract interfaces (Ports)
│   │   ├── models.py                  # AudioChunk, TranscribedSegment, StageOverlayCard
│   │   └── interfaces.py              # AudioSourcePort, SpeechToTextPort, LexicalFilterPort
│   ├── infrastructure/                # Framework-specific adapters
│   │   ├── audio/                     # PortAudio driver & Silero-VAD v5 wrapper
│   │   ├── asr/                       # faster-whisper CTranslate2 worker
│   │   ├── nlp/                       # NGSL Bloom filter & spaCy lemmatizer
│   │   └── storage/                   # SQLite WAL lexicon repository
│   ├── application/                   # Core orchestrator pipeline
│   └── api/                           # FastAPI ASGI application & WebSockets
├── web/                               # Presentation clients
│   ├── stage/                         # Next.js transparent lower-third overlay
│   └── companion/                     # Next.js mobile PWA attendee portal
├── pyproject.toml                     # Modern Python project & dependency configuration
└── README.md
```
