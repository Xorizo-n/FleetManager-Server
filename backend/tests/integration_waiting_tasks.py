"""Ожидающие задачи и цепочки плейбуков на настоящей БД (блокировки, JSONB).

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
db.query(TaskRun).filter(TaskRun.playbook_name.like("it-%")).delete(synchronize_session=False)
db.query(Host).filter(Host.hostname.like("IT-WAIT-%")).delete(synchronize_session=False)
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


# 1. Один запуск на 4 выключенных + 1 включённый: две задачи, а не пять
now, waiting = wt.create_task_sequence(db, task_type=TaskType.playbook, host_ids=h + [on], created_by=None, steps=[step("it-a.yml")])
assert [t.host_ids for t in now] == [[on]], now
assert len(waiting) == 1 and sorted(waiting[0].host_ids) == sorted(h)
w_old = waiting[0].id

# 2. Повторное назначение на h0,h1: они уходят из старой задачи
_, waiting = wt.create_task_sequence(db, task_type=TaskType.playbook, host_ids=h[:2], created_by=None, steps=[step("it-a.yml")])
w_new = waiting[0].id
assert sorted(get(w_old).host_ids) == sorted(h[2:]), get(w_old).host_ids
assert "назначена снова" in get(w_old).log_output
# Другой плейбук на те же ПК не трогает
_, other = wt.create_task_sequence(db, task_type=TaskType.playbook, host_ids=h[2:3], created_by=None, steps=[step("it-other.yml")])
assert sorted(get(w_old).host_ids) == sorted(h[2:])
# Назначение h2,h3 заново опустошает старую задачу — она отменена
wt.create_task_sequence(db, task_type=TaskType.playbook, host_ids=h[2:], created_by=None, steps=[step("it-a.yml")])
assert get(w_old).status == TaskStatus.cancelled and get(w_old).host_ids == []

# 3. h0 и h1 появились: один запуск, одна дочерняя задача на двоих
assert wt.release_waiting_tasks(db, hosts[0].id) == 1
assert wt.release_waiting_tasks(db, hosts[1].id) == 0  # запуск уже назначен — просто добавился
assert wt.release_waiting_tasks(db, hosts[1].id) == 0  # повторный heartbeat не задваивает
assert flushes == [str(w_new)], flushes
assert sorted(get(w_new).ready_host_ids) == sorted(h[:2])
child_id = wt.flush_released(str(w_new))
child = get(child_id)
assert sorted(child.host_ids) == sorted(h[:2]) and child.parent_id == w_new and child.status == TaskStatus.queued
assert child.extra_vars == {"x": 1}
assert get(w_new).status == TaskStatus.released, get(w_new).status
assert enqueued[-1] == child.id

# 4. Цепочка из трёх плейбуков на выключенных h2,h3 и включённый; прежние задачи с ними убираем
for leftover in db.query(TaskRun).filter(TaskRun.playbook_name.like("it-%"), TaskRun.status == TaskStatus.waiting):
    wt.cancel_waiting_task(db, leftover, "test")
enqueued.clear(); flushes.clear()
now, waiting = wt.create_task_sequence(db, task_type=TaskType.playbook, host_ids=h[2:] + [on], created_by=None,
                                       steps=[step("it-1.yml"), step("it-2.yml"), step("it-3.yml")])
assert [t.status for t in now] == [TaskStatus.queued, TaskStatus.pending, TaskStatus.pending]
# Отменённый второй плейбук пропускается: после первого идёт третий
assert wt.cancel_waiting_task(db, now[1], "test")
assert wt.start_followers(db, now[0].id) == 1 and enqueued == [now[2].id]
assert get(now[2].id).status == TaskStatus.queued

# h2 появился: освобождает только первую задачу цепочки
assert wt.release_waiting_tasks(db, hosts[2].id) == 1
assert flushes == [str(waiting[0].id)], flushes
assert h[2] in get(waiting[1].id).host_ids
first = get(wt.flush_released(str(waiting[0].id)))
assert first.playbook_name == "it-1.yml" and first.host_ids == [h[2]]
second = db.query(TaskRun).filter(TaskRun.parent_id == waiting[1].id).one()
third = db.query(TaskRun).filter(TaskRun.parent_id == waiting[2].id).one()
assert (second.status, second.after_task_id, second.host_ids) == (TaskStatus.pending, first.id, [h[2]])
assert (third.status, third.after_task_id) == (TaskStatus.pending, second.id)
for w in waiting:
    assert get(w.id).host_ids == [h[3]] and get(w.id).status == TaskStatus.waiting

# 5. Отмена ожидающей задачи, пока ПК собираются: запуска нет
assert wt.release_waiting_tasks(db, hosts[3].id) == 1
assert wt.cancel_waiting_task(db, get(waiting[0].id), "test")
assert wt.flush_released(str(waiting[0].id)) is None
# h3 ещё держат второй и третий — теперь второй стал первым в цепочке
assert wt.release_waiting_tasks(db, hosts[3].id) == 1

db.query(TaskRun).filter(TaskRun.playbook_name.like("it-%")).delete(synchronize_session=False)
db.query(Host).filter(Host.hostname.like("IT-WAIT-%")).delete(synchronize_session=False)
db.commit()
print("integration_waiting_tasks: ok")
