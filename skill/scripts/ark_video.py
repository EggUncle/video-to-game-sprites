#!/usr/bin/env python3
"""Persistent Seedance jobs. API Key is read from SEEDDANCE_ARK_API_KEY, never saved."""
import argparse, base64, hashlib, json, os, re, time
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from PIL import Image, ImageOps
from statistics import median
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import cost_control as costs

BASE='https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks'
DEFAULT=dict(model='doubao-seedance-2-0-mini-260615',resolution='480p',ratio='1:1',duration=4,generate_audio=False,watermark=False)
TERMINAL={'succeeded','failed','cancelled','expired'}

class ArkAPIError(RuntimeError):
    def __init__(self,details):
        self.details=details
        super().__init__(json.dumps(details,ensure_ascii=False))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def save(path,data):
    path=Path(path);tmp=path.with_suffix('.tmp')
    with open(tmp,'w') as f:
        os.chmod(tmp,0o600);json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
    os.replace(tmp,path)


def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def task_id(value):
    if not re.fullmatch(r'cgt-[A-Za-z0-9_-]+',value):raise ValueError('Invalid task id')
    return value


def api(method,suffix='',body=None):
    key=os.environ.get('SEEDDANCE_ARK_API_KEY','').strip()
    if not key:raise ValueError('SEEDDANCE_ARK_API_KEY is not configured in this process environment')
    payload=json.dumps(body).encode() if body is not None else None
    req=Request(BASE+suffix,data=payload,method=method,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect()).open(req,timeout=45) as response:
            raw=response.read();return json.loads(raw) if raw else {}
    except HTTPError as e:
        # Retain diagnostic identifiers, never the raw response or credentials.
        try:
            data=json.loads(e.read());detail=data.get('error',{})
            message=str(detail.get('message','')).replace(key,'[REDACTED]')
            request_id=data.get('request_id') or detail.get('request_id') or e.headers.get('X-Request-Id')
            if not request_id:
                match=re.search(r'Request id:\s*([A-Za-z0-9_.:-]+)',message,re.I)
                request_id=match.group(1) if match else None
            def identifier(value):
                value=str(value) if value is not None else ''
                return value if value!=key and re.fullmatch(r'[A-Za-z0-9_.:-]{1,180}',value) else None
            code=identifier(detail.get('code'))
            request_id=identifier(request_id)
            message=re.sub(r'https?://\S+','[URL]',message)
            message=re.sub(r'[A-Za-z0-9_-]{24,}','[IDENTIFIER]',message)
        except (ValueError,AttributeError,TypeError):
            message='No structured error detail';code=None;request_id=None
        raise ArkAPIError({'http_status':e.code,'error_code':code,'request_id':request_id,
                           'message':message[:500]}) from None
    except (URLError,TimeoutError,OSError):
        raise RuntimeError('Ark transport error; submission may have reached server. Do not resubmit blindly.') from None


def plan(image,prompt,out,mode='reference_image',crop=None):
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise ValueError('Job directory must be new or empty')
    text=Path(prompt).read_text().strip()
    if not text:raise ValueError('Prompt is empty')
    im=ImageOps.exif_transpose(Image.open(image)).convert('RGBA')
    if crop:
        x,y,w,h=map(int,crop.split(','))
        if min(x,y)<0 or min(w,h)<1 or x+w>im.width or y+h>im.height:raise ValueError('Crop outside input')
        im=im.crop((x,y,x+w,y+h))
    out.mkdir(parents=True,exist_ok=True)
    # Fit onto a square solid backdrop, retaining the selected view, never inventing views.
    im.thumbnail((560,560),Image.Resampling.LANCZOS)
    corners=[im.getpixel((x,y)) for x,y in [(0,0),(im.width-1,0),(0,im.height-1),(im.width-1,im.height-1)]]
    background=tuple(int(median(c[i] for c in corners)) for i in range(3)) if all(c[3]==255 for c in corners) else (192,192,192)
    canvas=Image.new('RGB',(640,640),background)
    canvas.paste(im,((640-im.width)//2,(640-im.height)//2),im)
    canvas.save(out/'input.png')
    config=dict(DEFAULT,prompt=text,image_role=mode,image_sha256=sha(out/'input.png'),source_sha256=sha(image),crop=crop)
    save(out/'job.json',config);save(out/'state.json',{'status':'planned'})
    (out/'prompt.txt').write_text(text+'\n')
    return {'status':'planned','settings':DEFAULT,'role':mode,'input':str(out/'input.png'),'network_calls':0}


def payload(job):
    job=Path(job);cfg=read(job/'job.json')
    if sha(job/'input.png')!=cfg['image_sha256']:raise ValueError('Input changed; create a new job')
    if cfg['image_role'] not in ['first_frame','reference_image']:raise ValueError('Invalid image role')
    if cfg['model']!=DEFAULT['model']:raise ValueError('This preset supports the requested mini model only')
    if cfg['resolution'] not in ['480p','720p'] or not 4<=cfg['duration']<=15:raise ValueError('Invalid mini settings')
    encoded=base64.b64encode((job/'input.png').read_bytes()).decode()
    return {**{k:cfg.get(k,DEFAULT[k]) for k in DEFAULT},'content':[{'type':'text','text':cfg['prompt']},
      {'type':'image_url','image_url':{'url':'data:image/png;base64,'+encoded},'role':cfg['image_role']}]}


def submit(job,ledger=None,policy=None):
    job=Path(job);state=read(job/'state.json')
    if state.get('id'):return {'id':state['id'],'status':'existing_task_no_resubmit'}
    if state['status']!='planned':raise ValueError('Ambiguous previous submission. Reconcile via list/attach; do not resubmit.')
    if not os.environ.get('SEEDDANCE_ARK_API_KEY','').strip():raise ValueError('SEEDDANCE_ARK_API_KEY is not configured')
    body=payload(job)
    if not ledger or not policy:raise ValueError("Submission requires --ledger and --policy for budget control")
    quote=costs.reserve(job,ledger,policy)
    save(job/"cost.json",quote)
    save(job/"budget.json",{"ledger":str(Path(ledger).resolve())})
    # Exclusive on-disk submission intent also guards concurrent callers and crashes.
    try:
        fd=os.open(job/'submit.intent',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    except FileExistsError:raise ValueError('Submission intent exists; reconcile via list/attach') from None
    save(job/'state.json',{'status':'submission_unknown','submitted_at':time.time()})
    try:
        response=api('POST',body=body)
    except ArkAPIError as error:
        save(job/'create-error.json',error.details)
        raise
    ident=task_id(response['id'])
    state={'id':ident,'status':'queued','submitted_at':time.time()}
    save(job/'state.json',state)
    return state


def status(job):
    job=Path(job);state=read(job/'state.json')
    ident=task_id(state.get('id',''))
    remote=api('GET','/'+ident)
    save(job/'remote.json',remote)
    state.update(status=remote['status'],usage=remote.get('usage'),checked_at=time.time())
    save(job/'state.json',state)
    if (job/'budget.json').exists():costs.reconcile(job,read(job/'budget.json')['ledger'],state)
    return state


def wait(job,seconds=50):
    if not 0<=seconds<=50:raise ValueError('Wait must be between 0 and 50 seconds; resume by calling again')
    deadline=time.monotonic()+seconds
    while True:
        state=status(job)
        if state['status'] in TERMINAL or time.monotonic()>=deadline:return state
        time.sleep(min(10,max(0,deadline-time.monotonic())))


def download(job):
    job=Path(job);target=job/'video.mp4'
    if target.exists():
        digest=sha(target);recorded=read(job/'state.json').get('video_sha256')
        if recorded and digest!=recorded:raise ValueError('Cached video changed; preserve it and review before proceeding')
        return {'file':str(target),'sha256':digest,'cached':True}
    state=status(job)
    if state['status']!='succeeded':raise ValueError('Task is not successful yet')
    url=read(job/'remote.json').get('content',{}).get('video_url','')
    parsed=urlparse(url)
    if parsed.scheme!='https' or not (parsed.hostname or '').endswith(('.volces.com','.volccdn.com','.byteimg.com')):
        raise ValueError('Unexpected video host; review the returned URL locally before downloading')
    # No Authorization header accompanies the signed CDN download, nor any redirect.
    try:
        with build_opener(NoRedirect()).open(Request(url),timeout=45) as response,open(job/'video.part','wb') as f:
            while chunk:=response.read(1024*1024):f.write(chunk)
    except (HTTPError,URLError,TimeoutError,OSError):raise RuntimeError('Video download failed; resume download, not submission') from None
    with open(job/'video.part','rb') as f:header=f.read(32)
    if b'ftyp' not in header:raise ValueError('Downloaded file is not an MP4 container')
    os.replace(job/'video.part',target)
    state['video_sha256']=sha(target);save(job/'state.json',state)
    return {'file':str(target),'sha256':state['video_sha256']}


def attach(job,ident):
    job=Path(job);ident=task_id(ident);old=read(job/'state.json')
    if old.get('id') and old['id']!=ident:raise ValueError('Job already has another task')
    remote=api('GET','/'+ident)
    if remote.get('model')!=read(job/'job.json')['model']:raise ValueError('Recovered task model does not match')
    save(job/'remote.json',remote);save(job/'state.json',{'id':ident,'status':remote['status'],'attached':True})
    return {'id':ident,'status':remote['status']}


def delete(job,confirm):
    job=Path(job);state=status(job);ident=state['id']
    if confirm!=ident:raise ValueError('--confirm-task must match the task to cancel/delete')
    if state['status']=='running':raise ValueError('Running task cannot be cancelled; keep polling')
    api('DELETE','/'+ident)
    state['status']='cancel_requested' if state['status']=='queued' else 'remote_deleted'
    save(job/'state.json',state);return state


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('plan');a.add_argument('--image',required=True);a.add_argument('--prompt',required=True);a.add_argument('--out',required=True);a.add_argument('--mode',choices=['first_frame','reference_image'],default='reference_image');a.add_argument('--crop',help='x,y,width,height in source pixels')
    for name in ['submit','status','wait','download','attach','delete']:
        a=sub.add_parser(name);a.add_argument('job')
        if name=='submit':a.add_argument('--ledger',required=True);a.add_argument('--policy',required=True)
        if name=='wait':a.add_argument('--seconds',type=int,default=50)
        if name=='attach':a.add_argument('--task',required=True)
        if name=='delete':a.add_argument('--confirm-task',required=True)
    a=sub.add_parser('list');a.add_argument('--page',type=int,default=1);a.add_argument('--page-size',type=int,default=20)
    sub.add_parser('doctor')
    a=sub.add_parser('estimate');a.add_argument('job');a.add_argument('--policy',required=True)
    a=sub.add_parser('budget-init');a.add_argument('ledger');a.add_argument('--total',required=True);a.add_argument('--per-job',required=True)
    a=sub.add_parser('cost-report');a.add_argument('ledger')
    a=p.parse_args()
    try:
        if a.cmd=='plan':result=plan(a.image,a.prompt,a.out,a.mode,a.crop)
        elif a.cmd=='doctor':result={'SEEDDANCE_ARK_API_KEY_configured':bool(os.environ.get('SEEDDANCE_ARK_API_KEY','').strip()),'model':DEFAULT['model']}
        elif a.cmd=='estimate':result=costs.quote(a.job,read(a.policy))
        elif a.cmd=='budget-init':result=costs.init(a.ledger,a.total,a.per_job)
        elif a.cmd=='cost-report':result=costs.report(a.ledger)
        elif a.cmd=='submit':result=submit(a.job,a.ledger,a.policy)
        elif a.cmd=='list':
            if not 1<=a.page<=500 or not 1<=a.page_size<=500:raise ValueError('Pagination outside 1..500')
            data=api('GET','?'+urlencode({'page_num':a.page,'page_size':a.page_size}))
            result={'total':data.get('total'),'items':[{k:r.get(k) for k in ['id','model','status','created_at','resolution','duration','ratio']} for r in data.get('items',[])]}
        elif a.cmd=='wait':result=wait(a.job,a.seconds)
        elif a.cmd=='attach':result=attach(a.job,a.task)
        elif a.cmd=='delete':result=delete(a.job,a.confirm_task)
        else:result=globals()[a.cmd](a.job)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,RuntimeError,KeyError,OSError) as e:
        p.exit(1,str(e)+'\n')

if __name__=='__main__':main()
