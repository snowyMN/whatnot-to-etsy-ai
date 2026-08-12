## Updated Plan: Dual Local AI Pipelines (Qwen + FLUX/ComfyUI)

Goal: Extend the existing listing-intelligence plan to include a local product image enhancement pipeline while preserving factual product condition and original images. Use Qwen2.5-VL-7B-Instruct through LM Studio for multimodal analysis/validation and FLUX.2 klein 4B through ComfyUI for selective semantic image edits.

### Core Architecture
Whatnot import -> Raw product record -> Original image assets -> Qwen product analysis -> Listing draft/keywords -> Qwen image quality analysis -> Processing decision (deterministic vs FLUX) -> Enhanced image asset -> Qwen original-vs-enhanced validation -> Human review -> Approved listing + approved image choice -> Marketplace adapters (future).

### Key Constraints
- Never alter factual product condition.
- Original images immutable and always retained.
- Deterministic processing preferred whenever sufficient.
- FLUX used only when deterministic tools cannot safely achieve desired result.
- Model/provider abstraction for both LM Studio and ComfyUI.

### Planned Components
- LocalLLMProvider + LMStudioProvider for Qwen workflows.
- ImageEditingProvider + ComfyUIImageEditingProvider for FLUX workflows.
- ImageEnhancementService orchestration.
- Image model/table for original, processed, validation, and approval tracking.

### Milestone Scope
Implement import -> image cache -> analyze -> enhance -> validate -> side-by-side review -> approve image choice. No automatic marketplace publishing.
