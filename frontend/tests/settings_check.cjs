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
      let releaseSettings;
      const settingsReady = new Promise((resolve) => { releaseSettings = resolve; });
      let holdBlocked = false;
      let releaseBlocked;
      let failNextBlocked = false;
      const notes = new Map([
        ['note.md', { content: '# Root\n\n## Child\n\n## Other\n\n```python\nprint(\'hi\')\n```', version: '1' }],
        ['other.md', { content: '# Second\n\n- First item\n-\n\nParagraph\n-', version: '1' }],
        ['regressions.md', {
          content: [
            'Paragraph',
            '- item',
            '---',
            '',
            'Title',
            '---',
            '',
            'Top title',
            '===',
            '',
            '> ## Same',
            '',
            '- ## Same',
            '',
            '## Same',
            '',
            'Same',
            '---',
            '',
            '```c++',
            'int x = 1;',
            '```',
            '',
            '```c#',
            'var x = 1;',
            '```',
            '',
            '```f#',
            'let x = 1',
            '```',
            '',
            '```plaintext',
            '\\section{not latex}',
            '```',
          ].join('\n'),
          version: '1',
        }],
        ['crlf.md', { content: 'line1\r\nline2\r\nline3\r\nline4', version: '1' }],
        ['parser-edge.md', { content: '# Start\n\nAlpha\n-\tBeta\n---\n\n<pre>raw line one\nraw line two</pre>', version: '1' }],
      ]);
      const items = [
        { name: 'note.md', is_directory: false, modified_time: null },
        { name: 'other.md', is_directory: false, modified_time: null },
        { name: 'regressions.md', is_directory: false, modified_time: null },
        { name: 'crlf.md', is_directory: false, modified_time: null },
        { name: 'parser-edge.md', is_directory: false, modified_time: null },
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
        font_weights: { ui: 400, body: 400, monospace: 400 },
        theme_overrides: {},
        custom_themes: {},
        file_icons: { set: 'minimal', extensions: {} },
      };
      window.copiedText = '';
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: async (text) => { window.copiedText = text; } },
      });
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
    // A paragraph followed by a single dash is a valid Setext heading; list items stay out of Contents.
    assert.deepEqual(await page.locator('.note-outline a').allInnerTexts(), ['Second', 'Paragraph']);

    // 5. Editor features: line numbers toggle, fold gutter, Ctrl+B shortcut, click-below focus, Read code highlighting + Copy.
    await page.getByRole('button', { name: 'note.md', exact: true }).click();
    await page.locator('.note-panel:not(.inactive) .cm-content').waitFor();
    assert.equal(await page.locator('.note-panel:not(.inactive) .cm-lineNumbers').count(), 0);
    assert.equal(await page.locator('.note-panel:not(.inactive) .cm-foldGutter').count(), 1);
    await page.locator('.view-menu > summary').click();
    await page.locator('.view-menu-content').getByRole('button', { name: 'Line numbers' }).click();
    assert.equal(await page.locator('.note-panel:not(.inactive) .cm-lineNumbers').count(), 1);
    // Click empty area in .note-scroll below editor text to focus editor at end.
    await page.locator('.note-panel:not(.inactive) .note-scroll').click({ position: { x: 20, y: 500 } });
    assert.equal(await page.locator('.note-panel:not(.inactive) .cm-content').evaluate((el) => el.contains(document.activeElement)), true);
    await page.keyboard.press('Enter');
    await page.keyboard.type('word');
    await page.keyboard.press('Shift+Home');
    await page.keyboard.press('Control+b');
    assert.ok((await page.locator('.note-panel:not(.inactive) .cm-content').innerText()).includes('**word**'));
    // Read mode highlights Python code block and copies code via Copy button.
    await page.getByRole('button', { name: 'Read', exact: true }).click();
    await page.locator('.read-code-block pre code .tok-string').waitFor();
    await page.locator('.read-code-copy').click();
    await page.locator('.read-code-copy', { hasText: 'Copied' }).waitFor();
    assert.equal(await page.evaluate(() => window.copiedText), "print('hi')");

    // 6. Typography font weight selector persists and updates CSS variable.
    await page.locator('.settings-menu > summary').click();
    await page.getByRole('button', { name: 'Open Settings' }).click();
    await page.getByRole('tab', { name: 'Workspace' }).click();
    await page.locator('.setting-select > summary[aria-label="Reading font weight"]').click();
    await page.getByRole('button', { name: 'Medium', exact: true }).click();
    await page.waitForFunction(() => window.appearance.font_weights.body === 500);
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--font-weight-body').trim()), '500');

    // 7. Markdown regressions: no Setext block swallowing, nested heading jumpToHeading, code language labels/highlighting.
    await page.getByRole('button', { name: 'regressions.md', exact: true }).click();
    await page.locator('.note-panel[data-note-path="regressions.md"]:not(.inactive) .cm-content').waitFor();
    assert.deepEqual(await page.locator('.note-outline a').allInnerTexts(), ['Title', 'Top title', 'Same', 'Same']);
    await page.locator('.note-outline a', { hasText: 'Top title' }).click();
    assert.equal((await page.locator('.note-panel[data-note-path="regressions.md"] .cm-activeLine').innerText()).trim(), 'Top title');
    await page.locator('.note-outline a', { hasText: 'Title' }).first().click();
    assert.equal((await page.locator('.note-panel[data-note-path="regressions.md"] .cm-activeLine').innerText()).trim(), 'Title');
    // Jump from Contents in Source mode should focus editor on the top-level "## Same" despite quoted/list "## Same".
    await page.getByRole('link', { name: 'Same', exact: true }).first().click();
    const activeLineText = await page.locator('.note-panel[data-note-path="regressions.md"] .cm-activeLine').innerText();
    assert.equal(activeLineText.trim(), '## Same');
    await page.getByRole('link', { name: 'Same', exact: true }).last().click();
    assert.equal((await page.locator('.note-panel[data-note-path="regressions.md"] .cm-activeLine').innerText()).trim(), 'Same');
    await page.locator('.note-panel[data-note-path="regressions.md"]').getByRole('button', { name: 'Read', exact: true }).click();
    const readPanel = page.locator('.note-panel[data-note-path="regressions.md"] .note-read');
    assert.equal(await readPanel.locator('hr').count(), 1);
    assert.equal(await readPanel.getByRole('heading', { name: 'Title', exact: true, level: 2 }).count(), 1);
    assert.equal(await readPanel.getByRole('heading', { name: 'Top title', exact: true, level: 1 }).count(), 1);
    assert.equal(await readPanel.getByRole('heading', { name: 'Same', exact: true, level: 2 }).last().getAttribute('id'), 'same-3');
    assert.equal(await readPanel.locator('ul li').first().innerText(), 'item');
    assert.deepEqual(
      await readPanel.locator('.read-code-lang').allTextContents(),
      ['c++', 'c#', 'f#', 'plaintext'],
    );
    // Wait for C++, C#, F# syntax highlighting and verify plaintext is NOT highlighted as LaTeX.
    await readPanel.locator('.read-code-block').nth(0).locator('pre code .tok-typeName, pre code .tok-keyword, pre code .tok-number').first().waitFor();
    await readPanel.locator('.read-code-block').nth(1).locator('pre code .tok-keyword, pre code .tok-number').first().waitFor();
    await readPanel.locator('.read-code-block').nth(2).locator('pre code .tok-keyword, pre code .tok-number').first().waitFor();
    await page.waitForTimeout(150);
    assert.equal(await readPanel.locator('.read-code-block').nth(3).locator('pre code span[class^="tok-"]').count(), 0);

    // 8. CRLF multiline shortcuts (Ctrl+B toggle and Ctrl+K link wrap) do not miscalculate offsets or throw.
    await page.getByRole('button', { name: 'crlf.md', exact: true }).click();
    const crlfEditor = page.locator('.note-panel[data-note-path="crlf.md"]:not(.inactive) .cm-content');
    await crlfEditor.waitFor();
    await crlfEditor.click();
    await page.keyboard.press('Control+a');
    await page.keyboard.press('Control+b');
    assert.equal(await crlfEditor.innerText(), '**line1\nline2\nline3\nline4**');
    // Toggle bold back off while selection is preserved across all 4 CRLF lines.
    await page.keyboard.press('Control+b');
    assert.equal(await crlfEditor.innerText(), 'line1\nline2\nline3\nline4');
    // Wrap all 4 CRLF lines as a link and replace selected "url" by typing.
    await page.keyboard.press('Control+k');
    await page.keyboard.type('https://example.com');
    assert.equal(await crlfEditor.innerText(), '[line1\nline2\nline3\nline4](https://example.com)');

    // Marked and CodeMirror can parse Setext differently; navigation follows the rendered heading.
    await page.getByRole('button', { name: 'parser-edge.md', exact: true }).click();
    const edgePanel = page.locator('.note-panel[data-note-path="parser-edge.md"]');
    await edgePanel.locator('.cm-content').waitFor();
    await page.locator('.note-outline a', { hasText: 'Alpha' }).click();
    assert.equal((await edgePanel.locator('.cm-activeLine').innerText()).trim(), 'Alpha');
    await edgePanel.getByRole('button', { name: 'Read', exact: true }).click();
    await edgePanel.locator('.read-code-copy').click();
    assert.equal(await page.evaluate(() => window.copiedText), 'raw line one\nraw line two');
    assert.equal(pageErrors.length, 0, `Unexpected page errors: ${pageErrors.map((e) => e.message).join('; ')}`);

    console.log('headless settings and outline checks passed');
  } finally {
    if (browser) await browser.close();
    vite.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
