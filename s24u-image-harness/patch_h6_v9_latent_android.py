#!/usr/bin/env python3
from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_service(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        val format: String = "jpeg",
        val imageBase64: String,
    )
''',
        '''        val format: String = "jpeg",
        val imageBase64: String,
        val channelStats: List<Float> = emptyList(),
        val channelCorrelation: List<Float> = emptyList(),
        val channelHistograms: List<Float> = emptyList(),
    )
''',
        "preview inspector fields",
    )
    text = replace_once(
        text,
        '''        val dynamicsUnetMs: Long = 0L,
        val dynamicsSchedulerMs: Long = 0L,
    )
''',
        '''        val dynamicsUnetMs: Long = 0L,
        val dynamicsSchedulerMs: Long = 0L,
        val channelStats: List<Float> = emptyList(),
        val channelCorrelation: List<Float> = emptyList(),
        val channelHistograms: List<Float> = emptyList(),
    )
''',
        "event inspector fields",
    )
    text = replace_once(
        text,
        '''            dynamicsUnetMs = message.optLong("dynamics_unet_ms", 0L),
            dynamicsSchedulerMs = message.optLong("dynamics_scheduler_ms", 0L),
        )
''',
        '''            dynamicsUnetMs = message.optLong("dynamics_unet_ms", 0L),
            dynamicsSchedulerMs = message.optLong("dynamics_scheduler_ms", 0L),
            channelStats = jsonFloatList(message, "channel_stats"),
            channelCorrelation = jsonFloatList(message, "channel_correlation"),
            channelHistograms = jsonFloatList(message, "channel_histograms"),
        )
''',
        "inspector parser",
    )
    text = replace_once(
        text,
        '''                format = "jpeg",
                imageBase64 = event.imageBase64,
            )
''',
        '''                format = "jpeg",
                imageBase64 = event.imageBase64,
                channelStats = event.channelStats,
                channelCorrelation = event.channelCorrelation,
                channelHistograms = event.channelHistograms,
            )
''',
        "latent preview inspector fields",
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''            put("format", preview.format)
            put("image_base64", preview.imageBase64)
        }
''',
        '''            put("format", preview.format)
            put("image_base64", preview.imageBase64)
            put("channel_stats", floatArrayJson(preview.channelStats))
            put("channel_correlation", floatArrayJson(preview.channelCorrelation))
            put("channel_histograms", floatArrayJson(preview.channelHistograms))
        }
''',
        "preview inspector bridge",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v9_latent_android.py <h6r3-task4-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_service(root)
    patch_screen(root)
    print("S24U_IMAGE_HARNESS_H6R3_LATENT_ANDROID_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
