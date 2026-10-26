# Prime Components · 素数零件

**模块化智能组件的开放研究项目：用尽可能少的模块型号，组合、计算、维修，完成明确的一组现实任务。**

[English](README.en.md) · [进程故障实验](docs/runtime.md) · [跨任务选择](docs/portfolio.md) · [研究问题](docs/vision.md) · [相关工作](docs/references.md) · [参与贡献](CONTRIBUTING.md)

我们希望机器人可以像可维护的基础设施一样，由可识别、可组合、可替换的智能组件构成。不同形态共享模块、接口和软件；任务变化时重新组合，部件失效时替换或重新分配工作。端侧计算节点可以按任务协作，减少对远程服务的依赖。

“素数零件”是这个项目的设计隐喻。这里的“最少”必须相对于任务集、环境和性能约束定义；不主张机械系统拥有数学上的唯一分解。

## 当前状态 · v0.2.0 可运行的协作与恢复实验

现在可以在一台电脑上启动多个独立 Python 工作进程，通过本机 HTTP 分配真实的 SHA-256 计算任务。实验会终止一个已经领到任务的进程，把未完成任务重新分配，再与单进程计算结果逐项核对。

这是真实的进程与通信实验，采用单协调器作为基线。它仍没有硬件机器人、跨设备协作推理或去中心化一致性实现。

| 已可运行 | 还需要证明 |
| --- | --- |
| 多工作进程、真实 HTTP 请求、在途任务故障注入和重派 | 多台设备、断网与分区、协调器故障恢复 |
| 任务尝试编号、旧分配或重复结果拒收、事件时间记录 | 跨协调器一致性、持久化恢复、物理动作安全 |
| 为整组顺序任务精确选择共享模块库存 | 几何连接、负载、型号规格的实物验证 |
| 原有功能组合模型与通信开销计算器 | 真实设备的推理质量、能耗和扩展上限 |

模块规划仍是给定有限库存中的符号能力计算；没有发现通用世界中的最小零件集合。多个工作进程共享同一台电脑的 CPU、内存和操作系统，测得时间不能作为硬件集群或数据中心性能证据。

## 五分钟运行

在仓库根目录使用 Python 3.10 或更高版本；无第三方依赖。

```sh
git clone https://github.com/sugarzzzcccsss/prime-components.git
cd prime-components
```

已下载 ZIP 或已有本地副本时，直接进入项目目录执行：

```sh
python -m unittest discover -s tests -v
python -m prime_components runtime --output results/runtime.json
python -m prime_components portfolio --output results/portfolio.json
python -m prime_components demo --output results/demo.json
python -m prime_components compute --output results/compute.json
```

`runtime` 比较单工作进程、多工作进程正常、多工作进程故障三种场景，保存结果与事件轨迹。`portfolio` 展示整组任务共同选库存与各自选最优组合的差异。具体边界和报告字段见 [运行说明](docs/runtime.md) 与 [规划说明](docs/portfolio.md)。

`demo` 保留首版的状态字段故障演示。`compute` 仍是公式估算，参数均为教学假设；它的结果要与 `runtime` 的实际进程测时区分。

可修改 JSON 后复跑，不必修改程序：

```sh
python -m prime_components demo --catalog examples/catalog.json --fail sense-a --output results/demo-custom.json
python -m prime_components compute --input examples/compute.json --output results/compute-custom.json
python -m prime_components portfolio --input examples/portfolio.json --output results/portfolio-custom.json
```

v0.2 的运行结果见 [验收记录](docs/validation-v0.2.0.md)。首版公式与符号模型记录保留在 [v0.1 验收记录](docs/validation.md) 和 [模型示例](benchmarks/model-v0.1.0)。

## 三个核心研究问题

1. **少型号是否值得？** 用相同的模块库存完成多种任务，相比专用方案，能否减少库存与维修成本，同时保持任务质量？
2. **协作计算何时值得？** 在相同模型、精度和功耗口径下，哪些任务适合本地执行、整任务分配或跨节点切分？
3. **故障后能否更快恢复？** 从故障发生直到首个合格任务完成，需要多久，失败率是多少？

大型数据中心的等效性能是远期假设，不能由模块数量乘以标称 TOPS 得出。应先取得少量设备在某一明确工作负载上的可复现收益。

## 从哪里贡献

第一批工作是记录真实设备和网络的测量数据、建立模块描述格式、验证一个小型任务集，以及测量故障恢复全过程。具体完成条件见 [路线图](docs/roadmap.md)。欢迎提交失败结果，只要条件、数据和复现步骤清楚。

软件与本仓库原创文档采用 [MIT License](LICENSE)。第三方论文与标准仅链接引用，未重新授权；目前没有 CAD、PCB、固件或 BOM 可供制造。未来硬件设计发布时需另行明确许可和适用范围。
