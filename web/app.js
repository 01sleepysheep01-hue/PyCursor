"use strict";

const ui = {
  body: document.body,
  connectionChip: document.getElementById("connectionChip"),
  connectionStatus: document.getElementById("connectionStatus"),
  modelChip: document.getElementById("modelChip"),
  modelStatus: document.getElementById("modelStatus"),
  mcpChip: document.getElementById("mcpChip"),
  mcpStatus: document.getElementById("mcpStatus"),
  authButton: document.getElementById("authButton"),
  workspacePath: document.getElementById("workspacePath"),
  fileSummary: document.getElementById("fileSummary"),
  fileList: document.getElementById("fileList"),
  refreshFiles: document.getElementById("refreshFiles"),
  messages: document.getElementById("messages"),
  emptyState: document.getElementById("emptyState"),
  traceList: document.getElementById("traceList"),
  clearTrace: document.getElementById("clearTrace"),
  taskForm: document.getElementById("taskForm"),
  promptInput: document.getElementById("promptInput"),
  sendTask: document.getElementById("sendTask"),
  stopTask: document.getElementById("stopTask"),
  newChat: document.getElementById("newChat"),
  authDialog: document.getElementById("authDialog"),
  authForm: document.getElementById("authForm"),
  tokenInput: document.getElementById("tokenInput"),
  loginButton: document.getElementById("loginButton"),
  authError: document.getElementById("authError"),
  toast: document.getElementById("toast"),
  tabButtons: Array.from(document.querySelectorAll(".mobile-tabs button")),
  suggestions: Array.from(document.querySelectorAll(".suggestion")),
};

const state = {
  sessionId: null,
  activeTaskId: null,
  stream: null,
  busy: false,
  authRequired: false,
  toolNodes: new Map(),
  toastTimer: null,
};

const streamEventTypes = [
  "task.queued",
  "task.started",
  "model.started",
  "model.completed",
  "assistant.thought",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "change.diff",
  "hook.post_tool",
  "context.compacted",
  "agent.reminder",
  "assistant.message",
  "task.completed",
  "task.cancelled",
  "task.failed",
];

class APIError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "APIError";
    this.status = status;
  }
}

function createElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  return node;
}

function truncate(text, limit) {
  const value = String(text === undefined || text === null ? "" : text);
  if (value.length <= limit) {
    return value;
  }
  return value.slice(0, limit) + "\n… 已截断 " + (value.length - limit) + " 个字符";
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) {
    return "";
  }
  if (bytes < 1024) {
    return bytes + " B";
  }
  if (bytes < 1024 * 1024) {
    return (bytes / 1024).toFixed(1) + " KB";
  }
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function basename(path) {
  const parts = String(path || "").split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

function setChip(chip, label, tone) {
  chip.classList.remove("status-neutral", "status-ok", "status-busy", "status-error");
  chip.classList.add("status-" + tone);
  const textNode = chip.querySelector("span:last-child");
  if (textNode) {
    textNode.textContent = label;
  }
}

function showToast(message, isError) {
  window.clearTimeout(state.toastTimer);
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", Boolean(isError));
  ui.toast.hidden = false;
  state.toastTimer = window.setTimeout(() => {
    ui.toast.hidden = true;
  }, 4200);
}

async function api(path, options) {
  const config = Object.assign({}, options || {});
  config.credentials = "same-origin";
  config.headers = new Headers(config.headers || {});
  const response = await fetch(path, config);
  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json")) {
    payload = await response.json();
  } else {
    const text = await response.text();
    payload = text ? { error: text } : null;
  }
  if (response.status === 401) {
    openAuth();
  }
  if (!response.ok) {
    const message = payload && payload.error ? payload.error : "请求失败：" + response.status;
    throw new APIError(message, response.status);
  }
  return payload;
}

function openAuth(message) {
  ui.authDialog.hidden = false;
  ui.authError.textContent = message || "请输入启动服务时显示的访问令牌。";
  window.setTimeout(() => ui.tokenInput.focus(), 30);
}

function closeAuth() {
  ui.authDialog.hidden = true;
  ui.authError.textContent = "";
  ui.tokenInput.value = "";
}

async function login(event) {
  event.preventDefault();
  const token = ui.tokenInput.value.trim();
  if (!token) {
    ui.authError.textContent = "令牌不能为空。";
    return;
  }
  ui.loginButton.disabled = true;
  ui.authError.textContent = "正在验证…";
  try {
    await api("/api/web/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    closeAuth();
    showToast("访问令牌验证成功");
    await refreshStatus();
  } catch (error) {
    ui.authError.textContent = error.message || "访问令牌不正确。";
  } finally {
    ui.loginButton.disabled = false;
  }
}

async function refreshStatus() {
  try {
    const health = await api("/api/health");
    state.authRequired = Boolean(health.auth_required);
    ui.authButton.hidden = !state.authRequired;
    ui.workspacePath.textContent = health.workspace || "未配置工作区";
    ui.workspacePath.title = health.workspace || "";
    setChip(ui.connectionChip, "H5 在线", "ok");
    setChip(ui.modelChip, health.model || "DeepSeek", "ok");
    ui.modelStatus.title = "CodeProof " + (health.version || "");
    const results = await Promise.allSettled([
      api("/api/mcp/status"),
      api("/api/files"),
    ]);
    if (results[0].status === "fulfilled") {
      renderMcp(results[0].value);
    } else {
      setChip(ui.mcpChip, "MCP 不可用", "error");
    }
    if (results[1].status === "fulfilled") {
      renderFiles(results[1].value);
    } else {
      renderFileError(results[1].reason);
    }
  } catch (error) {
    if (error.status === 401) {
      setChip(ui.connectionChip, "等待令牌", "busy");
      return;
    }
    setChip(ui.connectionChip, "连接失败", "error");
    showToast(error.message || "无法连接 CodeProof 服务", true);
  }
}

function renderMcp(status) {
  const servers = status && status.servers ? Object.keys(status.servers) : [];
  const running = servers.filter((name) => status.servers[name].running);
  const toolCount = running.reduce((total, name) => {
    return total + (status.servers[name].tools || []).length;
  }, 0);
  if (running.length) {
    setChip(ui.mcpChip, "MCP " + running.length + " · " + toolCount + " 工具", "ok");
  } else if (servers.length) {
    setChip(ui.mcpChip, "MCP 未运行", "error");
  } else {
    setChip(ui.mcpChip, "MCP 未配置", "neutral");
  }
}

function renderFileError(error) {
  ui.fileSummary.textContent = "工作区文件读取失败";
  ui.fileList.replaceChildren(createElement("li", "file-placeholder", error.message || "无法读取文件"));
}

function renderFiles(payload) {
  const entries = Array.isArray(payload.entries) ? payload.entries.slice() : [];
  ui.workspacePath.textContent = payload.root || ui.workspacePath.textContent;
  ui.workspacePath.title = payload.root || "";
  const files = entries.filter((entry) => entry.kind === "file").length;
  ui.fileSummary.textContent = entries.length + " 个条目 · " + files + " 个文件";
  ui.fileList.replaceChildren();
  if (!entries.length) {
    ui.fileList.appendChild(createElement("li", "file-placeholder", "工作区为空"));
    return;
  }
  entries.slice(0, 180).forEach((entry) => {
    const item = createElement("li");
    const icon = createElement(
      "span",
      "file-icon" + (entry.kind === "dir" ? " dir-icon" : ""),
      entry.kind === "dir" ? "▸" : "·",
    );
    const name = createElement("span", "file-name", entry.path || entry.name);
    name.title = entry.path || entry.name;
    const size = createElement("span", "file-size", formatBytes(entry.size));
    item.append(icon, name, size);
    ui.fileList.appendChild(item);
  });
  if (entries.length > 180) {
    ui.fileList.appendChild(
      createElement("li", "file-placeholder", "仅显示前 180 个条目"),
    );
  }
}

function setBusy(busy) {
  state.busy = busy;
  ui.sendTask.disabled = busy;
  ui.promptInput.disabled = busy;
  ui.stopTask.hidden = !busy;
  setChip(
    ui.connectionChip,
    busy ? "智能体运行中" : "H5 在线",
    busy ? "busy" : "ok",
  );
}

function addMessage(role, text, options) {
  const settings = options || {};
  ui.emptyState.hidden = true;
  const article = createElement("article", "message " + role);
  const avatar = createElement("div", "message-avatar", role === "user" ? "我" : "C");
  const body = createElement("div", "message-body");
  const meta = createElement("div", "message-meta");
  meta.append(
    createElement("span", "", settings.label || (role === "user" ? "你" : "CODEPROOF")),
    createElement("span", "", new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })),
  );
  const content = createElement("pre", "message-text", text);
  if (settings.error) {
    article.classList.add("error");
  }
  body.append(meta, content);
  article.append(avatar, body);
  ui.messages.appendChild(article);
  scrollMessages();
  return article;
}

function scrollMessages() {
  ui.messages.scrollTop = ui.messages.scrollHeight;
}

function resetTrace() {
  state.toolNodes.clear();
  ui.traceList.replaceChildren();
  const placeholder = createElement("div", "trace-placeholder");
  placeholder.append(
    createElement("strong", "", "还没有轨迹"),
    createElement("span", "", "发送任务后，这里会出现模型决策、工具参数、返回结果和 diff。"),
  );
  ui.traceList.appendChild(placeholder);
}

function ensureTraceReady() {
  const placeholder = ui.traceList.querySelector(".trace-placeholder");
  if (placeholder) {
    placeholder.remove();
  }
}

function traceTime(event) {
  const stamp = event && event.timestamp ? new Date(event.timestamp * 1000) : new Date();
  return stamp.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function addTrace(kind, title, detail, event, tone) {
  ensureTraceReady();
  const item = createElement("article", "trace-item " + (tone || ""));
  const head = createElement("div", "trace-head");
  head.append(
    createElement("span", "trace-title", title),
    createElement("span", "trace-time", traceTime(event)),
  );
  item.appendChild(head);
  if (detail) {
    item.appendChild(createElement("pre", "trace-detail", truncate(detail, 5000)));
  }
  ui.traceList.appendChild(item);
  ui.traceList.scrollTop = ui.traceList.scrollHeight;
  return item;
}

function addDiff(step, path, diff, event) {
  ensureTraceReady();
  const item = createElement("article", "trace-item ok");
  const head = createElement("div", "trace-head");
  head.append(
    createElement("span", "trace-title", "step " + step + " · diff · " + (path || "unknown")),
    createElement("span", "trace-time", traceTime(event)),
  );
  const pre = createElement("pre", "diff-block");
  String(diff || "").split("\n").forEach((line) => {
    let className = "diff-line";
    if (line.startsWith("+") && !line.startsWith("+++")) {
      className += " add";
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      className += " remove";
    } else if (line.startsWith("@@")) {
      className += " hunk";
    }
    pre.appendChild(createElement("span", className, line || " "));
  });
  item.append(head, pre);
  ui.traceList.appendChild(item);
  ui.traceList.scrollTop = ui.traceList.scrollHeight;
}

function toolKey(event) {
  return String(event.call_id || event.seq || event.step + "-" + event.name);
}

function updateTool(event, completed, failed) {
  const key = toolKey(event);
  const node = state.toolNodes.get(key);
  if (!node) {
    return;
  }
  node.classList.remove("running");
  node.classList.add(failed ? "error" : "ok");
  const status = failed ? "失败" : "完成";
  const title = node.querySelector(".trace-title");
  if (title) {
    title.textContent = "step " + event.step + " · " + event.name + " · " + status;
  }
  const detail = failed ? event.error : event.content;
  if (detail) {
    node.appendChild(createElement("pre", "trace-detail", truncate(detail, 5000)));
  }
}

function handleStreamEvent(type, event) {
  if (type === "task.queued") {
    addTrace("queued", "任务已进入队列", "task " + (event.task_id || ""), event);
    return;
  }
  if (type === "task.started") {
    addTrace("running", "模型开始决策 · " + (event.model || "DeepSeek"), "", event, "running");
    return;
  }
  if (type === "model.started") {
    addTrace("running", "step " + event.step + " · 等待模型", "", event, "running");
    return;
  }
  if (type === "model.completed") {
    const usage = event.usage || {};
    addTrace(
      "ok",
      "step " + event.step + " · 模型返回",
      usage.total_tokens ? "tokens: " + usage.total_tokens : "",
      event,
      "ok",
    );
    return;
  }
  if (type === "assistant.thought") {
    addTrace("model", "step " + event.step + " · 模型说明", event.content, event);
    return;
  }
  if (type === "tool.started") {
    ensureTraceReady();
    const item = createElement("article", "trace-item running");
    const head = createElement("div", "trace-head");
    head.append(
      createElement("span", "trace-title", "step " + event.step + " · " + event.name + " · 运行中"),
      createElement("span", "trace-time", traceTime(event)),
    );
    item.appendChild(head);
    const args = JSON.stringify(event.arguments || {}, null, 2);
    item.appendChild(createElement("pre", "trace-detail", truncate(args, 4000)));
    ui.traceList.appendChild(item);
    state.toolNodes.set(toolKey(event), item);
    ui.traceList.scrollTop = ui.traceList.scrollHeight;
    setChip(ui.connectionChip, event.name + " 运行中", "busy");
    return;
  }
  if (type === "tool.completed") {
    updateTool(event, true, false);
    setChip(ui.connectionChip, "智能体运行中", "busy");
    return;
  }
  if (type === "tool.failed") {
    updateTool(event, false, true);
    setChip(ui.connectionChip, "工具失败，模型继续处理", "busy");
    return;
  }
  if (type === "change.diff") {
    addDiff(event.step, event.path, event.diff, event);
    return;
  }
  if (type === "hook.post_tool") {
    addTrace(
      "ok",
      "PostToolUse 测试 · exit " + event.exit_code,
      event.command + "\n" + event.summary,
      event,
      event.exit_code === 0 ? "ok" : "error",
    );
    return;
  }
  if (type === "context.compacted") {
    addTrace(
      "info",
      "上下文已压缩",
      event.before_chars + " → " + event.after_chars + " 字符",
      event,
    );
    return;
  }
  if (type === "agent.reminder") {
    addTrace("error", "Agent 防循环提醒", event.message, event, "error");
    return;
  }
  if (type === "assistant.message") {
    addMessage("assistant", event.content || "");
    return;
  }
  if (type === "task.completed") {
    finishTask("completed", event);
    return;
  }
  if (type === "task.cancelled") {
    finishTask("cancelled", event);
    return;
  }
  if (type === "task.failed") {
    finishTask("failed", event);
  }
}

function openStream(url) {
  if (state.stream) {
    state.stream.close();
  }
  const source = new EventSource(url);
  state.stream = source;
  streamEventTypes.forEach((type) => {
    source.addEventListener(type, (message) => {
      try {
        const payload = JSON.parse(message.data);
        handleStreamEvent(type, payload);
      } catch (error) {
        addTrace("error", "事件解析失败", error.message, null, "error");
      }
    });
  });
  source.onopen = () => {
    addTrace("ok", "SSE 已连接", "实时事件流已建立", null, "ok");
  };
  source.onerror = () => {
    if (state.busy && source.readyState !== EventSource.CLOSED) {
      setChip(ui.connectionChip, "事件流重连中", "busy");
    }
  };
}

async function submitTask(event) {
  event.preventDefault();
  if (state.busy) {
    return;
  }
  const prompt = ui.promptInput.value.trim();
  if (!prompt) {
    showToast("请先输入任务", true);
    return;
  }
  addMessage("user", prompt);
  ui.promptInput.value = "";
  setBusy(true);
  try {
    const task = await api("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        session_id: state.sessionId,
      }),
    });
    state.sessionId = task.session_id;
    state.activeTaskId = task.task_id;
    addTrace("queued", "任务 " + task.task_id, "session " + task.session_id, null);
    openStream(task.events_url);
  } catch (error) {
    setBusy(false);
    addMessage("assistant", error.message || "任务启动失败", { error: true, label: "运行失败" });
    showToast(error.message || "任务启动失败", true);
  }
}

async function stopTask() {
  if (!state.activeTaskId || !state.busy) {
    return;
  }
  ui.stopTask.disabled = true;
  try {
    await api("/api/tasks/" + encodeURIComponent(state.activeTaskId) + "/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    setChip(ui.connectionChip, "正在中断", "busy");
  } catch (error) {
    showToast(error.message || "中断失败", true);
    ui.stopTask.disabled = false;
  }
}

function finishTask(kind, event) {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
  state.activeTaskId = null;
  ui.stopTask.disabled = false;
  setBusy(false);
  if (kind === "completed") {
    const elapsed = event.elapsed === undefined ? "" : " · " + event.elapsed + " 秒";
    addTrace("ok", "任务完成 · " + (event.steps || "?") + " 步" + elapsed, "", event, "ok");
    setChip(ui.connectionChip, "完成" + elapsed, "ok");
    refreshFiles().catch(() => {});
  } else if (kind === "cancelled") {
    addMessage("assistant", event.content || "任务已中断", { error: true, label: "已中断" });
    addTrace("error", "任务已中断", "", event, "error");
    setChip(ui.connectionChip, "已中断", "error");
  } else {
    const error = event.error || event.content || "任务失败";
    addMessage("assistant", error, { error: true, label: "运行失败" });
    addTrace("error", "任务失败", error, event, "error");
    setChip(ui.connectionChip, "任务失败", "error");
  }
}

async function refreshFiles() {
  const payload = await api("/api/files");
  renderFiles(payload);
}

function newChat() {
  if (state.busy) {
    showToast("当前任务仍在运行，请先停止", true);
    return;
  }
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
  state.sessionId = null;
  state.activeTaskId = null;
  ui.messages.querySelectorAll(".message").forEach((node) => node.remove());
  ui.emptyState.hidden = false;
  resetTrace();
  setChip(ui.connectionChip, "H5 在线", "ok");
  ui.promptInput.focus();
}

function switchMobileView(view) {
  ui.body.dataset.mobileView = view;
  ui.tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
}

function bindEvents() {
  ui.taskForm.addEventListener("submit", submitTask);
  ui.stopTask.addEventListener("click", stopTask);
  ui.newChat.addEventListener("click", newChat);
  ui.clearTrace.addEventListener("click", resetTrace);
  ui.refreshFiles.addEventListener("click", () => {
    refreshFiles().catch((error) => showToast(error.message, true));
  });
  ui.authForm.addEventListener("submit", login);
  ui.authButton.addEventListener("click", () => openAuth());
  ui.promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      ui.taskForm.requestSubmit();
    }
  });
  ui.suggestions.forEach((button) => {
    button.addEventListener("click", () => {
      ui.promptInput.value = button.dataset.prompt || "";
      ui.promptInput.focus();
    });
  });
  ui.tabButtons.forEach((button) => {
    button.addEventListener("click", () => switchMobileView(button.dataset.view));
  });
}

async function init() {
  bindEvents();
  resetTrace();
  await refreshStatus();
}

init();
