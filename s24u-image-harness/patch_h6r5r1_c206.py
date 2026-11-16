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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_h6r5r1_c206.py <H6R5R1 Local Dream source root>")
    apply(Path(sys.argv[1]).resolve())
