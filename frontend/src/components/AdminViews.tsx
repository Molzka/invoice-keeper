import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import { isCalendarDate, normalizeRecurringAmount, previewMonthlyDueDates } from '../lib/recurring-inputs';
import type { RecurringPayment, User } from '../types/api';
import { Drawer, ErrorNotice, Pagination } from './UI';
import { PageHeader } from './PageHeader';
import { DatePicker } from './DatePicker';
import { SelectField } from './SelectField';

export type AdminViewProps = {
  onChanged: () => void;
  onHistory: (id: string, title: string) => void;
  notify: (message: string) => void;
  isAdmin: boolean;
  today: string;
  timezone: string;
  createRequested?: number;
  onCreateRequestHandled?: () => void;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };
type FieldErrors = Record<string, string>;
type Currency = 'RUB' | 'USD' | 'EUR';
const PAGE_SIZE = 10;

function money(amount: string, currency: string) {
  const [whole, decimal = '00'] = amount.split('.');
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0')},${decimal}\u00a0${currency}`;
}

function calendarDate(date: string | null) {
  if (!date) return '—';
  const [year, month, day] = date.split('-');
  return `${day}.${month}.${year}`;
}

function createdDate(value: string, timezone: string) {
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: timezone, day: '2-digit', month: 'short', year: 'numeric',
  }).format(new Date(value));
}

function fieldsFromError(error: unknown): FieldErrors {
  if (!(error instanceof ApiError)) return {};
  return Object.fromEntries(error.details.map(detail => [detail.field, detail.message]));
}

function resultUncertain(error: unknown) {
  return error instanceof ApiError && ['TIMEOUT', 'NETWORK_ERROR'].includes(error.code);
}

function FieldMessage({ id, message }: { id: string; message?: string }) {
  return message ? <span className="field-error" id={id} role="alert">{message}</span> : null;
}

function PlusIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>;
}

function Forbidden() {
  return <div className="panel empty-state"><span className="eyebrow">Недостаточно прав</span><h2>Раздел доступен администратору</h2><p className="muted">Для управления пользователями нужна учётная запись администратора.</p></div>;
}

function UncertainCreate({ onCheck }: { onCheck: () => void }) {
  return <div className="notice" role="alert"><strong>Результат создания пока неизвестен.</strong><p>Соединение прервалось до ответа сервера. Запись могла сохраниться. Сначала проверьте список, чтобы не создать дубликат.</p><button type="button" className="btn btn-secondary" onClick={onCheck}>Закрыть и проверить список</button></div>;
}

export function RecurringView({ onChanged, onHistory, notify, isAdmin, today, timezone, createRequested, onCreateRequestHandled }: AdminViewProps) {
  const [activeFilter, setActiveFilter] = useState<'active' | 'all' | 'stopped'>('active');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<Page<RecurringPayment> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [stopping, setStopping] = useState<RecurringPayment | null>(null);
  const [busyStop, setBusyStop] = useState(false);
  const [stopError, setStopError] = useState<unknown>(null);
  const stopGuard = useRef(false);
  useEffect(() => { if (isAdmin && createRequested) { setCreating(true); onCreateRequestHandled?.(); } }, [isAdmin, createRequested, onCreateRequestHandled]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError(null);
    api.listRecurringPayments({
      limit: PAGE_SIZE, offset,
      ...(activeFilter !== 'all' ? { is_active: activeFilter === 'active' } : {}),
    }).then(result => {
      if (!alive) return;
      if (offset > 0 && result.items.length === 0 && result.total <= offset) {
        setOffset(Math.max(0, Math.floor(Math.max(0, result.total - 1) / PAGE_SIZE) * PAGE_SIZE));
        return;
      }
      setPage(result);
    }).catch(error => { if (alive) setLoadError(error); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [activeFilter, offset, refresh, today, timezone]);

  function reload() { setRefresh(value => value + 1); }
  function changed() { reload(); onChanged(); }

  async function confirmStop() {
    if (!stopping || stopGuard.current) return;
    stopGuard.current = true;
    setBusyStop(true);
    setStopError(null);
    try {
      await api.stopRecurringPayment(stopping.id);
      setStopping(null);
      notify('Повторение прекращено. История и существующие обязательства сохранены.');
      changed();
    } catch (error) { setStopError(error); }
    finally { stopGuard.current = false; setBusyStop(false); }
  }

  return <section aria-labelledby="recurring-heading">
    <PageHeader kind="recurring" id="recurring-heading" title="Регулярные платежи" eyebrow="Повторения под контролем" description="Правила ежемесячных обязательств и их полная история.">
      {isAdmin && <button className="btn btn-primary" onClick={() => setCreating(true)}><PlusIcon />Добавить платёж</button>}
    </PageHeader>
    <div className="panel">
      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Состояние регулярных платежей">
          {([['active', 'Активные'], ['all', 'Все платежи'], ['stopped', 'Прекращённые']] as const).map(([value, label]) => <button key={value} type="button" className={activeFilter === value ? 'segment active' : 'segment'} aria-pressed={activeFilter === value} onClick={() => { setOffset(0); setActiveFilter(value); }}>{label}</button>)}
        </div>
        <span className="muted">Ежемесячно · {timezone}</span>
      </div>
      {loadError ? <ErrorNotice error={loadError} onRetry={reload} /> : loading ? <div className="loading-state" role="status"><span className="spinner" />Загружаем регулярные платежи…</div> : !page?.items.length ? <div className="empty-state"><span className="empty-symbol" aria-hidden="true">↻</span><h2>{activeFilter === 'stopped' ? 'Прекращённых платежей пока нет' : 'Здесь появятся регулярные платежи'}</h2><p className="muted">{activeFilter === 'stopped' ? 'Когда повторение будет прекращено, его история останется доступна.' : isAdmin ? 'Добавьте аренду, сервер или подписку — система создаст отдельные периоды оплаты.' : 'Администратор может добавить ежемесячные обязательства команды.'}</p>{isAdmin && activeFilter !== 'stopped' && <button className="btn btn-primary" onClick={() => setCreating(true)}><PlusIcon />Добавить платёж</button>}</div> : <>
        <div className="table-wrap"><table className="data-table"><thead><tr><th scope="col">Платёж</th><th scope="col">Сумма в месяц</th><th scope="col">Следующий срок</th><th scope="col">Состояние</th><th scope="col"><span className="sr-only">Действия</span></th></tr></thead><tbody>{page.items.map(payment => <tr key={payment.id}>
          <td><div className="payment-title">{payment.title}</div><span className="muted table-caption">С {calendarDate(payment.first_due_date)} · {payment.anchor_day}-го числа</span></td>
          <td className={`money ${payment.amount.split('.')[0].length > 9 ? 'money-large' : ''}`} data-label="Сумма в месяц">{money(payment.amount, payment.currency)}</td>
          <td className="date-cell" data-label="Следующий срок">{calendarDate(payment.next_due_date)}<span className="muted table-caption">{payment.is_active ? 'Плановая дата' : 'Повторение остановлено'}</span></td>
          <td data-label="Состояние"><span className={`status ${payment.is_active ? 'status-success' : 'status-neutral'}`}><span className="status-dot" />{payment.is_active ? 'Активен' : 'Прекращён'}</span></td>
          <td><div className="inline-actions"><button className="btn btn-secondary btn-small" onClick={() => onHistory(payment.id, payment.title)} aria-label={`История платежа «${payment.title}»`}>История <span aria-hidden="true">↗</span></button>{isAdmin && payment.is_active && <button className="icon-button danger-text" title="Прекратить повторение" aria-label={`Прекратить повторение «${payment.title}»`} onClick={() => { setStopError(null); setStopping(payment); }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="3" stroke="currentColor" strokeWidth="1.6" /></svg></button>}</div></td>
        </tr>)}</tbody></table></div>
        <Pagination total={page.total} limit={page.limit} offset={page.offset} onPage={setOffset} />
      </>}
    </div>
    <p className="section-note">Прекращение повторения сохраняет историю. Уже созданные периоды остаются в списке платежей и в сводке.</p>
    {creating && <RecurringForm today={today} onClose={() => setCreating(false)} onCreated={() => { setCreating(false); setOffset(0); notify('Регулярный платёж добавлен. Периоды оплаты уже созданы.'); changed(); }} onCheck={() => { setCreating(false); setActiveFilter('all'); setOffset(0); reload(); }} />}
    {stopping && <Drawer canClose={!busyStop} title="Прекратить повторение?" subtitle={stopping.title} onClose={() => { if (!busyStop) setStopping(null); }}>
      <div className="notice"><strong>История сохранится.</strong><p>Новые периоды и напоминания по этому правилу больше не будут создаваться. Уже созданные периоды останутся в истории и сводке; их оплату по-прежнему можно исправлять.</p></div>
      <p className="muted">Прекращение повторения не списывает существующие обязательства. Возобновить это правило через интерфейс v1 нельзя.</p>
      {stopError != null && <ErrorNotice error={stopError} />}
      <div className="form-actions"><button data-drawer-close className="btn btn-secondary" type="button" disabled={busyStop} onClick={() => setStopping(null)}>Отмена</button><button className="btn btn-danger" disabled={busyStop} onClick={confirmStop}>{busyStop ? 'Прекращаем…' : 'Прекратить повторение'}</button></div>
    </Drawer>}
  </section>;
}

function RecurringForm({ today, onClose, onCreated, onCheck }: { today: string; onClose: () => void; onCreated: () => void; onCheck: () => void }) {
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState<Currency>('RUB');
  const [firstDueDate, setFirstDueDate] = useState(today);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [error, setError] = useState<unknown>(null);
  const [uncertain, setUncertain] = useState(false);
  const [busy, setBusy] = useState(false);
  const guard = useRef(false);
  const dueDates = previewMonthlyDueDates(firstDueDate);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (guard.current || uncertain) return;
    const nextErrors: FieldErrors = {};
    if (!title.trim() || title.trim().length > 200) nextErrors.title = 'Введите название от 1 до 200 символов.';
    const normalizedAmount = normalizeRecurringAmount(amount);
    if (normalizedAmount === null) nextErrors.amount = 'Введите сумму от 0,01 до 999999999999,99. Например: 45000, 45000,50 или 45000.50; не более двух знаков после разделителя.';
    if (!isCalendarDate(firstDueDate)) nextErrors.first_due_date = 'Выберите действительную дату первого срока.';
    setErrors(nextErrors);
    setError(null);
    if (Object.keys(nextErrors).length || normalizedAmount === null) return;
    guard.current = true;
    setBusy(true);
    try {
      await api.createRecurringPayment({ title: title.trim(), amount: normalizedAmount, currency, first_due_date: firstDueDate, periodicity: 'monthly' });
      onCreated();
    } catch (caught) {
      setErrors(fieldsFromError(caught));
      setError(caught);
      setUncertain(resultUncertain(caught));
    } finally { guard.current = false; setBusy(false); }
  }

  return <Drawer canClose={!busy} title="Новый регулярный платёж" subtitle="Добавьте обязательство один раз — дальше каждый месяц." onClose={() => { if (!busy) { if (uncertain) onCheck(); else onClose(); } }}>
    <form onSubmit={submit} noValidate className="form-grid">
      <label className="field" htmlFor="recurring-title"><span>Название платежа</span><input id="recurring-title" name="title" value={title} onChange={event => setTitle(event.target.value)} maxLength={200} placeholder="Например, аренда офиса" disabled={busy || uncertain} aria-invalid={Boolean(errors.title)} aria-describedby={errors.title ? 'recurring-title-error' : undefined} required /><FieldMessage id="recurring-title-error" message={errors.title} /></label>
      <div className="form-row"><label className="field" htmlFor="recurring-amount"><span>Сумма</span><input id="recurring-amount" name="amount" inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} placeholder="45000 или 45000,50" disabled={busy || uncertain} aria-invalid={Boolean(errors.amount)} aria-describedby={errors.amount ? 'recurring-amount-error' : 'recurring-amount-hint'} required /><span id="recurring-amount-hint" className="field-hint">Например: 45000, 45000,50 или 45000.50</span><FieldMessage id="recurring-amount-error" message={errors.amount} /></label><label className="field" htmlFor="recurring-currency"><span>Валюта</span><SelectField id="recurring-currency" value={currency} onChange={value => setCurrency(value as Currency)} options={[{value: "RUB", label: "RUB · рубль"}, {value: "USD", label: "USD · доллар"}, {value: "EUR", label: "EUR · евро"}]} disabled={busy || uncertain} aria-invalid={Boolean(errors.currency)} aria-describedby={errors.currency ? 'recurring-currency-error' : undefined}/><FieldMessage id="recurring-currency-error" message={errors.currency} /></label></div>
      <label className="field" htmlFor="recurring-date"><span>Первый срок оплаты</span><DatePicker id="recurring-date" today={today} aria-label="Первый срок оплаты" value={firstDueDate} onChange={setFirstDueDate} disabled={busy || uncertain} aria-invalid={Boolean(errors.first_due_date)} aria-describedby={errors.first_due_date ? 'recurring-date-error' : 'recurring-date-hint'} required /><span id="recurring-date-hint" className="field-hint">Можно выбрать прошедшую дату для учёта старых обязательств.</span><FieldMessage id="recurring-date-error" message={errors.first_due_date} /></label>
      <div className="field"><span>Периодичность</span><div className="static-field">↻ Каждый месяц</div><span className="field-hint">Если в месяце нет выбранного числа, сроком станет его последний день.</span><FieldMessage id="recurring-periodicity-error" message={errors.periodicity} /></div>
      <section className="recurring-preview" aria-labelledby="recurring-preview-title">
        <div className="recurring-preview-heading"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="5" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.6" /><path d="M8 3v4M16 3v4M4 10h16M8 14h3M8 17h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg><h3 id="recurring-preview-title">Предварительные сроки</h3><span>3 месяца</span></div>
        <div className="recurring-preview-dates" aria-live="polite" aria-atomic="true">
          {dueDates.length ? <ol>{dueDates.map((date, index) => <li key={index}><span className="recurring-preview-step">{String(index + 1).padStart(2, '0')}</span><time dateTime={date}>{calendarDate(date)}</time></li>)}</ol> : <p className="recurring-preview-empty">Выберите первый срок — покажем три ближайшие даты.</p>}
          {dueDates.length > 0 && dueDates.length < 3 && <p className="recurring-preview-empty">Дальнейшие даты выходят за поддерживаемый диапазон до 9999 года.</p>}
        </div>
        <p className="recurring-preview-note">Это предварительный расчёт. Окончательные сроки рассчитывает сервер.</p>
      </section>
      <div className="notice"><strong>Напоминания в Telegram</strong><p>Неоплаченные периоды будут напоминать о себе за 3 дня до срока. Для уже близкого или прошедшего срока напоминание готовится сразу.</p></div>
      {uncertain ? <UncertainCreate onCheck={onCheck} /> : error != null && <ErrorNotice error={error} />}
      <div className="form-actions"><button data-drawer-close className="btn btn-secondary" type="button" disabled={busy} onClick={() => uncertain ? onCheck() : onClose()}>Отмена</button><button className="btn btn-primary" type="submit" disabled={busy || uncertain}>{busy ? 'Создаём…' : 'Добавить платёж'}</button></div>
    </form>
  </Drawer>;
}

export function UsersView({ onChanged, notify, isAdmin, timezone }: AdminViewProps) {
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<Page<User> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [editing, setEditing] = useState<User | 'new' | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);
  const [busyDelete, setBusyDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<unknown>(null);
  const deleteGuard = useRef(false);

  useEffect(() => {
    if (!isAdmin) return;
    let alive = true;
    setLoading(true);
    setLoadError(null);
    api.listUsers({ limit: PAGE_SIZE, offset }).then(result => {
      if (!alive) return;
      if (offset > 0 && result.items.length === 0 && result.total <= offset) {
        setOffset(Math.max(0, Math.floor(Math.max(0, result.total - 1) / PAGE_SIZE) * PAGE_SIZE));
        return;
      }
      setPage(result);
    }).catch(error => { if (alive) setLoadError(error); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [isAdmin, offset, refresh]);

  function reload() { setRefresh(value => value + 1); }
  function changed() { reload(); onChanged(); }

  async function confirmDelete() {
    if (!deleting || deleteGuard.current) return;
    deleteGuard.current = true;
    setBusyDelete(true);
    setDeleteError(null);
    try {
      await api.deleteUser(deleting.id);
      setDeleting(null);
      notify('Пользователь удалён. Платёжная история сохранена.');
      changed();
    } catch (error) { setDeleteError(error); }
    finally { deleteGuard.current = false; setBusyDelete(false); }
  }

  if (!isAdmin) return <Forbidden />;
  return <section aria-labelledby="users-heading">
    <PageHeader kind="users" id="users-heading" title="Пользователи" eyebrow="Команда и доступ" description="Дайте команде доступ к общему списку платежей.">
      <button className="btn btn-primary" onClick={() => setEditing('new')}><PlusIcon />Добавить пользователя</button>
    </PageHeader>
    <div className="panel">
      <div className="toolbar"><h2 className="panel-title">Участники команды</h2><span className="pill">Обычные пользователи</span></div>
      {loadError ? <ErrorNotice error={loadError} onRetry={reload} /> : loading ? <div className="loading-state" role="status"><span className="spinner" />Загружаем пользователей…</div> : !page?.items.length ? <div className="empty-state"><span className="empty-symbol" aria-hidden="true">+</span><h2>Пригласите первого участника</h2><p className="muted">Пользователи смогут смотреть платежи и отмечать оплату каждого периода.</p><button className="btn btn-primary" onClick={() => setEditing('new')}><PlusIcon />Добавить пользователя</button></div> : <>
        <div className="table-wrap"><table className="data-table"><thead><tr><th scope="col">Пользователь</th><th scope="col">Доступ</th><th scope="col">Дата создания</th><th scope="col"><span className="sr-only">Действия</span></th></tr></thead><tbody>{page.items.map(user => <tr key={user.id}><td><div className="user-cell"><span className="avatar" aria-hidden="true">{user.username.slice(0, 2).toUpperCase()}</span><strong className="payment-title">{user.username}</strong></div></td><td data-label="Доступ"><span className="status status-neutral">Пользователь</span><span className="muted table-caption">Просмотр и отметка оплаты</span></td><td className="date-cell" data-label="Дата создания">{createdDate(user.created_at, timezone)}</td><td><div className="inline-actions"><button className="btn btn-secondary btn-small" aria-label={`Изменить пользователя ${user.username}`} onClick={() => setEditing(user)}>Изменить</button><button className="icon-button danger-text" title="Удалить пользователя" aria-label={`Удалить пользователя ${user.username}`} onClick={() => { setDeleteError(null); setDeleting(user); }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg></button></div></td></tr>)}</tbody></table></div>
        <Pagination total={page.total} limit={page.limit} offset={page.offset} onPage={setOffset} />
      </>}
    </div>
    <p className="section-note">Учётная запись администратора задаётся в конфигурации сервера и защищена от изменения в этом разделе.</p>
    {editing != null && <UserForm key={editing === 'new' ? 'new' : editing.id} user={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { notify(editing === 'new' ? 'Пользователь добавлен.' : 'Изменения пользователя сохранены.'); setEditing(null); changed(); }} onCheck={() => { setEditing(null); setOffset(0); reload(); }} />}
    {deleting && <Drawer canClose={!busyDelete} title="Удалить пользователя?" subtitle={deleting.username} onClose={() => { if (!busyDelete) setDeleting(null); }}><div className="notice"><strong>Доступ будет отозван сразу.</strong><p>Все сессии пользователя завершатся. Его удаление не затронет платежи, отметки об оплате или историю команды.</p></div>{deleteError != null && <ErrorNotice error={deleteError} />}<div className="form-actions"><button data-drawer-close className="btn btn-secondary" type="button" disabled={busyDelete} onClick={() => setDeleting(null)}>Отмена</button><button className="btn btn-danger" disabled={busyDelete} onClick={confirmDelete}>{busyDelete ? 'Удаляем…' : 'Удалить пользователя'}</button></div></Drawer>}
  </section>;
}

function UserForm({ user, onClose, onSaved, onCheck }: { user: User | null; onClose: () => void; onSaved: () => void; onCheck: () => void }) {
  const [username, setUsername] = useState(user?.username ?? '');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const guard = useRef(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (guard.current || uncertain) return;
    const nextErrors: FieldErrors = {};
    if (!/^[a-z0-9_.-]{3,64}$/.test(username)) nextErrors.username = 'От 3 до 64 символов: латинские строчные буквы, цифры, _, . и -.';
    if ((!user || password !== '') && (password.length < 8 || password.length > 128)) nextErrors.password = 'Пароль должен содержать от 8 до 128 символов.';
    if (user && username === user.username && password === '') nextErrors.username = 'Измените логин или укажите новый пароль.';
    setErrors(nextErrors);
    setError(null);
    if (Object.keys(nextErrors).length) return;
    guard.current = true;
    setBusy(true);
    try {
      if (user) {
        await api.updateUser(user.id, { ...(username !== user.username ? { username } : {}), ...(password !== '' ? { password } : {}) });
      } else {
        await api.createUser({ username, password });
      }
      setPassword('');
      onSaved();
    } catch (caught) {
      const apiFields = fieldsFromError(caught);
      if (caught instanceof ApiError && caught.code === 'USERNAME_TAKEN' && !apiFields.username) apiFields.username = 'Этот логин уже занят. Выберите другой.';
      setErrors(apiFields);
      setError(caught);
      setUncertain(!user && resultUncertain(caught));
    } finally { guard.current = false; setBusy(false); }
  }

  return <Drawer canClose={!busy} title={user ? 'Изменить пользователя' : 'Новый пользователь'} subtitle={user ? `Настройки доступа для ${user.username}` : 'Участник сможет просматривать платежи и отмечать оплату.'} onClose={() => { if (!busy) { if (uncertain) onCheck(); else onClose(); } }}>
    <form className="form-grid" noValidate onSubmit={submit}>
      <label className="field" htmlFor="user-username"><span>Логин</span><input id="user-username" name="username" autoComplete="off" autoCapitalize="none" spellCheck={false} value={username} onChange={event => setUsername(event.target.value)} maxLength={64} placeholder="ivan.petrov" disabled={busy || uncertain} aria-invalid={Boolean(errors.username)} aria-describedby={errors.username ? 'user-username-error' : 'user-username-hint'} required /><span id="user-username-hint" className="field-hint">3–64 символа: a–z, 0–9, _, . и -</span><FieldMessage id="user-username-error" message={errors.username} /></label>
      <label className="field" htmlFor="user-password"><span>{user ? 'Новый пароль' : 'Пароль'}</span><div className="password-field"><input id="user-password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} maxLength={128} placeholder={user ? 'Оставьте пустым, чтобы сохранить' : 'Не менее 8 символов'} disabled={busy || uncertain} aria-invalid={Boolean(errors.password)} aria-describedby={errors.password ? 'user-password-error' : 'user-password-hint'} required={!user} /><button type="button" className="password-toggle" onClick={() => setShowPassword(value => !value)} aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'} aria-pressed={showPassword}>{showPassword ? 'Скрыть' : 'Показать'}</button></div><span id="user-password-hint" className="field-hint">{user ? 'При смене пароля все текущие сессии этого пользователя завершатся.' : 'От 8 до 128 символов. Пробелы и регистр сохраняются.'}</span><FieldMessage id="user-password-error" message={errors.password} /></label>
      <div className="notice"><strong>Доступ обычного пользователя</strong><p>Просмотр общего списка, истории и сводки; подтверждение, отмена и исправление даты оплаты. Управление правилами и участниками доступно администратору.</p></div>
      {uncertain ? <UncertainCreate onCheck={onCheck} /> : error != null && <ErrorNotice error={error} />}
      <div className="form-actions"><button data-drawer-close type="button" className="btn btn-secondary" onClick={() => uncertain ? onCheck() : onClose()} disabled={busy}>Отмена</button><button className="btn btn-primary" type="submit" disabled={busy || uncertain}>{busy ? 'Сохраняем…' : user ? 'Сохранить изменения' : 'Добавить пользователя'}</button></div>
    </form>
  </Drawer>;
}

