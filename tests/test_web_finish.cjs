// NODE_PATH=<jsdom node_modules> node tests/test_web_finish.cjs <rendered PAGE html>
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');

(async () => {
  const page = fs.readFileSync(process.argv[2], 'utf8');
  const dom = new JSDOM(page, {url:'http://127.0.0.1:8095', runScripts:'outside-only'});
  const w = dom.window;
  w.setInterval = () => 0;
  w.setTimeout = () => 0;
  let state = {
    ok:true, allow_motion:true, cameras:[],
    remote:{motion:{state:'idle',armed:false},recording:{session:null,active_episode:null},
      conversion:{last:{state:'running'}}},
    job:{action:'finish',state:'running',steps:[]}
  };
  w.fetch = async () => ({ok:true,json:async () => state});
  w.eval(page.match(/<script>([\s\S]*?)<\/script>/)[1]);
  await w.refresh();
  const button = id => w.document.getElementById('b-'+id);
  for (const id of ['start','record','save','discard','finish']) assert.equal(button(id).disabled,true);
  assert.match(w.document.getElementById('notice').textContent,/等待完成/);
  // A timed-out local finish must still stay locked while the remote job runs.
  state.job.state = 'failed';
  await w.refresh();
  assert.equal(button('start').disabled,true);
  // Publication must finish before a new follow session becomes available.
  state.remote.conversion.last = {state:'ready',verified:true,path:'/published/rev-0001'};
  state.job = {action:'finish',state:'ready',steps:[],publication:state.remote.conversion.last};
  await w.refresh();
  assert.equal(button('start').disabled,false);
  assert.match(w.document.getElementById('notice').textContent,/已保存并发布/);
  state.ok = false;
  await w.refresh();
  assert.equal(button('start').disabled,true);
  dom.window.close();
  console.log('Finish DOM check passed: pending/timeout lock, publication unlock, connection-loss lock');
})().catch(error => {console.error(error);process.exitCode=1;});
