import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { chromium, expect } from '@playwright/test';
import { aConfiguredMock, operateTheInstrument, rest } from './workflows/target_acquisition/steps/scan_the_overview/live-bridge.js';

// Run from the repository root against a disposable, idle native window.
// See MICROSCOPE_ISSUES_2026-09-10.md for setup and validation limits.
if (!process.env.OPERATOR_EVIDENCE_DIR) throw new Error('OPERATOR_EVIDENCE_DIR is required');
if (!process.env.PYTHON) throw new Error('PYTHON must point to the operator environment executable');
const evidence = path.join(process.env.OPERATOR_EVIDENCE_DIR, 'run-'+Date.now());
fs.mkdirSync(evidence, { recursive: true });
process.env.ZMART_MOCK_STATE = path.join(evidence, 'mock-instrument.json');
process.env.ZMART_MOCK_MACHINE = path.join(evidence, 'mock-machine');
const browser = await chromium.connectOverCDP('http://127.0.0.1:9223');
const page = browser.contexts()[0].pages()[0];
const originalUrl = process.env.NATIVE_OPERATOR_URL || page.url();
aConfiguredMock();
const outputRoot=fs.mkdtempSync(path.join(os.tmpdir(),'nv-'));
const child = spawn(process.env.PYTHON,['-u','application/framework/bridge.py','--port','8837','--output-root',outputRoot],{windowsHide:true,stdio:['ignore','pipe','pipe']});
const log=fs.createWriteStream(path.join(evidence,'bridge.log'));
child.stdout.pipe(log); child.stderr.pipe(log);
const bridge={at:'http://127.0.0.1:8837',stop:async()=>{
  try { await fetch('http://127.0.0.1:8837/api/disconnect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(5000)}); } catch {}
  child.kill();
}};
await expect.poll(async()=>{try{return (await fetch(bridge.at+'/api/instruments')).ok;}catch{return false;}}).toBe(true);
const report = { runtime: 'native WebView2', originalUrl, outputRoot, steps: [], errors: [], failedRequests: [] };
report.statuses = [];
report.reorders = [];
report.chunks = [];
page.on('response', response => { if (/\/data\/.*\/c\//.test(response.url())) report.chunks.push({url:response.url(),status:response.status(),at:Date.now()}); });
page.on('request', request => { if (request.url().endsWith('/api/targets/raise')) report.reorders.push(request.url()); });
page.on('response', async response => {
  if (response.url() === bridge.at+'/api/viewer') {
    const state = await response.json().catch(()=>null);
    if (state) report.statuses.push({at:Date.now(),publications:state.publications,
      views:state.acquisitions?.flatMap(a=>a.channels.map(c=>({name:a.name,view:c.view?.type,revisions:c.sourceRevisions}))) });
  }
});
page.setDefaultTimeout(15000);
page.on('pageerror', e => { report.errors.push(e.message); console.log('PAGE ERROR',e.message); });
page.on('response', response => { if (response.status() >= 400) report.failedRequests.push({ url: response.url(), status: response.status() }); });
const step = async name => { console.log(name); report.steps.push(name); await page.screenshot({path:path.join(evidence, name+'.png')}); };
const goto = async name => { await page.locator(`.step:has-text("${name}")`).first().click(); await rest(300); };
const record = async (id, job) => {
  operateTheInstrument('choose', job);
  await page.locator(`#${id} .setting-box.open button.run`).click();
  await rest(800);
};
const canvasSignal = (selector, index=0) => page.locator(selector).nth(index).evaluate(canvas => {
  const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
  let sum=0,lit=0;
  for(let i=0;i<pixels.length;i+=4) { const value=Math.max(pixels[i],pixels[i+1],pixels[i+2]); sum+=value; lit+=value>30; }
  return {mean:sum/(pixels.length/4),lit:lit/(pixels.length/4),width:canvas.width,height:canvas.height};
});
try {
  await page.goto(bridge.at);
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.reload();
  await page.locator('.session-form select').first().selectOption({ label: "Mock · the controller's fake driver" });
  await page.getByLabel('Bake coarse images (experimental)').check();
  await page.locator('.session-foot button.run').click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({timeout:60000});
  await step('01-connected-mock');
  await goto('Define Carrier');
  await page.locator('input[data-field="w"]').fill('2.5');
  await page.locator('input[data-field="h"]').fill('2.5');
  // Let the carrier's blur handler finish rebuilding the rail before clicking it.
  await page.keyboard.press('Tab');
  await rest(300);
  await goto('Overview scan area');
  await record('sf-preset', 'Overview');
  await page.locator('.sf-apply-grid').click();
  await rest(500);
  report.plan = await page.evaluate(() => window.__theStageCanvas.plan());
  console.log('PLAN', JSON.stringify(report.plan));
  if (report.plan.length > 6 || !report.plan.length) throw new Error('Validation requires a bounded plan of 1–6 positions');
  await page.locator('#tileset-btn').click();
  await step('02-bounded-plan');
  await goto('Focus strategy');
  await record('focus-preset', 'Focussing');
  await page.locator('#fp-place').click();
  await page.locator('.panel.on button.step-run').click();
  await expect.poll(()=>page.evaluate(()=>window.__theRunState().running),{timeout:90000}).toBeFalsy();
  await step('03-focus-complete');
  const focus = await (await page.request.get(bridge.at+'/api/focus/measure')).json();
  report.focus = { error:focus.error, points:focus.points?.map(p=>({x:p.x,y:p.y,z:p.z,slices:p.slices?.length})) };
  console.log('FOCUS',JSON.stringify(report.focus));
  expect(focus.error).toBeNull();
  expect(focus.points.length).toBeGreaterThan(0);
  expect(focus.points.every(p=>p.slices?.length>1)).toBe(true);
  report.focusNavigation=[];
  for(let index=0;index<focus.points.length;index++) {
    await page.locator('#focus-traces .point-row button.point-pick').nth(index).click();
    await expect(page.locator('#zpreview')).toBeVisible();
    await expect.poll(async()=> (await canvasSignal('#zpreview-canvas')).lit).toBeGreaterThan(0.02);
    const before=await page.evaluate(()=>window.__theSliceShown());
    const box=await page.locator('#zortho-canvas').boundingBox();
    await page.mouse.click(box.x+box.width/2,box.y+box.height*0.35);
    await expect.poll(()=>page.evaluate(()=>window.__theSliceShown())).not.toBe(before);
    report.focusNavigation.push({index,before,after:await page.evaluate(()=>window.__theSliceShown()),signal:await canvasSignal('#zpreview-canvas')});
  }
  await step('03b-focus-navigation');
  await goto('Scan the overview');
  await page.locator('.panel.on button.step-run').click();
  await expect(page.locator('.panel.on button.step-run')).not.toHaveClass(/\brunning\b/,{timeout:180000});
  await expect.poll(async()=> (await (await page.request.get(bridge.at+'/api/viewer')).json()).publications?.overview?.state,{timeout:120000}).toBe('ready');
  await step('04-overview-ready');
  report.viewer = await (await page.request.get(bridge.at+'/api/viewer')).json();
  await goto('Detect objects');
  await expect.poll(async()=> (await canvasSignal('#tile-canvas')).lit).toBeGreaterThan(0.01);
  report.detectionPreview=await canvasSignal('#tile-canvas');
  report.detectionCanvases=await page.locator('.panel.on canvas').evaluateAll(nodes=>nodes.map(n=>({id:n.id,cls:n.className})));
  await step('05-detection-preview');
  await page.locator('.panel.on button.step-run').click();
  await expect(page.locator('.panel.on button.step-run')).not.toHaveClass(/\brunning\b/,{timeout:180000});
  const discovery=await (await page.request.get(bridge.at+'/api/targets/discover')).json();
  expect(discovery.error).toBeNull();
  report.detected=await page.evaluate(()=>window.__theStageCanvas.targets().length);
  expect(report.detected).toBeGreaterThan(1);
  await goto('Discover Targets');
  const plot=await page.locator('#scatter-canvas').boundingBox();
  for(const [x,y] of [[0.02,0.02],[0.98,0.02],[0.98,0.98],[0.02,0.98],[0.02,0.02]]) {
    await page.mouse.click(plot.x+1+(plot.width-63)*x,plot.y+1+(plot.height-39)*y);
  }
  await expect(page.locator('#gate-list .gate-row')).toHaveCount(1);
  await goto('Target scan area');
  await record('target-type','Target');
  await page.locator('#gate-max-on').check();
  await page.locator('#gate-max').fill('2');
  await page.locator('#gate-max').dispatchEvent('input');
  await page.keyboard.press('Tab');
  await page.locator('.panel.on button.step-run').click();
  await expect(page.locator('.panel.on button.step-run')).not.toHaveClass(/\brunning\b/);
  await goto('Acquire Targets');
  await page.locator('.panel.on button.step-run').click();
  await expect(page.locator('.panel.on button.step-run')).toHaveText('Rerun all',{timeout:180000});
  await expect.poll(async()=> (await (await page.request.get(bridge.at+'/api/viewer')).json()).publications?.targets?.state,{timeout:120000}).toBe('ready');
  report.selection=[];
  const run=await page.evaluate(()=>window.__theRunState());
  expect(run.acquiredTileKeys.length).toBe(2);
  for(const key of run.acquiredTileKeys) {
    const start=Date.now();
    await page.locator(`#target-list .point-row[data-target="${key}"] button`).click();
    await expect(page.locator('.pair')).toHaveAttribute('data-target',key);
    await expect.poll(async()=> (await canvasSignal('.pair canvas')).lit).toBeGreaterThan(0.01);
    await expect.poll(async()=> (await canvasSignal('.pair canvas',1)).lit).toBeGreaterThan(0.01);
    report.selection.push({key,ms:Date.now()-start});
  }
  expect(report.reorders).toEqual([]);
  await step('06-target-selection');
  await page.evaluate(()=>{window.validationPicture=window.__thePicture;});
  const chosen=run.targetTilePositions.find(t=>t.key===run.acquiredTileKeys.at(-1));
  const chunkStart=report.chunks.length;
  await page.evaluate(t=>window.__theStageCanvas.lookAt({centre:{x:t.x,y:t.y},zoom:0.2}),chosen);
  await expect.poll(()=>report.chunks.slice(chunkStart).some(r=>/targets_top\.zmartview\.zarr\/0\/c\//.test(r.url)&&r.status===200),{timeout:20000}).toBe(true);
  await step('07-native-fine-detail');
  report.refinement={zoom:0.2,successfulFineChunks:report.chunks.slice(chunkStart).filter(r=>/targets_top\.zmartview\.zarr\/0\/c\//.test(r.url)&&r.status===200).length};
  const sample=report.chunks.slice(chunkStart).find(r=>/targets_top\.zmartview\.zarr\/0\/c\//.test(r.url)&&r.status===200).url;
  const status=async()=> (await (await page.request.get(bridge.at+'/api/viewer')).json());
  const revision=s=>s.acquisitions.find(a=>a.name==='targets').channels.find(c=>c.view?.type==='top').sourceRevisions[0];
  const before=await status();
  report.rerun={beforeRevision:revision(before),samples:[]};
  let finished=false;
  const monitor=(async()=>{while(!finished){
    const start=Date.now();
    const [pixels,state]=await Promise.all([fetch(sample),status()]);
    await pixels.arrayBuffer();
    report.rerun.samples.push({status:pixels.status,ms:Date.now()-start,publication:state.publications.targets,revision:revision(state)});
    await rest(100);
  }})();
  try {
    await page.getByRole('button',{name:'Rerun current',exact:true}).click();
    await expect.poll(async()=> { const s=await status(); return s.publications.targets.state==='ready'&&revision(s)>report.rerun.beforeRevision; },{timeout:120000}).toBe(true);
  } finally { finished=true; await monitor; }
  expect(report.rerun.samples.every(s=>s.status===200)).toBe(true);
  expect(report.rerun.samples.some(s=>s.publication.state==='preparing')).toBe(true);
  expect(await page.evaluate(()=>window.validationPicture===window.__thePicture)).toBe(true);
  report.rerun.afterRevision=revision(await status());
  await step('08-readable-during-rerun');
  expect(report.errors).toEqual([]);
  report.success=true;
} catch (error) {
  report.failure = error.stack;
  await page.screenshot({path:path.join(evidence,'failure.png')}).catch(()=>{});
  console.error(error);
  process.exitCode = 1;
} finally {
  fs.writeFileSync(path.join(evidence,'report.json'), JSON.stringify(report,null,2));
  await page.goto(originalUrl).catch(()=>{});
  await bridge.stop();
  // Detach the diagnostic transport; Browser.close is not supported by an
  // embedded WebView2 host and would wait for the native window to disappear.
  browser._connection.close();
}
