"""Apply the C206 UI to a fully patched H6R5R1 tree after packaging the phone APK."""
from pathlib import Path
import shutil
import sys

from patch_h6_v15_h6r5r1_history_carousel import replace_once


def edit(path, edits):
    text = path.read_text(encoding="utf-8")
    for old, new in edits:
        text = replace_once(text, old, new, str(path))
    path.write_text(text, encoding="utf-8")


def apply_car_identity(main, kotlin):
    resources = main / "res"
    shutil.copytree(Path(__file__).with_name("c206") / "res", resources, dirs_exist_ok=True)
    for path in resources.glob("values*/strings.xml"):
        contents = path.read_text(encoding="utf-8")
        contents = contents.replace("Local Dream", "HQ 绘梦").replace("S24U Image Harness", "HQ 绘梦")
        # Standalone listening uses the dedicated local port. Host mode still uses the wire protocol port.
        lines = [line.replace("8081", "18081") if 'name="listen_on_all_addresses_hint"' in line else line
                 for line in contents.splitlines(keepends=True)]
        path.write_text("".join(lines), encoding="utf-8")
    edit(kotlin / "ui/screens/ModelListScreen.kt", [
        ('text = "Local Dream✨"', 'text = stringResource(R.string.app_name)'),
    ])
    edit(kotlin / "ui/screens/ModelRunScreen.kt", [
        ('"S24U HARNESS · PURE RAW"', '"HQ 绘梦 · PURE RAW"'),
    ])
    edit(kotlin / "ui/components/ParamShareDialogs.kt", [('"Local Dream params"', '"HQ 绘梦 params"')])
    edit(main / "assets/s24u_microscope/index.html", [
        ('<title>S24U H6 Conditioning Influence Microscope</title>', '<title>HQ 绘梦 · 扩散显微镜</title>'),
        ('>C206 · H6R5R1<', '>HQ 绘梦 · C206 · H6R5R1<'),
    ])


def isolate_local_backend(kotlin):
    service = kotlin / "service"
    edit(service / "BackgroundGenerationService.kt", [
        ('const val LOCAL_BACKEND_HOST = "localhost:8081"',
         'const val LOCAL_BACKEND_PORT = 18081\n        const val LOCAL_BACKEND_HOST = "localhost:$LOCAL_BACKEND_PORT"'),
    ])
    edit(service / "BackendService.kt", [
        ('import io.github.xororz.localdream.data.Model', 'import io.github.xororz.localdream.data.Model\nimport io.github.xororz.localdream.remote.RemoteProtocol'),
        ('val listenOnAll: Boolean,', 'val listenOnAll: Boolean,\n        val port: Int,'),
        ('        val listenOnAll = getSharedPreferences', '        val hosting = RemoteHostService.isRunning.value\n        val listenOnAll = getSharedPreferences'),
        ('            RemoteHostService.isRunning.value\n        return BackendConfig(modelId, backendType, width, height, listenOnAll)',
         '            hosting\n        val port = if (hosting) RemoteProtocol.GENERATION_PORT else BackgroundGenerationService.LOCAL_BACKEND_PORT\n        return BackendConfig(modelId, backendType, width, height, listenOnAll, port)'),
        ('runtimeDir.absolutePath,\n                    "--port",\n                    "8081",', 'runtimeDir.absolutePath,\n                    "--port",\n                    config.port.toString(),'),
        ('modelsDir.absolutePath,\n                    "--port",\n                    "8081",', 'modelsDir.absolutePath,\n                    "--port",\n                    config.port.toString(),'),
    ])
    edit(kotlin / "ui/screens/ModelRunSupport.kt", [
        ('"http://localhost:8081/health"', '"http://${BackgroundGenerationService.LOCAL_BACKEND_HOST}/health"'),
    ])
    edit(kotlin / "ui/screens/UpscaleScreen.kt", [('"8081",', 'BackgroundGenerationService.LOCAL_BACKEND_PORT.toString(),')])


def fix_cpu_microscope(main, kotlin):
    edit(kotlin / "ui/screens/ModelRunScreen.kt", [
        ('    val h6r5UnetSha256 by produceState(', '''    val unetFileName = if (model?.backendType == "sd15cpu") "unet.mnn" else "unet.bin"
    val h6r5UnetSha256 by produceState('''),
        ('        modelId, model?.id, isRemote,\n    ) {\n        value = if (isRemote) "remote-unavailable" else withContext(Dispatchers.IO) {\n            h6r5CachedSha256(context, model?.id ?: modelId, "unet.bin")',
         '''        modelId, model?.id, unetFileName, isRemote,
    ) {
        value = if (isRemote) "remote-unavailable" else withContext(Dispatchers.IO) {
            h6r5CachedSha256(context, model?.id ?: modelId, unetFileName)'''),
        ('    val h6r5ModelLoras by produceState(', '''    val unetWeightsSha256 by produceState<String?>(null, modelId, model?.id, unetFileName, isRemote) {
        value = if (isRemote || unetFileName != "unet.mnn") null else withContext(Dispatchers.IO) {
            h6r5CachedSha256(context, model?.id ?: modelId, "unet.mnn.weight")
        }
    }
    val h6r5ModelLoras by produceState('''),
        ('put("unet_sha256", h6r5UnetSha256)', 'put("unet_sha256", h6r5UnetSha256)\n            put("unet_hash_file", unetFileName)\n            unetWeightsSha256?.let { put("unet_weights_sha256", it) }'),
    ])
    edit(main / "assets/s24u_microscope/microscope.js", [
        ('unet SHA256=${txt(s.unet_sha256)}', '${txt(s.unet_hash_file,\'U-Net\')} SHA256=${txt(s.unet_sha256)}${s.unet_weights_sha256 ? ` · unet.mnn.weight SHA256=${s.unet_weights_sha256}` : \'\'}'),
        ("if(preservation){const pos=Boolean(s.positive_token_preserved)", '''if (preservation && !arr(s.positive_chunk_token_ids).length && !arr(s.negative_chunk_token_ids).length) {
      preservation.className = 'attention-state';
      preservation.textContent = '等待后端返回 Token 记录';
    } else if(preservation){const pos=Boolean(s.positive_token_preserved)'''),
    ])


def enable_model_history_carousel(kotlin):
    edit(kotlin / "ui/screens/ModelRunScreen.kt", [
        ('import androidx.compose.runtime.rememberCoroutineScope', 'import androidx.compose.runtime.key\nimport androidx.compose.runtime.rememberCoroutineScope'),
        ('''        val historyBitmap by produceState<Bitmap?>(null, detailImagePath) {
            value = withContext(Dispatchers.IO) {
                detailImagePath?.let { BitmapFactory.decodeFile(it) }
            }
        }
        val dismissDetail = {''', '''        val historyBitmap by key(detailImagePath) {
            produceState<Bitmap?>(null) {
                value = withContext(Dispatchers.IO) { detailImagePath?.let { BitmapFactory.decodeFile(it) } }
            }
        }
        val detailIds by produceState(emptyList<Long>(), historyFilter, historyTotalCount) {
            value = historyManager.queryIds(historyFilter)
        }
        val currentId = selectedHistoryItem?.id
        val detailIndex = remember(detailIds, currentId) { currentId?.let(detailIds::indexOf) ?: -1 }
        val detailScope = rememberCoroutineScope()
        fun moveDetail(delta: Int) {
            if (detailIndex < 0) return
            val targetId = detailIds.getOrNull(detailIndex + delta) ?: return
            detailScope.launch {
                val next = historyManager.getItems(listOf(targetId)).firstOrNull()
                if (next != null && selectedHistoryItem?.id == currentId) selectedHistoryItem = next
            }
        }
        val dismissDetail = {'''),
        ('''            bitmap = historyBitmap,
            onDismiss = dismissDetail,
            topEndContent = {''', '''            bitmap = historyBitmap,
            onDismiss = dismissDetail,
            canNavigatePrevious = detailIndex > 0,
            canNavigateNext = detailIndex >= 0 && detailIndex < detailIds.lastIndex,
            navigationPosition = if (detailIndex >= 0) "${detailIndex + 1} / ${detailIds.size}" else null,
            onPrevious = { moveDetail(-1) },
            onNext = { moveDetail(1) },
            topEndContent = {'''),
    ])


def apply(root):
    app = root / "app"
    main = app / "src/main"
    kotlin = main / "java/io/github/xororz/localdream"
    edit(app / "build.gradle.kts", [
        ("versionCode = 7412", "versionCode = 7413"),
        ('versionName = "2.8.1-s24u-h6r5r1"', 'versionName = "2.8.1-s24u-h6r5r1-c206.1"'),
    ])
    edit(main / "AndroidManifest.xml", [
        ('android:screenOrientation="portrait"',
         'android:resizeableActivity="true"\n            android:screenOrientation="landscape"'),
    ])
    edit(kotlin / "MainActivity.kt", [
        ("import androidx.compose.ui.Modifier", """import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density"""),
        ("            CompositionLocalProvider(LocalThemeController provides themeController) {",
         """            val density = LocalDensity.current
            val wide = LocalConfiguration.current.screenWidthDp >= 1000
            val touchDensity = remember(density, wide) {
                if (wide) Density(density.density * 1.5f, density.fontScale) else density
            }
            CompositionLocalProvider(LocalThemeController provides themeController, LocalDensity provides touchDensity) {"""),
    ])
    edit(kotlin / "ui/screens/ModelListScreen.kt", [
        ("import androidx.compose.foundation.lazy.LazyColumn", """import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems"""),
        ("""                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (page == 0 && !remoteActive) {""",
         """                LazyVerticalGrid(
                    columns = GridCells.Adaptive(360.dp),
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 24.dp, vertical = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (page == 0 && !remoteActive) {"""),
        ("                    items(\n                        items = models,",
         "                    gridItems(\n                        items = models,"),
        ("if (models.isEmpty() && modelRepository.isLoaded) {\n                        item {",
         "if (models.isEmpty() && modelRepository.isLoaded) {\n                        item(span = { GridItemSpan(maxLineSpan) }) {"),
    ])
    edit(kotlin / "ui/screens/ModelRunPages.kt", [
        ("columns = GridCells.Fixed(2),", "columns = GridCells.Adaptive(205.dp),"),
    ])
    edit(kotlin / "ui/components/ZoomableImageOverlay.kt", [
        ("import androidx.compose.foundation.layout.aspectRatio", """import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding"""),
        ("            .then(navigationModifier)",
         "            .windowInsetsPadding(WindowInsets.safeDrawing)\n            .then(navigationModifier)"),
        ("""                    // The image is laid out as a centered square of this side,
                    // then ContentScale.Fit letterboxes the bitmap inside it by
                    // its aspect ratio, then graphicsLayer scales about the
                    // center and translates. Reproduce that to get the actual
                    // visible image rect so taps in the letterbox (a non-square
                    // image) dismiss too, not only taps outside the square.
                    val square = minOf(size.width, size.height).toFloat()
                    val aspect = bmp.width.toFloat() / bmp.height.toFloat()
                    val baseWidth = if (aspect >= 1f) square else square * aspect
                    val baseHeight = if (aspect >= 1f) square / aspect else square""",
         """                    // Hit-test the bitmap inside the same safe viewport used by ContentScale.Fit.
                    val fit = minOf(size.width.toFloat() / bmp.width, size.height.toFloat() / bmp.height)
                    val baseWidth = bmp.width * fit
                    val baseHeight = bmp.height * fit"""),
        ("                    .fillMaxWidth()\n                    .aspectRatio(1f, matchHeightConstraintsFirst = true)",
         "                    .fillMaxSize()"),
        ("                .padding(top = 60.dp, end = 16.dp),", "                .padding(top = 8.dp, end = 16.dp),"),
    ])
    microscope = main / "assets/s24u_microscope"
    edit(microscope / "index.html", [
        ('  <link rel="stylesheet" href="microscope.css">',
         '  <link rel="stylesheet" href="microscope.css">\n  <link rel="stylesheet" href="c206.css">'),
        ("S24U H6 · LIVE", "C206 · H6R5R1"),
    ])
    shutil.copyfile(Path(__file__).with_name("c206") / "microscope.css", microscope / "c206.css")
    apply_car_identity(main, kotlin)
    isolate_local_backend(kotlin)
    fix_cpu_microscope(main, kotlin)
    enable_model_history_carousel(kotlin)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_h6r5r1_c206.py <H6R5R1 Local Dream source root>")
    apply(Path(sys.argv[1]).resolve())
