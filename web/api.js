"use strict";

export class ApiError extends Error {
  constructor(message, status = 0, code = "request_failed", details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export async function apiRequest(path, options = {}) {
  const requestOptions = { ...options };
  const headers = new Headers(options.headers || {});
  if (requestOptions.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  requestOptions.headers = headers;

  let response;
  try {
    response = await fetch(path, requestOptions);
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new ApiError("请求已取消。", 0, "request_aborted");
    }
    throw new ApiError("无法连接后端服务，请确认 FastAPI 已启动。", 0, "network_error");
  }

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json")) {
    try {
      payload = await response.json();
    } catch (error) {
      throw new ApiError("后端返回了无法解析的数据。", response.status, "invalid_response");
    }
  } else {
    await response.text();
  }

  if (!response.ok) {
    const errorBody = payload && payload.error && typeof payload.error === "object"
      ? payload.error
      : null;
    const message = errorBody && typeof errorBody.message === "string"
      ? errorBody.message
      : "后端暂时无法完成请求，请稍后重试。";
    const code = errorBody && typeof errorBody.code === "string"
      ? errorBody.code
      : "http_error";
    throw new ApiError(message, response.status, code, payload);
  }

  if (!contentType.includes("application/json")) {
    throw new ApiError("后端返回了非 JSON 响应。", response.status, "invalid_response");
  }
  return payload;
}

function query(parameters) {
  return new URLSearchParams(parameters).toString();
}

function sessionPath(sessionId, suffix = "") {
  return `/api/sessions/${encodeURIComponent(sessionId)}${suffix}`;
}

function tracePath(runId = "") {
  return runId ? `/api/traces/${encodeURIComponent(runId)}` : "/api/traces";
}

function expectArray(payload, resourceName) {
  if (!Array.isArray(payload)) {
    throw new ApiError(`后端返回的${resourceName}格式无效。`, 200, "invalid_response");
  }
  return payload;
}

function expectObject(payload, resourceName) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new ApiError(`后端返回的${resourceName}格式无效。`, 200, "invalid_response");
  }
  return payload;
}

export function healthCheck() {
  return apiRequest("/api/health");
}

export function createSession(payload) {
  return apiRequest("/api/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listSessions(userId, { signal } = {}) {
  return expectArray(
    await apiRequest(`/api/sessions?${query({ user_id: userId })}`, { signal }),
    "Session 列表",
  );
}

export function getSession(userId, sessionId) {
  return apiRequest(`${sessionPath(sessionId)}?${query({ user_id: userId })}`);
}

export function renameSession(userId, sessionId, title) {
  return apiRequest(sessionPath(sessionId), {
    method: "PATCH",
    body: JSON.stringify({ user_id: userId, title }),
  });
}

export function deleteSession(userId, sessionId) {
  return apiRequest(`${sessionPath(sessionId)}?${query({ user_id: userId })}`, {
    method: "DELETE",
  });
}

export async function listMessages(userId, sessionId, limit = 200, { signal } = {}) {
  return expectArray(await apiRequest(
    `${sessionPath(sessionId, "/messages")}?${query({ user_id: userId, limit: String(limit) })}`,
    { signal },
  ), "消息列表");
}

export function clearMessages(userId, sessionId) {
  return apiRequest(
    `${sessionPath(sessionId, "/messages")}?${query({ user_id: userId })}`,
    { method: "DELETE" },
  );
}

export async function sendChat(payload) {
  return expectObject(await apiRequest("/api/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  }), "Chat 响应");
}

export function listTodos(userId, sessionId, { signal } = {}) {
  return apiRequest(
    `${sessionPath(sessionId, "/todos")}?${query({ user_id: userId })}`,
    { signal },
  ).then((payload) => expectArray(payload, "Todo 列表"));
}

export function listTraceRuns(
  userId,
  { sessionId = null, status = null, limit = 50, signal } = {},
) {
  const parameters = { user_id: userId, limit: String(limit) };
  if (sessionId) {
    parameters.session_id = sessionId;
  }
  if (status) {
    parameters.status = status;
  }
  return apiRequest(`${tracePath()}?${query(parameters)}`, { signal })
    .then((payload) => expectArray(payload, "Trace 列表"));
}

export function getTrace(userId, runId, { signal } = {}) {
  return apiRequest(`${tracePath(runId)}?${query({ user_id: userId })}`, { signal })
    .then((payload) => expectObject(payload, "Trace 详情"));
}

export function deleteTrace(userId, runId) {
  return apiRequest(`${tracePath(runId)}?${query({ user_id: userId })}`, {
    method: "DELETE",
  });
}
