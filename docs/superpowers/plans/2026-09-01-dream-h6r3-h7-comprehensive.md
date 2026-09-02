# Dream H6R3 + H7 综合升级实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐项实施。所有任务采用 RED → GREEN → Regression → Phone Gate。

**Goal:** 在不破坏当前 S24U 本地模型、不增加无意义推理负担的前提下，解决当前生成语义偏差，重构显微镜的信息架构，并为真正的 token-level Cross-attention 可观测性建立 H7 Debug UNet Graph。

**Architecture:** H6R3 保留现有 Production QNN 推理路径，把“真实性、语义保真、观测信息密度”补齐；所有新增可视化优先复用当前已经真实采集的 token/chunk、UNet prediction、scheduler latent、timing 数据，不为了展示而增加模型推理。H7 单独引入 Debug UNet Graph，仅在显微镜调试模式下暴露选定 cross-attention 中间输出，Production UNet 保持原样。

**Tech Stack:** Android / Kotlin / Compose / WebView / JavaScript / C++ / xtensor / Local Dream / MNN / Qualcomm QNN/HTP / QAIRT / GitHub Actions

**Spec:** 本文第 1～8 节即为冻结规格；实现任务从第 9 节开始。

## Global Constraints

- 当前冻结基线：`QuJindai/mllm-windows-ai-workbench` → `feature/s24u-image-harness-h6-conditioning-influence` → H6R2。
- H6R2 已完成 GitHub 全链路构建；真机证明观测链已打通，但语义保真未通过。
- 不卸载、不清数据、不破坏现有模型目录；继续沿用稳定 TEST-ONLY 签名实现覆盖安装。
- H6R3 的观测重构不得增加 CLIP / UNet / VAE / Scheduler 调用次数，除非任务明确属于“受控诊断实验”。
- 所有新增页面必须区分“真实数据 / 推导数据 / 当前不可观测”，禁止把 contribution map、latent map 冒充 cross-attention 或 UNet feature map。
- 显微镜页保留 H6R1 手势仲裁修复：父级 `HorizontalPager` 不抢 WebView 的纵向滑动。
- 不再用“两个页面展示同一份 latent 图片”的方式填充 UI。
- `main` 在 S24U 综合真机门禁通过前保持不合并。

---

## 1. 当前真机状态与证据结论

### 1.1 已通过：Observability

本轮 S24U 真机截图证明：

- 1024×1024、本轮 8 diffusion steps、总耗时约 33.133 s。
- Positive：190 / 190 content tokens，拆为 3 chunks。
- Negative：90 / 91 content tokens，拆为 2 chunks。
- Conditioning Influence：3 chunks × 8 steps = 24 个真实 chunk-step samples。
- Scheduler latent：8 个 step 均成功采集，`1×4×128×128`。
- SDXL QNN low-RAM 下没有逐 step VAE decode 时，H6R2 已正确标成 `LATENT FALLBACK / 非 VAE decode`。
- Cross-attention 页面已不再假装“页面坏了”，而是明确标记为当前 Production QNN 图能力缺口。

### 1.2 未通过：Semantic Fidelity

相同运行中：

- Prompt 的一级语义要求包含“雨夜 / 汽车后排 / 两个人 / 关系场景”。
- 最终图却明显偏离为“单人动漫风人物”，核心实体和环境没有被可靠保留。
- Negative Prompt 包含对 anime/cartoon 等风格的排斥，但本轮 `CFG = 1.0`。

当前 Pipeline 公式为：

```text
noise = uncond + cfg × (text - uncond)
```

因此当 `CFG = 1.0`：

```text
noise = text
negative / uncond 对最终 noise prediction 的有效权重 = 0
```

结论：**Negative 虽然被 tokenize / encode，但本轮不应在 UI 中显示为“有效参与生成”。**

### 1.3 当前最重要的工程判断

1. Token / Chunk / CLIP / UNet 数据已经真实进入观测链；不能再把主要精力放在“有没有传进去”。
2. 下一步应区分：
   - CFG 语义控制是否正确；
   - 长 Prompt 多 Chunk 的融合是否打散全局语义；
   - 模型本身对该提示词是否有能力；
   - DMD2 / 低步数配置是否进一步放大语义丢失。
3. 先做同 seed、同模型、同参数的受控隔离实验，再决定是否修改 Chunk Fusion；禁止凭感觉重写 tokenizer/CLIP。

---

## 2. H6R3 总体目标

H6R3 不是单一 bugfix，而是一次“语义真实性 + 显微镜信息架构”的整合升级。最终只交付一个综合 APK，不让真机反复安装零散小版本。

### H6R3-A：CFG / Negative Truthfulness

要回答：**Negative 到底有没有实际作用？**

运行时必须同时展示：

```text
CFG value
skip_uncond
positive effective weight
negative effective weight
negative encoded = true/false
negative effective = true/false
```

规则：

```text
CFG = 1.0 且 QNN canSkipUncond=true
→ Negative effective weight = 0
→ UI 显示“已编码，但本轮不参与最终 guidance”
```

CFG > 1 时，才显示 Negative 对最终 guidance 的真实有效性。

### H6R3-B：Long Prompt Semantic Fidelity Lab

用同 seed 自动构造受控 A/B/C/D 组：

| 组 | Prompt 处理 | 目的 |
|---|---|---|
| A | 短提示词，只保留核心实体/场景 | 验证模型基本语义能力 |
| B | 原 Prompt 的 Chunk 1 only | 验证第一段是否能锁定全局主体 |
| C | 当前 3-Chunk 等权 prediction mean | 当前 H2/H6 基线 |
| D | 受控候选融合算法 | 验证融合是否导致语义改善 |

所有组固定：

- 同模型
- 同 seed
- 同尺寸
- 同 scheduler
- 同 steps
- 同 CFG
- 不自动改写用户原 Prompt

第一轮只做诊断，不直接改变默认生成算法。

### H6R3-C：Microscope 信息架构重构

把当前“同一份 latent 两次展示”彻底拆开。

#### 页面 1：Process Dynamics（时间演化）

回答：**模型每一步发生了什么变化？**

不再展示原始 4-channel contact sheet 作为主视觉，改为：

- `Δz_t = z_{t-1} - z_t` 空间变化热图；
- `||Δz_t||₂`；
- `mean(|Δz_t|)`；
- `cos(z_t, z_{t-1})`；
- latent mean / std；
- timestep；
- 每 step 的 UNet / Scheduler 耗时；
- 8 steps 的收敛曲线；
- 若真实 VAE preview 可用，单独显示为“Decoded Preview”辅视图；
- 若 low-RAM 不允许 VAE preview，则明确写“无 decoded preview”，**不再用 latent contact sheet 冒充过程图**。

#### 页面 2：Latent State Inspector（内部状态）

回答：**当前 step 的 latent 内部状态是什么？**

- C0 / C1 / C2 / C3 四通道分别显示；
- 每通道 `min / max / mean / std / L2`；
- 每通道直方图；
- 4×4 channel correlation matrix；
- 当前 step / 上一步 / 最终 step 快速比较；
- 可选显示 2×2 contact sheet，但只作为 Overview，不作为唯一视图。

### H6R3-D：Runtime Compute Graph

替换当前低信息密度的：

```text
Prompt → Token → CLIP → ...
```

改成真实运行时数据流图。每个节点至少显示：

```text
backend
shape
call count
duration
executed / skipped
current value / mode
input source
output destination
```

建议节点：

```text
Prompt
  ↓
Tokenizer / Prompt Processor
  ↓
Chunker
  ↓
CLIP-1 / CLIP-2 (MNN / CPU)
  ↓
Conditioning
  ↓
CFG / Guidance
  ↓
UNet Chunk 1..K (QNN / HTP)
  ↓
Chunk Fusion
  ↓
Scheduler (CPU)
  ↓
Latent z_t
  ↓
Final VAE Decode (QNN / HTP)
  ↓
Image
```

本轮示例应能真实显示：

```text
POS 190 tokens → [75, 75, 40]
NEG 90 tokens → [75, 15/16]  // 以实际 trace 为准
CLIP context = 77
SDXL encoder_hidden_states = 1×77×2048
text_embeds = 1×1280
time_ids = 1×6
CFG = 1.0
Negative effective weight = 0
UNet chunk calls / step = 3
Diffusion steps = 8
Latent = 1×4×128×128
```

节点可点击展开详细 trace，避免首页堆满文本。

---

## 3. Process Dynamics 与 Latent State 的数据边界

### 3.1 当前重复的根因

H6R2 的 fallback 逻辑本质上是：

```javascript
processFrames = previews.length ? previews : latents
```

所以 low-RAM 场景下：

```text
“逐 step 生成过程” = latent_maps
“内部 latent 通道图” = latent_maps
```

像素来源完全相同，仅交互方式不同。

### 3.2 H6R3 的新边界

```text
Process Dynamics = 对相邻 latent 的变化进行派生分析
Latent State      = 对单个 latent 状态进行内部通道分析
Decoded Preview   = 只有真实 VAE decode 发生时才出现
```

这样三类信息互不冒充。

### 3.3 计算成本约束

`Δz / L2 / mean / std / cosine / histogram / correlation` 全部直接基于已经存在的 CPU-side float latent 计算：

- 不增加 UNet 调用；
- 不增加 CLIP 调用；
- 不增加 VAE 调用；
- 不增加 Scheduler 调用。

---

## 4. Cross-attention：为什么现在拿不到

### 4.1 当前 Production SDXL QNN UNet 的真实接口

当前执行接口向 QNN UNet 提供：

```text
sample                 1×4×H×W
encoder_hidden_states  1×77×2048
timestep               1
text_embeds             1×1280
time_ids                1×6
```

Production QNN graph 执行完成后，应用层只取：

```text
outputs[0] = out_sample = 1×4×H×W
```

也就是最终 noise prediction。

### 4.2 Cross-attention 在哪里

概念上，UNet 内部 Cross-attention 会计算：

```text
Q ← image / latent feature
K,V ← text conditioning
A = softmax(QKᵀ)
output = A·V
```

真正的 token → spatial region 归因需要的是 `A` 或其 head/layer 聚合结果。

### 4.3 为什么不能在当前 APK 里临时“读取一下”

当前 `unet.bin` 是已经编译、优化后的 QNN/HTP 图。Production graph 的外部契约只有预定义 input/output。

它不是 PyTorch eager graph，不能在运行时临时：

```python
register_forward_hook(attention_layer)
```

而且 QNN 编译过程中还可能发生：

- operator fusion；
- quantization；
- layout transform；
- graph partition / HTP optimization。

因此“知道 attention 在数学上存在”不等于“当前 compiled graph 暴露了它”。

---

## 5. H7 Attention Microscope 设计

H7 必须与 H6R3 分开：它已经属于**模型图重新导出/编译**，不能伪装成普通 UI 修改。

### 5.1 双图模式

```text
Production UNet
- 现有 unet.bin
- 只用于正常生成
- 性能优先

Debug UNet
- 新的 debug_unet.bin
- 仅显微镜模式使用
- 暴露少量选定 attention outputs
```

Production 模型永远保留，不被 Debug 图覆盖。

### 5.2 不导出“全部 attention”

全部层、全部 head、全部 token 的 attention tensor 会造成不可接受的：

- QNN output 数量；
- HTP → CPU 带宽；
- RAM；
- APK / 模型包尺寸；
- UI 数据量。

第一版只选代表层：

```text
Down block：1 层
Mid block：1 层
Up block：1 层
```

每层优先输出 head-aggregated attention，而不是全部 heads。

### 5.3 Token-level UI

H7 页面：

```text
Token Strip
→ 点击 car / rain / woman / backseat 等 token
→ Layer Selector: Down / Mid / Up
→ Spatial Attention Heatmap
→ 当前 token 的 attention entropy / peak / coverage
```

必须同时显示：

```text
Token ID
Token text
Chunk index
CLIP slot
Layer
Attention map shape
Aggregation mode
```

### 5.4 Debug Graph 数值门禁

新增 debug outputs 后，不允许改变正常 UNet 主输出。

同一输入下：

```text
Production out_sample
vs
Debug Graph out_sample
```

要求：

```text
max_abs_error <= 既定 QNN 导出容差
cosine >= 0.999x（具体阈值在首次基线实测后冻结）
```

在容差未冻结前，不把 Debug Graph 用于真实生成。

---

## 6. Semantic Fidelity：诊断与候选修复策略

### 6.1 第一原则

**先证明问题在哪，再改算法。**

不能因为最终图跑偏，就直接认定 tokenizer、token ID、CLIP 或 Chunk Fusion 任一环节必错。

### 6.2 受控真机实验矩阵

固定 seed / model / 1024×1024 / 8 steps，至少跑：

| Case | Prompt | CFG | Negative | 目的 |
|---|---|---:|---|---|
| S1 | `two people sitting in the back seat of a car at night in heavy rain` | 1.0 | empty | 验证基础主体能力 |
| S2 | 同 S1 | >1 | 简短 negative | 验证 CFG / negative 生效 |
| L1 | 原始长 Prompt，Chunk 1 only | 与当前相同 | 原 negative | 第一 Chunk 基线 |
| L2 | 原始长 Prompt，当前 K-chunk equal mean | 与当前相同 | 原 negative | 当前算法 |
| L3 | 原始长 Prompt，token-count weighted fusion | 与当前相同 | 原 negative | 候选算法 |
| L4 | 原始长 Prompt，anchor + residual fusion | 与当前相同 | 原 negative | 候选算法 |

### 6.3 候选 Chunk Fusion

#### Baseline：Equal Mean

```text
ε̄ = (1/K) Σ ε_k
```

优点：当前实现简单、稳定。

风险：不同 Chunk 的语义地位完全等价，可能把“主体/场景锚点”和“后续细节”平均稀释。

#### Candidate A：Token-count Weighted

```text
w_k = content_tokens_k / Σ content_tokens
ε̄ = Σ w_k ε_k
```

优点：最后一个短 Chunk 不再与满 75-token Chunk 同权。

#### Candidate B：Anchor + Residual

```text
ε̄ = ε_1 + α Σ_{k>1}(ε_k - ε_1)
```

目标：让第一 Chunk 锁定主体/场景，后续 Chunk 以 residual 形式补充细节。

`α` 不提前拍脑袋固定；由同 seed 实验比较后冻结。

### 6.4 默认算法切换门禁

只有同时满足：

- 核心实体/场景真机目视明显改善；
- 不引入结构性 artifacts；
- 不明显增加耗时；
- 现有短 Prompt 行为不退化；

才允许把候选融合设为默认。

否则保留 Equal Mean，并把候选算法放到“实验模式”。

---

## 7. Runtime Compute Graph 信息密度规格

每个节点采用“摘要 + 展开”两层信息。

### 7.1 摘要层

例如：

```text
CLIP-1 + CLIP-2
MNN / CPU
3 calls
77×2048
6.4 s
```

```text
UNet
QNN / HTP
3 chunks × 8 steps = 24 calls
~2.0 s / step group
```

```text
CFG
1.0
NEG effective = 0
skip_uncond = true
```

### 7.2 展开层

点击后显示：

- exact input shape；
- exact output shape；
- token/chunk 映射；
- duration timeline；
- backend；
- skipped reason；
- cache hit/miss（若已有数据）；
- 当前公式；
- 前后节点 ID。

### 7.3 状态颜色语义

只表达状态，不表达“好坏”：

```text
Executed
Skipped by optimization
Unavailable in production graph
Derived from observed tensor
Debug-only
```

---

## 8. 版本与交付策略

### H6R3

建议：

```text
versionCode = 7409
versionName = 2.8.1-s24u-h6r3
```

H6R3 最终 APK 同时包含：

- CFG/Negative Truthfulness；
- Semantic Fidelity Lab；
- Process Dynamics；
- Latent State Inspector；
- Runtime Compute Graph；
- H6R1 gesture fix；
- H6R2 low-RAM truthfulness。

开发中允许多个内部 checkpoint，但**不要求用户安装每一个小版本**。

### H7

只有 H6R3 真机稳定后再进入：

```text
H7 Attention Microscope
Debug UNet Graph
```

避免在语义链本身还不稳定时同时引入新模型图变量。

---

# 9. Implementation Plan

## File Map

### Existing files to modify

- `s24u-image-harness/tests/test_h6r3_semantic_fidelity_contract.py`
  - H6R3 CFG/Negative、Fusion、Dynamics、Architecture 总合同。
- `s24u-image-harness/patch_h6_v6_semantic_fidelity.py`
  - H6R3 patch 入口。
- `app/src/main/cpp/src/Pipeline.hpp`
  - CFG truth trace、fusion experiment、latent delta/statistics。
- `app/src/main/cpp/src/main.cpp`
  - 新 telemetry 序列化。
- `app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt`
  - 新 runtime graph / latent dynamics state reducer。
- `app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt`
  - JSON bridge / H6R3 marker。
- `app/src/main/assets/s24u_microscope/index.html`
  - 页面结构重构。
- `app/src/main/assets/s24u_microscope/microscope.js`
  - Dynamics / Latent Inspector / Runtime Graph 渲染。
- `app/src/main/assets/s24u_microscope/microscope.css`
  - 高密度节点、展开面板、矩阵/图表布局。

### New H7 files

- `s24u-image-harness/h7/ATTENTION_GRAPH_SPEC.md`
- `s24u-image-harness/tests/test_h7_attention_graph_contract.py`
- `s24u-image-harness/patch_h7_attention_debug.py`
- `s24u-image-harness/h7/export_attention_debug_graph.py`
- `s24u-image-harness/h7/compile_attention_debug_qnn.sh`
- `s24u-image-harness/h7/verify_attention_parity.py`
- `s24u-image-harness/h7/attention_graph_manifest.json`

以上 H7 资产均使用独立 Debug 命名，不覆盖 Production `unet.bin`。

---

## Task 1: Freeze H6R2 phone evidence and H6R3 RED contract

**Files:**
- Create: `s24u-image-harness/tests/test_h6r3_semantic_fidelity_contract.py`
- Create: `docs/superpowers/plans/2026-09-01-dream-h6r3-h7-comprehensive.md`

**Produces:** `H6R3_RED`：当前 H6R2 必须因缺少 H6R3 truth/dynamics/runtime-graph markers 而失败。

- [ ] 写 H6R3 失败合同：要求 `7409 / h6r3 marker / cfg effective weight / latent dynamics / runtime graph`。
- [ ] 在 pinned Local Dream 上应用 H2→H6R2。
- [ ] 运行 H6R3 contract，确认只因 H6R3 能力缺失失败。
- [ ] 保存 RED evidence。
- [ ] Commit：`test(s24u): define H6R3 semantic fidelity and microscope contract`。

---

## Task 2: CFG / Negative Truthfulness

**Files:**
- Modify: `Pipeline.hpp`
- Modify: `main.cpp`
- Modify: `BackgroundGenerationService.kt`
- Modify: `microscope.js`

**Produces:**

```text
cfg
skip_uncond
negative_encoded
negative_effective_weight
positive_effective_weight
```

- [ ] RED：CFG=1 时 UI/trace 必须报告 `negative_effective_weight=0`。
- [ ] Native trace 增加 guidance semantics，但不增加推理调用。
- [ ] Android bridge 保存字段。
- [ ] Runtime Graph 的 CFG 节点展示“NEG encoded but ineffective”。
- [ ] GREEN：合同通过。
- [ ] Regression：H2→H6R2 全部通过。
- [ ] Commit：`feat(s24u): expose truthful CFG and negative-prompt effectiveness`。

---

## Task 3: Semantic Fidelity Isolation Harness

**Files:**
- Modify: `Pipeline.hpp`
- Modify: microscope UI assets
- Create: `s24u-image-harness/tests/test_h6r3_fusion_lab_contract.py`

**Produces:** 诊断模式下可选择 `first-only / equal-mean / token-weighted / anchor-residual`，默认仍保持 equal-mean，直到真机门禁批准。

- [ ] RED：默认算法必须保持 current equal-mean；实验算法只能显式选择。
- [ ] 增加 fusion mode enum / request field。
- [ ] 实现 token-count weighted。
- [ ] 实现 anchor + residual（alpha 作为实验参数）。
- [ ] 显微镜显示每种模式的真实权重公式和 chunk weights。
- [ ] 确保普通模式不增加 UNet 次数。
- [ ] GREEN + regression。
- [ ] Commit：`feat(s24u): add controlled long-prompt fusion lab`。

---

## Task 4: Process Dynamics

**Files:**
- Modify: `Pipeline.hpp`
- Modify: `main.cpp`
- Modify: `BackgroundGenerationService.kt`
- Modify: `microscope.js`

**Produces:** 每相邻 step 的真实 latent dynamics。

- [ ] RED：过程页不得再直接以 `latent_maps` 作为主过程图。
- [ ] 保留上一 step latent，只到下一 step statistics 计算完成。
- [ ] 计算：`delta_l2 / delta_mean_abs / latent_cosine / mean / std`。
- [ ] 生成 `|Δz|` 轻量 heatmap。
- [ ] 计算完成后立即释放临时 delta tensor。
- [ ] UI 绘制 convergence curve + per-step heatmap。
- [ ] VAE preview 只有真实存在时作为 secondary decoded preview。
- [ ] GREEN + 内存释放顺序合同。
- [ ] Commit：`feat(s24u): replace latent fallback duplication with diffusion dynamics`。

---

## Task 5: Latent State Inspector

**Files:**
- Modify: `app/src/main/cpp/src/Pipeline.hpp`
- Modify: `app/src/main/cpp/src/main.cpp`
- Modify: `app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt`
- Modify: `app/src/main/assets/s24u_microscope/index.html`
- Modify: `app/src/main/assets/s24u_microscope/microscope.js`
- Modify: `app/src/main/assets/s24u_microscope/microscope.css`

**Produces:** 4-channel 独立观测。

- [ ] RED：要求 C0-C3 独立 stats 和 correlation matrix。
- [ ] 每通道计算 `min/max/mean/std/L2`。
- [ ] 生成固定 bin 数的 histogram，禁止传完整 float tensor 到 WebView。
- [ ] 计算 4×4 correlation matrix。
- [ ] UI：通道卡 + histogram + correlation matrix + step compare。
- [ ] 原 2×2 contact sheet 降为 overview。
- [ ] GREEN + bounded payload test。
- [ ] Commit：`feat(s24u): add channel-level latent state inspector`。

---

## Task 6: Runtime Compute Graph

**Files:**
- Modify: `BackgroundGenerationService.kt`
- Modify: `ModelRunScreen.kt`
- Modify: `index.html / microscope.js / microscope.css`

**Produces:** 高信息密度真实计算链。

- [ ] RED：每个节点必须包含 `backend/shape/call count/duration/executed-state`。
- [ ] 构建静态拓扑 + runtime data overlay。
- [ ] CLIP 节点明确 MNN/CPU。
- [ ] UNet/VAE 节点明确 QNN/HTP。
- [ ] Scheduler 节点明确 CPU。
- [ ] CFG=1 节点显示 NEG effective=0。
- [ ] Chunk Fusion 节点显示当前公式和 weights。
- [ ] 点击节点展开 raw trace/shape/timing。
- [ ] GREEN + WebView payload regression。
- [ ] Commit：`feat(s24u): build high-density runtime compute graph`。

---

## Task 7: H6R3 Full CI

**Files:**
- Create/Modify: `.github/workflows/s24u-image-harness-h6r3-build.yml`

- [ ] H2→H6R2 regression。
- [ ] H6R3 RED→GREEN。
- [ ] 推理调用计数门：普通模式 H6R2 vs H6R3 CLIP/UNet/VAE 调用数一致。
- [ ] QAIRT SDK。
- [ ] ARM64/QNN native rebuild。
- [ ] Gradle unit tests。
- [ ] APK build。
- [ ] DEX H6R3 marker。
- [ ] Version/signature verification。
- [ ] Artifact SHA-256。
- [ ] 生成 phone-test APK。

---

## Task 8: S24U Integrated Acceptance

一次完成，不拆成大量小探针。

### A. Upgrade / regression

- [ ] H6R2 → H6R3 覆盖安装成功。
- [ ] 模型目录保留，无重新下载。
- [ ] 生成、历史、显微镜、手势均正常。

### B. Semantic isolation

- [ ] S1/S2/L1/L2/L3/L4 固定 seed 比较。
- [ ] 记录核心实体：car / rain / two people / back seat。
- [ ] CFG=1 时 UI 正确显示 Negative effective=0。
- [ ] CFG>1 时验证 Negative 行为变化。
- [ ] 决定是否切换默认 fusion；没有证据则不切。

### C. Microscope

- [ ] Process Dynamics 与 Latent State 明显不同，不再重复同一图片。
- [ ] Dynamics 曲线与 step scrubber 同步。
- [ ] C0-C3 stats / histogram / correlation 正常。
- [ ] Runtime Graph 节点数据与本轮 trace 一致。
- [ ] 自然斜向上下滑动无 Pager 抢手势。

### D. Performance

- [ ] 普通生成耗时相比 H6R2 无显著观测开销回退。
- [ ] WebView 滚动无持续卡顿。
- [ ] 连续两轮生成无 revision 污染。
- [ ] 温升/内存无明显异常。

**Merge Gate:** A+B+C+D 全部通过后，H6R3 才可进入 merge-ready。

---

## Task 9: H7 Attention Graph Spec / RED

**Files:**
- Create: `s24u-image-harness/h7/ATTENTION_GRAPH_SPEC.md`
- Create: `s24u-image-harness/tests/test_h7_attention_graph_contract.py`

- [ ] 固定 Production graph I/O 基线。
- [ ] 列出选定 Down/Mid/Up cross-attention 节点。
- [ ] 定义 Debug graph output shape / dtype / aggregation。
- [ ] 定义主 `out_sample` parity gate。
- [ ] RED：当前 Production unet.bin 必须因无 attention outputs 而失败。
- [ ] Commit：`test(s24u): define H7 attention debug graph contract`。

---

## Task 10: H7 Debug UNet Graph

**Files:**
- Create: `s24u-image-harness/h7/export_attention_debug_graph.py`
- Create: `s24u-image-harness/h7/compile_attention_debug_qnn.sh`
- Create: `s24u-image-harness/h7/verify_attention_parity.py`
- Create: `s24u-image-harness/h7/attention_graph_manifest.json`
- Modify: `s24u-image-harness/patch_h7_attention_debug.py`

- [ ] 从可重建的 UNet 源图/ONNX 起点导出 Debug graph。
- [ ] 仅增加 3 个代表层的聚合 attention outputs。
- [ ] 编译独立 `debug_unet.bin`。
- [ ] 不覆盖 Production `unet.bin`。
- [ ] 同输入比较 Production/Debug `out_sample` 数值一致性。
- [ ] 超过容差则阻断 H7，不进入 App。
- [ ] Commit：`feat(s24u): compile debug UNet with selected cross-attention outputs`。

---

## Task 11: H7 Attention Microscope UI

**Files:**
- Modify: `app/src/main/cpp/src/QnnModel.hpp`
- Modify: `app/src/main/cpp/src/Pipeline.hpp`
- Modify: `app/src/main/cpp/src/main.cpp`
- Modify: `app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt`
- Modify: `app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt`
- Modify: `app/src/main/assets/s24u_microscope/index.html`
- Modify: `app/src/main/assets/s24u_microscope/microscope.js`
- Modify: `app/src/main/assets/s24u_microscope/microscope.css`

- [ ] Token strip 与 CLIP slot 映射。
- [ ] Layer selector：Down/Mid/Up。
- [ ] Attention spatial heatmap。
- [ ] token ID / chunk / slot / layer / map shape 明示。
- [ ] attention entropy / peak / coverage。
- [ ] 明确 Debug-only 状态。
- [ ] Production mode 不加载 Debug graph。
- [ ] 真机性能/内存门禁。

---

# 10. 最终验收标准

## H6R3 可合并标准

必须同时满足：

1. **Semantic Truthfulness**：CFG/Negative UI 不再误导。
2. **Semantic Fidelity**：至少完成同 seed 融合隔离，默认算法选择有证据。
3. **No Duplicate Observability**：Process Dynamics 与 Latent State 不再重复同一份图片。
4. **Runtime Density**：Architecture 变成真实数据流，不是教学占位图。
5. **No Fake Attention**：H7 之前绝不冒充 token-level cross-attention。
6. **Zero Extra Inference**：普通显微镜模式不增加模型调用次数。
7. **Phone Gate**：S24U 覆盖安装、模型保留、性能、手势、连续运行全部通过。

## H7 可启用标准

1. Debug graph 主输出与 Production graph 在冻结容差内一致。
2. Attention maps 随 token / layer 变化，不是常量或重复伪图。
3. 输出数据量有界，不造成 S24U 内存或 HTP→CPU 带宽失控。
4. Debug graph 与 Production graph 可独立选择，Production 性能不受影响。

---

# 11. 决策结论

当前建议路线锁定为：

```text
H6R2 Observability PASS
        ↓
H6R3 Semantic Fidelity + Truthfulness
        +
Process Dynamics / Latent State 分工
        +
Runtime Compute Graph 高信息密度化
        ↓
S24U Integrated Gate
        ↓
H6R3 merge-ready
        ↓
H7 Debug UNet Graph
        ↓
Real token-level Cross-attention Microscope
```

核心原则只有三条：

1. **先证据，后改算法。**
2. **同一份数据不占两个页面。**
3. **看不到的中间量宁可明确标“未导出”，也不制造假的可视化。**
