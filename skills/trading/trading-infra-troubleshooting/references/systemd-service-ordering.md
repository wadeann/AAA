# Systemd Service Ordering: MCP → Gateway

## 问题

`hermes gateway restart` 或系统重启后，Hermes Agent 找不到 MCP tools（`mcp_intel_*`, `mcp_risk_*`, `mcp_exec_*`），显示"MCP server failed initial connection after 3 attempts, giving up"。

## 根因

`hermes-gateway.service` 和 `pup-mcp.service` 同时启动，但 MCP server 需要 5-30s 初始化（Intel 的 DB 重建 + Flask 启动），Gateway 先起来后 MCP 还没就绪，重试3次放弃后永久不重连。

## 修复

### `pup-mcp.service` 增加 `Before=`

```ini
[Unit]
Description=Pup-MCP Sovereign Suite (Unified)
After=network.target
Before=hermes-gateway.service
```

### `hermes-gateway.service` 增加 `After=` + `Requires=`

```ini
[Unit]
Description=Hermes Agent Gateway - Messaging Platform Integration
After=network-online.target pup-mcp.service
Wants=network-online.target
Requires=pup-mcp.service
```

### 应用

```bash
systemctl --user daemon-reload
systemctl --user restart pup-mcp.service
systemctl --user restart hermes-gateway.service
```

## 验证

```bash
# 检查服务状态
systemctl --user is-active pup-mcp.service  # 应返回 active
systemctl --user is-active hermes-gateway.service  # 应返回 active

# 检查 MCP 端口监听
ss -tlnp | grep -E '900[123]'

# 从 gateway 进程检查 MCP 连接
hermes mcp list
# 应显示 intel/risk/exec 三个全部 ✓ enabled

# 直接 MCP tool 调用（任意一个）
systemctl --user status hermes-gateway.service | grep -i mcp
```

## 警告

- 如果 `pup-mcp.service` 启动失败，`hermes-gateway.service` 也会启动失败（`Requires=` 语义）
- 这不是 bug，而是正确行为——MCP 不可用时 gateway 没有意义
- 如需独立调试 gateway，临时注释 `Requires=` 行再 restart
