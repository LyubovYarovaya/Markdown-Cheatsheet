/* Публичная страница списка: гость смотрит и бронирует подарки. */

const token = location.pathname.split('/').filter(Boolean).pop();
const itemsNode = document.getElementById('items');
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

// Секрет гостя — по нему он потом может снять свою бронь с этого же устройства.
function guestSecret() {
  let secret = localStorage.getItem('guest_secret');
  if (!secret) {
    secret = (crypto.randomUUID?.() || String(Math.random())).replace(/-/g, '');
    localStorage.setItem('guest_secret', secret);
  }
  return secret;
}

const guestName = () => localStorage.getItem('guest_name') || '';

function toast(text) {
  const node = document.createElement('div');
  node.className = 'toast';
  node.textContent = text;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 2600);
}

async function api(path, { method = 'GET', body } = {}) {
  const response = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* пусто */ }
    throw new Error(detail);
  }
  return response.json();
}

function askName() {
  return new Promise((resolve) => {
    modalRoot.innerHTML = `<div class="sheet-backdrop">
      <form class="sheet">
        <h2>Как вас зовут?</h2>
        <p style="color:var(--hint);font-size:13px;margin-top:-6px">
          Имя увидят только другие гости — чтобы не задарить одно и то же дважды.
        </p>
        <label class="field"><input name="name" required maxlength="60" value="${esc(guestName())}" placeholder="Аня"></label>
        <div class="sheet-actions">
          <button type="button" class="btn" data-cancel>Отмена</button>
          <button type="submit" class="btn primary">Забронировать</button>
        </div>
      </form>
    </div>`;
    const backdrop = modalRoot.firstElementChild;
    const form = backdrop.querySelector('form');
    const close = (value) => { modalRoot.innerHTML = ''; resolve(value); };
    backdrop.addEventListener('click', (event) => { if (event.target === backdrop) close(null); });
    form.querySelector('[data-cancel]').addEventListener('click', () => close(null));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const name = new FormData(form).get('name').toString().trim();
      if (!name) return;
      localStorage.setItem('guest_name', name);
      close(name);
    });
    form.querySelector('input').focus();
  });
}

function itemCard(item) {
  const thumb = item.image_url
    ? `<img class="thumb" src="${esc(item.image_url)}" alt="" loading="lazy" onerror="this.remove()">`
    : '';
  const meta = [];
  if (item.price) meta.push(`<span class="price">${esc(money(item.price, item.currency))}</span>`);
  if (item.priority > 0) meta.push('<span class="badge">очень хочется</span>');
  if (item.is_reserved) {
    meta.push(`<span class="badge reserved">🎀 ${item.mine ? 'вы забронировали' : 'забронировано: ' + esc(item.reserved_by)}</span>`);
  }

  let action = `<button class="btn small primary" data-reserve="${item.id}">🎀 Забронировать</button>`;
  if (item.is_reserved) {
    action = item.mine
      ? `<button class="btn small" data-unreserve="${item.id}">Снять бронь</button>`
      : '';
  }

  return `<div class="card">
    ${thumb}
    <div class="body">
      <div class="title">${esc(item.title)}</div>
      <div class="meta">${meta.join('')}</div>
      ${item.note ? `<div class="meta">📝 ${esc(item.note)}</div>` : ''}
      <div class="actions">
        ${item.url ? `<a class="btn small" href="${esc(item.url)}" target="_blank" rel="noopener">🔗 Посмотреть</a>` : ''}
        ${action}
      </div>
    </div>
  </div>`;
}

async function load() {
  try {
    const data = await api(`/api/public/${encodeURIComponent(token)}?secret=${encodeURIComponent(guestSecret())}`);
    document.getElementById('emoji').textContent = data.emoji;
    document.getElementById('title').textContent = data.title;
    document.title = data.title;
    document.getElementById('subtitle').textContent = data.owner_name
      ? `Вишлист: ${data.owner_name}`
      : data.household_title;

    if (data.hide_from_owner) {
      document.getElementById('foot').innerHTML =
        'Отмечайте «Забронировать», чтобы никто не подарил одно и то же дважды.<br>'
        + 'Владелец вишлиста брони не видит — сюрприз останется сюрпризом.';
    }

    itemsNode.innerHTML = data.items.length
      ? data.items.map(itemCard).join('')
      : '<div class="empty"><div class="big">🕊</div>Список пока пуст</div>';
  } catch (error) {
    itemsNode.innerHTML = `<div class="empty"><div class="big">🙈</div>${esc(error.message)}</div>`;
    document.getElementById('title').textContent = 'Список недоступен';
  }
}

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-reserve], [data-unreserve]');
  if (!target) return;

  try {
    if (target.dataset.reserve) {
      const name = await askName();
      if (!name) return;
      await api(`/api/public/${encodeURIComponent(token)}/items/${target.dataset.reserve}/reserve`, {
        method: 'POST', body: { name, secret: guestSecret() },
      });
      toast('Забронировано 🎀');
    } else {
      await api(`/api/public/${encodeURIComponent(token)}/items/${target.dataset.unreserve}/unreserve`, {
        method: 'POST', body: { secret: guestSecret() },
      });
      toast('Бронь снята');
    }
    await load();
  } catch (error) {
    toast(error.message);
    await load();
  }
});

load();
