# HQ 人物图库一键授权：代码与本机部署验收

日期：2026-11-04。代码阶段仅修改代码和隔离验证；随后用户明确要求部署，已完成本机前后端更新。用户随后确认「我自己确认了，好了」及「已经改好了」，并要求提交 main、同步 GitHub。自动验收没有替用户签发真实授权或生图。

## 实现

- 授权缺失、失效或过期时显示「一键授权」；图库读取期间到期也会显示入口。
- 新增本机 `POST /api/hq/authorization/renew`。空请求，不接受凭据、命令、账号或回调地址。复用现有同源、直接 loopback、拒绝代理转发和 no-store 保护。
- 复用本机 Wrangler 登录与现有私有 R2 `sessions/v1/<SHA256(token)>` 协议，1 小时短期会话。固定账号/桶，无公网匿名签发入口，不修改插件。
- 先写受当前 Windows 用户及 SYSTEM ACL 保护的临时会话，再上传仅含版本和有效期的会话记录，随后核验既有私有人物列表接口，最后原子替换本地会话。
- 连续点击互斥；丢失回复后的重试复用仍有效且验证通过的会话；授权成功后清除后端缓存并刷新前端图库。授权动作不调用生图或取消接口。
- 失败保留旧会话；按组件缺失、Cloudflare 登录失效、连接/权限失败、超时、并发处理中区分错误，不回显命令行原始错误。
- 「只选本机档案」不读取私有图库、不出现授权按钮；切换人物来源仍互斥。服装、姿势、原有作品和任务行为保持。

## 验证结果

| 验证 | 结果 | 边界 |
| --- | --- | --- |
| 新增后端授权测试 | 19 PASS | 模拟云端写入和 HTTP；真实临时文件、原子替换、Windows ACL 校验 |
| 既有 HQ 服务、路由、修整生命周期回归 | 130 PASS | 真实存储/服务逻辑，测试用 HTTP/推理进程边界 |
| HQ 页面和 API 测试 | 101 PASS | React DOM 交互、重复点击、授权结果核验、失效重试、刷新与来源切换；非线上 GUI 验收 |
| TypeScript 构建 | PASS | `tsc -b` |
| 前端生产构建 | PASS | 独立构建后部署，HTTP 读取的 JS 与构建产物 SHA-256 一致；保留原有单包大于 500 kB 的体积提示 |
| 当前用户与 SYSTEM 专用文件权限 | PASS | 在 Windows 实际创建测试文件并读取 DACL，核验原子替换后的权限 |
| 自动执行真实 Cloudflare 授权和 R2 写入 | NOT RUN | 自动流程没有替用户点击授权或验证当前 OAuth 状态 |
| 正式服务重启与本机部署 | PASS | 新版已在 8766 启动，健康检查、授权能力和静态资源读回通过 |
| 用户界面验收 | USER CONFIRMED | 用户自行确认完成；自动界面检查因 Chrome 最小化未能完成，不冒称工具已目视验收 |
| 真实生图 | NOT RUN | 本次功能不要求生图验证 |

合计 250 项相关测试通过。测试及构建产物位于 `E:/Dream/test-runs/hq-authorization-20261104`。没有读取或打印本机真实 token；部署检查确认授权文件长度和修改时间不变。未自动安装依赖、打开登录或执行 Wrangler 远程操作。

## 本机部署

- 版本：`dream-hq-one-click-authorization-20261104`。
- 地址：`http://127.0.0.1:8766/?view=hq-tryon`。
- 资源：`index-C3Cr4paZ.js`、`index-DHvg1nu_.css`；保留旧版带哈希资源，原子更新入口文件。
- 2026-11-04 14:44（Asia/Shanghai）读回：健康状态正常，模型文件齐备，`authorization.available=true`，方法 `local-wrangler`；38 条 HQ 任务保留，无活动生成或修整任务。
- 新授权路径的只读 GET 返回 405，验证路由存在但 GET 不能触发续期。授权仍由用户主动点击。
- 部署证据：`E:/Dream/test-runs/hq-authorization-20261104/deploy/verification.json`。
- 回滚文件：`E:/Dream/test-runs/hq-authorization-20261104/deploy/rollback-20261104-144158`，含旧前端入口/资源及部署前 backend 源码归档。恢复代码与前端后按现有空闲检查流程重启，保留人物、作品、任务和授权文件。

## 验证命令

前端在 `E:/Dream/repo/apps/dream-windows`：

```powershell
& ./node_modules/.bin/vitest.cmd run src/app/pages/HQTryOnPage.test.tsx src/providers/hq-tryon-api.test.ts --maxWorkers=2 --testTimeout=20000
& ./node_modules/.bin/tsc.cmd -b
& ./node_modules/.bin/vite.cmd build --outDir E:/Dream/test-runs/hq-authorization-20261104/frontend
```

后端使用现有隔离验证依赖，测试根在 E 盘，`test_hq_authorization.py` 禁止真实云端访问：

```powershell
$env:PYTHONPATH='E:/Dream/test-runs/hq-repair-20261102/validation-env/Lib/site-packages'
$env:TEMP='E:/Dream/test-runs/hq-authorization-20261104'
$env:TMP=$env:TEMP
& 'C:/Users/Admin/AppData/Local/Programs/Python/Python312/python.exe' -m pytest -q apps/dream-windows/server/tests/test_hq_authorization.py
& 'C:/Users/Admin/AppData/Local/Programs/Python/Python312/python.exe' -m pytest -q apps/dream-windows/server/tests/test_hq_routes.py apps/dream-windows/server/tests/test_hq_service.py apps/dream-windows/server/tests/test_hq_repair_lifecycle.py
```

## 验收边界

本机部署已完成，用户自行确认完成。真实授权仍需主动点击按钮；若返回 `HQ_CLOUDFLARE_LOGIN_REQUIRED`，先完成本机 Wrangler 登录。ChatGPT 连接器授权不自动成为本机登录。本报告的自动测试不等同于真实云端签发验收；用户确认单独记录，不替代底层授权审计。

配置、错误码和回滚见 [HQ_LOCAL_TRYON.md](HQ_LOCAL_TRYON.md)。回滚仅恢复代码/前端版本，保留全部凭据、人物档案、作品与历史任务。
