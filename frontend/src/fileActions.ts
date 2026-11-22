/** Open a workspace file, or offer to show a blocked file in the file manager. */
export async function openWorkspaceFile(workspaceId: string, path: string): Promise<void> {
  const api = window.pywebview?.api
  if (!api) throw new Error('Backend unavailable')
  const opened = await api.open_workspace_file(workspaceId, path)
  if (!opened && window.confirm(`This file type is blocked from opening: ${path}\n\nShow it in the file manager?`)) {
    await api.reveal_workspace_file(workspaceId, path)
  }
}
