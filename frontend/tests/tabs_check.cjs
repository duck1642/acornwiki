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
        }],
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
            workspaces: ['test'], blocked_extensions: [],
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
    await page.getByRole('button', { name: 'test', exact: true }).click();
    await page.getByRole('button', { name: 'note.md', exact: true }).waitFor();
    await page.getByRole('button', { name: 'note.md', exact: true }).click();

    const noteTab = page.locator('.document-tab').filter({ hasText: 'note.md' }).getByRole('tab');
    const otherTab = page.locator('.document-tab').filter({ hasText: 'other.md' }).getByRole('tab');
    const panelFor = notePath => page.locator(`.note-panel[data-note-path="${notePath}"]`);
    const editorFor = notePath => panelFor(notePath).locator('.cm-content');
    await editorFor('note.md').waitFor();
    await page.evaluate(() => { window.holdRegistration = true; });
    await page.getByRole('button', { name: 'other.md', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[data-note-path="note.md"] .cm-content')?.getAttribute('contenteditable') === 'false');
    await page.waitForFunction(() => window.registrationHeld);
    await page.evaluate(() => { window.holdRegistration = false; window.releaseRegistration(); });
    await editorFor('other.md').waitFor();
    await page.getByRole('button', { name: 'note.md', exact: true }).click();
    await editorFor('note.md').waitFor();
    await page.evaluate(() => { window.rejectRegistration = true; });
    await page.getByRole('button', { name: 'Navigate back' }).click();
    await page.getByText('Could not update the open note list.').waitFor();
    assert.equal(await editorFor('note.md').isVisible(), true);
    assert.equal(await page.getByRole('button', { name: 'Navigate back' }).isEnabled(), true);
    await page.evaluate(() => { window.rejectRegistration = false; });
    const expectRegistration = async paths => {
      const expected = [...paths].sort();
      await page.waitForFunction(value => {
        const current = window.openNoteRegistrations.at(-1);
        return current && JSON.stringify([...current].sort()) === JSON.stringify(value);
      }, expected);
    };

    await noteTab.waitFor();
    await editorFor('note.md').waitFor();
    await expectRegistration(['note.md']);

    await page.evaluate(() => window.externalNoteChange('note.md', '# Root\n\n<h2>Raw title</h2>\n\n## Real Markdown\n\n## [Reference heading][ref]\n\n[ref]: /docs'));
    await page.getByRole('link', { name: 'Reference heading', exact: true }).waitFor();
    await page.getByRole('link', { name: 'Real Markdown', exact: true }).click();
    assert.equal(await page.evaluate(() => getSelection()?.anchorNode?.parentElement?.closest('.cm-line')?.textContent), '## Real Markdown');
    await page.getByRole('link', { name: 'Reference heading', exact: true }).click();
    assert.equal(await page.evaluate(() => getSelection()?.anchorNode?.parentElement?.closest('.cm-line')?.textContent), '## [Reference heading][ref]');
    await page.evaluate(() => window.externalNoteChange('note.md', '# Root'));
    await page.waitForFunction(() => document.querySelector('[data-note-path="note.md"] .cm-content')?.textContent === '# Root');

    await page.evaluate(() => { window.holdReads = true; window.externalNoteChange('note.md', '# Remote A'); });
    await page.waitForFunction(() => window.heldReads.length >= 1);
    await page.evaluate(() => window.externalNoteChange('note.md', '# Remote B'));
    await page.waitForTimeout(350);
    await page.evaluate(() => window.heldReads.shift()());
    await page.waitForFunction(() => window.heldReads.length >= 1);
    await page.evaluate(() => { window.holdReads = false; window.heldReads.shift()(); });
    await page.waitForFunction(() => document.querySelector('[data-note-path="note.md"] .cm-content')?.textContent === '# Remote B');
    await page.evaluate(() => window.externalNoteChange('note.md', '# Root'));
    await page.waitForFunction(() => document.querySelector('[data-note-path="note.md"] .cm-content')?.textContent === '# Root');

    await editorFor('note.md').click();
    await page.keyboard.press('End');
    await page.keyboard.type(' root edit');
    await page.getByRole('button', { name: 'other.md', exact: true }).click();
    await otherTab.waitFor();
    await editorFor('other.md').waitFor();
    assert.equal(await editorFor('other.md').innerText(), '# Other');
    await expectRegistration(['note.md', 'other.md']);

    await editorFor('other.md').click();
    await page.keyboard.press('End');
    await page.keyboard.type(' other edit');
    await noteTab.click();
    assert.equal(await editorFor('note.md').innerText(), '# Root root edit');
    await editorFor('note.md').click();
    await page.keyboard.press('Control+z');
    assert.equal(await editorFor('note.md').innerText(), '# Root');
    assert.equal(await editorFor('other.md').innerText(), '# Other other edit');
    await page.keyboard.press('Control+y');
    assert.equal(await editorFor('note.md').innerText(), '# Root root edit');

    await page.keyboard.press('Control+s');
    await page.waitForFunction(() => window.noteDisk('note.md') === '# Root root edit');
    assert.equal(await page.evaluate(() => window.noteDisk('other.md')), '# Other');

    await editorFor('note.md').click();
    await page.keyboard.press('End');
    await page.keyboard.type(' local');
    const readsBeforeChange = await page.evaluate(() => window.noteReads.filter(path => path === 'note.md').length);
    await otherTab.click();
    await page.evaluate(() => window.externalNoteChange('note.md', '# Remote Root'));
    await page.waitForFunction((previousReads) => {
      return window.noteReads.filter(path => path === 'note.md').length > previousReads;
    }, readsBeforeChange);
    await noteTab.click();
    await panelFor('note.md').getByText('File changed externally. Your editor content was kept.').waitFor();
    assert.equal(await editorFor('note.md').innerText(), '# Root root edit local');
    assert.equal(await page.evaluate(() => window.noteDisk('note.md')), '# Remote Root');
    page.once('dialog', dialog => dialog.accept());
    await panelFor('note.md').getByRole('button', { name: 'Load disk version', exact: true }).click();
    assert.equal(await editorFor('note.md').innerText(), '# Remote Root');

    await otherTab.click();
    await page.getByRole('button', { name: 'Close other.md', exact: true }).click();
    const otherClosePrompt = panelFor('other.md').getByRole('alert').filter({ hasText: 'You have unsaved changes.' });
    await otherClosePrompt.waitFor();
    await otherClosePrompt.getByRole('button', { name: 'Cancel', exact: true }).click();
    await otherTab.waitFor();
    assert.equal(await editorFor('other.md').innerText(), '# Other other edit');

    await page.getByRole('button', { name: 'Close other.md', exact: true }).click();
    await otherClosePrompt.waitFor();
    await otherClosePrompt.getByRole('button', { name: 'Save', exact: true }).click();
    await otherTab.waitFor({ state: 'detached' });
    await page.waitForFunction(() => window.noteDisk('other.md') === '# Other other edit');
    await expectRegistration(['note.md']);

    await page.getByRole('button', { name: 'Close note.md', exact: true }).click();
    await noteTab.waitFor({ state: 'detached' });
    await expectRegistration([]);
    assert.equal(await page.evaluate(() => window.noteDisk('note.md')), '# Remote Root');
    assert.equal(await page.evaluate(() => window.noteDisk('other.md')), '# Other other edit');

    console.log('headless multi-tab checks passed');
  } finally {
    if (browser) await browser.close();
    vite.kill();
  }
})().catch(error => { console.error(error); process.exit(1); });
