# H4 Open-source visualization references

H4 does not bundle these projects as runtime dependencies. They are design/interaction references used to avoid reinventing established visualization patterns.

## Diffusion Explainer

- Repository: `poloclub/diffusion-explainer`
- License: MIT
- H4 borrows the architecture-first / progressive drill-down idea visible in its `architecture.js`, `text_l2expl.js`, `text_l3expl.js`, `denoise_l2expl.js`, and `denoise_l3expl.js` organization.
- H4's HTML/CSS/JS is newly authored and wired to real S24U QNN telemetry.

## Perfetto

- Repository: `google/perfetto`
- H4 borrows the horizontal tracing/timing-lane vocabulary.
- H4 does not embed Perfetto itself in the APK.

## DAAM / ComfyUI-DAAM

- Repositories: `castorini/daam` and community ComfyUI-DAAM integrations.
- H4 borrows the concept of prompt-to-image attribution heatmaps.
- H4 explicitly displays `Cross-attention：未采集` until the QNN/MNN runtime actually exports suitable cross-attention data; no synthetic heatmap is permitted.

## Netron

- Repository: `lutzroeder/netron`
- H4 borrows the hierarchical model/tensor inspection vocabulary.
- H4 does not embed Netron.
