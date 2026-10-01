# pup-mcp 代码同步与服务重启工作流

## 标准流程

```bash
cd /home/ubuntu/ai/pup-mcp

# 1. 检查本地是否有未提交修改
git status

# 2. 如有本地修改，先提交
git add -A && git commit -m "local changes before pull"

# 3. 拉取最新代码
git pull

# 4. 检查 .env 是否存在（git pull 可能删除/覆盖 .env）
cat .env || echo "WARNING: .env missing!"

# 5. 安装新依赖（如有）
.venv/bin/pip install -r requirements.txt 2>/dev/null || true

# 6. 停止旧服务
bash scripts/stop.sh

# 7. 启动新服务（必须用 background，否则会阻塞）
cd /home/ubuntu/ai/pup-mcp && nohup bash scripts/start_all.sh > /dev/null 2>&1 &

# 8. 验证三个服务
sleep 3
curl -s http://localhost:9001/health
curl -s http://localhost:9002/health
curl -s http://localhost:9003/health
```

## 关键注意事项

1. **`.env` 可能被 git pull 删除** — 2026-06-15 事件：上游将 `.env` 从版本控制移除（`delete mode 100644 .env`），`git pull` 直接删除了本地 `.env`。拉取后务必检查 `.env` 是否还在，丢失则需要从 `.env.example` 重建。
2. **`.env` 应在 `.gitignore` 中** — 本地 `.env` 不应被追踪。如果被追踪，上游删除会影响本地。确保 `.gitignore` 包含 `.env`。
3. **启动脚本阻塞问题** — `scripts/start.sh` 和 `scripts/start_all.sh` 在前台运行（含 sleep 等待），直接在 terminal 执行会被阻塞或中断。用 `nohup ... &` 或 `bash -c '... &'` 后台运行。
4. **启动顺序** — start_all.sh 已内置正确顺序：intel(9001) → risk(9002) → exec(9003)。

## .env 必要字段

参考 `.env.example`，关键配置：
- `WENCAI_KEY_1` / `WENCAI_KEY_2` / `WENCAI_KEY_3` — 问财 API 密钥（3个）
- 数据源相关 token
- 其他服务配置

重建 .env 时：
```bash
cp .env.example .env
# 然后编辑填入实际密钥
vim .env
```
