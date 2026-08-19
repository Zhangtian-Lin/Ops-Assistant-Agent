# Windows 服务故障排查（Demo SOP）

## 服务未运行

先检查白名单服务的状态、最近错误和依赖服务。服务不存在、停止、启动失败要分别记录；不要根据自然语言直接执行启动、停止或重启。

## 处理建议

确认配置、端口冲突、权限和事件日志后，再把可选修复步骤交给人工审批。当前 Agent 只查询 nginx、mysql、redis、docker、ssh、postgresql、mongodb、httpd 等已注册服务。
