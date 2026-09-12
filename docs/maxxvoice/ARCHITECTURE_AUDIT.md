# MaxxVoice Architecture Audit

**Audit date:** 2026-09-12  
**Repository:** `maxxmitchy/VoiceStudio`  
**Upstream:** VoiceStudio / previously OmniVoice-Studio

## Executive finding

The fork is already a strong speech/media workstation rather than a thin TTS wrapper. The correct strategy is **evolution, not rewrite**: retain the mature engine/media infrastructure and add a clean MaxxVoice orchestration layer above it.

## 1. Current architecture

### Frontend
- React 19 + Vite 8.
- Zustand for client state.
- TanStack Query/Table/Virtual for data-heavy UI.
- Radix UI primitives and Tailwind CSS 4.
- Wavesurfer for waveform/audio interaction.
- Tauri 2 is the desktop shell.
- The UI is currently concentrated around `frontend/src/App.jsx`, with dedicated `components`, `pages`, `api`, `store`, `hooks`, `config`, `data`, `lib`, and `i18n` areas.

### Backend
- FastAPI/Python backend under `backend/`.
- API is separated into routers, schemas and dependencies.
- Services hold domain/application operations.
- Engines are isolated under `backend/engines/`.
- There is a worker area and a speech client layer.
- `backend/main.py` is a substantial lifecycle/bootstrap entry point handling platform process behavior, environment/configuration, logging, diagnostics and deferred application initialization.

### Engine architecture
The repository has a registry-oriented backend architecture. The engines area includes multiple TTS implementations and subprocess/sidecar variants. The API exposes TTS, ASR and LLM families and supports selecting active backends, health checks, availability reporting and engine installation for some optional components.

This is an excellent seam for MaxxVoice: **do not make downstream products depend on individual model implementations.** They should call a stable capability interface.

### Media/audio
The service layer already contains dedicated components for:
- ASR
- TTS
- audio I/O/DSP
- chunked TTS
- audiobook generation
- video dubbing
- duration planning
- dubbing QC
- batch processing
- capture/dictation
- speaker/voice workflows

The API router set also shows dedicated audiobook, batch, capture, dictation, dubbing, engine and other workflow boundaries.

### AI/orchestration
A particularly important existing component is `backend/services/director.py`. It already accepts natural-language delivery direction and converts it into a stable taxonomy covering energy, emotion, pace, intimacy and formality. It can use an LLM or deterministic heuristic fallback, and the resulting contract influences translation, TTS instruction and speech-rate planning.

This means the repository already contains the beginnings of the **intelligence/orchestration layer** we want. MaxxVoice should expand this concept rather than invent it from scratch.

### API/MCP
The repository contains a dedicated `backend/mcp_server.py`, and the README documents REST/SSE/WebSocket interfaces, an OpenAI-compatible audio API and MCP. This gives MaxxVoice a natural machine-facing interface for agents and external applications.

## 2. Important architectural observation

The current codebase has a lot of product-specific terminology and historical `OmniVoice`/`VoiceStudio` naming, but the functional boundaries are much cleaner than the branding suggests.

We should therefore separate:

```text
MAXXVOICE PLATFORM
        |
        +-- Orchestration / Agents
        |
        +-- Stable Capability API
        |
        +-- Existing Speech + Media Services
        |
        +-- Engine Registry / Adapters
        |
        +-- Models / Hardware / Workers
```

Applications such as Careflux, Generix Global and educational/content products should consume the platform through the API/MCP layer rather than being embedded into the core.

## 3. What we should preserve

- Existing TTS/ASR engine adapters.
- Model catalogue and model lifecycle management.
- Device detection and GPU routing.
- Voice cloning/design workflows.
- Dubbing pipeline.
- Audiobook/long-form generation.
- Batch queue.
- DSP/audio processing.
- Diagnostics and logging.
- Tauri desktop packaging.
- Docker support.
- Existing CI/test infrastructure.
- AGPL-3.0 license and upstream attribution obligations.

## 4. What we should change gradually

### A. Branding boundary
Introduce MaxxVoice branding/configuration without immediately deleting upstream names from implementation internals. Rename only after tests establish that the change is safe.

### B. Stable capability layer
Create a platform-level capability contract such as:

- `synthesize`
- `transcribe`
- `clone_voice`
- `design_voice`
- `convert_voice`
- `isolate_voice`
- `diarize`
- `dub`
- `render_long_form`
- `batch`

The implementation should resolve capabilities through the existing engine registry.

**Phase 2 implementation status:** `backend/maxxvoice/capabilities.py` now provides the first stable `synthesize` and `transcribe` contracts. It delegates TTS resolution to `resolve_generation_backend()` and ASR resolution to `load_active_asr_backend()`, preserving existing availability checks, hardware routing, model lifecycle and fallback rules. The capability layer does not import individual model implementations.

### C. Orchestration layer
Add a MaxxVoice orchestration service responsible for turning high-level user intent into one or more capability calls.

Example:

```text
"Turn this article into a 7-minute podcast"
        ↓
Intent extraction
        ↓
Script planner
        ↓
Voice/casting decision
        ↓
TTS generation
        ↓
Audio assembly/QC
        ↓
Export
```

### D. Agent/MCP layer
Expose orchestration primitives through MCP so an AI agent can operate MaxxVoice as a tool rather than merely calling raw TTS.

## 5. Proposed MaxxVoice modules

```text
backend/maxxvoice/
├── capabilities.py       # Phase 2: stable synthesize/transcribe boundary
├── orchestration/
│   ├── planner.py
│   ├── jobs.py
│   ├── casting.py
│   └── quality.py
├── agents/
│   ├── tools.py
│   └── workflows.py
├── projects/
│   └── models.py
└── api/
    └── router.py
```

The exact directory layout should be adjusted after dependency inspection; the important point is the dependency direction, not the names.

## 6. First product to build

The best initial MaxxVoice product is not another generic voice generator. It is a **Voice/Audio Agent Workbench**:

1. User gives a natural-language objective.
2. MaxxVoice plans the work.
3. It selects appropriate speech/media capabilities.
4. It generates intermediate artifacts.
5. User reviews/edits.
6. MaxxVoice renders the final output.
7. The same workflow is callable through API/MCP.

This gives the project a differentiated reason to exist while preserving the upstream workstation.

## 7. Priority roadmap

### Phase 1 — Audit
- [x] Confirm repository fork and default branch.
- [x] Map frontend/backend boundaries.
- [x] Map API/router structure.
- [x] Identify engine registry boundary.
- [x] Identify existing orchestration/director capability.
- [x] Identify MCP/API surface.

### Phase 2 — Safe foundation
- [x] Add MaxxVoice capability contracts.
- [ ] Add orchestration package without changing existing workflows.
- [x] Add tests for capability validation and contract stability.
- [ ] Add a health/status endpoint for MaxxVoice layer.
- [x] Add architecture documentation.

### Phase 3 — Agent workflows
- [ ] Script-to-audio workflow.
- [ ] Article-to-podcast workflow.
- [ ] Multi-speaker casting workflow.
- [ ] Voice-directed generation.
- [ ] Batch content factory.

### Phase 4 — Product integrations
- [ ] Careflux Voice adapter.
- [ ] Generix medical-content adapter.
- [ ] Educational/audiobook adapter.
- [ ] External API/MCP integrations.

## 8. Guardrails

- Do not replace functioning engines merely for branding.
- Do not hard-code Careflux or other businesses into the core platform.
- Do not expose arbitrary remote model installation through an unauthenticated API.
- Do not assume all model weights share the AGPL license; preserve each model's upstream terms.
- Maintain upstream attribution and AGPL-3.0 compliance.
- Prefer additive commits with tests over large rewrites.

## 9. Current conclusion

**MaxxVoice should become the orchestration and agent layer over a mature local-first speech/media engine.**

The repository already provides most of the difficult low-level infrastructure. Our competitive work should therefore focus on intent, workflow planning, voice intelligence, automation, APIs/MCP, product integrations and an excellent user experience—not rebuilding TTS engines from zero.
