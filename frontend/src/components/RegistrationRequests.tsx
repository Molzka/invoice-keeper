import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, API_MODE } from '../api/client';
import type { RegistrationRequest, RegistrationRequestList } from '../types/api';
import { Drawer, ErrorNotice, Pagination } from './UI';

type Status = RegistrationRequest['status'];
type Selection = { request: RegistrationRequest; action: 'approve' | 'reject' | 'view' };
const PAGE_SIZE = 10;
const STATUS_LABELS: Record<Status, string> = {
  pending: 'Ожидает решения', approved: 'Одобрена', rejected: 'Отклонена',
};
const EMPTY_LABELS: Record<Status, string> = {
  pending: 'Новых заявок нет', approved: 'Одобренных заявок пока нет', rejected: 'Отклонённых заявок пока нет',
};

function dateLabel(value: string, timezone: string) {
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: timezone, day: '2-digit', month: 'short', year: 'numeric',
  }).format(new Date(value));
}

function preview(value: string) {
  const characters = Array.from(value);
  return characters.length > 120 ? `${characters.slice(0, 120).join('')}…` : value;
}

export function RegistrationRequests({ timezone, notify, onChanged }: {
  timezone: string; notify: (message: string) => void; onChanged: () => void;
}) {
  const [status, setStatus] = useState<Status>('pending');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<RegistrationRequestList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selection, setSelection] = useState<Selection | null>(null);

  useEffect(() => {
    if (API_MODE !== 'real') return;
    let alive = true;
    setLoading(true);
    setError(null);
    api.registrationRequests({ status, limit: PAGE_SIZE, offset }).then(result => {
      if (!alive) return;
      if (offset > 0 && result.items.length === 0 && result.total <= offset) {
        setOffset(Math.max(0, Math.floor(Math.max(0, result.total - 1) / PAGE_SIZE) * PAGE_SIZE));
        return;
      }
      setPage(result);
    }).catch(caught => { if (alive) setError(caught); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [status, offset, refresh]);

  function reload() { setRefresh(value => value + 1); }
  function checkList() { setSelection(null); reload(); }

  if (API_MODE !== 'real') return <div className="panel empty-state">
    <h2>Заявки доступны при подключении к серверу</h2>
    <p className="muted">В демонстрации заявки не отправляются и не рассматриваются. Для работы с обращениями сотрудников подключите настоящий API.</p>
  </div>;

  return <>
    <div className="panel">
      <div className="toolbar">
        <h2 className="panel-title">Заявки сотрудников</h2>
        <button type="button" className="btn btn-secondary btn-small" disabled={loading} onClick={reload}>Обновить список</button>
      </div>
      <div className="status-tabs" role="group" aria-label="Решение по заявке">
        {([['pending', 'Ожидают решения'], ['approved', 'Одобрены'], ['rejected', 'Отклонены']] as const).map(([value, label]) =>
          <button key={value} type="button" className={`status-tab ${status === value ? 'active' : ''}`} aria-pressed={status === value}
            onClick={() => { setOffset(0); setStatus(value); }}>{label}</button>)}
      </div>
      {error ? <ErrorNotice error={error} onRetry={reload} /> : loading ?
        <div className="loading-state" role="status"><span className="spinner" />Загружаем заявки…</div> : !page?.items.length ?
          <div className="empty-state"><h2>{EMPTY_LABELS[status]}</h2><p className="muted">{status === 'pending'
            ? 'Здесь появятся обращения сотрудников. До вашего одобрения доступа к платежам у них нет.'
            : 'Рассмотренные заявки сохраняются здесь вместе с датой решения.'}</p></div> : <>
            <div className="table-wrap"><table className="data-table">
              <caption className="sr-only">Заявки сотрудников: {STATUS_LABELS[status]}</caption>
              <thead><tr><th scope="col">Сотрудник</th><th scope="col">Дата заявки</th><th scope="col">Решение</th><th scope="col">Действия</th></tr></thead>
              <tbody>{page.items.map(item => <tr key={item.id}>
                <td><strong className="payment-title">{item.username}</strong><span className="muted table-caption registration-message">{preview(item.message)}</span></td>
                <td className="date-cell" data-label="Дата заявки">{dateLabel(item.created_at, timezone)}</td>
                <td data-label="Решение"><span className={`status ${item.status === 'approved' ? 'status-success' : 'status-neutral'}`}>{STATUS_LABELS[item.status]}</span>
                  {item.reviewed_at && <span className="muted table-caption">{dateLabel(item.reviewed_at, timezone)}</span>}</td>
                <td><div className="inline-actions">{item.status === 'pending' ? <>
                  <button type="button" className="btn btn-primary btn-small" aria-label={`Одобрить заявку ${item.username}`} onClick={() => setSelection({ request: item, action: 'approve' })}>Одобрить</button>
                  <button type="button" className="btn btn-secondary btn-small" aria-label={`Отклонить заявку ${item.username}`} onClick={() => setSelection({ request: item, action: 'reject' })}>Отклонить</button>
                </> : <button type="button" className="btn btn-secondary btn-small" aria-label={`Подробности заявки ${item.username}`} onClick={() => setSelection({ request: item, action: 'view' })}>Подробности</button>}</div></td>
              </tr>)}</tbody>
            </table></div>
            <Pagination total={page.total} limit={page.limit} offset={page.offset} onPage={setOffset} />
          </>}
    </div>
    <p className="section-note">Одобрение создаёт обычного пользователя. Пароль выбирает сотрудник при подаче заявки; он не показывается администратору.</p>
    {selection && <DecisionDrawer key={`${selection.request.id}:${selection.action}`} selection={selection} timezone={timezone}
      onClose={() => setSelection(null)} onCheck={checkList} onSaved={() => {
        notify(selection.action === 'approve' ? 'Заявка одобрена. Сотрудник может войти с выбранным паролем.' : 'Заявка отклонена. Доступ не предоставлен.');
        setSelection(null); reload(); onChanged();
      }} />}
  </>;
}

function DecisionDrawer({ selection: { request, action }, timezone, onClose, onSaved, onCheck }: {
  selection: Selection; timezone: string; onClose: () => void; onSaved: () => void; onCheck: () => void;
}) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [checkRequired, setCheckRequired] = useState(false);
  const [noteError, setNoteError] = useState('');
  const guard = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (guard.current || checkRequired || action === 'view') return;
    if (Array.from(note).length > 300 || note.includes('\0')) {
      setNoteError('Причина должна содержать не более 300 символов без служебных знаков.');
      return;
    }
    guard.current = true;
    setBusy(true); setError(null); setNoteError('');
    try {
      if (action === 'approve') await api.approveRegistration(request.id);
      else await api.rejectRegistration(request.id, note.trim() || undefined);
      if (mounted.current) onSaved();
    } catch (caught) {
      if (!mounted.current) return;
      setError(caught);
      setCheckRequired(caught instanceof ApiError && ['TIMEOUT', 'NETWORK_ERROR', 'REGISTRATION_REVIEWED', 'REGISTRATION_NOT_FOUND'].includes(caught.code));
    } finally { guard.current = false; if (mounted.current) setBusy(false); }
  }

  return <Drawer title={action === 'approve' ? 'Предоставить доступ?' : action === 'reject' ? 'Отклонить заявку?' : 'Решение по заявке'}
    subtitle={request.username} canClose={!busy} onClose={checkRequired ? onCheck : onClose}>
    <p className="muted">Заявка от {dateLabel(request.created_at, timezone)}</p>
    <div className="notice"><strong>Сообщение сотрудника</strong><p className="registration-message">{request.message}</p></div>
    {action === 'view' ? <>
      <p><strong>{STATUS_LABELS[request.status]}</strong>{request.reviewed_at && ` · ${dateLabel(request.reviewed_at, timezone)}`}</p>
      {request.decision_note && <div className="notice"><strong>Причина решения</strong><p className="registration-message">{request.decision_note}</p></div>}
      <div className="form-actions"><button data-drawer-close type="button" className="btn btn-secondary" onClick={onClose}>Закрыть</button></div>
    </> : <form onSubmit={submit}>
      <p className="muted">{action === 'approve'
        ? 'Проверьте, что это сотрудник вашей команды. После одобрения он сможет войти, просматривать платежи и отмечать оплату.'
        : 'Аккаунт по этой заявке создан не будет. Сотрудник не получит доступа к платежам.'}</p>
      {action === 'reject' && <label className="field" htmlFor="registration-note">Причина отказа <span className="muted">(необязательно)</span>
        <textarea id="registration-note" value={note} onChange={event => setNote(event.target.value)} disabled={busy || checkRequired}
          aria-invalid={!!noteError} aria-describedby={noteError ? 'registration-note-error' : 'registration-note-hint'} rows={3} />
        <small id="registration-note-hint" className="muted">До 300 символов. Причина сохранится в истории заявки.</small>
        {noteError && <span id="registration-note-error" className="field-error" role="alert">{noteError}</span>}
      </label>}
      {error != null && <ErrorNotice error={error} />}
      {checkRequired && <div className="notice" role="alert"><strong>Сначала проверьте состояние заявки.</strong><p>Решение могло сохраниться или заявку уже рассмотрел другой администратор.</p>
        <button type="button" className="btn btn-secondary" onClick={onCheck}>Закрыть и проверить список</button></div>}
      <div className="form-actions"><button data-drawer-close type="button" className="btn btn-secondary" disabled={busy} onClick={checkRequired ? onCheck : onClose}>Отмена</button>
        <button type="submit" className={`btn ${action === 'approve' ? 'btn-primary' : 'btn-danger'}`} disabled={busy || checkRequired}>
          {busy ? 'Сохраняем решение…' : action === 'approve' ? 'Одобрить и создать аккаунт' : 'Отклонить заявку'}</button></div>
    </form>}
  </Drawer>;
}
