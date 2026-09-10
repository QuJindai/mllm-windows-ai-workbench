from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", alias="negativePrompt", max_length=2000)
    model_id: str = Field(min_length=1, alias="modelId")
    width: int = Field(default=768, ge=256, le=2048)
    height: int = Field(default=768, ge=256, le=2048)
    steps: int = Field(default=20, ge=1, le=50)
    cfg: float = Field(default=4.0, ge=0, le=30)
    sampling_method: Literal["dpm++2m", "dpm++2m_sde", "lcm", "euler", "euler_a"] = Field(default="dpm++2m_sde", alias="samplingMethod")
    scheduler: Literal["karras", "discrete", "exponential", "lcm"] = "karras"
    seed: int | Literal["random"] = "random"
    fusion_mode: str = Field(default="none", alias="fusionMode")
    trace_level: Literal["off", "basic", "h6", "h7"] = Field(default="basic", alias="traceLevel")

    @field_validator("width", "height")
    @classmethod
    def dimensions_are_aligned(cls, value: int) -> int:
        if value % 8 != 0:
            raise ValueError("width and height must be multiples of 8")
        return value

    @field_validator("prompt")
    @classmethod
    def prompt_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value.strip()


class FavoriteRequest(BaseModel):
    value: bool


class ExperimentRequest(BaseModel):
    kind: Literal["fusion", "steps", "model"] = "fusion"
    seed: int = Field(ge=0, le=2147483647)
    model_id: str = Field(min_length=1, alias="modelId")
    prompt: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    negative_prompt: str = Field(default="", alias="negativePrompt", max_length=2000)
    steps: int = Field(default=20, ge=1, le=50)
    cfg: float = Field(default=4.0, ge=0, le=30)

    model_config = ConfigDict(populate_by_name=True)


class WorkspaceOpenRequest(BaseModel):
    entry: Literal["base", "models", "outputs", "history", "cache", "logs"]


class SettingsUpdateRequest(BaseModel):
    autopilot_enabled: bool | None = Field(default=None, alias="autopilotEnabled")
    precision_mode: Literal["fp16", "fp32"] | None = Field(default=None, alias="precisionMode")
    fallback_to_cpu: bool | None = Field(default=None, alias="fallbackToCpu")
    tile_mode: Literal["automatic", "enabled", "disabled"] | None = Field(default=None, alias="tileMode")
    vae_memory_mode: Literal["sliced", "full"] | None = Field(default=None, alias="vaeMemoryMode")
    attention_slicing: bool | None = Field(default=None, alias="attentionSlicing")
    vram_threshold_gb: int | None = Field(default=None, alias="vramThresholdGb", ge=1, le=12)
    optimization_level: Literal["conservative", "balanced", "aggressive"] | None = Field(default=None, alias="optimizationLevel")

    model_config = ConfigDict(populate_by_name=True)


class ApiErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)
