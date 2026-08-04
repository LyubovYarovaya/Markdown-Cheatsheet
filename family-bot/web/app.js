/* Mini App: списки покупок, вишлисты и траты. Ванильный JS, без сборки. */

const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const state = {
  tab: 'shopping',
  me: null,
  lists: [],
  active: { shopping: null, wishlist: null },
  items: [],
  showBought: false,
  expenseCategories: [],
  month: new Date(),
  expenses: [],
  templates: [],
  summary: null,
};

const view = document.getElementById('view');
const fab = document.getElementById('fab');
const modalRoot = document.getElementById('modal-root');

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

const money = (value, currency) => {
  if (value === null || value === undefined) return '';
  const num = Number(value);
  const text = num % 1 === 0 ? num.toLocaleString('ru-RU') : num.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${text} ${currency}` : text;
};

const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
const PERIODS = { once: 'Разовая', monthly: 'Ежемесячная', quarterly: 'Ежеквартальная', yearly: 'Ежегодная' };

function toast(text) {
  const node = document.createElement('div');
  node.className = 'toast';
  node.textContent = text;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 2600);
}

function haptic(type = 'light') {
  try { tg?.HapticFeedback?.impactOccurred(type); } catch (_) { /* не критично */ }
}

async function api(path, { method = 'GET', body } = {}) {
  const response = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': tg?.initData || '',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* пусто */ }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

/* ---------- загрузка данных ---------- */

async function loadCore() {
  state.me = await api('/api/me');
  document.getElementById('header-title').textContent = state.me.household_title;
  document.getElementById('header-sub').textContent =
    state.me.members.map((m) => m.name).join(' · ');
}

async function loadLists() {
  state.lists = await api('/api/lists');
  for (const kind of ['shopping', 'wishlist']) {
    const own = state.lists.filter((l) => l.kind === kind);
    if (!own.some((l) => l.id === state.active[kind])) {
      state.active[kind] = own.length ? own[0].id : null;
    }
  }
}

async function loadItems(listId) {
  state.items = listId ? await api(`/api/lists/${listId}/items`) : [];
}

function monthRange(date) {
  const from = new Date(date.getFullYear(), date.getMonth(), 1);
  const to = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return [iso(from), iso(to)];
}

async function loadExpenses() {
  const [from, to] = monthRange(state.month);
  const [categories, expenses, templates, summary] = await Promise.all([
    api('/api/expense-categories'),
    api(`/api/expenses?date_from=${from}&date_to=${to}`),
    api('/api/expenses?templates=true'),
    api(`/api/expenses/summary?date_from=${from}&date_to=${to}`),
  ]);
  state.expenseCategories = categories;
  state.expenses = expenses;
  state.templates = templates;
  state.summary = summary;
}

/* ---------- рендер: покупки и вишлисты ---------- */

function listChips(kind) {
  const lists = state.lists.filter((l) => l.kind === kind);
  return `<div class="chips">${lists.map((l) => `
    <button class="chip ${l.id === state.active[kind] ? 'active' : ''}" data-pick-list="${l.id}">
      <span>${esc(l.emoji)} ${esc(l.title)}</span>
      <span class="count">${l.active_count}</span>
    </button>`).join('')}
    <button class="chip" data-new-list="${kind}">＋</button>
  </div>`;
}

function itemCard(item) {
  const thumb = item.image_url
    ? `<img class="thumb" src="${esc(item.image_url)}" alt="" loading="lazy" onerror="this.remove()">`
    : '';
  const meta = [];
  if (item.price) meta.push(`<span class="price">${esc(money(item.price, item.currency || state.me.currency))}</span>`);
  if (item.shop) meta.push(`<span>${esc(item.shop)}</span>`);
  if (item.created_by) meta.push(`<span>${esc(item.created_by)}</span>`);
  if (item.is_reserved) meta.push(`<span class="badge reserved">🎀 ${esc(item.reserved_by || 'забронировано')}</span>`);

  return `<div class="card ${item.status === 'bought' ? 'bought' : ''}">
    ${thumb}
    <div class="body">
      <div class="title">${esc(item.title)}</div>
      <div class="meta">${meta.join('')}</div>
      ${item.note ? `<div class="meta">📝 ${esc(item.note)}</div>` : ''}
      <div class="actions">
        ${item.url ? `<a class="btn small" href="${esc(item.url)}" target="_blank" rel="noopener">🔗 Открыть</a>` : ''}
        <button class="btn small" data-toggle-bought="${item.id}">${item.status === 'bought' ? '↩︎ Вернуть' : '✅ Куплено'}</button>
        <button class="btn small" data-edit-item="${item.id}">✏️</button>
        <button class="btn small danger" data-delete-item="${item.id}">🗑</button>
      </div>
    </div>
  </div>`;
}

function currentList(kind) {
  return state.lists.find((l) => l.id === state.active[kind]) || null;
}

function renderItemsView(kind) {
  const list = currentList(kind);
  const visible = state.items.filter((i) => state.showBought || i.status === 'active');
  const total = visible
    .filter((i) => i.status === 'active' && i.price)
    .reduce((sum, i) => sum + Number(i.price), 0);

  const body = visible.length
    ? visible.map(itemCard).join('')
    : `<div class="empty"><div class="big">${kind === 'wishlist' ? '🎁' : '🛍'}</div>
        Пусто. Кинь боту ссылку на товар — он сам разложит по категориям.</div>`;

  view.innerHTML = `
    ${listChips(kind)}
    ${list ? `<div class="panel">
      <div class="row" style="padding-top:0">
        <div class="label"><b>${esc(list.emoji)} ${esc(list.title)}</b></div>
        <div class="value">${total ? esc(money(total, state.me.currency)) : ''}</div>
      </div>
      <div class="actions" style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn small" data-toggle-shown>${state.showBought ? 'Скрыть купленное' : 'Показать купленное'}</button>
        <button class="btn small" data-share-list="${list.id}">${list.is_shared ? '🔗 Ссылка' : '🔒 Поделиться'}</button>
        <button class="btn small" data-rename-list="${list.id}">✏️ Название</button>
        <button class="btn small danger" data-delete-list="${list.id}">🗑</button>
      </div>
      ${list.is_shared ? `<div class="share-box">
        <input readonly value="${esc(list.share_url)}">
        <button class="btn small" data-copy="${esc(list.share_url)}">Копировать</button>
      </div>` : ''}
    </div>` : ''}
    ${body}`;
}

/* ---------- рендер: траты ---------- */

function expenseRow(expense) {
  const date = new Date(expense.spent_on);
  return `<div class="row">
    <div class="label">
      <span>${esc(expense.category_emoji || '❔')}</span>
      <span>
        <div>${esc(expense.title || expense.category_title || 'Трата')}</div>
        <div style="font-size:12px;color:var(--hint)">
          ${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}
          ${expense.period !== 'once' ? ' · ' + esc(PERIODS[expense.period]) : ''}
          ${expense.created_by ? ' · ' + esc(expense.created_by) : ''}
        </div>
      </span>
    </div>
    <div class="value">
      ${esc(money(expense.amount, expense.currency))}
      <button class="btn small ghost" data-edit-expense="${expense.id}">✏️</button>
    </div>
  </div>`;
}

function renderExpensesView() {
  const summary = state.summary;
  const max = Math.max(1, ...summary.by_category.map((b) => b.total));
  const monthLabel = `${MONTHS[state.month.getMonth()]} ${state.month.getFullYear()}`;

  const categories = summary.by_category.map((bucket) => `
    <div class="row">
      <div class="label"><span>${esc(bucket.emoji)}</span><span>${esc(bucket.title)}
        <div class="bar"><span style="width:${(bucket.total / max) * 100}%"></span></div>
      </span></div>
      <div class="value">${esc(money(bucket.total, summary.currency))}</div>
    </div>`).join('') || '<div class="empty">Трат за месяц нет</div>';

  const others = summary.by_currency.filter((b) => b.key !== summary.currency);
  const templates = state.templates.map((template) => `
    <div class="row">
      <div class="label"><span>${esc(template.category_emoji || '🔁')}</span><span>
        <div>${esc(template.title || template.category_title || 'Платёж')}</div>
        <div style="font-size:12px;color:var(--hint)">${esc(PERIODS[template.period])}</div>
      </span></div>
      <div class="value">${esc(money(template.amount, template.currency))}
        <button class="btn small" data-pay-template="${template.id}">Оплатить</button>
        <button class="btn small ghost" data-edit-expense="${template.id}">✏️</button>
      </div>
    </div>`).join('') || '<div style="color:var(--hint);font-size:13px">Регулярных платежей пока нет — добавь аренду, подписки, страховку.</div>';

  view.innerHTML = `
    <div class="panel">
      <div class="row" style="padding-top:0;align-items:center">
        <button class="btn small" data-month="-1">‹</button>
        <b>${esc(monthLabel)}</b>
        <button class="btn small" data-month="1">›</button>
      </div>
      <div class="total">${esc(money(summary.total, summary.currency))}</div>
      ${others.length ? `<div style="color:var(--hint);font-size:13px">
        + ${others.map((b) => esc(money(b.total, b.key))).join(' · ')}</div>` : ''}
      <div class="row"><div class="label">Регулярные в месяц</div>
        <div class="value">${esc(money(summary.planned_monthly, summary.currency))}</div></div>
      <div class="row"><div class="label">В квартал</div>
        <div class="value">${esc(money(summary.planned_quarterly, summary.currency))}</div></div>
      <div class="row"><div class="label">В год</div>
        <div class="value">${esc(money(summary.planned_yearly, summary.currency))}</div></div>
    </div>

    <div class="panel"><h3>По категориям</h3>${categories}</div>

    <div class="panel"><h3>🔁 Регулярные платежи</h3>${templates}
      <button class="btn small" data-new-template style="margin-top:10px">＋ Добавить регулярный</button>
    </div>

    <div class="panel"><h3>Траты месяца</h3>
      ${state.expenses.length ? state.expenses.map(expenseRow).join('') : '<div class="empty">Пока пусто</div>'}
    </div>`;
}

/* ---------- рендер: настройки ---------- */

function renderSettings() {
  const me = state.me;
  const shared = state.lists.filter((l) => l.is_shared);
  view.innerHTML = `
    <div class="panel">
      <h3>👨‍👩‍👧 ${esc(me.household_title)}</h3>
      ${me.members.map((m) => `<div class="row"><div class="label">${esc(m.name)}</div>
        <div class="value">${m.id === me.user.id ? 'это ты' : ''}</div></div>`).join('')}
      <div class="share-box">
        <input readonly value="${esc(me.invite_url)}">
        <button class="btn small" data-copy="${esc(me.invite_url)}">Копировать</button>
      </div>
      <div style="color:var(--hint);font-size:13px;margin-top:8px">
        Отправь эту ссылку второй половинке — списки и траты станут общими.
      </div>
    </div>

    <div class="panel">
      <h3>🔗 Открытые ссылки</h3>
      ${shared.length ? shared.map((l) => `<div class="row">
        <div class="label">${esc(l.emoji)} ${esc(l.title)}</div>
        <div class="value"><button class="btn small" data-copy="${esc(l.share_url)}">Копировать</button>
        <button class="btn small danger" data-unshare="${l.id}">Закрыть</button></div>
      </div>`).join('') : '<div style="color:var(--hint);font-size:13px">Пока ничего не расшарено. Открой список и нажми «Поделиться».</div>'}
    </div>

    <div class="panel">
      <h3>💸 Категории трат</h3>
      ${state.expenseCategories.map((c) => `<div class="row">
        <div class="label">${esc(c.emoji)} ${esc(c.title)}</div>
        <div class="value"><button class="btn small danger" data-delete-expense-category="${c.id}">🗑</button></div>
      </div>`).join('')}
      <button class="btn small" data-new-expense-category style="margin-top:10px">＋ Новая категория</button>
    </div>

    <div class="panel">
      <h3>ℹ️ Как это работает</h3>
      <div style="color:var(--hint);font-size:13px">
        Кидай боту ссылку на товар — он вытянет название, цену и картинку и положит
        в подходящую категорию. Пиши «450 бензин» — запишет трату.
        Любой список можно открыть по ссылке: гости увидят его без Telegram
        и смогут забронировать подарок.
      </div>
    </div>`;
}

/* ---------- модальные окна ---------- */

function closeSheet() { modalRoot.innerHTML = ''; }

function openSheet(title, html, onSubmit) {
  modalRoot.innerHTML = `<div class="sheet-backdrop">
    <form class="sheet"><h2>${esc(title)}</h2>${html}
      <div class="sheet-actions">
        <button type="button" class="btn" data-cancel>Отмена</button>
        <button type="submit" class="btn primary">Сохранить</button>
      </div>
    </form>
  </div>`;
  const backdrop = modalRoot.firstElementChild;
  const form = backdrop.querySelector('form');
  backdrop.addEventListener('click', (event) => { if (event.target === backdrop) closeSheet(); });
  form.querySelector('[data-cancel]').addEventListener('click', closeSheet);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    const button = form.querySelector('[type=submit]');
    button.disabled = true;
    try {
      await onSubmit(data);
      closeSheet();
    } catch (error) {
      toast(error.message);
      button.disabled = false;
    }
  });
  form.querySelector('input, select, textarea')?.focus();
}

function listOptions(kind, selectedId) {
  return state.lists.filter((l) => l.kind === kind)
    .map((l) => `<option value="${l.id}" ${l.id === selectedId ? 'selected' : ''}>${esc(l.emoji)} ${esc(l.title)}</option>`)
    .join('');
}

function openItemSheet(item = null) {
  const kind = state.tab === 'wishlist' ? 'wishlist' : 'shopping';
  const listId = item ? item.list_id : state.active[kind];
  const bothKinds = ['shopping', 'wishlist']
    .map((k) => `<optgroup label="${k === 'shopping' ? 'Покупки' : 'Вишлисты'}">${listOptions(k, listId)}</optgroup>`)
    .join('');
  const auto = item ? '' : '<option value="">✨ Подобрать категорию самому</option>';

  openSheet(item ? 'Позиция' : 'Новая позиция', `
    <label class="field"><span>Ссылка на товар</span>
      <input name="url" type="url" inputmode="url" placeholder="https://…" value="${esc(item?.url || '')}"></label>
    <label class="field"><span>Название ${item ? '' : '(можно оставить пустым — возьму со страницы)'}</span>
      <input name="title" value="${esc(item?.title || '')}"></label>
    <div class="grid-2">
      <label class="field"><span>Цена</span>
        <input name="price" type="number" step="0.01" inputmode="decimal" value="${item?.price ?? ''}"></label>
      <label class="field"><span>Валюта</span>
        <input name="currency" value="${esc(item?.currency || state.me.currency)}"></label>
    </div>
    <label class="field"><span>Список</span><select name="list_id">${auto}${bothKinds}</select></label>
    <label class="field"><span>Заметка</span><input name="note" value="${esc(item?.note || '')}"></label>
  `, async (data) => {
    const payload = {
      url: data.url || null,
      title: data.title || null,
      price: data.price ? Number(data.price) : null,
      currency: data.currency || null,
      note: data.note || null,
      list_id: data.list_id ? Number(data.list_id) : null,
    };
    if (!payload.url && !payload.title) throw new Error('Нужна ссылка или название');
    if (item) {
      await api(`/api/items/${item.id}`, { method: 'PATCH', body: payload });
    } else {
      toast('Читаю страницу…');
      await api('/api/items', { method: 'POST', body: payload });
    }
    await refresh();
  });
}

function openExpenseSheet(expense = null, { template = false } = {}) {
  const isTemplate = expense ? expense.is_template : template;
  const today = new Date().toISOString().slice(0, 10);
  const options = state.expenseCategories
    .map((c) => `<option value="${c.id}" ${c.id === expense?.category_id ? 'selected' : ''}>${esc(c.emoji)} ${esc(c.title)}</option>`)
    .join('');
  const periods = Object.entries(PERIODS)
    .map(([key, title]) => `<option value="${key}" ${key === (expense?.period || (isTemplate ? 'monthly' : 'once')) ? 'selected' : ''}>${title}</option>`)
    .join('');

  openSheet(isTemplate ? 'Регулярный платёж' : 'Трата', `
    <div class="grid-2">
      <label class="field"><span>Сумма</span>
        <input name="amount" type="number" step="0.01" inputmode="decimal" required value="${expense?.amount ?? ''}"></label>
      <label class="field"><span>Валюта</span>
        <input name="currency" value="${esc(expense?.currency || state.me.currency)}"></label>
    </div>
    <label class="field"><span>На что</span>
      <input name="title" placeholder="бензин, аптека, садик" value="${esc(expense?.title || '')}"></label>
    <label class="field"><span>Категория</span>
      <select name="category_id"><option value="">Без категории</option>${options}</select></label>
    <div class="grid-2">
      <label class="field"><span>Периодичность</span><select name="period">${periods}</select></label>
      <label class="field"><span>Дата</span>
        <input name="spent_on" type="date" value="${expense?.spent_on || today}"></label>
    </div>
    ${expense ? `<button type="button" class="btn danger block" data-delete-expense="${expense.id}">Удалить</button>` : ''}
  `, async (data) => {
    const payload = {
      amount: Number(data.amount),
      title: data.title || '',
      currency: data.currency || null,
      period: data.period,
      spent_on: data.spent_on || today,
      category_id: data.category_id ? Number(data.category_id) : null,
    };
    if (!payload.amount || payload.amount <= 0) throw new Error('Сумма должна быть больше нуля');
    if (expense) {
      await api(`/api/expenses/${expense.id}`, { method: 'PATCH', body: payload });
    } else {
      await api('/api/expenses', { method: 'POST', body: { ...payload, is_template: isTemplate } });
    }
    await refresh();
  });
}

function openListSheet(kind) {
  openSheet(kind === 'wishlist' ? 'Новый вишлист' : 'Новая категория', `
    <div class="grid-2">
      <label class="field"><span>Эмодзи</span><input name="emoji" value="${kind === 'wishlist' ? '🎁' : '📦'}" maxlength="4"></label>
      <label class="field"><span>Название</span><input name="title" required></label>
    </div>
    ${kind === 'wishlist' ? `<label class="field"><span>Чей</span>
      <select name="personal"><option value="">Общий на двоих</option><option value="1">Только мой</option></select></label>` : ''}
  `, async (data) => {
    if (!data.title?.trim()) throw new Error('Нужно название');
    const created = await api('/api/lists', {
      method: 'POST',
      body: { kind, title: data.title.trim(), emoji: data.emoji || '📦', personal: Boolean(data.personal) },
    });
    state.active[kind] = created.id;
    await refresh();
  });
}

function openRenameSheet(list) {
  openSheet('Название списка', `
    <div class="grid-2">
      <label class="field"><span>Эмодзи</span><input name="emoji" value="${esc(list.emoji)}" maxlength="4"></label>
      <label class="field"><span>Название</span><input name="title" value="${esc(list.title)}" required></label>
    </div>
  `, async (data) => {
    await api(`/api/lists/${list.id}`, { method: 'PATCH', body: { title: data.title, emoji: data.emoji } });
    await refresh();
  });
}

function openExpenseCategorySheet() {
  openSheet('Категория трат', `
    <div class="grid-2">
      <label class="field"><span>Эмодзи</span><input name="emoji" value="💸" maxlength="4"></label>
      <label class="field"><span>Название</span><input name="title" required></label>
    </div>
  `, async (data) => {
    await api('/api/expense-categories', { method: 'POST', body: { title: data.title, emoji: data.emoji } });
    await refresh();
  });
}

/* ---------- действия ---------- */

async function shareList(listId) {
  const list = state.lists.find((l) => l.id === listId);
  if (!list.is_shared) {
    await api(`/api/lists/${listId}`, { method: 'PATCH', body: { is_shared: true } });
    await refresh();
    toast('Ссылка готова — копируй и отправляй');
    return;
  }
  copy(list.share_url);
}

function copy(text) {
  navigator.clipboard?.writeText(text)
    .then(() => toast('Скопировано'))
    .catch(() => toast(text));
}

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-pick-list], [data-new-list], [data-toggle-bought], [data-edit-item],'
    + '[data-delete-item], [data-toggle-shown], [data-share-list], [data-rename-list], [data-delete-list],'
    + '[data-copy], [data-month], [data-edit-expense], [data-delete-expense], [data-pay-template],'
    + '[data-new-template], [data-new-expense-category], [data-delete-expense-category], [data-unshare]');
  if (!target) return;
  const data = target.dataset;

  try {
    if (data.pickList) {
      const kind = state.tab === 'wishlist' ? 'wishlist' : 'shopping';
      state.active[kind] = Number(data.pickList);
      haptic();
      await loadItems(state.active[kind]);
      renderItemsView(kind);
    } else if (data.newList) {
      openListSheet(data.newList);
    } else if (data.toggleBought) {
      const item = state.items.find((i) => i.id === Number(data.toggleBought));
      await api(`/api/items/${item.id}`, {
        method: 'PATCH', body: { status: item.status === 'bought' ? 'active' : 'bought' },
      });
      haptic();
      await refresh();
    } else if (data.editItem) {
      openItemSheet(state.items.find((i) => i.id === Number(data.editItem)));
    } else if (data.deleteItem) {
      if (!confirm('Удалить позицию?')) return;
      await api(`/api/items/${data.deleteItem}`, { method: 'DELETE' });
      await refresh();
    } else if (data.toggleShown !== undefined) {
      state.showBought = !state.showBought;
      renderItemsView(state.tab === 'wishlist' ? 'wishlist' : 'shopping');
    } else if (data.shareList) {
      await shareList(Number(data.shareList));
    } else if (data.unshare) {
      await api(`/api/lists/${data.unshare}`, { method: 'PATCH', body: { is_shared: false } });
      await refresh();
    } else if (data.renameList) {
      openRenameSheet(state.lists.find((l) => l.id === Number(data.renameList)));
    } else if (data.deleteList) {
      if (!confirm('Удалить список вместе со всем содержимым?')) return;
      await api(`/api/lists/${data.deleteList}`, { method: 'DELETE' });
      await refresh();
    } else if (data.copy) {
      copy(data.copy);
    } else if (data.month) {
      state.month = new Date(state.month.getFullYear(), state.month.getMonth() + Number(data.month), 1);
      await loadExpenses();
      renderExpensesView();
    } else if (data.editExpense) {
      const id = Number(data.editExpense);
      openExpenseSheet(state.expenses.find((e) => e.id === id) || state.templates.find((e) => e.id === id));
    } else if (data.deleteExpense) {
      if (!confirm('Удалить трату?')) return;
      await api(`/api/expenses/${data.deleteExpense}`, { method: 'DELETE' });
      closeSheet();
      await refresh();
    } else if (data.payTemplate) {
      await api(`/api/expenses/${data.payTemplate}/pay`, { method: 'POST', body: {} });
      haptic('medium');
      toast('Записала оплату');
      await refresh();
    } else if (data.newTemplate !== undefined) {
      openExpenseSheet(null, { template: true });
    } else if (data.newExpenseCategory !== undefined) {
      openExpenseCategorySheet();
    } else if (data.deleteExpenseCategory) {
      if (!confirm('Удалить категорию? Траты останутся без категории.')) return;
      await api(`/api/expense-categories/${data.deleteExpenseCategory}`, { method: 'DELETE' });
      await refresh();
    }
  } catch (error) {
    toast(error.message);
  }
});

document.querySelectorAll('nav.tabbar button').forEach((button) => {
  button.addEventListener('click', async () => {
    document.querySelectorAll('nav.tabbar button').forEach((b) => b.classList.remove('active'));
    button.classList.add('active');
    state.tab = button.dataset.tab;
    haptic();
    await refresh();
  });
});

fab.addEventListener('click', () => {
  if (state.tab === 'expenses') openExpenseSheet();
  else openItemSheet();
});

/* ---------- главный цикл ---------- */

async function refresh() {
  try {
    if (state.tab === 'shopping' || state.tab === 'wishlist') {
      await loadLists();
      await loadItems(state.active[state.tab]);
      renderItemsView(state.tab);
      fab.hidden = false;
    } else if (state.tab === 'expenses') {
      await loadExpenses();
      renderExpensesView();
      fab.hidden = false;
    } else {
      await Promise.all([loadLists(), (async () => {
        state.expenseCategories = await api('/api/expense-categories');
      })()]);
      renderSettings();
      fab.hidden = true;
    }
  } catch (error) {
    view.innerHTML = `<div class="empty"><div class="big">😕</div>${esc(error.message)}</div>`;
  }
}

(async function init() {
  try {
    await loadCore();
    await refresh();
  } catch (error) {
    view.innerHTML = `<div class="empty"><div class="big">🔒</div>
      Не получилось авторизоваться: ${esc(error.message)}<br><br>
      Открой приложение через кнопку в боте.</div>`;
  }
})();
