from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from research_traces import InvalidArtifact, read_bounded_json


@dataclass(frozen=True)
class DreamServerConfig:
    repo_root: Path
    dream_root: Path
    core_exe: Path
    engine_exe: Path
    wrapper: Path
    registry_path: Path
    frontend_dist: Path
    host: str = "127.0.0.1"
    port: int = 8866

    @property
    def persistent_engine_exe(self) -> Path:
        return Path(os.environ.get("DREAM_SDCPP_SERVER_EXE") or self.engine_exe.with_name("sd-server.exe"))

    @property
    def persistent_engine_url(self) -> str:
        value = os.environ.get("DREAM_SDCPP_SERVER_URL", "http://127.0.0.1:12444").rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port is None:
            raise ValueError("DREAM_SDCPP_SERVER_URL must be an explicit localhost HTTP URL with a port")
        return value

    @property
    def h7_engine_exe(self) -> Path:
        return Path(os.environ.get("DREAM_H7_SDCPP_EXE") or self.dream_root / "app" / "stable-diffusion-cuda-h7" / "sd-cli.exe")

    @property
    def h7_manifest_path(self) -> Path:
        return self.h7_engine_exe.with_name("build-manifest.json")

    def h7_attention_ready(self) -> bool:
        return "h7-attention-v1" in self.research_capabilities()

    def h6_conditioning_ready(self) -> bool:
        return "h6-conditioning-v1" in self.research_capabilities()

    def h7_self_attention_ready(self) -> bool:
        return "h7-self-attention-v1" in self.research_capabilities()

    def h7_research_ready(self) -> bool:
        return {"h7-attention-v1", "h6-conditioning-v1", "h7-self-attention-v1"} <= self.research_capabilities()

    def research_capabilities(self) -> set[str]:
        if not self.h7_engine_exe.is_file() or not self.h7_manifest_path.is_file():
            return set()
        try:
            manifest = read_bounded_json(self.h7_manifest_path, 64 * 1024)
        except InvalidArtifact:
            return set()
        capabilities = manifest.get("capabilities")
        valid = (
            type(manifest.get("schemaVersion")) is int and manifest["schemaVersion"] == 1
            and manifest.get("executable") == self.h7_engine_exe.name
            and manifest.get("source") == "debug-unet"
            and isinstance(capabilities, list) and len(capabilities) <= 32
            and all(isinstance(value, str) and 1 <= len(value) <= 128 for value in capabilities)
        )
        return set(capabilities) if valid and len(set(capabilities)) == len(capabilities) else set()

    @classmethod
    def from_environment(cls) -> "DreamServerConfig":
        repo_root = Path(os.environ.get("DREAM_REPO_ROOT") or Path(__file__).resolve().parents[3]).resolve()
        dream_root = Path(os.environ.get("DREAM_HOME") or r"E:\Dream").resolve()
        engine_root = Path(os.environ.get("DREAM_STABLE_DIFFUSION_CPP_ROOT") or dream_root / "app" / "stable-diffusion-cpp")
        return cls(
            repo_root=repo_root,
            dream_root=dream_root,
            core_exe=Path(os.environ.get("DREAM_CORE_EXE") or dream_root / "app" / "current" / "dream-core.exe"),
            engine_exe=Path(os.environ.get("DREAM_STABLE_DIFFUSION_CPP_EXE") or engine_root / "sd-cli.exe"),
            wrapper=Path(os.environ.get("DREAM_SDCPP_GENERATE_WRAPPER") or repo_root / "scripts" / "run_stable_diffusion_wrapper.cmd"),
            registry_path=Path(os.environ.get("DREAM_MODEL_REGISTRY") or repo_root / "config" / "dream" / "model-registry.json"),
            frontend_dist=Path(os.environ.get("DREAM_FRONTEND_DIST") or dream_root / "builds" / "dream-windows" / "frontend"),
            host=os.environ.get("DREAM_WEB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DREAM_WEB_PORT", "8866")),
        )

    @classmethod
    def for_testing(cls) -> "DreamServerConfig":
        root = Path(r"E:\Dream")
        return cls(
            repo_root=Path(__file__).resolve().parents[3],
            dream_root=root,
            core_exe=root / "app" / "current" / "dream-core.exe",
            engine_exe=root / "app" / "stable-diffusion-cpp" / "sd-cli.exe",
            wrapper=Path("run_stable_diffusion_wrapper.cmd"),
            registry_path=Path("model-registry.json"),
            frontend_dist=Path("dist"),
        )

    def path_under_dream(self, value: Path) -> bool:
        try:
            value.resolve().relative_to(self.dream_root.resolve())
            return True
        except ValueError:
            return False
