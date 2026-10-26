# 本地进程实验记录

这些文件是合成 SHA-256 工作负载在一台电脑上的真实软件执行记录。它们不测量机器人硬件、跨设备网络或神经网络推理性能。

- `run-01.json`、`run-02.json`、`run-03.json`：单工作进程、多工作进程正常、多工作进程故障的结果与时间轨迹。
- `all-workers-unavailable.json`：所有初始工作进程退出，预留任务未完成的负例。
- `portfolio.json`：固定假设库存中的跨任务符号规划，里面的 W 数值不是测量值。
- `summary.json`：原始观察汇总、环境、参数和规范化源码摘要。
- `tests.txt`：本地完整测试输出。

重跑命令：`python scripts/record_local_evidence.py --output results/local-evidence`。请把你的新观察放在新的路径，不覆盖已有公开记录；环境和时间不同是正常现象。
