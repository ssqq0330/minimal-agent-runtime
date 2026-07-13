"use strict";

function appendInlineMarkdown(container, text) {
  const pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
  let cursor = 0;
  let match = pattern.exec(text);
  while (match) {
    if (match.index > cursor) {
      container.append(document.createTextNode(text.slice(cursor, match.index)));
    }
    const token = match[0];
    const element = document.createElement(token.startsWith("**") ? "strong" : "code");
    element.textContent = token.startsWith("**") ? token.slice(2, -2) : token.slice(1, -1);
    container.append(element);
    cursor = match.index + token.length;
    match = pattern.exec(text);
  }
  if (cursor < text.length) {
    container.append(document.createTextNode(text.slice(cursor)));
  }
}

export function renderSafeMessage(container, text) {
  container.replaceChildren();
  const value = typeof text === "string" ? text : String(text ?? "");
  const lines = value.split("\n");
  let list = null;

  lines.forEach((line, index) => {
    if (line.startsWith("- ") && line.length > 2) {
      if (!list) {
        list = document.createElement("ul");
        container.append(list);
      }
      const item = document.createElement("li");
      appendInlineMarkdown(item, line.slice(2));
      list.append(item);
      return;
    }

    list = null;
    const lineContainer = document.createElement("span");
    lineContainer.className = "message-line";
    appendInlineMarkdown(lineContainer, line);
    container.append(lineContainer);
    if (index < lines.length - 1) {
      container.append(document.createElement("br"));
    }
  });
}
