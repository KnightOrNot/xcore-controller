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
  const dom = new JSDOM('<html><head></head><body><div id="react-root"><button class="btn secondary"><svg class="lucide lucide-upload"></svg>Upload</button></div></body></html>', {
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
  assert.equal(pull.tagName, 'BUTTON', 'Pull must be a button to inherit Merge/Upload styling');
  assert.equal(pull.className, upload.className, 'Pull must reuse the Upload classes verbatim');
  assert.equal(upload.nextElementSibling, pull, 'Pull must sit next to Merge/Upload');
  pull.click();
  await tick();
  assert.equal(originalUploadClicked, false);
  assert.equal(pull.dataset.target, '/upload?dataset=source%2Frev-0001');
  assert.equal(fullNavigations, 1, 'Pull must navigate a full document');
  assert.equal(window.document.querySelector('dialog'), null);
  // React replacing the toolbar must not strand or duplicate the control.
  window.history.pushState({}, '', '/edit-dataset?dataset=second/rev-0002');
  window.document.getElementById('react-root').innerHTML = '<button class="btn"><svg class="lucide lucide-upload"></svg>Upload</button>';
  await tick();
  const replaced = window.document.getElementById('xcore-pull-link');
  assert.equal(replaced.previousElementSibling, window.document.querySelector('#react-root button'));
  assert.equal(replaced.className, 'btn');
  replaced.click();
  await tick();
  assert.equal(fullNavigations, 2);
  assert.equal(replaced.dataset.target, '/upload?dataset=second%2Frev-0002');
  assert.equal(originalUploadClicked, false);
  dom.window.close();
  // Load the adapter after DOMContentLoaded, as can happen on an existing SPA.
  const late = new JSDOM('<html><body><button>Upload</button></body></html>', {
    url:'http://127.0.0.1:8090/edit-dataset?dataset=source/rev-0001', runScripts:'outside-only'
  });
  await tick();
  late.window.eval(script.replace('__XCORE_TOKEN__', 'test-token'));
  assert.equal(late.window.document.querySelector('button').textContent, 'Upload');
  const latePull = late.window.document.getElementById('xcore-pull-link');
  assert.equal(latePull.tagName, 'BUTTON');
  assert.equal(latePull.previousElementSibling, late.window.document.querySelector('button'));
  late.window.close();

  // No fixed toolbar: the control only exists where Merge/Upload exist, and it
  // is removed again when the SPA leaves the dataset page.
  const shell = new JSDOM('<html><body><div id="root">Home</div></body></html>', {
    url:'http://127.0.0.1:8090/', runScripts:'outside-only'
  });
  shell.window.eval(script.replace('__XCORE_TOKEN__', 'test-token'));
  await tick();
  assert.equal(shell.window.document.getElementById('xcore-pull-link'), null);
  shell.window.history.pushState({}, '', '/edit-dataset?dataset=source%2Frev-0001');
  shell.window.document.getElementById('root').innerHTML = '<h1>Browse dataset</h1>';
  await tick();
  assert.equal(shell.window.document.getElementById('xcore-pull-link'), null,
    'no button is injected on a page without the Merge/Upload toolbar');
  shell.window.document.getElementById('root').innerHTML =
    '<button class="btn"><svg class="lucide lucide-upload"></svg>Upload</button>';
  await tick();
  assert.ok(shell.window.document.getElementById('xcore-pull-link'));
  shell.window.history.pushState({}, '', '/');
  shell.window.document.getElementById('root').innerHTML = '<h1>Home again</h1>';
  await tick();
  assert.equal(shell.window.document.getElementById('xcore-pull-link'), null,
    'leaving the dataset page must drop the injected button');
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
  const fresh = new JSDOM('<html><body><button class="btn"><svg class="lucide lucide-upload"></svg>Upload</button><div id="root"></div></body></html>', {
    url:'http://127.0.0.1:8090/edit-dataset?dataset=source%2Frev-0001&xcore_ui='+revision,
    runScripts:'outside-only',virtualConsole:upgradeConsole
  });
  fresh.window.eval(versionedScript);
  await tick();
  assert.equal(upgrades,1,'current-version first load must not reload');
  const current = fresh.window.document.getElementById('xcore-pull-link');
  assert.ok(current, 'a current-version dataset page must still get the Pull button');
  fresh.window.fetch = async url => {
    assert.equal(url,'/api/xcore/ui');
    return {ok:true,json:async () => ({revision:'abcdef012345'})};
  };
  fresh.window.dispatchEvent(new fresh.window.PageTransitionEvent('pageshow',{persisted:true}));
  await tick();
  assert.equal(upgrades,2,'restored browser history must detect a newer server version');
  current.click();
  const href = new URL(current.dataset.target, 'http://127.0.0.1:8090');
  assert.equal(href.searchParams.get('dataset'),'source/rev-0001');
  assert.equal(href.searchParams.get('xcore_ui'),revision);
  fresh.window.close();

  // Both the direct URL and the toolbar destination use this exact page.
  const page = fs.readFileSync(path.join(__dirname, '../src/xcore_controller/lelab_upload.html'), 'utf8');
  for (const url of ['http://127.0.0.1:8090/upload', 'http://127.0.0.1:8090/upload?dataset=source%2Frev-0001']) {
  const direct = new JSDOM(page, {url, runScripts:'outside-only'});
  let directRequest, revealRequest;
  direct.window.fetch = async (url, options) => {
    if (url === '/api/datasets') return {ok:true, json:async () => ({datasets:['source/rev-0001']})};
    if (url === '/api/xcore/reveal') {
      revealRequest = JSON.parse(options.body);
      return {ok:true, json:async () => ({opened:revealRequest.path})};
    }
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
  // A finished pull has nothing to start: the primary action becomes the folder.
  const startButton = direct.window.document.getElementById('xp-start');
  const revealButton = direct.window.document.getElementById('xp-reveal');
  assert.equal(startButton.style.display, 'none', 'finished pull must not offer 开始拉取');
  assert.notEqual(revealButton.style.display, 'none');
  revealButton.click();
  await tick();
  assert.deepEqual(revealRequest, {path:'/local/direct'});
  format.value = 'pose10';
  direct.window.document.getElementById('xp-start').click();
  await tick();
  assert.equal(directRequest.representation, 'pose10');
  direct.window.close();
  }
  global.console.log('LeLab DOM check passed: Pull button beside Merge/Upload, class reuse, navigation, formats, path, SPA');
})().catch(error => { console.error(error); process.exitCode = 1; });
