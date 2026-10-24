"""Запуски с состоянием по ПК, ожидание и цепочки плейбуков на настоящей БД (блокировки, JSONB).

Запуск на копии схемы: DATABASE_URL=.../fm_migtest python tests/integration_waiting_tasks.py
"""
from unittest import mock

from database import SessionLocal
from models.host import Host, HostOS, HostStatus
from models.task import TaskRun, TaskStatus, TaskType
from services import waiting_tasks as wt

enqueued, flushes = [], []
mock.patch.object(wt, "enqueue", side_effect=lambda task, countdown=None: enqueued.append(task.id)).start()
mock.patch.object(wt.flush_released, "apply_async", side_effect=lambda args, countdown: flushes.append(args[0])).start()

db = SessionLocal()


def cleanup():
    db.query(TaskRun).filter(TaskRun.playbook_name.like("it-%"), TaskRun.parent_id.isnot(None)).delete(synchronize_session=False)
    db.query(TaskRun).filter(TaskRun.playbook_name.like("it-%")).delete(synchronize_session=False)
    db.query(Host).filter(Host.hostname.like("IT-WAIT-%")).delete(synchronize_session=False)
    db.commit()


cleanup()
hosts = [Host(hostname=f"IT-WAIT-{i}", os=HostOS.windows_11, status=HostStatus.offline) for i in range(4)]
online = Host(hostname="IT-WAIT-ON", os=HostOS.windows_11, status=HostStatus.online)
db.add_all(hosts + [online])
db.commit()
h = [str(x.id) for x in hosts]
on = str(online.id)


def get(task_id):
    db.expire_all()
    return db.get(TaskRun, task_id)


def step(name):
    return {"playbook_name": name, "extra_vars": {"x": 1}}


def run(host_ids, *names):
    return wt.create_task_sequence(db, task_type=TaskType.playbook, host_ids=host_ids, created_by=None, steps=[step(n) for n in names])


def finish(execution_id, status, states=None):
    """Как исполнитель: итог задачи и по ПК, затем сигнал task_postrun."""
    execution = get(execution_id)
    wt.execution_started(db, execution.id)
    execution = get(execution_id)
    execution.status = status
    execution.host_states = states
    db.commit()
    wt.execution_finished(db, execution.id)


# 1. Один запуск на 4 выключенных + 1 включённый: одна запись, выполняет дочерняя задача
groups, execution = run(h + [on], "it-a.yml")
old = groups[0]
assert execution.parent_id == old.id and execution.host_ids == [on]
assert get(old.id).host_states == {**{x: "waiting" for x in h}, on: "queued"}
wt.execution_started(db, execution.id)
assert get(old.id).status == TaskStatus.running and get(old.id).host_states[on] == "running"
finish(execution.id, TaskStatus.failed, {on: "failed"})
assert get(old.id).host_states[on] == "failed" and get(old.id).status == TaskStatus.waiting

# 2. Повторное назначение на h0,h1: в старом запуске они отменены
groups, _ = run(h[:2], "it-a.yml")
new = groups[0]
states = get(old.id).host_states
assert (states[h[0]], states[h[1]], states[h[2]]) == ("cancelled", "cancelled", "waiting"), states
assert "назначена снова" in get(old.id).log_output
# Другой плейбук на те же ПК не трогает
run(h[2:3], "it-other.yml")
assert get(old.id).host_states[h[2]] == "waiting"
# Назначение h2,h3 заново: в старом ждать некого — запуск закончен с итогом failed (у ПК в сети)
run(h[2:], "it-a.yml")
assert get(old.id).status == TaskStatus.failed and get(old.id).finished_at is not None

# 3. h0 и h1 появились: одна пачка на двоих
assert wt.release_waiting_tasks(db, hosts[0].id) == 1
assert wt.release_waiting_tasks(db, hosts[1].id) == 0  # пачка уже назначена — просто добавился
assert wt.release_waiting_tasks(db, hosts[1].id) == 0  # повторный heartbeat не задваивает
assert flushes == [str(new.id)], flushes
assert get(new.id).status == TaskStatus.queued
batch = get(wt.flush_released(str(new.id)))
assert sorted(batch.host_ids) == sorted(h[:2]) and batch.parent_id == new.id and batch.extra_vars == {"x": 1}
assert enqueued[-1] == batch.id
finish(batch.id, TaskStatus.failed, {h[0]: "success", h[1]: "failed"})
assert get(new.id).host_states == {h[0]: "success", h[1]: "failed"} and get(new.id).status == TaskStatus.failed

# 4. Цепочка из трёх плейбуков на выключенных h2,h3 и включённый; прежние запуски с ними отменяем
for leftover in db.query(TaskRun).filter(TaskRun.playbook_name.like("it-%"), TaskRun.grouped.is_(True), TaskRun.finished_at.is_(None)):
    wt.cancel_waiting_task(db, leftover, "test")
enqueued.clear(); flushes.clear()
groups, execution = run(h[2:] + [on], "it-1.yml", "it-2.yml", "it-3.yml")
execs = [db.query(TaskRun).filter(TaskRun.parent_id == g.id).one() for g in groups]
assert [e.status for e in execs] == [TaskStatus.queued, TaskStatus.pending, TaskStatus.pending]
assert get(groups[1].id).status == TaskStatus.pending  # ПК в сети ждут первый плейбук, h2,h3 — включения
# Отменённый второй плейбук пропускается: после первого идёт третий
assert wt.cancel_waiting_task(db, get(groups[1].id), "test")
assert get(groups[1].id).host_states[on] == "cancelled" and get(execs[1].id).status == TaskStatus.cancelled
finish(execs[0].id, TaskStatus.success)
assert enqueued == [execs[2].id], enqueued
assert get(execs[2].id).status == TaskStatus.queued and get(groups[2].id).host_states[on] == "queued"

# h2 появился: освобождает только первый запуск цепочки (во втором он отменён)
assert wt.release_waiting_tasks(db, hosts[2].id) == 1
assert flushes == [str(groups[0].id)], flushes
assert get(groups[2].id).host_states[h[2]] == "waiting"
first = get(wt.flush_released(str(groups[0].id)))
assert first.playbook_name == "it-1.yml" and first.host_ids == [h[2]]
third = db.query(TaskRun).filter(TaskRun.parent_id == groups[2].id, TaskRun.id != execs[2].id).one()
assert (third.status, third.after_task_id, third.host_ids) == (TaskStatus.pending, first.id, [h[2]])
assert get(groups[2].id).host_states[h[2]] == "pending"
enqueued.clear()
finish(first.id, TaskStatus.failed)
assert enqueued == [third.id] and get(groups[0].id).host_states[h[2]] == "failed"

# 5. Отмена запуска, пока ПК собираются в пачку: пачки нет
assert wt.release_waiting_tasks(db, hosts[3].id) == 1
assert wt.cancel_waiting_task(db, get(groups[0].id), "test")
assert get(groups[0].id).host_states[h[3]] == "cancelled"
assert wt.flush_released(str(groups[0].id)) is None
# h3 ещё ждёт третий плейбук — теперь он первый в цепочке
assert wt.release_waiting_tasks(db, hosts[3].id) == 1

cleanup()
print("integration_waiting_tasks: ok")
