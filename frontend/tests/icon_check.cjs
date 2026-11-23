const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const net = require('node:net');

(async () => {
  const probe = net.createServer();
  await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
  const port = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  const baseUrl = `http://127.0.0.1:${port}`;
  const frontendRoot = path.resolve(__dirname, '..');
  const vite = spawn(process.execPath, [
    path.resolve(frontendRoot, 'node_modules/vite/bin/vite.js'),
    '--host', '127.0.0.1', '--port', String(port), '--strictPort',
  ], { cwd: frontendRoot, stdio: 'ignore' });
  let browser;

  try {
    for (let attempt = 0; ; attempt++) {
      try {
        if ((await fetch(baseUrl)).ok) break;
      } catch {}
      if (attempt >= 100 || vite.exitCode !== null) throw Error('Vite did not start');
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    browser = await chromium.launch({
      headless: true,
      executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    });
    const page = await browser.newPage();
    await page.addInitScript(() => {
      const notes = new Map([
        ['note.md', { content: '# Root', version: '1' }],
        ['other.md', { content: '# Other', version: '1' }],
      ]);
      const state = new EventTarget();
      let revision = 0;
      let snapshots = 0;
      const items = [
        { name: 'folder', is_directory: true, modified_time: null },
        { name: 'image.jxl', is_directory: false, modified_time: null },
        { name: 'data.jsonl', is_directory: false, modified_time: null },
        { name: 'archive.7z', is_directory: false, modified_time: null },
        { name: 'book.djvu', is_directory: false, modified_time: null },
        { name: 'song.flac', is_directory: false, modified_time: null },
        { name: 'clip.mkv', is_directory: false, modified_time: null },
        { name: 'note.md', is_directory: false, modified_time: null },
        { name: 'other.md', is_directory: false, modified_time: null },
      ];
      const registrations = [];
      let releaseRegistration;
      window.holdRegistration = false;
      window.registrationHeld = false;
      window.rejectRegistration = false;
      window.holdReads = false;
      window.heldReads = [];
      window.releaseRegistration = () => releaseRegistration?.();
      const reads = [];
      const signal = key => state.dispatchEvent(new CustomEvent('change', { detail: { key } }));
      const snapshot = () => ({
        workspace_id: 'workspace-1',
        revision: ++snapshots,
        watcher_error: null,
        directories: [{
          workspace_id: 'workspace-1', path: '', items, loading: false, stale: false, error: null,
        }, { workspace_id: 'workspace-1', path: 'folder', items: [{ name: 'child.md', is_directory: false, modified_time: null }], loading: false, stale: false, error: null }],
      });

      window.noteDisk = notePath => notes.get(notePath)?.content ?? null;
      window.externalNoteChange = (notePath, content, notify = true) => {
        const current = notes.get(notePath);
        if (!current) throw Error(`Unknown note: ${notePath}`);
        notes.set(notePath, { content, version: String(Number(current.version) + 1) });
        if (notify) signal('note_revision');
      };
      window.noteReads = reads;
      window.openNoteRegistrations = registrations;
      window.pywebview = {
        state,
        api: {
          get_settings: async () => ({
            workspaces: ['test', 'C:\\alpha\\workspace', 'C:\\beta\\workspace', 'C:\\reading-room'], blocked_extensions: [],
            editor: { autosave: false, auto_reload: true, reload_notice: true },
          }),
          set_editor_preference: async () => {},
          get_workspace_settings: async () => ({
            automatic_link_update: true,
            appearance: {
              theme: 'warm-charcoal', surface_mode: 'framed',
              file_icons: { set: 'minimal', extensions: {} },
            },
          }),
          open_workspace: async () => snapshot(),
          get_tree: async () => snapshot(),
          set_directory_visible: async () => snapshot(),
          set_tree_sort: async () => snapshot(),
          refresh_tree: async () => snapshot(),
          read_note: async (_id, notePath) => {
            reads.push(notePath);
            const note = notes.get(notePath);
            if (!note) throw Error('missing note');
            const result = { path: notePath, content: note.content, version: note.version };
            if (window.holdReads) await new Promise(resolve => window.heldReads.push(resolve));
            return result;
          },
          save_note: async (_id, notePath, content, expectedVersion) => {
            const note = notes.get(notePath);
            if (!note || note.version !== expectedVersion) throw Error('note conflict');
            const result = { path: notePath, content, version: String(Number(note.version) + 1) };
            notes.set(notePath, { content: result.content, version: result.version });
            return result;
          },
          set_open_notes: async (_id, paths) => {
            if (window.rejectRegistration) throw Error('registration failed');
            if (window.holdRegistration) await new Promise(resolve => { releaseRegistration = resolve; window.registrationHeld = true; });
            registrations.push([...paths]);
          },
          set_active_note: async () => {},
          media_url: async () => 'http://127.0.0.1:12345/image',
          resolve_note_link: async () => { throw Error('Not used by this check'); },
          open_workspace_file: async () => true,
          reveal_workspace_file: async () => {},
          open_external_link: async () => {},
          finish_close: async () => {},
        },
      };
    });

    await page.goto(baseUrl);
    await page.locator('.workspace-picker > summary').click();
    assert.equal(await page.locator('.workspace-option-name').filter({hasText: /^workspace$/}).count(), 2);
    assert.equal(await page.locator('.workspace-option-name').filter({hasText: /^reading-room$/}).count(), 1);
    await page.getByRole('button', { name: 'test', exact: true }).click();
    assert.equal(await page.locator('.workspace-picker > summary span').innerText(), 'test');
    assert.equal((await page.locator('.workspace-picker > summary svg').boundingBox()).width, 16);
    await page.getByRole('button', { name: 'note.md', exact: true }).waitFor();
    await page.locator('.tree-folder').waitFor();
    for (const [name, expected] of [['image.jxl','image'], ['data.jsonl','config'], ['archive.7z','archive'], ['book.djvu','book'], ['song.flac','audio'], ['clip.mkv','video'], ['note.md','markdown']]) {
      await page.locator(`button.tree-file[title="${name}"] svg.file-icon-${expected}`).waitFor();
    }
    const sidebarToggle = page.getByRole('button', { name: 'Toggle files panel' });
    const filesButton = page.getByRole('button', { name: 'Files', exact: true });
    const sidebarRect = await sidebarToggle.boundingBox();
    const activityRect = await page.locator('.activity-bar').boundingBox();
    assert.ok(Math.abs((sidebarRect.x + sidebarRect.width / 2) - (activityRect.x + activityRect.width / 2)) < 1, 'Sidebar toggle should align with activity bar');
    await filesButton.click();
    assert.equal(await page.locator('.file-tree').count(), 1, 'Files button must not close the sidebar');
    await sidebarToggle.click();
    assert.equal(await page.locator('.file-tree').count(), 0, 'Sidebar button closes the sidebar');
    await filesButton.click();
    assert.equal(await page.locator('.file-tree').count(), 1, 'Files button opens the sidebar');
    const folder = page.locator('.tree-folder').first();
    assert.equal(await folder.locator('svg').count(), 1);
    await folder.click();
    const childRow = page.locator('.tree-entry').filter({ has: page.locator('button.tree-file[title="child.md"]') });
    assert.equal(await childRow.locator('.tree-indent-guide').count(), 1, 'Nested file should show one indent guide');
    const guide = await childRow.locator('.tree-indent-guide').boundingBox();
    const folderArrow = await folder.locator('svg').boundingBox();
    assert.ok(Math.abs(guide.x - (folderArrow.x + folderArrow.width / 2)) < 1, 'Indent guide should align with parent arrow');
    const arrow = await folder.locator('svg').boundingBox();
    const fileIcon = await page.locator('button.tree-file[title="note.md"] svg').boundingBox();
    assert.ok(Math.abs(arrow.x - fileIcon.x) < 1, 'Folder arrow and file icon should align');
    assert.ok(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--file-icon-pdf').trim()));
    const colors = await page.evaluate(async () => {
      const { setFileIconColors } = await import('/src/fileIconColors.ts');
      const root = document.documentElement;
      root.style.setProperty('--bg-panel', '#211f1b'); setFileIconColors(root);
      const dark = root.style.getPropertyValue('--file-icon-pdf');
      root.style.setProperty('--bg-panel', '#f1eade'); setFileIconColors(root);
      const light = root.style.getPropertyValue('--file-icon-pdf');
      root.style.removeProperty('--bg-panel'); setFileIconColors(root);
      return { dark, light };
    });
    assert.notEqual(colors.dark, colors.light, 'File icon colors should adapt to the panel background');
    console.log('headless file icon checks passed');
  } finally {
    if (browser) await browser.close();
    vite.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
