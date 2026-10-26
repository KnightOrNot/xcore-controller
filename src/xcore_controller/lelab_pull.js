// Application-owned adapter for the pinned LeLab browse page. No Hub uploads.
(() => {
  'use strict';
  const token = '__XCORE_TOKEN__';
  const uiRevision = '__XCORE_UI_REVISION__';
  // A normal navigation may revive an older document from browser history.
  // Upgrade its URL once, without requiring a manual hard refresh.
  function upgradeEntry(revision) {
    if (!/^[a-f0-9]{12}$/.test(revision)) return false;
    const entry = new URL(location.href);
    if (entry.searchParams.get('xcore_ui') !== revision) {
      entry.searchParams.set('xcore_ui', revision);
      location.replace(entry.href);
      return true;
    }
    return false;
  }
  if (upgradeEntry(uiRevision)) return;
  window.addEventListener('pageshow', async event => {
    if (!event.persisted) return;
    try {
      const response = await fetch('/api/xcore/ui', {cache:'no-store'});
      if (response.ok) upgradeEntry((await response.json()).revision);
    } catch { /* Preserve the current page during temporary disconnection. */ }
  });
  let dialog, timer, busy = false, current = null;
  const validDataset = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\/rev-[0-9]{4,}$/.test(value);
  const selected = () => {
    const source = document.getElementById('xp-source');
    if (source) return source.value || null;
    const value = new URL(location.href).searchParams.get('dataset') ||
      history.state?.usr?.datasetInfo?.dataset_repo_id;
    return validDataset(value) ? value : null;
  };
  function ensureDialog() {
    if (dialog) return;
    dialog = document.getElementById('xp-pull-content') || document.createElement('dialog');
    const modal = dialog.tagName === 'DIALOG';
    if (modal) dialog.id = 'xcore-pull-dialog';
    dialog.style.cssText = 'background:#111827;color:#f3f4f6;border:1px solid #475569;border-radius:14px;padding:24px;width:min(540px,90vw);font:15px system-ui;box-shadow:0 20px 80px #0009';
    dialog.innerHTML = `<form method="dialog"><h2 style="font-size:20px;margin:0 0 16px">拉取到本地</h2>
      <p id="xp-dataset" style="overflow-wrap:anywhere"></p>
      <label for="xp-format">数据格式</label>
      <select id="xp-format" style="display:block;width:100%;padding:10px;margin:8px 0 12px;background:#1e293b;color:white;border:1px solid #64748b;border-radius:6px">
        <option value="pose10">--pose：末端位姿＋夹爪（10 维）</option>
        <option value="joints">--joints：关节角＋夹爪（7 维，rad）</option>
      </select>
      <p style="font-size:13px;color:#94a3b8">所选格式尚未发布时，将先在远端生成，再拉取完整数据集。原始数据不变。</p>
      <p id="xp-status" role="status" aria-live="polite" style="white-space:pre-wrap;overflow-wrap:anywhere"></p>
      <pre id="xp-path" style="display:none;white-space:pre-wrap;overflow-wrap:anywhere;background:#020617;padding:12px;border-radius:6px"></pre>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px">
        <button type="button" id="xp-copy" style="display:none">复制路径</button>
        <button type="button" id="xp-start">开始拉取</button><button id="xp-close">关闭</button>
      </div></form>`;
    if (modal) document.body.appendChild(dialog);
    else dialog.style.cssText = 'margin-top:20px';
    dialog.querySelectorAll('button').forEach(button => {
      button.style.cssText = 'border:1px solid #64748b;border-radius:6px;padding:8px 14px;background:#1e293b;color:white;cursor:pointer';
    });
    dialog.querySelector('#xp-start').onclick = start;
    if (!modal) dialog.querySelector('#xp-close').style.display = 'none';
    dialog.querySelector('#xp-copy').onclick = async () => {
      try { await navigator.clipboard.writeText(dialog.querySelector('#xp-path').textContent); }
      catch { status('请选中上方路径手动复制。'); }
    };
  }
  const element = id => dialog.querySelector('#xp-' + id);
  function status(text) { element('status').textContent = text; }
  function render(job) {
    if (!job) return;
    current = job;
    busy = job.state === 'running';
    element('dataset').textContent = job.dataset;
    element('format').value = job.representation;
    element('format').disabled = busy;
    element('start').disabled = busy;
    const source = document.getElementById('xp-source');
    if (source) {
      source.disabled = busy;
      if ([...source.options].some(option => option.value === job.dataset)) source.value = job.dataset;
    }
    status(job.state === 'failed' ? '拉取失败：' + job.error : job.phase);
    element('path').style.display = job.path ? 'block' : 'none';
    element('path').textContent = job.path || '';
    element('copy').style.display = job.path ? 'inline-block' : 'none';
    if (job.state === 'ready') status('已拉取并校验完成。本地数据路径：');
  }
  async function poll() {
    try {
      const response = await fetch('/api/xcore/pulls', {cache:'no-store'});
      if (!response.ok) throw new Error('本地拉取服务不可用');
      const data = await response.json();
      if (data.job && (!current || current.id === data.job.id || busy)) render(data.job);
      if (data.job && data.job.state === 'running') timer = setTimeout(poll, 1000);
    } catch (error) {
      status('状态查询失败，任务可能仍在执行：' + error.message);
      timer = setTimeout(poll, 2000);
    }
  }
  async function open() {
    ensureDialog();
    clearTimeout(timer);
    const dataset = selected();
    if (!dataset) { status('请先选择远端数据集，再选择格式并开始拉取。'); return; }
    element('dataset').textContent = dataset;
    element('path').style.display = 'none';
    element('copy').style.display = 'none';
    status('选择格式后开始拉取，完成后将在此显示本地绝对路径。');
    if (dialog.tagName === 'DIALOG' && !dialog.open) dialog.showModal();
    try {
      const data = await (await fetch('/api/xcore/pulls', {cache:'no-store'})).json();
      if (data.job && (data.job.state === 'running' || data.job.dataset === dataset)) {
        render(data.job);
        if (busy) poll();
      } else {
        current = null; busy = false;
        element('start').disabled = false; element('format').disabled = false;
      }
    } catch (error) { status('本地服务不可用：' + error.message); }
  }
  async function start() {
    const dataset = current && busy ? current.dataset : selected();
    if (!dataset) { status('请先选择远端数据集版本。'); return; }
    if (busy) return;
    busy = true; element('start').disabled = true;
    const source = document.getElementById('xp-source');
    if (source) source.disabled = true;
    element('path').style.display = 'none'; element('copy').style.display = 'none';
    status('正在创建拉取任务…');
    try {
      const response = await fetch('/api/xcore/pulls', {
        method:'POST', headers:{'Content-Type':'application/json','X-Xcore-Token':token},
        body:JSON.stringify({dataset, representation:element('format').value})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '拉取请求失败');
      render(data.job); clearTimeout(timer); poll();
    } catch (error) {
      busy = false; element('start').disabled = false;
      if (source) source.disabled = false;
      status(error.message);
    }
  }
  function uploadUrl(dataset) {
    const query = new URLSearchParams();
    if (validDataset(dataset)) query.set('dataset', dataset);
    if (/^[a-f0-9]{12}$/.test(uiRevision)) query.set('xcore_ui', uiRevision);
    return '/upload' + (query.size ? '?' + query.toString() : '');
  }
  function decorate() {
    let link = document.getElementById('xcore-pull-link');
    if (link && link.closest('#xcore-data-toolbar')) {
      link.href = uploadUrl(location.pathname.startsWith('/edit-dataset') ? selected() : null);
      return;
    }
    if (!location.pathname.startsWith('/edit-dataset') || !selected()) {
      if (link) link.remove();
      return;
    }
    const upload = [...document.querySelectorAll('button')].find(button =>
      button.textContent.trim() === 'Upload' || button.querySelector('svg.lucide-upload'));
    if (!upload) return;
    if (!link) {
      link = document.createElement('a');
      link.id = 'xcore-pull-link';
      link.textContent = 'Pull 到本地';
      link.className = upload.className;
      link.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;text-decoration:none;padding:8px 12px;border:1px solid #38bdf8;border-radius:6px;color:#7dd3fc;background:#0f172a;font:inherit';
      link.setAttribute('aria-label', 'Pull 到本地');
      // This plain anchor requests a new document. It has no React router
      // handler and does not depend on intercepting the upstream Upload.
      upload.insertAdjacentElement('afterend', link);
    }
    if (link.previousElementSibling !== upload) upload.insertAdjacentElement('afterend', link);
    link.href = uploadUrl(selected());
  }
  document.addEventListener('click', event => {
    const link = event.target instanceof Element ? event.target.closest('a#xcore-pull-link') : null;
    if (link) link.href = uploadUrl(location.pathname.startsWith('/edit-dataset') ? selected() : null);
    // Keep the native default action, outside React's event delegation.
  }, true);
  async function initUploadPage() {
    const source = document.getElementById('xp-source');
    if (!source) return;
    ensureDialog();
    const preferred = new URL(location.href).searchParams.get('dataset');
    try {
      const response = await fetch('/api/datasets', {cache:'no-store'});
      if (!response.ok) throw new Error('远端数据服务不可用（HTTP ' + response.status + '）');
      const data = await response.json();
      if (!Array.isArray(data.datasets)) throw new Error('数据集列表格式错误');
      source.replaceChildren(new Option('请选择远端数据集版本', ''));
      for (const dataset of data.datasets.filter(validDataset)) source.add(new Option(dataset, dataset));
      source.disabled = false;
      if ([...source.options].some(option => option.value === preferred)) source.value = preferred;
      source.onchange = () => {
        const url = new URL(location.href);
        if (source.value) url.searchParams.set('dataset', source.value);
        else url.searchParams.delete('dataset');
        history.replaceState(history.state, '', url);
        open();
      };
      if (source.options.length === 1) document.getElementById('xp-source-error').textContent = '远端暂无已发布数据集。';
      await open();
    } catch (error) {
      document.getElementById('xp-source-error').textContent = error.message + '，请确认数据服务已启动后刷新。';
      status('尚未开始拉取。');
    }
  }
  function init() {
    decorate();
    new MutationObserver(decorate).observe(document.body, {childList:true, subtree:true});
    initUploadPage();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
  window.addEventListener('popstate', decorate);
})();
