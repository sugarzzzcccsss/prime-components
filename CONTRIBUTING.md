# 参与 Prime Components

欢迎代码、实物数据、协议讨论、实验复现和失败报告。维护者账号为 `sugarzzzcccsss`。当前项目处于研究起点，设计草案可通过带依据的提案修改。

## 最短贡献路径

1. 运行 README 的测试及与你的贡献有关的命令，阅读对应研究边界。
2. 从 [路线图](docs/roadmap.md) 选择一个问题，或提交描述清楚的新问题。
3. 小修改直接提交 PR；硬件接口、任务集或性能定义的改变先说明输入、替代方案和验收条件。
4. 在 PR 中写明变化、测试、原始数据位置和仍未验证的部分。

英文和中文均可。不能将参考模型结果称为硬件成绩，或以标称 TOPS 推导应用性能。负结果与正结果使用相同记录要求；保留失败次数，避免只报告成功样本。

## 本地检查

```sh
python -m unittest discover -s tests -v
python -m prime_components demo --output results/demo.json
python -m prime_components compute --output results/compute.json
python -m prime_components portfolio --output results/portfolio.json
python -m prime_components runtime --output results/runtime.json
```

`runtime` 会启动并回收本机工作进程，其中一个将被实验主动终止。它只操作本次启动的子进程。贡献运行时改动时，要保留失败报告、结果摘要和事件轨迹；检查全部工作进程是否已退出。新协调策略应使用相同输入与基线比较，不以一次测时宣布性能提升。

只修改文档时核对链接、命令和主张即可；模型或代码改变应补充能捕获错误的测试。生成输出默认放在被忽略的 `results/`；需要作为研究证据提交的文件应放入明确命名的 `benchmarks/` 子目录，并写明是否实测。

## 提交数据与许可

仅提交有权公开的数据和代码。去除设备密钥、访问凭据、私人影像及无关个人信息。记录软件、固件和模型许可；大文件先说明下载与校验方式，不把不明来源资源直接放进仓库。

软件与原创文档贡献采用仓库 MIT 许可。未来 CAD、PCB、固件与硬件数据在加入时分别明确许可，不用软件许可声明暗示已经完成整套开放硬件授权。

维护者以可复现性和证据作决定。涉及设备执行的缺陷应说明触发条件与测试范围；未审查的示例不得直接接入真实执行器。当前仓库没有此类驱动。
