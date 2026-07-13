"use strict";

import {
  ApiError,
  deleteTrace,
  getTrace,
  listTodos,
  listTraceRuns,
} from "/static/api.js";
import { renderSafeMessage } from "/static/render.js";
import {
  clearInspectorState,
  patchState,
  setActiveInspectorTab,
  setInspectorOpen,
  state,
} from "/static/state.js";
import { formatDateTime } from "/static/utils.js";

const dom = {
  body: document.body,
  panel: document.querySelector("#inspector-panel"),
  toggleButton: document.querySelector("#toggle-inspector-button"),
  closeButton: document.querySelector("#close-inspector-button"),
  tabs: Array.from(document.querySelectorAll("#inspector-tabs [role='tab']")),
  panels: {
    overview: document.querySelector("#overview-panel"),
    todo: document.querySelector("#todo-panel"),
    trace: document.querySelector("#trace-panel"),
  },
  overviewEmpty: document.querySelector("#overview-empty-state"),
  overviewMetrics: document.querySelector("#overview-metrics"),
  currentRunId: document.querySelector("#current-run-id"),
  copyRunIdButton: document.querySelector("#copy-run-id-button"),
  metricLlmCalls: document.querySelector("#metric-llm-calls"),
  metricToolCalls: document.querySelector("#metric-tool-calls"),
  metricContextCompressed: document.querySelector("#metric-context-compressed"),
  metricLoadedHistory: document.querySelector("#metric-loaded-history"),
  metricRunStatus: document.querySelector("#metric-run-status"),
  metricRunDuration: document.querySelector("#metric-run-duration"),
  todoList: document.querySelector("#todo-list"),
  todoEmpty: document.querySelector("#todo-empty-state"),
  todoLoading: document.querySelector("#todo-loading"),
  refreshTodosButton: document.querySelector("#refresh-todos-button"),
  traceRunList: document.querySelector("#trace-run-list"),
  traceEmpty: document.querySelector("#trace-empty-state"),
  traceLoading: document.querySelector("#trace-loading"),
  refreshTracesButton: document.querySelector("#refresh-traces-button"),
  traceDetail: document.querySelector("#trace-detail"),
  traceDetailEmpty: document.querySelector("#trace-detail-empty"),
  traceDetailLoading: document.querySelector("#trace-detail-loading"),
  traceRunSummary: document.querySelector("#trace-run-summary"),
  traceEventList: document.querySelector("#trace-event-list"),
  deleteTraceButton: document.querySelector("#delete-trace-button"),
  deleteTraceDialog: document.querySelector("#delete-trace-dialog"),
  deleteTraceForm: document.querySelector("#delete-trace-form"),
  confirmDeleteTraceButton: document.querySelector("#confirm-delete-trace-button"),
};

const TAB_NAMES = ["overview", "todo", "trace"];
let todoRequestVersion = 0;
let traceListRequestVersion = 0;
let traceDetailRequestVersion = 0;
let notify = () => {};
let describeError = (error, fallback) => (error && error.message) || fallback;

function shortRunId(runId) {
  if (!runId || typeof runId !== "string") {
    return "—";
  }
  return runId.length > 12 ? `${runId.slice(0, 8)}…${runId.slice(-4)}` : runId;
}

function truncate(value, limit = 80) {
  const text = typeof value === "string" ? value : "";
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function displayValue(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function formatDuration(startedAt, finishedAt) {
  const started = new Date(startedAt).getTime();
  const finished = new Date(finishedAt).getTime();
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) {
    return "—";
  }
  const milliseconds = finished - started;
  if (milliseconds < 1000) {
    return `${milliseconds} ms`;
  }
  return `${(milliseconds / 1000).toFixed(milliseconds < 10_000 ? 2 : 1)} s`;
}

function statusLabel(status) {
  const labels = { completed: "已完成", failed: "失败", running: "运行中" };
  return labels[status] || displayValue(status);
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

function latestAssistantMetadata() {
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (message.role === "assistant" && message.metadata) {
      return message.metadata;
    }
  }
  return {};
}

function contextFromTrace(detail) {
  if (!detail || !Array.isArray(detail.events)) {
    return null;
  }
  const event = detail.events.find((item) => item.event_type === "context_built");
  return event ? event.payload : null;
}

function renderInspectorShell() {
  dom.body.classList.toggle("inspector-collapsed", !state.inspectorOpen);
  dom.toggleButton.setAttribute("aria-expanded", String(state.inspectorOpen));
  dom.toggleButton.setAttribute("aria-label", state.inspectorOpen ? "收起 Inspector" : "展开 Inspector");
  dom.panel.setAttribute("aria-hidden", String(!state.inspectorOpen));

  dom.tabs.forEach((button) => {
    const tab = button.id.replace("-tab-button", "");
    const active = tab === state.activeInspectorTab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    dom.panels[tab].hidden = !active;
  });
}

function renderOverview() {
  const chat = state.lastChatResult;
  const detail = state.traceDetail;
  const run = detail ? detail.run : null;
  const metadata = latestAssistantMetadata();
  const agent = (chat && chat.agent) || metadata.agent || run || {};
  const context = (chat && chat.context) || metadata.context || contextFromTrace(detail) || {};
  const runId = (chat && chat.run_id) || state.lastRunId || (run && run.run_id) || state.selectedRunId;
  const hasData = Boolean(runId || run || metadata.agent || metadata.context);

  dom.overviewEmpty.hidden = hasData;
  dom.overviewMetrics.hidden = !hasData;
  dom.currentRunId.textContent = shortRunId(runId);
  dom.currentRunId.title = runId || "";
  dom.copyRunIdButton.disabled = !runId;
  dom.metricLlmCalls.textContent = displayValue(agent.total_llm_calls);
  dom.metricToolCalls.textContent = displayValue(agent.total_tool_calls);
  dom.metricContextCompressed.textContent = context.compressed === true
    ? "是"
    : (context.compressed === false ? "否" : "—");
  dom.metricLoadedHistory.textContent = displayValue(chat && chat.loaded_history_count);
  dom.metricRunStatus.textContent = statusLabel((run && run.status) || (chat && "completed"));
  dom.metricRunDuration.textContent = run ? formatDuration(run.started_at, run.finished_at) : "—";
}

function renderTodos() {
  dom.todoLoading.hidden = !state.isLoadingTodos;
  dom.todoLoading.setAttribute("aria-busy", String(state.isLoadingTodos));
  dom.refreshTodosButton.disabled = state.isLoadingTodos || !state.activeSessionId;
  dom.todoList.replaceChildren();
  const showEmpty = !state.isLoadingTodos && state.todos.length === 0;
  dom.todoEmpty.hidden = !showEmpty;

  const fragment = document.createDocumentFragment();
  state.todos.forEach((todo) => {
    const item = document.createElement("article");
    item.className = "todo-item";
    item.classList.toggle("is-completed", todo.completed === true);
    const marker = document.createElement("span");
    marker.className = "todo-marker";
    marker.setAttribute("aria-hidden", "true");
    marker.textContent = todo.completed ? "✓" : "○";
    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = todo.content;
    const meta = document.createElement("small");
    const completedText = todo.completed_at ? ` · 完成于 ${formatDateTime(todo.completed_at)}` : "";
    meta.textContent = `#${todo.id} · 创建于 ${formatDateTime(todo.created_at)}${completedText}`;
    content.append(title, meta);
    const badge = document.createElement("span");
    badge.className = todo.completed ? "status-badge is-completed" : "status-badge is-pending";
    badge.textContent = todo.completed ? "已完成" : "未完成";
    item.append(marker, content, badge);
    fragment.append(item);
  });
  dom.todoList.append(fragment);
}

function renderTraceRuns() {
  dom.traceLoading.hidden = !state.isLoadingTraceRuns;
  dom.traceLoading.setAttribute("aria-busy", String(state.isLoadingTraceRuns));
  dom.refreshTracesButton.disabled = state.isLoadingTraceRuns || !state.activeSessionId;
  dom.traceRunList.replaceChildren();
  dom.traceEmpty.hidden = state.isLoadingTraceRuns || state.traceRuns.length > 0;

  const fragment = document.createDocumentFragment();
  state.traceRuns.forEach((run) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "trace-run-item";
    button.dataset.runId = run.run_id;
    button.classList.toggle("is-active", run.run_id === state.selectedRunId);
    button.setAttribute("aria-pressed", String(run.run_id === state.selectedRunId));

    const heading = document.createElement("span");
    heading.className = "trace-run-heading";
    const id = document.createElement("strong");
    id.textContent = shortRunId(run.run_id);
    const badge = document.createElement("span");
    badge.className = `status-badge is-${run.status}`;
    badge.textContent = statusLabel(run.status);
    heading.append(id, badge);

    const preview = document.createElement("span");
    preview.className = "trace-run-preview";
    preview.textContent = truncate(run.user_input, 80) || "无输入预览";
    const meta = document.createElement("small");
    meta.textContent = `${formatDateTime(run.started_at)} · LLM ${run.total_llm_calls} · 工具 ${run.total_tool_calls}`;
    button.append(heading, preview, meta);
    fragment.append(button);
  });
  dom.traceRunList.append(fragment);
}

function appendSummaryValue(container, label, value, className = "") {
  const item = document.createElement("div");
  item.className = className;
  const term = document.createElement("span");
  term.textContent = label;
  const data = document.createElement("strong");
  data.textContent = displayValue(value);
  item.append(term, data);
  container.append(item);
}

function jsonDetails(label, value) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = label;
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(value, null, 2);
  details.append(summary, pre);
  return details;
}

function appendPayloadValue(container, label, value) {
  if (value === undefined) {
    return;
  }
  const row = document.createElement("p");
  const key = document.createElement("strong");
  key.textContent = `${label}: `;
  const copy = document.createTextNode(displayValue(value));
  row.append(key, copy);
  container.append(row);
}

function renderTraceEvent(event) {
  const payload = event.payload || {};
  const article = document.createElement("article");
  article.className = `trace-event trace-event-${event.event_type}`;
  if (payload.tool_call_id) {
    article.dataset.toolCallId = payload.tool_call_id;
  }

  const marker = document.createElement("span");
  marker.className = "trace-event-marker";
  marker.textContent = String(event.sequence);
  const content = document.createElement("div");
  content.className = "trace-event-content";
  const heading = document.createElement("div");
  heading.className = "trace-event-heading";
  const type = document.createElement("strong");
  type.textContent = event.event_type;
  const meta = document.createElement("small");
  const step = event.step_number == null ? "" : ` · Step ${event.step_number}`;
  meta.textContent = `${formatDateTime(event.created_at)}${step}`;
  heading.append(type, meta);
  content.append(heading);

  if (event.event_type === "context_built") {
    [
      ["compressed", payload.compressed],
      ["original_message_count", payload.original_message_count],
      ["output_message_count", payload.output_message_count],
      ["summarized_message_count", payload.summarized_message_count],
      ["retained_recent_count", payload.retained_recent_count],
      ["original_char_count", payload.original_char_count],
      ["output_char_count", payload.output_char_count],
    ].forEach(([label, value]) => appendPayloadValue(content, label, value));
  } else if (event.event_type === "llm_decision") {
    appendPayloadValue(content, "decision_type", payload.decision_type);
    appendPayloadValue(content, "reasoning_summary", payload.reasoning_summary);
    appendPayloadValue(content, "model", payload.model);
  } else if (event.event_type === "tool_call") {
    appendPayloadValue(content, "tool_call_id", payload.tool_call_id);
    appendPayloadValue(content, "tool_name", payload.tool_name);
    content.append(jsonDetails("查看 arguments", payload.arguments));
  } else if (event.event_type === "tool_result") {
    appendPayloadValue(content, "tool_call_id", payload.tool_call_id);
    appendPayloadValue(content, "tool_name", payload.tool_name);
    appendPayloadValue(content, "success", payload.success);
    if (payload.output !== undefined) {
      content.append(jsonDetails("查看 output", payload.output));
    }
    appendPayloadValue(content, "error", payload.error);
  } else if (event.event_type === "run_completed") {
    appendPayloadValue(content, "stopped_reason", payload.stopped_reason);
    appendPayloadValue(content, "total_llm_calls", payload.total_llm_calls);
    appendPayloadValue(content, "total_tool_calls", payload.total_tool_calls);
  } else if (event.event_type === "run_failed") {
    appendPayloadValue(content, "error_type", payload.error_type);
    appendPayloadValue(content, "error_message", payload.error_message);
  } else if (event.event_type !== "run_started") {
    content.append(jsonDetails("查看事件 payload", payload));
  }

  article.append(marker, content);
  return article;
}

function renderTraceDetail() {
  dom.traceDetailLoading.hidden = !state.isLoadingTraceDetail;
  dom.traceDetailLoading.setAttribute("aria-busy", String(state.isLoadingTraceDetail));
  dom.deleteTraceButton.disabled = !state.selectedRunId || state.isDeletingTrace;
  dom.deleteTraceButton.textContent = state.isDeletingTrace ? "正在删除…" : "删除 Trace";
  dom.traceRunSummary.replaceChildren();
  dom.traceEventList.replaceChildren();

  const detail = state.traceDetail;
  const showEmpty = !state.isLoadingTraceDetail && !detail;
  dom.traceDetailEmpty.hidden = !showEmpty;
  dom.traceRunSummary.hidden = !detail;
  if (!detail) {
    return;
  }

  const run = detail.run;
  appendSummaryValue(dom.traceRunSummary, "Run ID", shortRunId(run.run_id), "summary-wide");
  appendSummaryValue(dom.traceRunSummary, "状态", statusLabel(run.status));
  appendSummaryValue(dom.traceRunSummary, "耗时", formatDuration(run.started_at, run.finished_at));
  appendSummaryValue(dom.traceRunSummary, "开始", formatDateTime(run.started_at));
  appendSummaryValue(dom.traceRunSummary, "结束", formatDateTime(run.finished_at));
  appendSummaryValue(dom.traceRunSummary, "LLM", run.total_llm_calls);
  appendSummaryValue(dom.traceRunSummary, "工具", run.total_tool_calls);
  if (run.final_answer) {
    const answer = document.createElement("div");
    answer.className = "trace-final-answer summary-wide";
    const label = document.createElement("span");
    label.textContent = "最终回答";
    const copy = document.createElement("div");
    renderSafeMessage(copy, run.final_answer);
    answer.append(label, copy);
    dom.traceRunSummary.append(answer);
  }
  if (run.error_type || run.error_message) {
    appendSummaryValue(dom.traceRunSummary, "错误类型", run.error_type, "summary-wide");
    appendSummaryValue(dom.traceRunSummary, "错误信息", run.error_message, "summary-wide");
  }

  const fragment = document.createDocumentFragment();
  [...detail.events]
    .sort((left, right) => left.sequence - right.sequence)
    .forEach((event) => fragment.append(renderTraceEvent(event)));
  dom.traceEventList.append(fragment);
}

export function renderInspector() {
  renderInspectorShell();
  renderOverview();
  renderTodos();
  renderTraceRuns();
  renderTraceDetail();
}

export function resetInspector() {
  todoRequestVersion += 1;
  traceListRequestVersion += 1;
  traceDetailRequestVersion += 1;
  clearInspectorState();
  renderInspector();
}

export async function refreshTodos({ quiet = false } = {}) {
  const requestVersion = ++todoRequestVersion;
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  patchState({ todos: [], isLoadingTodos: Boolean(requestSessionId) });
  renderTodos();
  if (!requestSessionId) {
    return;
  }
  try {
    const todos = await listTodos(requestUserId, requestSessionId);
    const ownsResponse = requestVersion === todoRequestVersion
      && state.userId === requestUserId
      && state.activeSessionId === requestSessionId;
    if (!ownsResponse) {
      return;
    }
    patchState({ todos, isLoadingTodos: false });
    renderTodos();
  } catch (error) {
    if (requestVersion !== todoRequestVersion) {
      return;
    }
    patchState({ todos: [], isLoadingTodos: false });
    renderTodos();
    if (!quiet) {
      notify(describeError(error, "Todo 加载失败。"), "error");
    }
  }
}

export async function loadTraceDetail(runId) {
  const requestVersion = ++traceDetailRequestVersion;
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  patchState({ selectedRunId: runId, traceDetail: null, isLoadingTraceDetail: Boolean(runId) });
  renderTraceRuns();
  renderTraceDetail();
  renderOverview();
  if (!runId) {
    return;
  }
  try {
    const detail = await getTrace(requestUserId, runId);
    const ownsResponse = requestVersion === traceDetailRequestVersion
      && state.userId === requestUserId
      && state.activeSessionId === requestSessionId
      && state.selectedRunId === runId
      && detail.run.user_id === requestUserId
      && detail.run.session_id === requestSessionId
      && detail.run.run_id === runId;
    if (!ownsResponse) {
      return;
    }
    patchState({ traceDetail: detail, isLoadingTraceDetail: false });
    renderTraceDetail();
    renderOverview();
  } catch (error) {
    if (requestVersion !== traceDetailRequestVersion || state.selectedRunId !== runId) {
      return;
    }
    patchState({
      traceDetail: null,
      isLoadingTraceDetail: false,
      selectedRunId: error instanceof ApiError && error.status === 404 ? null : runId,
    });
    renderTraceRuns();
    renderTraceDetail();
    renderOverview();
    notify(describeError(error, "Trace 详情加载失败。"), "error");
  }
}

export async function refreshTraceRuns({ preferredRunId = state.lastRunId, quiet = false } = {}) {
  const requestVersion = ++traceListRequestVersion;
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  patchState({ traceRuns: [], isLoadingTraceRuns: Boolean(requestSessionId) });
  renderTraceRuns();
  if (!requestSessionId) {
    return;
  }
  try {
    const runs = await listTraceRuns(requestUserId, { sessionId: requestSessionId, limit: 50 });
    const ownsResponse = requestVersion === traceListRequestVersion
      && state.userId === requestUserId
      && state.activeSessionId === requestSessionId
      && runs.every((run) => run.user_id === requestUserId && run.session_id === requestSessionId);
    if (!ownsResponse) {
      return;
    }
    const selectedRunId = runs.some((run) => run.run_id === preferredRunId)
      ? preferredRunId
      : (runs.some((run) => run.run_id === state.selectedRunId)
        ? state.selectedRunId
        : (runs[0] ? runs[0].run_id : null));
    patchState({ traceRuns: runs, selectedRunId, isLoadingTraceRuns: false });
    renderTraceRuns();
    if (selectedRunId) {
      await loadTraceDetail(selectedRunId);
    } else {
      patchState({ traceDetail: null, isLoadingTraceDetail: false });
      renderTraceDetail();
      renderOverview();
    }
  } catch (error) {
    if (requestVersion !== traceListRequestVersion) {
      return;
    }
    patchState({ traceRuns: [], selectedRunId: null, traceDetail: null, isLoadingTraceRuns: false });
    renderTraceRuns();
    renderTraceDetail();
    renderOverview();
    if (!quiet) {
      notify(describeError(error, "Trace 列表加载失败。"), "error");
    }
  }
}

export async function refreshInspectorForActiveSession(options = {}) {
  if (!state.activeSessionId) {
    resetInspector();
    return;
  }
  await Promise.allSettled([
    refreshTodos(options),
    refreshTraceRuns({ preferredRunId: options.preferredRunId, quiet: options.quiet }),
  ]);
}

export function refreshInspectorAfterChat(result) {
  patchState({
    lastRunId: result.run_id,
    lastChatResult: result,
  });
  renderInspector();
  return Promise.allSettled([
    refreshTodos({ quiet: false }),
    refreshTraceRuns({ preferredRunId: result.run_id, quiet: false }),
  ]);
}

function activateTab(tab) {
  setActiveInspectorTab(tab);
  if (!state.inspectorOpen) {
    setInspectorOpen(true);
  }
  renderInspectorShell();
}

async function submitDeleteTrace(event) {
  event.preventDefault();
  const requestUserId = state.userId;
  const requestSessionId = state.activeSessionId;
  const requestRunId = state.selectedRunId;
  if (!requestRunId) {
    closeDialog(dom.deleteTraceDialog);
    return;
  }
  patchState({ isDeletingTrace: true });
  renderTraceDetail();
  try {
    await deleteTrace(requestUserId, requestRunId);
    const ownsResponse = state.userId === requestUserId
      && state.activeSessionId === requestSessionId
      && state.selectedRunId === requestRunId;
    if (!ownsResponse) {
      return;
    }
    closeDialog(dom.deleteTraceDialog);
    patchState({ selectedRunId: null, traceDetail: null, isDeletingTrace: false });
    notify("Trace 已删除；消息和 Todo 保持不变。", "success");
    await refreshTraceRuns({ preferredRunId: null });
  } catch (error) {
    patchState({ isDeletingTrace: false });
    renderTraceDetail();
    notify(describeError(error, "Trace 删除失败。"), "error");
  }
}

export function initializeInspector(options = {}) {
  notify = options.notify || notify;
  describeError = options.describeError || describeError;

  dom.toggleButton.addEventListener("click", () => {
    setInspectorOpen(!state.inspectorOpen);
    renderInspectorShell();
  });
  dom.closeButton.addEventListener("click", () => {
    setInspectorOpen(false);
    renderInspectorShell();
  });
  dom.tabs.forEach((button, index) => {
    const tab = button.id.replace("-tab-button", "");
    button.addEventListener("click", () => activateTab(tab));
    button.addEventListener("keydown", (event) => {
      let nextIndex = null;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % TAB_NAMES.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + TAB_NAMES.length) % TAB_NAMES.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = TAB_NAMES.length - 1;
      if (nextIndex !== null) {
        event.preventDefault();
        activateTab(TAB_NAMES[nextIndex]);
        dom.tabs[nextIndex].focus();
      }
    });
  });
  dom.refreshTodosButton.addEventListener("click", () => void refreshTodos());
  dom.refreshTracesButton.addEventListener("click", () => void refreshTraceRuns());
  dom.traceRunList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-run-id]");
    if (button) {
      void loadTraceDetail(button.dataset.runId);
    }
  });
  dom.copyRunIdButton.addEventListener("click", async () => {
    const runId = (state.lastChatResult && state.lastChatResult.run_id)
      || state.lastRunId
      || state.selectedRunId;
    if (!runId) return;
    try {
      await navigator.clipboard.writeText(runId);
      notify("Run ID 已复制。", "success");
    } catch (error) {
      notify("无法复制 Run ID，请手动选择。", "error");
    }
  });
  dom.deleteTraceButton.addEventListener("click", () => {
    if (state.selectedRunId) openDialog(dom.deleteTraceDialog);
  });
  dom.deleteTraceForm.addEventListener("submit", submitDeleteTrace);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.inspectorOpen && window.matchMedia("(max-width: 1280px)").matches) {
      setInspectorOpen(false);
      renderInspectorShell();
    }
  });
  renderInspector();
}
