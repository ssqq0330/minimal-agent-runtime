"use strict";

import {
  ApiError,
  clearMessages,
  createSession,
  deleteSession,
  healthCheck,
  listMessages,
  listSessions,
  renameSession,
  sendChat,
} from "/static/api.js";
import {
  changeUser,
  loadPreferences,
  patchState,
  restoreActiveSession,
  setActiveSession,
  setSidebarCollapsed,
  state,
} from "/static/state.js";
import { formatDateTime } from "/static/utils.js";

const MAX_MESSAGE_LENGTH = 8000;
const HEALTH_INTERVAL_MS = 45_000;

const dom = {
  body: document.body,
  userForm: document.querySelector("#user-form"),
  userInput: document.querySelector("#user-id-input"),
  applyUserButton: document.querySelector("#apply-user-button"),
  serviceStatus: document.querySelector("#service-status"),
  sessionSidebar: document.querySelector("#session-sidebar"),
  sessionList: document.querySelector("#session-list"),
  newSessionButton: document.querySelector("#new-session-button"),
  refreshSessionsButton: document.querySelector("#refresh-sessions-button"),
  toggleSidebarButton: document.querySelector("#toggle-sidebar-button"),
  currentSessionTitle: document.querySelector("#current-session-title"),
  currentSessionMeta: document.querySelector("#current-session-meta"),
  renameSessionButton: document.querySelector("#rename-session-button"),
  deleteSessionButton: document.querySelector("#delete-session-button"),
  clearMessagesButton: document.querySelector("#clear-messages-button"),
  messageList: document.querySelector("#message-list"),
  emptyChatState: document.querySelector("#empty-chat-state"),
  emptyChatTitle: document.querySelector("#empty-chat-state h3"),
  emptyChatCopy: document.querySelector("#empty-chat-state > p:last-child"),
  chatLoading: document.querySelector("#chat-loading"),
  chatLoadingCopy: document.querySelector("#chat-loading span:last-child"),
  messageForm: document.querySelector("#message-form"),
  messageInput: document.querySelector("#message-input"),
  sendButton: document.querySelector("#send-button"),
  characterCount: document.querySelector("#character-count"),
  toastContainer: document.querySelector("#toast-container"),
  sessionDialog: document.querySelector("#session-dialog"),
  sessionForm: document.querySelector("#session-form"),
  newSessionTitle: document.querySelector("#new-session-title"),
  newSessionId: document.querySelector("#new-session-id"),
  createSessionSubmit: document.querySelector("#create-session-submit"),
  renameDialog: document.querySelector("#rename-dialog"),
  renameForm: document.querySelector("#rename-form"),
  renameSessionTitle: document.querySelector("#rename-session-title"),
  renameSessionSubmit: document.querySelector("#rename-session-submit"),
  deleteDialog: document.querySelector("#delete-dialog"),
  deleteForm: document.querySelector("#delete-form"),
  deleteSessionDescription: document.querySelector("#delete-session-description"),
  confirmDeleteButton: document.querySelector("#confirm-delete-button"),
  clearDialog: document.querySelector("#clear-dialog"),
  clearForm: document.querySelector("#clear-form"),
  confirmClearButton: document.querySelector("#confirm-clear-button"),
};

let preferredSessionId = null;
let sessionRequestVersion = 0;
let messageRequestVersion = 0;

function activeSession() {
  return state.sessions.find((session) => session.session_id === state.activeSessionId) || null;
}

function setElementBusy(element, busy, busyLabel, idleLabel) {
  element.disabled = busy;
  element.textContent = busy ? busyLabel : idleLabel;
}

function openDialog(dialog) {
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeDialog(dialog) {
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

function renderSidebarState() {
  dom.body.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  dom.toggleSidebarButton.setAttribute("aria-expanded", String(!state.sidebarCollapsed));
  dom.toggleSidebarButton.setAttribute(
    "aria-label",
    state.sidebarCollapsed ? "展开 Session 侧边栏" : "收起 Session 侧边栏",
  );
}

function renderServiceStatus() {
  dom.serviceStatus.classList.remove("is-checking", "is-online", "is-degraded", "is-offline");
  const title = dom.serviceStatus.querySelector("strong");
  const details = dom.serviceStatus.querySelector("small");

  if (!state.serviceAvailable) {
    dom.serviceStatus.classList.add("is-offline");
    title.textContent = "服务离线";
    details.textContent = "等待后端恢复";
  } else if (!state.llmConfigured || !state.databaseAvailable) {
    dom.serviceStatus.classList.add("is-degraded");
    title.textContent = "服务可用 · 配置不完整";
    details.textContent = state.databaseAvailable ? "LLM 未配置" : "数据库不可用";
  } else {
    dom.serviceStatus.classList.add("is-online");
    title.textContent = "服务在线";
    details.textContent = "LLM 与数据库可用";
  }
}

function renderSessionList() {
  dom.sessionList.replaceChildren();
  if (state.isLoadingSessions) {
    const loading = document.createElement("div");
    loading.className = "sidebar-loading";
    loading.textContent = "正在加载 Sessions…";
    dom.sessionList.append(loading);
    for (let index = 0; index < 3; index += 1) {
      const skeleton = document.createElement("div");
      skeleton.className = "sidebar-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      dom.sessionList.append(skeleton);
    }
    return;
  }

  if (state.sessions.length === 0) {
    const empty = document.createElement("p");
    empty.className = "sidebar-empty";
    empty.textContent = "该用户还没有 Session。点击“新建会话”开始。";
    dom.sessionList.append(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  state.sessions.forEach((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item";
    button.dataset.sessionId = session.session_id;
    button.classList.toggle("is-active", session.session_id === state.activeSessionId);
    button.setAttribute("aria-pressed", String(session.session_id === state.activeSessionId));

    const title = document.createElement("strong");
    title.textContent = session.title;
    const meta = document.createElement("small");
    meta.textContent = `${session.session_id} · ${formatDateTime(session.updated_at)}`;
    button.append(title, meta);
    fragment.append(button);
  });
  dom.sessionList.append(fragment);
}

function createStatChip(label) {
  const chip = document.createElement("span");
  chip.className = "stat-chip";
  chip.textContent = label;
  return chip;
}

function messageStats(message) {
  if (message.role !== "assistant" || !message.metadata) {
    return null;
  }
  const agent = message.metadata.agent;
  const context = message.metadata.context;
  if (!agent && !context) {
    return null;
  }
  const stats = document.createElement("div");
  stats.className = "message-stats";
  if (agent && Number.isFinite(agent.total_llm_calls)) {
    stats.append(createStatChip(`LLM ${agent.total_llm_calls} 次`));
  }
  if (agent && Number.isFinite(agent.total_tool_calls)) {
    stats.append(createStatChip(`工具 ${agent.total_tool_calls} 次`));
  }
  if (context && context.compressed === true) {
    stats.append(createStatChip("Context 已压缩"));
  }
  return stats.childElementCount > 0 ? stats : null;
}

function renderMessages() {
  dom.messageList.replaceChildren();

  if (state.isLoadingMessages) {
    for (let index = 0; index < 3; index += 1) {
      const row = document.createElement("div");
      row.className = index % 2 === 0 ? "message-row is-assistant" : "message-row is-user";
      const card = document.createElement("div");
      card.className = "message-card sidebar-skeleton";
      card.style.width = index % 2 === 0 ? "62%" : "44%";
      card.style.height = index === 0 ? "94px" : "70px";
      card.setAttribute("aria-hidden", "true");
      row.append(card);
      dom.messageList.append(row);
    }
  } else {
    const fragment = document.createDocumentFragment();
    state.messages.forEach((message) => {
      const row = document.createElement("article");
      const roleClass = message.role === "user" ? "is-user" : "is-assistant";
      row.className = `message-row ${roleClass}`;
      row.classList.toggle("is-pending", Boolean(message.pending));
      row.classList.toggle("is-failed", Boolean(message.failed));

      const card = document.createElement("div");
      card.className = "message-card";
      const byline = document.createElement("div");
      byline.className = "message-byline";
      const role = document.createElement("span");
      role.className = "role-badge";
      role.textContent = message.role === "user" ? "YOU" : "AGENT";
      const time = document.createElement("time");
      time.textContent = message.pending
        ? (message.failed ? "发送失败" : "正在发送")
        : formatDateTime(message.created_at);
      byline.append(role, time);

      const bubble = document.createElement("div");
      bubble.className = "message-bubble";
      bubble.textContent = message.content;
      card.append(byline, bubble);
      const stats = messageStats(message);
      if (stats) {
        card.append(stats);
      }
      row.append(card);
      fragment.append(row);
    });
    dom.messageList.append(fragment);
  }

  const noMessages = !state.isLoadingMessages && state.messages.length === 0;
  dom.emptyChatState.hidden = !noMessages;
  if (noMessages && state.activeSessionId) {
    dom.emptyChatTitle.textContent = "这个 Session 还没有消息";
    dom.emptyChatCopy.textContent = "输入任务后，Agent 会自主决定是否调用已注册工具。";
  } else if (noMessages) {
    dom.emptyChatTitle.textContent = "选择一个 Session 开始对话";
    dom.emptyChatCopy.textContent = "Agent 会根据请求自主决定是否调用 calculator、search 或 todo 工具。";
  }

  dom.chatLoading.hidden = !(state.isSending || state.isLoadingMessages);
  dom.chatLoadingCopy.textContent = state.isSending
    ? "Agent 正在思考和调用工具"
    : "正在加载历史消息";
}

function renderCurrentSession() {
  const session = activeSession();
  dom.currentSessionTitle.textContent = session ? session.title : "请选择一个 Session";
  dom.currentSessionMeta.textContent = session
    ? `${session.session_id} · 更新于 ${formatDateTime(session.updated_at)}`
    : "新建或选择会话后即可开始。";
}

function renderControls() {
  const hasSession = Boolean(activeSession());
  const chatBlocked = !hasSession || !state.serviceAvailable || state.isSending;
  dom.messageInput.disabled = chatBlocked;
  dom.sendButton.disabled = chatBlocked || dom.messageInput.value.trim().length === 0;
  dom.renameSessionButton.disabled = !hasSession || state.isSending;
  dom.deleteSessionButton.disabled = !hasSession || state.isSending;
  dom.clearMessagesButton.disabled = !hasSession || state.isSending || state.messages.length === 0;
  dom.applyUserButton.disabled = state.isLoadingSessions || state.isSending;
  dom.newSessionButton.disabled = state.isLoadingSessions || !state.databaseAvailable;
  dom.refreshSessionsButton.disabled = state.isLoadingSessions;
  dom.characterCount.textContent = `${dom.messageInput.value.length} / ${MAX_MESSAGE_LENGTH}`;
  dom.messageInput.placeholder = hasSession
    ? "描述任务、追问上下文或让 Agent 调用工具…"
    : "选择 Session 后输入消息…";
}

function renderAll() {
  renderSidebarState();
  renderServiceStatus();
  renderSessionList();
  renderCurrentSession();
  renderMessages();
  renderControls();
}

function scrollToLatest() {
  window.requestAnimationFrame(() => {
    const conversation = dom.messageList.parentElement;
    conversation.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });
  });
}

function showToast(message, type = "info", options = {}) {
  const duplicate = Array.from(dom.toastContainer.querySelectorAll(".toast p"))
    .some((element) => element.textContent === message);
  if (duplicate) {
    return;
  }

  const toast = document.createElement("div");
  toast.className = `toast is-${type}`;
  toast.setAttribute("role", type === "error" ? "alert" : "status");
  const symbol = document.createElement("span");
  symbol.className = "toast-symbol";
  symbol.setAttribute("aria-hidden", "true");
  symbol.textContent = type === "success" ? "✓" : (type === "error" ? "!" : "i");
  const copy = document.createElement("p");
  copy.textContent = message;
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "toast-close";
  closeButton.setAttribute("aria-label", "关闭提示");
  closeButton.textContent = "×";
  closeButton.addEventListener("click", () => toast.remove());
  toast.append(symbol, copy, closeButton);
  dom.toastContainer.append(toast);

  const duration = options.persistent ? 0 : (type === "error" ? 7000 : 4200);
  if (duration > 0) {
    window.setTimeout(() => toast.remove(), duration);
  }
}

function markServiceOffline() {
  patchState({ serviceAvailable: false, llmConfigured: false, databaseAvailable: false });
  renderServiceStatus();
  renderControls();
}

function friendlyError(error, fallbackMessage) {
  if (!(error instanceof ApiError)) {
    return fallbackMessage;
  }
  if (error.status === 503 || error.code === "llm_unavailable") {
    return "LLM 尚未配置，请检查服务端 .env。";
  }
  if (error.code === "network_error") {
    markServiceOffline();
    return error.message;
  }
  if (error.status === 409) {
    return "这个 Session ID 已存在，请换一个后重试。";
  }
  return error.message || fallbackMessage;
}

async function checkHealth({ announceRecovery = false } = {}) {
  const wasAvailable = state.serviceAvailable;
  try {
    const health = await healthCheck();
    const available = health.status === "ok" && health.database === "available";
    patchState({
      serviceAvailable: available,
      llmConfigured: health.llm_configured === true,
      databaseAvailable: health.database === "available",
    });
    if (announceRecovery && !wasAvailable && available) {
      showToast("后端服务已恢复。", "success");
    }
  } catch (error) {
    markServiceOffline();
  }
  renderServiceStatus();
  renderControls();
}

async function loadActiveMessages() {
  const requestVersion = ++messageRequestVersion;
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  patchState({ messages: [], isLoadingMessages: Boolean(requestSessionId), lastRunId: null });
  renderCurrentSession();
  renderMessages();
  renderControls();
  if (!requestSessionId) {
    return;
  }

  try {
    const messages = await listMessages(requestUserId, requestSessionId, 200);
    if (
      requestVersion !== messageRequestVersion
      || state.userId !== requestUserId
      || state.activeSessionId !== requestSessionId
    ) {
      return;
    }
    patchState({ messages, isLoadingMessages: false });
    renderMessages();
    renderControls();
    scrollToLatest();
  } catch (error) {
    if (requestVersion !== messageRequestVersion) {
      return;
    }
    patchState({ isLoadingMessages: false, messages: [] });
    renderMessages();
    renderControls();
    showToast(friendlyError(error, "消息历史加载失败。"), "error");
    if (error instanceof ApiError && error.status === 404) {
      await refreshSessions({ loadMessagesAfter: true });
    }
  }
}

async function refreshSessions({
  preferredId = state.activeSessionId || preferredSessionId,
  loadMessagesAfter = false,
  announce = false,
} = {}) {
  const requestVersion = ++sessionRequestVersion;
  const requestUserId = state.userId;
  patchState({ isLoadingSessions: true });
  renderSessionList();
  renderControls();
  try {
    const sessions = await listSessions(requestUserId);
    if (requestVersion !== sessionRequestVersion || state.userId !== requestUserId) {
      return;
    }
    patchState({ sessions, isLoadingSessions: false });
    restoreActiveSession(preferredId);
    preferredSessionId = null;
    renderSessionList();
    renderCurrentSession();
    renderControls();
    if (loadMessagesAfter) {
      await loadActiveMessages();
    } else if (announce) {
      showToast("Session 列表已刷新。", "success");
    }
  } catch (error) {
    if (requestVersion !== sessionRequestVersion) {
      return;
    }
    patchState({ sessions: [], activeSessionId: null, messages: [], isLoadingSessions: false });
    renderSessionList();
    renderCurrentSession();
    renderMessages();
    renderControls();
    showToast(friendlyError(error, "Session 列表加载失败。"), "error");
  }
}

async function selectSession(sessionId) {
  if (sessionId === state.activeSessionId || state.isSending) {
    return;
  }
  setActiveSession(sessionId);
  messageRequestVersion += 1;
  renderSessionList();
  renderCurrentSession();
  renderMessages();
  renderControls();
  if (window.matchMedia("(max-width: 760px)").matches) {
    setSidebarCollapsed(true);
    renderSidebarState();
  }
  await loadActiveMessages();
}

async function applyUser(event) {
  event.preventDefault();
  const userId = dom.userInput.value.trim();
  if (!userId) {
    showToast("用户 ID 不能为空。", "error");
    dom.userInput.focus();
    return;
  }
  if (userId === state.userId) {
    await refreshSessions({ loadMessagesAfter: true, announce: true });
    return;
  }
  sessionRequestVersion += 1;
  messageRequestVersion += 1;
  changeUser(userId);
  renderAll();
  showToast(`已切换到用户 ${userId}。`, "info");
  await refreshSessions({ preferredId: null, loadMessagesAfter: true });
}

async function submitNewSession(event) {
  event.preventDefault();
  const title = dom.newSessionTitle.value.trim();
  const sessionId = dom.newSessionId.value.trim();
  if (!title) {
    showToast("会话标题不能为空。", "error");
    dom.newSessionTitle.focus();
    return;
  }
  const requestUserId = state.userId;
  setElementBusy(dom.createSessionSubmit, true, "正在创建…", "创建 Session");
  try {
    const payload = { user_id: requestUserId, title };
    if (sessionId) {
      payload.session_id = sessionId;
    }
    const session = await createSession(payload);
    if (state.userId !== requestUserId) {
      return;
    }
    closeDialog(dom.sessionDialog);
    dom.sessionForm.reset();
    dom.newSessionTitle.value = "新会话";
    showToast("Session 创建成功。", "success");
    await refreshSessions({ preferredId: session.session_id, loadMessagesAfter: true });
  } catch (error) {
    showToast(friendlyError(error, "Session 创建失败。"), "error", { persistent: true });
  } finally {
    setElementBusy(dom.createSessionSubmit, false, "正在创建…", "创建 Session");
  }
}

async function submitRename(event) {
  event.preventDefault();
  const title = dom.renameSessionTitle.value.trim();
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  if (!title || !requestSessionId) {
    showToast("标题不能为空。", "error");
    return;
  }
  setElementBusy(dom.renameSessionSubmit, true, "正在保存…", "保存标题");
  try {
    await renameSession(requestUserId, requestSessionId, title);
    if (state.userId !== requestUserId || state.activeSessionId !== requestSessionId) {
      return;
    }
    closeDialog(dom.renameDialog);
    showToast("Session 标题已更新。", "success");
    await refreshSessions({ preferredId: requestSessionId });
  } catch (error) {
    showToast(friendlyError(error, "重命名失败。"), "error");
    if (error instanceof ApiError && error.status === 404) {
      await refreshSessions({ loadMessagesAfter: true });
    }
  } finally {
    setElementBusy(dom.renameSessionSubmit, false, "正在保存…", "保存标题");
  }
}

async function submitDelete(event) {
  event.preventDefault();
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  if (!requestSessionId) {
    closeDialog(dom.deleteDialog);
    return;
  }
  setElementBusy(dom.confirmDeleteButton, true, "正在删除…", "确认删除");
  try {
    await deleteSession(requestUserId, requestSessionId);
    if (state.userId !== requestUserId) {
      return;
    }
    closeDialog(dom.deleteDialog);
    setActiveSession(null);
    showToast("Session 及其关联数据已删除。", "success");
    await refreshSessions({ preferredId: null, loadMessagesAfter: true });
  } catch (error) {
    showToast(friendlyError(error, "删除 Session 失败。"), "error", { persistent: true });
    if (error instanceof ApiError && error.status === 404) {
      closeDialog(dom.deleteDialog);
      await refreshSessions({ loadMessagesAfter: true });
    }
  } finally {
    setElementBusy(dom.confirmDeleteButton, false, "正在删除…", "确认删除");
  }
}

async function submitClear(event) {
  event.preventDefault();
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  if (!requestSessionId) {
    closeDialog(dom.clearDialog);
    return;
  }
  setElementBusy(dom.confirmClearButton, true, "正在清空…", "确认清空");
  try {
    const result = await clearMessages(requestUserId, requestSessionId);
    if (state.userId !== requestUserId || state.activeSessionId !== requestSessionId) {
      return;
    }
    closeDialog(dom.clearDialog);
    patchState({ messages: [], lastRunId: null });
    renderMessages();
    renderControls();
    showToast(`已清空 ${result.deleted_count} 条消息。`, "success");
  } catch (error) {
    showToast(friendlyError(error, "清空消息失败。"), "error");
  } finally {
    setElementBusy(dom.confirmClearButton, false, "正在清空…", "确认清空");
  }
}

async function submitMessage(event) {
  event.preventDefault();
  const content = dom.messageInput.value.trim();
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  if (!requestSessionId) {
    showToast("请先选择一个 Session。", "error");
    return;
  }
  if (!content) {
    showToast("消息不能为空。", "error");
    dom.messageInput.focus();
    return;
  }
  if (content.length > MAX_MESSAGE_LENGTH) {
    showToast(`消息不能超过 ${MAX_MESSAGE_LENGTH} 个字符。`, "error");
    return;
  }
  if (state.isSending) {
    return;
  }

  const pendingId = `pending-${Date.now()}`;
  const pendingMessage = {
    id: pendingId,
    role: "user",
    content,
    created_at: new Date().toISOString(),
    metadata: null,
    pending: true,
  };
  patchState({ messages: [...state.messages, pendingMessage], isSending: true });
  renderMessages();
  renderControls();
  scrollToLatest();

  try {
    const result = await sendChat({
      user_id: requestUserId,
      session_id: requestSessionId,
      message: content,
    });
    const ownsResponse = state.userId === requestUserId && state.activeSessionId === requestSessionId;
    if (ownsResponse) {
      const messages = state.messages.filter((message) => message.id !== pendingId);
      patchState({
        messages: [...messages, result.user_message, result.assistant_message],
        lastRunId: result.run_id,
      });
      dom.messageInput.value = "";
      renderMessages();
      renderControls();
      scrollToLatest();
    }
    await refreshSessions({ preferredId: state.activeSessionId });
  } catch (error) {
    const ownsResponse = state.userId === requestUserId && state.activeSessionId === requestSessionId;
    if (ownsResponse) {
      patchState({
        messages: state.messages.map((message) => (
          message.id === pendingId ? { ...message, pending: true, failed: true } : message
        )),
      });
      renderMessages();
      scrollToLatest();
    }
    showToast(friendlyError(error, "消息发送失败，请稍后重试。"), "error", { persistent: true });
    if (error instanceof ApiError && error.status === 404) {
      await refreshSessions({ loadMessagesAfter: true });
    }
  } finally {
    patchState({ isSending: false });
    renderMessages();
    renderControls();
    if (state.userId === requestUserId && state.activeSessionId === requestSessionId) {
      dom.messageInput.focus();
    }
  }
}

function bindEvents() {
  dom.userForm.addEventListener("submit", applyUser);
  dom.sessionList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-session-id]");
    if (button) {
      void selectSession(button.dataset.sessionId);
    }
  });
  dom.newSessionButton.addEventListener("click", () => {
    dom.sessionForm.reset();
    dom.newSessionTitle.value = "新会话";
    openDialog(dom.sessionDialog);
    dom.newSessionTitle.select();
  });
  dom.refreshSessionsButton.addEventListener("click", () => {
    void refreshSessions({ loadMessagesAfter: Boolean(state.activeSessionId), announce: true });
  });
  dom.toggleSidebarButton.addEventListener("click", () => {
    setSidebarCollapsed(!state.sidebarCollapsed);
    renderSidebarState();
  });
  dom.renameSessionButton.addEventListener("click", () => {
    const session = activeSession();
    if (!session) {
      return;
    }
    dom.renameSessionTitle.value = session.title;
    openDialog(dom.renameDialog);
    dom.renameSessionTitle.select();
  });
  dom.deleteSessionButton.addEventListener("click", () => {
    const session = activeSession();
    if (!session) {
      return;
    }
    dom.deleteSessionDescription.textContent = `“${session.title}”的消息、Todo 和 Trace 将被级联删除，且无法撤销。`;
    openDialog(dom.deleteDialog);
  });
  dom.clearMessagesButton.addEventListener("click", () => openDialog(dom.clearDialog));
  dom.sessionForm.addEventListener("submit", submitNewSession);
  dom.renameForm.addEventListener("submit", submitRename);
  dom.deleteForm.addEventListener("submit", submitDelete);
  dom.clearForm.addEventListener("submit", submitClear);
  dom.messageForm.addEventListener("submit", submitMessage);
  dom.messageInput.addEventListener("input", renderControls);
  dom.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      dom.messageForm.requestSubmit();
    }
  });
  document.querySelectorAll(".dialog-close-button, .dialog-cancel-button").forEach((button) => {
    button.addEventListener("click", () => closeDialog(button.closest("dialog")));
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      void checkHealth({ announceRecovery: true });
    }
  });
}

async function initialize() {
  const preferences = loadPreferences();
  preferredSessionId = preferences.activeSessionId;
  dom.userInput.value = state.userId;
  if (window.matchMedia("(max-width: 760px)").matches && !preferences.activeSessionId) {
    setSidebarCollapsed(false);
  }
  bindEvents();
  renderAll();
  await checkHealth();
  if (state.databaseAvailable) {
    await refreshSessions({ preferredId: preferredSessionId, loadMessagesAfter: true });
  } else {
    showToast("后端暂时不可用；恢复后可刷新 Session。", "error");
  }
  window.setInterval(() => {
    if (!document.hidden) {
      void checkHealth({ announceRecovery: true });
    }
  }, HEALTH_INTERVAL_MS);
}

void initialize();
