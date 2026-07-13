"use strict";

export const STORAGE_KEYS = Object.freeze({
  userId: "minimal-agent.user-id",
  activeSessionId: "minimal-agent.active-session-id",
  sidebarCollapsed: "minimal-agent.sidebar-collapsed",
  inspectorOpen: "minimal-agent.inspector-open",
  inspectorTab: "minimal-agent.inspector-tab",
});

export const state = {
  userId: "demo-user",
  sessions: [],
  activeSessionId: null,
  messages: [],
  isLoadingSessions: false,
  isLoadingMessages: false,
  isSending: false,
  serviceAvailable: false,
  llmConfigured: false,
  databaseAvailable: false,
  lastRunId: null,
  sidebarCollapsed: false,
  inspectorOpen: true,
  activeInspectorTab: "overview",
  todos: [],
  traceRuns: [],
  selectedRunId: null,
  traceDetail: null,
  isLoadingTodos: false,
  isLoadingTraceRuns: false,
  isLoadingTraceDetail: false,
  isDeletingTrace: false,
  lastChatResult: null,
};

function readStoredValue(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function writeStoredValue(key, value) {
  try {
    if (value == null || value === "") {
      window.localStorage.removeItem(key);
    } else {
      window.localStorage.setItem(key, String(value));
    }
  } catch (error) {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
}

export function loadPreferences() {
  const storedUserId = (readStoredValue(STORAGE_KEYS.userId) || "").trim();
  const storedInspectorOpen = readStoredValue(STORAGE_KEYS.inspectorOpen);
  const storedInspectorTab = readStoredValue(STORAGE_KEYS.inspectorTab);
  state.userId = storedUserId || "demo-user";
  state.sidebarCollapsed = readStoredValue(STORAGE_KEYS.sidebarCollapsed) === "true";
  state.inspectorOpen = storedInspectorOpen === null ? true : storedInspectorOpen === "true";
  state.activeInspectorTab = ["overview", "todo", "trace"].includes(storedInspectorTab)
    ? storedInspectorTab
    : "overview";
  return {
    activeSessionId: readStoredValue(STORAGE_KEYS.activeSessionId),
    inspectorPreferencePresent: storedInspectorOpen !== null,
  };
}

export function patchState(changes) {
  Object.assign(state, changes);
}

export function clearInspectorState() {
  patchState({
    todos: [],
    traceRuns: [],
    selectedRunId: null,
    traceDetail: null,
    isLoadingTodos: false,
    isLoadingTraceRuns: false,
    isLoadingTraceDetail: false,
    isDeletingTrace: false,
    lastChatResult: null,
  });
}

export function changeUser(userId) {
  const normalizedUserId = userId.trim();
  patchState({
    userId: normalizedUserId,
    sessions: [],
    activeSessionId: null,
    messages: [],
    isLoadingSessions: false,
    isLoadingMessages: false,
    isSending: false,
    lastRunId: null,
  });
  clearInspectorState();
  writeStoredValue(STORAGE_KEYS.userId, normalizedUserId);
  writeStoredValue(STORAGE_KEYS.activeSessionId, null);
}

export function setActiveSession(sessionId) {
  const valid = state.sessions.some((session) => session.session_id === sessionId);
  state.activeSessionId = valid ? sessionId : null;
  state.messages = [];
  state.lastRunId = null;
  clearInspectorState();
  writeStoredValue(STORAGE_KEYS.activeSessionId, state.activeSessionId);
}

export function restoreActiveSession(preferredSessionId) {
  const validPreferred = state.sessions.some(
    (session) => session.session_id === preferredSessionId,
  );
  const nextSessionId = validPreferred
    ? preferredSessionId
    : (state.sessions[0] ? state.sessions[0].session_id : null);
  if (state.activeSessionId !== nextSessionId) {
    setActiveSession(nextSessionId);
  } else {
    writeStoredValue(STORAGE_KEYS.activeSessionId, nextSessionId);
  }
  return state.activeSessionId;
}

export function setSidebarCollapsed(collapsed) {
  state.sidebarCollapsed = Boolean(collapsed);
  writeStoredValue(STORAGE_KEYS.sidebarCollapsed, state.sidebarCollapsed);
}

export function setInspectorOpen(open) {
  state.inspectorOpen = Boolean(open);
  writeStoredValue(STORAGE_KEYS.inspectorOpen, state.inspectorOpen);
}

export function setActiveInspectorTab(tab) {
  if (!["overview", "todo", "trace"].includes(tab)) {
    return;
  }
  state.activeInspectorTab = tab;
  writeStoredValue(STORAGE_KEYS.inspectorTab, tab);
}
