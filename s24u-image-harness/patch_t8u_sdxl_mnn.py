"""Add SDXL MNN to the pinned H6R5R1 landscape tree.

MNN stage implementation adapted from xororz/local-dream 209ba95.
The existing harness retains its independent fixed-77 conditioning chunks.
"""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
main = root / 'app/src/main'
cpp = main / 'cpp/src'
kotlin = main / 'java/io/github/xororz/localdream'

def edit(path, old, new, count=1):
    s = path.read_text(encoding='utf-8')
    assert s.count(old) == count, (str(path), old[:100], s.count(old))
    path.write_text(s.replace(old, new), encoding='utf-8')

header = Path(__file__).with_name('PipelineSdxlMnn.hpp').read_text(encoding='utf-8')
header = header.replace('text_encoder_.contextLength(req.prompt, req.negative_prompt)', '77 /* harness encodes independent fixed-77 chunks */')
header = header.replace('    if (stage == 0) net.setSessionMode', '    QNN_INFO("T8U_SDXLMNN_STAGE stage=%zu backend=%s", stage, config.type == MNN_FORWARD_OPENCL ? "OPENCL" : "CPU");\n    if (stage == 0) net.setSessionMode')
header = header.replace('    if (stage != 0) net.releaseModel();', '''    int actual_backends[8] = {-1};
    if (net.getSessionInfo(sessions_[stage], MNN::Interpreter::BACKENDS, actual_backends)) {
      QNN_INFO("T8U_SDXLMNN_ACTUAL stage=%zu backend=%d", stage, actual_backends[0]);
      if (stage == 0 && req.use_opencl && actual_backends[0] != MNN_FORWARD_OPENCL)
        throw std::runtime_error("SDXL requested OpenCL but MNN selected another backend");
    }
    if (stage != 0) net.releaseModel();''')
(cpp / 'PipelineSdxlMnn.hpp').write_text(header, encoding='utf-8')
# Reuse the baseline's dual CLIP and tiling; expose its stage paths to the MNN subclass.
edit(cpp/'PipelineSdxl.hpp', ' private:\n', ' protected:\n')
edit(cpp/'main.cpp', '#include "PipelineSdxl.hpp"', '#include "PipelineSdxl.hpp"\n#include "PipelineSdxlMnn.hpp"')
edit(cpp/'main.cpp', 'kSd15Cpu, kSd15Npu, kSdxl, kAnima', 'kSd15Cpu, kSd15Npu, kSdxl, kSdxlMnn, kAnima')
edit(cpp/'main.cpp', 'return type == ModelType::kSdxl;', 'return type == ModelType::kSdxl || type == ModelType::kSdxlMnn;')
edit(cpp/'main.cpp', 'return type == ModelType::kSd15Cpu;', 'return type == ModelType::kSd15Cpu || type == ModelType::kSdxlMnn;')
edit(cpp/'main.cpp', '  else if (typeStr == "sdxl")', '  else if (typeStr == "sdxlmnn")\n    opts.type = ServerOptions::ModelType::kSdxlMnn;\n  else if (typeStr == "sdxl")')
edit(cpp/'main.cpp', '    case ServerOptions::ModelType::kSdxl:', '''    case ServerOptions::ModelType::kSdxlMnn:
      return std::make_unique<PipelineSdxlMnn>(
          text_encoder, opts.model_dir, clip_path, clip2_path, unet_path,
          vae_decoder_path, vae_encoder_path, opts.use_v_pred, true);
    case ServerOptions::ModelType::kSdxl:''')
edit(kotlin/'data/Model.kt', 'isSdxl -> "sdxl"', 'isSdxl -> if (runOnCpu) "sdxlmnn" else "sdxl"')
edit(kotlin/'data/Model.kt', 'createCustomModel(dir, isNpu = true, isSdxl = true)', 'createCustomModel(dir, isNpu = !File(dir, "unet.mnn").exists(), isSdxl = true)')
edit(kotlin/'service/BackendService.kt', 'backendType != "sd15cpu" && backendType != BACKEND_TYPE_UPSCALER', 'backendType != "sd15cpu" && backendType != "sdxlmnn" && backendType != BACKEND_TYPE_UPSCALER')
edit(kotlin/'service/BackendService.kt', 'if (backendType == "sdxl" &&', 'if (backendType == "sdxlmnn" || backendType == "sdxl" &&')
run = kotlin/'ui/screens/ModelRunScreen.kt'
edit(run, 'model?.backendType == "sd15cpu"', 'model?.runOnCpu == true')
edit(run, 'put("backend", if (model?.runOnCpu == true) "CPU/MNN" else "NPU/QNN")', '''put("backend", if (model?.runOnCpu == true) {
                if (useOpenCL) "GPU/OpenCL + CPU CLIP/VAE" else "CPU/MNN"
            } else "NPU/QNN")
            put("unet_backend", if (model?.runOnCpu == true) { if (useOpenCL) "MNN / OpenCL" else "MNN / CPU" } else "QNN / HTP")
            put("vae_backend", if (model?.backendType == "sdxlmnn" || !useOpenCL) "MNN / CPU" else "MNN / OpenCL")''')
edit(run, 'width = if (model?.runOnCpu == true) generationParamsTmp.width else state.bitmap.width,', 'width = state.bitmap.width,')
edit(run, 'height = if (model?.runOnCpu == true) generationParamsTmp.height else state.bitmap.height,', 'height = state.bitmap.height,')
settings = kotlin/'ui/screens/AdvancedSettingsDialog.kt'
edit(settings, '                if (runOnCpu) {\n                    Column {', '                if (runOnCpu) {\n                    if (!isSdxl) Column {')
# Imported zip detection is decided from its contents, not the directory or tab name.
listing = kotlin/'ui/screens/ModelListScreen.kt'
edit(listing, 'val npuCustomFile = File(modelDir, "npucustom")\n            npuCustomFile.createNewFile()', '''if (File(modelDir, "unet.mnn").exists()) {
                File(modelDir, "finished").createNewFile()
            } else {
                File(modelDir, "npucustom").createNewFile()
            }''')
edit(listing, 'label = if (model.runOnCpu) {\n', 'label = if (model.runOnCpu && !model.isSdxl) {\n')
js = main/'assets/s24u_microscope/microscope.js'
edit(js, "backend:qnn?'QNN / HTP':'MNN / CPU',shape:`${activeChunks}", "backend:txt(s.unet_backend,qnn?'QNN / HTP':'MNN / CPU'),shape:`${activeChunks}")
edit(js, "{name:'VAE Decode',backend:qnn?'QNN / HTP':'MNN / CPU'", "{name:'VAE Decode',backend:qnn?'QNN / HTP':txt(s.vae_backend,'MNN / CPU')")
index = main/'assets/s24u_microscope/index.html'
edit(index, 'C206 · H6R5R1', 'T8U · H6R5R2 · SDXL MNN')
gradle=root/'app/build.gradle.kts'
edit(gradle, 'versionCode = 7415', 'versionCode = 7416')
edit(gradle, '2.8.1-s24u-h6r5r1-c206.3', '2.8.1-t8u-h6r5r2-sdxlmnn')
print('T8U_SDXL_MNN_SOURCE_APPLIED')
