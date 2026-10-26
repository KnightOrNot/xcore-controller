// DOM integration check: NODE_PATH=<jsdom node_modules> node tests/test_lelab_pull.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM,VirtualConsole} = require('jsdom');

(async () => {
  let fullNavigations = 0;
  const console = new VirtualConsole();
  console.on('jsdomError', error => {
    if (/navigation/.test(error.message)) fullNavigations++;
    else throw error;
  });
  const dom = new JSDOM('<html><head></head><body><div id="react-root"><button><svg class="lucide lucide-upload"></svg>Upload</button></div></body></html>', {
    url:'http://127.0.0.1:8090/edit-dataset?dataset=source/rev-0001', runScripts:'outside-only', virtualConsole:console
  });
  const {window} = dom;
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  let originalUploadClicked = false;
  window.document.querySelector('#react-root button').addEventListener('click', () => { originalUploadClicked = true; });
  const script = fs.readFileSync(path.join(__dirname, '../src/xcore_controller/lelab_pull.js'), 'utf8');
  window.eval(script.replace('__XCORE_TOKEN__', 'test-token'));
  const tick = () => new Promise(resolve => setTimeout(resolve, 10));
  await tick();
  const upload = window.document.querySelector('#react-root button');
  const pull = window.document.getElementById('xcore-pull-link');
  assert.equal(upload.textContent.trim(), 'Upload');
  assert.equal(pull.textContent, 'Pull 到本地');
  assert.equal(upload.nextElementSibling, pull);
  assert.equal(pull.getAttribute('href'), '/upload?dataset=source%2Frev-0001');
  pull.click();
  await tick();
  assert.equal(originalUploadClicked, false);
  assert.equal(fullNavigations, 1, 'native Pull link must navigate a full document');
  assert.equal(window.document.querySelector('dialog'), null);
  // React-style toolbar replacement after SPA navigation must also be adapted.
  window.history.pushState({}, '', '/edit-dataset?dataset=second/rev-0002');
  window.document.getElementById('react-root').innerHTML = '<button><svg class="lucide lucide-upload"></svg>Upload</button>';
  await tick();
  window.document.getElementById('xcore-pull-link').click();
  await tick();
  assert.equal(fullNavigations, 2);
  assert.equal(window.document.getElementById('xcore-pull-link').getAttribute('href'), '/upload?dataset=second%2Frev-0002');
  assert.equal(originalUploadClicked, false);
  dom.window.close();
  // Load the adapter after DOMContentLoaded, as can happen on an existing SPA.
  const late = new JSDOM('<html><body><button>Upload</button></body></html>', {
    url:'http://127.0.0.1:8090/edit-dataset?dataset=source/rev-0001', runScripts:'outside-only'
  });
  await tick();
  late.window.eval(script.replace('__XCORE_TOKEN__', 'test-token'));
  assert.equal(late.window.document.querySelector('button').textContent, 'Upload');
  assert.equal(late.window.document.getElementById('xcore-pull-link').getAttribute('href'), '/upload?dataset=source%2Frev-0001');
  late.window.close();

  // The server-owned toolbar must survive SPA navigation even if the React
  // tree is replaced entirely, and must not depend on a matching Upload button.
  const shell = new JSDOM('<html><body><nav id="xcore-data-toolbar"><a id="xcore-pull-link" href="/upload">Pull 到本地</a></nav><div id="root">Home</div></body></html>', {
    url:'http://127.0.0.1:8090/', runScripts:'outside-only'
  });
  shell.window.eval(script.replace('__XCORE_TOKEN__', 'test-token'));
  await tick();
  const persistent = shell.window.document.getElementById('xcore-pull-link');
  shell.window.history.pushState({}, '', '/edit-dataset?dataset=source%2Frev-0001');
  shell.window.document.getElementById('root').innerHTML = '<h1>Browse dataset</h1>';
  await tick();
  assert.equal(shell.window.document.getElementById('xcore-pull-link'), persistent);
  assert.equal(persistent.getAttribute('href'), '/upload?dataset=source%2Frev-0001');
  assert.equal(persistent.parentElement.id, 'xcore-data-toolbar');
  shell.window.history.pushState({}, '', '/');
  shell.window.document.getElementById('root').innerHTML = '<h1>Home again</h1>';
  await tick();
  assert.equal(shell.window.document.getElementById('xcore-pull-link'), persistent);
  assert.equal(persistent.getAttribute('href'), '/upload');
  shell.window.close();

  // An old cached document automatically moves to the current UI version,
  // while a current-version first load must not enter a refresh loop.
  const revision = '012345abcdef';
  let upgrades = 0;
  const upgradeConsole = new VirtualConsole();
  upgradeConsole.on('jsdomError', error => {
    if (/navigation/.test(error.message)) upgrades++;
    else throw error;
  });
  const versionedScript = script.replace('__XCORE_TOKEN__', 'test-token').replace('__XCORE_UI_REVISION__', revision);
  const cached = new JSDOM('<html><body>Cached LeLab</body></html>', {
    url:'http://127.0.0.1:8090/edit-dataset?dataset=source%2Frev-0001',
    runScripts:'outside-only',virtualConsole:upgradeConsole
  });
  cached.window.eval(versionedScript);
  assert.equal(upgrades,1,'cached entry must automatically request a versioned document');
  cached.window.close();
  const fresh = new JSDOM('<html><body><nav id="xcore-data-toolbar"><a id="xcore-pull-link">Pull 到本地</a></nav><div id="root"></div></body></html>', {
    url:'http://127.0.0.1:8090/edit-dataset?dataset=source%2Frev-0001&xcore_ui='+revision,
    runScripts:'outside-only',virtualConsole:upgradeConsole
  });
  fresh.window.eval(versionedScript);
  await tick();
  assert.equal(upgrades,1,'current-version first load must not reload');
  const href = new URL(fresh.window.document.getElementById('xcore-pull-link').href);
  assert.equal(href.searchParams.get('dataset'),'source/rev-0001');
  assert.equal(href.searchParams.get('xcore_ui'),revision);
  fresh.window.fetch = async url => {
    assert.equal(url,'/api/xcore/ui');
    return {ok:true,json:async () => ({revision:'abcdef012345'})};
  };
  fresh.window.dispatchEvent(new fresh.window.PageTransitionEvent('pageshow',{persisted:true}));
  await tick();
  assert.equal(upgrades,2,'restored browser history must detect a newer server version');
  fresh.window.close();

  // Both the direct URL and the toolbar destination use this exact page.
  const page = fs.readFileSync(path.join(__dirname, '../src/xcore_controller/lelab_upload.html'), 'utf8');
  for (const url of ['http://127.0.0.1:8090/upload', 'http://127.0.0.1:8090/upload?dataset=source%2Frev-0001']) {
  const direct = new JSDOM(page, {url, runScripts:'outside-only'});
  let directRequest;
  direct.window.fetch = async (url, options) => {
    if (url === '/api/datasets') return {ok:true, json:async () => ({datasets:['source/rev-0001']})};
    assert.equal(url, '/api/xcore/pulls');
    if (options?.method === 'POST') {
      directRequest = JSON.parse(options.body);
      return {ok:true, json:async () => ({job:{id:'direct', ...directRequest, state:'ready', phase:'done', path:'/local/direct'}})};
    }
    return {ok:true, json:async () => ({job:null})};
  };
  direct.window.eval(script.replace('__XCORE_TOKEN__', 'test-token'));
  await tick();
  const source = direct.window.document.getElementById('xp-source');
  assert.equal(source.options.length, 2);
  assert.equal(source.disabled, false);
  assert.equal(source.value, url.includes('?') ? 'source/rev-0001' : '');
  source.value = 'source/rev-0001';
  source.dispatchEvent(new direct.window.Event('change'));
  await tick();
  const format = direct.window.document.getElementById('xp-format');
  assert.deepEqual([...format.options].map(option => option.value), ['pose10', 'joints']);
  direct.window.document.getElementById('xp-format').value = 'joints';
  direct.window.document.getElementById('xp-start').click();
  await tick();
  assert.deepEqual(directRequest, {dataset:'source/rev-0001', representation:'joints'});
  assert.equal(direct.window.document.getElementById('xp-path').textContent, '/local/direct');
  assert.notEqual(direct.window.document.getElementById('xp-copy').style.display, 'none');
  format.value = 'pose10';
  direct.window.document.getElementById('xp-start').click();
  await tick();
  assert.equal(directRequest.representation, 'pose10');
  direct.window.close();
  }
  global.console.log('LeLab DOM check passed: independent Pull link, native navigation, selected dataset, formats, path, SPA');
})().catch(error => { console.error(error); process.exitCode = 1; });
