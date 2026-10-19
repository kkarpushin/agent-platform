"use strict";

/* Без сборки и внешних библиотек. Данные API всегда становятся текстом DOM. */
const $ = (selector, root = document) => root.querySelector(selector);
const state = {
  bootstrap: null,
  person: "mark",
  token: "",
  page: "",
  render: 0,
  busy: false,
  commandPreset: null,
};
try {
  state.person = localStorage.getItem("mayak-person") || "mark";
} catch (_) {
  /* private browsing */
}
const layers = [
  {
    id: "people",
    title: "Цели и люди",
    description: "Ради чего работаем и кто отвечает за результат.",
    icon: "◎",
  },
  {
    id: "roles",
    title: "Роли и полномочия",
    description: "Кто видит сведения, выполняет и утверждает.",
    icon: "◇",
  },
  {
    id: "knowledge",
    title: "Знания и информация",
    description: "Источники, поиск и основания для ответа.",
    icon: "▤",
  },
  {
    id: "skills",
    title: "Скиллы",
    description: "Способы работы, которые можно повторить.",
    icon: "✳",
  },
  {
    id: "agents",
    title: "Агенты и модели",
    description: "Исполнители с понятным входом и результатом.",
    icon: "↗",
  },
  {
    id: "tools",
    title: "Инструменты и доступы",
    description: "Чем пользуется система и где её границы.",
    icon: "⊞",
  },
  {
    id: "processes",
    title: "Процессы",
    description: "Как задача проходит от запроса до решения.",
    icon: "⇢",
  },
  {
    id: "runs",
    title: "Запуск и состояние",
    description: "Что выполняется, завершено или ждёт человека.",
    icon: "◷",
  },
  {
    id: "quality",
    title: "Проверка и улучшение",
    description: "Проверки, принятые решения и опыт команды.",
    icon: "✓",
  },
];
const sectionTitles = {
  projects: "Проекты",
  procedures: "Правила работы",
  rules: "Правила работы",
  finance: "Внутренние финансы",
  decisions: "Принятые решения",
  team: "Команда",
  finances: "Финансы",
  services: "Услуги и цены",
  costs: "Себестоимость",
  cases: "Кейсы",
  clients: "Клиенты",
  templates: "Шаблоны",
  technical: "Технические сведения",
};
const agentTitles = {
  "work-assistant": "Помощник по поручениям",
  "task-intake": "Разбор входящих",
  "daily-brief": "Сводка руководителя",
};
const fieldTitles = {
  request: "Поручение",
  skill: "Способ работы",
  selected_skill: "Применённый скилл",
  suggested_agent: "Предложенный процесс",
  suggested_input: "Вход для следующего процесса",
  missing_capability: "Недостающая возможность",
  event_id: "Входящее сообщение",
  project_id: "Проект",
  action: "Предлагаемое действие",
  task_id: "Задача",
  base_version: "Версия задачи до изменения",
  title: "Название задачи",
  owner: "Ответственный",
  status: "Состояние",
  due_date: "Срок",
  blocked_by: "Что мешает",
  question: "Вопрос человеку",
  source_refs: "Основания",
  client: "Клиент",
  task: "Задача",
  budget: "Бюджет, USD",
  deadline: "Желаемый срок",
  language: "Язык результата",
  markdown: "Текст результата",
  services: "Услуги",
  total_price: "Итоговая цена",
  timeline: "Длительность в днях",
  cases: "Кейсы",
  assumptions: "Допущения",
  sources: "Источники",
};
const statusTitles = {
  running: "Выполняется",
  needs_review: "Ждёт проверки",
  approved: "Одобрено",
  error: "Ошибка",
};
const statusClass = {
  running: "neutral",
  needs_review: "warning",
  approved: "",
  error: "error",
};
const skillTitles = {
  "explain-process": "Объяснение процесса",
  "meeting-actions": "Действия после встречи",
  "task-intake": "Разбор входящих",
  "daily-brief": "Сводка руководителя",
  intake: "Разбор входящих",
  review: "Проверка результата",
  "knowledge-update": "Обновление знаний",
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
function add(parent, ...children) {
  for (const child of children.flat()) if (child) parent.append(child);
  return parent;
}
function link(text, href, cls = "button") {
  const n = el("a", cls, text);
  n.href = href;
  return n;
}
function badge(text, cls = "") {
  return el("span", `badge ${cls}`, text);
}
function button(text, handler, cls = "") {
  const n = el("button", `button ${cls}`, text);
  n.type = "button";
  if (handler) n.addEventListener("click", handler);
  return n;
}
function definition(term, description, coral = false) {
  return add(
    el("div", `definition${coral ? " coral" : ""}`),
    el("strong", "", `${term} `),
    document.createTextNode(description),
  );
}
function titleForAgent(name) {
  return agentTitles[name] || name;
}
function roleTitle(role) {
  return state.bootstrap?.roles?.[role]?.title || role;
}
function personName(id) {
  if (id === "starter") return "Учебные исходники";
  if (String(id).startsWith("agent:"))
    return `Агент: ${titleForAgent(id.slice(6))}`;
  return state.bootstrap?.people?.find((p) => p.id === id)?.name || id;
}
function isCEO() {
  return state.bootstrap?.person?.role === "ceo";
}
function formatDate(value) {
  if (!value) return "Нет данных";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : `${new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(date)} UTC`;
}
function money(value) {
  return value === null || value === undefined
    ? "Не определена"
    : `${Number(value).toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 6 })} USD`;
}
function pretty(value) {
  return JSON.stringify(value, null, 2);
}
function shortVersion(value) {
  return String(value ?? "").slice(0, 10);
}
function announce(text) {
  $("#announcer").textContent = text;
}
function showError(error) {
  const box = $("#global-error");
  box.textContent = error?.message || String(error);
  box.hidden = false;
  announce(box.textContent);
}
function clearError() {
  $("#global-error").hidden = true;
  $("#global-error").textContent = "";
}
async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(state.token
      ? { Authorization: `Bearer ${state.token}` }
      : { "X-Person": state.person }),
    ...(options.headers || {}),
  };
  let response;
  try {
    response = await fetch(path, { ...options, headers, cache: "no-store" });
  } catch (_) {
    throw new Error(
      "Платформа недоступна. Проверьте, что система запущена, и повторите действие.",
    );
  }
  let data;
  try {
    data = await response.json();
  } catch (_) {
    throw new Error(
      `Сервер вернул ответ без данных (HTTP ${response.status}). Проверьте журнал платформы.`,
    );
  }
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : pretty(data.detail || data);
    const error = new Error(detail || `Ошибка HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}
async function withButton(btn, fn, label = "Подождите…") {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  try {
    return await fn();
  } catch (error) {
    showError(error);
  } finally {
    if (btn.isConnected) {
      btn.disabled = false;
      btn.textContent = original;
    }
  }
}
function heading(title, description, layer, actions = []) {
  const box = el("div", "page-heading");
  const copy = el("div");
  add(
    copy,
    el(
      "div",
      "eyebrow",
      layer
        ? `СЛОЙ ${String(layer).padStart(2, "0")} / 09`
        : "РАБОЧЕЕ ПРОСТРАНСТВО",
    ),
    el("h1", "", title),
    description && el("p", "", description),
  );
  add(box, copy, actions.length && add(el("div", "heading-actions"), actions));
  return box;
}
function sectionHeading(title, note) {
  return add(
    el("div", "section-title"),
    el("h2", "", title),
    note && el("span", "", note),
  );
}
function empty(title, description, action) {
  return add(
    el("div", "empty-state"),
    el("h3", "", title),
    el("p", "", description),
    action,
  );
}
function loading() {
  return add(
    el("div", "loading-state"),
    el("span", "spinner"),
    el("p", "", "Загружаем данные…"),
  );
}
function chipList(items, mapper = (value) => value) {
  return add(
    el("div", "chips"),
    items.map((value) => badge(mapper(value), "neutral")),
  );
}
function keyList(items) {
  const list = el("ul", "list-clean");
  for (const [title, description] of items)
    add(
      list,
      add(
        el("li"),
        el("strong", "", title),
        document.createTextNode(description),
      ),
    );
  return list;
}
function safeInline(node, text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  for (const part of parts) {
    if (part.startsWith("**") && part.endsWith("**"))
      node.append(el("strong", "", part.slice(2, -2)));
    else if (part.startsWith("`") && part.endsWith("`"))
      node.append(el("code", "", part.slice(1, -1)));
    else node.append(document.createTextNode(part));
  }
  return node;
}
function markdown(text) {
  const box = el("div", "markdown");
  const lines = String(text || "").split("\n");
  let list = null;
  const cells = (line) =>
    line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.trim()) {
      list = null;
      continue;
    }
    if (line.trim().startsWith("```")) {
      list = null;
      const code = [];
      while (++i < lines.length && !lines[i].trim().startsWith("```"))
        code.push(lines[i]);
      box.append(el("pre", "code-block", code.join("\n")));
      continue;
    }
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      cells(lines[i + 1]).every((cell) => /^:?-{3,}:?$/.test(cell))
    ) {
      list = null;
      const table = el("table");
      const headers = cells(line);
      add(
        table,
        add(
          el("thead"),
          add(
            el("tr"),
            headers.map((cell) => safeInline(el("th"), cell)),
          ),
        ),
      );
      const body = el("tbody");
      i += 1;
      while (
        i + 1 < lines.length &&
        lines[i + 1].includes("|") &&
        lines[i + 1].trim()
      ) {
        const values = cells(lines[++i]);
        body.append(
          add(
            el("tr"),
            headers.map((_, index) =>
              safeInline(el("td"), values[index] || ""),
            ),
          ),
        );
      }
      add(table, body);
      box.append(add(el("div", "table-wrap spaced"), table));
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.+)$/);
    const item = line.match(/^\s*(?:([-*])|(\d+)\.)\s+(.+)$/);
    const quote = line.match(/^>\s?(.*)$/);
    if (h) {
      list = null;
      box.append(safeInline(el(h[1].length < 3 ? "h2" : "h3"), h[2]));
    } else if (item) {
      const kind = item[2] ? "OL" : "UL";
      if (!list || list.tagName !== kind) {
        list = el(kind.toLowerCase());
        box.append(list);
      }
      list.append(safeInline(el("li"), item[3]));
    } else if (quote) {
      list = null;
      box.append(safeInline(el("blockquote"), quote[1]));
    } else {
      list = null;
      box.append(safeInline(el("p"), line));
    }
  }
  return box;
}

const iconPaths = {
  overview: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M3 14h7v7H3z", "M14 14h7v7h-7z"],
  people: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8", "M20 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"],
  roles: ["M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z", "m9 12 2 2 4-4"],
  knowledge: ["M4 3h12l4 4v14H4Z", "M14 3v5h6", "M8 12h8", "M8 16h5"],
  skills: ["m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"],
  agents: ["M7 7h10a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-7a3 3 0 0 1 3-3Z", "M12 3v4", "M9 12v2", "M15 12v2", "M9 17h6", "M1 11v5", "M23 11v5"],
  tools: ["m14.7 6.3 3 3", "m5 19 5-5", "M14 2a6 6 0 0 0-5 9L2 18a2.8 2.8 0 0 0 4 4l7-7a6 6 0 0 0 9-5l-4 2-4-4Z"],
  processes: ["M4 3h6v6H4z", "M14 15h6v6h-6z", "M7 9v8a1 1 0 0 0 1 1h6", "M10 6h7v9"],
  runs: ["M12 3a9 9 0 1 1-6.4 2.6", "M3 3v5h5", "M12 7v5l3 2"],
  quality: ["M20 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9", "m9 11 3 3L22 4"],
};
function icon(name, cls = "ui-icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({ viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "1.6", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: cls })) svg.setAttribute(key, value);
  for (const d of iconPaths[name] || iconPaths.skills) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}
function buildNavigation() {
  const nav = $("#navigation");
  nav.replaceChildren();
  const home = link("Рабочее пространство", "#overview", "nav-link");
  home.prepend(icon("overview"));
  nav.append(home);
  const groups = [
    ["РАБОТА", ["skills", "processes", "runs"]],
    ["УСТРОЙСТВО СИСТЕМЫ", ["people", "roles", "knowledge", "agents", "tools", "quality"]],
  ];
  for (const [title, ids] of groups) {
    nav.append(el("div", "nav-group-label", title));
    for (const id of ids) {
      const index = layers.findIndex(layer => layer.id === id);
      const item = link("", `#${id}`, "nav-link");
      add(item, icon(id), el("span", "nav-title", layers[index].title), el("span", "nav-number", String(index + 1).padStart(2, "0")));
      nav.append(item);
    }
  }
}
function updateHeader() {
  const b = state.bootstrap;
  const select = $("#person-select");
  select.replaceChildren();
  for (const person of b.people || [b.person]) {
    const option = el("option", "", person.name);
    option.value = person.id;
    option.selected = person.id === b.person.id;
    select.append(option);
  }
  select.disabled = !b.demo || state.busy;
  state.person = b.person.id;
  $("#role-badge").textContent = roleTitle(b.person.role);
  const banner = $("#mode-banner");
  banner.replaceChildren();
  const worker = b.cli_worker || {};
  const connection = add(el("span", `connection-status ${worker.connected ? "connected" : ""}`), el("span", "live-dot"), document.createTextNode(b.llm_mode === "fixture" ? "Тестовые ответы" : worker.connected ? `${cliTitle(worker.provider)} подключён` : "Модель не подключена"));
  const disclosure = el("details", "mode-details");
  add(disclosure, el("summary", "", b.demo ? "Учебное пространство" : "Личный доступ"),
    el("p", "", b.demo ? "Здесь вымышленные люди и данные. Переключатель сотрудника показывает его права, но не проверяет личность." : "Действия доступны в пределах вашей роли."),
    el("p", "", b.llm_mode === "fixture" ? "Ответы из тестовой фикстуры. Этот режим используется только для автоматических проверок." : worker.connected ? "Работу выполняет настоящая модель через ваш авторизованный CLI. Детали каждого обращения сохраняются в запуске." : "Для запуска модели подключите авторизованный Claude Code или Codex по инструкции в README."));
  add(banner, connection, disclosure);

}
async function init() {
  clearError();
  // Пока меняется сотрудник, предыдущие сведения не показываются как новые.
  state.render += 1;
  $("#person-select").disabled = true;
  $("#main").replaceChildren(loading());
  try {
    state.bootstrap = await api("/api/bootstrap");
    updateHeader();
    if ($("#token-dialog").open) $("#token-dialog").close();
    await renderRoute();
  } catch (error) {
    if (error.status === 401 || error.status === 403) {
      if (!$("#token-dialog").open) $("#token-dialog").showModal();
      $("#token-error").textContent = state.token ? error.message : "";
      $("#main").replaceChildren(
        empty(
          "Нужен личный доступ",
          "Введите токен, выданный владельцем платформы.",
        ),
      );
    } else {
      showError(error);
      $("#main").replaceChildren(
        empty(
          "Не удалось открыть систему",
          "Проверьте, что платформа запущена. Сохранённые данные останутся в базе.",
          button("Повторить подключение", init, "primary"),
        ),
      );
    }
  }
}
async function renderRoute() {
  if (!state.bootstrap) return;
  const sequence = ++state.render;
  const [page = "overview", id] = location.hash.slice(1).split("/");
  state.page = page || "overview";
  clearError();
  const layer = layers.find(
    (item) =>
      item.id === state.page ||
      (state.page === "run" && item.id === "runs") ||
      (state.page === "agent" && item.id === "agents"),
  );
  $("#page-crumb").textContent = layer?.title || "Рабочее пространство";
  document.title = `${layer?.title || "Рабочее пространство"} · Маяк`;
  for (const item of document.querySelectorAll(".nav-link")) {
    const active = item.hash === `#${layer?.id || "overview"}`;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  const main = $("#main");
  main.replaceChildren(loading());
  try {
    let pageNode;
    switch (state.page) {
      case "people":
        pageNode = peoplePage();
        break;
      case "roles":
        pageNode = rolesPage();
        break;
      case "knowledge":
        pageNode = await knowledgePage();
        break;
      case "skills":
        pageNode = skillsPage();
        break;
      case "agents":
        state.bootstrap = await api("/api/bootstrap");
        updateHeader();
        pageNode = agentsPage();
        break;
      case "agent":
        pageNode = agentPage(id);
        break;
      case "tools":
        pageNode = toolsPage();
        break;
      case "processes":
        state.bootstrap = await api("/api/bootstrap");
        updateHeader();
        pageNode = await processesPage();
        break;
      case "runs":
        pageNode = await runsPage();
        break;
      case "run":
        pageNode = await runPage(id);
        break;
      case "quality":
        pageNode = await qualityPage();
        break;
      default:
        state.bootstrap = await api("/api/bootstrap");
        updateHeader();
        pageNode = await overviewPage();
    }
    if (sequence !== state.render) return;
    main.replaceChildren(pageNode);
    main.dataset.page = state.page;
    if (state.page === "overview" && state.commandPreset) {
      $("#system-request")?.focus({ preventScroll: true });
      state.commandPreset = null;
    }
    announce(`${layer?.title || "Рабочее пространство"} загружено`);
  } catch (error) {
    if (sequence !== state.render) return;
    showError(error);
    main.replaceChildren(
      empty(
        "Данные пока недоступны",
        error.message,
        button("Повторить", renderRoute, "primary"),
      ),
    );
  }
}

function cliTitle(provider) {
  if (provider === "claude" || provider === "claude-code") return "Claude Code";
  if (provider === "codex") return "Codex";
  return "Claude Code / Codex";
}
function cliStatusPanel() {
  const worker = state.bootstrap.cli_worker || {};
  return add(el("section", `panel ${worker.connected ? "sage" : "cli-offline"}`),
    add(el("div", "card-top"), el("h3", "", `${cliTitle(worker.provider)} через платформу`), badge(worker.connected ? "CLI подключён" : "Ожидает подключения", worker.connected ? "" : "warning")),
    el("p", "", worker.connected
      ? "Система отправляет запрос реальной модели через CLI — программу в терминале, в которой вы вошли в аккаунт. Сведения для запроса отбирает платформа; агенты не получают вашу учётную запись."
      : "Для работы войдите в Claude Code или Codex и запустите подключение по инструкции в README.md. Пока CLI недоступен, агент вернёт ошибку; готовый ответ не подставляется."),
    el("p", "field-hint", "Подключение показывает доступность исполнителя. Фактическое обращение к модели видно в трассировке каждого запуска. Стоимость по подписке неизвестна и не считается нулевой."),
    worker.last_seen && el("p", "field-hint", `Последняя связь: ${formatDate(worker.last_seen)}`));
}
async function workspaceData() {
  const data = await api("/api/workspace");
  return data.access === false ? null : { ...data, inbox: data.inbox || [], tasks: data.tasks || [], projects: data.projects || [], attention: data.attention || {} };
}
function workspaceSummary(workspace) {
  if (!workspace) return add(el("div", "definition"), el("strong", "", "Доступ зависит от роли. "), document.createTextNode("Рабочая доска проектов недоступна этой роли. Ниже — доступные части системы."));
  const root = el("section", "workspace-summary");
  root.setAttribute("aria-label", "Что требует внимания");
  const stats = [
    [workspace.attention.unprocessed_events ?? workspace.inbox.filter(item => item.status === "new").length, "Новые сообщения", "Нужно разобрать", "↗"],
    [workspace.attention.pending_approvals ?? 0, "Ждут решения Анны", "Предложения по задачам", "◇"],
    [workspace.attention.blocked_tasks ?? workspace.tasks.filter(taskBlocked).length, "Задачи с препятствием", "Помочь исполнителю", "!"],
    [workspace.tasks.filter(task => !taskDone(task)).length, "Открытые задачи", `${workspace.projects.length} проекта в работе`, "◎"],
  ];
  for (const [count, title, hint, icon] of stats) add(root, add(el("div", "attention-card"), el("span", "attention-icon", icon), el("strong", "attention-value", count), el("h3", "", title), el("p", "", hint)));
  return root;
}
function projectName(id, workspace) {
  const project = workspace?.projects?.find(item => item.id === id || item.data?.project_id === id);
  return project?.data?.name || project?.title || id || "Проект не указан";
}
const taskStatusTitles = { todo: "К выполнению", in_progress: "В работе", blocked: "Есть препятствие", done: "Готово" };
function taskDone(task) { return task.status === "done"; }
function taskBlocked(task) { return task.status === "blocked" || Boolean(task.blocked_by); }
function dateOnly(value) {
  if (!value) return "Не определён";
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value.split("-").reverse().join(".") : String(value);
}
function sourceChips(refs) {
  return chipList((refs || []).map(item => typeof item === "object" ? item.id || item.source_id || pretty(item) : item));
}
function inboxCard(message, workspace) {
  const card = el("article", "inbox-message");
  card.dataset.eventId = message.event_id;
  add(card,
    add(el("div", "card-top"), el("span", "eyebrow", `${message.event_id} / ${projectName(message.project_id, workspace)}`), badge(message.status === "new" ? "Новое" : statusTitles[message.status] || message.status, message.status === "new" ? "neutral" : statusClass[message.status])),
    el("p", "message-text", message.text),
    el("p", "message-meta", `${personName(message.author)} · ${formatDate(message.received_at)}`));
  const actions = el("div", "message-actions");
  if (message.run_id && message.status !== "error") {
    actions.append(link(message.status === "approved" ? "Открыть решение →" : "Проверить результат →", `#run/${encodeURIComponent(message.run_id)}`, "button text"));
  } else if (["running", "needs_review", "approved"].includes(message.status)) {
    actions.append(el("p", "field-hint", message.status === "approved"
      ? "Решение по сообщению уже принято. Изменения видны на общей доске; подробный запуск доступен автору и руководителю."
      : "Сообщение уже обрабатывает другой сотрудник. Подробный запуск доступен автору и руководителю."));
  } else if (state.bootstrap.agents.some(agent => agent.name === "task-intake" && agent.allowed)) {
    const start = button(message.status === "error" ? "Повторить разбор ↗" : "Разобрать сообщение ↗", event => withButton(event.currentTarget, async () => {
      if (state.busy) return;
      state.busy = true;
      $("#person-select").disabled = true;
      announce("Агент читает разрешённые источники и обращается к модели. Дождитесь результата.");
      try {
        const run = await api("/api/runs", { method: "POST", body: JSON.stringify({ agent: "task-intake", input: { event_id: message.event_id }, request_id: crypto.randomUUID() }) });
        location.hash = `run/${encodeURIComponent(run.id)}`;
      } finally {
        state.busy = false;
        $("#person-select").disabled = !state.bootstrap.demo;
      }
    }, "Модель разбирает сообщение…"), "primary");
    start.dataset.processEvent = message.event_id;
    actions.append(start);
    if (message.run_id) actions.append(link("Ошибка предыдущего запуска", `#run/${encodeURIComponent(message.run_id)}`, "button text"));
  } else actions.append(el("p", "field-hint", "Разбор запускает координатор или руководитель."));
  add(card, actions);
  return card;
}
function taskCard(task, workspace) {
  const card = el("article", "task-card");
  card.dataset.taskId = task.id;
  add(card,
    el("div", "eyebrow", `${task.id} / ${projectName(task.project_id, workspace)}`),
    el("h3", "", task.title),
    badge(taskStatusTitles[task.status] || task.status, taskBlocked(task) ? "warning" : "neutral"),
    el("p", "task-owner", `Ответственный: ${personName(task.owner || "Не определён")}`),
    el("p", "muted", `Срок: ${dateOnly(task.due_date)} · версия ${task.version}`));
  if (task.blocked_by) add(card, el("p", "task-blocker", task.blocked_by));
  if (task.source_refs?.length) add(card, el("p", "field-hint", "Основания"), sourceChips(task.source_refs));
  const details = el("details", "task-history");
  details.append(el("summary", "", `История изменений · ${(task.history || []).length}`));
  if (!task.history?.length) details.append(el("p", "muted", "История пока отсутствует."));
  for (const item of [...(task.history || [])].reverse()) {
    const snap = item.snapshot || {};
    add(details, add(el("div", "history-item"),
      el("strong", "", `Версия ${item.version} · ${personName(item.author)}`),
      el("small", "", formatDate(item.created_at)),
      el("p", "", snap.title || task.title),
      el("p", "muted", `${taskStatusTitles[snap.status] || snap.status || ""} · ${personName(snap.owner || "Ответственный не определён")} · ${dateOnly(snap.due_date)}`),
      snap.blocked_by && el("p", "", snap.blocked_by),
      item.run_id && link(`Решение по версии ${item.run_version} →`, `#run/${encodeURIComponent(item.run_id)}`, "button text")));
  }
  card.append(details);
  return card;
}
function taskProposal(run) {
  const data = run.output;
  const actions = { create: "Создать задачу", update: "Обновить задачу", question: "Уточнить у человека", no_action: "Оставить без изменений" };
  const panel = el("div", "task-proposal");
  add(panel,
    el("div", "eyebrow", run.status === "approved" ? "РЕШЕНИЕ ПО ЗАДАЧЕ" : "ПРЕДЛОЖЕНИЕ · ЕЩЁ НЕ ПРИМЕНЕНО"),
    el("h3", "", actions[data.action] || data.action),
    data.title && el("p", "proposal-title", data.title));
  const facts = el("dl", "proposal-facts");
  for (const [label, value] of [["Сообщение", data.event_id], ["Проект", data.project_id], ["Задача", data.task_id || (data.action === "create" ? "Новая, после одобрения" : "Не указана")], ["Ответственный", personName(data.owner || "Не определён")], ["Состояние", taskStatusTitles[data.status] || data.status || "Не меняется"], ["Срок", dateOnly(data.due_date)], ["Проверяемая версия задачи", data.base_version ?? "Новая задача / без изменения"]]) add(facts, el("dt", "", label), el("dd", "", value));
  panel.append(facts);
  if (data.blocked_by) add(panel, el("p", "task-blocker", `Препятствие: ${data.blocked_by}`));
  if (data.question) add(panel, definition("Вопрос человеку.", data.question, true));
  if (data.source_refs?.length) add(panel, el("p", "field-hint", "Источники, на которых основано предложение"), sourceChips(data.source_refs));
  if (run.status === "approved") add(panel, link("Проверить общую доску →", "#processes", "button text spaced"));
  else add(panel, el("p", "field-hint", "Текст ниже объясняет предложение. Поля выше определяют, какое изменение задачи будет применено при одобрении."));
  return panel;
}

const skillExamples = {
  "explain-process": "Объясни, как устроена работа по проекту «Орбита»: кто за что отвечает, что уже готово, что мешает и кто принимает решение о запуске.",
  "meeting-actions": "Итоги встречи по проекту «Орбита»: макеты приняты. Марк собирает недостающие тексты у клиента. Ольга начнёт сборку после получения текстов. Дату запуска нужно согласовать с Анной. Выдели предлагаемые действия, ответственных и открытые вопросы.",
  "daily-brief": "Подготовь сводку по проектам «Орбита» и «Контур»: текущее состояние, что требует внимания, кто отвечает и какие решения нужны от руководителя.",
};
function useSkill(skill) {
  if (state.busy) return;
  state.commandPreset = { skill: skill.name, request: skillExamples[skill.name] || "" };
  if (location.hash === "#overview") renderRoute();
  else location.hash = "overview";
}
function commandPanel() {
  const panel = el("section", "panel command-panel");
  panel.id = "system-command";
  add(panel, add(el("div", "composer-heading"), add(el("span", "composer-symbol"), icon("skills")), el("h2", "", "Что сделаем сегодня?")), el("p", "", "Задайте вопрос или поручите работу. Помощник использует доступные вам знания и сохранённые способы работы."));
  const agent = state.bootstrap.agents.find(item => item.name === "work-assistant");
  if (!agent?.allowed) {
    add(panel, el("p", "field-hint spaced", "Эта роль не может давать поручения помощнику. Доступные части системы показаны ниже."));
    return panel;
  }
  const form = el("form");
  form.id = "system-command-form";
  const label = el("label", "field-label", "Что нужно сделать?");
  label.htmlFor = "system-request";
  const input = el("textarea");
  input.id = "system-request";
  input.required = true;
  input.minLength = 5;
  input.maxLength = 10000;
  input.placeholder = "Например: кто утверждает срок проекта «Орбита» и что нужно для решения?";
  const examples = el("div", "command-examples");
  for (const [title, name] of [["Разобраться в проекте", "explain-process"], ["Итоги встречи", "meeting-actions"], ["Сводка по проектам", "daily-brief"]]) {
    const available = state.bootstrap.skills.some(skill => skill.name === name && skill.execution === "draft" && (skill.roles || []).includes(state.bootstrap.person.role));
    if (!available) continue;
    examples.append(button(title, () => { input.value = skillExamples[name]; skillSelect.value = name; skillChoice.open = true; input.focus(); }, "command-example"));
  }
  const skillChoice = el("details", "command-skill-choice");
  const skillLabel = el("label", "field-label", "Сохранённый способ работы");
  skillLabel.htmlFor = "system-skill";
  const skillSelect = el("select");
  skillSelect.id = "system-skill";
  const auto = el("option", "", "Выбрать автоматически");
  auto.value = "auto";
  skillSelect.append(auto);
  for (const skill of state.bootstrap.skills.filter(item => item.execution === "draft" && (item.roles || []).includes(state.bootstrap.person.role))) {
    const option = el("option", "", skill.title || skillTitles[skill.name] || skill.name);
    option.value = skill.name;
    skillSelect.append(option);
  }
  add(skillChoice, el("summary", "", "Способ работы: автоматически или вручную"), skillLabel, skillSelect);
  if (state.commandPreset && [...skillSelect.options].some(option => option.value === state.commandPreset.skill)) {
    input.value = state.commandPreset.request;
    skillSelect.value = state.commandPreset.skill;
    skillChoice.open = true;
  }
  const error = el("p", "form-error");
  error.setAttribute("role", "alert");
  const submit = button("Выполнить поручение", null, "primary");
  submit.type = "submit";
  submit.id = "system-submit";
  add(form, label, input, examples, skillChoice, error, add(el("div", "form-actions"), submit, el("span", "field-hint", "Ответ и источники сохранятся в журнале. Изменения задач согласуются отдельно.")));
  let requestId = null;
  let previous = null;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (state.busy || !form.reportValidity()) return;
    const request = input.value.trim();
    if (!request) return;
    const inputData = { request, skill: skillSelect.value, project_id: "all" };
    const fingerprint = JSON.stringify(inputData);
    if (fingerprint !== previous) { requestId = crypto.randomUUID(); previous = fingerprint; }
    state.busy = true;
    $("#person-select").disabled = true;
    error.textContent = "";
    submit.disabled = true;
    submit.textContent = "Подбираем способ работы…";
    announce("Помощник выбирает скилл и работает с разрешёнными источниками.");
    try {
      const run = await api("/api/runs", { method: "POST", body: JSON.stringify({ agent: "work-assistant", input: inputData, request_id: requestId }) });
      location.hash = `run/${encodeURIComponent(run.id)}`;
    } catch (err) { error.textContent = err.message; }
    finally { state.busy = false; $("#person-select").disabled = !state.bootstrap.demo; submit.disabled = false; submit.textContent = "Выполнить поручение"; }
  });
  add(panel, form);
  return panel;
}
function assistantRoute(run) {
  const data = run.output;
  const panel = el("div", "task-proposal");
  const skill = state.bootstrap.skills.find(item => item.name === data.selected_skill);
  add(panel, el("div", "eyebrow", "ВЫБРАННЫЙ СПОСОБ РАБОТЫ"), el("h3", "", skill?.title || skillTitles[data.selected_skill] || data.selected_skill || "Способ не выбран"), el("p", "field-hint", "Этот запуск подготовил ответ. Общая доска задач не менялась."));
  if (data.source_refs?.length) add(panel, el("p", "field-hint", "Основания ответа"), sourceChips(data.source_refs));
  if (data.missing_capability) add(panel, definition("Чего пока не хватает.", data.missing_capability, true));
  const next = state.bootstrap.agents.find(item => item.name === data.suggested_agent);
  if (next) {
    const input = data.suggested_input || {};
    add(panel, el("h3", "spaced", `Следующий процесс: ${titleForAgent(next.name)}`), el("p", "", "Помощник предложил маршрут. Отдельный запуск начнётся только по кнопке ниже."));
    for (const [key, value] of Object.entries(input)) add(panel, el("p", "field-hint", `${fieldTitles[key] || key}: ${value}`));
    if (next.allowed) {
      const start = button(`Запустить: ${titleForAgent(next.name)} ↗`, event => withButton(event.currentTarget, async () => {
        if (state.busy) return;
        state.busy = true;
        $("#person-select").disabled = true;
        try {
          const result = await api("/api/runs", { method: "POST", body: JSON.stringify({ agent: next.name, input, request_id: crypto.randomUUID() }) });
          location.hash = `run/${encodeURIComponent(result.id)}`;
        } finally { state.busy = false; $("#person-select").disabled = !state.bootstrap.demo; }
      }, "Выполняем процесс…"), "primary spaced");
      start.id = "launch-suggested-agent";
      panel.append(start);
    } else add(panel, el("p", "field-hint", "Вашей роли запуск этого процесса недоступен."));
  }
  return panel;
}

function quickAction(title, copy, route, symbol) {
  const card = link("", route, "quick-action");
  add(card, add(el("span", "quick-action-icon"), icon(symbol)), add(el("span", "quick-action-copy"), el("strong", "", title), el("span", "", copy)), el("span", "action-arrow", "↗"));
  return card;
}
async function overviewPage() {
  const workspace = await workspaceData();
  const root = el("div", "overview-page");
  const b = state.bootstrap;
  const intro = add(el("div", "desk-heading"), add(el("div"), el("div", "eyebrow", "ЛЮДИ + АГЕНТЫ · ОБЩАЯ РАБОТА"), el("h1", "", "Рабочее пространство"), el("p", "", "Поручайте работу, используйте знания команды и принимайте решения в одном месте.")), link("Команда и цели", "#people", "button small"));
  root.append(intro);
  const actions = add(el("aside", "desk-actions"), el("div", "eyebrow", "ГОТОВО К РАБОТЕ"));
  if (b.agents.some(agent => agent.name === "task-intake" && agent.allowed)) actions.append(quickAction("Разобрать входящие", "Превратить сообщение в предложение задачи", "#processes", "processes"));
  if (b.agents.some(agent => agent.name === "daily-brief" && agent.allowed)) actions.append(quickAction("Собрать сводку", "Увидеть состояние проектов и открытые вопросы", "#agent/daily-brief", "runs"));
  actions.append(quickAction("Посмотреть скиллы", "Выбрать готовый способ работы", "#skills", "skills"));
  add(actions, add(el("div", "desk-note"), el("strong", "", "Вы определяете границы"), el("p", "", "Агенты работают с доступными вам знаниями. Предложения по задачам проверяет и утверждает Анна.")));
  add(root, add(el("div", "desk-grid"), commandPanel(), actions));
  if (workspace) {
    add(root, sectionHeading("Работа команды", "Текущее состояние проектов"), workspaceSummary(workspace));
    const projects = el("div", "project-grid");
    for (const project of workspace.projects) {
      const id = project.id || project.data?.project_id;
      const tasks = workspace.tasks.filter(task => task.project_id === id);
      const active = tasks.filter(task => !taskDone(task)).length;
      const card = add(el("article", "project-card"), add(el("div", "card-top"), add(el("div", "project-heading"), el("span", "project-monogram", (project.data?.name || project.title || "П").slice(0, 1)), add(el("div"), el("h3", "", project.data?.name || project.title), el("p", "", project.title))), badge(project.data?.status || "Проект", "neutral")), add(el("div", "project-meta"), el("span", "", `Координатор: ${personName(project.data?.coordinator || project.owner)}`), el("span", "", `Открытых задач: ${active}`)), link("Открыть входящие и задачи →", "#processes", "button text"));
      projects.append(card);
    }
    root.append(projects);
  } else root.append(workspaceSummary(workspace));
  const counts = [`${b.people.length} сотрудников`, `${Object.keys(b.roles).length} роли`, `${b.sections.reduce((sum, section) => sum + section.count, 0)} доступных записей`, `${b.skills.length} способов работы`, `${b.agents.length} агента`, "Разрешённые действия", "Входящие и задачи", "Результаты и история", "Решения и улучшения"];
  add(root, sectionHeading("Девять слоёв вашей системы", "Откройте слой, чтобы увидеть, как он устроен"));
  const grid = el("div", "layer-grid");
  layers.forEach((layer, i) => {
    const card = link("", `#${layer.id}`, "layer-card");
    add(card, add(el("div", "layer-top"), el("span", "layer-index", String(i + 1).padStart(2, "0")), icon(layer.id, "ui-icon layer-icon")), el("h3", "", layer.title), el("p", "", layer.description), add(el("div", "layer-meta"), el("span", "", counts[i]), el("span", "", "↗")));
    grid.append(card);
  });
  root.append(grid);
  return root;
}
function peoplePage() {
  const b = state.bootstrap;
  const goals = b.goals || {};
  const root = el("div");
  add(
    root,
    heading(
      "Команда и цели",
      "У процесса есть цель и человек, который отвечает за результат. AI помогает выполнить работу в заданных границах.",
      1,
    ),
  );
  const panels = el("div", "grid-two");
  const purpose = add(
    el("section", "panel ink"),
    el("div", "eyebrow", "ЦЕЛЬ СИСТЕМЫ"),
    el("h2", "", goals.purpose || "Цель ещё не задана в конфигурации"),
    el("p", "", goals.company || "Учебная компания"),
  );
  if (goals.owner)
    purpose.append(
      el("p", "", `Владелец результата: ${personName(goals.owner)}.`),
    );
  const criteria = add(
    el("section", "panel"),
    el("h2", "", "Как понять, что получилось"),
  );
  const list = el("ul", "list-clean");
  for (const criterion of goals.success_criteria || [])
    list.append(el("li", "", criterion));
  criteria.append(
    list.children.length
      ? list
      : el("p", "", "Критерии нужно определить в config/goals.yaml."),
  );
  add(panels, purpose, criteria);
  add(
    root,
    panels,
    sectionHeading("Учебная команда", "Вымышленные сотрудники"),
  );
  const grid = el("div", "people-grid");
  for (const person of b.people) {
    const card = el("article", "person-card");
    add(
      card,
      add(
        el("div", "person-top"),
        el("span", "avatar", person.name.slice(0, 1)),
        add(
          el("div"),
          el("h3", "", person.name),
          el("p", "", person.position || roleTitle(person.role)),
        ),
      ),
      badge(roleTitle(person.role)),
      person.id === b.person.id &&
        el("p", "", "Сейчас вы смотрите систему от имени этого сотрудника."),
    );
    grid.append(card);
  }
  add(
    root,
    grid,
    definition(
      "Владелец результата",
      "человек, который отвечает за качество и окончательное решение. Назначение агента исполнителем не передаёт ему полномочия владельца.",
    ),
  );
  return root;
}
function rolesPage() {
  const root = el("div");
  const b = state.bootstrap;
  add(
    root,
    heading(
      "Роли и полномочия",
      "Роль определяет доступ к сведениям, запуску агентов и согласованию. Проверка выполняется платформой при каждом запросе.",
      2,
    ),
    definition(
      "Роль",
      "набор разрешённых действий. Сотрудник получает роль; агент работает с доступом сотрудника, который его запустил.",
    ),
  );
  const table = el("table");
  add(
    table,
    add(
      el("thead"),
      add(
        el("tr"),
        ["Роль", "Доступные разделы", "Запуск агентов", "Решение"].map((text) =>
          el("th", "", text),
        ),
      ),
    ),
  );
  const body = el("tbody");
  for (const [id, role] of Object.entries(b.roles)) {
    const agents = b.agents.filter((agent) => agent.roles.includes(id));
    add(
      body,
      add(
        el("tr"),
        add(
          el("td"),
          el("strong", "", role.title),
          el("p", "", role.description || ""),
          id === b.person.role && badge("Текущая роль"),
        ),
        add(
          el("td"),
          chipList(role.sections || [], (name) => sectionTitles[name] || name),
        ),
        el(
          "td",
          "",
          agents.map((agent) => titleForAgent(agent.name)).join(", ") ||
            "Не разрешён",
        ),
        el(
          "td",
          "",
          role.can_approve ? "Может одобрять версии" : "Без права одобрения",
        ),
      ),
    );
  }
  add(table, body);
  add(
    root,
    add(el("div", "table-wrap"), table),
    sectionHeading("Две проверки доступа"),
    add(
      el("div", "grid-two"),
      add(
        el("section", "panel"),
        el("h3", "", "1. Что разрешено человеку"),
        el(
          "p",
          "",
          "Платформа проверяет его роль и доступ к отдельным записям. Закрытые финансовые сведения хранятся отдельно от рабочих данных проекта.",
        ),
      ),
      add(
        el("section", "panel"),
        el("h3", "", "2. Что нужно агенту"),
        el(
          "p",
          "",
          "Агент заранее объявляет разделы знаний. Даже доступный человеку раздел нельзя получить, если он не заявлен в настройках агента.",
        ),
      ),
    ),
  );
  return root;
}

async function knowledgePage() {
  const root = el("div");
  const actions = [];
  if (isCEO())
    actions.push(
      button("Синхронизировать файлы", (event) =>
        withButton(
          event.currentTarget,
          async () => {
            clearError();
            const result = await api("/api/sync", { method: "POST" });
            state.bootstrap = await api("/api/bootstrap");
            updateHeader();
            await renderRoute();
            announce(result.message || `Загружено записей: ${result.count}`);
          },
          "Синхронизируем…",
        ),
      ),
    );
  add(
    root,
    heading(
      "Знания команды",
      "Проекты, правила и другие сведения, которыми пользуются люди и агенты. Ваша роль определяет, какие записи доступны.",
      3,
      actions,
    ),
  );
  const form = el("form", "toolbar");
  form.id = "knowledge-search-form";
  const queryField = el("div", "search-field");
  const qlabel = el("label", "field-label", "Вопрос или ключевые слова");
  qlabel.htmlFor = "knowledge-query";
  const query = el("input");
  query.id = "knowledge-query";
  query.type = "search";
  query.placeholder = "Например: перенос запуска";
  add(queryField, qlabel, query);
  const selectField = el("div", "select-field");
  const slabel = el("label", "field-label", "Раздел");
  slabel.htmlFor = "knowledge-section";
  const select = el("select");
  select.id = "knowledge-section";
  const all = el("option", "", "Все разделы");
  all.value = "";
  select.append(all);
  for (const section of state.bootstrap.sections) {
    const option = el(
      "option",
      "",
      section.title || sectionTitles[section.name] || section.name,
    );
    option.value = section.name;
    select.append(option);
  }
  add(selectField, slabel, select);
  const submit = button("Найти");
  submit.type = "submit";
  add(form, queryField, selectField, submit);
  root.append(form);
  const results = el("div");
  results.id = "knowledge-results";
  results.setAttribute("aria-live", "polite");
  root.append(results);
  let searchSequence = 0;
  async function search() {
    const current = ++searchSequence;
    const params = new URLSearchParams({ q: query.value.trim() });
    if (select.value) params.set("section", select.value);
    const data = await api(`/api/knowledge?${params}`);
    if (current !== searchSequence) return;
    results.replaceChildren(
      el(
        "p",
        "count-line",
        `Найдено записей: ${data.records.length}. Скрыто вашей ролью: ${data.hidden_count || 0}. Названия и содержимое скрытых записей не передаются.`,
      ),
    );
    for (const record of data.records) {
      const details = el("details", "record");
      add(
        details,
        add(
          el("summary"),
          add(
            el("div"),
            el("h3", "", record.title),
            el(
              "p",
              "",
              `${sectionTitles[record.section] || record.section} · Владелец: ${personName(record.owner)} · Обновлено: ${record.updated}`,
            ),
          ),
        ),
        add(
          el("div", "record-body"),
          markdown(record.content),
          el(
            "p",
            "record-meta",
            `Источник: ${record.id} · Версия: ${record.version}`,
          ),
        ),
      );
      results.append(details);
    }
    if (!data.records.length)
      results.append(
        empty(
          "Совпадений нет",
          "Попробуйте другое слово или раздел. Поиск по словам может не распознать перефразировку.",
        ),
      );
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    withButton(submit, search, "Ищем…");
  });
  await search();
  add(
    root,
    definition(
      "RAG — поиск перед ответом.",
      "Агент сначала получает подходящие фрагменты, затем использует их для ответа. Здесь работает полнотекстовый поиск PostgreSQL — поиск по словам. Семантический поиск по смыслу можно добавить позже.",
    ),
  );
  return root;
}
function skillsPage() {
  const root = el("div");
  add(
    root,
    heading(
      "Скиллы команды",
      "Скилл — сохранённый способ работы. Выберите готовый скилл, откройте пример поручения и получите результат по знаниям команды.",
      4,
    ),
  );
  const grid = el("div", "grid-two skill-grid");
  const skillOrder = ["explain-process", "meeting-actions", "daily-brief"];
  const orderedSkills = [...state.bootstrap.skills].sort((a, b) => (skillOrder.includes(a.name) ? skillOrder.indexOf(a.name) : 10) - (skillOrder.includes(b.name) ? skillOrder.indexOf(b.name) : 10));
  for (const skill of orderedSkills) {
    const card = el("section", "panel skill-card");
    card.dataset.skill = skill.name;
    add(
      card,
      add(el("div", "skill-card-top"), add(el("span", "skill-card-icon"), icon("skills")), badge(skill.execution === "draft" ? "Готов к запуску" : "Инструкция процесса", skill.execution === "draft" ? "" : "neutral")),
      el("h3", "", skill.title || skillTitles[skill.name] || skill.name),
      el("p", "", skill.description),
    );
    const boundAgents = state.bootstrap.agents.filter((agent) =>
      (agent.skills || []).includes(skill.name) || (agent.name === "work-assistant" && skill.execution === "draft"),
    );
    add(
      card,
      el(
        "p",
        "field-hint",
        boundAgents.length
          ? `Подключён к агентам: ${boundAgents.map((agent) => titleForAgent(agent.name)).join(", ")}.`
          : "Инструкция для человека. Автоматический вызов агентом не настроен.",
      ),
    );
    const canUse = skill.execution === "draft" && (skill.roles || []).includes(state.bootstrap.person.role) && state.bootstrap.agents.some(agent => agent.name === "work-assistant" && agent.allowed);
    if (canUse) {
      const use = button("Использовать", () => useSkill(skill), "primary");
      use.dataset.useSkill = skill.name;
      card.append(add(el("div", "skill-action"), use, el("span", "field-hint", "Откроется пример поручения")));
    } else if (skill.execution === "draft") card.append(badge("Запуск недоступен вашей роли", "neutral"));
    else if (skill.name === "task-intake" && boundAgents.some(agent => agent.allowed)) card.append(link("Открыть входящие →", "#processes", "button"));
    if (skill.context?.length) card.append(chipList(skill.context, section => sectionTitles[section] || section));
    if (skill.content) {
      const method = el("details", "record spaced");
      add(
        method,
        add(el("summary"), el("h3", "", "Открыть способ работы")),
        add(
          el("div", "record-body"),
          markdown(skill.content),
          skill.version && el("p", "record-meta", `Версия: ${skill.version}`),
        ),
      );
      card.append(method);
    }

    grid.append(card);
  }
  if (!state.bootstrap.skills.length)
    grid.append(
      empty(
        "Скиллы ещё не добавлены",
        "Добавьте проверенную инструкцию в конфигурацию системы.",
      ),
    );
  add(
    root,
    grid,
    definition(
      "Инструкция и исполнитель — разные части.",
      "Скилл объясняет способ работы. Агент — программа, которая выполняет действия. Сохранённый файл инструкции сам по себе не доказывает, что агент прочитал и применил его.",
    ),
    add(
      el("section", "panel spaced"),
      el("h2", "", "Когда оформлять новый скилл"),
      keyList([
        [
          "Способ уже проверен",
          "Есть пример полезного результата и понятные проверки.",
        ],
        [
          "Задача повторяется",
          "Одну инструкцию можно применять к разным проектам и сообщениям.",
        ],
        [
          "Границы сформулированы",
          "Указано, когда остановиться и какой вопрос задать человеку.",
        ],
      ]),
    ),
  );
  return root;
}
const agentContracts = {
  "work-assistant": { input: "Ваш вопрос или поручение", output: "Ответ, источники и предложенный следующий шаг" },
  "task-intake": { input: "Сообщение из входящих", output: "Предложение: создать задачу, обновить её или уточнить у человека" },
  "daily-brief": { input: "Один проект или вся команда", output: "Сводка: состояние, препятствия, вопросы и следующие действия" },
};
function agentsPage() {
  const root = el("div");
  add(
    root,
    heading(
      "Агенты и модели",
      "Агент — отдельная программа. Он получает входные данные, использует разрешённые инструменты и возвращает результат согласованного формата.",
      5,
    ),
  );
  const grid = el("div", "agent-grid");
  for (const agent of state.bootstrap.agents) {
    const card = el(
      "article",
      `panel agent-card${agent.allowed ? "" : " disabled"}`,
    );
    add(
      card,
      add(
        el("div", "card-top"),
        el("h3", "", titleForAgent(agent.name)),
        badge(
          agent.allowed ? "Доступен" : "Нет доступа",
          agent.allowed ? "" : "neutral",
        ),
      ),
      el("div", "agent-code", `${agent.name} / ${agent.version}`),
      el("p", "", agent.description),
      add(
        el("div", "agent-contract"),
        add(
          el("div"),
          el("strong", "", "ВХОД"),
          document.createTextNode(
            agentContracts[agent.name]?.input || Object.keys(agent.input.properties || {})
              .map((key) => fieldTitles[key] || key)
              .join(", "),
          ),
        ),
        add(
          el("div"),
          el("strong", "", "ВЫХОД"),
          document.createTextNode(
            agentContracts[agent.name]?.output || Object.keys(agent.output.properties || {})
              .map((key) => fieldTitles[key] || key)
              .join(", "),
          ),
        ),
      ),
      chipList(
        agent.context || [],
        (section) => sectionTitles[section] || section,
      ),
    );
    if (agent.skills?.length)
      card.append(
        el(
          "p",
          "field-hint",
          `Скиллы: ${agent.skills.map((name) => skillTitles[name] || name).join(", ")}.`,
        ),
      );
    if (agent.metrics) {
      const metrics = el("div", "agent-metrics");
      add(
        metrics,
        el("span", "", `Запусков: ${agent.metrics.runs}`),
        el("span", "", `Оценка стоимости: ${money(agent.metrics.cost_usd)}`),
      );
      add(
        card,
        metrics,
        el(
          "p",
          "field-hint",
          "По всем запускам, доступным вашей роли. Обновляется при открытии раздела.",
        ),
      );
    }
    if (agent.allowed)
      card.append(
        link(
          "Открыть и запустить ↗",
          `#agent/${encodeURIComponent(agent.name)}`,
          "button primary",
        ),
      );
    else {
      const denied = button("Недоступен вашей роли");
      denied.disabled = true;
      card.append(denied);
    }
    grid.append(card);
  }
  add(
    root,
    grid,
    sectionHeading("Агент предлагает. Программа проверяет. Человек решает."),
    cliStatusPanel(),
    definition(
      "Контракт «вход → выход»",
      "это описание допустимых полей и типов данных. JSON Schema — формат такого описания; по нему система строит форму и проверяет ответ агента.",
    ),
    definition(
      "Токены модели",
      "небольшие части текста, которыми измеряется объём запроса и ответа. CLI использует авторизованный аккаунт. Стоимость отдельного запуска по подписке не вычисляется; объём показывается только если CLI его вернул.",
    ),
  );
  return root;
}

function schemaFieldIssue(schema) {
  if (!schema || typeof schema !== "object" || Array.isArray(schema))
    return "Описание поля должно быть объектом JSON Schema.";
  if (
    schema.nullable === true ||
    Array.isArray(schema.type) ||
    ["$ref", "anyOf", "oneOf", "allOf"].some((key) => key in schema)
  )
    return "Форма пока не поддерживает nullable-поля (значение может быть null), объединения типов и ссылки на другие схемы.";
  if (
    !["string", "number", "integer", "boolean", "object", "array"].includes(
      schema.type,
    )
  )
    return "Укажите один поддерживаемый тип: string, number, integer, boolean, object или array.";
  return null;
}

function createSchemaField(key, schema, required) {
  const wrap = el("div");
  const issue = schemaFieldIssue(schema);
  const fieldSchema = schema && typeof schema === "object" ? schema : {};
  const label = el(
    "label",
    "field-label",
    fieldTitles[key] || fieldSchema.title || key,
  );
  label.htmlFor = `input-${key}`;
  if (required) label.append(el("span", "field-required", "*"));
  if (issue) {
    add(wrap, label, el("p", "form-error", issue));
    return { wrap, input: null, schema: fieldSchema, key, required, issue };
  }
  let input;
  if (schema.enum) {
    input = el("select");
    for (const value of schema.enum) {
      const title =
        key === "project_id" && value === "all"
          ? "Все проекты"
          : value === "ru"
          ? "Русский"
          : value === true
            ? "Да"
            : value === false
              ? "Нет"
              : typeof value === "object"
                ? JSON.stringify(value)
                : String(value);
      const option = el("option", "", title);
      // Строка "false" и логическое false должны оставаться разными значениями.
      option.value = JSON.stringify(value);
      input.append(option);
    }
  } else if (schema.type === "boolean") {
    input = el("input");
    input.type = "checkbox";
  } else if (schema.type === "number" || schema.type === "integer") {
    input = el("input");
    input.type = "number";
    input.step = schema.type === "integer" ? "1" : "any";
    if (schema.minimum !== undefined) input.min = schema.minimum;
    if (schema.maximum !== undefined) input.max = schema.maximum;
  } else if (
    key === "task" || key === "request" ||
    schema.type === "object" ||
    schema.type === "array"
  )
    input = el("textarea");
  else {
    input = el("input");
    input.type = "text";
  }
  input.id = `input-${key}`;
  input.name = key;
  // JSON Schema требует наличия boolean, а HTML required требует именно true.
  input.required = required && input.type !== "checkbox";
  if (schema.minLength) input.minLength = schema.minLength;
  if (schema.maxLength) input.maxLength = schema.maxLength;
  if (schema.default !== undefined) {
    if (input.type === "checkbox") input.checked = schema.default === true;
    else if (schema.enum || schema.type === "object" || schema.type === "array")
      input.value = JSON.stringify(schema.default, null, schema.enum ? 0 : 2);
    else input.value = schema.default;
  }
  const placeholders = {
    event_id: "Например: E001",
    project_id: "Все проекты — all, отдельный — P01 или P02",
    client: "Точное название клиента из базы знаний",
    task: "Какой результат нужен и что уже известно?",
    request: "Что нужно сделать? Укажите результат и ограничения.",
    deadline: "Например: до конца следующего месяца",
    budget: "Необязательно",
  };
  if (placeholders[key]) input.placeholder = placeholders[key];
  add(wrap, label, input);
  const hint =
    key === "skill"
      ? "auto — помощник сам выберет подходящий скилл. Для точного выбора укажите его имя из раздела «Скиллы»."
      : key === "budget"
      ? "Бюджет — ограничение клиента. Он не меняет цену услуг из каталога."
      : key === "deadline"
        ? "Желаемая дата учитывается как запрос, а не как обещание."
        : schema.description;
  if (hint) wrap.append(el("p", "field-hint", hint));
  return { wrap, input, schema, key, required, issue: null };
}
function agentPage(name) {
  const agent = state.bootstrap.agents.find((item) => item.name === name);
  if (!agent)
    return empty(
      "Агент не найден",
      "Откройте список исполнителей.",
      link("К агентам", "#agents", "button primary"),
    );
  const root = el("div");
  add(
    root,
    heading(titleForAgent(agent.name), agent.description, 5, [
      link("← Все агенты", "#agents", "button"),
    ]),
  );
  if (!agent.allowed) {
    root.append(
      empty(
        "Запуск недоступен",
        `Ваша роль «${roleTitle(state.bootstrap.person.role)}» не может запускать этого агента. Платформа также проверяет это на сервере.`,
      ),
    );
    return root;
  }
  const layout = el("div", "form-layout");
  const panel = el("section", "panel");
  const form = el("form", "agent-form");
  form.id = "agent-run-form";
  const fields = Object.entries(agent.input.properties || {}).map(
    ([key, schema]) =>
      createSchemaField(
        key,
        schema,
        (agent.input.required || []).includes(key),
      ),
  );
  fields.forEach((field) => form.append(field.wrap));
  const error = el("p", "form-error");
  error.setAttribute("role", "alert");
  const submit = button("Запустить агента ↗", null, "primary");
  submit.type = "submit";
  submit.id = "run-agent-button";
  const unsupportedFields = fields.filter((field) => field.issue);
  const unsupportedSchema =
    schemaFieldIssue(agent.input) ||
    (agent.input.type !== "object"
      ? "Форма поддерживает входной объект с именованными полями."
      : null);
  if (unsupportedSchema || unsupportedFields.length) {
    submit.disabled = true;
    const reason =
      unsupportedSchema ||
      `Форма не может представить поля: ${unsupportedFields.map((field) => field.key).join(", ")}.`;
    error.textContent = `${reason} Используйте Run API (/api/runs) с JSON-входом либо задайте в agent.yaml простую поддерживаемую схему.`;
  }
  add(
    form,
    error,
    add(
      el("div", "form-actions"),
      submit,
      el("span", "field-hint", "Результат сохранится в журнале"),
    ),
  );
  panel.append(form);
  let requestId = null;
  let previousInput = null;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (
      state.busy ||
      unsupportedSchema ||
      unsupportedFields.length ||
      !form.reportValidity()
    )
      return;
    clearError();
    error.textContent = "";
    const input = {};
    try {
      for (const field of fields) {
        const value = field.input.value;
        if (!value && !field.required && field.schema.type !== "boolean")
          continue;
        if (field.schema.enum) input[field.key] = JSON.parse(value);
        else if (
          field.schema.type === "number" ||
          field.schema.type === "integer"
        )
          input[field.key] = Number(value);
        else if (field.schema.type === "boolean")
          input[field.key] = field.input.checked;
        else if (
          field.schema.type === "array" ||
          field.schema.type === "object"
        )
          input[field.key] = JSON.parse(value);
        else input[field.key] = value.trim();
      }
    } catch (_) {
      error.textContent =
        "Проверьте сложные поля: массивы и объекты должны быть записаны в формате JSON.";
      return;
    }
    const fingerprint = JSON.stringify(input);
    if (fingerprint !== previousInput) {
      requestId = crypto.randomUUID
        ? crypto.randomUUID()
        : `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      previousInput = fingerprint;
    }
    state.busy = true;
    $("#person-select").disabled = true;
    submit.disabled = true;
    submit.textContent = "Агент выполняет задачу…";
    announce("Запуск выполняется. Результат будет сохранён в журнале.");
    try {
      const run = await api("/api/runs", {
        method: "POST",
        body: JSON.stringify({
          agent: agent.name,
          input,
          request_id: requestId,
        }),
      });
      location.hash = `run/${encodeURIComponent(run.id)}`;
    } catch (err) {
      error.textContent = err.message;
      announce(err.message);
    } finally {
      state.busy = false;
      $("#person-select").disabled = !state.bootstrap.demo;
      submit.disabled = false;
      submit.textContent = "Запустить агента ↗";
    }
  });
  const side = el("aside", "panel sage");
  add(
    side,
    el("div", "eyebrow", "ПЕРЕД ЗАПУСКОМ"),
    el("h2", "", "Что будет происходить"),
    keyList([
      [
        "1. Проверка входа",
        "Платформа проверит поля и право вашей роли на запуск.",
      ],
      [
        "2. Работа с источниками",
        "Агент получит только разрешённые записи из заявленных разделов.",
      ],
      [
        "3. Выполнение и журнал",
        "Каждый выданный источник и шаг останется в истории.",
      ],
      [
        "4. Решение человека",
        "Готовый результат будет ждать проверки. Автоматической отправки нет.",
      ],
    ]),
    el("p", "spaced", "Доступные агенту разделы:"),
    chipList(agent.context, (section) => sectionTitles[section] || section),
    link("Посмотреть проекты в знаниях →", "#knowledge", "button text spaced"),
  );
  add(layout, panel, side);
  root.append(layout);
  return root;
}

function toolsPage() {
  const root = el("div");
  add(
    root,
    heading(
      "Действия работают в границах",
      "Инструмент выполняет конкретную операцию: найти запись, вызвать модель или сохранить результат. Агент не получает ключи внешних сервисов.",
      6,
    ),
  );
  const cards = [
    [
      "Поиск по знаниям",
      "Context API — интерфейс доступа к знаниям. Проверяет роль человека и разделы, заявленные агентом.",
      "Внутренний инструмент",
      "knowledge",
    ],
    [
      "Доступ к модели",
      "Шлюз модели передаёт запрос авторизованному Claude Code или Codex. Учётная запись остаётся на вашем компьютере; агент получает только ответ.",
      cliTitle(state.bootstrap.cli_worker?.provider),
      "agents",
    ],
    [
      "Запуск и журнал",
      "Run API — интерфейс запуска агентов из приложения или другой программы. Проверяет вход и выход, хранит результат.",
      "Внутренний инструмент",
      "runs",
    ],
  ];
  const grid = el("div", "grid-three");
  for (const [title, description, status, route] of cards)
    add(
      grid,
      add(
        el("section", "panel"),
        el("h3", "", title),
        el("p", "", description),
        add(el("div", "spaced"), badge(status)),
        link("Открыть →", `#${route}`, "button text spaced"),
      ),
    );
  add(
    root,
    grid,
    sectionHeading("Что разрешено в этом каркасе"),
    add(
      el("section", "panel"),
      keyList([
        [
          "Знания и модели — через платформу",
          "Токен запуска — временный ключ на 15 минут, связанный с человеком, его ролью и конкретным агентом. После завершения запуска он недействителен.",
        ],
        [
          "Внешние отправки не подключены",
          "Почта, мессенджеры, оплата и публикация не выполняются. Одобренный результат остаётся локальным.",
        ],
        [
          "Чужие разделы недоступны",
          "Платформа отклонит запрос к разделу, который агент не объявил в своих настройках.",
        ],
        [
          "Синхронизацию запускает руководитель",
          "Только роль руководителя обновляет знания из файлов. Ошибка чтения не должна заменять исправную базу.",
        ],
      ]),
    ),
    definition(
      "API",
      "программный интерфейс: способ попросить сервис выполнить действие без нажатия кнопки в браузере. Те же проверки прав действуют и для такого запроса.",
    ),
  );
  return root;
}
async function processesPage() {
  const [workspace, runs] = await Promise.all([workspaceData(), api("/api/runs")]);
  const root = el("div");
  add(root, heading("Входящие и задачи", "Откройте сообщение и нажмите «Разобрать сообщение». Агент предложит задачу или уточнение. После одобрения Анны изменение появится на доске.", 7, [button("Обновить", renderRoute), link("Собрать сводку ↗", "#agent/daily-brief", "button primary")]));
  if (!workspace) {
    root.append(empty("Рабочая доска недоступна этой роли", "Откройте доступные вам знания или переключитесь на участника проекта в учебном режиме.", link("Знания", "#knowledge", "button")));
    return root;
  }
  root.append(workspaceSummary(workspace));
  const inbox = el("section", "panel workspace-inbox");
  inbox.id = "inbox";
  add(inbox, sectionHeading("Входящие", "Учебные сообщения и итоги встреч"));
  if (!workspace.inbox.length) inbox.append(el("p", "muted", "Доступных сообщений пока нет."));
  for (const message of workspace.inbox) inbox.append(inboxCard(message, workspace));
  const decisions = el("section", "panel decision-queue");
  decisions.id = "decision-queue";
  add(decisions, sectionHeading("Ждут решения Анны", "Предложения по задачам"));
  const pending = (runs.runs || []).filter(run => run.agent === "task-intake" && run.status === "needs_review");
  if (!pending.length) decisions.append(empty("Очередь решений пуста", "После разбора сообщения здесь появится результат для проверки."));
  for (const run of pending) add(decisions, add(el("div", "decision-item"), add(el("div"), el("h3", "", titleForAgent(run.agent)), el("p", "muted", `${personName(run.person_id)} · версия ${run.current_version} · ${formatDate(run.created_at)}`)), link("Проверить →", `#run/${encodeURIComponent(run.id)}`, "button")));
  add(root, add(el("div", "workspace-columns"), inbox, decisions));
  add(root, sectionHeading("Общая доска задач", "Здесь только сохранённые задачи"));
  const board = el("div", "task-board");
  board.id = "task-board";
  const groups = [
    ["planned", "Следующий шаг", task => !taskDone(task) && !taskBlocked(task)],
    ["blocked", "Нужна помощь", task => !taskDone(task) && taskBlocked(task)],
    ["done", "Завершено", task => taskDone(task)],
  ];
  for (const [key, title, filter] of groups) {
    const tasks = workspace.tasks.filter(filter);
    const column = el("section", `task-column task-column-${key}`);
    add(column, add(el("div", "task-column-title"), el("h3", "", title), badge(tasks.length, "neutral")));
    if (!tasks.length) column.append(el("p", "muted task-empty", "Задач пока нет"));
    tasks.forEach(task => column.append(taskCard(task, workspace)));
    board.append(column);
  }
  add(root, board, definition("Повторное сообщение не создаёт новую задачу автоматически.", "Платформа различает доставку сообщения, предложение агента и одобренное изменение. Для обновления проверяется версия существующей задачи."));
  return root;
}

async function runsPage() {
  const data = await api("/api/runs");
  const root = el("div");
  add(
    root,
    heading(
      "Работа оставляет след",
      "Запуски сохраняются вместе с входом, использованными источниками, шагами и версиями результата. Вы видите свои запуски; руководитель — все.",
      8,
      [
        button("Обновить журнал", renderRoute),
        link("Новый запуск ↗", "#agents", "button primary"),
      ],
    ),
  );
  if (!data.runs.length) {
    root.append(
      empty(
        "Пока ни одного запуска",
        "Откройте входящее сообщение или запустите сводку руководителя. Здесь появится настоящий ход работы.",
        link("Выбрать агента", "#agents", "button primary"),
      ),
    );
    return root;
  }
  const table = el("table", "runs-table");
  add(
    table,
    add(
      el("thead"),
      add(
        el("tr"),
        [
          "Агент / запуск",
          "Инициатор",
          "Состояние",
          "Создан",
          "Оценка стоимости",
        ].map((text) => el("th", "", text)),
      ),
    ),
  );
  const body = el("tbody");
  for (const run of data.runs) {
    const cell = el("td");
    add(
      cell,
      link(titleForAgent(run.agent), `#run/${encodeURIComponent(run.id)}`, ""),
      el("p", "run-id", String(run.id).slice(0, 8)),
      el("p", "", `Версия ${run.current_version ?? "—"}`),
    );
    add(
      body,
      add(
        el("tr"),
        cell,
        el("td", "", personName(run.person_id)),
        add(
          el("td"),
          badge(
            statusTitles[run.status] || run.status,
            statusClass[run.status],
          ),
        ),
        el("td", "", formatDate(run.created_at)),
        add(
          el("td"),
          document.createTextNode(money(run.cost_usd)),
          el("p", "", run.llm_mode === "fixture" ? "Тестовая фикстура" : "Через авторизованный CLI"),
        ),
      ),
    );
  }
  table.append(body);
  add(
    root,
    add(el("div", "table-wrap"), table),
    definition(
      "Состояние",
      "текущая точка процесса: выполняется, ждёт решения, одобрено или завершилось ошибкой. Изменение задачи применяется только при одобрении точной версии; внешних отправок нет.",
    ),
  );
  return root;
}

function tracePanel(run) {
  const panel = el("section", "panel");
  add(
    panel,
    el("div", "eyebrow", "ТРАССИРОВКА"),
    el("h2", "", "Как получен результат"),
    el(
      "p",
      "section-copy",
      "Трассировка — последовательность реально записанных действий этого запуска.",
    ),
  );
  const list = el("ol", "trace spaced");
  const input = el("li");
  const inputDetail = el("details");
  add(
    inputDetail,
    el("summary", "", "Показать входные данные"),
    el("pre", "", pretty(run.input)),
  );
  add(
    input,
    el("h3", "", "Вход"),
    el("p", "", `${personName(run.person_id)} · ${roleTitle(run.role)}`),
    inputDetail,
  );
  list.append(input);
  const context = el("li");
  add(context, el("h3", "", "Контекст — выданные знания"));
  if (!(run.context_events || []).length)
    context.append(el("p", "", "Выдача знаний не зафиксирована."));
  for (const event of run.context_events || []) {
    const block = el("div", "trace-block");
    add(
      block,
      el("strong", "", sectionTitles[event.section] || event.section),
      event.query && el("p", "", `Запрос: ${event.query}`),
    );
    for (const record of event.records || [])
      add(
        block,
        el("p", "", record.title || record.id),
        el(
          "small",
          "",
          `${record.id} · версия ${shortVersion(record.version)}`,
        ),
      );
    if (!event.records?.length) block.append(el("p", "", "Записи не выданы."));
    block.append(el("p", "", `Скрыто ролью: ${event.hidden_count || 0}`));
    context.append(block);
  }
  list.append(context);
  const steps = el("li");
  steps.append(el("h3", "", "Шаги агента"));
  if (!(run.steps || []).length)
    steps.append(el("p", "", "Шаги не получены от агента."));
  for (const step of run.steps || [])
    steps.append(
      add(
        el("div", "trace-block"),
        el("strong", "", typeof step === "string" ? step : step.title || "Шаг"),
        typeof step === "object" &&
          step.detail &&
          el(
            "p",
            "",
            typeof step.detail === "string" ? step.detail : pretty(step.detail),
          ),
      ),
    );
  list.append(steps);
  if (run.model_calls?.length) {
    const models = el("li");
    models.append(el("h3", "", "Обращения к модели"));
    for (const call of run.model_calls) {
      const block = el("div", "trace-block");
      add(
        block,
        el(
          "strong",
          "",
          ({ select_skill: "Выбор способа работы", work_assistant: "Выполнение поручения", classify_message: "Разбор сообщения", task_intake: "Предложение по задаче", daily_brief: "Сводка руководителя", intake: "Разбор сообщения" })[call.purpose] || call.purpose,
        ),
        el(
          "p",
          "",
          `${call.mode === "fixture" ? "Тестовая фикстура" : `${cliTitle(call.provider || call.usage?.provider || call.mode)} · ${call.model || "Модель не указана"}`} · стоимость: ${money(call.cost_usd)}`,
        ),
      );
      if (call.mode === "fixture")
        block.append(
          el("p", "", "Обращения к нейросети нет; токены не расходуются."),
        );
      else {
        block.append(el("p", "", (call.status === "error" || call.status === "running") && !Object.keys(call.usage || {}).length
          ? "CLI не сообщил объём использованных токенов."
          : `Токены: вход ${call.input_tokens ?? "нет данных"}, выход ${call.output_tokens ?? "нет данных"}.`));
        if (call.cost_usd === null || call.cost_usd === undefined) block.append(el("p", "field-hint", "Стоимость по подписке не определена."));
      }
      if (call.status === "error" || call.status === "failed")
        block.append(el("p", "form-error", "Обращение завершилось ошибкой."));
      for (const skill of call.skill_refs || [])
        block.append(
          el(
            "small",
            "",
            `Инструкция: ${skillTitles[skill.name] || skill.name} · версия ${shortVersion(skill.version)}`,
          ),
        );
      models.append(block);
    }
    list.append(models);
  }
  add(
    list,
    add(
      el("li"),
      el("h3", "", "Выход"),
      el(
        "p",
        "",
        run.status === "error"
          ? "Запуск завершился ошибкой. Результат не одобрен."
          : `Версия ${run.current_version}. ${statusTitles[run.status] || run.status}.`,
      ),
    ),
  );
  add(
    panel,
    list,
    definition(
      "Версия источника",
      "отпечаток содержимого на момент чтения. Он помогает установить, на каких данных основан результат.",
    ),
  );
  return panel;
}

async function runPage(id) {
  if (!id) throw new Error("Не указан запуск.");
  const run = await api(`/api/runs/${encodeURIComponent(id)}`);
  const root = el("div");
  add(
    root,
    heading(
      titleForAgent(run.agent),
      `Инициатор: ${personName(run.person_id)}. Создан: ${formatDate(run.created_at)}.`,
      8,
      [link("← Журнал", "#runs", "button"), button("Обновить", renderRoute)],
    ),
    add(
      el("div", "run-top"),
      badge(statusTitles[run.status] || run.status, statusClass[run.status]),
      el("span", "run-id", `Запуск ${run.id}`),
      badge(
        run.llm_mode === "fixture"
          ? "Тестовая фикстура модели"
          : "Реальная модель через CLI",
        "neutral",
      ),
    ),
  );
  const metrics = el("div", "run-metrics");
  const elapsed =
    run.duration_ms === null || run.duration_ms === undefined
      ? "Ещё нет данных"
      : `${(run.duration_ms / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} с`;
  const incompleteUsage = (run.model_calls || []).some(call => call.mode !== "fixture" && ["error", "running"].includes(call.status) && !Object.keys(call.usage || {}).length);
  const tokens =
    incompleteUsage
      ? (run.input_tokens || run.output_tokens ? `${run.input_tokens} / ${run.output_tokens ?? "—"} · не все данные` : "CLI не сообщил")
      : run.llm_mode === "fixture"
      ? "Тестовая подстановка"
      : run.input_tokens === null || run.input_tokens === undefined
        ? "Нет данных"
        : `${run.input_tokens} / ${run.output_tokens ?? "—"}`;
  for (const [label, value] of [
    ["Версия результата", run.current_version || "—"],
    ["Время выполнения", elapsed],
    ["Оценка стоимости", money(run.cost_usd)],
    ["Токены: вход / выход", tokens],
  ])
    add(
      metrics,
      add(el("div", "metric"), el("small", "", label), el("strong", "", value)),
    );
  const executionDetails = el("details", "execution-details panel spaced");
  add(executionDetails, el("summary", "", "Детали выполнения: время, версия и использование модели"), metrics);
  if (run.source_warnings?.length || run.task_state_stale) {
    const warnings = add(
      el("section", "error-panel"),
      el("h3", "", "Основания изменились после запуска"),
      el(
        "p",
        "",
        "Знания или состояние задач уже изменились. Повторный разбор должен учесть актуальные данные перед новым решением.",
      ),
    );
    for (const warning of run.source_warnings || [])
      warnings.append(el("p", "", `${warning.id}: ${warning.reason}`));
    if (run.task_state_stale) warnings.append(el("p", "", "Доска проекта изменилась после подготовки предложения."));
    if (run.agent === "task-intake" && run.status === "needs_review" && !isCEO()) warnings.append(refreshProposalButton(run));
    root.append(warnings);
  }
  if (run.error)
    root.append(
      add(
        el("section", "error-panel"),
        el("h3", "", "Работа остановилась с ошибкой"),
        el(
          "p",
          "",
          typeof run.error === "string" ? run.error : pretty(run.error),
        ),
      ),
    );
  const layout = el("div", "run-layout");
  const left = el("div");
  const resultPanel = el("section", "panel");
  resultPanel.id = "run-result";
  const header = el("div", "result-header");
  const edit = button(run.agent === "task-intake" ? "Изменить пояснение" : "Редактировать", () => startEditing());
  edit.id = "edit-result-button";
  add(
    header,
    el("h2", "", "Результат"),
    run.output?.markdown !== undefined &&
      run.status !== "running" &&
      run.status !== "error" &&
      !(run.agent === "task-intake" && run.status === "approved") &&
      edit,
  );
  resultPanel.append(header);
  if (run.review_feedback) add(resultPanel, definition("Замечание к повторному разбору.", run.review_feedback));
  if (run.agent === "task-intake" && run.output) resultPanel.append(taskProposal(run));
  if (run.agent === "work-assistant" && run.output) resultPanel.append(assistantRoute(run));
  const output = el("div");
  if (run.output?.markdown !== undefined)
    output.append(markdown(run.output.markdown));
  else
    output.append(
      el(
        "p",
        "muted",
        run.status === "running"
          ? "Агент ещё выполняет работу. Обновите страницу результата."
          : "Текст результата отсутствует.",
      ),
    );
  resultPanel.append(output);
  if (run.output && Object.keys(run.output).length) {
    const data = el("details", "record spaced");
    add(
      data,
      add(el("summary"), el("h3", "", "Структурированный результат")),
      add(
        el("div", "record-body"),
        el(
          "pre",
          "code-label",
          pretty(
            Object.fromEntries(
              Object.entries(run.output).filter(([key]) => key !== "markdown"),
            ),
          ),
        ),
      ),
    );
    resultPanel.append(data);
  }
  function startEditing() {
    edit.disabled = true;
    output.replaceChildren();
    const form = el("form");
    const label = el(
      "label",
      "field-label",
      `Редактирование версии ${run.current_version}`,
    );
    label.htmlFor = "result-editor";
    const editor = el("textarea", "editor");
    editor.id = "result-editor";
    editor.value = run.output.markdown;
    editor.required = true;
    const err = el("p", "form-error");
    err.setAttribute("role", "alert");
    const save = button("Сохранить новую версию", null, "primary");
    save.type = "submit";
    save.id = "save-revision-button";
    add(
      form,
      label,
      editor,
      definition(
        "Новая версия требует нового решения.",
        run.agent === "task-intake"
          ? "Старый текст и прежние одобрения останутся в истории. Меняется только пояснение; поля задачи остаются прежними. Чтобы изменить ответственного, срок или действие, нужен новый запуск с исправленными исходными данными."
          : "Старый текст и прежние одобрения останутся в истории. Меняется только текст результата; ссылки на источники и другие поля сохраняются.",
      ),
      err,
      add(
        el("div", "form-actions"),
        save,
        button("Отмена", () => {
          output.replaceChildren(markdown(run.output.markdown));
          edit.disabled = false;
        }),
      ),
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      err.textContent = "";
      save.disabled = true;
      save.textContent = "Сохраняем…";
      try {
        await api(`/api/runs/${encodeURIComponent(run.id)}/revisions`, {
          method: "POST",
          body: JSON.stringify({
            base_version: run.current_version,
            markdown: editor.value,
          }),
        });
        await renderRoute();
        announce("Новая версия сохранена. Её нужно согласовать заново.");
      } catch (error) {
        err.textContent = error.message;
      } finally {
        save.disabled = false;
        save.textContent = "Сохранить новую версию";
      }
    });
    output.append(form);
    editor.focus();
  }
  left.append(resultPanel);
  if (run.agent === "task-intake" && run.status === "needs_review") left.append(proposalRetryPanel(run));
  if (run.status !== "error" && run.status !== "running")
    left.append(approvalPanel(run));
  if (run.versions?.length) {
    const history = el("section", "panel spaced");
    add(history, el("h2", "", "История версий"));
    for (const revision of [...run.versions].reverse()) {
      const item = el("div", "history-item");
      const details = el("details");
      add(
        details,
        el("summary", "", "Показать сохранённый текст"),
        markdown(revision.output?.markdown || "Текст отсутствует."),
      );
      add(
        item,
        el(
          "strong",
          "",
          `Версия ${revision.version}${revision.version === run.current_version ? " · текущая" : ""}`,
        ),
        el(
          "small",
          "",
          `${personName(revision.author)} · ${formatDate(revision.created_at)}`,
        ),
        details,
      );
      history.append(item);
    }
    left.append(history);
  }
  if (run.decisions?.length) {
    const decisions = el("section", "panel spaced");
    decisions.append(el("h2", "", "Решения по этому результату"));
    for (const decision of run.decisions)
      add(
        decisions,
        add(
          el("div", "history-item"),
          el(
            "strong",
            "",
            `Одобрена версия ${decision.version} · ${personName(decision.author)}`,
          ),
          el("p", "", decision.note || "Без комментария"),
          el("small", "", formatDate(decision.created_at)),
        ),
      );
    left.append(decisions);
  }
  if (run.status === "approved" && isCEO()) left.append(learningPanel(run));
  add(layout, left, tracePanel(run));
  root.append(layout);
  root.append(executionDetails);
  return root;
}

function proposalRetryPanel(run) {
  const panel = el("details", "panel spaced proposal-retry");
  panel.id = "proposal-retry";
  panel.append(el("summary", "", "Повторить разбор с замечанием"));
  const form = el("form", "spaced");
  form.id = "proposal-retry-form";
  const label = el("label", "field-label", "Что нужно исправить в предложении?");
  label.htmlFor = "proposal-retry-reason";
  const reason = el("textarea");
  reason.id = "proposal-retry-reason";
  reason.required = true;
  reason.minLength = 5;
  reason.maxLength = 2000;
  reason.placeholder = "Например: проверь, не существует ли уже задача по получению текстов. Объясни, почему выбран этот ответственный.";
  const error = el("p", "form-error");
  error.setAttribute("role", "alert");
  const submit = button("Повторить разбор с замечанием ↗", null, "primary");
  submit.id = "retry-proposal-button";
  submit.type = "submit";
  add(form, label, reason,
    el("p", "field-hint", "Начнётся новый вызов модели с вашим замечанием. Прежнее предложение останется в журнале. Изменения задач по-прежнему требуют решения человека."),
    error, submit);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (state.busy || !form.reportValidity()) return;
    const feedback = reason.value.trim();
    if (feedback.length < 5) { error.textContent = "Опишите замечание хотя бы пятью символами."; return; }
    error.textContent = "";
    state.busy = true;
    $("#person-select").disabled = true;
    submit.disabled = true;
    reason.disabled = true;
    submit.textContent = "Разбираем с учётом замечания…";
    announce("Начат новый разбор с замечанием. Прежний результат сохранён.");
    try {
      const updated = await api("/api/runs", { method: "POST", body: JSON.stringify({ agent: "task-intake", input: run.input, request_id: crypto.randomUUID(), refresh: true, retry_reason: feedback }) });
      location.hash = `run/${encodeURIComponent(updated.id)}`;
    } catch (err) {
      error.textContent = err.message;
      announce(err.message);
    } finally {
      state.busy = false;
      $("#person-select").disabled = !state.bootstrap.demo;
      reason.disabled = false;
      submit.disabled = false;
      submit.textContent = "Повторить разбор с замечанием ↗";
    }
  });
  panel.append(form);
  return panel;
}

function refreshProposalButton(run) {
  const refresh = button("Обновить предложение ↗", event => withButton(event.currentTarget, async () => {
    if (state.busy) return;
    state.busy = true;
    $("#person-select").disabled = true;
    try {
      const updated = await api("/api/runs", { method: "POST", body: JSON.stringify({ agent: "task-intake", input: run.input, request_id: crypto.randomUUID(), refresh: true }) });
      location.hash = `run/${encodeURIComponent(updated.id)}`;
    } finally { state.busy = false; $("#person-select").disabled = !state.bootstrap.demo; }
  }, "Повторно разбираем сообщение…"), "primary spaced");
  refresh.id = "refresh-proposal-button";
  return refresh;
}

function approvalPanel(run) {
  const panel = el("section", "approval-box");
  panel.id = "approval-panel";
  if (run.status === "approved") {
    add(
      panel,
      el("h3", "", `Версия ${run.current_version} одобрена локально`),
      run.task_application && el("p", "", `Применено к задаче ${run.task_application.task_id}, версия ${run.task_application.version}.`),
      el(
        "p",
        "",
        run.agent === "task-intake"
          ? "Решение сохранено для этой версии. Если одобрено создание или обновление задачи, изменение применено к общей доске. Внешних отправок нет."
          : "Согласован текст этой версии. Общая доска задач не менялась, внешних отправок нет.",
      ),
    );
    return panel;
  }
  add(
    panel,
    el("h3", "", "Следующий шаг — решение человека"),
    el(
      "p",
      "",
      run.agent === "task-intake"
        ? "Проверьте основания, ответственное лицо, срок и предлагаемое действие. При одобрении создание или обновление задачи применяется к общей доске. Согласование относится только к текущей версии."
        : "Проверьте факты, источники и текст. Одобрение относится только к этой версии ответа и не запускает предложенные процессы.",
    ),
  );
  if (!isCEO()) {
    panel.append(
      el(
        "p",
        "",
        state.bootstrap.demo
          ? "В учебном режиме переключитесь на Анну в шапке, чтобы принять решение. Ваш черновик уже сохранён."
          : "Результат должен проверить сотрудник с правом согласования.",
      ),
    );
    return panel;
  }
  if (run.source_warnings?.length || run.task_state_stale) {
    add(
      panel,
      el(
        "p",
        "",
        "Одобрение недоступно: основания изменились. Сначала нужен новый запуск.",
      ),
      run.agent === "task-intake"
        ? refreshProposalButton(run)
        : link("Открыть агента →", `#agent/${encodeURIComponent(run.agent)}`, "button primary"),
    );
    return panel;
  }
  const form = el("form");
  form.id = "approval-form";
  const label = el("label", "field-label", "Основание решения");
  label.htmlFor = "approval-note";
  const note = el("textarea");
  note.id = "approval-note";
  note.placeholder = "Что проверили и почему принимаете эту версию";
  note.required = true;
  const err = el("p", "form-error");
  err.setAttribute("role", "alert");
  const submit = button(
    `Одобрить версию ${run.current_version}`,
    null,
    "primary",
  );
  submit.id = "approve-button";
  submit.type = "submit";
  add(form, label, note, err, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submit.disabled = true;
    err.textContent = "";
    try {
      await api(`/api/runs/${encodeURIComponent(run.id)}/approve`, {
        method: "POST",
        body: JSON.stringify({
          version: run.current_version,
          note: note.value.trim(),
        }),
      });
      await renderRoute();
      announce(
        `Версия ${run.current_version} одобрена. Отправка не выполнялась.`,
      );
    } catch (error) {
      err.textContent = error.message;
      if (run.agent === "task-intake" && error.status === 409 && /[Дд]оска.*изменилась|[Зз]адача изменилась|[Ии]сточники изменились/.test(error.message) && !$("#refresh-proposal-button", panel)) {
        add(form, el("p", "field-hint", "Новый разбор проверит актуальное состояние. Прежнее предложение останется в истории."), refreshProposalButton(run));
      }
    } finally {
      submit.disabled = false;
    }
  });
  panel.append(form);
  return panel;
}
function learningPanel(run) {
  const panel = el("section", "panel spaced");
  add(
    panel,
    el("h2", "", "Сохранить подтверждённый урок"),
    el(
      "p",
      "",
      "Опишите обнаруженную ошибку или полезное правило и проверку, которая это подтверждает. Запись будет связана с этим запуском и версией.",
    ),
  );
  const form = el("form", "learning-form spaced");
  const label = el("label", "field-label", "Что стоит учитывать дальше");
  label.htmlFor = "learning-text";
  const text = el("textarea");
  text.id = "learning-text";
  text.required = true;
  text.minLength = 10;
  text.placeholder = "Наблюдение → основание → что меняем в работе";
  const err = el("p", "form-error");
  err.setAttribute("role", "alert");
  const submit = button("Сохранить в память");
  submit.type = "submit";
  add(form, label, text, err, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submit.disabled = true;
    try {
      await api(`/api/runs/${encodeURIComponent(run.id)}/learnings`, {
        method: "POST",
        body: JSON.stringify({ text: text.value.trim() }),
      });
      await renderRoute();
      announce("Урок сохранён с привязкой к запуску.");
    } catch (error) {
      err.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
  panel.append(form);
  for (const item of run.learnings || [])
    add(
      panel,
      add(
        el("div", "history-item"),
        el("p", "", item.text),
        el(
          "small",
          "",
          `${personName(item.author)} · ${formatDate(item.created_at)}`,
        ),
      ),
    );
  return panel;
}

async function qualityPage() {
  const memory = await api("/api/memory");
  const root = el("div");
  add(
    root,
    heading(
      "Качество становится частью работы",
      "Проверка входов и выходов, история версий и человеческое решение помогают находить ошибки. Память хранит выводы с основаниями.",
      9,
    ),
  );
  const checklist = el("section", "panel");
  add(
    checklist,
    el("h2", "", "Что проверять перед решением"),
    el(
      "p",
      "section-copy",
      "Это памятка проверяющему, а не отчёт о выполненных тестах.",
    ),
  );
  for (const [title, copy] of [
    [
      "Источник",
      "Есть ли в трассировке записи, подтверждающие ключевые факты?",
    ],
    ["Задача", "Не дублирует ли она существующую? Подтверждены ли ответственный и следующий шаг?"],
    ["Обещания", "Не превращён ли желаемый срок в безусловное обязательство?"],
    ["Версия", "Совпадает ли проверяемый текст с текущей версией?"],
  ])
    add(
      checklist,
      add(
        el("div", "quality-row"),
        el("span", "check", "○"),
        add(el("div"), el("h3", "", title), el("p", "", copy)),
      ),
    );
  root.append(checklist);
  const columns = el("div", "grid-two spaced");
  const decisions = el("section", "panel");
  add(
    decisions,
    el("div", "eyebrow", "ПАМЯТЬ РЕШЕНИЙ"),
    el("h2", "", "Что действительно одобрено"),
  );
  if (!memory.decisions.length)
    decisions.append(
      el(
        "p",
        "",
        "Пока нет решений, доступных вашей роли. Одобрите проверенную версию результата, чтобы появилась первая запись.",
      ),
    );
  for (const item of memory.decisions)
    add(
      decisions,
      add(
        el("div", "history-item"),
        el("strong", "", `Версия ${item.version} · ${personName(item.author)}`),
        el("p", "", item.note || "Без комментария"),
        el("small", "", formatDate(item.created_at)),
        el("br"),
        link(
          "Открыть запуск →",
          `#run/${encodeURIComponent(item.run_id)}`,
          "button text",
        ),
      ),
    );
  const learnings = el("section", "panel");
  add(
    learnings,
    el("div", "eyebrow", "ПАМЯТЬ УЛУЧШЕНИЙ"),
    el("h2", "", "Что учтём в следующий раз"),
  );
  if (!memory.learnings.length)
    learnings.append(
      el(
        "p",
        "",
        "Подтверждённые уроки ещё не сохранены. Руководитель может добавить запись на странице одобренного результата.",
      ),
    );
  for (const item of memory.learnings)
    add(
      learnings,
      add(
        el("div", "history-item"),
        el("p", "", item.text),
        el(
          "small",
          "",
          `${personName(item.author)} · версия ${item.version} · ${formatDate(item.created_at)}`,
        ),
        el("br"),
        link(
          "Открыть основание →",
          `#run/${encodeURIComponent(item.run_id)}`,
          "button text",
        ),
      ),
    );
  add(columns, decisions, learnings);
  add(
    root,
    columns,
    definition(
      "Память системы",
      "сохранённые решения и проверенные выводы. Новая запись не переписывает знания автоматически: изменение источников — отдельное осознанное действие.",
    ),
    add(
      el("section", "panel spaced"),
      el("h3", "", "Проверки самого каркаса"),
      el(
        "p",
        "",
        "Команда make test проверяет границы доступа, контракты агентов и сценарии работы. Их фактический результат смотрите в терминале — интерфейс не выдаёт наличие тестов за успешное прохождение.",
      ),
    ),
  );
  return root;
}

buildNavigation();
$("#person-select").addEventListener("change", async (event) => {
  if (state.busy) return;
  state.person = event.target.value;
  try {
    localStorage.setItem("mayak-person", state.person);
  } catch (_) {}
  await init();
});
$("#token-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = $("#access-token").value.trim();
  $("#access-token").value = "";
  const submit = $("#token-form button");
  submit.disabled = true;
  try {
    await init();
  } finally {
    submit.disabled = false;
  }
});
$("#token-dialog").addEventListener("cancel", (event) =>
  event.preventDefault(),
);
window.addEventListener("hashchange", () => {
  renderRoute();
  window.scrollTo({ top: 0, behavior: "instant" });
});
init();
