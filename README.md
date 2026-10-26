# Prime Components · 素数零件

**模块化智能组件的开放研究项目：用尽可能少的模块型号，组合、计算、维修，完成明确的一组现实任务。**

[English](README.en.md) · [研究问题](docs/vision.md) · [系统草案](docs/architecture.md) · [实验设计](docs/experiments.md) · [相关工作](docs/references.md) · [参与贡献](CONTRIBUTING.md)

我们希望机器人可以像可维护的基础设施一样，由可识别、可组合、可替换的智能组件构成。不同形态共享模块、接口和软件；任务变化时重新组合，部件失效时替换或重新分配工作。端侧计算节点可以按任务协作，减少对远程服务的依赖。

“素数零件”是这个项目的设计隐喻。这里的“最少”必须相对于任务集、环境和性能约束定义；不主张机械系统拥有数学上的唯一分解。

## 当前状态 · v0.1.0 研究起点

当前开放的是**研究文档和 Python 参考模型**，没有硬件样机、真实分布式运行时或已经达到数据中心性能的系统。

| 已可运行 | 还需要证明 |
| --- | --- |
| 读取虚构模块清单，按能力数量、接口标签、功耗筛选组合 | 几何连接、负载、精度、热设计和实际任务表现 |
| 将一个感知模块标记故障，再选择可用备用模块 | 真实故障检测、物理更换、重新标定和复工时间 |
| 计算串行比例与通信开销对协作计算收益的影响 | 真实设备上的吞吐、尾延迟、能耗和可靠性 |

局部穷举只寻找**给定库存内、单个功能任务**的最优组合；它没有发现通用世界中的最小零件集合。演示在一个 Python 进程内运行，也没有执行神经网络推理。

## 五分钟运行

在仓库根目录使用 Python 3.10 或更高版本；无第三方依赖。

```sh
python -m unittest discover -s tests -v
python -m prime_components demo --output results/demo.json
python -m prime_components compute --output results/compute.json
```

`demo` 展示功能组合和感知模块失效后的重新选择。`compute` 展示同样八个假设节点在不同通信条件下可能加速，也可能减速。所有参数均为教学假设，不是设备测量值；生成的 JSON 保留输入和结果，便于复算。

可修改 JSON 后复跑，不必修改程序：

```sh
python -m prime_components demo --catalog examples/catalog.json --fail sense-a --output results/demo-custom.json
python -m prime_components compute --input examples/compute.json --output results/compute-custom.json
```

本地运行结果见 [验收记录](docs/validation.md)，生成示例见 [benchmarks/model-v0.1.0](benchmarks/model-v0.1.0)。它们只验证软件模型，不验证实物。

## 三个核心研究问题

1. **少型号是否值得？** 用相同的模块库存完成多种任务，相比专用方案，能否减少库存与维修成本，同时保持任务质量？
2. **协作计算何时值得？** 在相同模型、精度和功耗口径下，哪些任务适合本地执行、整任务分配或跨节点切分？
3. **故障后能否更快恢复？** 从故障发生直到首个合格任务完成，需要多久，失败率是多少？

大型数据中心的等效性能是远期假设，不能由模块数量乘以标称 TOPS 得出。应先取得少量设备在某一明确工作负载上的可复现收益。

## 从哪里贡献

第一批工作是记录真实设备和网络的测量数据、建立模块描述格式、验证一个小型任务集，以及测量故障恢复全过程。具体完成条件见 [路线图](docs/roadmap.md)。欢迎提交失败结果，只要条件、数据和复现步骤清楚。

软件与本仓库原创文档采用 [MIT License](LICENSE)。第三方论文与标准仅链接引用，未重新授权；目前没有 CAD、PCB、固件或 BOM 可供制造。未来硬件设计发布时需另行明确许可和适用范围。
