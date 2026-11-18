# T8U DiT microscope 7421

The Android source overlay includes model-specific trace selection, a shared heatmap scale per run and channel, a separate final latent view, and the capture switch that defaults to off.

1. Prepare the T8U 7416 Local Dream tree using the source preparation and patch steps in the T8U SDXL MNN workflow.
2. In a separate copy of that tree, run `python s24u-image-harness/dit-microscope/apply.py <local-dream-tree> <HexAnima-1.7.1.apk>` from this repository. Python 3.11+ and Git are required. The script checks the APK SHA-256 and extracts the upstream runtime and assets.
3. Build the Android app from the prepared tree. Use the existing Local Dream native build inputs and Android toolchain. To upgrade an existing installation, sign with the matching key.

The overlay contains Java, JavaScript, Android resources and the integration patch. Model weights, APKs, local settings and signing keys are supplied separately. The HexAnima code and license are based on [HexAnima v1.7.1](https://github.com/ayanoby/hexanima/tree/v1.7.1). The existing workflow builds the SDXL MNN base.
