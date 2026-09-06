# W1 Windows model import contract

The first Windows model is `cyberrealistic-v10-dmd2`, recorded in
`config/dream/model-registry.json`.

The registry deliberately starts with `status: uninstalled`. Until the source
artifact and the Windows GGUF conversion are acquired, independently hashed,
and placed below `E:\Dream\models`, the W1 gate must stop. A missing model is
not replaced with another checkpoint and does not produce a placeholder PNG.

The Android branch and commit in the registry are provenance only:
`feature/s24u-image-harness-h6r5-semantic-fidelity` at
`381713f6985e1d48da16a14636989a4b27f1ae98`. Android QNN files such as
`unet.bin` are not Windows model files and must never be registered as GGUF.

## Import sequence

1. Acquire the exact CyberRealistic v10 DMD2 source artifact and place it in
   `E:\Dream\models\incoming`.
2. Record the source SHA-256 in the registry.
3. Convert or obtain a compatible `stable-diffusion.cpp` GGUF under
   `E:\Dream\models\windows`.
4. Record the GGUF SHA-256 and set `status` to `installed` only after the file
   is present and independently verified.
5. Run `scripts/validate_model_registry.ps1 -Root E:\Dream` and preserve the
   JSON report under `E:\Dream\data\metadata`.

The current registry is an identity and path contract, not proof that the
model is installed.
