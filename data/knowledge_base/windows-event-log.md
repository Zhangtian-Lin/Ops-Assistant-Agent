# Windows 事件日志排查（Demo SOP）

## 定位错误

排查系统异常时，按时间范围读取 System 和 Application 日志的 Error、Warning 事件。记录事件 ID、来源、时间和摘要；不要只凭单条错误就断定根因。

## 关联分析

将事件日志与服务状态、驱动异常、磁盘健康和网络状态交叉验证。导出或清理日志属于高影响操作，当前 Agent 只读，不自动删除或修改 Windows Event Log。
