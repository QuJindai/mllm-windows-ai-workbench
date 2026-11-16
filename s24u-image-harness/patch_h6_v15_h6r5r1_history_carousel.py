#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_gradle(root: Path) -> None:
    p = root / "app/build.gradle.kts"
    text = p.read_text(encoding="utf-8")
    text = replace_once(text, "versionCode = 7411", "versionCode = 7412", "H6R5R1 versionCode")
    text = replace_once(
        text,
        'versionName = "2.8.1-s24u-h6r5"',
        'versionName = "2.8.1-s24u-h6r5r1"',
        "H6R5R1 versionName",
    )
    p.write_text(text, encoding="utf-8")


def patch_overlay(root: Path) -> None:
    p = root / "app/src/main/java/io/github/xororz/localdream/ui/components/ZoomableImageOverlay.kt"
    text = p.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "import androidx.compose.foundation.gestures.detectTapGestures\n",
        "import androidx.compose.foundation.gestures.detectHorizontalDragGestures\n"
        "import androidx.compose.foundation.gestures.detectTapGestures\n",
        "H6R5R1 horizontal drag import",
    )
    text = replace_once(
        text,
        "import androidx.compose.material.icons.Icons\n",
        "import androidx.compose.material.icons.Icons\n"
        "import androidx.compose.material.icons.automirrored.filled.ArrowBack\n"
        "import androidx.compose.material.icons.automirrored.filled.ArrowForward\n",
        "H6R5R1 nav icon imports",
    )

    text = replace_once(
        text,
        "fun OverlayIconButton(icon: ImageVector, contentDescription: String?, onClick: () -> Unit) {\n"
        "    FilledTonalIconButton(\n"
        "        onClick = onClick,\n",
        "fun OverlayIconButton(\n"
        "    icon: ImageVector,\n"
        "    contentDescription: String?,\n"
        "    onClick: () -> Unit,\n"
        "    enabled: Boolean = true,\n"
        ") {\n"
        "    FilledTonalIconButton(\n"
        "        onClick = onClick,\n"
        "        enabled = enabled,\n",
        "H6R5R1 overlay button enabled state",
    )

    text = replace_once(
        text,
        "fun ZoomableImageOverlay(\n"
        "    bitmap: Bitmap?,\n"
        "    onDismiss: () -> Unit,\n"
        "    showScaleIndicator: Boolean = false,\n"
        "    topEndContent: @Composable RowScope.() -> Unit = {},\n"
        ") {\n"
        "    var scale by remember { mutableFloatStateOf(1f) }\n"
        "    var offsetX by remember { mutableFloatStateOf(0f) }\n"
        "    var offsetY by remember { mutableFloatStateOf(0f) }\n",
        "fun ZoomableImageOverlay(\n"
        "    bitmap: Bitmap?,\n"
        "    onDismiss: () -> Unit,\n"
        "    showScaleIndicator: Boolean = false,\n"
        "    canNavigatePrevious: Boolean = false,\n"
        "    canNavigateNext: Boolean = false,\n"
        "    navigationPosition: String? = null,\n"
        "    onPrevious: (() -> Unit)? = null,\n"
        "    onNext: (() -> Unit)? = null,\n"
        "    topEndContent: @Composable RowScope.() -> Unit = {},\n"
        ") {\n"
        "    var scale by remember(bitmap) { mutableFloatStateOf(1f) }\n"
        "    var offsetX by remember(bitmap) { mutableFloatStateOf(0f) }\n"
        "    var offsetY by remember(bitmap) { mutableFloatStateOf(0f) }\n"
        "\n"
        "    val navigationModifier = if (\n"
        "        scale <= 1.01f && (onPrevious != null || onNext != null)\n"
        "    ) {\n"
        "        Modifier.pointerInput(bitmap, canNavigatePrevious, canNavigateNext) {\n"
        "            var dragX = 0f\n"
        "            detectHorizontalDragGestures(\n"
        "                onDragStart = { dragX = 0f },\n"
        "                onHorizontalDrag = { _, dragAmount -> dragX += dragAmount },\n"
        "                onDragCancel = { dragX = 0f },\n"
        "                onDragEnd = {\n"
        "                    val threshold = size.width * 0.14f\n"
        "                    when {\n"
        "                        dragX <= -threshold && canNavigateNext -> onNext?.invoke()\n"
        "                        dragX >= threshold && canNavigatePrevious -> onPrevious?.invoke()\n"
        "                    }\n"
        "                    dragX = 0f\n"
        "                },\n"
        "            )\n"
        "        }\n"
        "    } else {\n"
        "        Modifier\n"
        "    }\n",
        "H6R5R1 carousel overlay signature",
    )

    text = replace_once(
        text,
        "            .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.9f))\n"
        "            .pointerInput(Unit) {\n",
        "            .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.9f))\n"
        "            .then(navigationModifier)\n"
        "            .pointerInput(Unit) {\n",
        "H6R5R1 navigation modifier",
    )

    text = replace_once(
        text,
        "                    offsetX += pan.x\n"
        "                    offsetY += pan.y\n",
        "                    val navigationAtBaseZoom =\n"
        "                        scale <= 1.01f && zoom in 0.99f..1.01f &&\n"
        "                            (onPrevious != null || onNext != null)\n"
        "                    if (!navigationAtBaseZoom) {\n"
        "                        offsetX += pan.x\n"
        "                        offsetY += pan.y\n"
        "                    }\n",
        "H6R5R1 base zoom swipe arbitration",
    )

    nav_anchor = '''        Box(
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 16.dp, bottom = 16.dp),
        ) {
'''
    nav_ui = '''        if (onPrevious != null) {
            Box(
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .padding(start = 12.dp),
            ) {
                OverlayIconButton(
                    icon = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "previous history image S24U_H6R5R1_HISTORY_CAROUSEL",
                    onClick = onPrevious,
                    enabled = canNavigatePrevious,
                )
            }
        }

        if (onNext != null) {
            Box(
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .padding(end = 12.dp),
            ) {
                OverlayIconButton(
                    icon = Icons.AutoMirrored.Filled.ArrowForward,
                    contentDescription = "next history image",
                    onClick = onNext,
                    enabled = canNavigateNext,
                )
            }
        }

        if (navigationPosition != null) {
            Text(
                text = navigationPosition,
                color = Color.White,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = if (showScaleIndicator) 56.dp else 16.dp)
                    .background(
                        color = MaterialTheme.colorScheme.scrim.copy(alpha = 0.5f),
                        shape = MaterialTheme.shapes.extraSmall,
                    )
                    .padding(horizontal = 10.dp, vertical = 5.dp),
            )
        }

'''
    text = replace_once(text, nav_anchor, nav_ui + nav_anchor, "H6R5R1 carousel navigation controls")
    p.write_text(text, encoding="utf-8")


def patch_history(root: Path) -> None:
    p = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/HistoryScreen.kt"
    text = p.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "    var previewItem by remember { mutableStateOf<HistoryItem?>(null) }\n"
        "    var showParamsDialog by remember { mutableStateOf(false) }\n",
        "    var previewItem by remember { mutableStateOf<HistoryItem?>(null) }\n"
        "    var previewIds by remember { mutableStateOf<List<Long>>(emptyList()) }\n"
        "    var previewIndex by remember { mutableStateOf(-1) }\n"
        "    var previewLoading by remember { mutableStateOf(false) }\n"
        "    var showParamsDialog by remember { mutableStateOf(false) }\n",
        "H6R5R1 carousel state",
    )

    helper_anchor = "    val scrollBehavior = TopAppBarDefaults.pinnedScrollBehavior()\n"
    helpers = '''    fun dismissPreview() {
        previewItem = null
        previewIds = emptyList()
        previewIndex = -1
        previewLoading = false
        showParamsDialog = false
        showShareDialog = false
        showDeleteDialog = false
    }

    fun openPreview(item: HistoryItem) {
        previewItem = item
        previewIds = listOf(item.id)
        previewIndex = 0
        previewLoading = true
        scope.launch {
            val ids = historyManager.queryIds(historyFilter)
            if (previewItem?.id == item.id && ids.isNotEmpty()) {
                val index = ids.indexOf(item.id)
                if (index >= 0) {
                    previewIds = ids
                    previewIndex = index
                }
            }
            previewLoading = false
        }
    }

    fun navigatePreview(delta: Int) {
        if (previewLoading) return
        val targetIndex = previewIndex + delta
        if (targetIndex !in previewIds.indices) return
        val targetId = previewIds[targetIndex]
        previewLoading = true
        scope.launch {
            val target = historyManager.getItems(listOf(targetId)).firstOrNull()
            if (target != null) {
                previewIndex = targetIndex
                previewItem = target
            } else {
                // The row may have disappeared since the overlay opened. Refresh
                // the id sequence without forcing the user back to the grid.
                val refreshed = historyManager.queryIds(historyFilter)
                val currentId = previewItem?.id
                previewIds = refreshed
                previewIndex = if (currentId == null) -1 else refreshed.indexOf(currentId)
            }
            previewLoading = false
        }
    }

'''
    text = replace_once(text, helper_anchor, helpers + helper_anchor, "H6R5R1 carousel helpers")

    text = replace_once(
        text,
        "                    } else {\n"
        "                        previewItem = item\n"
        "                    }\n",
        "                    } else {\n"
        "                        openPreview(item)\n"
        "                    }\n",
        "H6R5R1 open carousel from history grid",
    )

    text = replace_once(
        text,
        "        ZoomableImageOverlay(\n"
        "            bitmap = previewBitmap,\n"
        "            onDismiss = { previewItem = null },\n"
        "            topEndContent = {\n",
        "        ZoomableImageOverlay(\n"
        "            bitmap = previewBitmap,\n"
        "            onDismiss = { dismissPreview() },\n"
        "            canNavigatePrevious = !previewLoading && previewIndex > 0,\n"
        "            canNavigateNext = !previewLoading && previewIndex >= 0 && previewIndex < previewIds.lastIndex,\n"
        "            navigationPosition = if (previewIndex >= 0 && previewIds.isNotEmpty()) {\n"
        "                \"${previewIndex + 1} / ${previewIds.size}\"\n"
        "            } else {\n"
        "                null\n"
        "            },\n"
        "            onPrevious = { navigatePreview(-1) },\n"
        "            onNext = { navigatePreview(1) },\n"
        "            topEndContent = {\n",
        "H6R5R1 carousel overlay wiring",
    )

    old_delete = '''                onConfirm = {
                    scope.launch {
                        val success = historyManager.deleteHistoryItem(item)
                        showDeleteDialog = false
                        if (success) {
                            previewItem = null
                            Toast.makeText(context, msgDeleted, Toast.LENGTH_SHORT).show()
                        } else {
                            Toast.makeText(context, msgDeleteFailed, Toast.LENGTH_SHORT).show()
                        }
                    }
                },
'''
    new_delete = '''                onConfirm = {
                    scope.launch {
                        previewLoading = true
                        val removedIndex = previewIndex
                        val remainingIds = previewIds.filterNot { it == item.id }
                        val success = historyManager.deleteHistoryItem(item)
                        showDeleteDialog = false
                        if (success) {
                            previewIds = remainingIds
                            if (remainingIds.isEmpty()) {
                                previewItem = null
                                previewIndex = -1
                            } else {
                                val newIndex = removedIndex.coerceAtMost(remainingIds.lastIndex)
                                    .coerceAtLeast(0)
                                val nextItem = historyManager.getItems(
                                    listOf(remainingIds[newIndex]),
                                ).firstOrNull()
                                if (nextItem != null) {
                                    previewIndex = newIndex
                                    previewItem = nextItem
                                } else {
                                    previewItem = null
                                    previewIndex = -1
                                }
                            }
                            Toast.makeText(context, msgDeleted, Toast.LENGTH_SHORT).show()
                        } else {
                            Toast.makeText(context, msgDeleteFailed, Toast.LENGTH_SHORT).show()
                        }
                        previewLoading = false
                    }
                },
'''
    text = replace_once(text, old_delete, new_delete, "H6R5R1 delete carousel continuity")
    p.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v15_h6r5r1_history_carousel.py <h6r5-patched-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_overlay(root)
    patch_history(root)
    print("S24U_IMAGE_HARNESS_H6R5R1_HISTORY_CAROUSEL_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
