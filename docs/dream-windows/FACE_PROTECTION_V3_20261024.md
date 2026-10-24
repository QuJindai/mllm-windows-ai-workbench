# Protected reference refinement v3

The previous reference-anchor route pasted a target-box ellipse and then redrew the entire face on each pass. That allowed the eyes, nose and mouth to drift and introduced visible patterned texture in the inspected two-pass result. Repeated blending against the original was fixed separately in `34c0222`.

## Implemented correction

- Parse source and target faces on CPU using a locally configured ParseNet. Warp source labels with the exact same similarity transform as reference pixels. Intersect source skin/features, target skin/features and the existing permitted face region. Hair, ears, clothing and background are excluded.
- Use ParseNet's own class taxonomy: class 7 is right eyebrow and class 13 is hair. These differ from BiSeNet. See the [upstream ParseNet example](https://github.com/xinntao/facexlib/blob/master/inference/inference_parsing_parsenet.py).
- Reject unusable geometry and clipped/occluded feature regions. Normal feathering at the hairline is not classified as occlusion.
- Apply a bounded Lab colour offset before inward feathering. No face reshaping, identity embedding, GFPGAN or texture restorer is added.
- Protect the source eyebrows, eyes, nose and mouth plus the central landmark hull and buffer. Both diffusion passes operate on the seam. A native-resolution composite mask enforces exact pixel preservation in the protected region even if VAE decoding or resizing modifies those pixels internally.
- Feather towards both the outer boundary and the protected-feature boundary. Both passes refine the preceding stage.
- Return `protected-face-v3` with `central-features-v1`. Existing v2 history remains readable and is never relabelled as protected v3. Ordinary redraw remains explicitly different and may alter facial features.
- Report reference-anchor readiness separately from ordinary redraw and reject missing components before queueing a generation. ParseNet file content participates in warm-worker compatibility checks, including replacement at the same path.

## Verification and boundaries

A real isolated CyberRealistic XL + Plus Face run processed the same saved 768px base as the previous failure, with the same reference, seed, CFG and two-pass settings. It completed in about 64 seconds, with 1,954 MiB peak PyTorch allocated CUDA memory (not total process GPU memory).

A complete live service batch then generated a new base and applied both passes through the production worker. It completed in approximately 177 seconds; the 7-step and 4-step refinement passes took 20.7s and 13.0s. All three stage image endpoints were read back successfully. The original and pixels outside the allowed face mask were preserved.

An independent CPU reconstruction matched the saved anchor exactly. Both production refinement stages changed zero pixels in the protected/outside region. After the final protection-boundary fade and feature-coverage checks, another isolated real GPU refinement completed in 45.4 seconds and was visually inspected. These are different executions; they are not a single timing measurement or a benchmark of cold end-to-end generation.

Local regressions: frontend 550 passed with TypeScript and production build; backend 1,388 passed and 2 opt-in runtime checks skipped. The final retry-readiness adjustment passed 369 focused regressions, including same-key replay after component loss and concurrent replay. Six geometry regressions cover class labels, destructive patches, clipping, continuous feathering and normal hairline acceptance. These tests establish behavior, not visual similarity.

Visual inspection found the previous conspicuous facial hatch texture reduced and the reference eyebrow, eye, nose and lip shapes better retained. Face-versus-neck shading and hairline style differences remain. This is one controlled reference/scene validation, not a calibrated identity-similarity score, an all-angle guarantee or approval of disabled experimental model routes. The second pass is still optional and not guaranteed to improve an image.

Private reference images, profiles, embeddings and experiment outputs remain outside Git. Real evidence is stored locally under `E:/Dream/test-runs/face-quality-repair-20261024/`.
