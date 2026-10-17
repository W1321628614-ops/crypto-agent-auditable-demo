# 安全范围与运行边界

公开候选只包含白名单通用代码、合成fixture和文档；没有继承原私有仓库Git历史。不要将私有备份、真实研究记录、环境配置或账号材料加入本目录。

## 实际保护

- 默认无网络代码、模型SDK、登录流程、交易账户或下单客户端。
- 运行目录独占创建；输入、原答和日志独占写入。拒绝覆盖历史原答。
- 输入hash、运行代码/Schema指纹、请求hash绑定、证据ID和日志链在重启时核对。
- 原答不通过时保存原字节及拒绝原因；不改写后追认通过。
- 新单须有明确数量、价格、期限和风险；不解析自然语言下单条件。
- mandatory暂停新委托，已有保护性止损/止盈继续执行；普通观察不生成模型决策。

## 未提供的安全保证

这不是恶意代码沙箱。运行Python程序的用户可能有权读取同一主机其他目录；数据前缀接口只保证代码逻辑的因果性，不能证明操作系统隔离。任意有写权限的人也可能重写完整hash链，因此hash不能替代签名、权限隔离或外部审计。

发生缺口、锁冲突、损坏或代码版本变化时程序安全停止，保留现场。不要通过手改JSON/hash恢复；先保留副本并人工查明原因。本版不提供自动解除不明锁或修复损坏状态的命令。

## 公开候选检查

候选交付前对普通与隐藏文件、路径、全部新Git对象和提交元数据进行本地扫描，检查凭据样式、身份信息、绝对路径、私有来源标识、缓存、日志和大型二进制。扫描结果见验证记录。

扫描不能证明不存在所有未知秘密，也不认证原私有仓库安全。原仓库的未引用对象和历史从未进入此仓库。提交前仍应复查暂存区，禁止从私有目录执行整体复制。

若未来出现凭据暴露，先阻止发布、保留证据，并由所有者决定撤销/轮换；不能以删除当前文件代替历史处理。


## Local Git ownership and publication boundary

The local review copy may be owned by an administrative group because it was created in an explicitly approved host execution context. Some non-elevated Git processes can therefore reject it as a different-owner repository. No global `safe.directory`, wildcard trust, ownership or ACL changes were made. Inspect the exact known directory before choosing any per-command trust or ownership adjustment; do not trust arbitrary repositories globally.

Only the reviewed `main` history is a possible future publication scope. Old placeholder-identity metadata is retained in a separate local acceptance archive, not in the active candidate object store or any branch/tag. Local raw installation logs and environments also remain outside the candidate. Do not publish `.git`, local audit archives or raw logs: an exception message may contain user-supplied paths even though the source contains no hardcoded private paths.
