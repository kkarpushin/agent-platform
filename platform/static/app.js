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
  services: "Услуги и цены",
  costs: "Себестоимость",
  cases: "Кейсы",
  clients: "Клиенты",
  templates: "Шаблоны",
  technical: "Технические сведения",
};
const agentTitles = {
  "client-brief": "Справка о клиенте",
  "commercial-proposal": "Коммерческое предложение",
};
const fieldTitles = {
  client: "Клиент",
  task: "Задача клиента",
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
  needs_review: "Ждёт решения человека",
  approved: "Одобрено локально",
  error: "Ошибка",
};
const statusClass = {
  running: "neutral",
  needs_review: "warning",
  approved: "",
  error: "error",
};
const skillTitles = {
  proposal: "Подготовка предложения",
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
    ? "Не настроена"
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
      "Платформа недоступна. Проверьте, что docker compose up продолжает работать, и повторите действие.",
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

function buildNavigation() {
  const nav = $("#navigation");
  nav.replaceChildren();
  const home = link("Обзор системы", "#overview", "nav-link");
  home.prepend(el("span", "nav-number nav-home", "⊙"));
  nav.append(home);
  layers.forEach((layer, i) => {
    const item = link(layer.title, `#${layer.id}`, "nav-link");
    item.prepend(el("span", "nav-number", String(i + 1).padStart(2, "0")));
    nav.append(item);
  });
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
  if (b.demo)
    add(
      banner,
      el("strong", "", "Учебный режим. "),
      document.createTextNode(
        "Переключатель сотрудника демонстрирует права, а не проверяет личность. Все данные вымышлены. ",
      ),
    );
  else
    add(
      banner,
      el("strong", "", "Личный доступ. "),
      document.createTextNode("Действия доступны в пределах вашей роли. "),
    );
  add(
    banner,
    document.createTextNode(
      b.llm_mode === "demo"
        ? "Тексты модели демонстрационные; поиск и расчёты выполняются программой."
        : "Ответы модели запрашиваются через платформу.",
    ),
  );
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
  $("#page-crumb").textContent = layer?.title || "Обзор системы";
  document.title = `${layer?.title || "Обзор системы"} · Маяк`;
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
        pageNode = processesPage();
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
        pageNode = overviewPage();
    }
    if (sequence !== state.render) return;
    main.replaceChildren(pageNode);
    announce(`${layer?.title || "Обзор системы"} загружено`);
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

function overviewPage() {
  const root = el("div");
  const b = state.bootstrap;
  const hero = el("section", "hero");
  const copy = el("div", "hero-copy");
  const title = el("h1");
  add(
    title,
    document.createTextNode("Целая система."),
    el("br"),
    el("em", "", "Под вашим управлением."),
  );
  add(
    copy,
    el("div", "eyebrow", "ДЕВЯТЬ СЛОЁВ · ОДНО РАБОЧЕЕ ПРОСТРАНСТВО"),
    title,
    el(
      "p",
      "",
      "Люди задают цель. Агенты используют знания и выполняют работу. Платформа хранит ход процесса, а человек проверяет и принимает решение.",
    ),
    add(
      el("div", "hero-actions"),
      link("Пройти рабочий процесс ↗", "#processes", "button primary"),
      el("span", "hero-caption", "Начните с коммерческого предложения"),
    ),
  );
  const orbit = el("div", "system-orbit");
  orbit.setAttribute("aria-hidden", "true");
  add(
    orbit,
    el("div", "orbit-ring"),
    el("div", "orbit-ring inner"),
    add(
      el("div", "orbit-core"),
      el("strong", "", "м."),
      el("small", "", "МАЯК"),
    ),
    el("div", "orbit-node n1", "Люди и цель"),
    el("div", "orbit-node n2", "Знания и действия"),
    el("div", "orbit-node n3", "Процесс и состояние"),
    el("div", "orbit-node n4", "Решение человека"),
  );
  add(hero, copy, orbit);
  root.append(hero);
  const counts = [
    `Сотрудников в обзоре: ${b.people.length}`,
    `Ролей с разными полномочиями: ${Object.keys(b.roles).length}`,
    `Доступных записей: ${b.sections.reduce((sum, section) => sum + section.count, 0)}`,
    `Сохранённых способов работы: ${b.skills.length}`,
    `Независимых агентов: ${b.agents.length}`,
    b.llm_mode === "demo"
      ? "Модели: демонстрационный режим"
      : "Модели: Anthropic",
    "От запроса до согласования",
    "Журнал и версии результатов",
    "Решения и подтверждённые уроки",
  ];
  add(
    root,
    sectionHeading("Карта системы", "Каждый слой отвечает на свой вопрос"),
  );
  const grid = el("div", "layer-grid");
  layers.forEach((layer, i) => {
    const card = link("", `#${layer.id}`, "layer-card");
    add(
      card,
      add(
        el("div", "layer-top"),
        el("span", "layer-index", String(i + 1).padStart(2, "0")),
        el("span", "layer-icon", layer.icon),
      ),
      el("h3", "", layer.title),
      el("p", "", layer.description),
      add(
        el("div", "layer-meta"),
        el("span", "", counts[i]),
        el("span", "", "↗"),
      ),
    );
    grid.append(card);
  });
  root.append(grid);
  add(
    root,
    definition(
      "Начните с вопроса «зачем?».",
      "Затем определите людей, знания, исполнителей и шаги. Автоматизация полезна, когда у результата есть владелец и понятный способ проверки.",
    ),
  );
  return root;
}
function peoplePage() {
  const b = state.bootstrap;
  const goals = b.goals || {};
  const root = el("div");
  add(
    root,
    heading(
      "Работа начинается с людей",
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
      "Полномочия видны заранее",
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
          "Платформа проверяет его роль и доступ к отдельным записям. Себестоимость хранится отдельно от клиентского прайса.",
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
      "Сначала источник. Потом ответ.",
      "Знания хранятся в Markdown-файлах — обычных текстовых документах. После синхронизации платформа ищет по доступным вам записям.",
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
  query.placeholder = "Например: автоматизация продаж";
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
      "Способ работы можно сохранить",
      "Скилл — повторно используемая инструкция. Он описывает, как выполнять определённую часть работы и что проверять.",
      4,
    ),
  );
  const grid = el("div", "grid-two");
  for (const skill of state.bootstrap.skills) {
    const card = el("section", "panel");
    add(
      card,
      el("div", "eyebrow", "СОХРАНЁННЫЙ СПОСОБ РАБОТЫ"),
      el("h3", "", skill.title || skillTitles[skill.name] || skill.name),
      el("p", "", skill.description),
    );
    const boundAgents = state.bootstrap.agents.filter((agent) =>
      (agent.skills || []).includes(skill.name),
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
    if (skill.path) card.append(el("p", "code-label", skill.path));
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
          "Одну инструкцию можно применять к нескольким клиентам или процессам.",
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
function agentsPage() {
  const root = el("div");
  add(
    root,
    heading(
      "Каждому исполнителю — ясная задача",
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
            Object.keys(agent.input.properties || {})
              .map((key) => fieldTitles[key] || key)
              .join(", "),
          ),
        ),
        add(
          el("div"),
          el("strong", "", "ВЫХОД"),
          document.createTextNode(
            Object.keys(agent.output.properties || {})
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
    sectionHeading("Агент выбирает действия. Модель помогает с текстом."),
    add(
      el("section", "panel sage"),
      el(
        "h3",
        "",
        state.bootstrap.llm_mode === "demo"
          ? "Сейчас: демонстрационный режим модели"
          : "Сейчас: модель Anthropic через платформу",
      ),
      el(
        "p",
        "",
        state.bootstrap.llm_mode === "demo"
          ? "Текст предложения формируется по учебному шаблону. Реального обращения к нейросети и расхода токенов нет. Поиск, проверка прав и расчёт цены выполняются настоящим кодом."
          : "Ключ модели хранится только на платформе. Агент отправляет запрос через общий шлюз — посредник, который учитывает использование и связывает его с запуском.",
      ),
    ),
    definition(
      "Контракт «вход → выход»",
      "это описание допустимых полей и типов данных. JSON Schema — формат такого описания; по нему система строит форму и проверяет ответ агента.",
    ),
    definition(
      "Токены модели",
      "небольшие части текста, которыми измеряется объём запроса и ответа. Оценка стоимости рассчитывается по настроенным тарифам и не является счётом провайдера.",
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
        value === "ru"
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
    key === "task" ||
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
    client: "Точное название клиента из базы знаний",
    task: "Какую работу клиент хочет улучшить? Какой результат ему нужен?",
    deadline: "Например: до конца следующего месяца",
    budget: "Необязательно",
  };
  if (placeholders[key]) input.placeholder = placeholders[key];
  add(wrap, label, input);
  const hint =
    key === "budget"
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
    link("Посмотреть клиентов в знаниях →", "#knowledge", "button text spaced"),
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
      "LLM Gateway — общий шлюз к языковой модели. Связывает запрос с запуском, учитывает ответы и фактическое использование.",
      state.bootstrap.llm_mode === "demo"
        ? "Демонстрационный режим"
        : "Anthropic",
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
function processesPage() {
  const root = el("div");
  add(
    root,
    heading(
      "Один запрос проходит весь путь",
      "Процесс — последовательность действий с входом, результатом, ответственными и условиями остановки. Здесь готовим предложение клиенту.",
      7,
    ),
  );
  const flow = el("div", "process-flow");
  const steps = [
    ["Запрос", "Марк указывает клиента, задачу и ограничения."],
    ["Знания", "Агент получает услуги, сведения о клиенте и примеры."],
    ["Расчёт", "Код считает цену и длительность по каталогу."],
    ["Черновик", "Агент собирает текст, допущения и источники."],
    ["Решение", "Анна проверяет и одобряет точную версию."],
  ];
  steps.forEach(([title, copy], i) =>
    add(
      flow,
      add(
        el("div", "process-step"),
        el("small", "", String(i + 1).padStart(2, "0")),
        el("h3", "", title),
        el("p", "", copy),
      ),
    ),
  );
  root.append(flow);
  const panels = el("div", "grid-two");
  const start = el("section", "panel ink");
  add(
    start,
    el("div", "eyebrow", "ПОПРОБУЙТЕ ЦЕЛИКОМ"),
    el("h2", "", "От задачи — к проверяемому результату"),
    el(
      "p",
      "",
      "Откройте клиента в знаниях, запустите агента и изучите ход работы. В учебном режиме переключитесь на Анну для решения.",
    ),
  );
  const allowed = state.bootstrap.agents.find(
    (a) => a.name === "commercial-proposal",
  )?.allowed;
  start.append(
    allowed
      ? link(
          "Подготовить предложение ↗",
          "#agent/commercial-proposal",
          "button spaced",
        )
      : el("p", "", "Для запуска нужна роль продаж или руководителя."),
  );
  add(
    panels,
    start,
    add(
      el("section", "panel"),
      el("h2", "", "Где процесс останавливается"),
      keyList([
        [
          "Не хватает данных",
          "Неизвестный клиент или некорректный вход требуют уточнения.",
        ],
        [
          "Ошибка исполнения",
          "Платформа сохраняет ошибку. Неуспешный запуск нельзя одобрить.",
        ],
        [
          "Нужно решение",
          "Черновик ждёт человека. Новые правки отменяют прежнее одобрение текущего текста.",
        ],
      ]),
    ),
  );
  root.append(panels);
  if (state.bootstrap.process?.length) {
    const details = el("details", "record spaced");
    const content = el("div", "record-body");
    add(
      content,
      keyList(
        state.bootstrap.process.map((step, i) => [
          `Шаг ${i + 1}`,
          typeof step === "string" ? step : pretty(step),
        ]),
      ),
    );
    add(
      details,
      add(el("summary"), el("h3", "", "Описание процесса из конфигурации")),
      content,
    );
    root.append(details);
  }
  root.append(
    definition(
      "Детерминированный расчёт",
      "одинаковые исходные данные всегда дают одинаковую сумму. Модель помогает выбрать услуги и написать текст, но не придумывает цены.",
    ),
  );
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
        "Начните со справки о клиенте или коммерческого предложения. Здесь появится настоящий ход работы.",
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
          run.llm_mode === "demo" && el("p", "", "Демонстрационный режим"),
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
      "текущая точка процесса: выполняется, ждёт решения, одобрено или завершилось ошибкой. «Одобрено локально» не означает, что результат отправлен клиенту.",
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
          call.purpose === "select_services"
            ? "Подбор услуг"
            : call.purpose === "draft_proposal"
              ? "Подготовка текста"
              : call.purpose,
        ),
        el(
          "p",
          "",
          `${call.mode === "demo" ? "Демонстрационный ответ" : call.model || "Модель"} · ${money(call.cost_usd)}`,
        ),
      );
      if (call.mode === "demo")
        block.append(
          el("p", "", "Обращения к нейросети нет; токены не расходуются."),
        );
      else
        block.append(
          el(
            "p",
            "",
            `Токены: вход ${call.input_tokens ?? "нет данных"}, выход ${call.output_tokens ?? "нет данных"}.`,
          ),
        );
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
        run.llm_mode === "demo"
          ? "Демонстрационные ответы модели"
          : "Режим Anthropic API",
        "neutral",
      ),
    ),
  );
  const metrics = el("div", "run-metrics");
  const elapsed =
    run.duration_ms === null || run.duration_ms === undefined
      ? "Ещё нет данных"
      : `${(run.duration_ms / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} с`;
  const tokens =
    run.llm_mode === "demo"
      ? "Не расходуются"
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
  root.append(metrics);
  if (run.source_warnings?.length) {
    const warnings = add(
      el("section", "error-panel"),
      el("h3", "", "Источники изменились после запуска"),
      el(
        "p",
        "",
        "Этот результат основан на прежних версиях знаний. Запустите агента заново перед новым решением.",
      ),
    );
    for (const warning of run.source_warnings)
      warnings.append(el("p", "", `${warning.id}: ${warning.reason}`));
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
  const edit = button("Редактировать", () => startEditing());
  edit.id = "edit-result-button";
  add(
    header,
    el("h2", "", "Результат"),
    run.output?.markdown !== undefined &&
      run.status !== "running" &&
      run.status !== "error" &&
      edit,
  );
  resultPanel.append(header);
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
        "Старый текст и прежние одобрения останутся в истории. Редактируется только текст; расчётные поля сохраняются.",
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
  return root;
}

function approvalPanel(run) {
  const panel = el("section", "approval-box");
  panel.id = "approval-panel";
  if (run.status === "approved") {
    add(
      panel,
      el("h3", "", `Версия ${run.current_version} одобрена локально`),
      el(
        "p",
        "",
        "Решение сохранено. Отправка клиенту не выполнялась. Любое изменение текста потребует нового согласования.",
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
      "Проверьте источники, расчёт, обещания и текст. Согласование относится только к текущей версии.",
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
  if (run.source_warnings?.length) {
    add(
      panel,
      el(
        "p",
        "",
        "Одобрение недоступно: основания изменились. Сначала нужен новый запуск.",
      ),
      link(
        "Открыть агента →",
        `#agent/${encodeURIComponent(run.agent)}`,
        "button primary",
      ),
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
    ["Расчёт", "Сходится ли сумма услуг? Не выдан ли бюджет клиента за цену?"],
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
