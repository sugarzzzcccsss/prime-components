# v0.1.0 验收记录

日期：2026-10-26。环境：Windows，Python 3.13.0。

## 本地验证

在独立项目目录运行以下命令，退出码均为 0：

```sh
python -m unittest discover -s tests -v
python -m prime_components demo --output results/demo.json
python -m prime_components compute --output results/compute.json
python -m prime_components demo --catalog examples/catalog.json --fail sense-a --output results/demo-custom.json
python -m prime_components compute --input examples/compute.json --output results/compute-custom.json
```

13 项测试通过，含非法输入、型号数优先、接口与功耗约束、故障替换与无备用件、重复能力计数、规模上限、串行基线、通信反例、数值溢出和 CLI 退出码。

原始测试文本与演示输出保存于 [模型验收目录](../benchmarks/model-v0.1.0)。这些是软件运行证据，参数均为假设值。

`survey` 初始选择 `sense-a`；将它设为 `fault` 后选择 `compute-a` 和 `sense-b`。这也说明备用感知实例并未独自恢复全部能力，重规划还需要算力实例提供示例中的 `mapping` 能力。

计算演示得到 1.645、5.825、163.425 秒，对应约 6.079、1.717、0.061 倍基线性能，详见 [公式与限制](experiments.md)。

## 独立复查与边界

代码复查发现并修正了 GitHub CI 根目录错误、重复示例文件、自定义输入入口和数值溢出处理。另一次只读复查通过运行命令验证了功能，并发现文档尚未写完时的缺失链接；发布前补齐目标文件并检查本地链接。

仓库 CI 配置 Windows/Ubuntu 与 Python 3.10/3.13 的四种组合。云端通过情况应以对应提交的 GitHub Actions 结果为准，不能由本地 Windows 成绩推断。

未验证实物组合、真网络发现与协同推理、几何和运动、故障检测时延、物理替换、标定、实际复工时间、能耗收益或数据中心等效性能。
