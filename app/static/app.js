const dropZone = document.querySelector("#drop-zone");
const fileInput = document.querySelector("#file-input");
const statusMessage = document.querySelector("#upload-status");
const results = document.querySelector("#results");
const searchInput = document.querySelector("#search-input");
const savedList = document.querySelector("#saved-list");
const savedSearch = document.querySelector("#saved-search");
let extractedDocument = null;
let savedSearchTimer = null;

document.querySelector("#browse-button").addEventListener("click", (event) => {
  event.stopPropagation();
  fileInput.click();
});
dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
  fileInput.value = "";
});

for (const eventName of ["dragenter", "dragover"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
}
dropZone.addEventListener("drop", (event) => {
  if (event.dataTransfer.files[0]) uploadFile(event.dataTransfer.files[0]);
});

async function uploadFile(file) {
  statusMessage.className = "upload-status";
  statusMessage.textContent = `Extracting ${file.name}…`;
  const formData = new FormData();
  formData.append("file", file);
  try {
    const response = await fetch("/api/extract", { method: "POST", body: formData });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Extraction failed. Please try again.");
    extractedDocument = result;
    renderResult(result);
    statusMessage.className = "upload-status success";
    statusMessage.textContent = "Extraction complete. The JSON result is saved; the original file was not retained.";
    await loadSavedDocuments();
  } catch (error) {
    statusMessage.className = "upload-status error";
    statusMessage.textContent = error.message || "Could not reach the server. Check your connection and try again.";
    results.hidden = true;
  }
}

function renderResult(data) {
  extractedDocument = data;
  document.querySelector("#document-name").textContent = data.filename;
  document.querySelector("#document-meta").textContent =
    `${data.file_type.toUpperCase()} · ${data.page_count === null ? "page count unavailable" : `${data.page_count} page${data.page_count === 1 ? "" : "s"}`}${data.saved_at ? ` · Saved ${formatDate(data.saved_at)}` : ""}`;
  document.querySelector("#delete-current-button").hidden = !data.id;
  renderOriginalPages(data.page_previews || []);
  renderContent(data, "");
  results.hidden = false;
  setActiveTab(data.page_previews?.length ? "original" : "content");
}

function renderOriginalPages(pagePreviews) {
  const container = document.querySelector("#original-view");
  container.replaceChildren();
  const hasPagePreviews = pagePreviews.length > 0;
  document.querySelector("#original-tab").hidden = !hasPagePreviews;
  if (!hasPagePreviews) return;

  for (const preview of pagePreviews) {
    const figure = document.createElement("figure");
    figure.className = "original-page";
    const caption = document.createElement("figcaption");
    caption.textContent = `Page ${preview.page}`;
    const image = document.createElement("img");
    image.src = preview.url;
    image.alt = `Original PDF page ${preview.page}`;
    image.loading = "lazy";
    image.decoding = "async";
    figure.append(caption, image);
    container.append(figure);
  }
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

async function loadSavedDocuments(query = savedSearch.value.trim()) {
  savedList.replaceChildren();
  const loading = document.createElement("p");
  loading.className = "saved-empty";
  loading.textContent = "Loading saved documents…";
  savedList.append(loading);
  try {
    const response = await fetch(`/api/documents?q=${encodeURIComponent(query)}&limit=50`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not load saved documents.");
    document.querySelector("#saved-count").textContent = result.total ? `(${result.total})` : "";
    savedList.replaceChildren();
    if (!result.items.length) {
      const empty = document.createElement("p");
      empty.className = "saved-empty";
      empty.textContent = query ? "No saved documents match your search." : "No saved documents yet. Upload a PDF or DOCX to get started.";
      savedList.append(empty);
      return;
    }

    for (const documentInfo of result.items) {
      const item = document.createElement("article");
      item.className = "saved-item";
      const icon = document.createElement("span");
      icon.className = "saved-file-icon";
      icon.textContent = documentInfo.file_type.toUpperCase();
      const info = document.createElement("div");
      info.className = "saved-document-info";
      const openButton = document.createElement("button");
      openButton.className = "saved-open";
      openButton.type = "button";
      openButton.textContent = documentInfo.filename;
      openButton.title = documentInfo.filename;
      openButton.addEventListener("click", () => openSavedDocument(documentInfo.id));
      const preview = document.createElement("p");
      preview.className = "saved-preview";
      preview.textContent = documentInfo.preview || "No text preview available.";
      const date = document.createElement("div");
      date.className = "saved-date";
      date.textContent = `Saved ${formatDate(documentInfo.saved_at)}`;
      info.append(openButton, preview, date);
      const deleteButton = document.createElement("button");
      deleteButton.className = "saved-delete";
      deleteButton.type = "button";
      deleteButton.textContent = "Delete";
      deleteButton.setAttribute("aria-label", `Delete ${documentInfo.filename}`);
      deleteButton.addEventListener("click", () => removeSavedDocument(documentInfo.id, documentInfo.filename));
      item.append(icon, info, deleteButton);
      savedList.append(item);
    }
  } catch (error) {
    savedList.replaceChildren();
    const message = document.createElement("p");
    message.className = "saved-empty";
    message.textContent = error.message || "Could not load saved documents.";
    savedList.append(message);
  }
}

async function openSavedDocument(id) {
  try {
    const response = await fetch(`/api/documents/${encodeURIComponent(id)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not open saved document.");
    searchInput.value = "";
    renderResult(result);
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    statusMessage.className = "upload-status error";
    statusMessage.textContent = error.message || "Could not open saved document.";
  }
}

async function removeSavedDocument(id, filename) {
  if (!window.confirm(`Permanently delete the saved JSON for "${filename}"?`)) return;
  try {
    const response = await fetch(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.detail || "Could not delete saved document.");
    }
    if (extractedDocument?.id === id) {
      extractedDocument = null;
      results.hidden = true;
      savedSearch.value = "";
    }
    statusMessage.className = "upload-status success";
    statusMessage.textContent = `Deleted saved JSON for ${filename}.`;
    await loadSavedDocuments();
  } catch (error) {
    statusMessage.className = "upload-status error";
    statusMessage.textContent = error.message || "Could not delete saved document.";
  }
}

document.querySelector("#delete-current-button").addEventListener("click", () => {
  if (extractedDocument?.id) removeSavedDocument(extractedDocument.id, extractedDocument.filename);
});
savedSearch.addEventListener("input", () => {
  clearTimeout(savedSearchTimer);
  savedSearchTimer = setTimeout(() => loadSavedDocuments(), 250);
});
loadSavedDocuments();

function appendHighlightedText(container, text, query) {
  if (!query) {
    container.append(document.createTextNode(text));
    return;
  }
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  for (const part of parts) {
    if (part.toLowerCase() === query.toLowerCase()) {
      const mark = document.createElement("mark");
      mark.textContent = part;
      container.append(mark);
    } else {
      container.append(document.createTextNode(part));
    }
  }
}

function getDisplayBlocks(blocks) {
  const displayBlocks = [];
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index];
    const isStyledListItem =
      block.type === "list_item" ||
      /^List (Bullet|Number)/i.test(block.style || "");
    const questionNumber = block.question_number ??
      Number(block.text?.match(/^\s*(\d{1,2})\.\s*/)?.[1]);
    if (Number.isInteger(questionNumber) && questionNumber > 0) {
      displayBlocks.push({ ...block, question_number: questionNumber });
      continue;
    }
    if (isStyledListItem) {
      displayBlocks.push({
        ...block,
        type: "list_item",
        list_kind: block.list_kind || (/^List Number/i.test(block.style || "") ? "number" : "bullet"),
      });
      continue;
    }

    const nextBlock = blocks[index + 1];
    const marker = block.type === "paragraph" ? block.text.trim() : "";
    const markerBox = block.bbox;
    const nextBox = nextBlock?.bbox;
    const isStandaloneBullet = /^[•●▪◦‣⁃·*]$/.test(marker);
    const nearbyNextBlock =
      markerBox?.length === 4 &&
      nextBox?.length === 4 &&
      Math.abs(markerBox[0] - nextBox[0]) <= 48 &&
      nextBox[1] - markerBox[3] <= 48 &&
      nextBox[1] - markerBox[3] >= -(markerBox[3] - markerBox[1]);
    const nextIsListItem =
      nextBlock?.type === "list_item" ||
      (nextBlock?.type === "paragraph" && /^List (Bullet|Number)/i.test(nextBlock.style || ""));
    if (
      isStandaloneBullet &&
      nextBlock?.type === "paragraph" &&
      nearbyNextBlock &&
      !nextIsListItem
    ) {
      displayBlocks.push({
        ...nextBlock,
        type: "list_item",
        list_kind: "bullet",
        marker,
      });
      index += 1;
      continue;
    }
    displayBlocks.push(block);
  }
  return displayBlocks;
}

function renderContent(data, query) {
  const container = document.querySelector("#content-view");
  container.replaceChildren();
  let matches = 0;
  const pages = data.file_type === "pdf" ? data.blocks : [{ page: null, blocks: data.blocks }];
  for (const page of pages) {
    const visibleBlocks = getDisplayBlocks(page.blocks).filter((block) => {
      const searchable = block.type === "table" ? block.rows.flat().join(" ") : block.text;
      const matched = !query || searchable.toLowerCase().includes(query.toLowerCase());
      if (matched && query) matches += 1;
      return matched;
    });
    if (!visibleBlocks.length) continue;

    const section = document.createElement("section");
    section.className = "content-page";
    if (page.page !== null) {
      const label = document.createElement("p");
      label.className = "page-label";
      label.textContent = `Page ${page.page}`;
      section.append(label);
    }
    let activeList = null;
    let activeListKind = null;
    for (const block of visibleBlocks) {
      if (block.type === "table") {
        activeList = null;
        activeListKind = null;
        const wrapper = document.createElement("div");
        wrapper.className = "table-wrap";
        const table = document.createElement("table");
        table.className = "content-table";
        for (const [rowIndex, row] of block.rows.entries()) {
          const tr = document.createElement("tr");
          for (const cellText of row) {
            const cell = document.createElement(rowIndex === 0 ? "th" : "td");
            appendHighlightedText(cell, cellText, query);
            tr.append(cell);
          }
          table.append(tr);
        }
        wrapper.append(table);
        section.append(wrapper);
      } else if (block.type === "list_item") {
        const listKind = block.list_kind === "number" ? "number" : "bullet";
        if (activeListKind !== listKind) {
          activeList = document.createElement(listKind === "number" ? "ol" : "ul");
          activeList.className = "content-list";
          section.append(activeList);
          activeListKind = listKind;
        }
        const item = document.createElement("li");
        appendHighlightedText(item, block.text, query);
        activeList.append(item);
      } else {
        activeList = null;
        activeListKind = null;
        const paragraph = document.createElement("p");
        paragraph.className = "content-block";
        const questionNumber = block.question_number;
        const numberPrefix = questionNumber
          ? new RegExp(`^\\s*${questionNumber}\\.\\s*`)
          : null;
        const questionText = numberPrefix ? block.text.replace(numberPrefix, "") : block.text;
        if (questionNumber) {
          const number = document.createElement("span");
          number.className = "question-number";
          number.textContent = `${questionNumber}.`;
          paragraph.append(number);
        }
        appendHighlightedText(paragraph, questionText, query);
        section.append(paragraph);
      }
    }
    container.append(section);
  }
  document.querySelector("#search-count").textContent = query ? `${matches} match${matches === 1 ? "" : "es"}` : "";
  if (!container.childElementCount) {
    const empty = document.createElement("p");
    empty.className = "content-block";
    empty.textContent = "No matching content.";
    container.append(empty);
  }
}

searchInput.addEventListener("input", () => {
  if (extractedDocument) renderContent(extractedDocument, searchInput.value.trim());
});

function setActiveTab(tabName) {
  for (const [tab, panel, name] of [
    ["original-tab", "original-view", "original"],
    ["content-tab", "content-view", "content"],
  ]) {
    const isActive = tabName === name;
    document.querySelector(`#${tab}`).classList.toggle("active", isActive);
    document.querySelector(`#${tab}`).setAttribute("aria-selected", String(isActive));
    document.querySelector(`#${panel}`).hidden = !isActive;
  }
}
document.querySelector("#original-tab").addEventListener("click", () => setActiveTab("original"));
document.querySelector("#content-tab").addEventListener("click", () => setActiveTab("content"));

document.querySelector("#download-button").addEventListener("click", () => {
  if (!extractedDocument) return;
  const blob = new Blob([`${JSON.stringify(extractedDocument, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${extractedDocument.filename.replace(/\.[^.]+$/, "")}.json`;
  link.click();
  URL.revokeObjectURL(url);
});
