# HQ conditioning inside the existing identity pipeline

The local browser release `dream-hq-full-pose-catalog-20261102` serves the full
R2 pose catalog and uses the original depth images for the approved A/B/C poses. Open
[HQ 试衣](http://127.0.0.1:8766/?view=hq-tryon), choose a person, garment and
pose, then select **本机生成**. **套用 A/B/C 定稿参数** restores 768 × 1152,
30 Euler steps, seed 20261104 and optional face polish at 0.35. FaceID uses
CFG 5.5, identity 0.82, structure 0.9 and companion LoRA 0.55. The garment
adapter runs at 0.7 and SD1.5 Depth ControlNet runs at 0.9 over all steps.

The released pose pairs are `full_single_P001_low` (A/C, low-angle sitting)
and `full_single_P015_front` (B, frontal standing). All other selected poses
use the existing DWPose extractor and the SD1.5 OpenPose weights selected by
the server-owned `openpose` section in the HQ config. Each route has its own
readiness, job identity and captured pose conditioning. The picker forwards
pagination, search and categories to the owned R2 catalog.
The two small public control maps, their R2 keys, the original pose checksums
and depth checksums are packaged in `config/dream/hq-paired-depth-v1`.
Paired depth jobs verify the R2 original and depth file. Skeleton jobs verify
the R2 original and record the extracted skeleton. Both capture the tensor
observed during sampling.

On the existing Windows installation, run `scripts/stop_dream_web.ps1` while
idle, then `scripts/enable_hq_paired_depth.ps1`, build the browser frontend
with `npm.cmd run build` from `apps/dream-windows`, and launch
`scripts/start_dream_web_background.ps1`. The enable script verifies the model
and packaged maps and prints the backup path for the previous pipeline
configuration. A hash mismatch means the weight or map needs to be restored
from its verified copy. Existing drafts keep their selected pose.
To roll back, stop the idle service, restore the printed backup as
`E:/Dream/data/hq/pipeline.json`, restore the preceding frontend and server
release together, then start the service. Both releases use the same local
history. The DWPose configuration example below describes the skeleton route.

HQ generation runs through `IdentityService` -> one-shot `identity_worker.py` ->
`IdentitySession.__init__/render`. It uses the existing reference cache, FaceID
projection, companion LoRA, model selection, Euler scheduler, request parameters,
optional face polishing, original-image retention, publication, history and
independent refinement/version workspace. `hq_tryon_pipeline.py` now contains
only configuration checks and audit storage. It has no generation function;
legacy CLI invocation fails with `HQ_IDENTITY_PIPELINE_REQUIRED` before loading
models. The earlier standalone prototype and its CPU evidence are historical, not
acceptance evidence for this integration. Existing prototype audit files remain
untouched.

## Trusted internal request

The public `IdentityGenerateRequest` is unchanged. The service injects this field
only after binding its private assets to the real identity child job:

```json
{
  "hqConditioning": {
    "configPath": "E:/Dream/data/hq/pipeline.json",
    "inputs": {
      "person": {"path": "ABSOLUTE ORIGINAL PERSON IMAGE", "id": "asset-id", "sha256": "64 hex characters"},
      "garment": {"path": "ABSOLUTE ORIGINAL GARMENT IMAGE", "id": "asset-id", "sha256": "64 hex characters"},
      "pose": {"path": "ABSOLUTE ORIGINAL POSE IMAGE", "id": "asset-id", "sha256": "64 hex characters"}
    },
    "auditPath": "ABSOLUTE FRESH AUDIT JSON"
  }
}
```

Optional fields within `hqConditioning`: `jobId` (HQ parent ID), `version`,
`eventPath` (fresh flushed JSONL), `cancelPath` (cancel when file exists).
The authoritative `imagePath`, `referenceId`, `faceIndex`, `jobId`, `dreamRoot`,
`outputPath`, `metadataPath` remain the ordinary identity worker fields.

`inputs.person.path` may be the original R2 file while `imagePath` is its stored
identity PNG. The helper independently verifies **exact EXIF-transposed RGB pixel
equality and dimensions**, preserving both encoded-file hashes. Face features
are still obtained from `identity_features.reference_features` using `imagePath`
and the selected `faceIndex`. No profile is silently replaced.

Only `realistic-vision-v5.1-faceid` / SD1.5 is supported. SDXL HQ and hybrid anime
profiles are explicitly rejected. Ordinary identity requests do not instantiate
the helper, load a garment/pose model or alter their placement/publication path.
HQ uses a fresh one-shot identity worker and rejects reuse for another child.

## Supplemental configuration

Parent-owned `E:/Dream/data/hq/pipeline.json` needs only the additional assets:

```json
{
  "schemaVersion": 1,
  "garmentAdapter": "D:/CodexDigitalHuman/AppearanceV2/ComfyUI/models/ipadapter/ip-adapter-plus_sd15.safetensors",
  "controlnet": "D:/CodexDigitalHuman/AppearanceV2/ComfyUI/models/controlnet/control_v11p_sd15_openpose.pth",
  "controlnetConfig": "E:/Dream/models/hq/openpose-controlnet",
  "poseAuxSource": "D:/CodexDigitalHuman/AppearanceV2/ComfyUI/custom_nodes/comfyui_controlnet_aux/src",
  "poseEstimator": "dwpose-full-image",
  "poseModel": "D:/CodexDigitalHuman/AppearanceV2/ComfyUI/custom_nodes/comfyui_controlnet_aux/ckpts/yzd-v/DWPose/dw-ll_ucoco_384.onnx",
  "offload": "sequential",
  "garmentScale": 0.7,
  "poseScale": 0.9
}
```

All base assets come from the **resolved existing identity configuration**.
Legacy duplicated `checkpoint`, `personAdapter`, `personLora`, `clipVision`,
`pipelineConfig`, `insightfaceRoot` fields are tolerated only if their resolved
paths match that configuration exactly. They never select another base model.
Legacy HQ `personScale`, `personStructureScale`, `personLoraScale`, `guidanceScale`
and prompt fields do not override identity parameters.

Default identity values remain identityStrength `.82`, structureStrength `.9`,
faceLoraStrength `.55`, cfg `5.5`, Euler, seed `0..2147483647`. The existing
`IdentityGenerateRequest` controls dimensions, steps, facePolish and restoration
strength. HQ requires a positive identityStrength and positive garment/pose
scales. No pip install or new large weights are required with the inspected
local environment (diffusers 0.36.0, torch 2.9.1+cu130).

The official ControlNet configuration already acquired by the parent is:

- Destination: `E:/Dream/models/hq/openpose-controlnet/config.json` (999 bytes)
- [Pinned official download](https://huggingface.co/lllyasviel/control_v11p_sd15_openpose/resolve/9ae9f970358db89e211b87c915f9535c6686d5ba/config.json)
- SHA256: `aa6fecc8745c0d0b26f0d2ca0f686600c8b33177c667d44eb41a51e56e44a697`

`readiness(config_path, identity_config=None)` is lightweight, without torch/GPU
imports. By default it resolves the existing RV bundle via `identity_worker`;
the service can pass its already-resolved identity config explicitly. It reports
file presence, not successful model execution or visual quality.

## Execution and evidence

The helper wraps the existing pipeline with
`StableDiffusionControlNetPipeline.from_pipe`, checking object identity of UNet,
VAE, text encoder, tokenizer and scheduler. No second checkpoint load occurs.
The wrapper explicitly passes `torch_dtype=None` to preserve those components'
existing dtype: diffusers 0.36 otherwise defaults `from_pipe` to float32 and
casts the shared weights in place. Actual component dtypes are recorded in the
audit; HQ worker failures retain a full traceback in the private worker log.
Both IP adapters are loaded in fixed `[person, garment]` slots. IdentitySession
executes its existing FaceID projection; the helper projects only garment CLIP
features and retains the two trained attention K/V branches (4 and 16 tokens).
The existing `extract_clip_features` handles garment encoding.

DWPose runs on CPU using the actual native-aspect image. It predicts the full
single-subject body, then the skeleton is letterboxed to output size. Every
shoulder, elbow, wrist, hip, knee and ankle must score >= .3. Detailed facial and
hand landmarks are excluded. Low-confidence results fail without text or dummy
skeleton fallback. Historical CPU checks of supplied P015/P016 returned minimum
limb scores .654809/.492252; these are model responses, not calibrated accuracy.

HQ offloading is confined to HQ jobs. Before the existing FacePolisher runs,
Accelerate hooks are removed and modules restored to CPU so the original
INSwapper/GFPGAN sequence remains serial. This is the existing FaceID restoration
route; it does not claim the SDXL-only protected-face-v3 capability.

Success writes the **same JSON object** to `metadata.hq` and `auditPath`:

```text
schemaVersion: 2
pipeline: identity-session-hq-sd15-v1
status: completed
jobId: actual identity child ID
parentJobId: optional hqConditioning.jobId
parameters: validated IdentityGenerateRequest values
inputs.{person,garment,pose}: id,path,sha256,width,height,mode,bytes
identityReference: path,sha256,normalizedRgbSha256,width,height,
                   pixelEqualityVerified,normalization,referenceId,faceIndex
preprocessing.{role}: path,sha256,width,height,transform
conditioning.{role}.actualConditioning: sha256,shape,dtype,hashFormat,
                                       target,forwardCalls,observed
models: actual file fingerprints
scheduler: actual class and config
baseBeforePolish: SHA256 and dimensions; existing original path when retained
facePolish: existing optional_face_polish result, including failure/disabled state
output: path,sha256,width,height,bytes
completedSteps,timings,durationMs,peakAllocatedMiB,peakReservedMiB
```

`actualConditioning` is observed at the real UNet/ControlNet forward boundary,
not copied from the request. Success requires all three branches to be observed
on every denoising step. Prepared tensor files are stored beside the audit in
`<audit-stem>.conditioning/`. A cancelled/failed audit never claims completed
conditioning; partial observations and timing remain available. Parent-enforced
process cancellation may leave an honest `preparing`/`sampling` audit if killed
before an exception can be handled.

For one-shot HQ only, `identity_worker.py --operation generate
--ownership-handshake --request ... --result ...` prints
`{"workerReady":true,"pid":ACTUAL_PID}` and waits for stdin
`{"workerContinue":true}` before model imports. Existing normal identity argv
and persistent-worker protocol remain unchanged. HQ failures retain structured
`code` and `error:{code,message,details}`, including `VRAM_OOM`.

Implementation references: [diffusers native IP projections](https://github.com/huggingface/diffusers/blob/v0.36.0/src/diffusers/models/embeddings.py),
[native ControlNet pipeline](https://github.com/huggingface/diffusers/blob/v0.36.0/src/diffusers/pipelines/controlnet/pipeline_controlnet.py),
[DWPose implementation](https://github.com/IDEA-Research/DWPose).

GPU image quality, garment fidelity, restoration quality and production memory
acceptance remain the parent's real-job checks. CPU substitutes test integration
and publication behavior, not generated-image quality.
