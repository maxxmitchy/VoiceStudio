# MaxxVoice Architecture Audit

**Audit date:** 2026-09-12  
**Repository:** `maxxmitchy/VoiceStudio`  
**Primary downstream consumer:** `maxxmitchy/Wellivox-cAREFLUX-bUILD`  
**Upstream:** VoiceStudio / previously OmniVoice-Studio

## Executive finding

The fork is already a strong speech/media workstation rather than a thin TTS wrapper. The correct strategy is **evolution, not rewrite**: retain the mature engine/media infrastructure and add a clean MaxxVoice orchestration layer above it.

MaxxVoice is being developed specifically so the resulting platform can become the **voice/media execution layer for Careflux/WelLivox**, while remaining reusable by other products. Careflux-specific clinical reasoning, patient-data selection and approval remain outside MaxxVoice.

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
The service layer already contains dedicated components for ASR, TTS, audio I/O/DSP, chunked TTS, audiobook generation, video dubbing, duration planning, dubbing QC, batch processing, capture/dictation and speaker/voice workflows.

### AI/orchestration
A particularly important existing component is `backend/services/director.py`. It already accepts natural-language delivery direction and converts it into a stable taxonomy covering energy, emotion, pace, intimacy and formality. It can use an LLM or deterministic heuristic fallback, and the resulting contract influences translation, TTS instruction and speech-rate planning.

## 2. Product dependency direction

```text
Careflux / WelLivox
       |
       | approved, display-safe text + voice preferences
       v
MAXXVOICE API
       |
       +-- Workflow orchestration / durable jobs
       +-- Stable capability contracts
       +-- Existing VoiceStudio speech/media services
       +-- Engine registry / adapters
       +-- Models / hardware / workers
```

The important boundary is intentional: **Wellivox owns clinical context and decision-making; MaxxVoice owns voice/media presentation and execution.**

The first concrete Careflux integration is `POST /maxxvoice/workflows/careflux-voice`, which accepts approved text and returns a durable job/progress contract. The endpoint explicitly does not perform clinical reasoning.

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

## 4. MaxxVoice foundation status

### Stable capability layer
`backend/maxxvoice/capabilities.py` provides `synthesize` and `transcribe` contracts. It resolves TTS/ASR through existing registries rather than individual model implementations.

### Orchestration and durable jobs
MaxxVoice has inspectable plans, durable SQLite workflow jobs, idempotency keys, API job status/progress, durable per-step checkpoints and validated WAV artifact persistence. Concurrent idempotent requests now use an atomic SQLite claim so only the creator dispatches work.

### Resumability
Article → Podcast segment artifacts are validated before checkpoint completion and can be reused after failure. Resume regenerates only missing/corrupt work and reassembles the final output from validated segments.

### Restart recovery
Persisted jobs left in `running` state can be conservatively marked failed after process restart. They are not falsely reported as having continued execution; explicit resume remains the recovery action.

### Careflux voice workflow
`backend/maxxvoice/workflows/careflux_voice.py` provides a presentation-only renderer for already approved Careflux text. It delegates speech generation to the existing capability layer and can persist a WAV artifact.

## 5. Careflux/WelLivox integration contract

The downstream Android application `maxxmitchy/Wellivox-cAREFLUX-bUILD` already has a strict AI boundary around authoritative data, privacy transformation, provider invocation and deterministic validation. MaxxVoice therefore should not bypass that architecture.

The intended interaction is:

```text
Authoritative Wellivox data
        ↓
Careflux AI Engine
        ↓
privacy boundary + deterministic validation
        ↓
approved display-safe message
        ↓
MaxxVoice Careflux Voice API
        ↓
voice generation
        ↓
job status / audio artifact
        ↓
Wellivox playback / user-facing experience
```

The Android project now contains a small `MaxxVoiceApiService` boundary and configurable `MAXXVOICE_BASE_URL`. No provider secrets are added to the Android client.

## 6. Product roadmap

### Phase 1 — Audit
- [x] Confirm repository fork and default branch.
- [x] Map frontend/backend boundaries.
- [x] Map API/router structure.
- [x] Identify engine registry boundary.
- [x] Identify existing orchestration/director capability.
- [x] Identify MCP/API surface.

### Phase 2 — Safe foundation
- [x] Add MaxxVoice capability contracts.
- [x] Add orchestration package without replacing existing workflows.
- [x] Add tests for capability validation and planner contract.
- [ ] Wire health/status endpoint into application bootstrap.
- [x] Add architecture documentation.
- [x] Add durable workflow-job persistence.
- [x] Add atomic workflow idempotency support.
- [x] Add API job-status/progress surface.
- [x] Add durable per-segment checkpoints.
- [x] Add validated artifact persistence and resumable execution.
- [x] Add conservative restart recovery.

### Phase 3 — Agent workflows
- [ ] Script-to-audio workflow.
- [x] Article-to-podcast planning and segmented audio execution.
- [ ] Multi-speaker casting workflow.
- [ ] Voice-directed generation.
- [ ] Batch content factory.

### Phase 4 — Careflux/WelLivox product integration
- [x] Careflux presentation-voice workflow contract.
- [x] Android client API boundary.
- [ ] Wellivox UI playback integration.
- [ ] Wellivox job polling/state integration.
- [ ] Authentication and trusted-server deployment contract.
- [ ] Offline/queued voice requests where appropriate.
- [ ] Careflux voice UX and accessibility pass.

### Phase 5 — Other integrations
- [ ] Generix medical-content adapter.
- [ ] Educational/audiobook adapter.
- [ ] External API/MCP integrations.

## 7. Guardrails

- Do not replace functioning engines merely for branding.
- Do not hard-code Careflux clinical/business logic into the core speech engine.
- Do not send raw patient records to MaxxVoice when approved presentation text is sufficient.
- Do not expose arbitrary remote model installation through an unauthenticated API.
- Do not assume all model weights share the AGPL license; preserve each model's upstream terms.
- Maintain upstream attribution and AGPL-3.0 compliance.
- Prefer additive commits with tests over large rewrites.

## 8. Current conclusion

**MaxxVoice is now being shaped as the voice/media execution layer that Careflux/WelLivox can call, not as a separate generic TTS product.**

The immediate product goal is therefore to make the boundary reliable end-to-end: approved Careflux content → MaxxVoice job → speech artifact → Wellivox playback, while preserving the mature VoiceStudio engine room underneath.
