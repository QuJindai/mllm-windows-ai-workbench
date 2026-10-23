# 人物档案、批量创作与过程观察

用户已同意整套方案，并要求不做小步确认。沿用 Realistic Vision V5.1 / FaceID Plus V2 / 配套 LoRA、E 盘工作区和浏览器入口；不增加 ComfyUI、不切换模型、不进行个人 LoRA 训练。

## 验收场景

上传一次参考照，明确选脸并命名档案；创建时提取并保存身份/CLIP 特征。重启浏览器和服务后选择档案即可使用，不再上传、检测或提取同一有效特征。建档试图允许多个步数、多个固定种子对照，满意的一张可将参数存为档案预设。身份本身不会被生成图片自动重训或覆盖。

一次可选 1–8 张，同一批复用一次模型，逐张运行；建档试图每个种子比较选定步数，矩阵总数不超过 16。观察窗口显示当前第几张、真实采样步数、加载/解码阶段、已用时间、估计剩余时间、中间预览及已完成图片；取消仅取消剩余/当前未完成结果，已经完成的原图和历史保留。无预览模式不做额外 VAE 解码。刷新和切页恢复同一批任务，不重复提交。

## 组件与存储

- `identity_features.py`：可校验的文件指纹索引、参考特征键与特征提取。特征键只绑定参考文件/人脸序号/提取器与 CLIP 版本，不绑定提示词、采样步数或生成 checkpoint。文件属性/身份改变使指纹失效；显式刷新提供完整校验，不每张重复读取数 GB。
- `identity_pipeline.py`：拆为准备特征、构造管线、单张采样、批次循环；单图旧接口仍可调用。批次一进程一管线，工作进程退出释放 GPU，沿用 Job Object/所有权校验。
- `identity_events.py`：受限 NDJSON 事件写入/增量读取；真实回调采样、阶段、预览完成、单张完成，不虚构进度。文件是服务端指定的本地任务文件，不接受客户端路径。
- `identity_service.py` 及新的档案/批次模块：复用已有 OS 存储 lease 和 GPU 串行队列，扩展生命周期、重启恢复、局部结果保留。
- `IdentityPage` 分拆档案选择、批次参数、观察窗口组件，避免继续堆大单文件。

所有新数据位于 `E:/Dream/data/identity/{profiles,batches}`、`E:/Dream/cache/identity`、`E:/Dream/outputs/<date>`。档案撤下为可恢复归档，不删除照片或历史结果；界面说明。特征只在本机，不提交 Git。

## 共享接口（冻结）

原 `/api/identity/generate` 与旧 Job 结构保留兼容。原 `IdentityGenerateRequest` 不增加批次字段。

`Profile` = `{id:person-<24hex>,name,referenceId,faceIndex,state:preparing|ready|failed|archived,featureKey?:string,defaults:object,error:null|string,createdAt,updatedAt}`。defaults 是 IdentityGenerateRequest 中除 referenceId/faceIndex 的参数，不保存批次数/预览设置。

- GET `/profiles`：非归档 Profile[]。
- POST `/profiles`：`{name,referenceId,faceIndex}`，异步建档返回 preparing；共享队列完成特征预计算后置 ready。重复点击由前端禁用；引用只允许已存在的选定脸。
- GET `/profiles/{id}`：Profile。
- POST `/profiles/{id}/rename`：`{name}` -> Profile。
- POST `/profiles/{id}/archive`：归档，活跃使用时返回冲突；不删除历史/参考照。
- POST `/profiles/{id}/preset`：`{jobId}`，只接受完成且 referenceId/faceIndex 与档案相同的人物任务，保存实际 seed/steps/strength 参数，不替换身份特征。

`BatchRequest` = `{profileId?:string,request:IdentityGenerateRequest,count:1..8,stepValues?:number[],previewEvery:0|5|10}`，stepValues 去重且 1..50、最多4项，总张数 count*步数项数 <=16；省略步数项则用 request.steps。profileId 指定时须 ready 且与 request 中 referenceId/faceIndex 相符。随机种子在提交时固化；相同步数对比共享相同种子，不同张使用 baseSeed+index（合法范围取模）。

`Batch` = `{id:batch-<24hex>,state:queued|preparing|sampling|complete|failed|cancelled,request:BatchRequest,items:IdentityJob[],currentItem:number,totalItems:number,completedItems:number,step:number,totalSteps:number,progress:number,stage:string,elapsedMs:number,etaMs:number|null,previewUrl:string|null,error:string|null,createdAt,updatedAt}`。currentItem 从1开始，尚未开始为0。items 每项有旧 Job 的完整字段。所有单张结果继续进入普通历史。

- POST `/batches` -> Batch；GET `/batches` -> Batch[]；GET `/batches/{id}` -> Batch；POST `/batches/{id}/cancel` -> Batch。
- GET `/batches/{id}/previews/{filename}` -> 只允许该批次预览目录中已完成 PNG，文件名限制为该批 item jobId 加 step 编号，不可路径穿越。
- 前端以 500ms–1s 轮询 Batch 获取实测事件状态，勿给空窗口伪造百分比；离页仍运行，重新进页/刷新恢复。

Worker CLI 新增 operation `prepare` 与 `batch`。

prepare 请求 `{imagePath,faceIndex,dreamRoot,configPath}` -> `{ok:true,featureKey,cacheHit}`。
batch 请求 `{items:[{...IdentityGenerateRequest,jobId,imagePath,outputPath,metadataPath,dreamRoot,configPath}],dreamRoot,configPath,eventPath,previewDir,previewEvery}` -> `{ok:true,items:[{jobId,imageUrl,metadata}]}`。所有 items 同一人脸、模型、LoRA/强度/尺寸；可变 seed/steps/prompt（本期 UI 批内提示词相同）。

事件 API：`emit_event(path, event)` 与 `read_events(path,offset=0)->(events,new_offset)`。单次读取 <=64KiB，单行 <=16KiB，保留未完成尾行，非 JSON/过长行拒绝；事件字典带 `type`。
- stage：`{type:'stage',stage:string,itemIndex?:0based,elapsedMs}`。
- step：`{type:'step',itemIndex:0based,step:1based,totalSteps,elapsedMs,previewFile?:basename}`。
- item_complete：`{type:'item_complete',itemIndex,jobId,elapsedMs}`，只有 PNG 与 metadata 已原子写完才发；服务端读取预先确定的文件，不信事件提供任意路径。
- preview_error：非致命，仅提示中间预览不可用，继续生成并保留真实进度。

## 进度与资源策略

现有采样器每步 callback_on_step_end 触发真实事件。预览每 5/10 步用现有 VAE 解码并缩小最长边256，明确标为“中间预览”；不增加大模型。previewEvery=0 完全关闭预览。阶段和总耗时分别计量，ETA 仅在有有效采样数据后估计，不把其当观测值。

加载一次服务同批样本，批次结束退出。不得同时常驻普通 SDXL 与人物 GPU 模型。建档需要 CLIP 时也经过共享队列与已验证原生释放逻辑。取消/故障清理未完成单张；已确认完整的单张不可被批次取消/恢复删除。重启将活跃批次标中断，保留已完成项和参数。

## 必须测试

档案重启持久化/归档与活跃冲突/错误选脸/其他人任务不可存预设；多步数种子配对/数量上限；NDJSON 分包/坏事件/有限数/路径边界；批内一次加载/关预览不解码/步骤来自回调；取消与重启保留已完成单图；前端恢复/零重复 POST/切档案晚响应隔离/部分完成图可打开；真 GPU 至少二图批次、步数对照、取消后再跑、真实预览可见。
