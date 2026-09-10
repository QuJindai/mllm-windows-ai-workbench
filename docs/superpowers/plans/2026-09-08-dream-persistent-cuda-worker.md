# Dream 常驻 CUDA 生图引擎实施计划

日期：2026-09-08

- [x] 为常驻服务客户端写失败测试：请求映射、图片解码、取消。
- [x] 实现本机 `sd-server` 探测、惰性启动、模型身份校验和 HTTP 客户端。
- [x] 为 JobRunner 写失败测试：Basic/off 选常驻，H6/H7 选 CLI，启动前失败回退。
- [x] 接入 JobRunner，保持输出、metadata、历史与真实 trace 契约。
- [x] 发布 `sd-server.exe` 到 `E:\Dream\app\stable-diffusion-cuda-12.9.1-latent` 并验证 SHA-256。
- [x] 跑 Python、前端、核心、PowerShell 和生产构建全回归。
- [x] 重启 8866 浏览器服务，执行真实 GUI 生成与页面巡检。
- [x] 检查实际图片质量、耗时和 metadata 证据。

## 执行证据

- 测试：前端 105 项、Python 后端/项目/核心 81 项，共 186 项通过。
- 生产构建：Vite 构建成功并输出到 `E:\Dream\builds\dream-windows\frontend`。
- 发布校验：`sd-server.exe` 源和发布目标 SHA-256 均为 `A4407A28B6D1941F7C3143CEF2B40BBBAC5199FD012F02BBBA01C081A4D5DF2F`。
- GUI 快速档：`job-be86ee782f1d`，512×512、20 步、9.031 秒、`persistent-server`、Flash Attention=true。
- GUI 平衡档：`job-99b929f420a3`，768×768、20 步、20.812 秒、`persistent-server`、Flash Attention=true。
- 平衡档图像检查：熵 8.827，纯黑附近像素比 0.000561，纯白附近像素比 0，未出现彩色糊块或大面积剪裁。
- GUI 巡检：生成、历史、模型、显微镜运行时/潜空间/H7、设置页面均加载正常；Basic trace 只显示实测总耗时，不伪造阶段拆分。
