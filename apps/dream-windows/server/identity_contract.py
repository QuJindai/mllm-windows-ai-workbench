from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal
from identity_models import is_visual_model_id, MODEL_SPECS


class IdentityGenerateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, strict=True)
    modelId: Literal['realistic-vision-v5.1-faceid', 'illustrious-xl-v2.0-faceid', 'cyberrealistic-xl-plus-face', 'illustrious-xl-v2.0-plus-face'] = 'realistic-vision-v5.1-faceid'
    referenceId: str = Field(pattern=r'^ref-[a-f0-9]{24}$')
    faceIndex: int = Field(ge=0, le=19)
    prompt: str = Field(min_length=1, max_length=2000)
    negativePrompt: str = Field(default='', max_length=2000)
    seed: int | Literal['random'] = 'random'
    width: int = Field(default=512, ge=256, le=768)
    height: int = Field(default=768, ge=256, le=768)
    steps: int = Field(default=28, ge=1, le=50)
    cfg: float = Field(default=5.5, ge=1.01, le=15)
    identityStrength: float = Field(default=.82, ge=0, le=1.5)
    referenceStart: float = Field(default=0., ge=0, le=1)
    referenceEnd: float = Field(default=1., ge=0, le=1)
    structureStrength: float = Field(default=.9, ge=0, le=1.5)
    faceLoraStrength: float = Field(default=.55, ge=0, le=1.5)
    loraId: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    loraStrength: float = Field(default=.6, ge=0, le=1.5)
    facePolish: bool = False
    animeProfileId: str | None = Field(default=None, pattern=r'^anime-[a-f0-9]{24}$')
    animeDenoiseStrength: float = Field(default=.35, ge=.15, le=.65)
    visualPolishMode: Literal['redraw', 'reference-anchor'] = 'redraw'
    visualAnchorStrength: float = Field(default=.95, ge=.3, le=1)
    visualPolishPasses: int = Field(default=1, ge=1, le=2)
    visualPolishPrompt: str = Field(default='', max_length=2000)
    visualPolishNegativePrompt: str = Field(default='', max_length=2000)
    faceRestoreStrength: float = Field(default=1.0, ge=0, le=1)
    traceLevel: Literal['off', 'basic', 'h6', 'h7'] = 'off'
    researchCoverage: Literal['representative', 'extended'] = 'representative'

    @model_validator(mode='after')
    def bounded_research(self):
        if self.referenceStart >= self.referenceEnd:
            raise ValueError('参考采样区间起点必须小于终点')
        if not is_visual_model_id(self.modelId) and (self.referenceStart, self.referenceEnd) != (0., 1.):
            raise ValueError('参考采样区间仅支持视觉参考模型')
        if not is_visual_model_id(self.modelId) and (self.visualPolishMode != 'redraw' or self.visualPolishPasses != 1):
            raise ValueError('参考脸对齐与多轮修脸仅支持视觉参考模型')
        if is_visual_model_id(self.modelId):
            if self.animeProfileId:
                raise ValueError('动漫视觉参考修脸使用当前参考图，请清除混合动漫修脸档案')
            if self.structureStrength or self.faceLoraStrength:
                raise ValueError('动漫视觉参考不使用 FaceID 结构权重或身份 LoRA，请设为 0')
        if self.facePolish and self.animeProfileId and self.modelId != 'illustrious-xl-v2.0-faceid':
            raise ValueError('动漫档案修脸仅支持 Illustrious XL 底模')
        if MODEL_SPECS[self.modelId][1] == 'SDXL' and self.traceLevel in ('h6', 'h7') and self.researchCoverage == 'extended':
            raise ValueError('SDXL 暂仅支持代表研究采集，请选择代表采集')
        if self.traceLevel in ('h6', 'h7') and self.researchCoverage == 'extended':
            if max(self.width, self.height) > 512 or self.steps > 12:
                raise ValueError('扩展研究采集限宽高各不超过512、最多12步；较大图请使用代表采集')
        if self.traceLevel == 'h7':
            from identity_research import MAX_ARTIFACT_BYTES, estimated_capture_bytes
            extended = self.researchCoverage == 'extended'
            # UTF-8 byte count is a conservative BPE token upper bound; no model
            # loading or GPU work is needed to reject an oversized request.
            tokens = min(75 if extended else 32, max(1, len(self.prompt.encode('utf-8'))))
            if estimated_capture_bytes(self.width, self.height, self.steps, tokens, extended) > MAX_ARTIFACT_BYTES:
                raise ValueError('研究产物预估超过512MiB；请改为8步、缩短提示词或选择代表采集')
        return self

    @field_validator('prompt')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('请输入提示词')
        return value.strip()

    @field_validator('visualPolishPrompt', 'visualPolishNegativePrompt')
    @classmethod
    def trim_detail_prompt(cls, value):
        return value.strip()

    @field_validator('width', 'height')
    @classmethod
    def aligned(cls, value):
        if value % 8:
            raise ValueError('尺寸必须是8的倍数')
        return value

    @field_validator('seed')
    @classmethod
    def valid_seed(cls, value):
        if isinstance(value, int) and not 0 <= value <= 2147483647:
            raise ValueError('种子超出范围')
        return value
