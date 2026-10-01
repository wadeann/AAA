# Rust 安全审计常见模式库（AGY审计实战记录）

> 基于2026-09-07 openpup/core/src/mcp/ Rust代码AGY审计实战。AGY发现17个问题，经两轮审计+修复后尚有6个遗留问题需第三轮。

## 🔴 致命模式（Critical）

### 1. 路径穿越：`canonicalize` 失败回退 + `starts_with` 不抵消 `..`

```rust
// 🚨 错误模式
let parent = path.parent().unwrap_or(&path);
let resolved_parent = parent
    .canonicalize()
    .unwrap_or_else(|_| parent.to_path_buf()); // ← 保留".."！
let resolved = resolved_parent.join(filename);
if !resolved.starts_with(&app_root) { bail!(...); } // ← starts_with不抵消".."
```

**攻击向量**：`~/nonexistent/../../../../etc/passwd` → canonicalize失败保留`..` → starts_with误判为真 → 任意文件覆写

**修复方案**：纯词法 Component 解析，不用 `canonicalize` + `starts_with`：

```rust
fn safe_path(raw: &str) -> Result<PathBuf> {
    let expanded = /* expand ~ */;
    let mut normalized = PathBuf::new();
    for comp in expanded.components() {
        match comp {
            Component::ParentDir => {
                // 不能pop超过app_root的边界
                if normalized.components().count() <= app_root_components.len() {
                    bail!("Path escapes workspace root");
                }
                normalized.pop();
            }
            Component::Normal(c) => normalized.push(c),
            Component::RootDir => normalized.push(comp),
            _ => {}
        }
    }
    if !normalized.starts_with(&app_root) {
        bail!("Refusing: outside workspace");
    }
    Ok(normalized)
}
```

### 2. 命令注入：`cmd.exe /c` 参数传递

```rust
// 🚨 错误模式 — Windows
std::process::Command::new("cmd")
    .args(["/c", "start", "", url]) // ← url可以含 & | ^ %
```

Rust标准库在Linux/macOS下参数隔离，但Windows的`cmd.exe /c`把参数合并为字符串重新解析。

**修复方案**：URL字符白名单过滤（只允许URI安全字符），拒绝不符的URL：

```rust
let sanitised: String = url.chars()
    .filter(|c| c.is_ascii_alphanumeric() || ":/?#[]@!$&'()*+,;=-._~%".contains(*c))
    .collect();
if sanitised != url { bail!("URL contains shell metacharacters"); }
cmd.args(["/c", "start", "", &sanitised]).spawn()?;
```

**更优方案**：不用cmd.exe，改用 `rundll32 url.dll,FileProtocolHandler` 或 `open` crate。

### 3. 本地工具未注册进核心路由表

MCP系统中，本地工具在`list_all_tools()`中硬编码返回，但**不参与**catalog快照构建、OpenAI Schema生成和`resolve_fn_name`路由 → 系统功能链完全断裂但UI看起来正常。

**修复方案**：在`rebuild_catalog_snapshot()`中自动注入本地工具到`tool_cache`。

## 🟡 中危模式（Medium）

### 4. 符号链接绕过（TOCTOU）

在路径安全校验后，如果目标文件是符号链接 → follow link写入外部。`safe_path`无法阻止。

**修复**：对已存在的文件做完整路径`canonicalize()` + 再次校验：

```rust
if path.exists() {
    let real = path.canonicalize()?;
    if !real.starts_with(&app_root) {
        bail!("symlink target outside workspace");
    }
}
```

### 5. Token/凭据明文泄露

**三重泄漏渠道**：
- `list_servers()` 直接暴露明文token → 脱敏为`****`
- `persist()` 写到磁盘无权限限制 → 原子写入 + `chmod 0600`
- `#[derive(Debug)]` 打印完整token → 自定义Debug实现屏蔽敏感字段

### 6. SSRF：用户配置的base_url无校验

MCP服务器url由用户配置，可指向：
- `127.0.0.1`（本机服务） 
- `192.168.x.x`（内网）  
- `169.254.169.254`（云元数据端点）
- `file://` 等非HTTP协议

**修复**：`url::Url` 解析 → 检查scheme(http/https) → DNS解析检查IP网段：

```rust
fn validate_url_not_ssrf(raw: &str) -> Result<()> {
    let parsed = Url::parse(raw)?;
    if scheme != "http" && scheme != "https" { bail!(...); }
    if let Some(host) = parsed.host_str() {
        // 检查localhost/.local/metadata.google.internal等hostname
        // 检查169.254.169.254等已知元数据IP
        if let Some(ip) = parsed.socket_addrs(|| None)?.first() {
            if ip.is_loopback() || ip.is_private() || ... { bail!(...); }
        }
    }
}
```

⚠️ **注意**：`ip.is_private()` 等API在Rust稳定版可用，但需确认 `url` crate的 `socket_addrs` 在 `no_std` 或跨平台是否可用。若编译报错，剥离这部分到 `cfg(not(test))`。

### 7. 异步请求无超时

Tokio中的网络调用不设timeout → 挂起的连接永久阻塞。

**修复**：对每个请求/握手加`tokio::time::timeout`，单独设不同超时值：

```rust
let client = timeout(Duration::from_secs(15), ClientInfo::default().serve(transport))
    .await.map_err(|_| anyhow!("timeout (15s)"))?;
let result = timeout(Duration::from_secs(60), client.call_tool(req))
    .await.map_err(|_| anyhow!("timeout (60s)"))?;
```

### 8. 后台任务竞态（Zombie Discovery）

`tokio::spawn`发起的后台发现任务完成时，服务器可能已被删除或禁用。后完成的任务无条件写入工具缓存 → 复活已删除的服务。

**修复**：在`replace_server_tools`中检查服务的实时状态：

```rust
async fn replace_server_tools(&self, server_name: &str, tools: Vec<McpToolInfo>) {
    let guard = self.servers.read().await;
    if let Some(entry) = guard.get(server_name) {
        if !entry.enabled { return; } // 已禁用，丢弃
    } else { return; } // 已删除，丢弃
    // ...写入cache
}
```

注意：测试用例中可能未预先注册到`servers`，需要考虑兼容性。

### 9. 缓存击穿（Thundering Herd）

多个并发查询同时检测到嵌入向量缺失 → 各自触发一次独立的预热请求。

**修复**：Singleflight模式，用`in_flight: HashSet<String>`防止重复触发。

### 10. 配置非原子写入

`fs::write` 覆盖写 → 进程崩溃时截断文件 → 永久丢失配置。

**修复**：写临时文件 → `fs::rename` 是大多数文件系统上的原子操作：

```rust
let tmp = path.with_extension("tmp");
fs::write(&tmp, &json)?;
fs::rename(&tmp, path)?; // 原子替换
```

### 11. 异步上下文中同步阻塞I/O

Tokio async fn里直接调`std::fs` → 阻塞Worker线程。

**修复**：用`tokio::task::spawn_blocking`迁移阻塞操作到阻塞线程池。

## 🔵 低危模式（Low）

### 12. 大文件全量读取OOM

`fs::read_to_string` 无大小限制 → 读取大文件/字符设备耗尽内存。

**修复**：读取前检查 `metadata().len() > 5MB` 拒绝。

### 13. Schema空对象无type声明

工具参数为`{}`（无`type`字段）→ 大模型接口要求 `parameters` 必须有 `type: object` 和 `properties: {}`。

**修复**：空对象自动补全 `{ type: "object", properties: {} }`。

### 14. 中文分词失效

标准英文分词`split(|c| !c.is_alphanumeric())`对中文整句不切分。

**修复**：逐字符处理，CJK字符每个单独成词，ASCII按原有分隔符分词。

### 15. JSON Schema递归无上限

递归解析嵌套Schema时无深度保护 → 构造循环Schema可触发栈溢出。

**修复**：加`depth > 10`截断。

### 16. 工具名清洗冲突

非法字符转`_` → `tool-a`和`tool_a`冲突；服务名含`__` → 路由解析错位。

**注意**：`__`作为分隔符时，服务名不应包含`__`。

### 17. `Vec::remove(0)` O(n)性能

在循环中反复调用`remove(0)` → 每次全数组挪移。

**修复**：改用`VecDeque::pop_front()`。

## AGY审计流程（复用antigravity-audit技能）

此模式库配合 `antigravity-audit` skill 使用：
1. 准备prompt（文件路径 + 本模式库CWE清单）
2. 跑AGY第一轮审计 → 对照本模式库识别具体漏洞
3. 修复 → 跑AGY复审 → 循环到APPROVED签署
4. 有cargo环境时：修复后 `cargo check` 验证编译通过
