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
    await page.addInitScript(() => {
      let releaseSettings;
      const settingsReady = new Promise((resolve) => { releaseSettings = resolve; });
      let holdBlocked = false;
      let releaseBlocked;
      let failNextBlocked = false;
      const notes = new Map([
        ['note.md', { content: '# Root\n\n## Child\n\n## Other', version: '1' }],
        ['other.md', { content: '# Second\n\nText', version: '1' }],
      ]);
      const items = [
        { name: 'note.md', is_directory: false, modified_time: null },
        { name: 'other.md', is_directory: false, modified_time: null },
      ];
      const snap = () => ({
        workspace_id: 'w',
        revision: 1,
        watcher_error: null,
        directories: [{ workspace_id: 'w', path: '', items, loading: false, stale: false, error: null }],
      });
      window.blockedSaveCalls = [];
      window.releaseSettings = () => releaseSettings();
      window.holdBlockedSave = () => { holdBlocked = true; };
      window.releaseBlockedSave = () => { holdBlocked = false; releaseBlocked?.(); releaseBlocked = undefined; };
      window.failNextBlockedSave = () => { failNextBlocked = true; };
      window.appearance = {
        theme: 'warm-charcoal',
        surface_mode: 'framed',
        page_width: '74ch',
        fonts: { ui: ['system-ui'], body: ['serif'], monospace: ['monospace'] },
        font_sizes: { ui: 14, body: 16, monospace: 14 },
        theme_overrides: {},
        custom_themes: {},
        file_icons: { set: 'minimal', extensions: {} },
      };
      window.pywebview = {
        state: new EventTarget(),
        api: {
          get_settings: async () => {
            await settingsReady;
            return {
              workspaces: ['test'],
              blocked_extensions: ['.exe', '.bat'],
              editor: { autosave: false, auto_reload: true, reload_notice: true },
            };
          },
          set_blocked_extensions: async (extensions) => {
            window.blockedSaveCalls.push([...extensions]);
            if (holdBlocked) await new Promise((resolve) => { releaseBlocked = resolve; });
            if (failNextBlocked) {
              failNextBlocked = false;
              throw Error('invalid extension');
            }
          },
          get_workspace_settings: async () => ({
            automatic_link_update: true,
            appearance: window.appearance,
            new_notes_folder: '.',
          }),
          set_workspace_appearance: async (id, patch) => { Object.assign(window.appearance, patch); },
          open_workspace: async () => snap(),
          get_tree: async () => snap(),
          refresh_tree: async () => snap(),
          set_open_notes: async () => {},
          media_url: async () => 'http://127.0.0.1:12345/image',
          read_note: async (id, notePath) => ({ path: notePath, ...notes.get(notePath) }),
        },
      };
    });

    await page.goto(baseUrl);

    // 1. Blocked extensions stay locked while startup settings are loading.
    await page.locator('.settings-menu > summary').click();
    await page.getByRole('button', { name: 'Open Settings' }).click();
    await page.getByRole('tab', { name: 'Application' }).click();
    const extInput = page.locator('#settings-blocked-extensions');
    await extInput.waitFor();
    assert.equal(await extInput.isDisabled(), true);
    await page.getByText('Loading blocked extensions...').waitFor();

    // Release initial settings and verify existing extensions load before edits.
    await page.evaluate(() => window.releaseSettings());
    await page.getByRole('listitem').filter({ hasText: '.exe' }).waitFor();
    await page.getByRole('listitem').filter({ hasText: '.bat' }).waitFor();
    assert.equal(await extInput.isDisabled(), false);

    // 2. Concurrent typing while saving .foo must not be cleared when .foo completes.
    await page.evaluate(() => window.holdBlockedSave());
    await extInput.fill('.foo');
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await page.waitForFunction(() => window.blockedSaveCalls.length === 1);
    assert.deepEqual(await page.evaluate(() => window.blockedSaveCalls[0]), ['.exe', '.bat', '.foo']);
    await extInput.fill('.bar');
    await page.evaluate(() => window.releaseBlockedSave());
    await page.getByRole('listitem').filter({ hasText: '.foo' }).waitFor();
    assert.equal(await extInput.inputValue(), '.bar');

    // Submit .bar and verify normal clear when input did not change during save.
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await page.getByRole('listitem').filter({ hasText: '.bar' }).waitFor();
    assert.equal(await extInput.inputValue(), '');
    assert.deepEqual(await page.evaluate(() => window.blockedSaveCalls[1]), ['.exe', '.bat', '.foo', '.bar']);

    // 3. Failed save must not add a stale chip and must preserve input.
    await page.evaluate(() => window.failNextBlockedSave());
    await extInput.fill('.bad');
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Could not save blocked extensions.' }).waitFor();
    assert.equal(await page.getByRole('listitem').filter({ hasText: '.bad' }).count(), 0);
    assert.equal(await extInput.inputValue(), '.bad');

    // 4. OutlinePanel preserves filter across hide/show, jumps to heading, and updates on tab switch.
    await page.locator('.workspace-picker > summary').click();
    await page.getByRole('button', { name: 'test', exact: true }).click();
    await page.getByRole('button', { name: 'note.md', exact: true }).waitFor();
    await page.getByRole('button', { name: 'note.md', exact: true }).click();
    await page.locator('.note-outline a').first().waitFor();
    assert.equal(await page.locator('.note-outline a').count(), 3);
    await page.getByLabel('Filter headings').fill('child');
    assert.equal(await page.locator('.note-outline a').count(), 2);
    await page.getByRole('button', { name: 'Toggle contents panel' }).click();
    assert.equal(await page.locator('.note-outline').count(), 0);
    await page.getByRole('button', { name: 'Toggle contents panel' }).click();
    await page.locator('.note-outline').waitFor();
    assert.equal(await page.getByLabel('Filter headings').inputValue(), 'child');
    assert.equal(await page.locator('.note-outline a').count(), 2);
    await page.getByLabel('Filter headings').fill('');
    await page.locator('.note-outline a', { hasText: 'Child' }).click();
    assert.equal(await page.locator('.note-panel:not(.inactive) .cm-content').evaluate((el) => el.contains(document.activeElement)), true);
    await page.getByRole('button', { name: 'other.md', exact: true }).click();
    await page.locator('.note-outline a', { hasText: 'Second' }).waitFor();
    assert.equal(await page.locator('.note-outline a').count(), 1);

    console.log('headless settings and outline checks passed');
  } finally {
    if (browser) await browser.close();
    vite.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
