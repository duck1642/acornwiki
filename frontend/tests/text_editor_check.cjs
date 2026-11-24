const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const net = require('node:net');

(async () => {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  const baseUrl = `http://127.0.0.1:${port}`;
  const vite = spawn(
    process.execPath,
    [path.resolve(__dirname, '../node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', String(port), '--strictPort'],
    { cwd: path.resolve(__dirname, '..'), stdio: 'ignore' },
  );
  let browser;
  try {
    for (let attempt = 0; ; attempt++) {
      try { if ((await fetch(baseUrl)).ok) break; } catch {}
      if (attempt >= 100 || vite.exitCode !== null) throw Error('Vite did not start');
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    browser = await chromium.launch({
      headless: true,
      executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    });
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(err));
    await page.addInitScript(() => {
      const state = new EventTarget();
      const signal = () => state.dispatchEvent(new CustomEvent('change', { detail: { key: 'note_revision' } }));
      const notes = new Map([
        ['note.md', { content: '# Guide\n\n[Script](helper.py)\n\n[Manual](manual.pdf)\n\n' + 'longword '.repeat(80), version: '1', has_bom: false }],
      ]);
      const textFiles = new Map([
        ['helper.py', { ok: true, content: "def greet():\r\n    return 'hi'\r\n", version: '1', has_bom: true, size_bytes: 30 }],
        ['SCRIPT.PY', { ok: true, content: 'value = 42\n', version: '1', has_bom: false, size_bytes: 11 }],
        ['CMakeLists.txt', { ok: true, content: 'cmake_minimum_required(VERSION 3.20)\n', version: '1', has_bom: false, size_bytes: 37 }],
        ['run.bat', { ok: true, content: '@echo off\r\necho hello\r\n', version: '1', has_bom: false, size_bytes: 22 }],
        ['blob.dat', { ok: false, reason: 'binary', size_bytes: 64, max_bytes: 2 * 1024 * 1024 }],
        ['big.log', { ok: false, reason: 'too_large', size_bytes: 3 * 1024 * 1024, max_bytes: 2 * 1024 * 1024 }],
      ]);
      const items = [
        { name: 'note.md', is_directory: false, modified_time: null },
        { name: 'helper.py', is_directory: false, modified_time: null },
        { name: 'SCRIPT.PY', is_directory: false, modified_time: null },
        { name: 'CMakeLists.txt', is_directory: false, modified_time: null },
        { name: 'run.bat', is_directory: false, modified_time: null },
        { name: 'blob.dat', is_directory: false, modified_time: null },
        { name: 'big.log', is_directory: false, modified_time: null },
        { name: 'manual.pdf', is_directory: false, modified_time: null },
        { name: 'image.svg', is_directory: false, modified_time: null },
        { name: 'book.djvu', is_directory: false, modified_time: null },
        { name: 'photo.jxl', is_directory: false, modified_time: null },
      ];
      const snap = () => ({
        workspace_id: 'w',
        revision: 1,
        watcher_error: null,
        directories: [{ workspace_id: 'w', path: '', items, loading: false, stale: false, error: null }],
      });
      let holdTextSave = false;
      let releaseTextSave;
      let holdTextReadPath = null;
      let releaseTextRead;
      let failNextClearOpenFiles = false;
      window.openedExternal = [];
      window.revealedExternal = [];
      window.savedTextCalls = [];
      window.openFilesCalls = [];
      window.holdTextSave = () => { holdTextSave = true; };
      window.releaseTextSave = () => { holdTextSave = false; releaseTextSave?.(); releaseTextSave = undefined; };
      window.holdTextRead = (p) => { holdTextReadPath = p; };
      window.releaseTextRead = () => { holdTextReadPath = null; releaseTextRead?.(); releaseTextRead = undefined; };
      window.failNextClearOpenFiles = () => { failNextClearOpenFiles = true; };
      window.externalText = (filePath, content, notify = true) => {
        const entry = textFiles.get(filePath);
        entry.content = content;
        entry.version = String(Number(entry.version) + 1);
        if (notify) signal();
      };
      window.rejectText = (filePath) => textFiles.set(filePath, { ok: false, reason: 'too_large', size_bytes: 3 * 1024 * 1024, max_bytes: 2 * 1024 * 1024 });
      window.requestClose = () => state.dispatchEvent(new CustomEvent('change', { detail: { key: 'close_request' } }));
      window.appearance = {
        theme: 'warm-charcoal',
        surface_mode: 'framed',
        page_width: '74ch',
        fonts: { ui: ['system-ui'], body: ['serif'], monospace: ['monospace'] },
        font_sizes: { ui: 14, body: 16, monospace: 14 },
        font_weights: { ui: 400, body: 400, monospace: 400 },
        theme_overrides: {},
        custom_themes: {},
        file_icons: { set: 'minimal', extensions: {} },
      };
      window.pywebview = {
        state,
        api: {
          get_settings: async () => ({
            workspaces: ['test'],
            blocked_extensions: ['.exe', '.bat', '.dat'],
            editor: { autosave: false, auto_reload: true, reload_notice: true },
          }),
          get_workspace_settings: async () => ({
            automatic_link_update: true,
            appearance: window.appearance,
            new_notes_folder: '.',
          }),
          set_workspace_appearance: async (id, patch) => { Object.assign(window.appearance, patch); },
          open_workspace: async () => snap(),
          get_tree: async () => snap(),
          refresh_tree: async () => snap(),
          set_open_files: async (id, paths) => {
            if (failNextClearOpenFiles && paths.length === 0) {
              failNextClearOpenFiles = false;
              throw Error('cannot clear');
            }
            window.openFilesCalls.push([...paths]);
          },
          finish_close: async () => { window.didClose = true; },
          media_url: async () => 'http://127.0.0.1:12345/image',
          resolve_note_link: async (id, note, href) => {
            const [targetPath, fragment = ''] = href.split('#');
            return { path: targetPath, fragment };
          },
          open_workspace_file: async (id, filePath) => {
            window.openedExternal.push(filePath);
            return !['.exe', '.bat', '.dat'].some((ext) => filePath.toLowerCase().endsWith(ext));
          },
          reveal_workspace_file: async (id, filePath) => {
            window.revealedExternal.push(filePath);
          },
          read_note: async (id, notePath) => ({ path: notePath, ...notes.get(notePath) }),
          save_note: async (id, notePath, content, expected, hasBom = false) => {
            const entry = notes.get(notePath);
            if (!entry || entry.version !== expected) throw Error('conflict');
            entry.content = content;
            entry.has_bom = hasBom;
            entry.version = String(Number(entry.version) + 1);
            return { path: notePath, ...entry };
          },
          read_text_file: async (id, filePath) => {
            if (holdTextReadPath === filePath) {
              await new Promise((resolve) => { releaseTextRead = resolve; });
            }
            return { path: filePath, ...textFiles.get(filePath) };
          },
          save_text_file: async (id, filePath, content, expected, hasBom = false) => {
            if (holdTextSave) await new Promise((resolve) => { releaseTextSave = resolve; });
            const entry = textFiles.get(filePath);
            if (!entry || !entry.ok || entry.version !== expected) throw Error('conflict');
            entry.content = content;
            entry.has_bom = hasBom;
            entry.version = String(Number(entry.version) + 1);
            window.savedTextCalls.push({ filePath, content, hasBom });
            return { path: filePath, content, version: entry.version, has_bom: hasBom };
          },
        },
      };
    });

    await page.goto(baseUrl);
    await page.locator('.workspace-picker > summary').click();
    await page.getByRole('button', { name: 'test', exact: true }).click();
    await page.getByRole('button', { name: 'helper.py', exact: true }).waitFor();

    // 1. Open Python file in TextEditor: line numbers ON, word wrap OFF, Python highlighting loaded, Contents hidden.
    await page.getByRole('button', { name: 'helper.py', exact: true }).click();
    const pyPanel = page.locator('.text-editor-panel[data-note-path="helper.py"]:not(.inactive)');
    await pyPanel.waitFor();
    assert.equal(await pyPanel.locator('.text-editor-lang').innerText(), 'Python');
    assert.equal(await pyPanel.locator('.cm-lineNumbers').count(), 1);
    assert.equal(await pyPanel.locator('.cm-lineWrapping').count(), 0);
    assert.equal(await page.locator('.note-outline').count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Toggle contents panel' }).isDisabled(), true);
    // Lazy-loaded Python syntax highlighting produces styled spans inside .cm-content.
    await pyPanel.locator('.cm-content span[class^="ͼ"]').first().waitFor();
    // Opaque sticky gutter background (#4) and selected tree item accent color (#6).
    const gutterBg = await pyPanel.locator('.cm-gutters').evaluate((el) => getComputedStyle(el).backgroundColor);
    assert.notEqual(gutterBg, 'rgba(0, 0, 0, 0)');
    await page.mouse.move(600, 400);
    const pyTreeColor = await page.getByRole('button', { name: 'helper.py', exact: true }).evaluate((el) => getComputedStyle(el).color);
    const mdTreeColor = await page.getByRole('button', { name: 'note.md', exact: true }).evaluate((el) => getComputedStyle(el).color);
    assert.notEqual(pyTreeColor, mdTreeColor);
    // Open files registration was sent to the backend.
    assert.ok((await page.evaluate(() => window.openFilesCalls)).some((list) => list.includes('helper.py')));

    // 2. Edit and save Python file: preserves CRLF and BOM flag, watches open text file, handles external reload.
    await pyPanel.locator('.cm-content').click();
    await page.keyboard.press('Control+End');
    await page.keyboard.type('x = 1');
    await page.keyboard.press('Control+s');
    await page.waitForFunction(() => window.savedTextCalls.length === 1);
    const savedCall = await page.evaluate(() => window.savedTextCalls[0]);
    assert.equal(savedCall.filePath, 'helper.py');
    assert.equal(savedCall.hasBom, true);
    assert.equal(savedCall.content, "def greet():\r\n    return 'hi'\r\nx = 1");
    await page.evaluate(() => window.externalText('helper.py', "print('reloaded')\r\n"));
    await pyPanel.getByText('File changed externally and was reloaded.').waitFor();
    assert.equal((await pyPanel.locator('.cm-content').innerText()).trim(), "print('reloaded')");

    // 3. Open Markdown tab alongside Python tab and verify editor-type-scoped View toggles.
    await page.getByRole('button', { name: 'note.md', exact: true }).click({ modifiers: ['Control'] });
    const mdPanel = page.locator('.note-panel[data-note-path="note.md"]:not(.inactive)');
    await mdPanel.waitFor();
    assert.equal(await mdPanel.locator('.cm-lineNumbers').count(), 0);
    assert.equal(await mdPanel.locator('.cm-lineWrapping').count(), 1);
    assert.equal(await page.locator('.note-outline').count(), 1);

    // Toggle Line numbers ON for Markdown, verify Text tab stays unaffected when toggling Word wrap ON for Text.
    await page.locator('.view-menu > summary').click();
    await page.locator('.view-menu-content').getByRole('button', { name: 'Line numbers' }).click();
    assert.equal(await mdPanel.locator('.cm-lineNumbers').count(), 1);

    await page.locator('.document-tab-select', { hasText: 'helper.py' }).click();
    await page.locator('.view-menu > summary').click();
    await page.locator('.view-menu-content').getByRole('button', { name: 'Word wrap' }).click();
    assert.equal(await pyPanel.locator('.cm-lineWrapping').count(), 1);
    // Switch back to Markdown and turn Word wrap OFF; Python must keep Word wrap ON and Markdown must not overflow .note-sheet (#4).
    await page.locator('.document-tab-select', { hasText: 'note.md' }).click();
    await page.locator('.view-menu > summary').click();
    await page.locator('.view-menu-content').getByRole('button', { name: 'Word wrap' }).click();
    assert.equal(await mdPanel.locator('.cm-lineWrapping').count(), 0);
    const mdOverflow = await mdPanel.evaluate((panel) => {
      const sheet = panel.querySelector('.note-sheet').getBoundingClientRect();
      const scroller = panel.querySelector('.cm-scroller');
      return {
        sheetRight: sheet.right,
        scrollerRight: scroller.getBoundingClientRect().right,
        overflowX: getComputedStyle(scroller).overflowX,
      };
    });
    assert.equal(mdOverflow.overflowX, 'auto');
    assert.ok(mdOverflow.scrollerRight <= mdOverflow.sheetRight + 1);
    await page.locator('.document-tab-select', { hasText: 'helper.py' }).click();
    assert.equal(await pyPanel.locator('.cm-lineWrapping').count(), 1);

    // 4. Settings tab disables Line numbers and Word wrap View toggles and displays updated Blocked extensions copy.
    await page.locator('.settings-menu > summary').click();
    await page.getByRole('button', { name: 'Open Settings' }).click();
    await page.locator('.view-menu > summary').click();
    assert.equal(await page.locator('.view-menu-content').getByRole('button', { name: 'Line numbers' }).isDisabled(), true);
    assert.equal(await page.locator('.view-menu-content').getByRole('button', { name: 'Word wrap' }).isDisabled(), true);
    await page.locator('.view-menu > summary').click();
    await page.getByRole('tab', { name: 'Application' }).click();
    await page.getByText('Plain UTF-8 text files can still be edited safely inside acornwiki.').waitFor();

    // 5. Blocked text script (.bat) opens safely in TextEditor without calling open_workspace_file.
    await page.getByRole('button', { name: 'run.bat', exact: true }).click({ modifiers: ['Control'] });
    await page.locator('.text-editor-panel[data-note-path="run.bat"]:not(.inactive)').waitFor();
    assert.deepEqual(await page.evaluate(() => window.openedExternal), []);

    // 6. Binary and oversized files show actionable banner instead of opening broken tabs, and fallback respects blocked_extensions.
    await page.getByRole('button', { name: 'big.log', exact: true }).click();
    const banner = page.locator('.workspace-notice-banner');
    await banner.waitFor();
    assert.ok((await banner.innerText()).includes('exceeds the 2 MB text editor limit'));
    assert.equal(await page.locator('.document-tab-select', { hasText: 'big.log' }).count(), 0);
    await banner.getByRole('button', { name: 'Dismiss' }).click();
    assert.equal(await banner.count(), 0);

    await page.getByRole('button', { name: 'blob.dat', exact: true }).click();
    await banner.waitFor();
    assert.ok((await banner.innerText()).includes('binary data'));
    page.once('dialog', (dialog) => dialog.accept());
    await banner.getByRole('button', { name: 'Open with default app' }).click();
    await page.waitForFunction(() => window.revealedExternal.includes('blob.dat'));
    assert.deepEqual(await page.evaluate(() => window.openedExternal), ['blob.dat']);

    // 7. Markdown local links share the same routing: [Script](helper.py) activates TextEditor, [Manual](manual.pdf) opens externally.
    await page.locator('.document-tab-select', { hasText: 'note.md' }).click();
    await mdPanel.getByRole('button', { name: 'Read', exact: true }).click();
    await mdPanel.getByRole('link', { name: 'Script', exact: true }).click();
    await pyPanel.waitFor();
    await page.locator('.document-tab-select', { hasText: 'note.md' }).click();
    await mdPanel.getByRole('link', { name: 'Manual', exact: true }).click();
    await page.waitForFunction(() => window.openedExternal.includes('manual.pdf'));

    // Known media go directly to the default app, even when their contents are UTF-8.
    for (const name of ['image.svg', 'book.djvu', 'photo.jxl']) {
      await page.getByRole('button', { name, exact: true }).click();
      await page.waitForFunction((file) => window.openedExternal.includes(file), name);
    }

    // A history entry that can no longer be read must not block earlier pages.
    await page.reload();
    await page.locator('.workspace-picker > summary').click();
    await page.getByRole('button', { name: 'test', exact: true }).click();
    await page.getByRole('button', { name: 'note.md', exact: true }).click();
    await page.getByRole('button', { name: 'helper.py', exact: true }).click();
    await page.getByRole('button', { name: 'run.bat', exact: true }).click();
    await page.locator('.text-editor-panel[data-note-path="run.bat"]:not(.inactive)').waitFor();
    await page.evaluate(() => window.rejectText('helper.py'));
    await page.getByRole('button', { name: 'Navigate back' }).last().click();
    await page.locator('.workspace-notice-banner').waitFor();
    await page.getByRole('button', { name: 'Navigate back' }).last().click();
    await page.locator('.note-panel[data-note-path="note.md"]:not(.inactive)').waitFor();

    // 8. Uppercase extension and CMakeLists.txt language detection (#5).
    await page.getByRole('button', { name: 'SCRIPT.PY', exact: true }).click({ modifiers: ['Control'] });
    const upperPyPanel = page.locator('.text-editor-panel[data-note-path="SCRIPT.PY"]:not(.inactive)');
    await upperPyPanel.waitFor();
    assert.equal(await upperPyPanel.locator('.text-editor-lang').innerText(), 'Python');
    await page.getByRole('button', { name: 'CMakeLists.txt', exact: true }).click();
    const cmakePanel = page.locator('.text-editor-panel[data-note-path="CMakeLists.txt"]:not(.inactive)');
    await cmakePanel.waitFor();
    assert.equal(await cmakePanel.locator('.text-editor-lang').innerText(), 'CMake');

    // 9. Clean file Ctrl+S after silent external edit auto-reloads cleanly: resets undo history while preserving scroll (#7, #18).
    const longLines = Array.from({ length: 120 }, (_, i) => `set(VAR_${i} "value_${i}")`).join('\n');
    await page.evaluate((text) => window.externalText('CMakeLists.txt', text, true), longLines);
    await cmakePanel.getByText('File changed externally and was reloaded.').waitFor();
    await cmakePanel.locator('.cm-content').click();
    await page.keyboard.press('Control+End');
    await page.keyboard.type('\n# saved edit');
    await page.keyboard.press('Control+s');
    await page.waitForFunction(() => window.savedTextCalls.some((c) => c.filePath === 'CMakeLists.txt'));
    await cmakePanel.locator('.cm-scroller').evaluate((el) => { el.scrollTop = 420; });
    const scrollBeforeReload = await cmakePanel.locator('.cm-scroller').evaluate((el) => el.scrollTop);
    await page.evaluate((text) => window.externalText('CMakeLists.txt', text, false), `${longLines}\n# silent update`);
    await page.keyboard.press('Control+s');
    await cmakePanel.getByText('File changed externally and was reloaded.').waitFor();
    assert.ok((await cmakePanel.locator('.cm-content').innerText()).includes('# silent update'));
    // Undo history was explicitly cleared on external reload, so Ctrl+Z must not revert the reloaded text.
    await page.keyboard.press('Control+z');
    assert.ok((await cmakePanel.locator('.cm-content').innerText()).includes('# silent update'));
    const scrollAfterReload = await cmakePanel.locator('.cm-scroller').evaluate((el) => el.scrollTop);
    assert.ok(Math.abs(scrollAfterReload - scrollBeforeReload) < 40, `Expected scroll near ${scrollBeforeReload}, got ${scrollAfterReload}`);

    // 10. Conflict action buttons disable while overwrite save is in flight (#12).
    await cmakePanel.locator('.cm-content').click();
    await page.keyboard.press('Control+End');
    await page.keyboard.type('# local');
    await page.evaluate(() => window.externalText('CMakeLists.txt', 'project(conflict)\n', true));
    await cmakePanel.getByText('File changed externally. Your editor content was kept.').waitFor();
    await page.evaluate(() => window.holdTextSave());
    page.once('dialog', (dialog) => dialog.accept());
    await cmakePanel.getByRole('button', { name: 'Overwrite with editor version' }).click();
    await page.waitForFunction(() => document.querySelector('.text-editor-panel[data-note-path="CMakeLists.txt"] .note-conflict button')?.disabled === true);
    await page.evaluate(() => window.releaseTextSave());
    await cmakePanel.locator('.note-conflict').waitFor({ state: 'detached' });

    // 11. Settings tab does not race with delayed read_text_file (#11).
    await page.locator('.settings-menu > summary').click();
    await page.getByRole('button', { name: 'Open Settings' }).click();
    await page.evaluate(() => window.holdTextRead('SCRIPT.PY'));
    const delayedClick = page.getByRole('button', { name: 'SCRIPT.PY', exact: true }).click({ modifiers: ['Control'] });
    await page.waitForTimeout(50);
    await page.getByRole('button', { name: 'Close Settings', exact: true }).click({ force: true });
    await page.evaluate(() => window.releaseTextRead());
    await delayedClick;
    await page.locator('.text-editor-panel[data-note-path="SCRIPT.PY"]:not(.inactive)').waitFor();

    // 12. Removing an unavailable history entry collapses adjacent duplicates (#15).
    await page.reload();
    await page.locator('.workspace-picker > summary').click();
    await page.getByRole('button', { name: 'test', exact: true }).click();
    await page.getByRole('button', { name: 'note.md', exact: true }).click();
    await page.getByRole('button', { name: 'helper.py', exact: true }).click();
    await page.getByRole('button', { name: 'note.md', exact: true }).click();
    const freshMdPanel = page.locator('.note-panel[data-note-path="note.md"]:not(.inactive)');
    await freshMdPanel.waitFor();
    await page.evaluate(() => window.rejectText('helper.py'));
    await freshMdPanel.getByRole('button', { name: 'Navigate back' }).click();
    await page.locator('.workspace-notice-banner').waitFor();
    assert.equal(await freshMdPanel.getByRole('button', { name: 'Navigate back' }).isDisabled(), true);

    // 13. Bulk close surfaces clear error when set_open_files([]) fails (#16).
    await page.evaluate(() => window.failNextClearOpenFiles());
    await page.evaluate(() => window.requestClose());
    await page.getByText('The open file list could not be cleared. Open tabs are still open.').waitFor();

    assert.equal(pageErrors.length, 0, `Unexpected page errors: ${pageErrors.map((e) => e.message).join('; ')}`);
    console.log('headless text editor checks passed');
  } finally {
    if (browser) await browser.close();
    vite.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
