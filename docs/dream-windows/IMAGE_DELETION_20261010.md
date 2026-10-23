# 图片删除功能验收 — 2026-10-10

## 本次范围
- 为生成预览、生成变体、人物单图及批次结果增加“删除图片”入口。
- 点击后明确确认；取消不写入。删除失败保留结果并显示可重试错误。
- 按提供方及图片 ID 共享 pending/错误状态，切页不重复提交。
- 历史页接收删除通知，作废旧分页请求并重新建立游标，避免跳过未删除图片。
- 人物结果只依据已提交的历史删除收据标记 resultDeleted；读取与暂存/提交/回滚共享锁。文件短暂缺失不等于删除成功。
- 复用原有可恢复事务：生成图片、对应元数据及人物修脸前原图进入 E:/Dream/data/history-trash；不删除人物档案、参考照、冻结任务参数或模型。
- 不包含批量勾选删除、回收站管理/一键恢复界面、人物相似度或修脸算法调整。

## 验证
- 前端：276 passed / 25 files，日志 E:/Dream/test-runs/delete-ui-final-20261010.log。
- 后端：684 passed / 1 existing Pillow deprecation warning，日志 E:/Dream/test-runs/delete-backend-final-20261010.log。
- TypeScript 与生产构建通过，日志 E:/Dream/test-runs/delete-build-20261010.log。
- 独立审查最初发现并修复三项边界问题，复审无剩余阻断项。
- 浏览器真实生成 DreamShaper XL Lightning，768×768、8 steps、CFG 2、seed 20261010，15.797 秒。
- 验收新图：取消删除后 PNG 仍在；确认删除后预览、检查器、变体和已打开历史同步移除；历史读回 404，生成参数保留。具体本机任务编号不随公开源码发布。
- 测试图及 JSON 已移入暂存区；提交收据保留在本机 history-trash 对应事务目录，不随公开源码发布。
- 人物结果 GUI 检查了现有正常任务的确认/取消入口，没有确认删除任何既有用户图片。批次删除、重开已删任务、回滚并发通过隔离后端集成及前端测试验证。
- 六个档案/参考照文件 SHA-256 前后相同。旧任务中已有一张文件缺失产生 404；未当成删除成功，也未修改该历史任务。
- 浏览器证据在 E:/Dream/worktrees/identity-sd15/output/playwright/delete-*.yml 与 delete-confirm.png。

## 发布和回退
- 正式入口：http://127.0.0.1:8766/，release.json = image-delete-20261010。
- 服务更新前确认无人物任务或生图工作进程运行；使用已有官方启动脚本重新启动，health ready。
- 构建 JS：index-DP-iLHYo.js，SHA-256 ED7FD481C1534BD61791254FED2B49773CFD0C273C7C8E755B6099D238DD52FD。
- 本次源文件已同步到 E:/Dream/repo，保留服务目录原有未提交修改。
- 更新前源码和前端备份：E:/Dream/backups/image-delete-20261010/。
- 回退需先确认没有生成任务，再恢复备份里的对应源码/前端并用 scripts/start_dream_web_background.ps1 -Port 8766 -NoBrowser 启动。新建文件保留但旧入口不引用即可；不清理任何用户数据。
- 暂存删除不是立即释放磁盘空间。恢复文件须核对 committed.json 的 source/staged 逐项恢复并处理收据，当前未提供恢复按钮。
