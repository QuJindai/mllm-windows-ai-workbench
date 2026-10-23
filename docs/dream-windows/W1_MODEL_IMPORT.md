# W1 Windows model import contract

The first Windows model is `cyberrealistic-xl-v10-standard`, recorded in
`config/dream/model-registry.json`.

The source artifact is the creator's public FP16 mirror on Hugging Face because
the Civitai download endpoint requires an authenticated browser session. The
source SHA-256 is independently verified as
`FD5E870B5BBCE4BDDEB64F4BB8E49C57F84AB793C0262A503F0123BE435E667D`.
The local Windows GGUF conversion is `q8_0` with SHA-256
`48A2D2A0FAA6332B3D8718707FEDBA750C75854904389C134B9535E23B1639F6`.
The registry is marked `status: installed` only after both files were verified
and placed below `E:\Dream\models`.

The Android branch and commit in the registry are provenance only:
`feature/s24u-image-harness-h6r5-semantic-fidelity` at
`381713f6985e1d48da16a14636989a4b27f1ae98`. Android QNN files such as
`unet.bin` are not Windows model files and must never be registered as GGUF.
`android_reference` is optional for models acquired directly for Windows. When
it is present, the validator still requires a branch, a 40-character commit,
and `artifact_policy: reference-only`; it must never be invented merely to
make a Windows-only model pass validation.

## Import sequence

1. Acquire the exact CyberRealistic v10 SDXL source artifact and place it in
   `E:\Dream\models\source`.
2. Record the source SHA-256 in the registry.
3. Convert or obtain a compatible `stable-diffusion.cpp` GGUF under
   `E:\Dream\models\windows`.
4. Record the GGUF SHA-256 and set `status` to `installed` only after the file
   is present and independently verified. The Windows runtime default is the
   balanced standard SDXL profile: DPM++ 2M SDE, Karras schedule, 20 steps,
   CFG 4, and a 512 x 512 startup canvas. The local GGUF is not treated as a
   dedicated DMD2-distilled artifact unless a separate model artifact proves
   that identity.
5. Run `scripts/validate_model_registry.ps1 -Root E:\Dream` and preserve the
   JSON report under `E:\Dream\data\metadata`.

The current registry records the completed local import and conversion.

## Sampling parity and incident finding

The Android reference remains useful implementation evidence, but Windows uses
a 6 GB VRAM-specific balanced startup profile. The Windows wrapper must receive
the selected values from the request and record the values actually used in the
sidecar metadata.

The previous Windows wrapper hard-coded LCM plus an exponential schedule while
the installed GGUF was loaded as a regular SDXL checkpoint. A same-seed A/B
run on the local RTX 1000 Ada produced a washed-out image with the old profile
and a valid detailed image with DPM++ 2M/Karras, 20 steps, and CFG 7. This is
why the default is now fail-closed to the standard SDXL profile; LCM remains
available only as an explicit request for a separately verified distilled
artifact.
