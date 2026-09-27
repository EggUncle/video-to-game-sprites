"""Local estimates and a locked budget ledger; never an account balance."""
import json, os, fcntl, hashlib
from pathlib import Path
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
from datetime import date


def number(value):
    n=Decimal(str(value))
    if not n.is_finite() or n<0:raise ValueError('Cost values must be finite and nonnegative')
    return n


def quote(job,policy):
    cfg=json.loads((Path(job)/'job.json').read_text())
    if cfg['model']!='doubao-seedance-2-0-mini-260615' or cfg['ratio']!='1:1' or cfg['resolution'] not in ('480p','720p'):
        raise ValueError('Estimator only supports mini, square 480p/720p image input')
    if date.today()>date.fromisoformat(policy['valid_until']):raise ValueError('Price policy expired; verify prices before submission')
    side={'480p':640,'720p':960}[cfg['resolution']]
    tokens=number(cfg['duration'])*side*side*24/1024
    rate=number(policy['yuan_per_million_tokens'])
    cost=tokens*rate/1000000
    margin=number(policy.get('reserve_multiplier',1.2))
    if margin<1:raise ValueError('Reservation multiplier must be >= 1')
    return {'estimated_tokens':int(tokens),'estimated_yuan':str(cost),
      'reserved_yuan':str((cost*margin).quantize(Decimal('.0001'),rounding=ROUND_CEILING)),
      'yuan_per_million_tokens':str(rate),'price_basis':policy['price_basis'],
      'bill_amount_yuan':None,'account_balance_yuan':None,
      'job_sha256':hashlib.sha256((Path(job)/'job.json').read_bytes()).hexdigest()}


@contextmanager
def locked(path):
    path=Path(path).resolve()
    with open(str(path)+'.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=json.loads(path.read_text())
        yield data
        tmp=Path(str(path)+'.tmp')
        with open(tmp,'w') as f:
            os.chmod(tmp,0o600);json.dump(data,f,ensure_ascii=False,indent=2)
        os.replace(tmp,path)


def init(path,total,per_job):
    data={'total_budget_yuan':str(number(total)),'per_job_limit_yuan':str(number(per_job)),'jobs':{}}
    with open(path,'x') as f:json.dump(data,f,indent=2)
    return data


def reserve(job,ledger,policy):
    q=quote(job,json.loads(Path(policy).read_text()));key=str(Path(job).resolve())
    with locked(ledger) as data:
        if key in data['jobs']:
            old=data['jobs'][key]
            if old['job_sha256']!=q['job_sha256']:raise ValueError('Reserved job changed')
            return old
        used=sum((number(v['budget_charge_yuan']) for v in data['jobs'].values()),Decimal(0))
        amount=number(q['reserved_yuan'])
        if amount>number(data['per_job_limit_yuan']):raise ValueError('Per-job budget exceeded; no submission')
        if used+amount>number(data['total_budget_yuan']):raise ValueError('Total budget exceeded; no submission')
        q.update(budget_charge_yuan=str(amount),accounting_status='reserved_or_unknown')
        data['jobs'][key]=q
    return q


def reconcile(job,ledger,state):
    key=str(Path(job).resolve())
    with locked(ledger) as data:
        if key not in data['jobs']:return
        row=data['jobs'][key];row['task_id']=state.get('id');row['task_status']=state['status']
        tokens=(state.get('usage') or {}).get('completion_tokens')
        if tokens is not None and state['status']=='succeeded':
            actual=number(tokens)*number(row['yuan_per_million_tokens'])/1000000
            row.update(actual_tokens=tokens,usage_based_estimated_yuan=str(actual),budget_charge_yuan=str(actual),accounting_status='usage_priced_not_bill')
        # Without usage retain the reservation, even on failure/deletion, until reconciled.


def report(ledger):
    with locked(ledger) as data:
        used=sum((number(v['budget_charge_yuan']) for v in data['jobs'].values()),Decimal(0))
        return {**data,'budget_committed_yuan':str(used),'local_budget_remaining_yuan':str(number(data['total_budget_yuan'])-used),
          'account_balance_yuan':None,'cloud_balance_connected':False,'scope':'Only jobs submitted through this ledger; not a cloud spending cap'}
