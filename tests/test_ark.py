import importlib.util, tempfile, unittest, os, io
from pathlib import Path
from unittest.mock import patch
from PIL import Image
spec=importlib.util.spec_from_file_location('ark',Path(__file__).resolve().parents[1]/'skill/scripts/ark_video.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class ArkJobs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.job=root/'job'
        Image.new('RGB',(64,64),(230,230,230)).save(root/'ref.png')
        (root/'prompt.txt').write_text('Run right')
        a.plan(root/'ref.png',root/'prompt.txt',self.job)
        self.ledger=root/'ledger.json';self.policy=root/'policy.json'
        a.costs.init(self.ledger,10,2)
        a.save(self.policy,{'yuan_per_million_tokens':'23','price_basis':'test','valid_until':'2099-01-01','reserve_multiplier':'1.2'})
        self.env=patch.dict(os.environ,{'SEEDDANCE_ARK_API_KEY':'test-only-not-a-real-key'});self.env.start();self.addCleanup(self.env.stop)
    def test_plan_and_payload(self):
        body=a.payload(self.job)
        self.assertEqual(body['duration'],4);self.assertFalse(body['generate_audio'])
        self.assertEqual(body['content'][1]['role'],'reference_image')
        self.assertFalse(body['watermark'])
        self.assertTrue(body['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
        self.assertEqual(Image.open(self.job/'input.png').getpixel((0,0)),(230,230,230))
    def test_error_details_without_secret(self):
        import urllib.error
        key=os.environ['SEEDDANCE_ARK_API_KEY']
        body=a.json.dumps({'error':{'code':'AccessDenied','message':'Denied '+key+' Request id: request-123456789012345678901234'}}).encode()
        error=urllib.error.HTTPError(a.BASE,403,'Forbidden',{},io.BytesIO(body))
        with patch.object(a,'build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(a.ArkAPIError) as caught:a.api('POST',body={})
        details=caught.exception.details
        self.assertEqual(details['error_code'],'AccessDenied')
        self.assertEqual(details['request_id'],'request-123456789012345678901234')
        self.assertNotIn(key,str(caught.exception))
    def test_http_failure_saved(self):
        error=a.ArkAPIError({'http_status':403,'error_code':'AccessDenied','request_id':'test-id','message':'Denied'})
        with patch.object(a,'api',side_effect=error):
            with self.assertRaises(a.ArkAPIError):a.submit(self.job,self.ledger,self.policy)
        self.assertEqual(a.read(self.job/'create-error.json')['request_id'],'test-id')
    def test_first_frame_explicit_still_supported(self):
        cfg=a.read(self.job/'job.json');cfg['image_role']='first_frame';a.save(self.job/'job.json',cfg)
        self.assertEqual(a.payload(self.job)['content'][1]['role'],'first_frame')
    def test_submit_once(self):
        with patch.object(a,'api',return_value={'id':'cgt-test'}) as api:
            a.submit(self.job,self.ledger,self.policy);a.submit(self.job,self.ledger,self.policy);self.assertEqual(api.call_count,1)
    def test_uncertain_submission_never_retries(self):
        with patch.object(a,'api',side_effect=RuntimeError('timeout')) as api:
            with self.assertRaises(RuntimeError):a.submit(self.job,self.ledger,self.policy)
            with self.assertRaises(ValueError):a.submit(self.job,self.ledger,self.policy)
            self.assertEqual(api.call_count,1)
    def test_missing_key_leaves_plan(self):
        with patch.dict(os.environ,{'SEEDDANCE_ARK_API_KEY':''}):
            with self.assertRaises(ValueError):a.submit(self.job,self.ledger,self.policy)
        self.assertFalse((self.job/'submit.intent').exists())
    def test_changed_input_rejected(self):
        Image.new('RGB',(32,32)).save(self.job/'input.png')
        with self.assertRaises(ValueError):a.submit(self.job,self.ledger,self.policy)
        self.assertFalse((self.job/'submit.intent').exists())
    def test_running_cannot_delete(self):
        a.save(self.job/'state.json',{'id':'cgt-test','status':'queued'})
        with patch.object(a,'api',return_value={'status':'running'}) as api:
            with self.assertRaises(ValueError):a.delete(self.job,'cgt-test')
            self.assertEqual(api.call_count,1)
    def test_download_no_key_and_cache_integrity(self):
        a.save(self.job/'state.json',{'id':'cgt-test','status':'succeeded'})
        class Opener:
            def open(inner,req,timeout):
                self.assertFalse(req.has_header('Authorization'))
                return io.BytesIO(b'\x00\x00\x00\x18ftypisom'+b'0'*40)
        with patch.object(a,'api',return_value={'status':'succeeded','content':{'video_url':'https://example.volces.com/video'}}),patch.object(a,'build_opener',return_value=Opener()):
            a.download(self.job)
        self.assertTrue(a.download(self.job)['cached'])
        (self.job/'video.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError):a.download(self.job)
    def test_budget_blocks_before_network(self):
        a.save(self.ledger,{'total_budget_yuan':'0.1','per_job_limit_yuan':'2','jobs':{}})
        with patch.object(a,'api') as api:
            with self.assertRaises(ValueError):a.submit(self.job,self.ledger,self.policy)
            api.assert_not_called()
        self.assertFalse((self.job/'submit.intent').exists())
    def test_quote_and_reconcile(self):
        q=a.costs.reserve(self.job,self.ledger,self.policy)
        self.assertEqual(q['estimated_tokens'],38400)
        self.assertEqual(q['estimated_yuan'],'0.8832')
        a.costs.reconcile(self.job,self.ledger,{'id':'cgt-test','status':'succeeded','usage':{'completion_tokens':40000}})
        report=a.costs.report(self.ledger)
        self.assertEqual(report['budget_committed_yuan'],'0.92')
        self.assertIsNone(report['account_balance_yuan'])
    def test_unknown_reservation_is_retained(self):
        with patch.object(a,'api',side_effect=RuntimeError('timeout')):
            with self.assertRaises(RuntimeError):a.submit(self.job,self.ledger,self.policy)
        self.assertEqual(a.costs.report(self.ledger)['budget_committed_yuan'],'1.0599')
    def test_expired_policy_blocks(self):
        p=a.read(self.policy);p['valid_until']='2000-01-01';a.save(self.policy,p)
        with self.assertRaises(ValueError):a.submit(self.job,self.ledger,self.policy)
    def test_terminal_wait(self):
        a.save(self.job/'state.json',{'id':'cgt-test','status':'queued'})
        with patch.object(a,'api',return_value={'status':'failed'}) as api:
            self.assertEqual(a.wait(self.job,50)['status'],'failed');self.assertEqual(api.call_count,1)

if __name__=='__main__':unittest.main()
