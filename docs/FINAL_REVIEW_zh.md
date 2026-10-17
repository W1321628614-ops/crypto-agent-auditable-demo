# Task17G 最终验收

**READY_FOR_USER_APPROVAL**

本轮只完善独立公开候选。运行代码与合成fixture未改，未扩大交易功能。已完成必要的文档、许可、身份、安全与复现检查；下一步仅等待用户最终批准是否发布。

## 1. 实际修改

修改：`.gitignore`、`README.md`、`LICENSE_STATUS.md`、`pyproject.toml`、`docs/PORTFOLIO.md`、`docs/PUBLIC_AUDIT.md`、`docs/SECURITY.md`、`docs/VERIFICATION.md`。

新增：`README.zh-CN.md`、`LICENSE`、`THIRD_PARTY_NOTICES.md`、`docs/dependency_licenses.json`、`docs/task17g_validation.json`、`docs/task17g_tests.txt`、`docs/task17g_safety.json`及本报告。

打包元数据声明MIT；为支持该标准许可表达方式，setuptools构建最低版本从68调整为77，实际验收使用84.0.0。没有改动模型契约、撮合、风控、策略或原私有项目。

## 2. 名称、简介与README

- 建议仓库名：`crypto-agent-auditable-demo`。
- 展示名：**Crypto Agent — Auditable AI Research & Paper-Trading System**。
- GitHub Description：An auditable AI-assisted market research and paper-trading system featuring decision freezing, deterministic simulation, and reproducible offline demos.
- 中文定位：可审计的AI辅助市场研究与模拟交易系统。

README以英文为主，提供中文文档，包含动机、能力、架构图、快速运行、离线Demo、复现、负责人贡献、AI辅助开发、限制及许可。明确：负责人发起并持续主导需求、研究方法、取舍、实验、评估及验收，大量工程实现由Codex等工具辅助；不声称独立手写全部代码或已掌握每项技术。

## 3. MIT与第三方许可

完整标准MIT文本在LICENSE，版权行为：

`Copyright (c) 2026 W1321628614-ops`

署名和MIT选择均已获用户明确确认。许可仅覆盖所有者有权授权的候选内容，不开放任何未纳入的私有知识、策略、数据或模型原答。

实际安装依赖及构建工具的声明均为MIT：jsonschema 4.26.0、attrs 26.1.0、jsonschema-specifications 2025.9.1、referencing 0.37.0、rpds-py 2026.9.1、setuptools 84.0.0。根许可原文保留于THIRD_PARTY_NOTICES.md；依赖源码、二进制及虚拟环境不随候选分发。未来若打包整个环境，应重新检查其中的嵌入组件许可。未发现需要额外授权的外部素材或vendored代码。

核对参考：[MIT原文](https://opensource.org/license/mit)。

## 4. Git身份、历史与本地所有者

- author/committer均为 `W1321628614-ops`，邮箱仅使用 `242327958+W1321628614-ops@users.noreply.github.com`。
- GitHub连接器独立核对账户login及数字ID；用户在Settings → Emails确认该noreply，以及Keep my email addresses private、Block command line pushes that expose my email均已开启。
- 用户已批准只在候选中规范化唯一未发布提交。最终候选保持单个root提交、仅main分支、无remote；可达历史及活动对象库中无旧占位身份。旧Git管理记录完整归档在独立本地验收区，不作为分支、标签、alternate或发布内容。
- 没有通过实际push测试GitHub服务端归属显示，因为本轮禁止发布；账户匹配、格式、用户设置确认与本地提交字段已经分别核查，不将其冒充服务端实测。
- 候选本地所有者为管理员组，非提升Git可能提示不同所有者。未改全局safe.directory、未加通配信任、未改ACL。运行Python Demo不要求管理员；本地信任或归属由用户在发布前针对这一明确目录审阅。

参考：[GitHub noreply格式](https://docs.github.com/en/account-and-profile/reference/email-addresses-reference)、[隐私保护选项](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/blocking-command-line-pushes-that-expose-your-personal-email-address)。

## 5. 安全与人工语义复核

公开候选文件、隐藏文件、配置、全部活动Git对象、可达历史与引用检查无待处理泄漏项；没有额外发布引用、原私有Git继承或外部对象库。

人工核对：数据为DEMOUSD合成fixture，回答明确mock；参数为展示用配置，未包含私有信号组合、KOL材料、真实策略/模型原答、账户、研究结论或交易记录。README没有把较大私有系统的功能当作本版实现，也没有把42项工程测试当作AI能力或交易收益。

原始安装日志、环境、旧Git档案均在候选外；仅脱敏测试记录与验收摘要进入docs。没有将连接器附带的非公开账户字段写入候选、报告或提交。源码未发现硬编码的私人绝对路径；运行中的系统异常仍可能包含用户输入路径，因此不直接发布原始运行日志或录屏私人窗口。

本检查不是对任意秘密不存在的数学证明，不认证原私有仓库可公开。hash也不是系统读取隔离或恶意重写保护。

## 6. 安装、测试、Demo与恢复

- 全新独立venv，从候选的独立构建副本执行README的 `pip install .`；包实际从新环境site-packages加载，pip check通过。
- 固定已核查版本的常规依赖从公开PyPI取得，后续安装使用本地wheelhouse；无模型请求或付费API。
- 42项现有自动化测试全部通过，0跳过；没有为适应文档改写测试或运行代码。
- 模块入口与research-demo入口通过；start、packet、import、advance、pause、status、resume、report均实际执行。
- 完整离线Demo、新进程恢复、暂停/继续通过；阻断socket后的Demo通过。
- 1笔故意构造的合成止损与后续no_trade仅验证流程，不是真实AI决策或盈利样本。

机器记录见task17g_validation.json，脱敏测试全文见task17g_tests.txt。平台实测为Windows x64/Python3.13；其他平台和声明支持的其余Python版本未逐一验收。

## 7. 剩余限制与下一步

没有未确认的版权署名、公开Git身份或已发现的第三方授权阻断项。尚需的只是用户对候选内容和实际发布的最终批准；本轮没有获得发布权限。

保留的产品限制：无实时模型/行情接入、无自主工具选择循环、无实盘；K线内顺序保守处理，跳空风险可能超预算；hash不能代替隔离；没有盈利/OOS结论。实际GitHub提交归属显示只能在未来获得发布授权后核查，不能通过本轮擅自推送验证。

建议下一步先由负责人结合真实代码解释因果输入、冻结、风控、撮合与恢复，准备演示；不再增加交易或网页试用功能。

**未创建远程仓库、未添加 remote、未 push、未公开发布、未修改原始私有项目。**
