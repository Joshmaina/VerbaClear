# VerbaClear: Formal Engineering Specification & Requirements Document (SRS)

**Document Classification:** Software Requirements Specification (SRS)  
**Author:** Joshua Maina ([mainajoshua713@gmail.com](mailto:mainajoshua713@gmail.com))  
**Version:** 2.0.0-PROD  
**Status:** Approved for Implementation  

---

## 1. System Scope & Objectives

VerbaClear is a localized, real-time speech intelligence appliance that:
1. Ingests raw audio from a live microphone or audio interface.
2. Performs low-latency offline speech-to-text (ASR).
3. Evaluates lexical rarity against standard linguistic corpora (NGSL / NAWL).
4. Emits contextual, low-distraction synonyms to a primary stage display.
5. Emits enriched educational cards with phonetics, definitions, and flashcard bookmarking to an audience-accessible web companion via QR code.

---

## 2. Functional Requirements (FR)

### Module 1: Audio Capture & Signal Conditioning
- **FR-1.1**: The system **SHALL** interface with standard PortAudio devices (USB interfaces, built-in microphones, virtual audio loopbacks) using 16,000 Hz, 16-bit mono linear PCM.
- **FR-1.2**: The system **SHALL** continuously monitor incoming audio frames (30ms chunks) using an embedded Voice Activity Detection (VAD) model (`Silero-VAD v5`).
- **FR-1.3**: The VAD engine **SHALL** drop frames with speech probability $< 0.5$, discarding HVAC hum, venue silence, and low-level room noise without invoking the ASR engine.
- **FR-1.4**: The system **SHALL** maintain a sliding circular buffer holding up to 5 seconds of audio and emit a complete speech chunk when a trailing silence pause $\ge 250\text{ ms}$ or a maximum window of $2.5\text{ s}$ is reached.

### Module 2: Local Automatic Speech Recognition (ASR)
- **FR-2.1**: The system **SHALL** execute transcription using an offline, locally hosted `faster-whisper` model (`distil-large-v3` or `whisper-small.en`).
- **FR-2.2**: The ASR engine **SHALL** generate word-level timestamps (`start_time`, `end_time`, `probability`) for each transcribed token.
- **FR-2.3**: The ASR engine **SHALL** use greedy decoding (`beam_size=1`, `temperature=0.0`) to minimize inference latency.

### Module 3: Lexical Analysis & Vocabulary Filter
- **FR-3.1**: The system **SHALL** tokenize and normalize incoming text into lowercased lemmas using a deterministic lemmatizer (spaCy `en_core_web_sm`).
- **FR-3.2**: The system **SHALL** check each lemma against an in-memory frequency index comprising the **New General Service List (NGSL 1.2)** and **Academic Word List (NAWL)**.
- **FR-3.3**: The system **SHALL** classify any word with a frequency rank $> 3,500$ as an **Uncommon Term**.
- **FR-3.4**: The system **SHALL** filter out stopwords, numbers, punctuation, and Named Entities (proper nouns such as personal names, geographic locations, and corporate brands).
- **FR-3.5**: For each detected uncommon term, the system **SHALL** query the local SQLite lexicon to extract:
  - 1–3 concise synonyms (maximum 3 words per synonym).
  - International Phonetic Alphabet (IPA) phonetic transcription.
  - Exactly 1 clear, accessible dictionary definition sentence.
  - The verbatim context sentence spoken by the presenter.
- **FR-3.6**: If a specialized **Domain Context Pack** (Legal, Medical, FinTech, Academic) is enabled, its terminology and definitions **SHALL** take precedence over the general lexicon.

### Module 4: Real-Time Event Hub & Dual WebSockets
- **FR-4.1**: The system **SHALL** provide a high-throughput WebSocket server (`/ws/stage` and `/ws/audience`).
- **FR-4.2**: The `/ws/stage` endpoint **SHALL** broadcast lightweight payloads containing the original word, 1–3 synonyms, and a display timer parameter.
- **FR-4.3**: The `/ws/audience` endpoint **SHALL** broadcast complete educational payloads including word, phonetics, definition, context sentence, and timestamp.
- **FR-4.4**: The event manager **SHALL** enforce an anti-collision queue: if multiple uncommon words occur in the same sentence, they **SHALL** be staggered with a minimum display separation of 3 seconds.

### Module 5: Stage Lower-Third Presentation Display
- **FR-5.1**: The stage presentation interface **SHALL** run as a transparent web page suitable for direct HDMI full-screen rendering or OBS Studio / vMix Browser Source.
- **FR-5.2**: When a vocabulary event arrives, the overlay **SHALL** trigger a smooth spring entrance transition in the lower-third quadrant.
- **FR-5.3**: The overlay card **SHALL** display an integrated visual decay countdown and automatically trigger an exit fade transition after exactly 7 seconds.
- **FR-5.4**: The stage screen **SHALL** require zero human operator interaction during a live event.

### Module 6: Audience Mobile Companion Portal
- **FR-6.1**: The companion portal **SHALL** be accessible via standard mobile browsers by scanning a dynamically generated local Wi-Fi or domain QR code without requiring native app installation.
- **FR-6.2**: The portal **SHALL** render an append-only, reverse-chronological feed of vocabulary cards in real-time.
- **FR-6.3**: Attendees **SHALL** be able to tap a "Bookmark" icon on any card to save it to their personal session deck.
- **FR-6.4**: Bookmarked words **SHALL** be persisted locally in the attendee's browser using `IndexedDB`.
- **FR-6.5**: The portal **SHALL** provide a one-tap export button generating an **Anki flashcard deck (`.apkg`)** and a standard CSV file.

---

## 3. Non-Functional Requirements (NFR)

### NFR-1: Real-Time Latency Bounds
- **NFR-1.1**: Spoken word-to-stage overlay rendering latency **SHALL NOT** exceed $1,000\text{ ms}$ at P95 and $1,200\text{ ms}$ at P99 under standard operating load.
- **NFR-1.2**: Vocabulary classification and database retrieval **SHALL** execute in $< 10\text{ ms}$ per word.
- **NFR-1.3**: WebSocket dispatch latency from backend to connected clients on local LAN **SHALL** be $< 15\text{ ms}$.

### NFR-2: Offline Resilience & Zero-Cloud Dependency
- **NFR-2.1**: 100% of core features (Audio capture, VAD, ASR, NLP filtering, SQLite queries, WebSockets, Stage display) **SHALL** function with zero active internet connection.
- **NFR-2.2**: The system **SHALL NOT** make external API calls to third-party cloud services during presentation runtime.

### NFR-3: Scalability & Concurrency
- **NFR-3.1**: The local WebSocket hub **SHALL** comfortably support at least 500 concurrent mobile companion connections on a standard Wi-Fi 6 local access point without degrading audio transcription throughput.
- **NFR-3.2**: Memory consumption of the core backend daemon **SHALL NOT** exceed 4 GB RAM when running the `distil-large-v3` model.

### NFR-4: Operational Reliability & Fault Tolerance
- **NFR-4.1**: If the audio capture interface is disconnected and reconnected, the audio daemon **SHALL** automatically recover and resume ingestion within 2 seconds without crashing the server.
- **NFR-4.2**: The system **SHALL** handle unexpected speech bursts without buffer overflow by utilizing bounded drop-oldest ring buffers.

---

## 4. Verification & Acceptance Test Matrix

| Req ID | Verification Method | Acceptance Criteria |
| :--- | :--- | :--- |
| **FR-1.2 / FR-1.3** | Automated Audio Benchmark | Ingesting 60s of cafeteria noise produces 0 ASR invocations; speaking 5 words activates ASR within 250ms of trailing pause. |
| **FR-2.1 / NFR-1.1** | Synthetic Audio Stream Test | Pre-recorded audio with known ground truth yields word error rate (WER) $\le 6\%$ and average inference time $\le 180\text{ ms}$. |
| **FR-3.3 / FR-3.4** | Linguistic Test Suite | Input string *"The CEO obfuscated the esoteric algorithmic parameters"* triggers cards for `obfuscate` and `esoteric`, ignoring `CEO`, `the`, `algorithmic`, `parameters`. |
| **FR-4.1 / NFR-1.3** | WebSocket Latency Benchmark | Dispatched payload arrives at 200 connected mock WebSocket clients within 12ms mean latency. |
| **FR-5.3** | Visual Automated Test | Lower-third card enters at $T=0$, remains steady, and completes exit animation at $T=7.0\text{s} \pm 0.1\text{s}$. |
| **FR-6.5** | File Format Validation | Exported `.apkg` file successfully parses and renders flashcards in official Anki Desktop / AnkiDroid apps. |
